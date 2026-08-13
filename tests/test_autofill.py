"""Unit tests for the auto-fill engine."""
import pytest
from playwright.async_api import async_playwright

from hawk.linkedin.autofill import auto_fill_current_step
import hawk.browser.driver as driver_module


@pytest.fixture
async def sample_modal_page():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="jobs-easy-apply-modal">
            <div class="fb-dash-form-element">
                <label>Número de teléfono móvil</label>
                <input type="tel" value="" />
            </div>

            <div class="fb-dash-form-element">
                <label>LinkedIn Profile</label>
                <input type="text" value="" />
            </div>

            <div class="fb-dash-form-element">
                <label>Portfolio link</label>
                <textarea></textarea>
            </div>

            <div class="fb-dash-form-element">
                <label>País de residencia</label>
                <select>
                    <option value="">Selecciona una opción</option>
                    <option value="us">United States</option>
                    <option value="ar">Argentina</option>
                </select>
            </div>

            <div class="fb-dash-form-element">
                <label>¿Cuántos años de experiencia tienes con Docker?</label>
                <input type="text" value="" />
            </div>

            <fieldset>
                <legend>¿Tienes autorización legal para trabajar en Argentina?</legend>
                <label><input type="radio" name="auth" value="yes"> Sí</label>
                <label><input type="radio" name="auth" value="no"> No</label>
            </fieldset>

            <div>
                <label><input type="checkbox" name="followCompany" checked> Seguir a la empresa</label>
            </div>

            <button type="button" class="artdeco-button--primary">Revisar</button>
        </div>
    </body>
    </html>
    """
    await page.set_content(html)
    driver_module._page = page
    driver_module._browser = browser
    driver_module._context = page.context

    yield page

    await browser.close()
    await playwright.stop()
    driver_module._page = None
    driver_module._browser = None
    driver_module._context = None


@pytest.mark.asyncio
async def test_autofill_engine_completes_all_fields(sample_modal_page):
    res = await auto_fill_current_step()
    filled = res.get("filled", [])
    assert len(filled) > 0

    # 1. Phone was filled
    phone_val = await sample_modal_page.locator('input[type="tel"]').input_value()
    assert phone_val == "221 695 9945" or "221" in phone_val

    # 2. LinkedIn was filled
    li_val = await sample_modal_page.locator('input[type="text"]').nth(0).input_value()
    assert "linkedin.com" in li_val

    # 3. Portfolio was filled
    port_val = await sample_modal_page.locator('textarea').input_value()
    assert "github.com" in port_val

    # 4. Country dropdown selected Argentina
    sel_val = await sample_modal_page.locator('select').input_value()
    assert sel_val == "ar"

    # 5. Experience years filled
    exp_val = await sample_modal_page.locator('input[type="text"]').nth(1).input_value()
    assert exp_val == "2"

    # 6. Radio button selected Sí
    radio_checked = await sample_modal_page.locator('input[type="radio"][value="yes"]').is_checked()
    assert radio_checked is True

    # 7. Follow company checkbox unchecked
    cb_checked = await sample_modal_page.locator('input[type="checkbox"]').is_checked()
    assert cb_checked is False

    assert res["has_next"] is True
