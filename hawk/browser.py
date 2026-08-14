"""Unified Playwright browser management, stealth patches, DOM tree inspection, and PDF rendering."""

from __future__ import annotations

import asyncio
import base64
import json
import random
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import Stealth

from hawk.config import PROJECT_ROOT, get_settings

_STATE_FILE = "storage_state.json"
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_STEALTH_JS = """
(() => {
    // Canvas fingerprint noise
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(...args) {
        const d = origGetImageData.apply(this, args);
        for (let i = 0; i < d.data.length; i += 4) {
            if (Math.random() < 0.02) {
                d.data[i] = Math.max(0, Math.min(255, d.data[i] + (Math.random() > 0.5 ? 1 : -1)));
            }
        }
        return d;
    };

    // WebGL spoofing
    const origGetParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return "Google Inc. (Intel)";
        if (p === 37446) return "ANGLE (Intel, Intel(R) UHD Graphics 630, OpenGL 4.5)";
        return origGetParam.apply(this, arguments);
    };

    // Navigator consistency
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
})();
"""


class BrowserManager:
    """Manages browser lifecycle, DOM snapshots, interactions, and PDF compilation."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._last_elements: list[dict[str, Any]] = []

    def get_page(self) -> Page | None:
        return self._page if (self._page and not self._page.is_closed()) else None

    async def launch(self, headless: bool | None = None, profile_dir: str | None = None) -> Page:
        """Start Playwright Chromium instance with stealth and storage state."""
        if self._page and not self._page.is_closed():
            return self._page

        await self.close()
        settings = get_settings()
        is_headless = headless if headless is not None else settings.browser.headless
        prof_dir = PROJECT_ROOT / (profile_dir or settings.browser.profile_dir)
        prof_dir.mkdir(parents=True, exist_ok=True)
        state_path = prof_dir / _STATE_FILE

        ua = random.choice(_USER_AGENTS)
        self._pw = await Stealth().use_async(async_playwright()).start()
        self._browser = await self._pw.chromium.launch(
            headless=is_headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-infobars",
                "--no-default-browser-check",
                "--window-size=1920,1080",
            ],
        )

        ctx_kwargs: dict[str, Any] = {
            "user_agent": ua,
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }
        if state_path.exists():
            ctx_kwargs["storage_state"] = str(state_path)
            logger.info("Loaded session from {}", state_path)

        self._context = await self._browser.new_context(**ctx_kwargs)
        self._page = await self._context.new_page()
        await self._page.add_init_script(_STEALTH_JS)

        logger.info("Browser launched (headless={}, ua={})", is_headless, ua[:40])
        return self._page

    async def close(self) -> None:
        """Save storage state and terminate browser."""
        if self._context:
            try:
                prof_dir = PROJECT_ROOT / get_settings().browser.profile_dir
                state_path = prof_dir / _STATE_FILE
                await self._context.storage_state(path=str(state_path))
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None

    async def check_session(self) -> str:
        """Check if logged in to LinkedIn."""
        page = self.get_page()
        if not page:
            return "no_browser"
        try:
            cookies = await page.context.cookies(["https://www.linkedin.com"])
            has_li_at = any(c.get("name") == "li_at" and bool(c.get("value")) for c in cookies)
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
            await self.dismiss_overlays()
            url = page.url
            if "login" in url or "authwall" in url or "checkpoint" in url:
                return "not_logged_in"
            if has_li_at or "feed" in url or "in" in url:
                return "logged_in"
            return "not_logged_in"
        except Exception as e:
            return f"error: {e}"

    async def wait_for_login(self, timeout: int = 120) -> str:
        """Actively wait for user to complete manual login."""
        page = self.get_page()
        if not page:
            return "error: browser not started"
        start = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start) < timeout:
            cookies = await page.context.cookies(["https://www.linkedin.com"])
            if any(c.get("name") == "li_at" and bool(c.get("value")) for c in cookies):
                # Save session
                prof_dir = PROJECT_ROOT / get_settings().browser.profile_dir
                await self._context.storage_state(path=str(prof_dir / _STATE_FILE))
                await self.dismiss_overlays()
                return "logged_in"
            await asyncio.sleep(2.0)
        return "timeout"

    async def navigate(self, url: str) -> str:
        """Navigate to URL and auto-dismiss guest overlays."""
        page = self.get_page()
        if not page:
            return "error: browser not started"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1.0)
            await self.dismiss_overlays()
            return f"navigated: {url}"
        except Exception as e:
            return f"error: {e}"

    async def dismiss_overlays(self) -> bool:
        """Dismiss guest modal popups."""
        page = self.get_page()
        if not page:
            return False
        selectors = [
            'button[aria-label="Descartar"]', 'button[aria-label="Dismiss"]',
            'button[aria-label="Cerrar"]', 'button[aria-label="Close"]',
            '.contextual-sign-in-modal__modal-dismiss-btn', '.modal__dismiss-btn',
            'button.artdeco-modal__dismiss', '[data-test-modal-close-btn]',
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=300):
                    # Do not dismiss actual easy apply form modal
                    is_apply = await loc.evaluate("el => !!el.closest('.jobs-easy-apply-modal, [data-test-modal-id=\"easy-apply-modal\"]')")
                    if not is_apply:
                        await loc.click(timeout=1000)
                        return True
            except Exception:
                pass
        return False

    async def snapshot(self, include_hidden: bool = False) -> dict[str, Any]:
        """Generate accessibility tree with unique data-hawk-id for deterministic actions."""
        page = self.get_page()
        if not page:
            return {"error": "browser not started"}

        try:
            raw = await page.evaluate(r"""
            (includeHidden) => {
                const selectors = ['button', 'input:not([type=hidden])', 'select', 'textarea', 'a[href]', '[role=button]', '[role=combobox]', '[role=checkbox]', '[role=radio]', '[role=tab]'];
                const seen = new Set();
                const results = [];
                let idx = 0;

                const dlg = document.querySelector('[role="dialog"], .jobs-easy-apply-modal, div[data-test-modal-id="easy-apply-modal"], .artdeco-modal');
                const root = dlg || document.body;

                for (const sel of selectors) {
                    for (const el of root.querySelectorAll(sel)) {
                        if (seen.has(el)) continue;
                        seen.add(el);

                        const currentIdx = idx++;
                        el.setAttribute('data-hawk-id', String(currentIdx));
                        const tag = el.tagName.toLowerCase();
                        const role = el.getAttribute('role') || (tag === 'a' ? 'link' : tag === 'button' ? 'button' : tag === 'input' ? el.type || 'textbox' : tag);

                        let label = el.getAttribute('aria-label') || el.innerText?.trim() || el.getAttribute('placeholder') || '';
                        if (!label && el.id) {
                            const lbl = document.querySelector(`label[for="${el.id}"]`);
                            if (lbl) label = lbl.innerText.trim();
                        }
                        if (!label) {
                            const group = el.closest('.fb-dash-form-element, .jobs-easy-apply-form-section__group, fieldset, div.artdeco-text-input--container');
                            if (group) {
                                const groupLbl = group.querySelector('label, legend, .fb-dash-form-element__label, .artdeco-text-input--label');
                                if (groupLbl) label = groupLbl.innerText.trim();
                            }
                        }
                        label = label.split('\n')[0].replace(/\s+/g, ' ').trim().slice(0, 100);

                        let val = el.value || el.getAttribute('value') || '';
                        if (tag === 'select' && el.selectedIndex >= 0 && el.options[el.selectedIndex]) {
                            val = el.options[el.selectedIndex].text.trim();
                        }

                        const isInvalid = el.getAttribute('aria-invalid') === 'true' || el.classList.contains('artdeco-text-input--error') || el.classList.contains('fb-form-element--error');
                        results.push({
                            index: currentIdx,
                            tag: tag,
                            role: role,
                            type: el.type || '',
                            name: label,
                            value: val,
                            required: Boolean(el.required || el.getAttribute('aria-required') === 'true' || label.includes('*')),
                            invalid: isInvalid,
                        });
                    }
                }

                const errors = [];
                document.querySelectorAll('.artdeco-inline-feedback--error, .fb-dash-form-element__error-text, [data-test-form-element-error], [role="alert"]').forEach(e => {
                    const txt = e.innerText?.trim();
                    if (txt && !errors.includes(txt)) errors.push(txt);
                });

                return { elements: results, form_errors: errors };
            }
            """, include_hidden)

            self._last_elements = raw.get("elements", [])
            return {
                "url": page.url,
                "title": await page.title(),
                "form_errors": raw.get("form_errors", []),
                "elements": self._last_elements,
            }
        except Exception as e:
            return {"error": str(e)}

    async def interact(self, element_index: int, action: str, value: str = "") -> str:
        """Perform action (click, type, select, upload) on element by its snapshot index."""
        page = self.get_page()
        if not page:
            return "error: browser not started"

        act = action.lower().strip()
        locator = page.locator(f'[data-hawk-id="{element_index}"]').first

        try:
            if act == "click":
                await locator.scroll_into_view_if_needed()
                await locator.click(timeout=3000)
                return f"clicked index {element_index}"

            elif act in ("type", "fill"):
                await locator.scroll_into_view_if_needed()
                await locator.fill(value)
                return f"typed '{value}' into index {element_index}"

            elif act == "select":
                # Try selecting by value, text, or substring
                selected = await page.evaluate(r"""
                ([idx, targetVal]) => {
                    const el = document.querySelector(`[data-hawk-id="${idx}"]`);
                    if (!el) return null;
                    if (el.tagName === 'SELECT') {
                        const target = targetVal.toLowerCase().trim();
                        for (let i = 0; i < el.options.length; i++) {
                            const opt = el.options[i];
                            const optVal = (opt.value || '').toLowerCase();
                            const optTxt = (opt.text || '').toLowerCase();
                            if (optVal === target || optTxt === target || optTxt.includes(target)) {
                                el.selectedIndex = i;
                                opt.selected = true;
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                                return opt.text.trim();
                            }
                        }
                    }
                    return null;
                }
                """, [element_index, value])
                if selected:
                    return f"selected '{selected}' in index {element_index}"
                await locator.select_option(value=value)
                return f"selected '{value}' in index {element_index}"

            elif act == "upload":
                if not Path(value).exists():
                    return f"error: file not found {value}"
                file_input = page.locator('input[type="file"]').first
                if await file_input.count() > 0:
                    await file_input.set_input_files(value)
                    return f"uploaded file {value}"
                # Try file chooser trigger
                async with page.expect_file_chooser(timeout=3000) as fc_info:
                    await locator.click()
                chooser = await fc_info.value
                await chooser.set_files(value)
                return f"uploaded file via chooser {value}"

            return f"error: unsupported action '{action}'"
        except Exception as e:
            return f"error interacting with element {element_index}: {e}"

    async def screenshot(self, output_path: str | None = None) -> str:
        """Capture screenshot to path or return base64."""
        page = self.get_page()
        if not page:
            return "error: browser not started"
        try:
            if output_path:
                out = Path(output_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(out), full_page=False)
                return f"saved: {out}"
            else:
                img_bytes = await page.screenshot(type="png")
                return base64.b64encode(img_bytes).decode("utf-8")
        except Exception as e:
            return f"error: {e}"

    async def render_pdf(self, html_content: str, output_path: str) -> str:
        """Render raw HTML to PDF using Playwright tab."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        encoded = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
        data_url = f"data:text/html;base64,{encoded}"

        page = self.get_page()
        if page and not page.is_closed():
            temp_page = await page.context.new_page()
            try:
                await temp_page.goto(data_url, wait_until="domcontentloaded", timeout=15000)
                await temp_page.pdf(path=str(out), format="A4", margin={"top": "12mm", "bottom": "12mm", "left": "15mm", "right": "15mm"}, print_background=True)
                return str(out)
            finally:
                await temp_page.close()

        # Headless fallback if browser not launched yet
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            temp_page = await browser.new_page()
            await temp_page.goto(data_url, wait_until="networkidle", timeout=15000)
            await temp_page.pdf(path=str(out), format="A4", margin={"top": "12mm", "bottom": "12mm", "left": "15mm", "right": "15mm"}, print_background=True)
            await browser.close()
        return str(out)


# Global singleton browser manager
browser = BrowserManager()
