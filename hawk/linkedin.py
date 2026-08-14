"""LinkedIn search, job scraping, Easy Apply autofill engine, and recruiter outreach."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Any
from urllib.parse import quote

from loguru import logger

from hawk.browser import browser
from hawk.config import get_settings, load_profile, match_field

EXPERIENCE_MAP = {"internship": "1", "entry": "2", "associate": "3", "mid_senior_level": "4", "director": "5", "executive": "6"}
JOB_TYPE_MAP = {"full_time": "F", "part_time": "P", "contract": "C", "temporary": "T", "internship": "I"}
DATE_FILTER_MAP = {"day": "r86400", "week": "r604800", "month": "r2592000"}


def build_search_url(
    positions: str | list[str] | None = None,
    locations: str | list[str] | None = None,
    easy_apply: bool = True,
) -> str:
    """Construct a LinkedIn job search URL with active settings filters."""
    settings = get_settings()
    pos_list = [positions] if isinstance(positions, str) else (positions or settings.linkedin.positions)
    loc_list = [locations] if isinstance(locations, str) else (locations or settings.linkedin.locations)

    keywords = pos_list[0] if pos_list else ""
    location = loc_list[0] if loc_list else "remote"

    params = [f"keywords={quote(keywords)}", f"location={quote(location)}"]
    if easy_apply:
        params.append("f_LF=f_AL")

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
    return f"https://www.linkedin.com/jobs/search/?{'&'.join(params)}"


async def human_delay(min_s: float | None = None, max_s: float | None = None) -> None:
    """Randomized humanized delay between actions."""
    settings = get_settings()
    delay = random.uniform(min_s or settings.apply.min_delay, max_s or settings.apply.max_delay)
    await asyncio.sleep(delay)


async def search(positions: str | list[str] | None = None, locations: str | list[str] | None = None, easy_apply: bool = True) -> str:
    """Navigate to LinkedIn search with configured parameters."""
    url = build_search_url(positions, locations, easy_apply)
    return await browser.navigate(url)


async def extract_jobs_list() -> list[dict[str, Any]]:
    """Extract job listings from search results (supports standard & 2026 SDUI DOMs)."""
    page = browser.get_page()
    if not page:
        return []

    try:
        jobs = await page.evaluate(r"""
        () => {
            const results = [];
            const seen = new Set();

            // Strategy 1: Standard job card selectors
            const cards = document.querySelectorAll('.job-card-container, .jobs-search-results__list-item, [data-job-id], [data-occludable-job-id]');
            for (const card of cards) {
                const id = card.getAttribute('data-job-id') || card.getAttribute('data-occludable-job-id') || card.getAttribute('data-entity-urn')?.split(':').pop() || '';
                if (!id || seen.has(id)) continue;
                seen.add(id);

                const titleEl = card.querySelector('.job-card-list__title, .job-card-container__link, a[href*="/jobs/view/"]');
                const companyEl = card.querySelector('.job-card-container__company-name, .artdeco-entity-lockup__subtitle');
                const locEl = card.querySelector('.job-card-container__metadata-item, .job-card-container__metadata-wrapper span');
                const easyBadge = card.querySelector('.job-card-container__easy-apply-label, [data-easy-apply-badge]');
                const appliedEl = card.querySelector('[aria-label*="Applied"], .artdeco-inline-feedback, [aria-label*="Solicitado"]');
                const linkEl = card.querySelector('a[href*="/jobs/view/"]');

                results.push({
                    job_id: id,
                    role: titleEl?.innerText?.trim() || '',
                    company: companyEl?.innerText?.trim() || '',
                    location: locEl?.innerText?.trim() || '',
                    easy_apply: !!easyBadge || (card.innerText || '').includes('Solicitud sencilla') || (card.innerText || '').includes('Easy Apply'),
                    already_applied: !!appliedEl && ((appliedEl.innerText || '').includes('Solicitado') || (appliedEl.innerText || '').includes('Applied')),
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
                        already_applied: text.includes('Candidatura enviada') || text.includes('Applied'),
                        link: `https://www.linkedin.com/jobs/view/${id}/`,
                    });
                }
            }
            return results;
        }
        """)

        # Filter against blacklists
        settings = get_settings()
        filtered = []
        for j in jobs:
            comp = j.get("company", "").lower()
            role = j.get("role", "").lower()
            loc = j.get("location", "").lower()
            if any(b.lower() in comp for b in settings.linkedin.company_blacklist if b):
                continue
            if any(b.lower() in role for b in settings.linkedin.title_blacklist if b):
                continue
            if any(b.lower() in loc for b in settings.linkedin.location_blacklist if b):
                continue
            filtered.append(j)
        return filtered
    except Exception as e:
        logger.warning("extract_jobs_list failed: {}", e)
        return []


async def extract_job_details() -> dict[str, Any]:
    """Extract job description and details from current active page."""
    page = browser.get_page()
    if not page:
        return {}

    try:
        return await page.evaluate(r"""
        () => {
            const titleEl = document.querySelector('.job-details-jobs-unified-top-card__job-title, h1.topcard__title, h1');
            const companyEl = document.querySelector('.job-details-jobs-unified-top-card__company-name, .topcard__org-name-link, a[href*="/company/"]');
            const locEl = document.querySelector('.job-details-jobs-unified-top-card__primary-description-container, .topcard__flavor--bullet');
            const descEl = document.querySelector('.jobs-description__content, .description__text, #job-details, [data-testid="lazy-column"]');
            const recruiterEl = document.querySelector('.hirer-card__hirer-information a, .message-the-recruiter a, [data-tracking-control-name="public_jobs_hirer-card"]');
            const applyBtn = document.querySelector('.jobs-apply-button, button[aria-label*="Easy Apply"], button[aria-label*="Solicitud sencilla"]');

            const fullText = document.body.innerText || '';
            const applied = fullText.includes('Applied') || fullText.includes('Solicitado hace') || fullText.includes('Candidatura enviada');

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
        """)
    except Exception as e:
        logger.warning("extract_job_details failed: {}", e)
        return {}


async def click_easy_apply() -> str:
    """Click the Easy Apply button on a job listing."""
    page = browser.get_page()
    if not page:
        return "error: browser not started"

    try:
        # Strategy 1: Locators
        selectors = [
            ".jobs-apply-button--top-card button",
            "button.jobs-apply-button",
            "button[aria-label*='Easy Apply']",
            "button[aria-label*='Solicitud sencilla']",
        ]
        for sel in selectors:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await human_delay(1.5, 2.5)
                return "clicked_easy_apply"

        # Strategy 2: Accessibility snapshot fallback
        snap = await browser.snapshot()
        for el in snap.get("elements", []):
            name = el.get("name", "").lower()
            if el.get("role") == "button" and any(k in name for k in ("easy apply", "solicitud sencilla", "aplicación sencilla")):
                await browser.interact(el["index"], "click")
                await human_delay(1.5, 2.5)
                return "clicked_easy_apply"

        # Check if already applied
        details = await extract_job_details()
        if details.get("already_applied"):
            return "already_applied"

        return "error: Easy Apply button not found"
    except Exception as e:
        return f"error: {e}"


async def apply_step(
    resume_path: str | None = None,
    auto_advance: bool = True,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """Inspect and autofill the current step of the Easy Apply wizard."""
    page = browser.get_page()
    if not page:
        return {"status": "error", "message": "Browser not started"}

    settings = get_settings()
    is_dry_run = dry_run if dry_run is not None else settings.apply.dry_run
    profile = load_profile()
    filled_items = []

    snap = await browser.snapshot()
    elements = snap.get("elements", [])
    form_errors = snap.get("form_errors", [])

    # 1. Uncheck "Follow company"
    for el in elements:
        name = el.get("name", "").lower()
        if "follow" in name or "seguir" in name:
            if el.get("type") == "checkbox" and el.get("value") not in ("false", "0", ""):
                await browser.interact(el["index"], "click")

    # 2. Autofill fields
    for el in elements:
        tag = el.get("tag", "")
        role = el.get("role", "")
        name = el.get("name", "")
        el_type = el.get("type", "")
        current_val = el.get("value", "")

        # Upload resume
        if el_type == "file" and resume_path and Path(resume_path).exists():
            res = await browser.interact(el["index"], "upload", resume_path)
            if "uploaded" in res:
                filled_items.append({"field": "resume", "value": resume_path})
            continue

        # Dropdowns
        if tag == "select" or role == "combobox":
            answer = match_field(name, profile)
            if answer:
                res = await browser.interact(el["index"], "select", str(answer))
                if "selected" in res:
                    filled_items.append({"field": name, "value": str(answer)})
            continue

        # Radio Buttons
        if el_type == "radio":
            answer = match_field(name, profile)
            if answer and answer.lower() in ("yes", "sí", "si", "true", "1") and "yes" in name.lower() or "sí" in name.lower():
                await browser.interact(el["index"], "click")
                filled_items.append({"field": name, "value": "Yes"})
            elif answer and answer.lower() in ("no", "false", "0") and "no" in name.lower():
                await browser.interact(el["index"], "click")
                filled_items.append({"field": name, "value": "No"})
            continue

        # Text Inputs & Textareas
        if tag in ("input", "textarea") or role == "textbox":
            if not current_val:
                answer = match_field(name, profile)
                if answer:
                    res = await browser.interact(el["index"], "type", str(answer))
                    if "typed" in res:
                        filled_items.append({"field": name, "value": str(answer)})
            continue

    if not auto_advance:
        return {"status": "filled", "filled": filled_items, "errors": form_errors}

    # 3. Detect Submit / Review / Next button
    submit_btn = next((e for e in elements if e.get("role") == "button" and any(k in e.get("name", "").lower() for k in ("submit", "enviar solicitud", "enviar candidatura"))), None)
    review_btn = next((e for e in elements if e.get("role") == "button" and any(k in e.get("name", "").lower() for k in ("review", "revisar"))), None)
    next_btn = next((e for e in elements if e.get("role") == "button" and any(k in e.get("name", "").lower() for k in ("next", "siguiente", "continue", "continuar", "avançar"))), None)

    if submit_btn:
        if is_dry_run:
            return {"status": "ready_to_submit_dry_run_blocked", "filled": filled_items}
        await browser.interact(submit_btn["index"], "click")
        await human_delay(2.0, 3.0)
        return {"status": "submitted", "filled": filled_items}

    if review_btn:
        await browser.interact(review_btn["index"], "click")
        await human_delay(1.5, 2.5)
        return {"status": "advanced", "filled": filled_items}

    if next_btn:
        await browser.interact(next_btn["index"], "click")
        await human_delay(1.5, 2.5)
        return {"status": "advanced", "filled": filled_items}

    return {"status": "no_advance_button", "filled": filled_items, "errors": form_errors}


def generate_recruiter_pitch(
    job_title: str,
    company: str,
    recruiter_name: str = "",
    top_skills: list[str] | None = None,
    language: str = "auto",
) -> str:
    """Generate concise LinkedIn recruiter connection note (<300 chars limit)."""
    profile = load_profile()
    name = profile.personal.first_name
    skills_list = top_skills or [k.capitalize() for k in profile.skills.keys()][:3] or [profile.professional.headline]
    skills_str = ", ".join(filter(None, skills_list))

    is_es = language.lower() in ("es", "spanish", "español") or any(
        w in f"{job_title} {company}".lower() for w in ("ingeniero", "desarrollador", "remoto", "sistemas")
    )
    first_name = recruiter_name.split()[0] if recruiter_name else ""

    if is_es:
        greeting = f"Hola {first_name}," if first_name else "Hola,"
        skills_part = f" Con experiencia en {skills_str}," if skills_str else ""
        note = f"{greeting} me postulé a {job_title} en {company}.{skills_part} me encantaría conectar y conversar sobre cómo puedo sumar al equipo. ¡Saludos, {name}!"
    else:
        greeting = f"Hi {first_name}," if first_name else "Hi,"
        skills_part = f" With experience in {skills_str}," if skills_str else ""
        note = f"{greeting} I applied for the {job_title} role at {company}.{skills_part} I'd love to connect and discuss how I can contribute! Best, {name}"

    return note[:299]
        note = f"{greeting} I applied for the {job_title} role at {company}. With experience in {skills_str}, I'd love to connect and discuss how I can contribute! Best, {name}"

    return note[:299]


async def connect_recruiter(recruiter_url: str, note: str = "", dry_run: bool = True) -> str:
    """Send connection request to recruiter."""
    page = browser.get_page()
    if not page:
        return "error: browser not started"

    try:
        if recruiter_url and not page.url.startswith(recruiter_url):
            await page.goto(recruiter_url, wait_until="domcontentloaded", timeout=25000)
            await human_delay()

        if dry_run:
            return f"dry_run: connection note prepared for {recruiter_url} -> '{note}'"

        connect_btn = page.locator('button:has-text("Conectar"), button:has-text("Connect")').first
        if await connect_btn.count() > 0 and await connect_btn.is_visible():
            await connect_btn.click()
            await page.wait_for_timeout(1000)
            if note:
                add_note = page.locator('button:has-text("Añadir nota"), button:has-text("Add a note")').first
                if await add_note.count() > 0:
                    await add_note.click()
                    await page.locator('textarea[name="message"]').fill(note)
                    send_btn = page.locator('button:has-text("Enviar"), button:has-text("Send")').first
                    await send_btn.click()
                    return "connection_sent_with_note"
            send_btn = page.locator('button:has-text("Enviar"), button:has-text("Send")').first
            if await send_btn.count() > 0:
                await send_btn.click()
            return "connection_sent"

        return "error: Connect button not found"
    except Exception as e:
        return f"error connecting with recruiter: {e}"
