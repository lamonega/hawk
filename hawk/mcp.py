"""High-level, consolidated MCP server exposing 12 streamlined automation tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from hawk.browser import browser
from hawk.config import (
    get_settings,
    load_profile,
    save_profile,
    update_setting,
    match_field,
    learn_answer,
    query_knowledge_base,
    sync_profile_to_resume,
    UserProfile,
)
from hawk.linkedin import (
    search,
    extract_jobs_list,
    extract_job_details,
    click_easy_apply,
    apply_step,
    generate_recruiter_pitch,
    connect_recruiter,
)
from hawk.resume import generate_tailored_pdf, generate_tailored_cover_letter
from hawk.storage import (
    init_db,
    insert_job,
    get_job,
    insert_application,
    get_application,
    get_daily_count,
    increment_daily_count,
)

mcp = FastMCP("hawk")
init_db()


# ── 1. Browser Tools ───────────────────────────────────────────────────────────

@mcp.tool()
async def browser_session(action: str = "status", timeout: int = 120, headless: bool = False) -> str:
    """Manage browser session: 'launch', 'status', 'wait_login', or 'close'."""
    act = action.lower().strip()
    if act == "launch":
        await browser.launch(headless=headless)
        return "browser_launched"
    elif act == "status":
        return await browser.check_session()
    elif act == "wait_login":
        return await browser.wait_for_login(timeout=timeout)
    elif act == "close":
        await browser.close()
        return "browser_closed"
    return f"error: unknown session action '{action}'"


@mcp.tool()
async def browser_navigate(url: str) -> str:
    """Navigate browser to specified URL."""
    return await browser.navigate(url)


@mcp.tool()
async def browser_snapshot(include_hidden: bool = False) -> str:
    """Get accessibility DOM tree snapshot with indexed interactive elements and form errors."""
    snap = await browser.snapshot(include_hidden=include_hidden)
    return json.dumps(snap, indent=2)


@mcp.tool()
async def browser_interact(element_index: int, action: str, value: str = "") -> str:
    """Interact with an element by index: action='click', 'type', 'select', or 'upload'."""
    return await browser.interact(element_index, action, value)


@mcp.tool()
async def browser_screenshot(output_path: str = "") -> str:
    """Capture page screenshot."""
    return await browser.screenshot(output_path=output_path or None)


# ── 2. LinkedIn Tools ─────────────────────────────────────────────────────────

@mcp.tool()
async def linkedin_search(positions: str = "", locations: str = "", easy_apply: bool = True) -> str:
    """Search LinkedIn jobs with filters."""
    pos_list = [p.strip() for p in positions.split(",") if p.strip()] if positions else None
    loc_list = [l.strip() for l in locations.split(",") if l.strip()] if locations else None
    return await search(positions=pos_list, locations=loc_list, easy_apply=easy_apply)


@mcp.tool()
async def linkedin_extract(mode: str = "auto") -> str:
    """Extract job list from search page or job details from current job listing (mode: 'jobs_list', 'job_details', 'auto')."""
    page = browser.get_page()
    if not page:
        return json.dumps({"error": "browser not started"})

    url = page.url
    if mode == "jobs_list" or (mode == "auto" and "jobs/search" in url):
        jobs = await extract_jobs_list()
        return json.dumps(jobs, indent=2)
    else:
        details = await extract_job_details()
        return json.dumps(details, indent=2)


@mcp.tool()
async def linkedin_apply_step(
    resume_path: str = "",
    auto_advance: bool = True,
    dry_run: bool = True,
) -> str:
    """Autofill current LinkedIn Easy Apply wizard step with tailored resume and advance."""
    # If on job page without open modal, attempt opening it first
    page = browser.get_page()
    if page:
        has_modal = await page.evaluate("() => !!document.querySelector('[role=\"dialog\"], .jobs-easy-apply-modal')")
        if not has_modal:
            click_res = await click_easy_apply()
            if click_res != "clicked_easy_apply":
                return json.dumps({"status": click_res})

    res = await apply_step(
        resume_path=resume_path or None,
        auto_advance=auto_advance,
        dry_run=dry_run,
    )
    return json.dumps(res, indent=2)


@mcp.tool()
async def linkedin_connect_recruiter(
    recruiter_url: str,
    job_title: str = "",
    company: str = "",
    recruiter_name: str = "",
    custom_note: str = "",
    dry_run: bool = True,
    language: str = "auto",
) -> str:
    """Send personalized connection note (<300 chars) to recruiter. You (the agent) should provide a dynamic custom_note grounded in candidate facts."""
    note = custom_note or generate_recruiter_pitch(
        job_title=job_title,
        company=company,
        recruiter_name=recruiter_name,
        language=language,
    )
    return await connect_recruiter(recruiter_url=recruiter_url, note=note, dry_run=dry_run)


# ── 3. Generation Tools ───────────────────────────────────────────────────────

@mcp.tool()
async def hawk_generate_document(
    doc_type: str,
    job_id: str,
    job_title: str,
    company: str = "",
    tailored_headline: str = "",
    tailored_summary: str = "",
    hiring_manager: str = "",
    body_paragraphs: str = "",
    highlighted_skills: str = "",
    language: str = "auto",
) -> str:
    """Generate ATS PDF resume or cover letter. You (the agent) must dynamically provide tailored_headline, tailored_summary, and highlighted_skills grounded strictly in candidate profile facts."""
    skills_list = [s.strip() for s in highlighted_skills.split(",") if s.strip()] if highlighted_skills else None
    paragraphs_list = [p.strip() for p in body_paragraphs.split("\n\n") if p.strip()] if body_paragraphs else None

    if doc_type.lower() in ("resume", "cv"):
        return await generate_tailored_pdf(
            job_id=job_id,
            job_title=job_title,
            tailored_headline=tailored_headline,
            tailored_summary=tailored_summary,
            highlighted_skills=skills_list,
            language=language,
        )
    elif doc_type.lower() in ("cover_letter", "letter"):
        return await generate_tailored_cover_letter(
            job_id=job_id,
            job_title=job_title,
            company=company,
            hiring_manager=hiring_manager,
            tailored_body=paragraphs_list,
            language=language,
        )
    return f"error: unknown doc_type '{doc_type}', use 'resume' or 'cover_letter'"


# ── 4. Profile, KB & Storage Tools ───────────────────────────────────────────

@mcp.tool()
async def hawk_profile(
    action: str = "get",
    field: str = "",
    value: str = "",
    query: str = "",
) -> str:
    """Manage profile & knowledge base: action='get', 'update', 'query_kb', 'learn', or 'sync'."""
    act = action.lower().strip()
    profile = load_profile()

    if act == "get":
        return json.dumps(profile.model_dump(), indent=2)
    elif act == "update":
        if not field:
            return "error: field required"
        parts = field.split(".")
        obj: Any = profile
        for part in parts[:-1]:
            obj = getattr(obj, part, None) or obj.get(part)
        last = parts[-1]
        if hasattr(obj, last):
            setattr(obj, last, value)
        elif isinstance(obj, dict):
            obj[last] = value
        save_profile(profile)
        return f"updated {field} = {value}"
    elif act == "learn":
        learn_answer(profile, field, value)
        save_profile(profile)
        return f"learned: '{field}' -> '{value}'"
    elif act == "query_kb":
        kb = query_knowledge_base(profile, query or field)
        return json.dumps(kb, indent=2)
    elif act == "sync":
        sync_profile_to_resume(profile)
        return "synchronized profile to plain_text_resume.yaml"

    return f"error: unknown action '{action}'"


@mcp.tool()
async def hawk_stats(
    action: str = "daily_count",
    job_id: str = "",
    status: str = "applied",
    score: int = 10,
    resume_path: str = "",
    dry_run: bool = True,
) -> str:
    """Manage application stats: 'daily_count', 'get_app', 'save_app', or 'save_job'."""
    act = action.lower().strip()
    if act == "daily_count":
        return json.dumps({"today_count": get_daily_count(), "max": get_settings().apply.daily_max})
    elif act == "get_app":
        app = get_application(job_id)
        return json.dumps(app or {}, indent=2)
    elif act == "save_app":
        ok = insert_application(job_id=job_id, status=status, score=score, resume_path=resume_path, dry_run=dry_run)
        if not dry_run:
            increment_daily_count()
        return json.dumps({"inserted": ok, "job_id": job_id, "dry_run": dry_run})
    elif act == "get_job":
        j = get_job(job_id)
        return json.dumps(j or {}, indent=2)

    return f"error: unknown stats action '{action}'"


def create_server() -> FastMCP:
    """Factory for MCP server instance."""
    return mcp


if __name__ == "__main__":
    mcp.run()
