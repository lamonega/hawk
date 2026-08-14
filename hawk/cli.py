"""Command line interface for hawk."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from typing import Any

import click
from loguru import logger

from hawk.config import (
    CONFIG_DIR,
    PROFILE_EXAMPLE_PATH,
    PROFILE_PATH,
    PROJECT_ROOT,
    RESUME_EXAMPLE_PATH,
    RESUME_PATH,
    SETTINGS_EXAMPLE_PATH,
    SETTINGS_PATH,
    get_settings,
)

# ── Constants ─────────────────────────────────────────────────────────────────

#: Loguru format string shared by all sink handlers.
_LOG_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
)

#: MCP server transport protocol.
_MCP_TRANSPORT = "stdio"

#: Fallback LinkedIn job URL template; ``{job_id}`` is substituted at runtime.
_LINKEDIN_JOB_URL = "https://www.linkedin.com/jobs/view/{job_id}/"

#: Placeholder role label when a job card omits the position title.
_DEFAULT_ROLE = "Candidate"

#: Placeholder company label when a job card omits the company name.
_DEFAULT_COMPANY = "Unknown"

#: Key in the apply-step result dict that carries the application status.
_KEY_STATUS = "status"

#: Status returned by Easy Apply when the form was successfully submitted.
_STATUS_SUBMITTED = "submitted"

#: Fallback status when the apply-step result omits an explicit status.
_STATUS_APPLIED = "applied"

#: ``browser.check_session()`` return value that indicates an active session.
_SESSION_LOGGED_IN = "logged_in"

#: Seconds to pause between consecutive job applications to mimic human pacing.
_INTER_JOB_DELAY_SECS = 2.0

#: Config file checks: (label, active path, example path).
#: Uses the canonical path constants already defined in ``hawk.config``.
_CONFIG_FILE_CHECKS: list[tuple[str, Any, Any]] = [
    ("Settings", SETTINGS_PATH, SETTINGS_EXAMPLE_PATH),
    ("Profile", PROFILE_PATH, PROFILE_EXAMPLE_PATH),
    ("Resume", RESUME_PATH, RESUME_EXAMPLE_PATH),
]


# ── Logging setup ─────────────────────────────────────────────────────────────


def _setup_logging(verbose: bool) -> None:
    """Configure application logging verbosity.

    Args:
        verbose: When ``True``, sets the log level to DEBUG; otherwise INFO.
    """
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO", format=_LOG_FORMAT)


# ── CLI root ──────────────────────────────────────────────────────────────────


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(verbose: bool) -> None:
    """hawk - AI-powered LinkedIn Easy Apply job applier via MCP."""
    _setup_logging(verbose)


# ── doctor ────────────────────────────────────────────────────────────────────


@main.command()
def doctor() -> None:
    """Check hawk installation, environment, and configuration files."""
    settings = get_settings()
    checks: list[tuple[str, bool]] = []

    # Config file presence: either the active file or its example must exist.
    for label, active_path, example_path in _CONFIG_FILE_CHECKS:
        checks.append((
            f"{label} configuration ({active_path.name} / .example)",
            active_path.exists() or example_path.exists(),
        ))

    # SQLite database connectivity.
    db_ok = False
    try:
        from hawk.storage import init_db
        init_db()
        db_ok = True
    except Exception as exc:
        logger.debug("Database check failed: {}", exc)
    checks.append(("SQLite database initialized", db_ok))

    # Browser profile directory accessibility.
    prof_dir = PROJECT_ROOT / settings.browser.profile_dir
    checks.append((
        "Browser profile directory accessible",
        prof_dir.exists() or prof_dir.parent.exists(),
    ))

    # Playwright package availability.
    checks.append(("Playwright package installed", importlib.util.find_spec("playwright") is not None))

    # Display results.
    click.echo("\n=== hawk doctor ===\n")
    for name, ok in checks:
        label = click.style("OK", fg="green") if ok else click.style("MISSING", fg="red")
        click.echo(f"  [{label}] {name}")

    all_ok = all(ok for _, ok in checks)
    summary, color = ("\nAll checks passed successfully.\n", "green") if all_ok else ("\nSome checks failed.\n", "yellow")
    click.echo(click.style(summary, fg=color))


# ── mcp ───────────────────────────────────────────────────────────────────────


@main.command()
def mcp() -> None:
    """Start hawk MCP server with stdio transport."""
    from hawk.mcp import mcp as server
    server.run(transport=_MCP_TRANSPORT)


# ── run (autonomous pipeline) ─────────────────────────────────────────────────


async def _process_job(card: dict[str, Any], dry_run: bool) -> bool:
    """Navigate to a job listing, generate a tailored resume, and apply.

    Args:
        card: Job card dict as returned by ``extract_jobs_list``.
        dry_run: When ``True``, simulates the apply step without submitting.

    Returns:
        ``True`` if an application was attempted; ``False`` if skipped
        (already applied, missing job ID, or flagged ``already_applied``).
    """
    from hawk.browser import browser
    from hawk.linkedin import apply_step, extract_job_details, human_delay
    from hawk.resume import generate_tailored_pdf
    from hawk.storage import get_application, increment_daily_count, insert_application

    job_id = str(card.get("job_id", "")).strip()
    if not job_id or card.get("already_applied") or get_application(job_id):
        return False

    role = card.get("role", _DEFAULT_ROLE)
    company = card.get("company", _DEFAULT_COMPANY)
    click.echo(f"Processing job: {role} at {company} ({job_id})")

    url = card.get("link") or _LINKEDIN_JOB_URL.format(job_id=job_id)
    await browser.navigate(url)
    await human_delay()

    details = await extract_job_details()
    resume_pdf = await generate_tailored_pdf(
        job_id=job_id,
        job_title=details.get("role") or role,
    )

    result = await apply_step(resume_path=resume_pdf, auto_advance=True, dry_run=dry_run)
    status = result.get(_KEY_STATUS, _STATUS_APPLIED)
    click.echo(f"  Result: {status}")

    insert_application(job_id=job_id, status=status, dry_run=dry_run, resume_path=resume_pdf)
    if not dry_run and status == _STATUS_SUBMITTED:
        increment_daily_count()

    return True


async def _run_pipeline(max_jobs: int, dry_run: bool) -> None:
    """Execute the full autonomous application pipeline.

    Args:
        max_jobs: Upper bound on the number of jobs to process this run.
        dry_run: When ``True``, no real submissions are made and daily
            counters are not incremented.
    """
    from hawk.browser import browser
    from hawk.linkedin import extract_jobs_list, search
    from hawk.storage import get_daily_count

    settings = get_settings()

    if not dry_run and get_daily_count() >= settings.apply.daily_max:
        click.echo(click.style(
            f"Daily application limit reached ({settings.apply.daily_max}). Exiting.",
            fg="yellow",
        ))
        return

    click.echo(f"Starting autonomous pipeline (max_jobs={max_jobs}, dry_run={dry_run})...")

    try:
        await browser.launch(headless=settings.browser.headless)

        if await browser.check_session() != _SESSION_LOGGED_IN:
            click.echo(click.style(
                "LinkedIn session not active. Please log in first via browser_session(action='wait_login').",
                fg="red",
            ))
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
                await asyncio.sleep(_INTER_JOB_DELAY_SECS)

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
