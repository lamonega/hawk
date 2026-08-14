"""Lightweight SQLite database storage for jobs, applications, and rate limits."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from hawk.config import PROJECT_ROOT

__all__ = [
    "DEFAULT_DB_NAME",
    "DEFAULT_OUTPUT_DIR",
    "init_db",
    "insert_job",
    "get_job",
    "insert_application",
    "get_application",
    "get_daily_count",
    "increment_daily_count",
]

# ── Database Constants ─────────────────────────────────────────────────────────

DEFAULT_DB_NAME = "hawk.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

# ── Table Schemas ─────────────────────────────────────────────────────────────

JOBS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    link TEXT NOT NULL,
    description TEXT,
    recruiter_link TEXT,
    extracted_at TEXT NOT NULL
);
"""

APPLICATIONS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    status TEXT NOT NULL DEFAULT 'pending',
    score INTEGER,
    resume_path TEXT,
    cover_letter_path TEXT,
    applied_at TEXT,
    dry_run INTEGER DEFAULT 1,
    metadata TEXT,
    UNIQUE(job_id)
);
"""

DAILY_RUNS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_runs (
    date TEXT PRIMARY KEY,
    count INTEGER DEFAULT 0
);
"""

INIT_SCHEMA_SQL = JOBS_TABLE_SCHEMA + APPLICATIONS_TABLE_SCHEMA + DAILY_RUNS_TABLE_SCHEMA


# ── Helpers & Context Management ──────────────────────────────────────────────

def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _utc_today_str() -> str:
    """Return the current UTC date as a ``YYYY-MM-DD`` string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_db_path(output_dir: Path | None = None) -> Path:
    """Resolve the SQLite database path, creating the directory if needed."""
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / DEFAULT_DB_NAME


@contextmanager
def db_session(output_dir: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager that yields a configured, transactional SQLite connection.

    PRAGMAs applied: ``journal_mode=WAL`` and ``foreign_keys=ON``.
    The connection is committed on clean exit and always closed afterward.
    """
    conn = sqlite3.connect(get_db_path(output_dir))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# ── Database Operations ───────────────────────────────────────────────────────

def init_db(output_dir: Path | None = None) -> None:
    """Create all database tables if they do not already exist."""
    db_path = get_db_path(output_dir)
    with db_session(output_dir) as conn:
        conn.executescript(INIT_SCHEMA_SQL)
    logger.debug("Database initialized at {}", db_path)


def insert_job(
    job_id: str,
    role: str,
    company: str,
    link: str,
    location: str = "",
    description: str = "",
    recruiter_link: str = "",
    output_dir: Path | None = None,
) -> None:
    """Insert or replace a job record in the database."""
    with db_session(output_dir) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs (
                id, role, company, location, link, description, recruiter_link, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                role,
                company,
                location,
                link,
                description,
                recruiter_link,
                _utc_now_iso(),
            ),
        )


def get_job(job_id: str, output_dir: Path | None = None) -> dict[str, Any] | None:
    """Retrieve a job by ID, or ``None`` if not found."""
    with db_session(output_dir) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def insert_application(
    job_id: str,
    status: str = "applied",
    score: int | None = None,
    resume_path: str = "",
    cover_letter_path: str = "",
    dry_run: bool = True,
    metadata: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> bool:
    """Insert a new application record, silently ignoring duplicates.

    Returns:
        ``True`` if the record was inserted; ``False`` if it already existed.
    """
    with db_session(output_dir) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO applications (
                job_id, status, score, resume_path, cover_letter_path, applied_at, dry_run, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                status,
                score,
                resume_path,
                cover_letter_path,
                _utc_now_iso(),
                1 if dry_run else 0,
                json.dumps(metadata or {}),
            ),
        )
        return cursor.rowcount > 0


def get_application(job_id: str, output_dir: Path | None = None) -> dict[str, Any] | None:
    """Retrieve an application record by job ID, or ``None`` if not found."""
    with db_session(output_dir) as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None


def get_daily_count(output_dir: Path | None = None) -> int:
    """Return the number of applications recorded today (UTC)."""
    with db_session(output_dir) as conn:
        row = conn.execute(
            "SELECT count FROM daily_runs WHERE date = ?", (_utc_today_str(),)
        ).fetchone()
        return int(row["count"]) if row else 0


def increment_daily_count(output_dir: Path | None = None) -> int:
    """Increment today's application count and return the updated value."""
    today = _utc_today_str()
    with db_session(output_dir) as conn:
        conn.execute(
            """
            INSERT INTO daily_runs (date, count) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET count = count + 1
            """,
            (today,),
        )
        row = conn.execute(
            "SELECT count FROM daily_runs WHERE date = ?", (today,)
        ).fetchone()
        return int(row["count"]) if row else 0
