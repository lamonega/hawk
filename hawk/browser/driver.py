"""Browser driver with persistent profile + full stealth via Playwright."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
from playwright_stealth import Stealth

from hawk.settings import get_settings

_STATE_FILE = "storage_state.json"
_browser: Browser | None = None
_context: BrowserContext | None = None
_page: Page | None = None
_pw: Any = None


# Realistic Chrome user agents (latest stable)
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# Canvas + WebGL + Audio fingerprint spoofing script
_FINGERPRINT_SPOOFING_JS = """
(() => {
    // --- Canvas fingerprint noise ---
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    const origMeasureText = CanvasRenderingContext2D.prototype.measureText;

    CanvasRenderingContext2D.prototype.getImageData = function(sx, sy, sw, sh) {
        const imageData = origGetImageData.call(this, sx, sy, sw, sh);
        const data = imageData.data;
        for (let i = 0; i < data.length; i += 4) {
            if (Math.random() < 0.02) {
                const noise = Math.floor(Math.random() * 3) - 1;
                data[i]     = Math.max(0, Math.min(255, data[i] + noise));
                data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + noise));
                data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + noise));
            }
        }
        return imageData;
    };

    HTMLCanvasElement.prototype.toDataURL = function() {
        const ctx = this.getContext('2d');
        if (ctx) {
            try {
                const imageData = origGetImageData.call(ctx, 0, 0, this.width, this.height);
                const data = imageData.data;
                for (let i = 0; i < data.length; i += 4) {
                    if (Math.random() < 0.02) {
                        const noise = Math.floor(Math.random() * 3) - 1;
                        data[i]     = Math.max(0, Math.min(255, data[i] + noise));
                        data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + noise));
                        data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + noise));
                    }
                }
                ctx.putImageData(imageData, 0, 0);
            } catch(e) {}
        }
        return origToDataURL.apply(this, arguments);
    };

    CanvasRenderingContext2D.prototype.measureText = function() {
        const result = origMeasureText.apply(this, arguments);
        if (result && typeof result.width === 'number') {
            result.width += Math.random() * 0.001;
        }
        return result;
    };

    // --- WebGL fingerprint spoofing ---
    const origGetParam = WebGLRenderingContext.prototype.getParameter;
    const origGetExt = WebGLRenderingContext.prototype.getExtension;

    WebGLRenderingContext.prototype.getParameter = function(pname) {
        if (pname === 37445) return "Google Inc. (Intel)";
        if (pname === 37446) return "ANGLE (Intel, Intel(R) UHD Graphics 630, OpenGL 4.5)";
        if (pname === 7937) return "WebKit";
        if (pname === 7936) return "WebKit WebGL";
        return origGetParam.apply(this, arguments);
    };

    WebGLRenderingContext.prototype.getExtension = function(name) {
        const ext = origGetExt.apply(this, arguments);
        if (name === 'WEBGL_debug_renderer_info' && ext) {
            return ext;
        }
        return ext;
    };

    if (window.WebGL2RenderingContext) {
        const origGetParam2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(pname) {
            if (pname === 37445) return "Google Inc. (Intel)";
            if (pname === 37446) return "ANGLE (Intel, Intel(R) UHD Graphics 630, OpenGL 4.5)";
            if (pname === 7937) return "WebKit";
            if (pname === 7936) return "WebKit WebGL";
            return origGetParam2.apply(this, arguments);
        };
    }

    // --- AudioContext fingerprint spoofing ---
    const origCreateOscillator = AudioContext.prototype.createOscillator;

    AudioContext.prototype.createOscillator = function() {
        const osc = origCreateOscillator.apply(this, arguments);
        const origFreq = Object.getOwnPropertyDescriptor(OscillatorNode.prototype, 'frequency');
        if (origFreq && origFreq.get) {
            Object.defineProperty(osc.frequency, 'value', {
                get: function() { return origFreq.get.call(this) + Math.random() * 0.001; },
                set: function(v) { return origFreq.set.call(this, v); },
                configurable: true,
                enumerable: true
            });
        }
        return osc;
    };

    // --- Navigator consistency ---
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
            ];
            plugins.length = 3;
            return plugins;
        }
    });

    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) window.chrome.runtime = {};

    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (params) => (
        params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(params)
    );

    Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
})();
"""


def get_profile_dir() -> Path:
    from hawk.settings import PROJECT_ROOT
    settings = get_settings()
    profile_dir = PROJECT_ROOT / settings.browser.profile_dir
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def get_state_path() -> Path:
    return get_profile_dir() / _STATE_FILE


def _close_existing() -> None:
    """Close any existing browser resources to prevent process leaks."""
    global _browser, _context, _page, _pw
    try:
        if _page and not _page.is_closed():
            _page.close()
    except Exception:
        pass
    try:
        if _context:
            _context.close()
    except Exception:
        pass
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    try:
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _page = None
    _context = None
    _browser = None
    _pw = None


def launch(headless: bool = False) -> Page:
    """Launch browser with stealth and persistent profile."""
    global _browser, _context, _page, _pw

    # Close existing browser to prevent process leak
    if _browser is not None or _pw is not None:
        logger.warning("Closing existing browser before re-launch")
        _close_existing()

    settings = get_settings()
    headless = headless or settings.browser.headless

    ua = random.choice(_USER_AGENTS)

    viewport = {
        "width": random.choice([1920, 1920, 1920, 1366, 1536]),
        "height": random.choice([1080, 1080, 1080, 768, 864]),
    }

    _pw = Stealth().use_sync(sync_playwright()).start()

    _browser = _pw.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--window-size=1920,1080",
        ],
    )

    state_path = get_state_path()
    context_kwargs: dict[str, Any] = {
        "user_agent": ua,
        "viewport": viewport,
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "color_scheme": "light",
        "device_scale_factor": random.choice([1, 1.25, 1.5]),
        "has_touch": False,
        "java_script_enabled": True,
        "bypass_csp": False,
        "ignore_https_errors": False,
    }
    if state_path.exists():
        context_kwargs["storage_state"] = str(state_path)
        logger.info("Loading saved session from {}", state_path)

    _context = _browser.new_context(**context_kwargs)
    _page = _context.new_page()

    # Apply fingerprint spoofing BEFORE any navigation
    _page.add_init_script(_FINGERPRINT_SPOOFING_JS)

    logger.info("Browser launched with stealth (headless={}, ua={}, viewport={}x{})",
                headless, ua[:50], viewport["width"], viewport["height"])
    return _page


def get_page() -> Page | None:
    """Get the current page, or None if browser not running."""
    return _page if (_page and not _page.is_closed()) else None


def save_session() -> None:
    """Save browser storage state (cookies, localStorage) for session reuse."""
    if _context:
        state_path = get_state_path()
        _context.storage_state(path=str(state_path))
        logger.info("Session saved to {}", state_path)


def check_linkedin_session() -> str:
    """Check if the browser has an active LinkedIn session.

    Returns:
        'logged_in', 'not_logged_in', or error message.
    """
    page = get_page()
    if page is None:
        return "not_started"

    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=15000)
        url = page.url

        if "login" in url or "authwall" in url:
            return "not_logged_in"

        feed = page.query_selector(".feed-identity-module")
        if feed:
            save_session()
            return "logged_in"

        if "/feed" in url:
            save_session()
            return "logged_in"

        return "not_logged_in"
    except Exception as e:
        logger.error("Session check failed: {}", e)
        return f"error: {e}"


def close() -> None:
    """Close the browser and clean up."""
    _close_existing()
    logger.info("Browser closed")
