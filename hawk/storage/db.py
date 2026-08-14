"""SQLite storage for hawk applications and state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from hawk.settings import PROJECT_ROOT

DB_NAME = "hawk.db"


def get_db_path(output_dir: Path | None = None) -> Path:
    if output_dir is None:
        output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / DB_NAME


def get_connection(output_dir: Path | None = None) -> sqlite3.Connection:
    db_path = get_db_path(output_dir)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(output_dir: Path | None = None) -> None:
    """Create tables if they don't exist."""
    conn = get_connection(output_dir)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                link TEXT NOT NULL,
                description TEXT,
                summarize TEXT,
                recruiter_link TEXT,
                extracted_at TEXT NOT NULL,
                source TEXT DEFAULT 'linkedin'
            );

            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id),
                status TEXT NOT NULL DEFAULT 'pending',
                score INTEGER,
                score_reasoning TEXT,
                resume_path TEXT,
                cover_letter_path TEXT,
                applied_at TEXT,
                dry_run INTEGER DEFAULT 0,
                metadata TEXT,
                UNIQUE(job_id)
            );

            CREATE TABLE IF NOT EXISTS daily_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                applications_count INTEGER DEFAULT 0,
                metadata TEXT,
                UNIQUE(date)
            );
            """
        )
        conn.commit()
        logger.debug("Database initialized at {}", get_db_path(output_dir))
    finally:
        conn.close()


def insert_job(
    job_id: str,
    role: str,
    company: str,
    link: str,
    location: str = "",
    description: str = "",
    summary: str = "",
    recruiter_link: str = "",
    source: str = "linkedin",
    output_dir: Path | None = None,
) -> None:
    conn = get_connection(output_dir)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO jobs (id, role, company, location, link, description, summarize, recruiter_link, extracted_at, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                role,
                company,
                location,
                link,
                description,
                summary,
                recruiter_link,
                datetime.now(timezone.utc).isoformat(),
                source,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def insert_application(
    job_id: str,
    status: str = "pending",
    score: int | None = None,
    score_reasoning: str = "",
    resume_path: str = "",
    cover_letter_path: str = "",
    dry_run: bool = True,
    metadata: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> bool:
    """Insert an application. Returns True if inserted, False if duplicate."""
    conn = get_connection(output_dir)
    try:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO applications (job_id, status, score, score_reasoning, resume_path, cover_letter_path, applied_at, dry_run, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                status,
                score,
                score_reasoning,
                resume_path,
                cover_letter_path,
                datetime.now(timezone.utc).isoformat(),
                1 if dry_run else 0,
                json.dumps(metadata or {}),
            ),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_today_application_count(output_dir: Path | None = None) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_connection(output_dir)
    try:
        row = conn.execute(
            "SELECT applications_count FROM daily_runs WHERE date = ?", (today,)
        ).fetchone()
        return row["applications_count"] if row else 0
    finally:
        conn.close()


def increment_daily_count(output_dir: Path | None = None) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_connection(output_dir)
    try:
        conn.execute(
            """
            INSERT INTO daily_runs (date, applications_count) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET applications_count = applications_count + 1
            """,
            (today,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT applications_count FROM daily_runs WHERE date = ?", (today,)
        ).fetchone()
        return row["applications_count"]
    finally:
        conn.close()


def get_application_history(job_id: str, output_dir: Path | None = None) -> dict | None:
    conn = get_connection(output_dir)
    try:
        row = conn.execute(
            "SELECT * FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
