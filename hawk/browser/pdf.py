"""PDF generation via Chrome DevTools Protocol printToPDF."""

from __future__ import annotations

import base64
from pathlib import Path

from loguru import logger

from hawk.browser.driver import get_page


def print_to_pdf(output_path: str) -> str:
    """Convert the current page to PDF using CDP Page.printToPDF.

    Args:
        output_path: File path for the output PDF.

    Returns:
        Path to the saved PDF file.
    """
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        # Execute CDP command to print to PDF
        pdf_data = page.evaluate(
            """
            async () => {
                const response = await fetch(window.location.href);
                // Use CDP through the page's connection
                return null;
            }
            """
        )

        # Use Playwright's built-in PDF generation
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

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
        logger.error("PDF generation failed: {}", e)
        return f"error: {e}"


def html_to_pdf(html_content: str, output_path: str) -> str:
    """Convert raw HTML content to PDF.

    Loads the HTML as a data URL, then prints to PDF.

    Args:
        html_content: Raw HTML string.
        output_path: File path for the output PDF.

    Returns:
        Path to the saved PDF file.
    """
    import urllib.parse

    page = get_page()
    if page is None:
        return "error: Browser not started"

    if not html_content or not html_content.strip():
        return "error: Empty HTML content"

    try:
        encoded = urllib.parse.quote(html_content)
        data_url = f"data:text/html;charset=utf-8,{encoded}"
        page.goto(data_url, wait_until="networkidle", timeout=15000)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

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

        logger.info("HTML-to-PDF saved to {}", out)
        return str(out)

    except Exception as e:
        logger.error("HTML-to-PDF failed: {}", e)
        return f"error: {e}"
