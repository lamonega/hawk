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
    """Take a DOM snapshot of the current page.

    Extracts interactive elements using JavaScript (works without page.accessibility).

    Returns a JSON string with:
    - url: current page URL
    - title: page title
    - elements: indexed list of interactive elements with their properties
    """
    page = get_page()
    if page is None:
        return json.dumps({"error": "Browser not started"})

    try:
        # Extract interactive elements via JS
        raw_elements = await page.evaluate(
            """
            () => {
                const selectors = [
                    'a[href]',
                    'button',
                    'input:not([type=hidden])',
                    'select',
                    'textarea',
                    '[role=button]',
                    '[role=link]',
                    '[role=tab]',
                    '[role=menuitem]',
                    '[role=option]',
                    '[role=combobox]',
                    '[role=textbox]',
                    '[role=checkbox]',
                    '[role=radio]',
                    '[tabindex]',
                    '[contenteditable=true]',
                ];
                const seen = new Set();
                const results = [];

                for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (seen.has(el)) continue;
                        seen.add(el);

                        const tag = el.tagName.toLowerCase();
                        const role = el.getAttribute('role') ||
                                      (tag === 'a' ? 'link' :
                                       tag === 'button' ? 'button' :
                                       tag === 'input' ? el.type || 'textbox' :
                                       tag === 'select' ? 'combobox' :
                                       tag === 'textarea' ? 'textbox' : tag);

                        const labelEl = el.labels && el.labels[0] ? el.labels[0] : el.closest('div, .fb-dash-form-element, section')?.querySelector('label');
                        const name = el.getAttribute('aria-label') ||
                                      el.getAttribute('title') ||
                                      (labelEl ? labelEl.innerText?.trim() : '') ||
                                      el.innerText?.trim().substring(0, 100) ||
                                      el.getAttribute('placeholder') ||
                                      el.getAttribute('name') ||
                                      '';

                        const id = el.id || '';
                        const value = el.value || el.getAttribute('value') || '';
                        const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                        const readonly = el.readOnly || el.getAttribute('aria-readonly') === 'true';
                        const href = el.getAttribute('href') || '';

                        results.push({
                            tag: tag,
                            id: id,
                            role: role,
                            name: name,
                            value: value,
                            disabled: disabled,
                            readonly: readonly,
                            href: href,
                            type: el.type || '',
                        });
                    }
                }
                return results;
            }
            """
        )

        elements = []
        for i, el in enumerate(raw_elements):
            elements.append({
                "index": i,
                "tag": el.get("tag", ""),
                "id": el.get("id", ""),
                "role": el.get("role", ""),
                "name": el.get("name", ""),
                "value": el.get("value", ""),
                "disabled": el.get("disabled", False),
                "readonly": el.get("readonly", False),
                "href": el.get("href", ""),
                "type": el.get("type", ""),
            })

        result = {
            "url": page.url,
            "title": await page.title(),
            "elements": elements,
        }

        # Store for later use in persistent driver state
        driver_state._last_snapshot = result
        driver_state._last_elements = elements

        logger.debug("Snapshot: {} elements on {}", len(elements), page.url)
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


async def _find_locator_for_element(page: Page, element: dict) -> Any | None:
    """Find a Playwright locator for an element from snapshot data."""
    name = element.get("name", "")
    tag = element.get("tag", "")
    el_id = element.get("id", "")
    href = element.get("href", "")
    role = element.get("role", "")
    el_type = element.get("type", "")

    # By ID
    if el_id:
        try:
            loc = page.locator(f"#{el_id}").first
            if await loc.count() > 0:
                return loc
        except Exception:
            pass

    # For links with href, navigate directly
    if tag == "a" and href:
        try:
            return page.locator(f'a[href="{href}"]').first
        except Exception:
            pass

    # For tel inputs
    if tag == "input" and el_type == "tel":
        try:
            loc = page.locator('input[type="tel"]').first
            if await loc.count() > 0:
                return loc
        except Exception:
            pass

    # For file inputs
    if tag == "input" and el_type == "file":
        try:
            return page.locator("input[type=file]").first
        except Exception:
            pass

    # Try label / name
    if name:
        try:
            locator = page.get_by_label(name, exact=False)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        try:
            locator = page.get_by_role(role, name=name, exact=False)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        try:
            locator = page.get_by_text(name, exact=False)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

    # Fallback by tag and type
    if tag == "input" and el_type:
        try:
            loc = page.locator(f'input[type="{el_type}"]').first
            if await loc.count() > 0:
                return loc
        except Exception:
            pass

    return None


async def click_element(element_index: int) -> str:
    """Click an element by its index from the last snapshot."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    element = get_element_by_index(element_index)
    if element is None:
        return f"error: Element index {element_index} not found in last snapshot"

    locator = await _find_locator_for_element(page, element)
    if locator is None:
        return f"error: Could not find locator for element '{element.get('name', '')}'"

    try:
        await locator.click(timeout=5000)
        return f"Clicked: {element.get('role', '')} '{element.get('name', '')}'"
    except Exception as e:
        return f"error clicking: {e}"


async def type_element(element_index: int, text: str, clear: bool = False) -> str:
    """Type text into an element by its index."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    element = get_element_by_index(element_index)
    if element is None:
        return f"error: Element index {element_index} not found in last snapshot"

    locator = await _find_locator_for_element(page, element)
    if locator is None:
        return f"error: Could not find locator for element '{element.get('name', '')}'"

    try:
        if clear:
            await locator.fill("")
        await locator.type(text, delay=50)  # Human-like typing speed
        return f"Typed '{text[:50]}...' into: {element.get('role', '')} '{element.get('name', '')}'"
    except Exception as e:
        return f"error typing: {e}"


async def select_element(element_index: int, value: str) -> str:
    """Select an option from a dropdown/select element."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    element = get_element_by_index(element_index)
    if element is None:
        return f"error: Element index {element_index} not found in last snapshot"

    locator = await _find_locator_for_element(page, element)
    if locator is None:
        return f"error: Could not find locator for element '{element.get('name', '')}'"

    try:
        await locator.select_option(value=value, timeout=5000)
        return f"Selected '{value}' in: {element.get('role', '')} '{element.get('name', '')}'"
    except Exception as e:
        return f"error selecting: {e}"


async def upload_file(element_index: int, file_path: str) -> str:
    """Upload a file to a file input element."""
    page = get_page()
    if page is None:
        return "error: Browser not started"

    element = get_element_by_index(element_index)
    if element is None:
        return f"error: Element index {element_index} not found in last snapshot"

    # For file inputs, we need to find the input[type=file] directly
    try:
        locator = page.locator("input[type=file]").first
        await locator.set_input_files(file_path, timeout=5000)
        return f"Uploaded '{file_path}' to file input"
    except Exception as e:
        return f"error uploading: {e}"


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
