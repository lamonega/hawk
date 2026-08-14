"""Unit and integration tests for DOM inspection and element interactions."""
import json
import pytest
from playwright.async_api import async_playwright

from hawk.browser.dom import snapshot, click_element, type_element, select_element
import hawk.browser.driver as driver_module


@pytest.fixture
async def sample_page():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    html_content = """
    <!DOCTYPE html>
    <html>
    <head><title>LinkedIn Easy Apply Test</title></head>
    <body>
        <div class="jobs-easy-apply-modal" role="dialog">
            <h2>Additional Questions</h2>
            
            <div class="fb-dash-form-element">
                <label for="li-profile">LinkedIn Profile</label>
                <input id="li-profile" type="text" value="" />
            </div>

            <div class="fb-dash-form-element">
                <label for="portfolio-url">Portfolio link</label>
                <textarea id="portfolio-url"></textarea>
            </div>

            <div class="fb-dash-form-element">
                <label for="country-sel">Country</label>
                <select id="country-sel">
                    <option value="">Selecciona una opción</option>
                    <option value="69947571101">Afghanistan</option>
                    <option value="69947579101">Argentina</option>
                    <option value="69947580101">Brazil</option>
                </select>
            </div>

            <fieldset>
                <legend>Are you legally authorized to work in Argentina?</legend>
                <label><input type="radio" name="auth" value="yes"> Yes</label>
                <label><input type="radio" name="auth" value="no"> No</label>
            </fieldset>

            <div>
                <label><input type="checkbox" name="followCompany" checked> Follow company</label>
            </div>

            <button type="button" id="btn-prev">Volver</button>
            <button type="button" id="btn-next" class="artdeco-button--primary">Revisar</button>
        </div>
    </body>
    </html>
    """
    await page.set_content(html_content)
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
async def test_dom_snapshot_and_interactions(sample_page):
    # 1. Snapshot
    raw_res = await snapshot()
    res = json.loads(raw_res)
    assert res["title"] == "LinkedIn Easy Apply Test"
    elements = res["elements"]
    assert len(elements) > 0

    # Verify label extraction
    li_input = next(e for e in elements if "LinkedIn Profile" in e["name"])
    assert li_input["tag"] == "input"

    port_ta = next(e for e in elements if "Portfolio link" in e["name"])
    assert port_ta["tag"] == "textarea"

    country_sel = next(e for e in elements if "Country" in e["name"])
    assert country_sel["tag"] == "select"

    # 2. Type into input
    res_type = await type_element(li_input["index"], "https://www.linkedin.com/in/example-user")
    assert "Typed" in res_type
    val = await sample_page.locator("#li-profile").input_value()
    assert val == "https://www.linkedin.com/in/example-user"

    # 3. Type into textarea
    res_ta = await type_element(port_ta["index"], "https://github.com/example-user")
    assert "Typed" in res_ta
    ta_val = await sample_page.locator("#portfolio-url").input_value()
    assert ta_val == "https://github.com/example-user"

    # 4. Select from dropdown by text
    res_sel = await select_element(country_sel["index"], "Argentina")
    assert "Selected" in res_sel
    sel_val = await sample_page.locator("#country-sel").input_value()
    assert sel_val == "69947579101"

    # 5. Click button
    btn_next = next(e for e in elements if "Revisar" in e["name"])
    res_click = await click_element(btn_next["index"])
    assert "Clicked" in res_click
