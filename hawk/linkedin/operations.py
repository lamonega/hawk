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
                  document.querySelector('.artdeco-modal') ||
                  document.querySelector('div[data-test-modal]') ||
                  document.querySelector('div[aria-modal="true"]') ||
                  document.body;

    // Text inputs
    modal.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], input[type="number"], input[type="url"], input:not([type])').forEach(el => {
        const label = el.getAttribute('aria-label') ||
                      el.closest('.jobs-easy-apply-form-section__group, .fb-dash-form-element, div[data-test-form-element]')?.querySelector('label')?.innerText ||
                      el.getAttribute('name') || '';
        if (label.trim()) {
            results.push({
                type: 'text',
                name: label.trim().split('\\n')[0].trim(),
                required: el.required || el.getAttribute('aria-required') === 'true',
                value: el.value || '',
                input_type: el.type || 'text',
            });
        }
    });

    // Selects
    modal.querySelectorAll('select').forEach(el => {
        const label = el.getAttribute('aria-label') ||
                      el.closest('.jobs-easy-apply-form-section__group, .fb-dash-form-element, div[data-test-form-element]')?.querySelector('label')?.innerText ||
                      el.getAttribute('name') || '';
        const options = Array.from(el.options).map(o => ({value: o.value, text: o.text}));
        results.push({
            type: 'select',
            name: label.trim().split('\\n')[0].trim(),
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
            const label = el.closest('.jobs-easy-apply-form-section__group, .fb-dash-form-element, div[data-test-form-element]')?.querySelector('label, legend')?.innerText || name;
            radioGroups[name] = {
                type: 'radio',
                name: label.trim().split('\\n')[0].trim(),
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
            name: label.trim().split('\\n')[0].trim(),
            required: false,
            checked: el.checked,
        });
    });

    // File uploads
    modal.querySelectorAll('input[type="file"]').forEach(el => {
        const label = el.getAttribute('aria-label') ||
                      el.closest('.jobs-easy-apply-form-section__group, .fb-dash-form-element, div[data-test-form-element]')?.querySelector('label')?.innerText ||
                      'Resume/CV';
        results.push({
            type: 'file',
            name: label.trim().split('\\n')[0].trim(),
            required: el.required,
        });
    });

    // Buttons (English and Spanish)
    const submitBtn = modal.querySelector('button[aria-label*="Submit application"]') ||
                      modal.querySelector('button[aria-label*="Enviar solicitud"]') ||
                      Array.from(modal.querySelectorAll('button')).find(b => {
                          const t = (b.innerText || '').toLowerCase();
                          return t === 'submit' || t === 'enviar solicitud';
                      });

    const nextBtn = modal.querySelector('button[aria-label*="Continue"]') ||
                    modal.querySelector('button[aria-label*="Review"]') ||
                    modal.querySelector('button[aria-label*="Siguiente"]') ||
                    modal.querySelector('button[aria-label*="Revisar"]') ||
                    modal.querySelector('button.artdeco-button--primary') ||
                    Array.from(modal.querySelectorAll('button')).find(b => {
                        const t = (b.innerText || '').toLowerCase();
                        return t === 'next' || t === 'continue' || t === 'review' || t === 'siguiente' || t === 'continuar' || t === 'revisar';
                    });

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


import asyncio

async def human_delay() -> None:
    """Sleep a random duration between min_delay and max_delay from settings."""
    settings = get_settings()
    delay = random.uniform(settings.apply.min_delay, settings.apply.max_delay)
    logger.debug("Human delay: {:.1f}s", delay)
    await asyncio.sleep(delay)


async def _take_debug_screenshot(step_name: str) -> str | None:
    """Take a screenshot for debugging, return path or None."""
    page = get_page()
    if page is None:
        return None
    try:
        path = _ensure_screenshot_dir() / f"{step_name}.png"
        await page.screenshot(path=str(path), full_page=False)
        logger.debug("Screenshot saved: {}", path)
        return str(path)
    except Exception as e:
        logger.debug("Screenshot failed: {}", e)
        return None


async def _get_progress_percentage() -> int | None:
    """Extract progress percentage from the Easy Apply modal (e.g. 'Step 2 of 4 — 50%').

    Returns the percentage as int, or None if not found.
    """
    page = get_page()
    if page is None:
        return None
    try:
        text = await page.evaluate(
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



async def wait_for_jobs() -> None:
    """Wait for job links to load in the split view."""
    page = get_page()
    if page:
        try:
            # Wait for at least one job link to appear
            await page.wait_for_timeout(5000)
            await page.wait_for_selector('a[href*="/jobs/view/"]', timeout=15000)
            await human_delay()
        except Exception:
            pass

async def extract_jobs_list() -> str:
    """Extract job cards from a LinkedIn search results page.

    Returns JSON array of job summaries. Tries multiple selector strategies
    including newer LinkedIn DOM patterns, then falls back to extracting all
    /jobs/view/ links directly from the page.
    """
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    await wait_for_jobs()

    for attempt in range(3):
        try:
            jobs = await page.evaluate(
                r"""
                () => {
                    const seen = new Set();
                    const jobs = [];

                    // Strategy 1: Modern split UI (data-display-contents)
                    const modernCards = Array.from(document.querySelectorAll('div[data-display-contents="true"]')).filter(el => {
                        const text = el.innerText || '';
                        return (text.includes('Solicitud sencilla') || text.includes('Easy Apply') || text.includes('Adelántate') || text.includes('hace') || text.includes('Publicado')) &&
                               text.length > 20 && text.length < 800;
                    });

                    if (modernCards.length > 0) {
                        for (const card of modernCards) {
                            const text = card.innerText.trim();
                            const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                            if (lines.length < 2) continue;

                            let role = lines[0].replace(/^Seleccionado,\s*/i, '').replace(/\s*\(empleo verificado\)/i, '');
                            if (role === 'Seleccionado' || role.length < 3) {
                                role = lines[1] || '';
                            }

                            if (!role || seen.has(role)) continue;
                            seen.add(role);

                            let company = '';
                            let location = '';
                            for (let i = 1; i < lines.length; i++) {
                                const line = lines[i];
                                if (line === role || line.includes('empleo verificado') || line.includes('Seleccionado')) continue;
                                if (!company && !line.includes('Adelántate') && !line.includes('Publicado') && !line.includes('hace') && !line.includes('Solicitud') && !line.includes('Evaluando')) {
                                    company = line;
                                    continue;
                                }
                                if (company && !location && (line.includes('Buenos Aires') || line.includes('Argentina') || line.includes('Remoto') || line.includes('Híbrido') || line.includes('Presencial') || line.includes('alrededores'))) {
                                    location = line;
                                    break;
                                }
                            }

                            const linkEl = card.querySelector('a[href*="currentJobId="], a[href*="/jobs/view/"]');
                            let link = '';
                            let jobId = '';
                            if (linkEl) {
                                link = linkEl.href;
                                const m = link.match(/currentJobId=(\d+)/) || link.match(/view\/(?:.*-)?(\d+)/);
                                if (m) jobId = m[1];
                            }

                            jobs.push({
                                job_id: jobId,
                                role: role,
                                company: company,
                                location: location,
                                link: link || (jobId ? `https://www.linkedin.com/jobs/view/${jobId}/` : ''),
                                easy_apply: text.toLowerCase().includes('solicitud sencilla') || text.toLowerCase().includes('easy apply'),
                                already_applied: text.toLowerCase().includes('solicitado') || text.toLowerCase().includes('applied'),
                            });
                        }

                        if (jobs.length > 0) return jobs;
                    }

                    // Strategy 2: Traditional card selectors
                    const cardSelectors = [
                        'ul.jobs-search__results-list > li',
                        '.scaffold-layout__list-container > li',
                        '.jobs-search-results-list > li',
                        'li:has(a[href*="/jobs/view/"])',
                        '.job-card-container',
                        '.base-card',
                    ];

                    let cards = [];
                    for (const sel of cardSelectors) {
                        const found = document.querySelectorAll(sel);
                        if (found.length > 0) {
                            cards = Array.from(found);
                            break;
                        }
                    }

                    if (cards.length > 0) {
                        for (const card of cards) {
                            const linkEl = card.querySelector('a[href*="/jobs/view/"]') || card.querySelector('a');
                            if (!linkEl) continue;

                            const href = linkEl.href.split('?')[0];
                            const idMatch = href.match(/view\/(?:.*-)?(\d+)/) || href.match(/(\d{8,12})/);
                            const jobId = idMatch ? idMatch[1] : '';
                            if (!jobId || seen.has(jobId)) continue;
                            seen.add(jobId);

                            const titleEl = card.querySelector('.base-search-card__title') ||
                                            card.querySelector('.job-card-list__title--link') ||
                                            card.querySelector('.job-card-list__title') ||
                                            card.querySelector('h3') ||
                                            card.querySelector('h4') ||
                                            card.querySelector('strong') ||
                                            linkEl;
                            const role = titleEl ? titleEl.innerText.trim() : '';

                            const companyEl = card.querySelector('.base-search-card__subtitle') ||
                                              card.querySelector('.job-card-container__primary-description') ||
                                              card.querySelector('.job-card-container__company-name') ||
                                              card.querySelector('.artdeco-entity-lockup__subtitle') ||
                                              card.querySelector('h4.base-search-card__subtitle a') ||
                                              card.querySelector('[class*="company"]') ||
                                              card.querySelector('[class*="subtitle"]');
                            const company = companyEl ? companyEl.innerText.trim() : '';

                            const locationEl = card.querySelector('.job-search-card__location') ||
                                               card.querySelector('.job-card-container__metadata-item') ||
                                               card.querySelector('.artdeco-entity-lockup__caption') ||
                                               card.querySelector('.job-card-container__location') ||
                                               card.querySelector('[class*="location"]') ||
                                               card.querySelector('[class*="caption"]');
                            const location = locationEl ? locationEl.innerText.trim() : '';

                            const cardText = card.innerText.toLowerCase();
                            const easyApply = cardText.includes('solicitud sencilla') ||
                                              cardText.includes('easy apply') ||
                                              !!card.querySelector('.job-card-container__apply-method') ||
                                              !!card.querySelector('[data-testid="job-card-list-item__easy-apply"]') ||
                                              !!card.querySelector('[class*="easy-apply"]');

                            const alreadyApplied = cardText.includes('solicitado') ||
                                                   cardText.includes('applied') ||
                                                   !!card.querySelector('.jobs-search-results-list__state-message') ||
                                                   !!card.querySelector('.artdeco-inline-feedback');

                            if (role) {
                                jobs.push({
                                    job_id: jobId,
                                    role: role,
                                    company: company,
                                    location: location,
                                    link: href,
                                    easy_apply: easyApply,
                                    already_applied: alreadyApplied,
                                });
                            }
                        }
                    }

                    // Strategy 3: Fallback direct links
                    if (jobs.length === 0) {
                        const links = Array.from(document.querySelectorAll('a[href*="/jobs/view/"], a[href*="currentJobId="]'));
                        for (const link of links) {
                            const href = link.href.split('?')[0];
                            const idMatch = href.match(/view\/(?:.*-)?(\d+)/) || href.match(/currentJobId=(\d+)/) || href.match(/(\d{8,12})/);
                            const jobId = idMatch ? idMatch[1] : '';
                            if (!jobId || seen.has(jobId)) continue;
                            seen.add(jobId);

                            const card = link.closest('li') || link.parentElement;
                            const role = link.innerText.trim() || link.getAttribute('aria-label') || '';
                            const cardText = card ? card.innerText.toLowerCase() : '';

                            if (role) {
                                jobs.push({
                                    job_id: jobId,
                                    role: role,
                                    company: '',
                                    location: '',
                                    link: href,
                                    easy_apply: cardText.includes('solicitud sencilla') || cardText.includes('easy apply'),
                                    already_applied: cardText.includes('solicitado') || cardText.includes('applied'),
                                });
                            }
                        }
                    }

                    return jobs;
                }
                """
            )
            return json.dumps(jobs, indent=2)
        except Exception as e:
            if attempt == 2:
                return json.dumps({"error": str(e)})
            await page.wait_for_timeout(2000)


async def extract_job_details() -> str:
    """Extract detailed job info from the current LinkedIn job page."""
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    try:
        job = await page.evaluate(
            r"""
            () => {
                // 1. Title
                let title = '';
                const titleEl = document.querySelector('h1.top-card-layout__title') ||
                                document.querySelector('h1.topcard__title') ||
                                document.querySelector('h1.job-details-jobs-unified-top-card__job-title') ||
                                document.querySelector('.jobs-unified-top-card__job-title') ||
                                document.querySelector('h1.t-24') ||
                                document.querySelector('h2.t-24') ||
                                document.querySelector('h1');
                if (titleEl) {
                    title = titleEl.innerText.trim();
                }

                // 2. Company
                let company = '';
                const companyEl = document.querySelector('a.topcard__org-name-link') ||
                                  document.querySelector('span.topcard__flavor:not(.topcard__flavor--bullet)') ||
                                  document.querySelector('.job-details-jobs-unified-top-card__company-name a') ||
                                  document.querySelector('.job-details-jobs-unified-top-card__company-name') ||
                                  document.querySelector('.jobs-unified-top-card__company-name a') ||
                                  document.querySelector('.jobs-unified-top-card__company-name') ||
                                  document.querySelector('.artdeco-entity-lockup__subtitle a') ||
                                  document.querySelector('.artdeco-entity-lockup__subtitle') ||
                                  document.querySelector('a[href*="/company/"]');
                if (companyEl) {
                    company = companyEl.innerText.trim().split('\n')[0].trim();
                }

                // 3. Location
                let location = '';
                const locationEl = document.querySelector('span.topcard__flavor--bullet') ||
                                   document.querySelector('.job-details-jobs-unified-top-card__bullet') ||
                                   document.querySelector('.jobs-unified-top-card__bullet') ||
                                   document.querySelector('.job-details-jobs-unified-top-card__primary-description') ||
                                   document.querySelector('.artdeco-entity-lockup__caption') ||
                                   document.querySelector('span.main-job-card__location');
                if (locationEl) {
                    location = locationEl.innerText.trim().split('\n')[0].trim();
                }

                // 4. Description
                let description = '';
                const descEl = document.querySelector('.jobs-description__content') ||
                               document.querySelector('.jobs-description') ||
                               document.querySelector('.description__text') ||
                               document.querySelector('.show-more-less-html__markup') ||
                               document.querySelector('.jobs-box__html-content') ||
                               document.querySelector('#job-details') ||
                               document.querySelector('article');
                if (descEl) {
                    description = descEl.innerText.trim();
                } else {
                    // Fallback to text matching "Acerca del empleo" / "About the job"
                    const pageText = document.body ? document.body.innerText : '';
                    const match = pageText.match(/(?:Acerca del empleo|About the job|Summary)[\s\S]{50,4000}/i);
                    if (match) {
                        description = match[0].trim();
                    }
                }

                // 5. Easy Apply button detection
                const easyApplyBtn = document.querySelector('button.jobs-apply-button') ||
                                     document.querySelector('button.apply-button--easy-apply') ||
                                     document.querySelector('button[aria-label*="Easy Apply"]') ||
                                     document.querySelector('button[aria-label*="Solicitud sencilla"]') ||
                                     document.querySelector('button[data-is-easy-apply="true"]') ||
                                     Array.from(document.querySelectorAll('button')).find(b => {
                                         const t = (b.innerText || '').toLowerCase();
                                         return t.includes('solicitud sencilla') || t.includes('easy apply');
                                     });

                // Detect "already applied" state
                const appliedBanner = document.querySelector('.jobs-apply-button--disabled') ||
                                      document.querySelector('.artdeco-inline-feedback--success');
                const alreadyApplied = !!(appliedBanner) ||
                    (easyApplyBtn && easyApplyBtn.disabled) ||
                    (easyApplyBtn && (easyApplyBtn.innerText.includes('Applied') || easyApplyBtn.innerText.includes('Solicitado')));

                const recruiter = document.querySelector('.jobs-search__organizer-link') ||
                                  document.querySelector('a[data-tracking-control-name="public_jobs_jobs-search-result-1"]');

                return {
                    role: title,
                    company: company,
                    location: location,
                    description: description,
                    easy_apply: !!easyApplyBtn,
                    already_applied: !!alreadyApplied,
                    recruiter: recruiter ? recruiter.href : '',
                    url: window.location.href,
                };
            }
            """
        )

        return json.dumps(job, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def click_easy_apply() -> str:
    """Click the Easy Apply button with multi-layer selector fallbacks.

    Returns 'clicked', 'already_applied', or 'error: ...'.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    await _take_debug_screenshot("easy_apply_before_click")

    try:
        selectors = [
            'button.jobs-apply-button',
            'button.apply-button--easy-apply',
            'button.apply-button',
            'button[aria-label*="Easy Apply"]',
            'button[aria-label*="Solicitud sencilla"]',
            'button.artdeco-button--primary:has-text("Easy Apply")',
            'button.artdeco-button--primary:has-text("Solicitud sencilla")',
            'button:has-text("Easy Apply")',
            'button:has-text("Solicitud sencilla")',
            'button:has-text("Solicitar")',
            'button[aria-label*="Apply"]',
            'button[aria-label*="Solicitar"]',
            'button[class*="apply-button"]',
        ]

        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=3000):
                    btn_text = await btn.inner_text(timeout=2000)
                    btn_text_lower = btn_text.lower()
                    is_disabled = await btn.is_disabled()

                    if is_disabled or "applied" in btn_text_lower or "solicitado" in btn_text_lower:
                        logger.info("Already applied to this job")
                        return "already_applied"

                    await btn.click(timeout=5000)
                    await human_delay()
                    await _take_debug_screenshot("easy_apply_after_click")
                    return "clicked"
            except Exception:
                continue

        return "error: Easy Apply button not found"
    except Exception as e:
        return f"error: {e}"


async def detect_form_fields() -> str:
    """Detect and auto-fill form fields in the current Easy Apply modal.

    Returns JSON with fields, filled_by_autofill, has_submit/has_next, progress percentage, and total_fields.
    """
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    # Run autofill first
    try:
        from hawk.linkedin.autofill import auto_fill_current_step
        autofill_res = await auto_fill_current_step()
    except Exception as e:
        logger.debug("Autofill step note: {}", e)
        autofill_res = {}

    progress = await _get_progress_percentage()

    try:
        fields = await page.evaluate(_DETECT_FIELDS_JS)

        # Add follow checkbox detection
        follow_result = await page.evaluate("""
            () => {
                const modal = document.querySelector('.jobs-easy-apply-modal') ||
                              document.querySelector('[role="dialog"]') ||
                              document.querySelector('.artdeco-modal');
                if (!modal) return {has_follow_checkbox: false, follow_checked: false};
                const followCheckbox = modal.querySelector('input[name="followCompany"]') ||
                                       modal.querySelector('[data-follow-company]') ||
                                       Array.from(modal.querySelectorAll('input[type="checkbox"]')).find(cb => {
                                           const l = (cb.closest('label')?.innerText || '').toLowerCase();
                                           return l.includes('seguir') || l.includes('follow');
                                       });
                return {
                    has_follow_checkbox: !!followCheckbox,
                    follow_checked: followCheckbox ? followCheckbox.checked : false,
                };
            }
        """)
        fields.update(follow_result)
        fields["autofill_filled"] = autofill_res.get("filled", [])
        fields["autofill_unknown"] = autofill_res.get("unknown_required", [])

        if progress is not None:
            fields["progress_percent"] = progress

        await _take_debug_screenshot("detect_fields")
        return json.dumps(fields, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def detect_fields_with_profile() -> str:
    """Detect form fields and match them against the user profile.

    Same as detect_form_fields but adds 'profile_value' to each field
    when a match is found. Also identifies fields that need human input.
    """
    from hawk.profile import load_profile, match_field

    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    profile = load_profile()
    progress = await _get_progress_percentage()

    try:
        raw = await page.evaluate(_DETECT_FIELDS_JS)

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

        await _take_debug_screenshot("detect_fields_with_profile")
        return json.dumps(raw, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def unfollow_company() -> str:
    """Uncheck the 'Follow [Company]' checkbox if it's checked.

    Returns 'unchecked', 'not_found', or 'error: ...'.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        result = await page.evaluate(
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
            await human_delay()
        return result
    except Exception as e:
        return f"error: {e}"


async def click_next_or_submit() -> str:
    """Click Next/Continue/Submit in the Easy Apply wizard.

    Checks Submit before Next (proper priority). Returns which button was clicked.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        # 1. Direct DOM autofill for select dropdowns and text inputs in active modal
        await page.evaluate("""
            () => {
                const modal = document.querySelector('.jobs-easy-apply-modal') ||
                              document.querySelector('[role="dialog"]') ||
                              document.querySelector('.artdeco-modal') ||
                              document.body;
                if (!modal) return;

                // Auto-select Argentina in any Country dropdown
                const selects = Array.from(modal.querySelectorAll('select'));
                for (const sel of selects) {
                    for (let i = 0; i < sel.options.length; i++) {
                        const optText = sel.options[i].text.trim().toLowerCase();
                        if (optText === 'argentina' || optText.includes('argentina') || sel.options[i].value === 'ar') {
                            sel.selectedIndex = i;
                            sel.options[i].selected = true;
                            sel.value = sel.options[i].value;
                            sel.dispatchEvent(new Event('input', { bubbles: true }));
                            sel.dispatchEvent(new Event('change', { bubbles: true }));
                            sel.dispatchEvent(new Event('blur', { bubbles: true }));
                            break;
                        }
                    }
                }

                // Auto-fill LinkedIn and Portfolio URLs
                const inputs = Array.from(modal.querySelectorAll('input[type="text"], input:not([type])'));
                for (const inp of inputs) {
                    const parent = inp.closest('.jobs-easy-apply-form-section__group, .fb-dash-form-element, div[data-test-form-element]') || inp.parentElement;
                    const label = ((parent ? parent.querySelector('label')?.innerText : '') || inp.getAttribute('aria-label') || inp.placeholder || inp.name || '').toLowerCase();
                    
                    if (label.includes('linkedin') && (!inp.value || inp.value.trim() === '')) {
                        inp.value = 'https://www.linkedin.com/in/lflamonega';
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                    } else if ((label.includes('portfolio') || label.includes('github') || label.includes('web')) && (!inp.value || inp.value.trim() === '')) {
                        inp.value = 'https://github.com/lflamonega';
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }
        """)
        await asyncio.sleep(0.8)

        # Priority: Submit first, then Next/Continue/Review
        selectors = [
            ("submit", 'button[aria-label*="Submit application"]'),
            ("submit", 'button[aria-label*="Enviar solicitud"]'),
            ("submit", 'button:has-text("Submit")'),
            ("submit", 'button:has-text("Enviar solicitud")'),
            ("submit", 'button:has-text("Enviar")'),
            ("next", 'button[aria-label*="Continue"]'),
            ("next", 'button[aria-label*="Review"]'),
            ("next", 'button[aria-label*="Siguiente"]'),
            ("next", 'button[aria-label*="Revisar"]'),
            ("next", 'button.artdeco-button--primary'),
            ("next", 'button:has-text("Next")'),
            ("next", 'button:has-text("Continue")'),
            ("next", 'button:has-text("Review")'),
            ("next", 'button:has-text("Siguiente")'),
            ("next", 'button:has-text("Continuar")'),
            ("next", 'button:has-text("Revisar")'),
        ]

        for action, selector in selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click(timeout=3000)
                    await human_delay()
                    await _take_debug_screenshot(f"after_{action}_click")
                    return f"clicked_{action}"
            except Exception:
                continue

        return "no_button_found"
    except Exception as e:
        return f"error: {e}"


async def submit_application() -> str:
    """Submit the Easy Apply application.

    1. Unfollow company if checkbox is checked
    2. Check dry_run — if true, do NOT click Submit
    3. Click Submit
    4. Verify submission by checking modal closed
    """
    settings = get_settings()
    if settings.apply.dry_run:
        logger.info("Dry run mode — skipping actual submission")
        await _take_debug_screenshot("dry_run_before_submit")
        return "dry_run_blocked"

    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        # Unfollow company before submitting
        await unfollow_company()

        btn = page.locator('button[aria-label="Submit application"]').first
        await btn.click(timeout=5000)
        await human_delay()

        # Verify submission succeeded — check modal closed
        try:
            modal = page.locator('.jobs-easy-apply-modal, [role="dialog"], .artdeco-modal').first
            await modal.wait_for(state="hidden", timeout=5000)
            logger.info("Submit verified: modal closed")
        except Exception:
            # Modal might still be open — check for success message
            success = page.locator('.artdeco-inline-feedback--success, .jobs-succeeded-apply-message').first
            if await success.is_visible(timeout=2000):
                logger.info("Submit verified: success message shown")
            else:
                logger.warning("Submit verification inconclusive — modal state unknown")

        await _take_debug_screenshot("after_submit")
        await save_session()
        return "submitted"
    except Exception as e:
        return f"error: {e}"


async def get_page_text() -> str:
    """Get the visible text content of the current page."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        text = await page.evaluate("() => document.body.innerText")
        return text[:10000]
    except Exception as e:
        return f"error: {e}"


async def navigate_to_url(url: str) -> str:
    """Navigate to a URL and return the page title + URL."""
    page = get_page()
    if page is None:
        return "error: Browser not started. Call browser_launch first."

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await human_delay()
        return f"Navigated to: {page.url}\nTitle: {await page.title()}"
    except Exception as e:
        return f"error: {e}"


async def search_and_navigate(
    positions: str = "",
    locations: str = "",
    easy_apply: bool = True,
) -> str:
    """Build a LinkedIn search URL and navigate to it."""
    url = build_search_url(positions, locations, easy_apply)
    return await navigate_to_url(url)


def generate_job_id(link: str) -> str:
    """Generate a short job ID from a LinkedIn job URL."""
    return hashlib.md5(link.encode()).hexdigest()[:10]
