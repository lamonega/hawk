"""Command line interface for hawk."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from typing import Any

import click
from loguru import logger

from hawk.config import CONFIG_DIR, PROJECT_ROOT, get_settings


def _setup_logging(verbose: bool) -> None:
    """Configure application logging verbosity."""
    logger.remove()
    log_level = "DEBUG" if verbose else "INFO"
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(verbose: bool) -> None:
    """hawk - AI-powered LinkedIn Easy Apply job applier via MCP."""
    _setup_logging(verbose)


@main.command()
def doctor() -> None:
    """Check hawk installation, environment, and configuration files."""
    settings = get_settings()
    checks: list[tuple[str, bool]] = []

    # 1. Configuration files check (DRY)
    config_targets = [
        ("Settings", "settings.yaml", "settings.example.yaml"),
        ("Profile", "profile.yaml", "profile.example.yaml"),
        ("Resume", "plain_text_resume.yaml", "plain_text_resume.example.yaml"),
    ]
    for label, active_file, example_file in config_targets:
        exists = (CONFIG_DIR / active_file).exists() or (CONFIG_DIR / example_file).exists()
        checks.append((f"{label} configuration ({active_file} / .example)", exists))

    # 2. Database connectivity check
    db_ok = False
    try:
        from hawk.storage import init_db
        init_db()
        db_ok = True
    except Exception as exc:
        logger.debug("Database check failed: {}", exc)
    checks.append(("SQLite database initialized", db_ok))

    # 3. Browser Profile directory check
    prof_dir = PROJECT_ROOT / settings.browser.profile_dir
    prof_ok = prof_dir.exists() or prof_dir.parent.exists()
    checks.append(("Browser profile directory accessible", prof_ok))

    # 4. Playwright installation check
    has_playwright = importlib.util.find_spec("playwright") is not None
    checks.append(("Playwright package installed", has_playwright))

    # Display results
    click.echo("\n=== hawk doctor ===\n")
    for name, ok in checks:
        status = click.style("OK", fg="green") if ok else click.style("MISSING", fg="red")
        click.echo(f"  [{status}] {name}")

    if all(ok for _, ok in checks):
        click.echo(click.style("\nAll checks passed successfully.\n", fg="green"))
    else:
        click.echo(click.style("\nSome checks failed.\n", fg="yellow"))


@main.command()
def mcp() -> None:
    """Start hawk MCP server with stdio transport."""
    from hawk.mcp import mcp as server
    server.run(transport="stdio")


async def _process_job(card: dict[str, Any], dry_run: bool) -> bool:
    """Process and apply to a single job listing.

    Returns True if the application was executed, False if skipped.
    """
    from hawk.browser import browser
    from hawk.linkedin import apply_step, extract_job_details, human_delay
    from hawk.resume import generate_tailored_pdf
    from hawk.storage import get_application, increment_daily_count, insert_application

    job_id = str(card.get("job_id", "")).strip()
    if not job_id or card.get("already_applied") or get_application(job_id):
        return False

    role = card.get("role", "Candidate")
    company = card.get("company", "Unknown")
    click.echo(f"Processing job: {role} at {company} ({job_id})")

    link = card.get("link") or f"https://www.linkedin.com/jobs/view/{job_id}/"
    await browser.navigate(link)
    await human_delay()

    details = await extract_job_details()
    target_title = details.get("role") or role
    resume_pdf = await generate_tailored_pdf(job_id=job_id, job_title=target_title)

    res = await apply_step(resume_path=resume_pdf, auto_advance=True, dry_run=dry_run)
    status = res.get("status", "applied")
    click.echo(f"  Result: {status}")

    insert_application(
        job_id=job_id,
        status=status,
        dry_run=dry_run,
        resume_path=resume_pdf,
    )
    if not dry_run and status == "submitted":
        increment_daily_count()

    return True


async def _run_pipeline(max_jobs: int, dry_run: bool) -> None:
    """Execute the full autonomous application pipeline."""
    from hawk.browser import browser
    from hawk.linkedin import extract_jobs_list, search
    from hawk.storage import get_daily_count

    settings = get_settings()

    if not dry_run and get_daily_count() >= settings.apply.daily_max:
        click.echo(click.style(f"Daily application limit reached ({settings.apply.daily_max}). Exiting.", fg="yellow"))
        return

    click.echo(f"Starting autonomous pipeline (max_jobs={max_jobs}, dry_run={dry_run})...")

    try:
        await browser.launch(headless=settings.browser.headless)

        session_status = await browser.check_session()
        if session_status != "logged_in":
            click.echo(
                click.style(
                    "LinkedIn session not active. Please log in first via browser_session(action='wait_login').",
                    fg="red",
                )
            )
            return

        await search()
        job_cards = await extract_jobs_list()
        click.echo(f"Found {len(job_cards)} Easy Apply jobs.")

        processed = 0
        for card in job_cards:
            if processed >= max_jobs:
                break
            if not dry_run and get_daily_count() >= settings.apply.daily_max:
                click.echo(click.style("Daily application limit reached during run. Stopping.", fg="yellow"))
                break

            if await _process_job(card=card, dry_run=dry_run):
                processed += 1
                await asyncio.sleep(2.0)

        click.echo(f"Pipeline complete. Processed {processed} jobs. Today's total: {get_daily_count()}")
    finally:
        await browser.close()


@main.command()
@click.option("--jobs", "-n", default=3, type=int, help="Maximum jobs to process")
@click.option("--dry-run/--no-dry-run", default=True, help="Enable/disable dry-run mode")
def run(jobs: int, dry_run: bool) -> None:
    """Execute autonomous application pipeline."""
    asyncio.run(_run_pipeline(max_jobs=jobs, dry_run=dry_run))


if __name__ == "__main__":
    main()
