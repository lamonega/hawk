"""LinkedIn search, job scraping, Easy Apply autofill engine, and recruiter outreach."""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any
from urllib.parse import quote

from loguru import logger

from hawk.browser import DEFAULT_NAV_TIMEOUT_MS, browser
from hawk.config import Settings, UserProfile, get_settings, load_profile, match_field

# ── 1. Search & Filter Constants ──────────────────────────────────────────────
LINKEDIN_JOBS_SEARCH_URL: str = "https://www.linkedin.com/jobs/search/?"
DEFAULT_SEARCH_LOCATION: str = "remote"
EASY_APPLY_SEARCH_PARAM: str = "f_LF=f_AL"

EXPERIENCE_MAP: dict[str, str] = {
    "internship": "1",
    "entry": "2",
    "associate": "3",
    "mid_senior_level": "4",
    "director": "5",
    "executive": "6",
}

JOB_TYPE_MAP: dict[str, str] = {
    "full_time": "F",
    "part_time": "P",
    "contract": "C",
    "temporary": "T",
    "internship": "I",
}

DATE_FILTER_MAP: dict[str, str] = {
    "day": "r86400",
    "week": "r604800",
    "month": "r2592000",
}

# ── 2. CSS Selectors ──────────────────────────────────────────────────────────
EASY_APPLY_BUTTON_SELECTORS: list[str] = [
    ".jobs-apply-button--top-card button",
    "button.jobs-apply-button",
    "button[aria-label*='Easy Apply']",
    "button[aria-label*='Solicitud sencilla']",
    "button[aria-label*='Aplicar']",
    "button[data-testid*='apply-button']",
    "button[data-test-easy-apply-btn]",
]

CONNECT_BUTTON_SELECTORS: str = 'button:has-text("Conectar"), button:has-text("Connect")'
ADD_NOTE_BUTTON_SELECTORS: str = 'button:has-text("Añadir nota"), button:has-text("Add a note")'
SEND_BUTTON_SELECTORS: str = 'button:has-text("Enviar"), button:has-text("Send")'
NOTE_TEXTAREA_SELECTOR: str = 'textarea[name="message"]'

# ── 3. UI Text & Action Indicators ────────────────────────────────────────────
EASY_APPLY_TEXT_INDICATORS: tuple[str, ...] = (
    "easy apply",
    "solicitud sencilla",
    "aplicación sencilla",
)

FOLLOW_TEXT_INDICATORS: tuple[str, ...] = (
    "follow",
    "seguir",
)

ACTION_SUBMIT: str = "submit"
ACTION_REVIEW: str = "review"
ACTION_NEXT: str = "next"

BUTTON_ACTIONS: list[tuple[str, tuple[str, ...]]] = [
    (ACTION_SUBMIT, ("submit", "enviar solicitud", "enviar candidatura")),
    (ACTION_REVIEW, ("review", "revisar")),
    (ACTION_NEXT, ("next", "siguiente", "continue", "continuar", "avançar")),
]

AFFIRMATIVE_VALUES: tuple[str, ...] = ("yes", "sí", "si", "true", "1")
NEGATIVE_VALUES: tuple[str, ...] = ("no", "false", "0")

# ── 4. Status & Result Constants ──────────────────────────────────────────────
STATUS_FILLED: str = "filled"
STATUS_SUBMITTED: str = "submitted"
STATUS_ADVANCED: str = "advanced"
STATUS_READY_TO_SUBMIT_DRY_RUN: str = "ready_to_submit_dry_run_blocked"
STATUS_NO_ADVANCE_BUTTON: str = "no_advance_button"
STATUS_ERROR: str = "error"

RES_CLICKED_EASY_APPLY: str = "clicked_easy_apply"
RES_ALREADY_APPLIED: str = "already_applied"
RES_CONNECTION_SENT_WITH_NOTE: str = "connection_sent_with_note"
RES_CONNECTION_SENT: str = "connection_sent"

# ── 5. Recruiter Pitch Constants ──────────────────────────────────────────────
MAX_NOTE_LENGTH: int = 299
MAX_PITCH_SKILLS: int = 3
DEFAULT_CANDIDATE_NAME: str = "Candidate"
AUTO_LANGUAGE: str = "auto"
SPANISH_LANGUAGES: tuple[str, ...] = ("es", "spanish", "español")
SPANISH_DETECTION_WORDS: tuple[str, ...] = (
    "ingeniero",
    "desarrollador",
    "remoto",
    "sistemas",
    "analista",
    "diseñador",
    "consultor",
)

_PITCH_NOTE_TEMPLATE_ES: str = (
    "{greeting} me postulé a {job_title} en {company}.{skills_part} "
    "Me encantaría conectar y conversar sobre cómo puedo sumar al equipo. ¡Saludos, {name}!"
)
_PITCH_NOTE_TEMPLATE_EN: str = (
    "{greeting} I applied for the {job_title} role at {company}.{skills_part} "
    "I'd love to connect and discuss how I can contribute! Best, {name}"
)
_PITCH_SKILLS_PART_ES: str = " Con experiencia en {skills},"
_PITCH_SKILLS_PART_EN: str = " With a background in {skills},"

# ── 6. Interaction & Field Response Markers ───────────────────────────────────
FIELD_RESUME: str = "resume"
_MARKER_UPLOADED: str = "uploaded"
_MARKER_SELECTED: str = "selected"
_MARKER_TYPED: str = "typed"

_CHECKBOX_UNCHECKED_VALUES: frozenset[str] = frozenset({"false", "0", ""})

# ── 7. JavaScript DOM Extraction Scripts ──────────────────────────────────────
MAX_JOB_DESCRIPTION_LENGTH: int = 5000

_EXTRACT_JOBS_LIST_JS: str = r"""
() => {
    const results = [];
    const seen = new Set();

    // Strategy 1: Standard job card selectors
    const cards = document.querySelectorAll(
        '.job-card-container, .jobs-search-results__list-item, [data-job-id], [data-occludable-job-id]'
    );
    for (const card of cards) {
        const id = card.getAttribute('data-job-id') ||
                   card.getAttribute('data-occludable-job-id') ||
                   card.getAttribute('data-entity-urn')?.split(':').pop() || '';
        if (!id || seen.has(id)) continue;
        seen.add(id);

        const titleEl = card.querySelector('.job-card-list__title, .job-card-container__link, a[href*="/jobs/view/"]');
        const companyEl = card.querySelector('.job-card-container__company-name, .artdeco-entity-lockup__subtitle');
        const locEl = card.querySelector('.job-card-container__metadata-item, .job-card-container__metadata-wrapper span');
        const easyBadge = card.querySelector('.job-card-container__easy-apply-label, [data-easy-apply-badge]');
        const appliedEl = card.querySelector('[aria-label*="Applied"], .artdeco-inline-feedback, [aria-label*="Solicitado"]');
        const linkEl = card.querySelector('a[href*="/jobs/view/"]');
        const text = card.innerText || '';

        results.push({
            job_id: id,
            role: titleEl?.innerText?.trim() || '',
            company: companyEl?.innerText?.trim() || '',
            location: locEl?.innerText?.trim() || '',
            easy_apply: !!easyBadge || text.includes('Solicitud sencilla') || text.includes('Easy Apply'),
            already_applied: !!appliedEl && (appliedEl.innerText || '').match(/solicitado|applied/i) !== null,
            link: linkEl ? linkEl.href : `https://www.linkedin.com/jobs/view/${id}/`,
        });
    }

    // Strategy 2: SDUI 2026 component cards
    const col = document.querySelector('[data-testid="lazy-column"], #lazy-column');
    if (col && results.length === 0) {
        for (const item of col.querySelectorAll('[componentkey*="job-card-component-ref-"]')) {
            const key = item.getAttribute('componentkey') || '';
            const id = key.replace('job-card-component-ref-', '').trim();
            if (!id || seen.has(id)) continue;
            seen.add(id);

            const titleEl = item.querySelector('p, span[aria-hidden="true"]');
            const text = item.innerText || '';
            const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

            results.push({
                job_id: id,
                role: titleEl?.innerText?.trim() || (lines[0] || ''),
                company: lines[1] || '',
                location: lines[2] || '',
                easy_apply: text.includes('Solicitud sencilla') || text.includes('Easy Apply'),
                already_applied: text.includes('Candidatura enviada') || text.includes('Applied') || text.includes('Solicitado'),
                link: `https://www.linkedin.com/jobs/view/${id}/`,
            });
        }
    }
    return results;
}
"""

_EXTRACT_JOB_DETAILS_JS: str = r"""
() => {
    const titleEl = document.querySelector(
        '.job-details-jobs-unified-top-card__job-title, h1.topcard__title, h1'
    );
    const companyEl = document.querySelector(
        '.job-details-jobs-unified-top-card__company-name, .topcard__org-name-link, a[href*="/company/"]'
    );
    const locEl = document.querySelector(
        '.job-details-jobs-unified-top-card__primary-description-container, .topcard__flavor--bullet'
    );
    const descEl = document.querySelector(
        '.jobs-description__content, .description__text, #job-details, [data-testid="lazy-column"]'
    );
    const recruiterEl = document.querySelector(
        '.hirer-card__hirer-information a, .message-the-recruiter a, [data-tracking-control-name="public_jobs_hirer-card"]'
    );
    const applyBtn = document.querySelector(
        '.jobs-apply-button, button[aria-label*="Easy Apply"], button[aria-label*="Solicitud sencilla"]'
    );

    const fullText = document.body.innerText || '';
    const applied = fullText.includes('Applied') ||
                    fullText.includes('Solicitado hace') ||
                    fullText.includes('Candidatura enviada');

    return {
        role: titleEl?.innerText?.trim() || document.title,
        company: companyEl?.innerText?.trim() || '',
        location: locEl?.innerText?.trim() || '',
        description: descEl?.innerText?.trim().slice(0, 5000) || '',
        recruiter: recruiterEl?.innerText?.trim() || '',
        recruiter_link: recruiterEl ? recruiterEl.href : '',
        easy_apply: !!applyBtn,
        already_applied: applied,
    };
}
"""


# ── Helper Functions ──────────────────────────────────────────────────────────

def _matches_blacklist(value: str, blacklist: list[str]) -> bool:
    """Return True if any non-empty blacklist entry is a substring of value (case-insensitive)."""
    lower = value.lower()
    return any(entry.lower() in lower for entry in blacklist if entry)


def _is_job_allowed(job: dict[str, Any], settings: Settings) -> bool:
    """Return True if the job passes all blacklist constraints."""
    bl = settings.linkedin
    return not (
        _matches_blacklist(job.get("company", ""), bl.company_blacklist)
        or _matches_blacklist(job.get("role", ""), bl.title_blacklist)
        or _matches_blacklist(job.get("location", ""), bl.location_blacklist)
    )


async def _uncheck_follow_company(elements: list[dict[str, Any]]) -> None:
    """Uncheck 'Follow company' checkboxes in Easy Apply modals."""
    for el in elements:
        name = el.get("name", "").lower()
        if (
            any(indicator in name for indicator in FOLLOW_TEXT_INDICATORS)
            and el.get("type") == "checkbox"
            and el.get("value") not in _CHECKBOX_UNCHECKED_VALUES
        ):
            await browser.interact(el["index"], "click")


async def _autofill_element(
    el: dict[str, Any],
    profile: UserProfile,
    resume_path: str | None,
) -> dict[str, str] | None:
    """Autofill a single form element using candidate profile data.

    Returns a ``{"field": ..., "value": ...}`` dict on success, or ``None`` if
    the element was skipped or the interaction produced no result.
    """
    tag = el.get("tag", "")
    role = el.get("role", "")
    name = el.get("name", "")
    el_type = el.get("type", "")
    current_val = el.get("value", "")
    index = el.get("index")

    if index is None:
        return None

    # File upload (Resume PDF)
    if el_type == "file" and resume_path and Path(resume_path).exists():
        res = await browser.interact(index, "upload", resume_path)
        return {"field": FIELD_RESUME, "value": resume_path} if _MARKER_UPLOADED in res else None

    # Dropdowns / Selects / Comboboxes
    if tag == "select" or role == "combobox":
        answer = match_field(name, profile)
        if answer:
            res = await browser.interact(index, "select", str(answer))
            return {"field": name, "value": str(answer)} if _MARKER_SELECTED in res else None
        return None

    # Radio Buttons
    if el_type == "radio":
        answer = match_field(name, profile)
        if answer:
            ans_lower = answer.lower().strip()
            name_lower = name.lower().strip()
            is_aff_answer = any(v in ans_lower for v in AFFIRMATIVE_VALUES)
            is_neg_answer = any(v in ans_lower for v in NEGATIVE_VALUES)
            is_aff_label = any(v in name_lower for v in AFFIRMATIVE_VALUES)
            is_neg_label = any(v in name_lower for v in NEGATIVE_VALUES)

            should_click = (is_aff_answer and is_aff_label) or (is_neg_answer and is_neg_label)
            if should_click:
                await browser.interact(index, "click")
                return {"field": name, "value": "Yes" if is_aff_answer else "No"}
        return None

    # Text Inputs & Textareas
    if (tag in ("input", "textarea") or role == "textbox") and not current_val:
        answer = match_field(name, profile)
        if answer:
            res = await browser.interact(index, "type", str(answer))
            return {"field": name, "value": str(answer)} if _MARKER_TYPED in res else None

    return None


def _detect_action_button(
    elements: list[dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None]:
    """Identify the primary step-advancement button in priority order (submit > review > next)."""
    for action, keywords in BUTTON_ACTIONS:
        for el in elements:
            if el.get("role") == "button":
                name = el.get("name", "").lower()
                if any(kw in name for kw in keywords):
                    return action, el
    return None, None


# ── Core Public API ───────────────────────────────────────────────────────────

def build_search_url(
    positions: str | list[str] | None = None,
    locations: str | list[str] | None = None,
    easy_apply: bool = True,
) -> str:
    """Construct a LinkedIn job search URL applying all active settings filters."""
    settings = get_settings()
    pos_list = [positions] if isinstance(positions, str) else (positions or settings.linkedin.positions)
    loc_list = [locations] if isinstance(locations, str) else (locations or settings.linkedin.locations)

    keywords = pos_list[0] if pos_list else ""
    location = loc_list[0] if loc_list else DEFAULT_SEARCH_LOCATION

    params = [f"keywords={quote(keywords)}", f"location={quote(location)}"]
    if easy_apply:
        params.append(EASY_APPLY_SEARCH_PARAM)

    if settings.linkedin.experience_levels:
        codes = [EXPERIENCE_MAP[e] for e in settings.linkedin.experience_levels if e in EXPERIENCE_MAP]
        if codes:
            params.append(f"f_E={','.join(codes)}")

    enabled_types = [JOB_TYPE_MAP[k] for k, v in settings.linkedin.job_types.items() if v and k in JOB_TYPE_MAP]
    if enabled_types:
        params.append(f"f_JT={','.join(enabled_types)}")

    date_code = DATE_FILTER_MAP.get(settings.linkedin.date_filter)
    if date_code:
        params.append(f"f_TPR={date_code}")

    params.append(f"distance={settings.linkedin.distance}")
    return f"{LINKEDIN_JOBS_SEARCH_URL}{'&'.join(params)}"


async def human_delay(min_s: float | None = None, max_s: float | None = None) -> None:
    """Sleep for a randomized humanized duration driven by apply settings."""
    settings = get_settings()
    delay = random.uniform(min_s or settings.apply.min_delay, max_s or settings.apply.max_delay)
    await asyncio.sleep(delay)


async def search(
    positions: str | list[str] | None = None,
    locations: str | list[str] | None = None,
    easy_apply: bool = True,
) -> str:
    """Navigate to LinkedIn job search with the configured search parameters."""
    url = build_search_url(positions=positions, locations=locations, easy_apply=easy_apply)
    return await browser.navigate(url)


async def extract_jobs_list() -> list[dict[str, Any]]:
    """Extract job listings from search results (supports standard DOM and 2026 SDUI DOM)."""
    page = browser.get_page()
    if not page:
        return []

    try:
        jobs: list[dict[str, Any]] = await page.evaluate(_EXTRACT_JOBS_LIST_JS)
        settings = get_settings()
        return [j for j in jobs if _is_job_allowed(j, settings)]
    except Exception as e:
        logger.warning("extract_jobs_list failed: {}", e)
        return []


async def extract_job_details() -> dict[str, Any]:
    """Extract job description and metadata from the currently active page."""
    page = browser.get_page()
    if not page:
        return {}

    try:
        details: dict[str, Any] = await page.evaluate(_EXTRACT_JOB_DETAILS_JS)
        return details
    except Exception as e:
        logger.warning("extract_job_details failed: {}", e)
        return {}


async def click_easy_apply() -> str:
    """Click the Easy Apply button on a job listing page."""
    page = browser.get_page()
    if not page:
        return "error: browser not started"

    try:
        # Strategy 1: CSS locators
        for sel in EASY_APPLY_BUTTON_SELECTORS:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await human_delay()
                return RES_CLICKED_EASY_APPLY

        # Strategy 2: Accessibility snapshot fallback
        snap = await browser.snapshot()
        for el in snap.get("elements", []):
            name = el.get("name", "").lower()
            if el.get("role") == "button" and any(k in name for k in EASY_APPLY_TEXT_INDICATORS):
                await browser.interact(el["index"], "click")
                await human_delay()
                return RES_CLICKED_EASY_APPLY

        # Check if already applied before reporting not-found
        details = await extract_job_details()
        if details.get("already_applied"):
            return RES_ALREADY_APPLIED

        return "error: Easy Apply button not found"
    except Exception as e:
        logger.warning("click_easy_apply failed: {}", e)
        return f"error: {e}"


async def apply_step(
    resume_path: str | None = None,
    auto_advance: bool = True,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """Inspect and autofill the current step of the Easy Apply wizard.

    Args:
        resume_path: Absolute path to the tailored PDF resume to upload.
        auto_advance: When True, click the step-advancement button after filling.
        dry_run: Override the settings ``apply.dry_run`` flag for this call only.

    Returns:
        A status dict containing ``"status"``, ``"filled"``, and optionally ``"errors"``.
    """
    page = browser.get_page()
    if not page:
        return {"status": STATUS_ERROR, "message": "Browser not started"}

    settings = get_settings()
    is_dry_run = dry_run if dry_run is not None else settings.apply.dry_run
    profile = load_profile()
    filled_items: list[dict[str, str]] = []

    snap = await browser.snapshot()
    elements: list[dict[str, Any]] = snap.get("elements", [])
    form_errors: list[str] = snap.get("form_errors", [])

    # 1. Uncheck "Follow company"
    await _uncheck_follow_company(elements)

    # 2. Autofill form elements
    for el in elements:
        filled = await _autofill_element(el, profile, resume_path)
        if filled:
            filled_items.append(filled)

    if not auto_advance:
        return {"status": STATUS_FILLED, "filled": filled_items, "errors": form_errors}

    # 3. Detect and handle step-advancement button
    action, btn = _detect_action_button(elements)

    if action == ACTION_SUBMIT and btn:
        if is_dry_run:
            return {"status": STATUS_READY_TO_SUBMIT_DRY_RUN, "filled": filled_items}
        await browser.interact(btn["index"], "click")
        await human_delay()
        return {"status": STATUS_SUBMITTED, "filled": filled_items}

    if action in (ACTION_REVIEW, ACTION_NEXT) and btn:
        await browser.interact(btn["index"], "click")
        await human_delay()
        return {"status": STATUS_ADVANCED, "filled": filled_items}

    return {"status": STATUS_NO_ADVANCE_BUTTON, "filled": filled_items, "errors": form_errors}


def generate_recruiter_pitch(
    job_title: str,
    company: str,
    recruiter_name: str = "",
    top_skills: list[str] | None = None,
    language: str = AUTO_LANGUAGE,
) -> str:
    """Generate a concise, personalized LinkedIn recruiter connection note.

    The note is capped at ``MAX_NOTE_LENGTH`` characters to comply with LinkedIn's
    connection message limit. Language is inferred from the job posting when
    ``language="auto"``.

    Args:
        job_title: Target job title from the posting.
        company: Target company name.
        recruiter_name: Full name of the recruiter (first name is extracted automatically).
        top_skills: Explicit list of skills to highlight; falls back to profile skills.
        language: ``"es"``/``"spanish"``/``"español"`` for Spanish, ``"auto"`` to infer.

    Returns:
        A ready-to-send connection note string.
    """
    profile = load_profile()
    name = profile.personal.first_name or DEFAULT_CANDIDATE_NAME

    if top_skills:
        skills_list = top_skills[:MAX_PITCH_SKILLS]
    elif profile.skills:
        skills_list = [k.capitalize() for k in profile.skills.keys()][:MAX_PITCH_SKILLS]
    elif profile.professional.headline:
        skills_list = [profile.professional.headline]
    else:
        skills_list = []

    skills_str = ", ".join(filter(None, skills_list))

    posting_text = f"{job_title} {company}".lower()
    is_es = language.lower() in SPANISH_LANGUAGES or (
        language == AUTO_LANGUAGE
        and any(w in posting_text for w in SPANISH_DETECTION_WORDS)
    )
    first_name = recruiter_name.split()[0] if recruiter_name else ""

    if is_es:
        greeting = f"Hola {first_name}," if first_name else "Hola,"
        skills_part = _PITCH_SKILLS_PART_ES.format(skills=skills_str) if skills_str else ""
        note = _PITCH_NOTE_TEMPLATE_ES.format(
            greeting=greeting,
            job_title=job_title,
            company=company,
            skills_part=skills_part,
            name=name,
        )
    else:
        greeting = f"Hi {first_name}," if first_name else "Hi,"
        skills_part = _PITCH_SKILLS_PART_EN.format(skills=skills_str) if skills_str else ""
        note = _PITCH_NOTE_TEMPLATE_EN.format(
            greeting=greeting,
            job_title=job_title,
            company=company,
            skills_part=skills_part,
            name=name,
        )

    return note.strip()[:MAX_NOTE_LENGTH]


async def connect_recruiter(
    recruiter_url: str,
    note: str = "",
    dry_run: bool | None = None,
) -> str:
    """Send a LinkedIn connection request to a recruiter with an optional personalized note.

    Args:
        recruiter_url: Full LinkedIn profile URL of the recruiter.
        note: Pre-generated connection note (≤ ``MAX_NOTE_LENGTH`` chars).
        dry_run: Override the settings ``apply.dry_run`` flag for this call only.

    Returns:
        A status string describing the outcome.
    """
    page = browser.get_page()
    if not page:
        return "error: browser not started"

    settings = get_settings()
    is_dry_run = dry_run if dry_run is not None else settings.apply.dry_run

    try:
        if recruiter_url and not page.url.startswith(recruiter_url):
            await page.goto(recruiter_url, wait_until="domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT_MS)
            await human_delay()

        if is_dry_run:
            return f"dry_run: connection note prepared for {recruiter_url} -> '{note}'"

        connect_btn = page.locator(CONNECT_BUTTON_SELECTORS).first
        if not (await connect_btn.count() > 0 and await connect_btn.is_visible()):
            return "error: Connect button not found"

        await connect_btn.click()
        await human_delay()

        if note:
            add_note = page.locator(ADD_NOTE_BUTTON_SELECTORS).first
            if await add_note.count() > 0:
                await add_note.click()
                await page.locator(NOTE_TEXTAREA_SELECTOR).fill(note)
                await page.locator(SEND_BUTTON_SELECTORS).first.click()
                return RES_CONNECTION_SENT_WITH_NOTE

        send_btn = page.locator(SEND_BUTTON_SELECTORS).first
        if await send_btn.count() > 0:
            await send_btn.click()
            return RES_CONNECTION_SENT

        return "error: Send button not found"
    except Exception as e:
        logger.warning("connect_recruiter failed: {}", e)
        return f"error connecting with recruiter: {e}"
