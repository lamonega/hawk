"""PDF generation via Chrome DevTools Protocol printToPDF."""

from __future__ import annotations

import base64
from pathlib import Path

from loguru import logger

from hawk.browser.driver import get_page


async def print_to_pdf(output_path: str) -> str:
    """Convert the current page to PDF using Playwright's await page.pdf().

    Note: await page.pdf() only works in headless mode. If the browser is running
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
        await page.pdf(
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
        # await page.pdf() fails in headed mode — try with a headless browser
        logger.warning("PDF failed in current mode (likely headed), trying headless: {}", e)
        return await _pdf_via_headless(page.url, out)


async def _pdf_via_headless(url: str, out: Path) -> str:
    """Launch a temporary headless browser to generate PDF."""
    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            temp_page = await context.new_page()
            await temp_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await temp_page.pdf(
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
            await context.close()
            await browser.close()
        logger.info("PDF saved via headless fallback to {}", out)
        return str(out)
    except Exception as e2:
        logger.error("Headless PDF generation also failed: {}", e2)
        return f"error: {e2}"


async def html_to_pdf(html_content: str, output_path: str) -> str:
    """Convert raw HTML content to PDF without disrupting the active browser page.

    Args:
        html_content: Raw HTML string.
        output_path: File path for the output PDF.

    Returns:
        Path to the saved PDF file.
    """
    if not html_content or not html_content.strip():
        return "error: Empty HTML content"

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    page = get_page()
    if page is not None and not page.is_closed():
        try:
            # Try isolated tab in existing context
            temp_page = await page.context.new_page()
            try:
                encoded = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
                data_url = f"data:text/html;base64,{encoded}"
                await temp_page.goto(data_url, wait_until="domcontentloaded", timeout=15000)
                await temp_page.pdf(
                    path=str(out),
                    format="A4",
                    margin={
                        "top": "12mm",
                        "bottom": "12mm",
                        "left": "15mm",
                        "right": "15mm",
                    },
                    print_background=True,
                )
                logger.info("HTML-to-PDF saved to {}", out)
                return str(out)
            finally:
                await temp_page.close()
        except Exception as e:
            logger.warning("Isolated tab PDF failed (likely headed mode), using headless: {}", e)

    # Headless fallback
    return await _html_pdf_via_headless(html_content, out)


async def _html_pdf_via_headless(html_content: str, out: Path) -> str:
    """Launch a temporary headless browser to generate PDF from HTML."""
    from playwright.async_api import async_playwright

    try:
        encoded = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
        data_url = f"data:text/html;base64,{encoded}"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            temp_page = await context.new_page()
            await temp_page.goto(data_url, wait_until="networkidle", timeout=15000)
            await temp_page.pdf(
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
            await context.close()
            await browser.close()
        logger.info("HTML-to-PDF saved via headless fallback to {}", out)
        return str(out)
    except Exception as e:
        logger.error("Headless HTML-to-PDF failed: {}", e)
        return f"error: {e}"
