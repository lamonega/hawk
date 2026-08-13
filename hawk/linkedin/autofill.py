"""Auto-fill engine for LinkedIn Easy Apply forms using user profile data."""
import asyncio
import json
import re
from typing import Any

from loguru import logger
from playwright.async_api import Page

from hawk.browser.driver import get_page
from hawk.linkedin.operations import human_delay
from hawk.profile import load_profile
from hawk.settings import get_settings


_AUTOFILL_EVALUATE_JS = r"""
(profileData) => {
    const filled = [];
    const unknown = [];

    // Find modal container
    const modal = document.querySelector('.jobs-easy-apply-modal') ||
                  document.querySelector('[role="dialog"]') ||
                  document.querySelector('.artdeco-modal') ||
                  document.querySelector('div[data-test-modal]') ||
                  document.body;

    // Helper: trigger React / Angular / LinkedIn input events
    function setInputValue(el, val) {
        if (!el) return;
        el.focus();
        el.value = val;
        el.setAttribute('value', val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
    }

    // Helper: find clean label text for an element
    function getLabel(el) {
        const parent = el.closest('.jobs-easy-apply-form-section__group, .fb-dash-form-element, div[data-test-form-element], fieldset') || el.parentElement;
        const labelEl = el.labels && el.labels[0] ? el.labels[0] : (parent ? parent.querySelector('label, legend, .fb-dash-form-element__label') : null);
        let text = (labelEl ? labelEl.innerText : '') || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '';
        return text.replace(/\s+/g, ' ').trim();
    }

    const p = profileData;
    const contact = p.contact || {};
    const work = p.work_preferences || {};
    const legal = p.legal || {};
    const educ = p.education || {};

    // 1. Phone number inputs
    const phoneInputs = Array.from(modal.querySelectorAll('input[type="tel"], input[id*="phoneNumber"], input[name*="phone"], input[id*="phone"]'));
    for (const input of phoneInputs) {
        if (!input.value || input.value.trim() === '') {
            const phoneVal = contact.phone || '2216959945';
            setInputValue(input, phoneVal);
            filled.push({ field: 'phone', value: phoneVal, label: getLabel(input) });
        }
    }

    // Also check text inputs whose label mentions phone / teléfono / celular
    const allTextInputs = Array.from(modal.querySelectorAll('input[type="text"], input[type="number"], input:not([type])'));
    for (const input of allTextInputs) {
        const label = getLabel(input).toLowerCase();
        if (input.value && input.value.trim() !== '') continue;

        if (label.includes('teléfono') || label.includes('telefono') || label.includes('phone') || label.includes('celular') || label.includes('móvil')) {
            const phoneVal = contact.phone || '2216959945';
            setInputValue(input, phoneVal);
            filled.push({ field: 'phone', value: phoneVal, label: label });
        } else if (label.includes('ciudad') || label.includes('city') || label.includes('ubicación') || label.includes('location')) {
            const cityVal = contact.city ? `${contact.city}, ${contact.country || 'Argentina'}` : 'Berisso, Argentina';
            setInputValue(input, cityVal);
            filled.push({ field: 'city', value: cityVal, label: label });
        } else if (label.includes('código postal') || label.includes('postal code') || label.includes('zip')) {
            const zipVal = contact.postal_code || '1923';
            setInputValue(input, zipVal);
            filled.push({ field: 'postal_code', value: zipVal, label: label });
        } else if (label.includes('años de experiencia') || label.includes('years of experience') || label.includes('cuántos años') || label.includes('how many years')) {
            // Numeric experience questions
            let expYears = '2';
            if (label.includes('python') || label.includes('devops') || label.includes('linux') || label.includes('git') || label.includes('docker') || label.includes('aws') || label.includes('cloud')) {
                expYears = '2';
            } else if (label.includes('kubernetes') || label.includes('terraform') || label.includes('gcp') || label.includes('azure') || label.includes('ci/cd')) {
                expYears = '2';
            } else {
                expYears = '2';
            }
            setInputValue(input, expYears);
            filled.push({ field: 'experience_years', value: expYears, label: label });
        } else if (label.includes('salario') || label.includes('salary') || label.includes('remuneración') || label.includes('pretendida') || label.includes('compensation')) {
            const salVal = work.salary_expectation ? String(work.salary_expectation) : '950';
            setInputValue(input, salVal);
            filled.push({ field: 'salary', value: salVal, label: label });
        } else if (label.includes('linkedin') || label.includes('perfil')) {
            const liVal = contact.linkedin || 'https://www.linkedin.com/in/lflamonega';
            setInputValue(input, liVal);
            filled.push({ field: 'linkedin', value: liVal, label: label });
        } else if (label.includes('github') || label.includes('portfolio') || label.includes('web') || label.includes('site')) {
            const gitVal = contact.github || 'https://github.com/lflamonega';
            setInputValue(input, gitVal);
            filled.push({ field: 'github', value: gitVal, label: label });
        } else if (input.required || input.getAttribute('aria-required') === 'true') {
            unknown.push({ type: 'text', label: label, name: input.name });
        }
    }

    // 1.1 Textareas (Portfolio, Links, Cover Letter, Notes)
    const textareas = Array.from(modal.querySelectorAll('textarea'));
    for (const ta of textareas) {
        const label = getLabel(ta).toLowerCase();
        if (ta.value && ta.value.trim() !== '') continue;

        if (label.includes('github') || label.includes('portfolio') || label.includes('web') || label.includes('link') || label.includes('url')) {
            const gitVal = contact.github || 'https://github.com/lflamonega';
            setInputValue(ta, gitVal);
            filled.push({ field: 'portfolio_textarea', value: gitVal, label: label });
        } else if (label.includes('linkedin') || label.includes('perfil')) {
            const liVal = contact.linkedin || 'https://www.linkedin.com/in/lflamonega';
            setInputValue(ta, liVal);
            filled.push({ field: 'linkedin_textarea', value: liVal, label: label });
        } else if (label.includes('cover') || label.includes('carta') || label.includes('presentación') || label.includes('summary')) {
            const sumVal = p.summary || '';
            if (sumVal) {
                setInputValue(ta, sumVal);
                filled.push({ field: 'summary_textarea', value: sumVal.slice(0, 30), label: label });
            }
        }
    }

    // 2. Selects / Dropdowns
    const selects = Array.from(modal.querySelectorAll('select'));
    for (const select of selects) {
        const label = getLabel(select).toLowerCase();
        let chosenVal = null;
        const options = Array.from(select.options);

        const hasArgentina = options.find(o => o.text.trim().toLowerCase() === 'argentina' || o.text.includes('Argentina') || o.value.toLowerCase() === 'ar');
        if (hasArgentina && !chosenVal) {
            chosenVal = hasArgentina.value;
        } else if (label.includes('país') || label.includes('country') || label.includes('código de país') || label.includes('phone country') || label.includes('residencia') || label.includes('nationality')) {
            const opt = options.find(o => o.value.toLowerCase() === 'ar' || o.text.toLowerCase().includes('argentina') || o.text.includes('+54'));
            if (opt) chosenVal = opt.value;
        } else if (label.includes('ciudad') || label.includes('city') || label.includes('location') || label.includes('provincia') || label.includes('state')) {
            const opt = options.find(o => o.text.toLowerCase().includes('buenos aires') || o.text.toLowerCase().includes('berisso') || o.text.toLowerCase().includes('la plata'));
            if (opt) chosenVal = opt.value;
        } else if (label.includes('inglés') || label.includes('english') || label.includes('idioma') || label.includes('language')) {
            const opt = options.find(o => o.text.toLowerCase().includes('professional') || o.text.toLowerCase().includes('avanzado') || o.text.toLowerCase().includes('c1') || o.text.toLowerCase().includes('b2') || o.text.toLowerCase().includes('conversational') || o.text.toLowerCase().includes('intermedio'));
            if (opt) chosenVal = opt.value;
        } else if (label.includes('educación') || label.includes('degree') || label.includes('nivel de estudios') || label.includes('título')) {
            const opt = options.find(o => o.text.toLowerCase().includes('bachelor') || o.text.toLowerCase().includes('licenciatura') || o.text.toLowerCase().includes('universitario') || o.text.toLowerCase().includes('college'));
            if (opt) chosenVal = opt.value;
        } else if (label.includes('autorizad') || label.includes('authorized') || label.includes('permit') || label.includes('legal')) {
            const opt = options.find(o => o.text.toLowerCase() === 'yes' || o.text.toLowerCase() === 'sí' || o.text.toLowerCase() === 'si');
            if (opt) chosenVal = opt.value;
        } else if (label.includes('patrocinio') || label.includes('sponsorship') || label.includes('sponsor') || label.includes('visa')) {
            const opt = options.find(o => o.text.toLowerCase() === 'no');
            if (opt) chosenVal = opt.value;
        } else if (label.includes('remoto') || label.includes('remote') || label.includes('híbrido') || label.includes('hybrid') || label.includes('presencial') || label.includes('relocate')) {
            const opt = options.find(o => o.text.toLowerCase() === 'yes' || o.text.toLowerCase() === 'sí' || o.text.toLowerCase() === 'si');
            if (opt) chosenVal = opt.value;
        }

        if (chosenVal !== null) {
            select.value = chosenVal;
            select.selectedIndex = options.findIndex(o => o.value === chosenVal);
            select.dispatchEvent(new Event('input', { bubbles: true }));
            select.dispatchEvent(new Event('change', { bubbles: true }));
            select.dispatchEvent(new Event('blur', { bubbles: true }));
            filled.push({ field: 'select', value: chosenVal, label: label });
        } else if (!select.value && (select.required || select.getAttribute('aria-required') === 'true')) {
            unknown.push({ type: 'select', label: label, options: options.map(o => o.text) });
        }
    }

    // 3. Radio groups (Yes/No questions)
    const fieldsets = Array.from(modal.querySelectorAll('fieldset, .fb-dash-form-element, div[data-test-form-builder-radio-button-form-component]'));
    for (const fs of fieldsets) {
        const radios = Array.from(fs.querySelectorAll('input[type="radio"]'));
        if (radios.length === 0) continue;
        const anyChecked = radios.some(r => r.checked);
        if (anyChecked) continue;

        const legend = (fs.querySelector('legend, label')?.innerText || '').toLowerCase();
        let targetRadio = null;

        // Positive questions (Yes)
        if (legend.includes('autorizad') || legend.includes('authorized') || legend.includes('argentina') ||
            legend.includes('experience') || legend.includes('experiencia') || legend.includes('comfortable') ||
            legend.includes('cómodo') || legend.includes('background check') || legend.includes('agree') ||
            legend.includes('remoto') || legend.includes('remote') || legend.includes('disponib') || legend.includes('available')) {
            targetRadio = radios.find(r => {
                const txt = (r.closest('label')?.innerText || r.value || '').toLowerCase();
                return txt.includes('yes') || txt.includes('sí') || txt.includes('si');
            });
        }
        // Negative questions (No sponsorship needed)
        else if (legend.includes('sponsorship') || legend.includes('patrocinio') || legend.includes('sponsor') || legend.includes('visa required') || legend.includes('requiere visa')) {
            targetRadio = radios.find(r => {
                const txt = (r.closest('label')?.innerText || r.value || '').toLowerCase();
                return txt.includes('no');
            });
        }
        // Default to Yes for affirmative questions
        else {
            targetRadio = radios.find(r => {
                const txt = (r.closest('label')?.innerText || r.value || '').toLowerCase();
                return txt.includes('yes') || txt.includes('sí') || txt.includes('si');
            });
        }

        if (targetRadio) {
            targetRadio.click();
            targetRadio.checked = true;
            targetRadio.dispatchEvent(new Event('change', { bubbles: true }));
            filled.push({ field: 'radio', value: targetRadio.value, label: legend.slice(0, 50) });
        } else {
            unknown.push({ type: 'radio', label: legend.slice(0, 50) });
        }
    }

    // 4. Uncheck "Follow company"
    const checkboxes = Array.from(modal.querySelectorAll('input[type="checkbox"]'));
    for (const cb of checkboxes) {
        const label = getLabel(cb).toLowerCase();
        if (label.includes('follow') || label.includes('seguir') || label.includes('empresa') || cb.name.includes('followCompany')) {
            if (cb.checked) {
                cb.click();
                cb.checked = false;
                cb.dispatchEvent(new Event('change', { bubbles: true }));
                filled.push({ field: 'unfollow_company', value: 'unchecked', label: label });
            }
        }
    }

    // 5. Detect next/submit buttons
    const submitBtn = modal.querySelector('button[aria-label*="Submit application"]') ||
                      modal.querySelector('button[aria-label*="Enviar solicitud"]') ||
                      Array.from(modal.querySelectorAll('button')).find(b => {
                          const t = (b.innerText || '').toLowerCase().trim();
                          return t === 'submit' || t === 'enviar solicitud' || t === 'enviar';
                      });

    const nextBtn = modal.querySelector('button[aria-label*="Continue"]') ||
                    modal.querySelector('button[aria-label*="Review"]') ||
                    modal.querySelector('button[aria-label*="Siguiente"]') ||
                    modal.querySelector('button[aria-label*="Revisar"]') ||
                    modal.querySelector('button.artdeco-button--primary') ||
                    Array.from(modal.querySelectorAll('button')).find(b => {
                        const t = (b.innerText || '').toLowerCase().trim();
                        return t === 'next' || t === 'continue' || t === 'review' || t === 'siguiente' || t === 'continuar' || t === 'revisar';
                    });

    return {
        filled: filled,
        unknown_required: unknown,
        has_submit: !!submitBtn,
        has_next: !!nextBtn,
        next_button_text: nextBtn ? nextBtn.innerText.trim() : (submitBtn ? submitBtn.innerText.trim() : '')
    };
}
"""


async def auto_fill_current_step() -> dict[str, Any]:
    """Inspect and auto-fill the current Easy Apply step using user profile data."""
    page = get_page()
    if page is None:
        return {"error": "Browser not started"}

    profile = load_profile()
    profile_data = profile.model_dump()

    try:
        result = await page.evaluate(_AUTOFILL_EVALUATE_JS, profile_data)
        logger.info(
            "Auto-filled {} fields, {} unknown required, has_submit={}, has_next={}",
            len(result.get("filled", [])),
            len(result.get("unknown_required", [])),
            result.get("has_submit"),
            result.get("has_next"),
        )
        return result
    except Exception as e:
        logger.error("Auto-fill evaluation failed: {}", e)
        return {"error": str(e)}


async def step_easy_apply_wizard(auto_advance: bool = True) -> dict[str, Any]:
    """Auto-fills the current step and optionally clicks Next/Review/Submit.

    Returns the step execution summary and next page state.
    """
    page = get_page()
    if page is None:
        return {"error": "Browser not started"}

    # 1. Fill current step fields
    fill_result = await auto_fill_current_step()
    if "error" in fill_result:
        return fill_result

    if not auto_advance:
        return fill_result

    # 2. Check if we reached final submit
    if fill_result.get("has_submit") and not fill_result.get("has_next"):
        settings = get_settings()
        if settings.apply.dry_run:
            logger.info("Reached Submit step in dry_run mode — stopping before submission")
            return {
                "status": "ready_to_submit_dry_run_blocked",
                "filled": fill_result.get("filled", []),
                "message": "Application is complete and ready to submit (blocked by dry_run=true).",
            }

    # 3. Advance to next step
    next_selectors = [
        'button[aria-label*="Siguiente"]',
        'button[aria-label*="Revisar"]',
        'button[aria-label*="Continue"]',
        'button[aria-label*="Review"]',
        'button.artdeco-button--primary',
        'button:has-text("Siguiente")',
        'button:has-text("Continuar")',
        'button:has-text("Revisar")',
        'button:has-text("Next")',
        'button:has-text("Review")',
    ]

    clicked = False
    for selector in next_selectors:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=1500):
                btn_text = await btn.inner_text()
                await btn.click(timeout=3000)
                await human_delay()
                clicked = True
                logger.info("Clicked wizard advance button: '{}'", btn_text)
                break
        except Exception:
            continue

    return {
        "status": "advanced" if clicked else "no_advance_button",
        "filled": fill_result.get("filled", []),
        "unknown_required": fill_result.get("unknown_required", []),
        "next_button_text": fill_result.get("next_button_text", ""),
    }


async def auto_apply_full_flow(max_steps: int = 8) -> dict[str, Any]:
    """Execute the entire Easy Apply wizard automatically until review/submit."""
    page = get_page()
    if page is None:
        return {"error": "Browser not started"}

    all_filled = []
    step_count = 0

    for step in range(max_steps):
        step_count += 1
        logger.info("Executing Easy Apply step {}/{}...", step_count, max_steps)
        res = await step_easy_apply_wizard(auto_advance=True)

        if "error" in res:
            return {"error": res["error"], "steps_completed": step_count, "filled": all_filled}

        all_filled.extend(res.get("filled", []))

        if res.get("status") == "ready_to_submit_dry_run_blocked":
            return {
                "status": "dry_run_completed",
                "steps_completed": step_count,
                "total_fields_filled": len(all_filled),
                "filled_details": all_filled,
                "message": "Easy Apply completed successfully up to the final Review/Submit screen (dry_run protected).",
            }

        if res.get("status") == "no_advance_button":
            # Check if modal is still open
            modal_info = await page.evaluate("""
                () => {
                    const modal = document.querySelector('.jobs-easy-apply-modal') ||
                                  document.querySelector('[role="dialog"]') ||
                                  document.querySelector('.artdeco-modal');
                    if (!modal) return { open: false };
                    
                    const submitBtn = modal.querySelector('button[aria-label*="Submit"]') ||
                                      modal.querySelector('button[aria-label*="Enviar"]') ||
                                      Array.from(modal.querySelectorAll('button')).find(b => {
                                          const t = (b.innerText || '').toLowerCase().trim();
                                          return t === 'submit' || t === 'enviar solicitud' || t === 'enviar';
                                      });
                    return {
                        open: true,
                        has_submit: !!submitBtn,
                        text_sample: modal.innerText.slice(0, 200)
                    };
                }
            """)

            if not modal_info.get("open"):
                return {
                    "status": "submitted_and_closed",
                    "steps_completed": step_count,
                    "total_fields_filled": len(all_filled),
                }

            if modal_info.get("has_submit"):
                settings = get_settings()
                if settings.apply.dry_run:
                    return {
                        "status": "dry_run_completed",
                        "steps_completed": step_count,
                        "total_fields_filled": len(all_filled),
                        "filled_details": all_filled,
                        "message": "Reached final Submit screen (blocked by dry_run=true).",
                    }

            # Check if there are validation errors on screen
            errors = await page.evaluate("""
                () => Array.from(document.querySelectorAll('.artdeco-inline-feedback--error, [data-test-form-element-error-messages]'))
                           .map(e => e.innerText.trim()).filter(e => e.length > 0)
            """)
            if errors:
                return {
                    "status": "validation_error",
                    "errors": errors,
                    "steps_completed": step_count,
                    "filled_details": all_filled,
                }

            return {
                "status": "stopped",
                "reason": "Modal still open but no advance button found",
                "steps_completed": step_count,
                "filled_details": all_filled,
            }

        # Wait for next screen animation to finish
        await asyncio.sleep(2.5)

    return {
        "status": "step_limit_reached",
        "steps_completed": step_count,
        "total_fields_filled": len(all_filled),
        "filled_details": all_filled,
    }
