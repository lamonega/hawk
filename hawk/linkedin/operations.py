"""LinkedIn-specific browser operations."""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

from hawk.browser.driver import get_page, save_session
from hawk.settings import get_settings

SCREENSHOT_DIR = Path("output/screenshots")

# Shared JS for detecting form fields in Easy Apply modals
_DETECT_FIELDS_JS = """
() => {
    const results = [];
    const modal = document.querySelector('.jobs-easy-apply-modal') ||
                  document.querySelector('[role="dialog"]') ||
                  document.querySelector('.artdeco-modal');

    if (!modal) return {fields: [], has_submit: false, has_next: false, total_fields: 0};

    // Text inputs
    modal.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], input[type="number"], input[type="url"], input:not([type])').forEach(el => {
        const label = el.getAttribute('aria-label') ||
                      el.closest('.jobs-easy-apply-form-section__group')?.querySelector('label')?.innerText ||
                      el.getAttribute('name') || '';
        results.push({
            type: 'text',
            name: label.trim(),
            required: el.required || el.getAttribute('aria-required') === 'true',
            value: el.value || '',
            input_type: el.type || 'text',
        });
    });

    // Selects
    modal.querySelectorAll('select').forEach(el => {
        const label = el.getAttribute('aria-label') ||
                      el.closest('.jobs-easy-apply-form-section__group')?.querySelector('label')?.innerText ||
                      el.getAttribute('name') || '';
        const options = Array.from(el.options).map(o => ({value: o.value, text: o.text}));
        results.push({
            type: 'select',
            name: label.trim(),
            required: el.required || el.getAttribute('aria-required') === 'true',
            value: el.value,
            options: options,
        });
    });

    // Radios (grouped by name)
    const radioGroups = {};
    modal.querySelectorAll('input[type="radio"]').forEach(el => {
        const name = el.getAttribute('name') || 'unknown';
        if (!radioGroups[name]) {
            const label = el.closest('.jobs-easy-apply-form-section__group')?.querySelector('label')?.innerText || name;
            radioGroups[name] = {
                type: 'radio',
                name: label.trim(),
                required: true,
                options: [],
            };
        }
        const optionLabel = el.closest('label')?.innerText ||
                            el.nextElementSibling?.innerText || el.value;
        radioGroups[name].options.push({value: el.value, text: optionLabel.trim()});
    });
    results.push(...Object.values(radioGroups));

    // Checkboxes
    modal.querySelectorAll('input[type="checkbox"]').forEach(el => {
        const label = el.getAttribute('aria-label') ||
                      el.closest('label')?.innerText ||
                      el.getAttribute('name') || '';
        results.push({
            type: 'checkbox',
            name: label.trim(),
            required: false,
            checked: el.checked,
        });
    });

    // File uploads
    modal.querySelectorAll('input[type="file"]').forEach(el => {
        const label = el.getAttribute('aria-label') ||
                      el.closest('.jobs-easy-apply-form-section__group')?.querySelector('label')?.innerText ||
                      'Resume/CV';
        results.push({
            type: 'file',
            name: label.trim(),
            required: el.required,
        });
    });

    // Buttons
    const submitBtn = modal.querySelector('button[aria-label="Submit application"]');
    const nextBtn = modal.querySelector('button[aria-label="Continue to next step"]') ||
                    modal.querySelector('button[aria-label="Continue to review"]') ||
                    modal.querySelector('button.artdeco-button--primary');

    return {
        fields: results,
        has_submit: !!submitBtn,
        has_next: !!nextBtn,
        total_fields: results.length,
    };
}
"""


def _ensure_screenshot_dir() -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_DIR


def human_delay() -> None:
    """Sleep a random duration between min_delay and max_delay from settings."""
    settings = get_settings()
    delay = random.uniform(settings.apply.min_delay, settings.apply.max_delay)
    logger.debug("Human delay: {:.1f}s", delay)
    time.sleep(delay)


def _take_debug_screenshot(step_name: str) -> str | None:
    """Take a screenshot for debugging, return path or None."""
    page = get_page()
    if page is None:
        return None
    try:
        path = _ensure_screenshot_dir() / f"{step_name}.png"
        page.screenshot(path=str(path), full_page=False)
        logger.debug("Screenshot saved: {}", path)
        return str(path)
    except Exception as e:
        logger.debug("Screenshot failed: {}", e)
        return None


def _get_progress_percentage() -> int | None:
    """Extract progress percentage from the Easy Apply modal (e.g. 'Step 2 of 4 — 50%').

    Returns the percentage as int, or None if not found.
    """
    page = get_page()
    if page is None:
        return None
    try:
        text = page.evaluate(
            """
            () => {
                const modal = document.querySelector('.jobs-easy-apply-modal') ||
                              document.querySelector('[role="dialog"]');
                return modal ? modal.innerText : '';
            }
            """
        )
        match = re.search(r"(\d{1,3})%", text)
        return int(match.group(1)) if match else None
    except Exception:
        return None


def build_search_url(
    positions: str = "",
    locations: str = "",
    easy_apply: bool = True,
) -> str:
    """Build a LinkedIn job search URL with filters."""
    from urllib.parse import quote_plus

    params = []
    if positions:
        params.append(f"keywords={quote_plus(positions)}")
    if locations:
        params.append(f"location={quote_plus(locations)}")
    if easy_apply:
        params.append("f_AL=true")

    # Apply settings-based filters
    settings = get_settings()

    # Experience levels
    exp_map = {
        "internship": "1", "entry": "2", "associate": "3",
        "mid_senior_level": "4", "director": "5", "executive": "6",
    }
    exp_codes = [exp_map[e] for e in settings.linkedin.experience_levels if e in exp_map]
    if exp_codes:
        params.append(f"f_E={','.join(exp_codes)}")

    # Job types
    jt_map = {
        "full_time": "F", "part_time": "P", "contract": "C",
        "temporary": "T", "internship": "I", "volunteer": "V", "other": "O",
    }
    jt_codes = [jt_map[k] for k, v in settings.linkedin.job_types.items() if v and k in jt_map]
    if jt_codes:
        params.append(f"f_JT={','.join(jt_codes)}")

    # Date filter
    date_map = {
        "day": "r86400", "week": "r604800", "month": "r2592000",
        "3_months": "r7776000", "6_months": "r15552000", "year": "r31536000",
    }
    date_code = date_map.get(settings.linkedin.date_filter)
    if date_code:
        params.append(f"f_TPR={date_code}")

    # Distance
    if settings.linkedin.distance != 25:
        params.append(f"distance={settings.linkedin.distance}")

    base = "https://www.linkedin.com/jobs/search/"
    query = "&".join(params)
    return f"{base}?{query}" if query else base


def extract_jobs_list() -> str:
    """Extract job cards from a LinkedIn search results page.

    Returns JSON array of job summaries. Tries multiple selector strategies
    including newer LinkedIn DOM patterns, then falls back to extracting all
    /jobs/view/ links directly from the page.
    """
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    try:
        jobs = page.evaluate(
            """
            () => {
                // Strategy 1: try known card container selectors
                const cardSelectors = [
                    '.jobs-search-results__list-item',
                    '.scaffold-layout__list li',
                    '[data-view-name="job-card"]',
                    '.job-card-container',
                    '[data-job-id]',
                    '[data-occludable-job-id]',
                    'li[class*="jobs-search"]',
                    'li[class*="job-card"]',
                ];

                let cards = [];
                for (const sel of cardSelectors) {
                    cards = document.querySelectorAll(sel);
                    if (cards.length > 0) break;
                }

                // Strategy 2 (fallback): scrape all /jobs/view/ links on the page
                if (cards.length === 0) {
                    const seen = new Set();
                    const links = document.querySelectorAll('a[href*="/jobs/view/"]');
                    return Array.from(links)
                        .map(link => {
                            const cleanHref = link.href.split('?')[0];
                            const idMatch = cleanHref.match(/view\\/([\\d]+)\\//);
                            if (!idMatch || seen.has(idMatch[1])) return null;
                            seen.add(idMatch[1]);

                            const card = link.closest('li') || link.parentElement;
                            const titleEl = card
                                ? (card.querySelector('strong') ||
                                   card.querySelector('[class*="title"]'))
                                : null;
                            const companyEl = card
                                ? card.querySelector('[class*="company"], [class*="subtitle"]')
                                : null;
                            const locationEl = card
                                ? card.querySelector('[class*="location"], [class*="caption"]')
                                : null;
                            const easyApplyEl = card
                                ? card.querySelector('[class*="easy-apply"], [class*="apply"]')
                                : null;

                            return {
                                job_id: idMatch[1],
                                role: titleEl
                                    ? titleEl.innerText.trim()
                                    : (link.getAttribute('aria-label') || link.innerText.trim()),
                                company: companyEl ? companyEl.innerText.trim() : '',
                                location: locationEl ? locationEl.innerText.trim() : '',
                                link: cleanHref,
                                easy_apply: !!easyApplyEl,
                                already_applied: false,
                            };
                        })
                        .filter(j => j && j.job_id);
                }

                // Process cards found via Strategy 1
                const seen = new Set();
                return Array.from(cards)
                    .map(card => {
                        const titleEl =
                            card.querySelector('.job-card-list__title--link') ||
                            card.querySelector('a.job-card-container__link') ||
                            card.querySelector('a[data-control-name="job_card_click"]') ||
                            card.querySelector('strong') ||
                            card.querySelector('a[aria-label]');

                        const companyEl =
                            card.querySelector('.artdeco-entity-lockup__subtitle') ||
                            card.querySelector('.job-card-container__primary-description') ||
                            card.querySelector('.job-card-container__company-name') ||
                            card.querySelector('[class*="company"]') ||
                            card.querySelector('[class*="subtitle"]');

                        const locationEl =
                            card.querySelector('.artdeco-entity-lockup__caption') ||
                            card.querySelector('.job-card-container__metadata-item') ||
                            card.querySelector('.job-card-container__location') ||
                            card.querySelector('[class*="location"]') ||
                            card.querySelector('[class*="caption"]');

                        const linkEl =
                            card.querySelector('a[href*="/jobs/view/"]') ||
                            card.querySelector('a');

                        const easyApplyEl =
                            card.querySelector('.job-card-container__apply-method') ||
                            card.querySelector('[data-testid="job-card-list-item__easy-apply"]') ||
                            card.querySelector('[class*="easy-apply"]');

                        const appliedBadge =
                            card.querySelector('.jobs-search-results-list__state-message') ||
                            card.querySelector('.artdeco-inline-feedback');

                        // Also try data attributes for job ID
                        const dataJobId =
                            card.getAttribute('data-job-id') ||
                            card.getAttribute('data-occludable-job-id') ||
                            (card.getAttribute('data-entity-urn') || '').match(/\\d+/)?.[0];

                        const link = linkEl ? linkEl.href.split('?')[0] : '';
                        const idMatch = link.match(/view\\/([\\d]+)\\//);
                        const job_id = idMatch ? idMatch[1] : (dataJobId || '');

                        if (!job_id || seen.has(job_id)) return null;
                        seen.add(job_id);

                        return {
                            job_id,
                            role: titleEl ? titleEl.innerText.trim() : '',
                            company: companyEl ? companyEl.innerText.trim() : '',
                            location: locationEl ? locationEl.innerText.trim() : '',
                            link: link,
                            easy_apply: !!easyApplyEl,
                            already_applied: !!appliedBadge,
                        };
                    })
                    .filter(j => j && j.role && j.link);
            }
            """
        )

        return json.dumps(jobs, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def extract_job_details() -> str:
    """Extract detailed job info from the current LinkedIn job page."""
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    try:
        job = page.evaluate(
            """
            () => {
                const title = document.querySelector('h1.job-details-jobs-unified-top-card__job-title') ||
                              document.querySelector('h1.t-24') ||
                              document.querySelector('h1');

                const company = document.querySelector('.job-details-jobs-unified-top-card__company-name a') ||
                                document.querySelector('.job-details-jobs-unified-top-card__company-name') ||
                                document.querySelector('.artdeco-entity-lockup__subtitle a') ||
                                document.querySelector('.artdeco-entity-lockup__subtitle');

                const location = document.querySelector('.job-details-jobs-unified-top-card__bullet') ||
                                 document.querySelector('.artdeco-entity-lockup__caption') ||
                                 document.querySelector('.job-details-jobs-unified-top-card__primary-description');

                const descEl = document.querySelector('.jobs-description__content') ||
                               document.querySelector('.description__text') ||
                               document.querySelector('.jobs-box__html-content');
                const description = descEl ? descEl.innerText.trim() : '';

                const easyApplyBtn = document.querySelector('button.jobs-apply-button');
                const easyApplyBadge = document.querySelector('.jobs-apply-button');

                // Detect "already applied" state on the job page
                const appliedBanner = document.querySelector('.jobs-apply-button--disabled') ||
                                      document.querySelector('.artdeco-inline-feedback--success');
                const alreadyApplied = !!(appliedBanner) ||
                    (easyApplyBtn && easyApplyBtn.disabled) ||
                    (easyApplyBtn && easyApplyBtn.innerText.includes('Applied'));

                const recruiter = document.querySelector('.jobs-search__organizer-link') ||
                                  document.querySelector('a[data-tracking-control-name="public_jobs_jobs-search-result-1"]');

                return {
                    role: title ? title.innerText.trim() : '',
                    company: company ? company.innerText.trim() : '',
                    location: location ? location.innerText.trim().split('\\n')[0] : '',
                    description: description,
                    easy_apply: !!(easyApplyBtn || easyApplyBadge),
                    already_applied: alreadyApplied,
                    recruiter: recruiter ? recruiter.href : '',
                    url: window.location.href,
                };
            }
            """
        )

        return json.dumps(job, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def click_easy_apply() -> str:
    """Click the Easy Apply button with multi-layer selector fallbacks.

    Returns 'clicked', 'already_applied', or 'error: ...'.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    _take_debug_screenshot("easy_apply_before_click")

    try:
        # Multi-layer selector cascade (inspired by david-izhak)
        selectors = [
            'button.jobs-apply-button',
            'button[aria-label*="Easy Apply"]',
            'button[aria-label*="Apply"]',
            'button.artdeco-button--primary:has-text("Easy Apply")',
            'button:has-text("Easy Apply")',
        ]

        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=3000):
                    # Check if already applied (button disabled or text says "Applied")
                    btn_text = btn.inner_text(timeout=2000).lower()
                    is_disabled = btn.is_disabled()

                    if is_disabled or "applied" in btn_text:
                        logger.info("Already applied to this job")
                        return "already_applied"

                    btn.click(timeout=5000)
                    human_delay()
                    _take_debug_screenshot("easy_apply_after_click")
                    return "clicked"
            except Exception:
                continue

        return "error: Easy Apply button not found"
    except Exception as e:
        return f"error: {e}"


def detect_form_fields() -> str:
    """Detect form fields in the current Easy Apply modal.

    Returns JSON with fields, has_submit/has_next, progress percentage, and total_fields.
    """
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    progress = _get_progress_percentage()

    try:
        fields = page.evaluate(_DETECT_FIELDS_JS)

        # Add follow checkbox detection
        follow_result = page.evaluate("""
            () => {
                const modal = document.querySelector('.jobs-easy-apply-modal') ||
                              document.querySelector('[role="dialog"]');
                if (!modal) return {has_follow_checkbox: false, follow_checked: false};
                const followCheckbox = modal.querySelector('input[name="followCompany"]') ||
                                       modal.querySelector('[data-follow-company]');
                return {
                    has_follow_checkbox: !!followCheckbox,
                    follow_checked: followCheckbox ? followCheckbox.checked : false,
                };
            }
        """)
        fields.update(follow_result)

        if progress is not None:
            fields["progress_percent"] = progress

        _take_debug_screenshot("detect_fields")
        return json.dumps(fields, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def detect_fields_with_profile() -> str:
    """Detect form fields and match them against the user profile.

    Same as detect_form_fields but adds 'profile_value' to each field
    when a match is found. Also identifies fields that need human input.
    """
    from hawk.profile import load_profile, match_field

    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    profile = load_profile()
    progress = _get_progress_percentage()

    try:
        raw = page.evaluate(_DETECT_FIELDS_JS)

        # Match each field against profile
        needs_human = []
        for field in raw.get("fields", []):
            name = field.get("name", "")
            field["profile_value"] = match_field(name, profile)
            if field["profile_value"] is None and field.get("required", False):
                needs_human.append(name)

        raw["needs_human_input"] = needs_human
        raw["needs_human_count"] = len(needs_human)

        if progress is not None:
            raw["progress_percent"] = progress

        _take_debug_screenshot("detect_fields_with_profile")
        return json.dumps(raw, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def unfollow_company() -> str:
    """Uncheck the 'Follow [Company]' checkbox if it's checked.

    Returns 'unchecked', 'not_found', or 'error: ...'.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        result = page.evaluate(
            """
            () => {
                const modal = document.querySelector('.jobs-easy-apply-modal') ||
                              document.querySelector('[role="dialog"]');
                if (!modal) return 'no_modal';

                // Multiple selector strategies for follow checkbox
                const selectors = [
                    'input[name="followCompany"]',
                    '[data-follow-company]',
                    'input[type="checkbox"]',
                ];

                for (const sel of selectors) {
                    const checkboxes = modal.querySelectorAll(sel);
                    for (const cb of checkboxes) {
                        const label = cb.closest('label')?.innerText || cb.getAttribute('aria-label') || '';
                        if (label.toLowerCase().includes('follow') && cb.checked) {
                            cb.click();
                            return 'unchecked';
                        }
                    }
                }
                return 'not_found';
            }
            """
        )
        if result == "unchecked":
            logger.info("Unfollowed company checkbox")
            human_delay()
        return result
    except Exception as e:
        return f"error: {e}"


def click_next_or_submit() -> str:
    """Click Next/Continue/Submit in the Easy Apply wizard.

    Checks Submit before Next (proper priority). Returns which button was clicked.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        # Priority: Submit first, then Next/Continue/Review
        selectors = [
            ("submit", 'button[aria-label="Submit application"]'),
            ("submit", 'button:has-text("Submit")'),
            ("next", 'button[aria-label="Continue to next step"]'),
            ("next", 'button[aria-label="Continue to review"]'),
            ("next", 'button.artdeco-button--primary'),
            ("next", 'button:has-text("Next")'),
            ("next", 'button:has-text("Continue")'),
            ("next", 'button:has-text("Review")'),
        ]

        for action, selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    btn.click(timeout=3000)
                    human_delay()
                    _take_debug_screenshot(f"after_{action}_click")
                    return f"clicked_{action}"
            except Exception:
                continue

        return "no_button_found"
    except Exception as e:
        return f"error: {e}"


def submit_application() -> str:
    """Submit the Easy Apply application.

    1. Unfollow company if checkbox is checked
    2. Check dry_run — if true, do NOT click Submit
    3. Click Submit
    4. Verify submission by checking modal closed
    """
    settings = get_settings()
    if settings.apply.dry_run:
        logger.info("Dry run mode — skipping actual submission")
        _take_debug_screenshot("dry_run_before_submit")
        return "dry_run_blocked"

    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        # Unfollow company before submitting
        unfollow_company()

        btn = page.locator('button[aria-label="Submit application"]').first
        btn.click(timeout=5000)
        human_delay()

        # Verify submission succeeded — check modal closed
        try:
            modal = page.locator('.jobs-easy-apply-modal, [role="dialog"], .artdeco-modal').first
            modal.wait_for(state="hidden", timeout=5000)
            logger.info("Submit verified: modal closed")
        except Exception:
            # Modal might still be open — check for success message
            success = page.locator('.artdeco-inline-feedback--success, .jobs-succeeded-apply-message').first
            if success.is_visible(timeout=2000):
                logger.info("Submit verified: success message shown")
            else:
                logger.warning("Submit verification inconclusive — modal state unknown")

        _take_debug_screenshot("after_submit")
        save_session()
        return "submitted"
    except Exception as e:
        return f"error: {e}"


def get_page_text() -> str:
    """Get the visible text content of the current page."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        text = page.evaluate("() => document.body.innerText")
        return text[:10000]
    except Exception as e:
        return f"error: {e}"


def navigate_to_url(url: str) -> str:
    """Navigate to a URL and return the page title + URL."""
    page = get_page()
    if page is None:
        return "error: Browser not started. Call browser_launch first."

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        human_delay()
        return f"Navigated to: {page.url}\nTitle: {page.title()}"
    except Exception as e:
        return f"error: {e}"


def search_and_navigate(
    positions: str = "",
    locations: str = "",
    easy_apply: bool = True,
) -> str:
    """Build a LinkedIn search URL and navigate to it."""
    url = build_search_url(positions, locations, easy_apply)
    return navigate_to_url(url)


def generate_job_id(link: str) -> str:
    """Generate a short job ID from a LinkedIn job URL."""
    return hashlib.md5(link.encode()).hexdigest()[:10]
