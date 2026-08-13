"""PDF generation via Chrome DevTools Protocol printToPDF."""

from __future__ import annotations

import base64
from pathlib import Path

from loguru import logger

from hawk.browser.driver import get_page


def print_to_pdf(output_path: str) -> str:
    """Convert the current page to PDF using Playwright's page.pdf().

    Note: page.pdf() only works in headless mode. If the browser is running
    in headed mode, this will launch a temporary headless browser to generate the PDF.

    Args:
        output_path: File path for the output PDF.

    Returns:
        Path to the saved PDF file.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        page.pdf(
            path=str(out),
            format="A4",
            margin={
                "top": "20mm",
                "bottom": "20mm",
                "left": "15mm",
                "right": "15mm",
            },
            print_background=True,
        )
        logger.info("PDF saved to {}", out)
        return str(out)
    except Exception as e:
        # page.pdf() fails in headed mode — try with a headless browser
        logger.warning("PDF failed in current mode (likely headed), trying headless: {}", e)
        return _pdf_via_headless(page.url, out)


def _pdf_via_headless(url: str, out: Path) -> str:
    """Launch a temporary headless browser to generate PDF."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            temp_page = context.new_page()
            temp_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            temp_page.pdf(
                path=str(out),
                format="A4",
                margin={
                    "top": "20mm",
                    "bottom": "20mm",
                    "left": "15mm",
                    "right": "15mm",
                },
                print_background=True,
            )
            context.close()
            browser.close()
        logger.info("PDF saved via headless fallback to {}", out)
        return str(out)
    except Exception as e2:
        logger.error("Headless PDF generation also failed: {}", e2)
        return f"error: {e2}"


def html_to_pdf(html_content: str, output_path: str) -> str:
    """Convert raw HTML content to PDF.

    Loads the HTML as a base64 data URL, then prints to PDF.

    Args:
        html_content: Raw HTML string.
        output_path: File path for the output PDF.

    Returns:
        Path to the saved PDF file.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    if not html_content or not html_content.strip():
        return "error: Empty HTML content"

    try:
        # Use base64 encoding instead of urllib.parse.quote (which breaks HTML tags)
        encoded = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
        data_url = f"data:text/html;base64,{encoded}"
        page.goto(data_url, wait_until="networkidle", timeout=15000)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            page.pdf(
                path=str(out),
                format="A4",
                margin={
                    "top": "20mm",
                    "bottom": "20mm",
                    "left": "15mm",
                    "right": "15mm",
                },
                print_background=True,
            )
        except Exception:
            # Fallback to headless
            return _html_pdf_via_headless(html_content, out)

        logger.info("HTML-to-PDF saved to {}", out)
        return str(out)

    except Exception as e:
        logger.error("HTML-to-PDF failed: {}", e)
        return f"error: {e}"


def _html_pdf_via_headless(html_content: str, out: Path) -> str:
    """Launch a temporary headless browser to generate PDF from HTML."""
    from playwright.sync_api import sync_playwright

    try:
        encoded = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
        data_url = f"data:text/html;base64,{encoded}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            temp_page = context.new_page()
            temp_page.goto(data_url, wait_until="networkidle", timeout=15000)
            temp_page.pdf(
                path=str(out),
                format="A4",
                margin={
                    "top": "20mm",
                    "bottom": "20mm",
                    "left": "15mm",
                    "right": "15mm",
                },
                print_background=True,
            )
            context.close()
            browser.close()
        logger.info("HTML-to-PDF saved via headless fallback to {}", out)
        return str(out)
    except Exception as e:
        logger.error("Headless HTML-to-PDF failed: {}", e)
        return f"error: {e}"
