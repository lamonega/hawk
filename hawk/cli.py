"""hawk CLI - entry point for hawk commands."""

from __future__ import annotations

import click
from loguru import logger


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(verbose: bool) -> None:
    """hawk - AI-powered LinkedIn Easy Apply job applier via MCP."""
    if verbose:
        logger.remove()
        logger.add(lambda msg: click.echo(msg, err=True), level="DEBUG")
    else:
        logger.remove()
        logger.add(lambda msg: click.echo(msg, err=True), level="INFO")


@main.command()
def doctor() -> None:
    """Check hawk installation and configuration."""
    from pathlib import Path

    from hawk.settings import get_settings

    settings = get_settings()
    checks = []

    # Config files
    config_dir = Path("config")
    has_settings = (config_dir / "settings.yaml").exists() or (config_dir / "settings.example.yaml").exists()
    has_profile = (config_dir / "profile.yaml").exists() or (config_dir / "profile.example.yaml").exists()
    has_resume = (config_dir / "plain_text_resume.yaml").exists() or (config_dir / "plain_text_resume.example.yaml").exists()
    checks.append(("Settings config (settings.yaml / settings.example.yaml)", has_settings))
    checks.append(("Profile config (profile.yaml / profile.example.yaml)", has_profile))
    checks.append(("Resume config (plain_text_resume.yaml / plain_text_resume.example.yaml)", has_resume))

    # Database
    from hawk.storage.db import get_db_path

    db_path = get_db_path()
    checks.append(("SQLite database (lazy init)", True))

    # Browser profile
    profile_dir = Path(settings.browser.profile_dir)
    checks.append(("Browser profile dir", profile_dir.exists()))

    # Playwright
    try:
        import playwright  # noqa: F401
        checks.append(("Playwright installed", True))
    except ImportError:
        checks.append(("Playwright installed", False))

    # Display results
    click.echo("\n=== hawk doctor ===\n")
    for name, ok in checks:
        status = click.style("OK", fg="green") if ok else click.style("MISSING", fg="red")
        click.echo(f"  [{status}] {name}")

    if all(ok for _, ok in checks):
        click.echo(click.style("\nAll checks passed.", fg="green"))
    else:
        click.echo(click.style("\nSome checks failed.", fg="yellow"))


@main.command()
def mcp() -> None:
    """Start the hawk MCP server (stdio transport)."""
    from hawk.mcp_server import create_server

    server = create_server()
    server.run()


@main.command()
@click.option("--jobs", "-n", default=3, type=int, help="Number of jobs to process")
@click.option("--dry-run/--no-dry-run", default=True, help="Don't submit applications")
def run(jobs: int, dry_run: bool) -> None:
    """Run hawk in autonomous script mode."""
    import asyncio
    from hawk.workflow import JobSearchEngine

    click.echo(f"Starting hawk autonomous pipeline (jobs={jobs}, dry_run={dry_run})...")
    engine = JobSearchEngine(dry_run=dry_run)
    result = asyncio.run(engine.run(max_jobs=jobs))
    click.echo(f"Pipeline finished: {result.get('status')}")
    if result.get("processed_jobs_count"):
        click.echo(f"Processed {result['processed_jobs_count']} jobs. Today's total: {result.get('today_count')}")


if __name__ == "__main__":
    main()
