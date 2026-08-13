"""Browser driver with persistent profile via Playwright CDP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from hawk.settings import get_settings

_STATE_FILE = "storage_state.json"
_browser: Browser | None = None
_context: BrowserContext | None = None
_page: Page | None = None


def get_profile_dir() -> Path:
    settings = get_settings()
    profile_dir = Path(settings.browser.profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def get_state_path() -> Path:
    return get_profile_dir() / _STATE_FILE


def launch(headless: bool = False) -> Page:
    """Launch browser with persistent profile and return the active page."""
    global _browser, _context, _page

    if _page and not _page.is_closed():
        logger.debug("Browser already running, reusing page")
        return _page

    settings = get_settings()
    headless = headless or settings.browser.headless
    profile_dir = get_profile_dir()

    pw = sync_playwright().start()
    _browser = pw.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )

    state_path = get_state_path()
    context_kwargs: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    if state_path.exists():
        context_kwargs["storage_state"] = str(state_path)
        logger.info("Loading saved session from {}", state_path)

    _context = _browser.new_context(**context_kwargs)
    _page = _context.new_page()

    # Remove webdriver flag
    _page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """
    )

    logger.info("Browser launched (headless={})", headless)
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

        # Check for feed content as a signal
        feed = page.query_selector(".feed-identity-module")
        if feed:
            save_session()
            return "logged_in"

        # Fallback: if we're on /feed/ without redirect, assume logged in
        if "/feed" in url:
            save_session()
            return "logged_in"

        return "not_logged_in"
    except Exception as e:
        logger.error("Session check failed: {}", e)
        return f"error: {e}"


def close() -> None:
    """Close the browser and clean up."""
    global _browser, _context, _page

    if _page and not _page.is_closed():
        _page.close()
    if _context:
        _context.close()
    if _browser:
        _browser.close()

    _page = None
    _context = None
    _browser = None
    logger.info("Browser closed")
