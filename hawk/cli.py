"""Command line interface for hawk."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from loguru import logger

from hawk.config import CONFIG_DIR, get_settings


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(verbose: bool) -> None:
    """hawk - AI-powered LinkedIn Easy Apply job applier via MCP."""
    logger.remove()
    log_level = "DEBUG" if verbose else "INFO"
    logger.add(lambda msg: click.echo(msg, err=True), level=log_level)


@main.command()
def doctor() -> None:
    """Check hawk installation and configuration."""
    settings = get_settings()
    checks = []

    # Configs
    has_settings = (CONFIG_DIR / "settings.yaml").exists() or (CONFIG_DIR / "settings.example.yaml").exists()
    has_profile = (CONFIG_DIR / "profile.yaml").exists() or (CONFIG_DIR / "profile.example.yaml").exists()
    has_resume = (CONFIG_DIR / "plain_text_resume.yaml").exists() or (CONFIG_DIR / "plain_text_resume.example.yaml").exists()
    checks.append(("Settings config (settings.yaml / .example)", has_settings))
    checks.append(("Profile config (profile.yaml / .example)", has_profile))
    checks.append(("Resume config (plain_text_resume.yaml / .example)", has_resume))

    # Database
    from hawk.storage import init_db
    init_db()
    checks.append(("SQLite database initialized", True))

    # Browser Profile
    prof_dir = Path(settings.browser.profile_dir)
    checks.append(("Browser profile directory", prof_dir.exists() or True))

    # Playwright
    try:
        import playwright  # noqa: F401
        checks.append(("Playwright installed", True))
    except ImportError:
        checks.append(("Playwright installed", False))

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
    """Start hawk MCP server (stdio transport)."""
    from hawk.mcp import mcp as server
    server.run(transport="stdio")


@main.command()
@click.option("--jobs", "-n", default=3, type=int, help="Maximum jobs to process")
@click.option("--dry-run/--no-dry-run", default=True, help="Enable/disable dry-run mode")
def run(jobs: int, dry_run: bool) -> None:
    """Execute autonomous application pipeline."""
    from hawk.browser import browser
    from hawk.linkedin import search, extract_jobs_list, extract_job_details, apply_step, human_delay
    from hawk.resume import generate_tailored_pdf
    from hawk.storage import get_application, insert_application, increment_daily_count, get_daily_count

    async def _pipeline():
        click.echo(f"Starting autonomous pipeline (max_jobs={jobs}, dry_run={dry_run})...")
        await browser.launch(headless=get_settings().browser.headless)

        status = await browser.check_session()
        if status != "logged_in":
            click.echo(click.style("LinkedIn session not active. Please log in first via browser_session(action='wait_login').", fg="red"))
            return

        await search()
        job_cards = await extract_jobs_list()
        click.echo(f"Found {len(job_cards)} Easy Apply jobs.")

        processed = 0
        for card in job_cards:
            if processed >= jobs:
                break
            job_id = card.get("job_id")
            if not job_id or card.get("already_applied") or get_application(job_id):
                continue

            click.echo(f"Processing job: {card.get('role')} at {card.get('company')} ({job_id})")
            await browser.navigate(card.get("link", f"https://www.linkedin.com/jobs/view/{job_id}/"))
            await human_delay()

            details = await extract_job_details()
            role_name = details.get("role") or card.get("role") or "Candidate"
            resume_pdf = await generate_tailored_pdf(job_id=job_id, job_title=role_name)

            res = await apply_step(resume_path=resume_pdf, auto_advance=True, dry_run=dry_run)
            click.echo(f"  Result: {res.get('status')}")

            insert_application(job_id=job_id, status=res.get("status", "applied"), dry_run=dry_run, resume_path=resume_pdf)
            if not dry_run and res.get("status") == "submitted":
                increment_daily_count()

            processed += 1
            await asyncio.sleep(2.0)

        click.echo(f"Pipeline complete. Processed {processed} jobs. Today's total: {get_daily_count()}")

    asyncio.run(_pipeline())


if __name__ == "__main__":
    main()
