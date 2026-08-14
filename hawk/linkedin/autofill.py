"""Auto-fill engine for LinkedIn Easy Apply forms using user profile data."""
import asyncio
import json
import re
from typing import Any

from loguru import logger
from playwright.async_api import Page

from hawk.browser.driver import get_page
from hawk.linkedin.operations import _EASY_APPLY_ROOT_JS, human_delay, upload_resume
from hawk.profile import load_profile
from hawk.settings import get_settings


_AUTOFILL_EVALUATE_JS = r"""
(profileData) => {
""" + _EASY_APPLY_ROOT_JS + r"""
    const filled = [];
    const unknown = [];

    // Find form root container
    const root = easyApplyRoot();

    // Helper: trigger React / Angular / LinkedIn input events
    function setInputValue(el, val) {
        if (!el || val === undefined || val === null) return;
        const strVal = String(val);
        el.focus();
        const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
        const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (nativeSetter) {
            nativeSetter.call(el, strVal);
        } else {
            el.value = strVal;
        }
        el.setAttribute('value', strVal);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
    }

    // Helper: find clean label text for an element
    function getLabel(el) {
        if (!el) return '';
        if (el.id) {
            try {
                const labelFor = document.querySelector(`label[for="${el.id}"]`);
                if (labelFor && labelFor.innerText.trim()) {
                    return labelFor.innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
                }
            } catch(e) {}
        }
        if (el.labels && el.labels[0] && el.labels[0].innerText.trim()) {
            return el.labels[0].innerText.split('\n')[0].replace(/\s+/g, ' ').trim();
        }
        const parent = el.closest(
            '.jobs-easy-apply-form-section__group, .fb-dash-form-element, ' +
            'div[data-test-form-element], div[data-test-single-line-text-form-component], ' +
            'div[data-test-form-builder-text-input], div[data-test-dropdown-form-component], ' +
            'div[data-test-form-builder-radio-button-form-component], ' +
            'div[data-test-text-entity-list-form-component], div.jobs-easy-apply-form-element, ' +
            'fieldset, div.artdeco-text-input--container'
        ) || el.parentElement;

        const labelEl = parent ? parent.querySelector('label, legend, .fb-dash-form-element__label, span.t-14, p, h3') : null;
        let text = (labelEl ? labelEl.innerText : '') || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '';
        return text.split('\n')[0].replace(/\s+/g, ' ').trim();
    }

    const p = profileData || {};
    const personal = p.personal || p.contact || {};
    const links = p.links || {};
    const professional = p.professional || {};
    const auth = p.work_authorization || p.legal || {};
    const educ = p.education || {};
    const salary = p.salary || {};
    const pref = p.preferences || p.work_preferences || {};
    const skills = p.skills || {};
    const commonAnswers = p.common_answers || {};

    const defaultYears = professional.years_of_experience || '2';
    const phoneVal = personal.phone || '221 695 9945';
    const emailVal = personal.email || 'lflamonega@gmail.com';
    const cityVal = personal.city ? `${personal.city}, ${personal.country || 'Argentina'}` : 'Berisso, Argentina';
    const postalVal = personal.postal_code || '1923';
    
    let rawLi = links.linkedin || 'https://www.linkedin.com/in/lflamonega';
    if (!rawLi.startsWith('http')) rawLi = 'https://' + (rawLi.startsWith('www.') ? '' : 'www.') + rawLi;
    else if (rawLi.startsWith('https://linkedin.com')) rawLi = rawLi.replace('https://linkedin.com', 'https://www.linkedin.com');
    const liVal = rawLi;

    let rawGit = links.github || 'https://github.com/lflamonega';
    if (!rawGit.startsWith('http')) rawGit = 'https://' + rawGit;
    const gitVal = rawGit;

    const portVal = links.portfolio ? (links.portfolio.startsWith('http') ? links.portfolio : `https://${links.portfolio}`) : gitVal;
    const salaryVal = salary.expected ? String(salary.expected).replace(/[^0-9]/g, '') || '950' : '950';

    // 0. Check common_answers cache for any element
    function checkCommonAnswers(label) {
        const cleanL = label.toLowerCase().trim();
        for (const [q, a] of Object.entries(commonAnswers)) {
            if (cleanL.includes(q.toLowerCase().trim()) || q.toLowerCase().trim().includes(cleanL)) {
                return a;
            }
        }
        return null;
    }

    // 1. Phone inputs
    const phoneInputs = Array.from(root.querySelectorAll('input[type="tel"], input[id*="phoneNumber"], input[name*="phone"], input[id*="phone"]'));
    for (const input of phoneInputs) {
        if (!input.value || input.value.trim() === '') {
            setInputValue(input, phoneVal);
            filled.push({ field: 'phone', value: phoneVal, label: getLabel(input) });
        }
    }

    // 2. All text, number, and email inputs
    const allTextInputs = Array.from(root.querySelectorAll('input[type="text"], input[type="email"], input[type="number"], input[type="url"], input:not([type])'));
    for (const input of allTextInputs) {
        const rawLabel = getLabel(input);
        const label = rawLabel.toLowerCase();
        if (input.value && input.value.trim() !== '') continue;

        const cached = checkCommonAnswers(label);
        if (cached !== null) {
            setInputValue(input, cached);
            filled.push({ field: 'cached_answer', value: cached, label: rawLabel });
            continue;
        }

        if (label.includes('teléfono') || label.includes('telefono') || label.includes('phone') || label.includes('celular') || label.includes('móvil') || label.includes('mobile')) {
            setInputValue(input, phoneVal);
            filled.push({ field: 'phone', value: phoneVal, label: rawLabel });
        } else if (label.includes('email') || label.includes('correo') || label.includes('dirección de correo') || input.type === 'email') {
            setInputValue(input, emailVal);
            filled.push({ field: 'email', value: emailVal, label: rawLabel });
        } else if (label.includes('first name') || (label.includes('nombre') && !label.includes('completo') && !label.includes('empresa'))) {
            const fName = personal.first_name || 'Laureano';
            setInputValue(input, fName);
            filled.push({ field: 'first_name', value: fName, label: rawLabel });
        } else if (label.includes('last name') || label.includes('apellido') || label.includes('surname')) {
            const lName = personal.last_name || 'Francisco Lamonega';
            setInputValue(input, lName);
            filled.push({ field: 'last_name', value: lName, label: rawLabel });
        } else if (label.includes('full name') || label.includes('nombre completo')) {
            const fullName = `${personal.first_name || 'Laureano'} ${personal.last_name || 'Francisco Lamonega'}`.trim();
            setInputValue(input, fullName);
            filled.push({ field: 'full_name', value: fullName, label: rawLabel });
        } else if (label.includes('ciudad') || label.includes('city') || label.includes('ubicación') || label.includes('location') || label.includes('localidad')) {
            setInputValue(input, cityVal);
            filled.push({ field: 'city', value: cityVal, label: rawLabel });
        } else if (label.includes('código postal') || label.includes('codigo postal') || label.includes('postal code') || label.includes('zip')) {
            setInputValue(input, postalVal);
            filled.push({ field: 'postal_code', value: postalVal, label: rawLabel });
        } else if (label.includes('años de experiencia') || label.includes('anos de experiencia') || label.includes('years of experience') || label.includes('cuántos años') || label.includes('cuantos anos') || label.includes('how many years')) {
            // Check specific skill match in skills dict
            let expYears = defaultYears;
            for (const [skillName, skillYears] of Object.entries(skills)) {
                if (label.includes(skillName.toLowerCase())) {
                    expYears = String(skillYears);
                    break;
                }
            }
            setInputValue(input, expYears);
            filled.push({ field: 'experience_years', value: expYears, label: rawLabel });
        } else if (label.includes('salario') || label.includes('salary') || label.includes('remuneración') || label.includes('remuneracion') || label.includes('pretendida') || label.includes('compensation') || label.includes('sueldo')) {
            const isArs = label.includes('pesos') || label.includes('ars') || label.includes('argentino') || label.includes('argentina');
            const isUsd = label.includes('usd') || label.includes('dolar') || label.includes('dólar') || label.includes('dollar');
            const profileCurrency = ((salary && salary.currency) || 'USD').toUpperCase();

            if (isArs && profileCurrency !== 'ARS') {
                const cachedArs = checkCommonAnswers('salario pesos') || checkCommonAnswers('remuneracion pesos') || checkCommonAnswers('salario en pesos');
                if (cachedArs !== null) {
                    setInputValue(input, cachedArs);
                    filled.push({ field: 'salary_ars_cached', value: cachedArs, label: rawLabel });
                } else {
                    unknown.push({ type: 'salary_currency_mismatch', label: rawLabel, expected_currency: 'ARS', profile_currency: profileCurrency, profile_salary: salary.expected });
                }
            } else if (isUsd && profileCurrency !== 'USD') {
                const cachedUsd = checkCommonAnswers('salario usd') || checkCommonAnswers('salary usd');
                if (cachedUsd !== null) {
                    setInputValue(input, cachedUsd);
                    filled.push({ field: 'salary_usd_cached', value: cachedUsd, label: rawLabel });
                } else {
                    unknown.push({ type: 'salary_currency_mismatch', label: rawLabel, expected_currency: 'USD', profile_currency: profileCurrency, profile_salary: salary.expected });
                }
            } else {
                setInputValue(input, salaryVal);
                filled.push({ field: 'salary', value: salaryVal, label: rawLabel });
            }
        } else if (label.includes('linkedin') || label.includes('perfil')) {
            setInputValue(input, liVal);
            filled.push({ field: 'linkedin', value: liVal, label: rawLabel });
        } else if (label.includes('github')) {
            setInputValue(input, gitVal);
            filled.push({ field: 'github', value: gitVal, label: rawLabel });
        } else if (label.includes('portfolio') || label.includes('portafolio') || label.includes('web') || label.includes('sitio') || label.includes('site') || label.includes('url')) {
            setInputValue(input, portVal);
            filled.push({ field: 'portfolio', value: portVal, label: rawLabel });
        } else if (input.required || input.getAttribute('aria-required') === 'true') {
            unknown.push({ type: 'text', label: rawLabel, name: input.name });
        }
    }

    // 3. Textareas (Portfolio, Links, Cover Letter, Summary)
    const textareas = Array.from(root.querySelectorAll('textarea'));
    for (const ta of textareas) {
        const rawLabel = getLabel(ta);
        const label = rawLabel.toLowerCase();
        if (ta.value && ta.value.trim() !== '') continue;

        const cached = checkCommonAnswers(label);
        if (cached !== null) {
            setInputValue(ta, cached);
            filled.push({ field: 'cached_textarea', value: cached, label: rawLabel });
            continue;
        }

        if (label.includes('github')) {
            setInputValue(ta, gitVal);
            filled.push({ field: 'github_textarea', value: gitVal, label: rawLabel });
        } else if (label.includes('portfolio') || label.includes('portafolio') || label.includes('web') || label.includes('link') || label.includes('url') || label.includes('enlace')) {
            setInputValue(ta, portVal);
            filled.push({ field: 'portfolio_textarea', value: portVal, label: rawLabel });
        } else if (label.includes('linkedin') || label.includes('perfil')) {
            setInputValue(ta, liVal);
            filled.push({ field: 'linkedin_textarea', value: liVal, label: rawLabel });
        } else if (label.includes('cover') || label.includes('carta') || label.includes('presentación') || label.includes('presentacion') || label.includes('summary') || label.includes('resumen') || label.includes('about')) {
            const sumVal = professional.summary || p.summary || '';
            if (sumVal) {
                setInputValue(ta, sumVal);
                filled.push({ field: 'summary_textarea', value: sumVal.slice(0, 30), label: rawLabel });
            }
        }
    }

    // 4. Selects / Dropdowns
    const selects = Array.from(root.querySelectorAll('select'));
    for (const select of selects) {
        const rawLabel = getLabel(select);
        const label = rawLabel.toLowerCase();
        let chosenVal = null;
        const options = Array.from(select.options);

        const hasArgentina = options.find(o => o.text.trim().toLowerCase() === 'argentina' || o.text.includes('Argentina') || o.value.toLowerCase() === 'ar');
        
        if (label.includes('país') || label.includes('pais') || label.includes('country') || label.includes('código de país') || label.includes('phone country') || label.includes('residencia') || label.includes('nationality') || label.includes('nacionalidad')) {
            const opt = options.find(o => o.value.toLowerCase() === 'ar' || o.text.toLowerCase().includes('argentina') || o.text.includes('+54'));
            if (opt) chosenVal = opt.value;
        } else if (hasArgentina && !chosenVal && !select.value) {
            chosenVal = hasArgentina.value;
        } else if (label.includes('ciudad') || label.includes('city') || label.includes('location') || label.includes('provincia') || label.includes('state')) {
            const opt = options.find(o => o.text.toLowerCase().includes('buenos aires') || o.text.toLowerCase().includes('berisso') || o.text.toLowerCase().includes('la plata'));
            if (opt) chosenVal = opt.value;
        } else if (label.includes('inglés') || label.includes('ingles') || label.includes('english') || label.includes('idioma') || label.includes('language')) {
            const profileEng = ((p.languages && p.languages.english) || 'Professional').toLowerCase();
            let syns = [];
            if (profileEng.includes('prof') || profileEng.includes('adv') || profileEng.includes('avanz')) {
                syns = ['professional', 'profesional', 'avanzado', 'advanced', 'c1', 'c2', 'fluido', 'fluent', 'full professional', 'competencia profesional'];
            } else if (profileEng.includes('conv') || profileEng.includes('interm')) {
                syns = ['conversational', 'conversacion', 'conversación', 'intermedio', 'intermediate', 'b1', 'b2', 'competencia básica profesional'];
            } else if (profileEng.includes('nat') || profileEng.includes('bil')) {
                syns = ['native', 'nativo', 'bilingual', 'bilingüe', 'bilingue', 'competencia bilingüe'];
            } else {
                syns = ['professional', 'profesional', 'avanzado', 'advanced', 'c1', 'conversational', 'conversacion', 'conversación', 'fluent', 'fluido'];
            }
            const opt = options.find(o => {
                const t = o.text.toLowerCase();
                const v = o.value.toLowerCase();
                return syns.some(s => t.includes(s) || v.includes(s));
            });
            if (opt) chosenVal = opt.value;
        } else if (label.includes('educación') || label.includes('educacion') || label.includes('degree') || label.includes('nivel de estudios') || label.includes('título') || label.includes('titulo') || label.includes('estudios')) {
            const opt = options.find(o => {
                const t = o.text.toLowerCase();
                const v = o.value.toLowerCase();
                const syns = ['bachelor', 'licenciatura', 'universitario', 'universidad', 'grado', 'bachelor\'s', 'ingeniería', 'ingenieria', 'terciario', 'college', 'completo', 'en curso'];
                return syns.some(s => t.includes(s) || v.includes(s));
            });
            if (opt) chosenVal = opt.value;
        } else if (label.includes('autorizad') || label.includes('authorized') || label.includes('permit') || label.includes('legal') || label.includes('habilitad') || label.includes('work authorization') || label.includes('derecho a trabajar')) {
            const opt = options.find(o => {
                const t = o.text.toLowerCase();
                const v = o.value.toLowerCase();
                return t === 'yes' || t === 'sí' || t === 'si' || v === 'yes' || v === 'true' || t.includes('autorizado') || t.includes('habilitado');
            });
            if (opt) chosenVal = opt.value;
        } else if (label.includes('patrocinio') || label.includes('sponsorship') || label.includes('sponsor') || label.includes('visa')) {
            const opt = options.find(o => {
                const t = o.text.toLowerCase();
                const v = o.value.toLowerCase();
                return t === 'no' || v === 'no' || v === 'false' || t.includes('no requiero') || t.includes('no requiere') || t.includes('no preciso');
            });
            if (opt) chosenVal = opt.value;
        } else if (label.includes('remoto') || label.includes('remote') || label.includes('híbrido') || label.includes('hibrido') || label.includes('hybrid') || label.includes('presencial') || label.includes('relocate') || label.includes('modalidad')) {
            const opt = options.find(o => {
                const t = o.text.toLowerCase();
                const v = o.value.toLowerCase();
                return t === 'yes' || t === 'sí' || t === 'si' || v === 'yes' || v === 'true' || t.includes('remoto') || t.includes('híbrido') || t.includes('hibrido');
            });
            if (opt) chosenVal = opt.value;
        }

        if (chosenVal !== null) {
            select.value = chosenVal;
            select.selectedIndex = options.findIndex(o => o.value === chosenVal);
            select.dispatchEvent(new Event('input', { bubbles: true }));
            select.dispatchEvent(new Event('change', { bubbles: true }));
            select.dispatchEvent(new Event('blur', { bubbles: true }));
            filled.push({ field: 'select', value: chosenVal, label: rawLabel });
        } else if (!select.value && (select.required || select.getAttribute('aria-required') === 'true')) {
            unknown.push({ type: 'select', label: rawLabel, options: options.map(o => o.text) });
        }
    }

    // 5. Radio groups (Yes/No questions)
    const fieldsets = Array.from(root.querySelectorAll('fieldset, .fb-dash-form-element, div[data-test-form-builder-radio-button-form-component]'));
    for (const fs of fieldsets) {
        const radios = Array.from(fs.querySelectorAll('input[type="radio"]'));
        if (radios.length === 0) continue;
        const anyChecked = radios.some(r => r.checked);
        if (anyChecked) continue;

        const rawLegend = fs.querySelector('legend, label, .fb-dash-form-element__label')?.innerText || '';
        const legend = rawLegend.toLowerCase();
        let targetRadio = null;

        const cached = checkCommonAnswers(legend);
        if (cached !== null) {
            targetRadio = radios.find(r => {
                const txt = (r.closest('label')?.innerText || r.value || '').toLowerCase();
                return txt.includes(cached.toLowerCase()) || r.value.toLowerCase() === cached.toLowerCase();
            });
        }

        if (!targetRadio) {
            // Negative questions: Visa sponsorship, criminal record, restrictions -> NO
            if (legend.includes('sponsorship') || legend.includes('patrocinio') || legend.includes('sponsor') || 
                legend.includes('visa required') || legend.includes('requiere visa') || legend.includes('require visa') ||
                legend.includes('visa sponsorship') || legend.includes('need visa')) {
                targetRadio = radios.find(r => {
                    const txt = (r.closest('label')?.innerText || r.value || '').toLowerCase();
                    return txt === 'no' || txt.includes('no');
                });
            }
            // Positive questions: Legal authorization, remote, experience, comfortable, etc. -> YES
            else if (legend.includes('autorizad') || legend.includes('autorizaci') || legend.includes('authorized') || legend.includes('argentina') ||
                     legend.includes('experience') || legend.includes('experiencia') || legend.includes('comfortable') ||
                     legend.includes('cómodo') || legend.includes('comodo') || legend.includes('background check') || 
                     legend.includes('agree') || legend.includes('acepto') || legend.includes('de acuerdo') ||
                     legend.includes('remoto') || legend.includes('remote') || legend.includes('disponib') || 
                     legend.includes('available') || legend.includes('habilitad') || legend.includes('habilitaci') || legend.includes('right to work')) {
                targetRadio = radios.find(r => {
                    const txt = (r.closest('label')?.innerText || r.value || '').toLowerCase();
                    return txt.includes('yes') || txt.includes('sí') || txt.includes('si');
                });
            }
            // Default to Yes for standard affirmative screening questions
            else {
                targetRadio = radios.find(r => {
                    const txt = (r.closest('label')?.innerText || r.value || '').toLowerCase();
                    return txt.includes('yes') || txt.includes('sí') || txt.includes('si');
                });
            }
        }

        if (targetRadio) {
            targetRadio.click();
            targetRadio.checked = true;
            targetRadio.dispatchEvent(new Event('change', { bubbles: true }));
            filled.push({ field: 'radio', value: targetRadio.value, label: rawLegend.slice(0, 60) });
        } else {
            unknown.push({ type: 'radio', label: rawLegend.slice(0, 60) });
        }
    }

    // 6. Uncheck "Follow company" / "Seguir a la empresa"
    const checkboxes = Array.from(root.querySelectorAll('input[type="checkbox"]'));
    for (const cb of checkboxes) {
        const rawLabel = getLabel(cb);
        const label = rawLabel.toLowerCase();
        if (label.includes('follow') || label.includes('seguir') || label.includes('empresa') || (cb.name && cb.name.includes('followCompany'))) {
            if (cb.checked) {
                cb.click();
                cb.checked = false;
                cb.dispatchEvent(new Event('change', { bubbles: true }));
                filled.push({ field: 'unfollow_company', value: 'unchecked', label: rawLabel });
            }
        }
    }

    // 7. Detect Next/Submit buttons (searched across entire DOCUMENT)
    const submitBtn = document.querySelector('button[aria-label*="Submit application"]') ||
                      document.querySelector('button[aria-label*="Enviar solicitud"]') ||
                      document.querySelector('button[aria-label*="Enviar candidatura"]') ||
                      document.querySelector('button[aria-label*="Bewerbung senden"]') ||
                      document.querySelector('button[aria-label*="Invia candidatura"]') ||
                      Array.from(document.querySelectorAll('button')).find(b => {
                          const t = (b.innerText || '').toLowerCase().trim();
                          return t === 'submit' || t === 'enviar solicitud' || t === 'enviar' || t === 'enviar candidatura';
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
                        return t === 'next' || t === 'continue' || t === 'review' || 
                               t === 'siguiente' || t === 'continuar' || t === 'revisar' || 
                               t === 'avançar' || t === 'seguinte' || t === 'suivant';
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


async def step_easy_apply_wizard(
    auto_advance: bool = True,
    override_dry_run: bool | None = None,
    resume_path: str | None = None,
) -> dict[str, Any]:
    """Auto-fills the current step and optionally clicks Next/Review/Submit.

    If resume_path is provided and the current step contains a resume upload option,
    the file is uploaded automatically before advancing.

    Returns the step execution summary and next page state.
    """
    page = get_page()
    if page is None:
        return {"error": "Browser not started"}

    # 1. Fill current step fields
    fill_result = await auto_fill_current_step()
    if "error" in fill_result:
        return fill_result

    # 1.5. If resume_path provided, check if this is the resume step
    if resume_path:
        try:
            has_upload = await page.locator(
                'button:has-text("Cargar currículum"), button:has-text("Upload resume"), '
                'label:has-text("Cargar currículum"), label:has-text("Upload resume"), '
                'div[role="button"]:has-text("Cargar currículum"), div[role="button"]:has-text("Upload resume")'
            ).count() > 0
            if has_upload:
                upload_res = await upload_resume(resume_path)
                logger.info("Auto-upload resume during wizard: {}", upload_res)
                if not upload_res.startswith("error"):
                    fill_result.setdefault("filled", []).append({
                        "field": "resume_upload",
                        "value": resume_path,
                        "status": upload_res,
                    })
        except Exception as e:
            logger.warning("Resume upload check failed: {}", e)

    if not auto_advance:
        return fill_result

    # 2. Check if we reached final submit
    if fill_result.get("has_submit") and not fill_result.get("has_next"):
        settings = get_settings()
        is_dry = override_dry_run if override_dry_run is not None else settings.apply.dry_run
        if is_dry:
            logger.info("Reached Submit step in dry_run mode — stopping before submission")
            return {
                "status": "ready_to_submit_dry_run_blocked",
                "filled": fill_result.get("filled", []),
                "message": "Application is complete and ready to submit (blocked by dry_run=true).",
            }

    # 3. Advance to next step
    next_selectors = [
        'button[aria-label*="Siguiente"]',
        'button[aria-label*="Continuar"]',
        'button[aria-label*="Revisar"]',
        'button[aria-label*="Continue"]',
        'button[aria-label*="Review"]',
        'button[aria-label*="Next"]',
        'button[aria-label*="Avançar"]',
        'button.artdeco-button--primary',
        'button:has-text("Siguiente")',
        'button:has-text("Continuar")',
        'button:has-text("Revisar")',
        'button:has-text("Next")',
        'button:has-text("Continue")',
        'button:has-text("Review")',
        'button:has-text("Avançar")',
    ]

    clicked = False
    for selector in next_selectors:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=1500):
                btn_text = await btn.inner_text()
                await btn.scroll_into_view_if_needed()
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


async def auto_apply_full_flow(
    max_steps: int = 8,
    override_dry_run: bool | None = None,
    resume_path: str | None = None,
) -> dict[str, Any]:
    """Execute the entire Easy Apply wizard automatically until review/submit."""
    page = get_page()
    if page is None:
        return {"error": "Browser not started"}

    all_filled = []
    step_count = 0

    for step in range(max_steps):
        step_count += 1
        logger.info("Executing Easy Apply step {}/{}...", step_count, max_steps)
        res = await step_easy_apply_wizard(
            auto_advance=True,
            override_dry_run=override_dry_run,
            resume_path=resume_path,
        )

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
            # Check if modal or form is still open
            modal_info = await page.evaluate(
                r"""
                () => {
                """
                + _EASY_APPLY_ROOT_JS
                + r"""
                    const root = easyApplyRoot();
                    if (!root || (root === document.body && !document.querySelector('button[aria-label*="Submit"], button[aria-label*="Enviar"], button[aria-label*="Siguiente"], button[aria-label*="Continuar"], button[aria-label*="Review"], button[aria-label*="Revisar"]'))) {
                        return { open: false };
                    }
                    
                    const submitBtn = document.querySelector('button[aria-label*="Submit application"]') ||
                                      document.querySelector('button[aria-label*="Enviar solicitud"]') ||
                                      document.querySelector('button[aria-label*="Enviar candidatura"]') ||
                                      Array.from(document.querySelectorAll('button')).find(b => {
                                          const t = (b.innerText || '').toLowerCase().trim();
                                          return t === 'submit' || t === 'enviar solicitud' || t === 'enviar' || t === 'enviar candidatura';
                                      });
                    return {
                        open: true,
                        has_submit: !!submitBtn,
                        text_sample: root.innerText.slice(0, 200)
                    };
                }
                """
            )

            if not modal_info.get("open"):
                return {
                    "status": "submitted_and_closed",
                    "steps_completed": step_count,
                    "total_fields_filled": len(all_filled),
                }

            if modal_info.get("has_submit"):
                settings = get_settings()
                is_dry = override_dry_run if override_dry_run is not None else settings.apply.dry_run
                if is_dry:
                    return {
                        "status": "dry_run_completed",
                        "steps_completed": step_count,
                        "total_fields_filled": len(all_filled),
                        "filled_details": all_filled,
                        "message": "Reached final Submit screen (blocked by dry_run=true).",
                    }

            # Check if there are validation errors on screen
            errors = await page.evaluate("""
                () => Array.from(document.querySelectorAll('.artdeco-inline-feedback--error, [data-test-form-element-error-messages], .fb-dash-form-element__error-message'))
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
