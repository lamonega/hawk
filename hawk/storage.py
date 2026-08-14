"""Lightweight SQLite database storage for jobs, applications, and rate limits."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from hawk.config import PROJECT_ROOT

DB_NAME = "hawk.db"


def get_db_path(output_dir: Path | None = None) -> Path:
    out = output_dir or (PROJECT_ROOT / "output")
    out.mkdir(parents=True, exist_ok=True)
    return out / DB_NAME


def get_connection(output_dir: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(get_db_path(output_dir)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(output_dir: Path | None = None) -> None:
    """Initialize SQLite database tables."""
    conn = get_connection(output_dir)
    try:
        conn.executescript("""
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

            CREATE TABLE IF NOT EXISTS daily_runs (
                date TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            );
        """)
        conn.commit()
    finally:
        conn.close()


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
    conn = get_connection(output_dir)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs (id, role, company, location, link, description, recruiter_link, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, role, company, location, link, description, recruiter_link, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_job(job_id: str, output_dir: Path | None = None) -> dict[str, Any] | None:
    conn = get_connection(output_dir)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


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
    conn = get_connection(output_dir)
    try:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO applications (job_id, status, score, resume_path, cover_letter_path, applied_at, dry_run, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, status, score, resume_path, cover_letter_path, datetime.now(timezone.utc).isoformat(), 1 if dry_run else 0, json.dumps(metadata or {})),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_application(job_id: str, output_dir: Path | None = None) -> dict[str, Any] | None:
    conn = get_connection(output_dir)
    try:
        row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_daily_count(output_dir: Path | None = None) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_connection(output_dir)
    try:
        row = conn.execute("SELECT count FROM daily_runs WHERE date = ?", (today,)).fetchone()
        return row["count"] if row else 0
    finally:
        conn.close()


def increment_daily_count(output_dir: Path | None = None) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_connection(output_dir)
    try:
        conn.execute(
            """
            INSERT INTO daily_runs (date, count) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET count = count + 1
            """,
            (today,),
        )
        conn.commit()
        row = conn.execute("SELECT count FROM daily_runs WHERE date = ?", (today,)).fetchone()
        return row["count"] if row else 0
    finally:
        conn.close()
