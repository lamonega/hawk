"""LinkedIn-specific browser operations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

from hawk.browser.driver import get_page, save_session
try:
    from hawk.browser.driver import dismiss_guest_overlays
except ImportError:
    async def dismiss_guest_overlays(page: Any = None) -> bool:
        p = page or get_page()
        if p is None:
            return False
        for sel in [
            'button[aria-label="Descartar"]', 'button[aria-label="Dismiss"]',
            'button[aria-label="Cerrar"]', 'button[aria-label="Close"]',
            '.contextual-sign-in-modal__modal-dismiss-btn', '.modal__dismiss-btn',
            'button.artdeco-modal__dismiss', '[data-test-modal-close-btn]',
            'button[data-tracking-control-name="public_jobs_contextual-sign-in-modal_sign-in-modal_dismiss"]',
        ]:
            try:
                loc = p.locator(sel).first
                if await loc.is_visible(timeout=500):
                    is_apply = await loc.evaluate("el => !!el.closest('.jobs-easy-apply-modal, [data-test-modal-id=\"easy-apply-modal\"], [data-testid=\"easy-apply-modal\"]')")
                    if not is_apply:
                        await loc.click(force=True)
                        await asyncio.sleep(0.5)
            except Exception:
                pass
        return False
from hawk.settings import get_settings

SCREENSHOT_DIR = Path("output/screenshots")

# Shared JS helper to locate Easy Apply form root (inline card in SDUi lazy-column or dialog modal)
_EASY_APPLY_ROOT_JS = r"""
function easyApplyRoot() {
    const dlg = document.querySelector('[role="dialog"]');
    if (dlg && (dlg.querySelector('input, select, textarea, [role="radio"], button[aria-label*="Enviar"], button[aria-label*="Submit"], button[aria-label*="Continue"], button[aria-label*="Siguiente"]') || dlg.classList.contains('jobs-easy-apply-modal') || dlg.classList.contains('artdeco-modal'))) {
        return dlg;
    }
    const modalOld = document.querySelector('.jobs-easy-apply-modal, div[data-test-modal-id="easy-apply-modal"], .artdeco-modal');
    if (modalOld) return modalOld;

    const col = document.querySelector('[data-testid="lazy-column"]') || document.querySelector('#lazy-column');
    if (col) {
        for (const card of col.children) {
            const t = (card.innerText || '').trim().toLowerCase();
            const isStep = /^(contact info|datos de contacto|experience|experiencia|legal|información legal|additional questions|preguntas adicionales|review|revisar|submit|confirmar|home address|dirección|education|educación|work authorization|autorización|resume|currículum|cv)/i.test(t)
                           || /^paso \d/i.test(t)
                           || /^step \d/i.test(t);
            if (isStep && card.querySelector('input, select, textarea, [role="radio"]')) {
                return card;
            }
        }
    }
    return document.body;
}
"""

# Shared JS for detecting form fields in Easy Apply modals
_DETECT_FIELDS_JS = r"""
() => {
""" + _EASY_APPLY_ROOT_JS + r"""
    const results = [];
    const root = easyApplyRoot();

    // Helper: find clean human-readable label text for an element
    function getCleanLabel(el, idx) {
        if (!el) return `Field ${idx}`;
        
        // 1. Label tag associated by ID
        if (el.id) {
            try {
                const labelFor = document.querySelector(`label[for="${el.id}"]`);
                if (labelFor && labelFor.innerText.trim()) {
                    return labelFor.innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                }
            } catch(e) {}
        }

        // 2. Native HTML5 labels
        if (el.labels && el.labels[0] && el.labels[0].innerText.trim()) {
            return el.labels[0].innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
        }

        // 3. aria-labelledby target elements
        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
            const parts = labelledBy.split(' ');
            let combined = '';
            for (const id of parts) {
                const target = document.getElementById(id);
                if (target && target.innerText.trim()) {
                    combined += ' ' + target.innerText.trim();
                }
            }
            if (combined.trim()) {
                return combined.split('\n')[0].replace(/\s+/g, ' ').trim();
            }
        }

        // 4. aria-label attribute
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel && ariaLabel.trim()) {
            return ariaLabel.split('\n')[0].replace(/\s+/g, ' ').trim();
        }

        // 5. Parent container query
        const parent = el.closest(
            'div._85ba3e52, .jobs-easy-apply-form-section__group, .fb-dash-form-element, ' +
            'div[data-test-form-element], div[data-test-single-line-text-form-component], ' +
            'div[data-test-form-builder-text-input], div[data-test-dropdown-form-component], ' +
            'div[data-test-form-builder-radio-button-form-component], ' +
            'div[data-test-text-entity-list-form-component], div.jobs-easy-apply-form-element, ' +
            'fieldset, div.artdeco-text-input--container'
        ) || el.parentElement;

        if (parent) {
            const labelEl = parent.querySelector('label, legend, .fb-dash-form-element__label, .artdeco-text-input--label, span.t-14, p, h3');
            if (labelEl && labelEl.innerText.trim()) {
                return labelEl.innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
            }
        }

        // 6. Placeholder / Title / Name fallback
        const placeholder = el.getAttribute('placeholder') || el.getAttribute('title') || el.name || '';
        if (placeholder.trim()) {
            return placeholder.split('\n')[0].replace(/\s+/g, ' ').trim();
        }

        return `Field ${idx} (${el.type || el.tagName.toLowerCase()})`;
    }

    let fieldIndex = 0;

    // Text inputs (scoped to root)
    root.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], input[type="number"], input[type="url"], input:not([type])').forEach(el => {
        fieldIndex++;
        const label = getCleanLabel(el, fieldIndex);
        const isCombobox = el.getAttribute('role') === 'combobox' || !!el.closest('[data-test-text-entity-list-form-component]');
        results.push({
            type: isCombobox ? 'combobox' : 'text',
            name: label,
            required: el.required || el.getAttribute('aria-required') === 'true' || label.includes('*'),
            value: el.value || '',
            input_type: el.type || 'text',
            id: el.id || '',
        });
    });

    // Textareas (scoped to root)
    root.querySelectorAll('textarea').forEach(el => {
        fieldIndex++;
        const label = getCleanLabel(el, fieldIndex);
        results.push({
            type: 'textarea',
            name: label,
            required: el.required || el.getAttribute('aria-required') === 'true' || label.includes('*'),
            value: el.value || '',
            id: el.id || '',
        });
    });

    // Native Selects (scoped to root)
    root.querySelectorAll('select').forEach(el => {
        fieldIndex++;
        const label = getCleanLabel(el, fieldIndex);
        const allOpts = Array.from(el.options).map(o => ({value: o.value, text: o.text.trim()}));
        const totalCount = allOpts.length;
        let options = allOpts;
        if (totalCount > 20) {
            const selectedOpt = el.selectedIndex >= 0 ? allOpts[el.selectedIndex] : null;
            const preview = allOpts.slice(0, 5);
            if (selectedOpt && !preview.some(p => p.value === selectedOpt.value)) {
                preview.unshift(selectedOpt);
            }
            options = preview;
        }
        results.push({
            type: 'select',
            name: label,
            required: el.required || el.getAttribute('aria-required') === 'true' || label.includes('*'),
            value: el.value || '',
            selected_text: el.selectedIndex >= 0 && el.options[el.selectedIndex] ? el.options[el.selectedIndex].text.trim() : '',
            options: options,
            total_options: totalCount,
            id: el.id || '',
        });
    });

    // Radios (scoped to root)
    const radioGroups = {};
    root.querySelectorAll('input[type="radio"]').forEach(el => {
        const parent = el.closest('fieldset, .fb-dash-form-element, div[data-test-form-builder-radio-button-form-component]') || el.parentElement;
        const groupKey = el.name || (parent ? parent.innerText.slice(0, 30) : `radio_${fieldIndex}`);
        
        if (!radioGroups[groupKey]) {
            fieldIndex++;
            const groupLegend = (parent ? parent.querySelector('legend, label, .fb-dash-form-element__label')?.innerText : '') || getCleanLabel(el, fieldIndex);
            radioGroups[groupKey] = {
                type: 'radio',
                name: groupLegend.split('\n')[0].replace(/\s+/g, ' ').trim(),
                required: true,
                options: [],
                group_name: el.name || '',
            };
        }
        
        const optionLabel = el.closest('label')?.innerText ||
                            (el.id ? document.querySelector(`label[for="${el.id}"]`)?.innerText : '') ||
                            el.nextElementSibling?.innerText || el.value || '';
        radioGroups[groupKey].options.push({
            value: el.value || '',
            text: optionLabel.split('\n')[0].replace(/\s+/g, ' ').trim(),
            checked: el.checked,
        });
    });
    results.push(...Object.values(radioGroups));

    // Checkboxes (scoped to root)
    root.querySelectorAll('input[type="checkbox"]').forEach(el => {
        fieldIndex++;
        const label = getCleanLabel(el, fieldIndex);
        const isFollow = label.toLowerCase().includes('follow') || label.toLowerCase().includes('seguir') || (el.name && el.name.toLowerCase().includes('follow'));
        results.push({
            type: 'checkbox',
            name: label,
            required: el.required || el.getAttribute('aria-required') === 'true',
            checked: el.checked,
            is_follow_company: isFollow,
            id: el.id || '',
        });
    });

    // File uploads (scoped to root)
    root.querySelectorAll('input[type="file"]').forEach(el => {
        fieldIndex++;
        const label = getCleanLabel(el, fieldIndex);
        results.push({
            type: 'file',
            name: label || 'Resume/CV',
            required: el.required || el.getAttribute('aria-required') === 'true',
            id: el.id || '',
        });
    });

    // Buttons (English, Spanish, Portuguese, French, German, Italian) — search DOCUMENT scope
    const submitBtn = document.querySelector('button[aria-label*="Submit application"]') ||
                      document.querySelector('button[aria-label*="Enviar solicitud"]') ||
                      document.querySelector('button[aria-label*="Enviar candidatura"]') ||
                      document.querySelector('button[aria-label*="Bewerbung senden"]') ||
                      document.querySelector('button[aria-label*="Invia candidatura"]') ||
                      Array.from(document.querySelectorAll('button')).find(b => {
                          const t = (b.innerText || '').toLowerCase().trim();
                          return t === 'submit' || t === 'submit application' || 
                                 t === 'enviar solicitud' || t === 'enviar' || 
                                 t === 'enviar candidatura' || t === 'candidatar-se' ||
                                 t === 'soumettre' || t === 'bewerbung senden' || t === 'bewerben' ||
                                 t === 'invia candidatura';
                      });

    const nextBtn = document.querySelector('button[aria-label*="Continue"]') ||
                    document.querySelector('button[aria-label*="Review"]') ||
                    document.querySelector('button[aria-label*="Next"]') ||
                    document.querySelector('button[aria-label*="Siguiente"]') ||
                    document.querySelector('button[aria-label*="Continuar"]') ||
                    document.querySelector('button[aria-label*="Revisar"]') ||
                    document.querySelector('button[aria-label*="Avançar"]') ||
                    document.querySelector('button[aria-label*="Suivant"]') ||
                    document.querySelector('button[aria-label*="Weiter"]') ||
                    document.querySelector('button.artdeco-button--primary') ||
                    Array.from(document.querySelectorAll('button')).find(b => {
                        const t = (b.innerText || '').toLowerCase().trim();
                        return t === 'next' || t === 'continue' || t === 'review' || t === 'review your application' ||
                               t === 'siguiente' || t === 'continuar' || t === 'revisar' || t === 'revisar solicitud' ||
                               t === 'avançar' || t === 'seguinte' || t === 'suivant' || t === 'weiter' || t === 'avanti';
                    });

    const backBtn = document.querySelector('button[aria-label*="Back"]') ||
                    document.querySelector('button[aria-label*="Previous"]') ||
                    document.querySelector('button[aria-label*="Volver"]') ||
                    document.querySelector('button[aria-label*="Anterior"]') ||
                    Array.from(document.querySelectorAll('button')).find(b => {
                        const t = (b.innerText || '').toLowerCase().trim();
                        return t === 'back' || t === 'previous' || t === 'volver' || t === 'anterior' || t === 'zurück' || t === 'retour';
                    });

    // Validation errors currently shown
    const errors = Array.from(root.querySelectorAll('.artdeco-inline-feedback--error, [data-test-form-element-error-messages], .fb-dash-form-element__error-message, [data-testid="text-input-helper-text"], [role="alert"]'))
                        .map(e => e.innerText.trim()).filter(e => e.length > 0);

    return {
        fields: results,
        has_submit: !!submitBtn,
        has_next: !!nextBtn,
        has_back: !!backBtn,
        total_fields: results.length,
        errors: errors,
    };
}
"""


def _ensure_screenshot_dir() -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_DIR


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
    """Extract progress percentage from the Easy Apply modal or form.

    Checks aria-valuenow on progressbars, percentage strings, or step counts (e.g. 'Step 2 of 4').
    """
    page = get_page()
    if page is None:
        return None
    try:
        data = await page.evaluate(
            r"""
            () => {
            """
            + _EASY_APPLY_ROOT_JS
            + r"""
                const root = easyApplyRoot();
                if (!root) return { valuenow: null, text: '' };

                const bar = root.querySelector('div[role="progressbar"], progress, .artdeco-completeness-meter-bar');
                const valuenow = bar ? (bar.getAttribute('aria-valuenow') || bar.value) : null;
                return {
                    valuenow: valuenow ? parseInt(valuenow) : null,
                    text: root.innerText || ''
                };
            }
            """
        )
        if data.get("valuenow") is not None:
            return data["valuenow"]

        text = data.get("text", "")
        # Check percentage string "50%"
        match_pct = re.search(r"(\d{1,3})%", text)
        if match_pct:
            return int(match_pct.group(1))

        # Check step count "Step 2 of 4" or "Paso 1 de 3"
        match_step = re.search(r"(?:Step|Paso|Étape|Schritt)\s+(\d+)\s+(?:of|de|von|d'|di)\s+(\d+)", text, re.IGNORECASE)
        if match_step:
            current, total = int(match_step.group(1)), int(match_step.group(2))
            if total > 0:
                return int((current / total) * 100)

        return None
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
    """Wait for job cards or links to load on the search page."""
    page = get_page()
    if not page:
        return

    await dismiss_guest_overlays(page)

    job_selectors = [
        '[data-testid="lazy-column"]',
        '#lazy-column',
        '[componentkey^="job-card-component-ref-"]',
        'li[data-occludable-job-id]',
        'div.job-card-container',
        'div.jobs-search-results-list',
        '.scaffold-layout__list',
        'a[href*="/jobs/view/"]',
        'a[href*="currentJobId="]',
        '.base-card',
    ]
    for sel in job_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=2500):
                logger.debug("Found job results container with: {}", sel)
                break
        except Exception:
            continue

    # Smoothly scroll down the list container to trigger lazy-loaded cards
    try:
        await page.evaluate("""
            () => {
                const list = document.querySelector('[data-testid="lazy-column"]') ||
                             document.querySelector('#lazy-column') ||
                             document.querySelector('.jobs-search-results-list') ||
                             document.querySelector('.scaffold-layout__list') ||
                             document.querySelector('div.scaffold-layout__list-container');
                if (list && list.scrollBy) {
                    list.scrollBy(0, 600);
                }
                window.scrollBy(0, 600);
            }
        """)
        await asyncio.sleep(1.0)
    except Exception:
        pass


async def extract_jobs_list() -> str:
    """Extract job cards from a LinkedIn search results page.

    Returns JSON array of job summaries. Automatically scrolls to load virtualized
    cards and applies modern SDUi 2026 and legacy LinkedIn DOM parsing.
    """
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    await wait_for_jobs()

    # Auto-scroll the results container 3 times to trigger virtualized cards
    for _ in range(3):
        try:
            await page.evaluate("""
                () => {
                    const list = document.querySelector('[data-testid="lazy-column"]') ||
                                 document.querySelector('#lazy-column') ||
                                 document.querySelector('.jobs-search-results-list') ||
                                 document.querySelector('.scaffold-layout__list') ||
                                 document.querySelector('div.scaffold-layout__list-container');
                    if (list && list.scrollBy) {
                        list.scrollBy(0, 500);
                    }
                    window.scrollBy(0, 500);
                }
            """)
            await asyncio.sleep(0.5)
        except Exception:
            break

    for attempt in range(3):
        try:
            jobs = await page.evaluate(
                r"""
                () => {
                    const seen = new Set();
                    const jobs = [];

                    function cleanRole(text) {
                        if (!text) return '';
                        return text
                            .replace(/^Seleccionado,\s*/i, '')
                            .replace(/^Selected,\s*/i, '')
                            .replace(/\s*\(empleo verificado\)/gi, '')
                            .replace(/\s*\(verified job\)/gi, '')
                            .replace(/\s*·\s*contrataci[oó]n activa/gi, '')
                            .replace(/\s*·\s*actively recruiting/gi, '')
                            .replace(/\s*·\s*promoted/gi, '')
                            .replace(/\s*·\s*promocionado/gi, '')
                            .split('\n')[0]
                            .replace(/\s+/g, ' ')
                            .trim();
                    }

                    // 1. SDUi 2026 cards with componentkey
                    const cardEls = document.querySelectorAll('[componentkey^="job-card-component-ref-"]');
                    for (const el of cardEls) {
                        const ck = el.getAttribute('componentkey') || '';
                        const m = ck.match(/job-card-component-ref-(\d+)/);
                        if (!m) continue;
                        const jobId = m[1];
                        if (seen.has(jobId)) continue;
                        seen.add(jobId);

                        // Card container: the element itself or closest ancestor card
                        const card = el.closest('div._1e5cedba') || el.closest('div[role="button"]') || el;

                        // Role / Title: span[aria-hidden="true"] or span._4da622bc
                        let role = '';
                        const hiddenSpan = card.querySelector('span[aria-hidden="true"]');
                        if (hiddenSpan && hiddenSpan.innerText.trim()) {
                            role = cleanRole(hiddenSpan.innerText);
                        }
                        if (!role) {
                            const vhSpan = card.querySelector('span._4da622bc') || card.querySelector('p');
                            if (vhSpan) role = cleanRole(vhSpan.innerText);
                        }

                        // Company & Location in div.ced15e10
                        let company = '';
                        let location = '';
                        const infoDiv = card.querySelector('div.ced15e10') || card;
                        const pList = infoDiv.querySelectorAll('p');
                        if (pList.length >= 2) {
                            company = pList[0].innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                            location = pList[1].innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                        } else if (pList.length === 1) {
                            company = pList[0].innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                        }

                        // Easy apply & already applied
                        const cardText = card.innerText.toLowerCase();
                        const easyApply = cardText.includes('solicitud sencilla') ||
                                          cardText.includes('easy apply') ||
                                          cardText.includes('candidatura sencilla') ||
                                          cardText.includes('candidatura fácil') ||
                                          !!card.querySelector('svg#linkedin-bug-small');

                        const alreadyApplied = cardText.includes('solicitado') ||
                                               cardText.includes('applied') ||
                                               cardText.includes('candidatura enviada') ||
                                               cardText.includes('ya has solicitado');

                        if (role) {
                            jobs.push({
                                job_id: jobId,
                                role: role,
                                company: company,
                                location: location,
                                link: `https://www.linkedin.com/jobs/view/${jobId}/`,
                                easy_apply: easyApply,
                                already_applied: alreadyApplied,
                            });
                        }
                    }

                    // 2. Fallback: standard and legacy card containers if no SDUi cards found
                    if (jobs.length === 0) {
                        const cardSelectors = [
                            'li[data-occludable-job-id]',
                            'li.jobs-search-results__list-item',
                            'li.scaffold-layout__list-item',
                            'div.job-card-container',
                            'div.job-card-list',
                            'div[data-job-id]',
                            'div[data-view-name="job-card"]',
                            'ul.jobs-search__results-list > li',
                            '.scaffold-layout__list-container > li',
                            '.base-card',
                            'div[data-display-contents="true"]:has(a[href*="/jobs/view/"])',
                            'div[data-display-contents="true"]:has(a[href*="currentJobId="])',
                        ];

                        let rawCards = [];
                        for (const sel of cardSelectors) {
                            const found = document.querySelectorAll(sel);
                            if (found.length > 0) {
                                rawCards = Array.from(found);
                                break;
                            }
                        }

                        for (const card of rawCards) {
                            let jobId = card.getAttribute('data-job-id') ||
                                        card.getAttribute('data-occludable-job-id') ||
                                        '';
                            
                            const linkEl = card.querySelector('a.job-card-list__title--link') ||
                                           card.querySelector('a.job-card-container__link') ||
                                           card.querySelector('a.job-card-list__title') ||
                                           card.querySelector('a[href*="/jobs/view/"]') ||
                                           card.querySelector('a[href*="currentJobId="]') ||
                                           card.querySelector('a');

                            let link = '';
                            if (linkEl) {
                                link = linkEl.href;
                                if (!jobId) {
                                    const m = link.match(/currentJobId=(\d+)/) ||
                                              link.match(/\/jobs\/view\/(?:[^\/]+-)?(\d+)/) ||
                                              link.match(/\/view\/(\d+)/) ||
                                              link.match(/(\d{8,12})/);
                                    if (m) jobId = m[1];
                                }
                            }

                            if (!jobId) {
                                const urn = card.getAttribute('data-entity-urn') || '';
                                const m = urn.match(/jobPosting:(\d+)/);
                                if (m) jobId = m[1];
                            }

                            if (!jobId) {
                                jobId = link || card.innerText.slice(0, 30);
                            }

                            if (seen.has(jobId)) continue;
                            seen.add(jobId);

                            let role = '';
                            const titleEl = card.querySelector('.job-card-list__title--link') ||
                                            card.querySelector('.job-card-list__title') ||
                                            card.querySelector('.job-card-container__link') ||
                                            card.querySelector('.base-search-card__title') ||
                                            card.querySelector('strong') ||
                                            card.querySelector('h3') ||
                                            card.querySelector('h4') ||
                                            linkEl;
                            
                            if (titleEl) {
                                const hiddenSpan = titleEl.querySelector('span[aria-hidden="true"]');
                                role = cleanRole(hiddenSpan ? hiddenSpan.innerText : titleEl.innerText);
                            }

                            if (!role || role.length < 2) {
                                const lines = card.innerText.split('\n').map(l => cleanRole(l)).filter(l => l.length > 2);
                                role = lines[0] || '';
                            }

                            let company = '';
                            const companyEl = card.querySelector('.job-card-container__primary-description') ||
                                              card.querySelector('.artdeco-entity-lockup__subtitle') ||
                                              card.querySelector('.job-card-container__company-name') ||
                                              card.querySelector('a[href*="/company/"]') ||
                                              card.querySelector('.base-search-card__subtitle') ||
                                              card.querySelector('[class*="company"]') ||
                                              card.querySelector('[class*="subtitle"]');
                            if (companyEl) {
                                company = companyEl.innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                            }

                            let location = '';
                            const locationEl = card.querySelector('.job-card-container__metadata-item') ||
                                               card.querySelector('.artdeco-entity-lockup__caption') ||
                                               card.querySelector('ul.job-card-container__metadata-wrapper li') ||
                                               card.querySelector('.job-card-container__location') ||
                                               card.querySelector('.job-search-card__location') ||
                                               card.querySelector('[class*="location"]') ||
                                               card.querySelector('[class*="caption"]');
                            if (locationEl) {
                                location = locationEl.innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                            }

                            const cardText = card.innerText.toLowerCase();
                            const easyApply = cardText.includes('solicitud sencilla') ||
                                              cardText.includes('easy apply') ||
                                              cardText.includes('candidatura sencilla') ||
                                              cardText.includes('candidatura fácil') ||
                                              !!card.querySelector('.job-card-container__apply-method') ||
                                              !!card.querySelector('[data-testid="job-card-list-item__easy-apply"]') ||
                                              !!card.querySelector('[class*="easy-apply"]');

                            const alreadyApplied = cardText.includes('solicitado') ||
                                                   cardText.includes('applied') ||
                                                   cardText.includes('candidatura enviada') ||
                                                   cardText.includes('ya has solicitado') ||
                                                   !!card.querySelector('.jobs-search-results-list__state-message') ||
                                                   !!card.querySelector('.artdeco-inline-feedback');

                            const canonicalLink = jobId && /^\d+$/.test(jobId) 
                                ? `https://www.linkedin.com/jobs/view/${jobId}/` 
                                : (link ? link.split('?')[0] : '');

                            if (role) {
                                jobs.push({
                                    job_id: jobId,
                                    role: role,
                                    company: company,
                                    location: location,
                                    link: canonicalLink,
                                    easy_apply: easyApply,
                                    already_applied: alreadyApplied,
                                });
                            }
                        }
                    }

                    // 3. Direct links fallback
                    if (jobs.length === 0) {
                        const links = Array.from(document.querySelectorAll('a[href*="/jobs/view/"], a[href*="currentJobId="]'));
                        for (const link of links) {
                            const href = link.href;
                            const m = href.match(/currentJobId=(\d+)/) ||
                                      href.match(/\/jobs\/view\/(?:[^\/]+-)?(\d+)/) ||
                                      href.match(/\/view\/(\d+)/) ||
                                      href.match(/(\d{8,12})/);
                            const jobId = m ? m[1] : '';
                            if (!jobId || seen.has(jobId)) continue;
                            seen.add(jobId);

                            const card = link.closest('li, div[class*="card"], div[class*="item"]') || link.parentElement;
                            const cardText = card ? card.innerText.toLowerCase() : '';
                            const role = cleanRole(link.innerText || link.getAttribute('aria-label') || '');

                            if (role) {
                                jobs.push({
                                    job_id: jobId,
                                    role: role,
                                    company: '',
                                    location: '',
                                    link: `https://www.linkedin.com/jobs/view/${jobId}/`,
                                    easy_apply: cardText.includes('solicitud sencilla') || cardText.includes('easy apply') || cardText.includes('candidatura sencilla'),
                                    already_applied: cardText.includes('solicitado') || cardText.includes('applied') || cardText.includes('candidatura enviada'),
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
            await page.wait_for_timeout(1500)

    return json.dumps([])


async def extract_job_details() -> str:
    """Extract detailed job info from the current LinkedIn job page or split view."""
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    await dismiss_guest_overlays(page)

    # Try to expand truncated description ("Show more" / "Ver más")
    try:
        await page.evaluate("""
            () => {
                const showMoreBtn = Array.from(document.querySelectorAll('button')).find(b => {
                    const t = (b.innerText || '').toLowerCase().trim();
                    return (t.includes('ver más') || t.includes('show more') || t === 'más') && !t.includes('ver menos');
                }) || document.querySelector('button.jobs-description__footer-button') ||
                      document.querySelector('button[aria-label*="Show more"]') ||
                      document.querySelector('button[aria-label*="Ver más"]') ||
                      document.querySelector('button.show-more-less-html__button') ||
                      document.querySelector('.artdeco-card__actions button');
                if (showMoreBtn) {
                    showMoreBtn.click();
                }
            }
        """)
        await asyncio.sleep(0.5)
    except Exception:
        pass

    try:
        job = await page.evaluate(
            r"""
            () => {
                const col = document.querySelector('[data-testid="lazy-column"]') || document.querySelector('#lazy-column');
                const topCard = col ? col.firstElementChild : document.body;

                // 1. Title / Role
                let title = '';
                const titleEl = document.querySelector('h1.job-details-jobs-unified-top-card__job-title') ||
                                document.querySelector('h2.job-details-jobs-unified-top-card__job-title') ||
                                document.querySelector('.job-details-jobs-unified-top-card__job-title-link') ||
                                document.querySelector('div.job-details-jobs-unified-top-card__title-container h1') ||
                                document.querySelector('.jobs-unified-top-card__job-title') ||
                                document.querySelector('h1.top-card-layout__title') ||
                                document.querySelector('p.d3e5c957._062c687f') ||
                                document.querySelector('p._062c687f') ||
                                (topCard && topCard !== document.body ? topCard.querySelector('p.d3e5c957, p._062c687f') : null);
                if (titleEl) {
                    title = titleEl.innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                }

                if (!title && topCard && topCard !== document.body) {
                    const companyLink = topCard.querySelector('a[href*="/company/"]');
                    if (companyLink) {
                        const pEls = Array.from(topCard.querySelectorAll('p'));
                        const compP = companyLink.closest('p') || companyLink.parentElement;
                        const compIdx = pEls.indexOf(compP);
                        if (compIdx >= 0 && compIdx + 1 < pEls.length) {
                            title = pEls[compIdx + 1].innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                        }
                    }
                }

                if (!title || title.length < 2) {
                    const h1 = document.querySelector('h1');
                    if (h1) title = h1.innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                }

                if (!title || title.length < 2) {
                    title = (document.title || '').split(' | ')[0].split(' - ')[0].trim();
                }

                // 2. Company
                let company = '';
                const compLink = document.querySelector('a[href*="/company/"]') ||
                                 document.querySelector('div.job-details-jobs-unified-top-card__company-name a') ||
                                 document.querySelector('span.job-details-jobs-unified-top-card__company-name') ||
                                 document.querySelector('div.job-details-jobs-unified-top-card__company-name');
                if (compLink) {
                    company = compLink.innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                }

                // 3. Location & Workplace Type
                let location = '';
                let workplaceType = '';

                // Location paragraph matching "hace \d+" or city format
                if (topCard) {
                    const locP = Array.from(topCard.querySelectorAll('p')).find(p => {
                        const t = p.innerText;
                        return /\b(hace \d+|ago \d+|días?|horas?|days?|hours?)\b/i.test(t) ||
                               (t.includes(',') && !t.includes('http') && t.length < 150);
                    });
                    if (locP) {
                        location = locP.innerText
                            .replace(/\s*·\s*hace\s+[^·]+/gi, '')
                            .replace(/\s*·\s*\d+\s*(?:solicitudes|applicants|candidaturas).*/gi, '')
                            .replace(/\s*·\s*ago\s+[^·]+/gi, '')
                            .split('\n')[0]
                            .replace(/\s+/g, ' ')
                            .trim();
                    }
                }
                if (!location) {
                    const locEl = document.querySelector('.job-details-jobs-unified-top-card__primary-description-container') ||
                                  document.querySelector('span.job-details-jobs-unified-top-card__bullet') ||
                                  document.querySelector('.jobs-unified-top-card__bullet') ||
                                  document.querySelector('span.topcard__flavor--bullet');
                    if (locEl) {
                        location = locEl.innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                    }
                }

                // Workplace type chip
                const wpEl = Array.from(document.querySelectorAll('span, a')).find(el => 
                    /^(presencial|en remoto|híbrido|on-site|remote|hybrid)$/i.test(el.textContent.trim())
                ) || document.querySelector('span.job-details-jobs-unified-top-card__workplace-type') ||
                     document.querySelector('span.jobs-unified-top-card__workplace-type');
                if (wpEl) {
                    workplaceType = wpEl.textContent.trim();
                } else if (location.includes('(') && location.includes(')')) {
                    const m = location.match(/\(([^)]+)\)/);
                    if (m) workplaceType = m[1].trim();
                }

                // 4. Description
                let description = '';
                const h2 = Array.from(document.querySelectorAll('h2')).find(h => 
                    /acerca del empleo|about the job|sobre la vacante|job description/i.test(h.innerText)
                );
                if (h2 && h2.parentElement) {
                    const container = h2.parentElement;
                    const lines = (container.innerText || '').split('\n');
                    description = lines.slice(1).join('\n')
                        .replace(/(?:ver más|ver menos|show more|show less)\s*$/i, '')
                        .trim();
                }
                if (!description || description.length < 50) {
                    const descEl = document.querySelector('#job-details') ||
                                   document.querySelector('.jobs-description__content') ||
                                   document.querySelector('.jobs-box__html-content') ||
                                   document.querySelector('.jobs-description') ||
                                   document.querySelector('.show-more-less-html__markup') ||
                                   document.querySelector('article.jobs-description__container') ||
                                   document.querySelector('.description__text') ||
                                   document.querySelector('article');
                    if (descEl) {
                        description = descEl.innerText.trim();
                    }
                }
                if (!description || description.length < 50) {
                    const pageText = document.body ? document.body.innerText : '';
                    const match = pageText.match(/(?:Acerca del empleo|About the job|Sobre la vacante|Description)[\s\S]{50,6000}/i);
                    if (match) {
                        description = match[0].trim();
                    }
                }

                // 5. Easy Apply Button & State
                const easyApplyBtn = document.querySelector('button.jobs-apply-button') ||
                                     document.querySelector('button.apply-button--easy-apply') ||
                                     document.querySelector('button[aria-label*="Easy Apply"]') ||
                                     document.querySelector('button[aria-label*="Solicitud sencilla"]') ||
                                     document.querySelector('button[aria-label*="Candidatura sencilla"]') ||
                                     document.querySelector('button[data-is-easy-apply="true"]') ||
                                     document.querySelector('div.jobs-apply-button--top-card button') ||
                                     document.querySelector('div.jobs-s-apply button') ||
                                     Array.from(document.querySelectorAll('button')).find(b => {
                                         const t = (b.innerText || '').toLowerCase().trim();
                                         return t.includes('solicitud sencilla') || t.includes('easy apply') || t.includes('candidatura sencilla');
                                     });

                const appliedBanner = document.querySelector('.jobs-apply-button--disabled') ||
                                      document.querySelector('.artdeco-inline-feedback--success') ||
                                      document.querySelector('.jobs-applied-banner') ||
                                      document.querySelector('span.jobs-s-apply__applied-text');
                
                const btnText = easyApplyBtn ? (easyApplyBtn.innerText || '').toLowerCase() : '';
                const alreadyApplied = !!appliedBanner ||
                                       (easyApplyBtn && easyApplyBtn.disabled) ||
                                       btnText.includes('applied') || btnText.includes('solicitado') || btnText.includes('enviada');

                // 6. Recruiter info
                const recruiterEl = document.querySelector('a[data-tracking-control-name*="hirer"]') ||
                                    document.querySelector('a[href*="/in/"][data-tracking-control-name]') ||
                                    document.querySelector('.jobs-poster__name') ||
                                    document.querySelector('.hirer-card__hirer-information') ||
                                    document.querySelector('.jobs-search__organizer-link');

                return {
                    role: title,
                    company: company,
                    location: location,
                    workplace_type: workplaceType,
                    description: description,
                    easy_apply: !!easyApplyBtn,
                    already_applied: !!alreadyApplied,
                    recruiter: recruiterEl ? (recruiterEl.innerText || recruiterEl.href || '').trim() : '',
                    url: window.location.href,
                };
            }
            """
        )

        return json.dumps(job, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def click_easy_apply() -> str:
    """Click the Easy Apply button with robust selector fallbacks.

    Returns 'clicked', 'already_applied', or 'error: ...'.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    await dismiss_guest_overlays(page)
    await _take_debug_screenshot("easy_apply_before_click")

    selectors = [
        'button.jobs-apply-button',
        'button.apply-button--easy-apply',
        'button.apply-button',
        'button[aria-label*="Easy Apply"]',
        'button[aria-label*="Solicitud sencilla"]',
        'button[aria-label*="Candidatura sencilla"]',
        'button.artdeco-button--primary:has-text("Easy Apply")',
        'button.artdeco-button--primary:has-text("Solicitud sencilla")',
        'button.artdeco-button--primary:has-text("Candidatura sencilla")',
        'button:has-text("Easy Apply")',
        'button:has-text("Solicitud sencilla")',
        'button:has-text("Candidatura sencilla")',
        'button:has-text("Solicitar")',
        'div.jobs-apply-button--top-card button',
        'div.jobs-s-apply button',
        'button[class*="apply-button"]',
    ]

    try:
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    btn_text = (await btn.inner_text(timeout=1500)).lower()
                    is_disabled = await btn.is_disabled()

                    if is_disabled or "applied" in btn_text or "solicitado" in btn_text or "enviada" in btn_text:
                        logger.info("Already applied to this job (detected on button)")
                        return "already_applied"

                    await btn.scroll_into_view_if_needed()
                    await btn.click(timeout=4000)
                    await human_delay()
                    await _take_debug_screenshot("easy_apply_after_click")
                    return "clicked"
            except Exception:
                continue

        # Strategy 2: Native JS click
        clicked_js = await page.evaluate("""
            () => {
                const btn = document.querySelector('button.jobs-apply-button') ||
                            document.querySelector('button[aria-label*="Easy Apply"]') ||
                            document.querySelector('button[aria-label*="Solicitud sencilla"]') ||
                            Array.from(document.querySelectorAll('button')).find(b => {
                                const t = (b.innerText || '').toLowerCase();
                                return t.includes('solicitud sencilla') || t.includes('easy apply');
                            });
                if (btn && !btn.disabled) {
                    btn.scrollIntoView({ block: 'center' });
                    btn.click();
                    return true;
                }
                return false;
            }
        """)
        if clicked_js:
            await human_delay()
            await _take_debug_screenshot("easy_apply_after_click_js")
            return "clicked"

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
        follow_result = await page.evaluate(
            r"""
            () => {
            """
            + _EASY_APPLY_ROOT_JS
            + r"""
                const root = easyApplyRoot();
                if (!root) return {has_follow_checkbox: false, follow_checked: false};
                const followCheckbox = root.querySelector('input[name="followCompany"]') ||
                                       root.querySelector('[data-follow-company]') ||
                                       Array.from(root.querySelectorAll('input[type="checkbox"]')).find(cb => {
                                           const l = (cb.closest('label')?.innerText || cb.getAttribute('aria-label') || '').toLowerCase();
                                           return l.includes('seguir') || l.includes('follow');
                                       });
                return {
                    has_follow_checkbox: !!followCheckbox,
                    follow_checked: followCheckbox ? followCheckbox.checked : false,
                };
            }
            """
        )
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

    Adds 'profile_value' to each field when a match is found and lists fields needing human input.
    """
    from hawk.profile import load_profile, match_field

    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    profile = load_profile()
    progress = await _get_progress_percentage()

    try:
        raw = await page.evaluate(_DETECT_FIELDS_JS)

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
            r"""
            () => {
            """
            + _EASY_APPLY_ROOT_JS
            + r"""
                const root = easyApplyRoot();
                if (!root) return 'no_modal';

                const checkboxes = root.querySelectorAll('input[name="followCompany"], [data-follow-company], input[type="checkbox"]');
                for (const cb of checkboxes) {
                    const label = cb.closest('label')?.innerText || cb.getAttribute('aria-label') || '';
                    const labelLower = label.toLowerCase();
                    if ((labelLower.includes('follow') || labelLower.includes('seguir')) && cb.checked) {
                        cb.click();
                        cb.checked = false;
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                        return 'unchecked';
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
        # Priority: Submit first, then Next/Continue/Review
        selectors = [
            ("submit", 'button[aria-label*="Submit application"]'),
            ("submit", 'button[aria-label*="Enviar solicitud"]'),
            ("submit", 'button[aria-label*="Enviar candidatura"]'),
            ("submit", 'button:has-text("Submit application")'),
            ("submit", 'button:has-text("Enviar solicitud")'),
            ("submit", 'button:has-text("Enviar candidatura")'),
            ("submit", 'button:has-text("Submit")'),
            ("submit", 'button:has-text("Enviar")'),
            ("next", 'button[aria-label*="Continue"]'),
            ("next", 'button[aria-label*="Review"]'),
            ("next", 'button[aria-label*="Siguiente"]'),
            ("next", 'button[aria-label*="Continuar"]'),
            ("next", 'button[aria-label*="Revisar"]'),
            ("next", 'button[aria-label*="Avançar"]'),
            ("next", 'button.artdeco-button--primary'),
            ("next", 'button:has-text("Next")'),
            ("next", 'button:has-text("Continue")'),
            ("next", 'button:has-text("Review")'),
            ("next", 'button:has-text("Siguiente")'),
            ("next", 'button:has-text("Continuar")'),
            ("next", 'button:has-text("Revisar")'),
            ("next", 'button:has-text("Avançar")'),
        ]

        for action, selector in selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.scroll_into_view_if_needed()
                    await btn.click(timeout=3000)
                    await human_delay()
                    await _take_debug_screenshot(f"after_{action}_click")
                    return f"clicked_{action}"
            except Exception:
                continue

        return "no_button_found"
    except Exception as e:
        return f"error: {e}"


async def submit_application(override_dry_run: bool | None = None) -> str:
    """Submit the Easy Apply application.

    1. Unfollow company if checkbox is checked
    2. Check dry_run — if true, do NOT click Submit
    3. Click Submit
    4. Verify submission by checking modal closed or confirmation message
    """
    settings = get_settings()
    is_dry = override_dry_run if override_dry_run is not None else settings.apply.dry_run
    if is_dry:
        logger.info("Dry run mode — skipping actual submission")
        await _take_debug_screenshot("dry_run_before_submit")
        return "dry_run_blocked"

    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        # Unfollow company before submitting
        await unfollow_company()

        submit_selectors = [
            'button[aria-label*="Submit application"]',
            'button[aria-label*="Enviar solicitud"]',
            'button[aria-label*="Enviar candidatura"]',
            'button:has-text("Enviar solicitud")',
            'button:has-text("Submit application")',
            'button:has-text("Enviar candidatura")',
            'button:has-text("Enviar")',
            'button:has-text("Submit")',
        ]
        btn = None
        for sel in submit_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=1500):
                    btn = loc
                    break
            except Exception:
                continue

        if btn is None:
            return "error: Submit button not found"

        await btn.scroll_into_view_if_needed()
        await btn.click(timeout=5000)
        await human_delay()

        # Verify submission succeeded — check modal closed
        try:
            modal = page.locator('.jobs-easy-apply-modal, div[data-test-modal-id="easy-apply-modal"], [role="dialog"], .artdeco-modal').first
            await modal.wait_for(state="hidden", timeout=5000)
            logger.info("Submit verified: modal closed")
        except Exception:
            # Modal might still be open — check for success message
            success = page.locator('.artdeco-inline-feedback--success, .jobs-succeeded-apply-message, .jobs-applied-banner').first
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
        return text[:15000]
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


async def upload_resume(file_path: str) -> str:
    """Upload a resume file to the current LinkedIn Easy Apply modal."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    path_obj = Path(file_path)
    if not path_obj.exists():
        return f"error: File not found: {file_path}"

    abs_path = str(path_obj.resolve())

    try:
        # 1. Direct input[type="file"]
        file_input = page.locator('.jobs-easy-apply-modal input[type="file"], [role="dialog"] input[type="file"], input[type="file"]').first
        if await file_input.count() > 0:
            await file_input.set_input_files(abs_path)
            await page.wait_for_timeout(2500)
            logger.info("Resume uploaded via direct file input: {}", abs_path)
            return f"uploaded: {abs_path}"

        # 2. Intercept native file chooser via upload button
        upload_btn = page.locator(
            'button:has-text("Cargar currículum"), button:has-text("Upload resume"), '
            'label:has-text("Cargar currículum"), label:has-text("Upload resume"), '
            'div[role="button"]:has-text("Cargar currículum"), div[role="button"]:has-text("Upload resume")'
        ).first

        if await upload_btn.count() > 0:
            async with page.expect_file_chooser(timeout=7000) as fc_info:
                await upload_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(abs_path)
            await page.wait_for_timeout(3000)
            logger.info("Resume uploaded via file chooser: {}", abs_path)
            return f"uploaded: {abs_path}"

        return "error: Could not find resume upload button or file input on current step"
    except Exception as e:
        logger.error("upload_resume failed: {}", e)
        return f"error: {e}"


def generate_recruiter_pitch(
    job_title: str,
    company: str,
    recruiter_name: str = "",
    top_skills: list[str] | None = None,
) -> str:
    """Generate a high-impact, concise LinkedIn connection note (< 300 chars limit)."""
    from hawk.profile import load_profile

    profile = load_profile()
    name = profile.personal.first_name
    skills_str = ", ".join(top_skills[:3]) if top_skills else "CI/CD, Docker & AWS"

    greeting = f"Hi {recruiter_name.split()[0]}," if recruiter_name else "Hi,"
    note = f"{greeting} I applied for the {job_title} role at {company}. With 2+ yrs optimizing {skills_str}, I'd love to connect and discuss how I can contribute to the team! Best, {name}"

    if len(note) > 295:
        note = f"{greeting} I applied to the {job_title} role at {company}. With hands-on DevOps & {skills_str} experience, I'd love to connect! Best, {name}"

    return note[:300]


async def connect_with_recruiter(recruiter_url: str, note: str = "", dry_run: bool = True) -> str:
    """Send a personalized connection request with note to a recruiter or job poster.

    Respects LinkedIn's 300 character limit on notes.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        if recruiter_url and not page.url.startswith(recruiter_url):
            await page.goto(recruiter_url, wait_until="domcontentloaded", timeout=25000)
            await human_delay()

        # Look for Connect button
        connect_btn = page.locator(
            'button:has-text("Conectar"), button:has-text("Connect"), '
            'button[aria-label*="Conectar con"], button[aria-label*="Invite to connect"]'
        ).first

        if await connect_btn.count() == 0 or not await connect_btn.is_visible():
            # Check under "More actions" / "Más acciones"
            more_btn = page.locator('button[aria-label*="Más acciones"], button[aria-label*="More actions"]').first
            if await more_btn.count() > 0:
                await more_btn.click()
                await page.wait_for_timeout(1000)
                connect_btn = page.locator('div[role="button"]:has-text("Conectar"), div[role="button"]:has-text("Connect")').first

        if await connect_btn.count() == 0 or not await connect_btn.is_visible():
            return "error: Could not find Connect button on profile"

        await connect_btn.click()
        await page.wait_for_timeout(1500)

        # Handle 'Add a note' modal
        add_note_btn = page.locator('button:has-text("Añadir una nota"), button:has-text("Add a note")').first
        if note and await add_note_btn.count() > 0 and await add_note_btn.is_visible():
            await add_note_btn.click()
            await page.wait_for_timeout(1000)
            textarea = page.locator('textarea[name="message"], textarea#custom-message').first
            if await textarea.count() > 0:
                clean_note = note[:300]
                await textarea.fill(clean_note)
                logger.info("Filled recruiter connection note: {}", clean_note)

        if dry_run:
            logger.info("Dry-run mode: Stopping before sending connection request")
            return "dry_run_blocked: Connection request prepared with note."

        send_btn = page.locator(
            'button:has-text("Enviar"), button:has-text("Send"), button[aria-label*="Enviar ahora"], button[aria-label*="Send now"]'
        ).first
        if await send_btn.count() > 0:
            await send_btn.click()
            await page.wait_for_timeout(2000)
            return "connection_request_sent"

        return "error: Send button not found in connection modal"

    except Exception as e:
        logger.error("connect_with_recruiter failed: {}", e)
        return f"error: {e}"

