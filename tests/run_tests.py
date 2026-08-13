"""Runner for async test suite."""
import asyncio
import json
import sys
import os

sys.path.insert(0, r"C:\Users\Laureano\Código\Propio\lamonega\hawk")

from playwright.async_api import async_playwright
import hawk.browser.driver as driver_module
from hawk.browser.dom import snapshot, click_element, type_element, select_element
from hawk.linkedin.autofill import auto_fill_current_step

async def run_all_tests():
    print("=== STARTING AUTOMATED MCP & DOM TESTS ===")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()

    html = """
    <!DOCTYPE html>
    <html>
    <head><title>LinkedIn Easy Apply Test</title></head>
    <body>
        <div class="jobs-easy-apply-modal" role="dialog">
            <h2>Additional Questions</h2>
            
            <div class="fb-dash-form-element">
                <label for="li-phone">Número de teléfono móvil</label>
                <input id="li-phone" type="tel" value="" />
            </div>

            <div class="fb-dash-form-element">
                <label for="li-profile">LinkedIn Profile</label>
                <input id="li-profile" type="text" value="" />
            </div>

            <div class="fb-dash-form-element">
                <label for="portfolio-url">Portfolio link</label>
                <textarea id="portfolio-url"></textarea>
            </div>

            <div class="fb-dash-form-element">
                <label for="country-sel">Country*</label>
                <select id="country-sel">
                    <option value="">Selecciona una opción</option>
                    <option value="69947571101">Afghanistan</option>
                    <option value="69947579101">Argentina</option>
                    <option value="69947580101">Brazil</option>
                </select>
            </div>

            <div class="fb-dash-form-element">
                <label for="exp-docker">¿Cuántos años de experiencia tienes con Docker?</label>
                <input id="exp-docker" type="text" value="" />
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
    await page.set_content(html)
    driver_module._page = page
    driver_module._browser = browser
    driver_module._context = page.context

    # --- Test 1: DOM Snapshot ---
    print("\n[TEST 1] Testing snapshot and clean label parsing...")
    snap_raw = await snapshot()
    snap = json.loads(snap_raw)
    assert snap["title"] == "LinkedIn Easy Apply Test", "Snapshot title mismatch"
    elems = snap["elements"]
    print(f"  [OK] Snapshot extracted {len(elems)} elements successfully:")
    for el in elems:
        print(f"    - [{el['index']}] {el['tag']} ({el['type']}) | name='{el['name']}' | val='{el['value']}'")

    # Find labels
    phone_el = next(e for e in elems if "teléfono" in e["name"].lower() or e["tag"] == "input" and e["type"] == "tel")
    li_el = next(e for e in elems if "linkedin" in e["name"].lower())
    port_el = next(e for e in elems if "portfolio" in e["name"].lower())
    country_el = next(e for e in elems if "country" in e["name"].lower())
    btn_rev = next(e for e in elems if "revisar" in e["name"].lower() or "revisar" in e["value"].lower() or el.get("id") == "btn-next")

    print(f"  [OK] Labels detected cleanly:")
    print(f"    - Phone element [index {phone_el['index']}]: label='{phone_el['name']}'")
    print(f"    - LinkedIn element [index {li_el['index']}]: label='{li_el['name']}'")
    print(f"    - Portfolio element [index {port_el['index']}]: label='{port_el['name']}'")
    print(f"    - Country select [index {country_el['index']}]: label='{country_el['name']}'")
    print(f"    - Next button [index {btn_rev['index']}]: label='{btn_rev['name']}'")

    # --- Test 2: Precision Typing ---
    print("\n[TEST 2] Testing precision typing...")
    res_type = await type_element(li_el["index"], "https://www.linkedin.com/in/lflamonega")
    assert "Typed" in res_type
    li_val = await page.locator("#li-profile").input_value()
    assert li_val == "https://www.linkedin.com/in/lflamonega"
    print("  [OK] Input typing verified (value = https://www.linkedin.com/in/lflamonega)")

    res_ta = await type_element(port_el["index"], "https://github.com/lflamonega")
    assert "Typed" in res_ta
    port_val = await page.locator("#portfolio-url").input_value()
    assert port_val == "https://github.com/lflamonega"
    print("  [OK] Textarea typing verified (value = https://github.com/lflamonega)")

    # --- Test 3: Precision Select ---
    print("\n[TEST 3] Testing precision select dropdown...")
    res_sel = await select_element(country_el["index"], "Argentina")
    assert "Selected" in res_sel
    sel_val = await page.locator("#country-sel").input_value()
    assert sel_val == "69947579101"
    print("  [OK] Dropdown selection verified (chosen = Argentina / 69947579101)")

    # --- Test 4: Precision Click ---
    print("\n[TEST 4] Testing precision button click...")
    res_click = await click_element(btn_rev["index"])
    assert "Clicked" in res_click
    print("  [OK] Button click verified (Revisar clicked)")

    # --- Test 5: Full Autofill Engine ---
    print("\n[TEST 5] Testing autonomous full autofill engine...")
    # Reset values to test full autofill
    await page.locator("#li-phone").fill("")
    await page.locator("#li-profile").fill("")
    await page.locator("#portfolio-url").fill("")
    await page.locator("#country-sel").select_option(value="")
    await page.locator("#exp-docker").fill("")

    autofill_res = await auto_fill_current_step()
    print("  [OK] Autofill executed. Filled fields summary:")
    for f in autofill_res.get("filled", []):
        print(f"    - {f['field']}: '{f['value']}' (label: {f.get('label', '')})")

    # Assertions
    assert await page.locator("#li-phone").input_value() != "", "Phone must be filled"
    assert await page.locator("#li-profile").input_value() == "https://www.linkedin.com/in/lflamonega", "LinkedIn must be filled"
    assert await page.locator("#portfolio-url").input_value() == "https://github.com/lflamonega", "Portfolio must be filled"
    assert await page.locator("#country-sel").input_value() == "69947579101", "Country must be Argentina"
    assert await page.locator("#exp-docker").input_value() == "2", "Docker experience must be 2 years"
    assert await page.locator('input[type="radio"][value="yes"]').is_checked(), "Authorization radio must be Yes"
    assert not await page.locator('input[type="checkbox"]').is_checked(), "Follow company must be unchecked"

    print("\n==========================================")
    print("ALL 5 INTEGRATION & DOM TESTS PASSED 100%!")
    print("==========================================")

    await browser.close()
    await pw.stop()

if __name__ == "__main__":
    asyncio.run(run_all_tests())
