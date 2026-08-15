"""Lightweight SQLite database storage for jobs, applications, and rate limits."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from hawk.config import DATA_DIR

__all__ = [
    "DEFAULT_APPLICATION_STATUS",
    "DEFAULT_DB_NAME",
    "DEFAULT_OUTPUT_DIR",
    "SQLITE_BUSY_TIMEOUT_SECONDS",
    "db_session",
    "get_application",
    "get_daily_count",
    "get_db_path",
    "get_job",
    "increment_daily_count",
    "init_db",
    "insert_application",
    "insert_job",
]

# ── Database & Application Constants ──────────────────────────────────────────

DEFAULT_DB_NAME: str = "hawk.db"
DEFAULT_OUTPUT_DIR: Path = DATA_DIR
DEFAULT_APPLICATION_STATUS: str = "applied"
DEFAULT_SCHEMA_STATUS: str = "pending"
DATE_FORMAT: str = "%Y-%m-%d"
SQLITE_BUSY_TIMEOUT_SECONDS: float = 10.0

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

INIT_SCHEMA_SQL: str = (
    JOBS_TABLE_SCHEMA.strip()
    + "\n"
    + APPLICATIONS_TABLE_SCHEMA.strip()
    + "\n"
    + DAILY_RUNS_TABLE_SCHEMA.strip()
)


# ── Helpers & Serialization ───────────────────────────────────────────────────

def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def _utc_today_str() -> str:
    """Return the current UTC date formatted as ``YYYY-MM-DD``."""
    return datetime.now(UTC).strftime(DATE_FORMAT)


def _serialize_metadata(metadata: dict[str, Any] | None) -> str:
    """Serialize application metadata dictionary to a JSON string."""
    if not metadata:
        return "{}"
    try:
        return json.dumps(metadata, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning("Failed to serialize metadata dict: {}. Storing empty JSON.", exc)
        return "{}"


def _deserialize_metadata(raw_metadata: str | None) -> dict[str, Any]:
    """Deserialize application metadata JSON string to a dictionary."""
    if not raw_metadata:
        return {}
    try:
        parsed = json.loads(raw_metadata)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse metadata JSON: {}. Returning empty dict.", exc)
        return {}


# ── Context Management & Session ──────────────────────────────────────────────

def get_db_path(output_dir: Path | None = None) -> Path:
    """Resolve the SQLite database path, creating the parent directory if needed."""
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / DEFAULT_DB_NAME


@contextmanager
def db_session(output_dir: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager that yields a configured, transactional SQLite connection.

    PRAGMAs applied:
        - ``journal_mode=WAL``: Enables Write-Ahead Logging for high concurrency.
        - ``foreign_keys=ON``: Enforces relational foreign key constraints.
        - ``busy_timeout``: Configures milliseconds to wait before busy locking.

    Transaction semantics:
        Automatically commits on successful block exit, rolls back on unhandled
        exceptions, and guarantees connection closure in the ``finally`` block.
    """
    db_path = get_db_path(output_dir)
    conn = sqlite3.connect(db_path, timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)}")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# ── Database Operations ───────────────────────────────────────────────────────

def init_db(output_dir: Path | None = None) -> None:
    """Create all database tables if they do not already exist.

    Args:
        output_dir: Optional custom directory where the database file resides.
    """
    db_path = get_db_path(output_dir)
    try:
        with db_session(output_dir) as conn:
            conn.executescript(INIT_SCHEMA_SQL)
        logger.debug("Database initialized at {}", db_path)
    except sqlite3.Error as exc:
        logger.error("Failed to initialize database at {}: {}", db_path, exc)
        raise


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
    """Insert or replace a job record in the database.

    Args:
        job_id: Unique identifier for the job posting.
        role: Position title or role name.
        company: Hiring organization name.
        link: Direct URL to the job listing.
        location: Geographic location or remote descriptor.
        description: Full text description of the job posting.
        recruiter_link: Profile URL of the hiring recruiter if available.
        output_dir: Optional custom database storage directory.
    """
    clean_job_id = job_id.strip()
    if not clean_job_id:
        logger.warning("Attempted to insert job with empty job_id; skipping.")
        return

    with db_session(output_dir) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs (
                id, role, company, location, link, description, recruiter_link, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_job_id,
                role.strip(),
                company.strip(),
                location.strip(),
                link.strip(),
                description.strip(),
                recruiter_link.strip(),
                _utc_now_iso(),
            ),
        )


def get_job(job_id: str, output_dir: Path | None = None) -> dict[str, Any] | None:
    """Retrieve a job by ID, or ``None`` if not found.

    Args:
        job_id: Unique identifier for the job posting.
        output_dir: Optional custom database storage directory.

    Returns:
        Dictionary representing the job row, or ``None`` if no record matches.
    """
    clean_job_id = job_id.strip()
    if not clean_job_id:
        return None

    with db_session(output_dir) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (clean_job_id,)).fetchone()
        return dict(row) if row else None


def insert_application(
    job_id: str,
    status: str = DEFAULT_APPLICATION_STATUS,
    score: int | None = None,
    resume_path: str = "",
    cover_letter_path: str = "",
    dry_run: bool = True,
    metadata: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> bool:
    """Insert a new application record, silently ignoring duplicate submissions.

    Args:
        job_id: Unique identifier of the job being applied for.
        status: Application outcome status (e.g., 'applied', 'submitted', 'skipped').
        score: Compatibility screening score (1-10) evaluated by the agent.
        resume_path: Filesystem path to the generated ATS resume PDF.
        cover_letter_path: Filesystem path to the generated cover letter PDF.
        dry_run: Whether this application was executed in preview/dry-run mode.
        metadata: Arbitrary supplemental key-value metadata to store as JSON.
        output_dir: Optional custom database storage directory.

    Returns:
        ``True`` if the application record was inserted; ``False`` if it already existed.
    """
    clean_job_id = job_id.strip()
    if not clean_job_id:
        logger.warning("Attempted to insert application with empty job_id; skipping.")
        return False

    with db_session(output_dir) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO applications (
                job_id, status, score, resume_path, cover_letter_path, applied_at, dry_run, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_job_id,
                status.strip() or DEFAULT_APPLICATION_STATUS,
                score,
                resume_path.strip(),
                cover_letter_path.strip(),
                _utc_now_iso(),
                1 if dry_run else 0,
                _serialize_metadata(metadata),
            ),
        )
        return cursor.rowcount > 0


def get_application(job_id: str, output_dir: Path | None = None) -> dict[str, Any] | None:
    """Retrieve an application record by job ID, or ``None`` if not found.

    Parses the internal ``metadata`` JSON column into a Python dict and converts
    ``dry_run`` into a standard boolean.

    Args:
        job_id: Unique identifier of the target job.
        output_dir: Optional custom database storage directory.

    Returns:
        Dictionary of the application record with deserialized metadata, or ``None``.
    """
    clean_job_id = job_id.strip()
    if not clean_job_id:
        return None

    with db_session(output_dir) as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE job_id = ?", (clean_job_id,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["dry_run"] = bool(data.get("dry_run", 0))
        data["metadata"] = _deserialize_metadata(data.get("metadata"))
        return data


def get_daily_count(output_dir: Path | None = None) -> int:
    """Return the number of applications recorded today (UTC).

    Args:
        output_dir: Optional custom database storage directory.

    Returns:
        Total count of submitted applications for today's date in UTC.
    """
    with db_session(output_dir) as conn:
        row = conn.execute(
            "SELECT count FROM daily_runs WHERE date = ?", (_utc_today_str(),)
        ).fetchone()
        return int(row["count"]) if row else 0


def increment_daily_count(output_dir: Path | None = None) -> int:
    """Increment today's application count (UTC) and return the updated value.

    Args:
        output_dir: Optional custom database storage directory.

    Returns:
        Updated count of submitted applications for today's date in UTC.
    """
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
