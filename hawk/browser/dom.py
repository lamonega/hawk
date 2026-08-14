"""DOM accessibility tree snapshot and element interaction."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from playwright.async_api import Page

from hawk.browser.driver import get_page
import hawk.browser.driver as driver_state

# Global state delegated to driver module to survive hot reloads
if not hasattr(driver_state, "_last_snapshot"):
    driver_state._last_snapshot = {}
if not hasattr(driver_state, "_last_elements"):
    driver_state._last_elements = []


async def snapshot() -> str:
    """Take an accessibility tree snapshot of the current page.

    Assigns a unique 'data-hawk-id' attribute to every interactive element in the DOM
    so that click, type, and select actions are 100% deterministic and error-free.

    Returns:
        JSON string with page URL, title, and indexed interactive elements.
    """
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    try:
        # Extract and tag interactive elements in the DOM
        raw_elements = await page.evaluate(
            r"""
            () => {
                const selectors = [
                    'button',
                    'input:not([type=hidden])',
                    'select',
                    'textarea',
                    'a[href]',
                    '[role=button]',
                    '[role=combobox]',
                    '[role=textbox]',
                    '[role=checkbox]',
                    '[role=radio]',
                    '[role=tab]',
                    '[tabindex="0"]',
                ];

                const seen = new Set();
                const results = [];
                let hawkIndex = 0;

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

                // Scope strictly to active modal when open, otherwise full document
                const rootForm = easyApplyRoot();
                const rootNodes = (rootForm && rootForm !== document.body) ? [rootForm] : [document.body];

                for (const root of rootNodes) {
                    for (const sel of selectors) {
                        for (const el of root.querySelectorAll(sel)) {
                            if (seen.has(el)) continue;
                            seen.add(el);

                            // Tag element with data-hawk-id for reliable Playwright targeting
                            const currentIndex = hawkIndex++;
                            el.setAttribute('data-hawk-id', String(currentIndex));

                            const tag = el.tagName.toLowerCase();
                            const role = el.getAttribute('role') ||
                                          (tag === 'a' ? 'link' :
                                           tag === 'button' ? 'button' :
                                           tag === 'input' ? el.type || 'textbox' :
                                           tag === 'select' ? 'combobox' :
                                           tag === 'textarea' ? 'textbox' : tag);

                            // Precision label extraction
                            let cleanLabel = '';
                            if (tag === 'button' || tag === 'a' || role === 'button' || role === 'link') {
                                cleanLabel = el.getAttribute('aria-label') ||
                                             el.innerText?.trim() ||
                                             el.getAttribute('title') ||
                                             el.value ||
                                             el.name ||
                                             '';
                            } else {
                                if (el.id) {
                                    try {
                                        const labelFor = document.querySelector(`label[for="${el.id}"]`);
                                        if (labelFor && labelFor.innerText.trim()) cleanLabel = labelFor.innerText;
                                    } catch(e) {}
                                }
                                if (!cleanLabel && el.labels && el.labels[0]) {
                                    cleanLabel = el.labels[0].innerText;
                                }
                                if (!cleanLabel) {
                                    const ariaBy = el.getAttribute('aria-labelledby');
                                    if (ariaBy) {
                                        cleanLabel = ariaBy.split(' ')
                                            .map(id => document.getElementById(id)?.innerText || '')
                                            .join(' ').trim();
                                    }
                                }
                                if (!cleanLabel) {
                                    const formGroup = el.closest('.jobs-easy-apply-form-section__group, .fb-dash-form-element, div[data-test-form-element], fieldset, tr, div.artdeco-text-input--container');
                                    if (formGroup && !formGroup.classList.contains('jobs-easy-apply-modal') && !formGroup.classList.contains('artdeco-modal')) {
                                        const formLabel = formGroup.querySelector('label, legend, .fb-dash-form-element__label, .artdeco-text-input--label, dt, th, span.t-14');
                                        if (formLabel) cleanLabel = formLabel.innerText;
                                    }
                                }
                                if (!cleanLabel) {
                                    cleanLabel = el.getAttribute('aria-label') ||
                                                 el.getAttribute('placeholder') ||
                                                 el.getAttribute('title') ||
                                                 el.name ||
                                                 '';
                                }
                            }

                            // Clean up multiline text / options pollution in select labels
                            cleanLabel = cleanLabel.split('\n')[0].replace(/\s+/g, ' ').trim().slice(0, 120);

                            const id = el.id || '';
                            let value = el.value || el.getAttribute('value') || '';
                            if (tag === 'select' && el.selectedIndex >= 0 && el.options[el.selectedIndex]) {
                                value = el.options[el.selectedIndex].text.trim();
                            }

                            // Extract validation and error diagnostics
                            const isAriaInvalid = el.getAttribute('aria-invalid') === 'true';
                            const hasErrorClass = el.classList.contains('artdeco-text-input--error') ||
                                                  el.classList.contains('fb-form-element--error') ||
                                                  Boolean(el.closest('.artdeco-text-input--error, .fb-dash-form-element--error, [data-test-form-element-error]'));
                            const isInvalid = isAriaInvalid || hasErrorClass;

                            let elemError = '';
                            if (isInvalid) {
                                const group = el.closest('.jobs-easy-apply-form-section__group, .fb-dash-form-element, div[data-test-form-element], fieldset, div.artdeco-text-input--container');
                                if (group) {
                                    const errEl = group.querySelector('.artdeco-inline-feedback--error, .fb-dash-form-element__error-text, [role="alert"], [data-test-form-element-error]');
                                    if (errEl) elemError = errEl.innerText.trim();
                                }
                            }

                            const isRequired = Boolean(el.required || el.getAttribute('aria-required') === 'true' || cleanLabel.includes('*'));
                            const placeholder = el.getAttribute('placeholder') || '';
                            const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                            const readonly = el.readOnly || el.getAttribute('aria-readonly') === 'true';
                            const href = el.getAttribute('href') || '';

                            results.push({
                                index: currentIndex,
                                tag: tag,
                                id: id,
                                role: role,
                                name: cleanLabel,
                                value: value,
                                disabled: disabled,
                                readonly: readonly,
                                required: isRequired,
                                invalid: isInvalid,
                                error_message: elemError,
                                placeholder: placeholder,
                                href: href,
                                type: el.type || '',
                            });
                        }
                    }
                }

                // Collect overall page / modal error alerts
                const formErrors = [];
                const errNodes = document.querySelectorAll(
                    '.artdeco-inline-feedback--error, .fb-dash-form-element__error-text, ' +
                    '[data-test-form-element-error], .jobs-easy-apply-modal__error-message, ' +
                    'div.artdeco-modal__alert, [role="alert"]'
                );
                for (const node of errNodes) {
                    const txt = (node.innerText || '').trim();
                    if (txt && !formErrors.includes(txt) && txt.length < 300) {
                        formErrors.push(txt);
                    }
                }

                return { elements: results, form_errors: formErrors };
            }
            """
        )

        elements_list = raw_elements.get("elements", []) if isinstance(raw_elements, dict) else raw_elements
        form_errors_list = raw_elements.get("form_errors", []) if isinstance(raw_elements, dict) else []

        result = {
            "url": page.url,
            "title": await page.title(),
            "form_errors": form_errors_list,
            "elements": elements_list,
        }

        # Store in persistent driver state
        driver_state._last_snapshot = result
        driver_state._last_elements = elements_list

        logger.debug("Snapshot: {} elements, {} errors on {}", len(elements_list), len(form_errors_list), page.url)
        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error("Snapshot failed: {}", e)
        return json.dumps({"error": str(e)})


def get_element_by_index(index: int) -> dict | None:
    """Get element info from last snapshot by index."""
    elems = getattr(driver_state, "_last_elements", [])
    if index < 0 or index >= len(elems):
        return None
    return elems[index]


async def click_element(element_index: int) -> str:
    """Click an element by its index from the last snapshot."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    element = get_element_by_index(element_index)
    if element is None:
        return f"error: Element index {element_index} not found in last snapshot"

    # Strategy 1: Target by data-hawk-id
    try:
        loc = page.locator(f'[data-hawk-id="{element_index}"]').first
        if await loc.count() > 0:
            await loc.scroll_into_view_if_needed()
            await loc.click(timeout=4000)
            return f"Clicked: {element.get('role', '')} '{element.get('name', '')}'"
    except Exception:
        pass

    # Strategy 2: Native JS click via data-hawk-id
    try:
        clicked = await page.evaluate(f"""
            () => {{
                const el = document.querySelector('[data-hawk-id="{element_index}"]');
                if (el) {{
                    el.scrollIntoView({{ block: 'center' }});
                    el.focus();
                    el.click();
                    return true;
                }}
                return false;
            }}
        """)
        if clicked:
            return f"Clicked (native JS): {element.get('role', '')} '{element.get('name', '')}'"
    except Exception:
        pass

    return f"error: Could not click element {element_index} ('{element.get('name', '')}')"


async def type_element(element_index: int, text: str, clear: bool = False) -> str:
    """Type text into an input or textarea by its index."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    element = get_element_by_index(element_index)
    if element is None:
        return f"error: Element index {element_index} not found in last snapshot"

    # Strategy 1: Playwright locator with data-hawk-id
    try:
        loc = page.locator(f'[data-hawk-id="{element_index}"]').first
        if await loc.count() > 0:
            await loc.scroll_into_view_if_needed()
            if clear:
                await loc.clear()
            await loc.fill(text)
            return f"Typed: '{text}' into {element.get('tag', '')} '{element.get('name', '')}'"
    except Exception:
        pass

    # Strategy 2: Native JS input with React-aware event dispatching
    try:
        typed = await page.evaluate(f"""
            (textVal) => {{
                const el = document.querySelector('[data-hawk-id="{element_index}"]');
                if (el) {{
                    el.focus();
                    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
                    const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                    if (nativeSetter) {{
                        nativeSetter.call(el, textVal);
                    }} else {{
                        el.value = textVal;
                    }}
                    el.setAttribute('value', textVal);
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                    return true;
                }}
                return false;
            }}
        """, text)
        if typed:
            return f"Typed (native JS): '{text}' into {element.get('tag', '')} '{element.get('name', '')}'"
    except Exception:
        pass

    return f"error: Could not type into element {element_index} ('{element.get('name', '')}')"


async def select_element(element_index: int, value: str) -> str:
    """Select an option from a dropdown/select element by value or text."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    element = get_element_by_index(element_index)

    # Strategy 0: Direct search across all form / modal selects
    try:
        selected_text = await page.evaluate(r"""
            (targetVal) => {
                function easyApplyRoot() {
                    const dlg = document.querySelector('[role="dialog"]');
                    if (dlg && (dlg.querySelector('input, select, textarea, [role="radio"]') || dlg.classList.contains('jobs-easy-apply-modal') || dlg.classList.contains('artdeco-modal'))) {
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

                const root = easyApplyRoot();
                const selects = Array.from(root.querySelectorAll('select'));
                for (const sel of selects) {
                    for (let i = 0; i < sel.options.length; i++) {
                        const opt = sel.options[i];
                        const valLower = targetVal.toLowerCase().trim();
                        if ((opt.text || '').toLowerCase().trim().includes(valLower) || 
                            (opt.value || '').toLowerCase().trim() === valLower) {
                            sel.selectedIndex = i;
                            opt.selected = true;
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('input', { bubbles: true }));
                            sel.dispatchEvent(new Event('change', { bubbles: true }));
                            sel.dispatchEvent(new Event('blur', { bubbles: true }));
                            return opt.text.trim();
                        }
                    }
                }
                return null;
            }
        """, value)
        if selected_text:
            return f"Selected: '{selected_text}'"
    except Exception:
        pass

    if element is None:
        return f"error: Element index {element_index} not found in last snapshot"

    # Strategy 1: Native JS select matching by value, text, or substring
    try:
        selected_text = await page.evaluate(f"""
            (targetVal) => {{
                const el = document.querySelector('[data-hawk-id="{element_index}"]');
                if (!el) return null;

                // Handle native SELECT
                if (el.tagName === 'SELECT') {{
                    const valLower = targetVal.toLowerCase().trim();
                    let matchedOpt = null;

                    for (let i = 0; i < el.options.length; i++) {{
                        const opt = el.options[i];
                        const optVal = (opt.value || '').toLowerCase().trim();
                        const optText = (opt.text || '').toLowerCase().trim();
                        if (optVal === valLower || optText === valLower || optText.includes(valLower)) {{
                            matchedOpt = opt;
                            el.selectedIndex = i;
                            break;
                        }}
                    }}

                    if (matchedOpt) {{
                        matchedOpt.selected = true;
                        el.value = matchedOpt.value;
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                        return matchedOpt.text.trim();
                    }}
                }}

                // Handle custom Artdeco dropdown or combobox
                if (el.getAttribute('role') === 'combobox' || el.classList.contains('artdeco-dropdown__trigger')) {{
                    el.click();
                    return 'opened_combobox';
                }}

                return null;
            }}
        """, value)

        if selected_text and selected_text != 'opened_combobox':
            return f"Selected: '{selected_text}' in select '{element.get('name', '')}'"
    except Exception:
        pass

    # Strategy 2: Playwright select_option
    try:
        loc = page.locator(f'[data-hawk-id="{element_index}"]').first
        if await loc.count() > 0:
            await loc.select_option(value=value)
            return f"Selected: '{value}' in '{element.get('name', '')}'"
    except Exception:
        pass

    return f"error: Could not select '{value}' in element {element_index} ('{element.get('name', '')}')"


async def upload_file(element_index: int, file_path: str) -> str:
    """Upload a file to a file input element."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        # Check all frames and main document for file inputs
        info = await page.evaluate(r"""
        () => {
            const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
            const res = inputs.map(i => ({
                id: i.id,
                name: i.name,
                accept: i.accept,
                parentTag: i.parentElement ? i.parentElement.tagName : '',
                parentClass: i.parentElement ? i.parentElement.className : '',
                visible: i.offsetParent !== null,
                style: i.getAttribute('style') || ''
            }));
            const buttons = Array.from(document.querySelectorAll('button, label, div[role="button"]'))
                .filter(b => (b.innerText || '').toLowerCase().includes('currículum') || (b.innerText || '').toLowerCase().includes('resume') || (b.innerText || '').toLowerCase().includes('cargar') || (b.innerText || '').toLowerCase().includes('upload'))
                .map(b => ({
                    tag: b.tagName,
                    text: (b.innerText || '').trim(),
                    for: b.getAttribute('for') || '',
                    id: b.id,
                    className: b.className
                }));
            return { fileInputs: res, uploadButtons: buttons };
        }
        """)
        logger.info("Upload diagnostic info: {}", json.dumps(info, indent=2))

        # Check if there is any file input on page
        file_input = page.locator('input[type="file"]').first
        if await file_input.count() > 0:
            await file_input.set_input_files(file_path)
            await page.wait_for_timeout(2500)
            return f"Uploaded file: {file_path} (info: {json.dumps(info)})"

        # Check if file input is inside an iframe
        for frame in page.frames:
            f_input = frame.locator('input[type="file"]').first
            if await f_input.count() > 0:
                await f_input.set_input_files(file_path)
                await page.wait_for_timeout(2500)
                return f"Uploaded file in frame {frame.name}: {file_path}"

        # If still not found, check if clicking the upload button triggers or opens file chooser
        upload_btn = page.locator('button:has-text("Cargar currículum"), button:has-text("Upload resume"), label:has-text("Cargar currículum"), label:has-text("Upload resume")').first
        if await upload_btn.count() > 0:
            async with page.expect_file_chooser(timeout=5000) as fc_info:
                await upload_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(file_path)
            await page.wait_for_timeout(2500)
            return f"Uploaded file via file chooser: {file_path}"

    except Exception as e:
        return f"error uploading file: {e} (info: {json.dumps(info) if 'info' in locals() else 'none'})"

    return f"error: Could not find file input for element {element_index} (diagnostic: {json.dumps(info)})"


async def take_screenshot() -> str:
    """Take a screenshot of the current page and return base64 PNG."""
    import base64

    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        screenshot = await page.screenshot(type="png")
        return base64.b64encode(screenshot).decode("utf-8")
    except Exception as e:
        return f"error: {e}"
