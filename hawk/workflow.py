"""hawk autonomous workflow engine and agentic application harness."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from hawk.browser.driver import get_page, launch, close, check_linkedin_session
from hawk.browser.dom import snapshot, click_element, type_element, select_element
from hawk.linkedin.operations import (
    search_and_navigate,
    extract_jobs_list,
    extract_job_details,
    click_easy_apply,
    click_next_or_submit,
    unfollow_company,
    submit_application,
    human_delay,
)
from hawk.linkedin.autofill import step_easy_apply_wizard, auto_apply_full_flow
from hawk.profile import load_profile, query_knowledge_base
from hawk.resume.generator import generate_tailored_pdf, generate_tailored_cover_letter
from hawk.settings import get_settings
from hawk.storage.db import (
    init_db,
    insert_job,
    insert_application,
    get_application_history,
    get_today_application_count,
    increment_daily_count,
)


class ApplicationHarness:
    """Resilient Easy Apply execution harness with self-correction feedback loop."""

    def __init__(self, max_steps: int = 8, dry_run: bool | None = None) -> None:
        self.settings = get_settings()
        self.dry_run = dry_run if dry_run is not None else self.settings.apply.dry_run
        self.max_steps = max_steps
        self.profile = load_profile()

    async def apply_to_job(
        self,
        job_id: str,
        job_url: str,
        resume_path: str | None = None,
        cover_letter_path: str | None = None,
    ) -> dict[str, Any]:
        """Execute the Easy Apply wizard with automated self-correction on blockages."""
        page = get_page()
        if page is None:
            return {"status": "error", "message": "Browser is not running"}

        # 1. Check if already applied in local DB
        existing = get_application_history(job_id)
        if existing:
            return {"status": "already_applied_db", "job_id": job_id}

        # 2. Check daily quota
        today_count = get_today_application_count()
        if not self.dry_run and today_count >= self.settings.apply.daily_max:
            return {
                "status": "daily_limit_reached",
                "count": today_count,
                "max": self.settings.apply.daily_max,
            }

        # 3. Navigate and click Easy Apply
        if page.url != job_url:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            await human_delay()

        click_res = await click_easy_apply()
        if click_res.startswith("error") or click_res == "already_applied":
            return {"status": click_res, "job_id": job_id}

        # 4. Step-by-step Execution with Self-Correction Loop
        filled_records = []
        for step in range(self.max_steps):
            logger.info("Harness processing step {}/{} for job {}", step + 1, self.max_steps, job_id)

            step_res = await step_easy_apply_wizard(
                auto_advance=True,
                override_dry_run=self.dry_run,
                resume_path=resume_path,
            )

            filled_records.extend(step_res.get("filled", []))

            if step_res.get("status") == "ready_to_submit_dry_run_blocked":
                logger.info("Harness reached final review screen (dry_run protected)")
                insert_application(
                    job_id=job_id,
                    status="applied_dry_run",
                    score=10,
                    dry_run=True,
                    resume_path=resume_path or "",
                    cover_letter_path=cover_letter_path or "",
                )
                return {
                    "status": "dry_run_completed",
                    "job_id": job_id,
                    "filled": filled_records,
                }

            # Self-healing if wizard didn't advance
            if step_res.get("status") == "no_advance_button":
                snap_json = await snapshot()
                snap_data = json.loads(snap_json) if isinstance(snap_json, str) else {}
                form_errors = snap_data.get("form_errors", [])
                elements = snap_data.get("elements", [])

                logger.debug("Harness inspecting blocked screen: {} errors, {} elements", len(form_errors), len(elements))

                # Check if review/submit button is available
                submit_btn = next(
                    (el for el in elements if el.get("role") == "button" and any(k in el.get("name", "").lower() for k in ("submit", "enviar solicitud", "enviar candidatura", "review", "revisar"))),
                    None
                )
                if submit_btn:
                    if self.dry_run:
                        insert_application(job_id=job_id, status="applied_dry_run", score=10, dry_run=True)
                        return {"status": "dry_run_completed", "job_id": job_id, "filled": filled_records}
                    await click_element(submit_btn["index"])
                    await human_delay()
                    insert_application(job_id=job_id, status="applied", score=10, dry_run=False)
                    increment_daily_count()
                    return {"status": "submitted", "job_id": job_id}

                # Try clicking any primary advance button
                primary_btn = next(
                    (el for el in elements if el.get("role") == "button" and any(k in el.get("name", "").lower() for k in ("next", "siguiente", "continue", "continuar", "avançar"))),
                    None
                )
                if primary_btn:
                    await click_element(primary_btn["index"])
                    await human_delay()
                    continue

                break

            await asyncio.sleep(2.0)

        return {"status": "completed_flow", "job_id": job_id, "filled": filled_records}


class JobSearchEngine:
    """Autonomous job search, scoring, and application runner."""

    def __init__(self, dry_run: bool | None = None) -> None:
        self.settings = get_settings()
        self.dry_run = dry_run if dry_run is not None else self.settings.apply.dry_run
        self.harness = ApplicationHarness(dry_run=self.dry_run)
        init_db()

    async def run(self, max_jobs: int = 3) -> dict[str, Any]:
        """Execute autonomous pipeline from discovery to application."""
        # 1. Launch Browser & Check Session
        await launch(headless=self.settings.browser.headless)
        session_status = await check_linkedin_session()
        if session_status != "logged_in":
            return {
                "status": "error",
                "message": "LinkedIn session not active. Please log in manually once in browser profile.",
            }

        positions_str = ", ".join(self.settings.linkedin.positions)
        locations_str = ", ".join(self.settings.linkedin.locations)

        # 2. Search Easy Apply Jobs
        logger.info("Searching LinkedIn for positions: {} in {}", positions_str, locations_str)
        await search_and_navigate(
            positions=positions_str,
            locations=locations_str,
            easy_apply=self.settings.linkedin.easy_apply_only,
        )

        # 3. Extract Job List
        jobs_list = await extract_jobs_list()
        logger.info("Found {} jobs in search results", len(jobs_list))

        processed = []
        for job_card in jobs_list:
            if len(processed) >= max_jobs:
                break

            job_id = job_card.get("job_id")
            if not job_id or not job_card.get("easy_apply"):
                continue

            # Deduplication
            if get_application_history(job_id) or job_card.get("already_applied"):
                logger.info("Skipping job {} (already applied)", job_id)
                continue

            # Extract full job specs
            job_link = job_card.get("link", f"https://www.linkedin.com/jobs/view/{job_id}/")
            page = get_page()
            if page:
                await page.goto(job_link, wait_until="domcontentloaded", timeout=25000)
                await human_delay()

            job_details = await extract_job_details()
            insert_job(
                job_id=job_id,
                role=job_details.get("role", job_card.get("role", "")),
                company=job_details.get("company", job_card.get("company", "")),
                link=job_link,
                location=job_details.get("location", ""),
                description=job_details.get("description", ""),
            )

            # Generate ATS Tailored Resume & Cover Letter
            role_name = job_details.get("role", "DevOps Engineer")
            company_name = job_details.get("company", "")

            resume_pdf = await generate_tailored_pdf(
                job_id=job_id,
                job_title=role_name,
                tailored_headline=f"{role_name} | CI/CD | Cloud Infrastructure",
            )

            cover_letter_pdf = await generate_tailored_cover_letter(
                job_id=job_id,
                job_title=role_name,
                company=company_name,
            )

            # Apply via resilient harness
            app_result = await self.harness.apply_to_job(
                job_id=job_id,
                job_url=job_link,
                resume_path=resume_pdf,
                cover_letter_path=cover_letter_pdf,
            )

            processed.append({
                "job_id": job_id,
                "role": role_name,
                "company": company_name,
                "result": app_result,
                "resume": resume_pdf,
                "cover_letter": cover_letter_pdf,
            })

            await asyncio.sleep(self.settings.apply.min_delay)

        return {
            "status": "success",
            "processed_jobs_count": len(processed),
            "jobs": processed,
            "today_count": get_today_application_count(),
        }
