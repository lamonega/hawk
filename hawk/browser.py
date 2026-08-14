"""Unified Playwright browser management, stealth patches, DOM tree inspection, and PDF rendering."""

from __future__ import annotations

import asyncio
import base64
import random
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import Stealth

from hawk.config import PROJECT_ROOT, get_settings

# --- Session & LinkedIn URLs ---
_STATE_FILE: str = "storage_state.json"
LINKEDIN_BASE_URL: str = "https://www.linkedin.com"
LINKEDIN_FEED_URL: str = "https://www.linkedin.com/feed/"
LI_AT_COOKIE: str = "li_at"
AUTH_URL_KEYWORDS: tuple[str, ...] = ("login", "authwall", "checkpoint")
SESSION_INDICATORS: tuple[str, ...] = ("feed", "/in/")

# --- Browser Environment & Fingerprint Constants ---
_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

DEFAULT_VIEWPORT: dict[str, int] = {"width": 1920, "height": 1080}
DEFAULT_LOCALE: str = "en-US"
DEFAULT_TIMEZONE_ID: str = "America/New_York"

CHROMIUM_LAUNCH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-infobars",
    "--no-default-browser-check",
    "--window-size=1920,1080",
]

# --- Timeouts & Delays ---
DEFAULT_NAV_TIMEOUT_MS: int = 30_000
DEFAULT_SESSION_TIMEOUT_MS: int = 20_000
DEFAULT_ACTION_TIMEOUT_MS: int = 3_000
DEFAULT_PDF_TIMEOUT_MS: int = 15_000
DEFAULT_LOGIN_TIMEOUT_SEC: int = 120
QUICK_LOCATOR_TIMEOUT_MS: int = 300
LOGIN_POLL_INTERVAL_SEC: float = 2.0
NAV_SETTLE_DELAY_SEC: float = 1.0

# --- PDF Rendering Constants ---
PDF_PAGE_FORMAT: str = "A4"
PDF_MARGINS: dict[str, str] = {
    "top": "12mm",
    "bottom": "12mm",
    "left": "15mm",
    "right": "15mm",
}

# --- Selectors ---
OVERLAY_DISMISS_SELECTORS: list[str] = [
    'button[aria-label="Descartar"]',
    'button[aria-label="Dismiss"]',
    'button[aria-label="Cerrar"]',
    'button[aria-label="Close"]',
    ".contextual-sign-in-modal__modal-dismiss-btn",
    ".modal__dismiss-btn",
    "button.artdeco-modal__dismiss",
    "[data-test-modal-close-btn]",
]

EASY_APPLY_MODAL_SELECTOR: str = (
    'dialog[open], dialog[data-testid="dialog"], [data-testid="dialog"], '
    '.jobs-easy-apply-modal, [data-test-modal-id="easy-apply-modal"], [role="dialog"], .artdeco-modal'
)

# --- JavaScript Injections ---
_STEALTH_JS: str = """
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

_DOM_SNAPSHOT_JS: str = r"""
(includeHidden) => {
    const INTERACTIVE_SELECTORS = [
        'button',
        'input:not([type="hidden"])',
        'select',
        'textarea',
        'a[href]',
        '[role="button"]',
        '[role="combobox"]',
        '[role="checkbox"]',
        '[role="radio"]',
        '[role="tab"]'
    ];

    const MODAL_CONTAINER_SELECTOR = 'dialog[open], dialog[data-testid="dialog"], [data-testid="dialog"], [role="dialog"], .jobs-easy-apply-modal, div[data-test-modal-id="easy-apply-modal"], .artdeco-modal';
    const ERROR_SELECTORS = [
        '.artdeco-inline-feedback--error',
        '.fb-dash-form-element__error-text',
        '[data-test-form-element-error]',
        '[role="alert"]'
    ];

    const isElementVisible = (el) => {
        if (!el) return false;
        if (el.tagName.toLowerCase() === 'input' && el.type === 'file') return true;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 || rect.height > 0 || el.getClientRects().length > 0;
    };

    const getElementLabel = (el) => {
        let label = el.getAttribute('aria-label') || el.innerText?.trim() || el.getAttribute('placeholder') || '';
        if (!label) {
            const labelledBy = el.getAttribute('aria-labelledby');
            if (labelledBy) {
                try {
                    const refEl = document.getElementById(labelledBy);
                    if (refEl) label = refEl.innerText?.trim() || '';
                } catch (_) {}
            }
        }
        if (!label && el.id) {
            try {
                const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (lbl) label = lbl.innerText.trim();
            } catch (_) {}
        }
        if (!label) {
            const group = el.closest('.fb-dash-form-element, .jobs-easy-apply-form-section__group, fieldset, div.artdeco-text-input--container');
            if (group) {
                const groupLbl = group.querySelector('label, legend, .fb-dash-form-element__label, .artdeco-text-input--label');
                if (groupLbl) label = groupLbl.innerText.trim();
            }
        }
        return label.split('\n')[0].replace(/\s+/g, ' ').trim().slice(0, 100);
    };

    const getElementValue = (el, tag) => {
        if (tag === 'select' && el.selectedIndex >= 0 && el.options[el.selectedIndex]) {
            return el.options[el.selectedIndex].text.trim();
        }
        if (el.type === 'checkbox' || el.type === 'radio') {
            if (el.checked !== undefined) {
                return el.checked ? 'true' : 'false';
            }
        }
        return el.value || el.getAttribute('value') || '';
    };

    const root = document.querySelector(MODAL_CONTAINER_SELECTOR) || document.body;
    const seen = new Set();
    const results = [];
    let idx = 0;

    for (const sel of INTERACTIVE_SELECTORS) {
        for (const el of root.querySelectorAll(sel)) {
            if (seen.has(el)) continue;
            seen.add(el);

            if (!includeHidden && !isElementVisible(el)) continue;

            const currentIdx = idx++;
            el.setAttribute('data-hawk-id', String(currentIdx));

            const tag = el.tagName.toLowerCase();
            const role = el.getAttribute('role') || (
                tag === 'a' ? 'link' :
                tag === 'button' ? 'button' :
                tag === 'input' ? (el.type || 'textbox') :
                tag
            );

            const label = getElementLabel(el);
            const val = getElementValue(el, tag);
            const isInvalid = (
                el.getAttribute('aria-invalid') === 'true' ||
                el.classList.contains('artdeco-text-input--error') ||
                el.classList.contains('fb-form-element--error')
            );
            const isRequired = Boolean(
                el.required ||
                el.getAttribute('aria-required') === 'true' ||
                label.includes('*')
            );

            results.push({
                index: currentIdx,
                tag: tag,
                role: role,
                type: el.type || '',
                name: label,
                value: val,
                required: isRequired,
                invalid: isInvalid,
            });
        }
    }

    const errors = [];
    for (const errSel of ERROR_SELECTORS) {
        document.querySelectorAll(errSel).forEach(e => {
            const txt = e.innerText?.trim();
            if (txt && !errors.includes(txt)) {
                errors.push(txt);
            }
        });
    }

    return { elements: results, form_errors: errors };
}
"""

_SELECT_OPTION_JS: str = r"""
([idx, targetVal]) => {
    const el = document.querySelector(`[data-hawk-id="${idx}"]`);
    if (!el || el.tagName !== 'SELECT') return null;

    const target = (targetVal || '').toLowerCase().trim();
    for (let i = 0; i < el.options.length; i++) {
        const opt = el.options[i];
        const optVal = (opt.value || '').toLowerCase().trim();
        const optTxt = (opt.text || '').toLowerCase().trim();
        if (optVal === target || optTxt === target || optTxt.includes(target)) {
            el.selectedIndex = i;
            opt.selected = true;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return opt.text.trim();
        }
    }
    return null;
}
"""


class BrowserManager:
    """Manages browser lifecycle, stealth configuration, DOM snapshots, and PDF rendering."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._last_elements: list[dict[str, Any]] = []

    def _get_storage_state_path(self, profile_dir: str | Path | None = None) -> Path:
        """Resolve absolute path to session storage state file."""
        if profile_dir:
            base = Path(profile_dir)
            base_dir = base if base.is_absolute() else PROJECT_ROOT / base
        else:
            p_dir = Path(get_settings().browser.profile_dir)
            base_dir = p_dir if p_dir.is_absolute() else PROJECT_ROOT / p_dir
        return base_dir / _STATE_FILE

    @staticmethod
    async def _render_page_to_pdf(page: Page, data_url: str, output_path: Path) -> None:
        """Render data URL to an A4 PDF file using a given Playwright page."""
        await page.goto(
            data_url,
            wait_until="domcontentloaded",
            timeout=DEFAULT_PDF_TIMEOUT_MS,
        )
        await page.pdf(
            path=str(output_path),
            format=PDF_PAGE_FORMAT,
            margin=PDF_MARGINS,
            print_background=True,
        )

    def get_page(self) -> Page | None:
        """Return active page if open and available."""
        return self._page if (self._page and not self._page.is_closed()) else None

    async def launch(
        self,
        headless: bool | None = None,
        profile_dir: str | Path | None = None,
    ) -> Page:
        """Start Playwright Chromium instance with stealth patches and persistent storage state."""
        if self._page and not self._page.is_closed():
            return self._page

        await self.close()
        settings = get_settings()
        is_headless = headless if headless is not None else settings.browser.headless

        state_path = self._get_storage_state_path(profile_dir)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        ua = random.choice(_USER_AGENTS)
        try:
            self._pw = await Stealth().use_async(async_playwright()).start()
            self._browser = await self._pw.chromium.launch(
                headless=is_headless,
                args=CHROMIUM_LAUNCH_ARGS,
            )

            ctx_kwargs: dict[str, Any] = {
                "user_agent": ua,
                "viewport": DEFAULT_VIEWPORT,
                "locale": DEFAULT_LOCALE,
                "timezone_id": DEFAULT_TIMEZONE_ID,
            }
            if state_path.exists():
                ctx_kwargs["storage_state"] = str(state_path)
                logger.info("Loaded session from {}", state_path)

            self._context = await self._browser.new_context(**ctx_kwargs)
            self._page = await self._context.new_page()
            await self._page.add_init_script(_STEALTH_JS)

            logger.info("Browser launched (headless={}, ua={})", is_headless, ua[:40])
            return self._page
        except Exception as e:
            logger.error("Failed to launch browser: {}", e)
            await self.close()
            raise

    async def close(self) -> None:
        """Save storage state and gracefully terminate browser resources."""
        try:
            if self._context:
                try:
                    state_path = self._get_storage_state_path()
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    await self._context.storage_state(path=str(state_path))
                except Exception as e:
                    logger.debug("Failed saving storage state during close: {}", e)
                try:
                    await self._context.close()
                except Exception as e:
                    logger.debug("Error closing browser context: {}", e)

            if self._browser:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.debug("Error closing browser instance: {}", e)

            if self._pw:
                try:
                    await self._pw.stop()
                except Exception as e:
                    logger.debug("Error stopping playwright engine: {}", e)
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None

    async def check_session(self) -> str:
        """Check if logged in to LinkedIn by examining cookies and navigation state."""
        page = self.get_page()
        if not page:
            return "no_browser"
        try:
            cookies = await page.context.cookies([LINKEDIN_BASE_URL])
            has_li_at = any(
                c.get("name") == LI_AT_COOKIE and bool(c.get("value"))
                for c in cookies
            )

            await page.goto(
                LINKEDIN_FEED_URL,
                wait_until="domcontentloaded",
                timeout=DEFAULT_SESSION_TIMEOUT_MS,
            )
            await self.dismiss_overlays()
            url = page.url

            if any(keyword in url for keyword in AUTH_URL_KEYWORDS):
                return "not_logged_in"
            if has_li_at or any(ind in url for ind in SESSION_INDICATORS):
                return "logged_in"
            return "not_logged_in"
        except Exception as e:
            logger.warning("Error checking session: {}", e)
            return f"error: {e}"

    async def wait_for_login(self, timeout: int = DEFAULT_LOGIN_TIMEOUT_SEC) -> str:
        """Actively poll and wait for user to complete manual login."""
        page = self.get_page()
        if not page or not self._context:
            return "error: browser not started"

        start = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start) < timeout:
            cookies = await page.context.cookies([LINKEDIN_BASE_URL])
            if any(c.get("name") == LI_AT_COOKIE and bool(c.get("value")) for c in cookies):
                state_path = self._get_storage_state_path()
                state_path.parent.mkdir(parents=True, exist_ok=True)
                await self._context.storage_state(path=str(state_path))
                logger.info("Session saved to {}", state_path)
                await self.dismiss_overlays()
                return "logged_in"
            await asyncio.sleep(LOGIN_POLL_INTERVAL_SEC)
        return "timeout"

    async def navigate(self, url: str) -> str:
        """Navigate to URL and auto-dismiss guest overlays."""
        page = self.get_page()
        if not page:
            return "error: browser not started"
        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=DEFAULT_NAV_TIMEOUT_MS,
            )
            await asyncio.sleep(NAV_SETTLE_DELAY_SEC)
            await self.dismiss_overlays()
            return f"navigated: {url}"
        except Exception as e:
            logger.warning("Failed navigating to {}: {}", url, e)
            return f"error: {e}"

    async def dismiss_overlays(self) -> bool:
        """Dismiss guest login and promotional modal popups while keeping Easy Apply intact."""
        page = self.get_page()
        if not page:
            return False

        for sel in OVERLAY_DISMISS_SELECTORS:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=QUICK_LOCATOR_TIMEOUT_MS):
                    # Do not dismiss actual Easy Apply application modal
                    is_apply = await loc.evaluate(
                        f"el => Boolean(el.closest('{EASY_APPLY_MODAL_SELECTOR}'))"
                    )
                    if not is_apply:
                        await loc.click(timeout=DEFAULT_ACTION_TIMEOUT_MS)
                        logger.debug("Dismissed overlay with selector: {}", sel)
                        return True
            except Exception:
                continue
        return False

    async def snapshot(self, include_hidden: bool = False) -> dict[str, Any]:
        """Generate accessibility tree with unique data-hawk-id for deterministic actions."""
        page = self.get_page()
        if not page:
            return {"error": "browser not started"}

        try:
            raw: dict[str, Any] = await page.evaluate(_DOM_SNAPSHOT_JS, include_hidden)
            self._last_elements = raw.get("elements", [])
            return {
                "url": page.url,
                "title": await page.title(),
                "form_errors": raw.get("form_errors", []),
                "elements": self._last_elements,
            }
        except Exception as e:
            logger.warning("DOM snapshot error: {}", e)
            return {"error": str(e)}

    async def interact(self, element_index: int, action: str, value: str = "") -> str:
        """Perform action (click, type, select, upload) on element by its snapshot index."""
        page = self.get_page()
        if not page:
            return "error: browser not started"

        act = action.lower().strip()
        locator = page.locator(f'[data-hawk-id="{element_index}"]').first

        try:
            if act in ("click", "check", "uncheck"):
                await locator.scroll_into_view_if_needed()
                await locator.click(timeout=DEFAULT_ACTION_TIMEOUT_MS)
                return f"clicked index {element_index}"

            if act in ("type", "fill"):
                await locator.scroll_into_view_if_needed()
                await locator.fill(value)
                return f"typed '{value}' into index {element_index}"

            if act == "select":
                selected = await page.evaluate(_SELECT_OPTION_JS, [element_index, value])
                if selected:
                    return f"selected '{selected}' in index {element_index}"
                await locator.select_option(value=value)
                return f"selected '{value}' in index {element_index}"

            if act == "upload":
                file_path = Path(value)
                if not file_path.exists():
                    return f"error: file not found {value}"
                file_input = page.locator('input[type="file"]').first
                if await file_input.count() > 0:
                    await file_input.set_input_files(str(file_path))
                    return f"uploaded file {value}"

                # Try file chooser trigger
                async with page.expect_file_chooser(timeout=DEFAULT_ACTION_TIMEOUT_MS) as fc_info:
                    await locator.click()
                chooser = await fc_info.value
                await chooser.set_files(str(file_path))
                return f"uploaded file via chooser {value}"

            return f"error: unsupported action '{action}'"
        except Exception as e:
            logger.warning("Interaction error on index {}: {}", element_index, e)
            return f"error interacting with element {element_index}: {e}"

    async def screenshot(self, output_path: str | Path | None = None) -> str:
        """Capture screenshot to path or return base64 encoded PNG string."""
        page = self.get_page()
        if not page:
            return "error: browser not started"
        try:
            if output_path:
                out = Path(output_path).resolve()
                out.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(out), full_page=False)
                return f"saved: {out}"

            img_bytes = await page.screenshot(type="png")
            return base64.b64encode(img_bytes).decode("utf-8")
        except Exception as e:
            logger.warning("Screenshot error: {}", e)
            return f"error: {e}"

    async def render_pdf(self, html_content: str, output_path: str | Path) -> str:
        """Render raw HTML to PDF using active browser tab or ephemeral headless instance."""
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        encoded = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
        data_url = f"data:text/html;base64,{encoded}"

        page = self.get_page()
        if page and not page.is_closed():
            temp_page = await page.context.new_page()
            try:
                await self._render_page_to_pdf(temp_page, data_url, out)
                return str(out)
            finally:
                await temp_page.close()

        # Ephemeral headless fallback if browser is not actively running
        async with async_playwright() as p:
            temp_browser = await p.chromium.launch(headless=True)
            try:
                temp_page = await temp_browser.new_page()
                try:
                    await self._render_page_to_pdf(temp_page, data_url, out)
                finally:
                    await temp_page.close()
            finally:
                await temp_browser.close()

        return str(out)


# Global singleton browser manager
browser = BrowserManager()
