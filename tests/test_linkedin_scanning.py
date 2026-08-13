"""Tests for LinkedIn site scanning and DOM extraction."""
import asyncio
import json
import pytest
from playwright.async_api import async_playwright

import hawk.browser.driver as driver_module
from hawk.linkedin.operations import (
    extract_jobs_list,
    extract_job_details,
    detect_form_fields,
    detect_fields_with_profile,
    _get_progress_percentage,
)
from hawk.profile import load_profile, match_field, UserProfile


@pytest.mark.asyncio
async def test_extract_jobs_list_modern_dom():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()

    html = """
    <!DOCTYPE html>
    <html>
    <head><title>LinkedIn Jobs Search</title></head>
    <body>
        <div class="jobs-search-results-list">
            <ul class="scaffold-layout__list-container">
                <li class="jobs-search-results__list-item" data-occludable-job-id="4123456789">
                    <div class="job-card-container" data-job-id="4123456789">
                        <div class="artdeco-entity-lockup__content">
                            <div class="job-card-list__title">
                                <a class="job-card-list__title--link" href="/jobs/view/4123456789/?trackingId=abc">
                                    <span aria-hidden="true">Senior Python Backend Engineer</span>
                                </a>
                            </div>
                            <div class="job-card-container__primary-description">
                                <span>Tech Innovations Inc.</span>
                            </div>
                            <ul class="job-card-container__metadata-wrapper">
                                <li class="job-card-container__metadata-item">Buenos Aires, Argentina (Remoto)</li>
                            </ul>
                            <div class="job-card-container__apply-method">
                                <span>Solicitud sencilla</span>
                            </div>
                        </div>
                    </div>
                </li>
                <li class="jobs-search-results__list-item" data-occludable-job-id="4987654321">
                    <div class="job-card-container" data-job-id="4987654321">
                        <div class="artdeco-entity-lockup__content">
                            <div class="job-card-list__title">
                                <a class="job-card-list__title--link" href="https://www.linkedin.com/jobs/view/devops-engineer-4987654321/">
                                    <strong>DevOps Specialist (AWS / Docker)</strong>
                                </a>
                            </div>
                            <div class="job-card-container__primary-description">
                                <span>Cloud Systems LATAM</span>
                            </div>
                            <ul class="job-card-container__metadata-wrapper">
                                <li class="job-card-container__metadata-item">Remote, Argentina</li>
                            </ul>
                            <div class="artdeco-inline-feedback">
                                <span>Solicitado hace 2 días</span>
                            </div>
                        </div>
                    </div>
                </li>
            </ul>
        </div>
    </body>
    </html>
    """
    await page.set_content(html)
    driver_module._page = page
    driver_module._browser = browser

    raw_jobs = await extract_jobs_list()
    jobs = json.loads(raw_jobs)

    assert len(jobs) == 2, f"Expected 2 jobs, got {len(jobs)}"
    
    # Job 1
    assert jobs[0]["job_id"] == "4123456789"
    assert "Python Backend" in jobs[0]["role"]
    assert jobs[0]["company"] == "Tech Innovations Inc."
    assert "Buenos Aires" in jobs[0]["location"]
    assert jobs[0]["easy_apply"] is True
    assert jobs[0]["already_applied"] is False

    # Job 2
    assert jobs[1]["job_id"] == "4987654321"
    assert "DevOps" in jobs[1]["role"]
    assert jobs[1]["company"] == "Cloud Systems LATAM"
    assert jobs[1]["already_applied"] is True

    await browser.close()
    await pw.stop()


@pytest.mark.asyncio
async def test_extract_job_details_page():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()

    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Senior Software Engineer - LinkedIn</title></head>
    <body>
        <div class="job-details-jobs-unified-top-card__title-container">
            <h1 class="job-details-jobs-unified-top-card__job-title">Senior Python DevOps Engineer</h1>
        </div>
        <div class="job-details-jobs-unified-top-card__company-name">
            <a href="/company/example-corp/">Example Global Corp</a>
        </div>
        <div class="job-details-jobs-unified-top-card__primary-description-container">
            <span>Buenos Aires, Argentina</span> · <span class="job-details-jobs-unified-top-card__workplace-type">Remoto</span>
        </div>

        <div id="job-details">
            <p>We are seeking a talented DevOps Engineer to join our team.</p>
            <p>Requirements:</p>
            <ul>
                <li>3+ years Python and Docker</li>
                <li>CI/CD pipeline architecture</li>
                <li>AWS experience (EC2, EKS)</li>
            </ul>
        </div>

        <div class="jobs-apply-button--top-card">
            <button class="jobs-apply-button" aria-label="Solicitud sencilla para Senior Python DevOps Engineer">
                <span>Solicitud sencilla</span>
            </button>
        </div>

        <div class="jobs-poster__name">
            <a href="https://www.linkedin.com/in/recruiter-jane/">Jane Doe</a>
        </div>
    </body>
    </html>
    """
    await page.set_content(html)
    driver_module._page = page
    driver_module._browser = browser

    raw_details = await extract_job_details()
    details = json.loads(raw_details)

    assert details["role"] == "Senior Python DevOps Engineer"
    assert details["company"] == "Example Global Corp"
    assert "Buenos Aires" in details["location"]
    assert details["workplace_type"] == "Remoto"
    assert "CI/CD pipeline" in details["description"]
    assert details["easy_apply"] is True
    assert details["already_applied"] is False
    assert "Jane Doe" in details["recruiter"]

    await browser.close()
    await pw.stop()


@pytest.mark.asyncio
async def test_detect_modal_fields_and_profile_matching():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()

    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="jobs-easy-apply-modal" role="dialog">
            <h2>Datos de contacto y preguntas adicionales</h2>
            <div class="artdeco-completeness-meter-bar" role="progressbar" aria-valuenow="50"></div>

            <div class="fb-dash-form-element" data-test-single-line-text-form-component>
                <label for="f-phone">Número de teléfono móvil*</label>
                <input id="f-phone" type="tel" value="" required />
            </div>

            <div class="fb-dash-form-element" data-test-single-line-text-form-component>
                <label for="f-email">Correo electrónico*</label>
                <input id="f-email" type="email" value="" required />
            </div>

            <div class="fb-dash-form-element" data-test-single-line-text-form-component>
                <label for="f-city">Ciudad de residencia</label>
                <input id="f-city" type="text" value="" />
            </div>

            <div class="fb-dash-form-element" data-test-single-line-text-form-component>
                <label for="f-salary">Salario bruto pretendido (USD)</label>
                <input id="f-salary" type="text" value="" />
            </div>

            <div class="fb-dash-form-element" data-test-dropdown-form-component>
                <label for="f-english">Nivel de inglés</label>
                <select id="f-english">
                    <option value="">Selecciona</option>
                    <option value="basic">Básico</option>
                    <option value="intermediate">Intermedio</option>
                    <option value="advanced">Avanzado / Profesional</option>
                </select>
            </div>

            <fieldset>
                <legend>¿Tienes autorización legal para trabajar en Argentina?*</legend>
                <label><input type="radio" name="auth_legal" value="yes" /> Sí</label>
                <label><input type="radio" name="auth_legal" value="no" /> No</label>
            </fieldset>

            <div>
                <label><input type="checkbox" name="followCompany" checked /> Seguir a la empresa</label>
            </div>

            <button type="button" class="artdeco-button--primary">Continuar</button>
        </div>
    </body>
    </html>
    """
    await page.set_content(html)
    driver_module._page = page
    driver_module._browser = browser

    raw_fields = await detect_form_fields()
    fields_data = json.loads(raw_fields)

    assert fields_data["has_next"] is True
    assert fields_data["has_submit"] is False
    assert fields_data["has_follow_checkbox"] is True
    assert fields_data["progress_percent"] == 50
    assert len(fields_data["fields"]) >= 6

    # Test match_field across Spanish queries
    profile = load_profile()
    assert match_field("Número de teléfono móvil", profile) is not None
    assert match_field("Correo electrónico", profile) is not None
    assert match_field("Ciudad de residencia", profile) is not None
    assert match_field("¿Tienes autorización legal para trabajar?", profile) == "Yes"
    assert match_field("¿Requieres patrocinio de visa?", profile) == "No"

    await browser.close()
    await pw.stop()


def test_spanish_profile_matching():
    p = UserProfile(
        personal={"first_name": "Laureano", "last_name": "Lamonega", "email": "test@example.com", "phone": "2216959945", "city": "Berisso", "country": "Argentina"},
        work_authorization={"authorized": True, "sponsorship_required": False},
        salary={"expected": "950", "currency": "USD"},
        languages={"english": "Professional"},
    )
    assert match_field("Primer nombre", p) == "Laureano"
    assert match_field("Apellido", p) == "Lamonega"
    assert match_field("Nombre completo", p) == "Laureano Lamonega"
    assert match_field("Dirección de correo", p) == "test@example.com"
    assert match_field("Teléfono", p) == "2216959945"
    assert match_field("Ciudad", p) == "Berisso"
    assert match_field("País de residencia", p) == "Argentina"
    assert match_field("¿Estás habilitado para trabajar?", p) == "Yes"
    assert match_field("¿Necesitas sponsor para visa?", p) == "No"
    assert match_field("Salario pretendido", p) == "950"
    assert match_field("Nivel de inglés", p) == "Professional"
