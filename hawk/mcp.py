"""High-level, consolidated MCP server exposing 12 streamlined automation tools."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from mcp.server.fastmcp import FastMCP

from hawk.browser import EASY_APPLY_MODAL_SELECTOR, browser
from hawk.config import (
    get_settings,
    learn_answer,
    load_profile,
    query_knowledge_base,
    save_profile,
    sync_profile_to_resume,
)
from hawk.linkedin import (
    MAX_NOTE_LENGTH,
    apply_step,
    click_easy_apply,
    connect_recruiter,
    extract_job_details,
    extract_jobs_list,
    generate_recruiter_pitch,
    search,
)
from hawk.resume import generate_tailored_cover_letter, generate_tailored_pdf
from hawk.storage import (
    get_application,
    get_daily_count,
    get_job,
    increment_daily_count,
    init_db,
    insert_application,
    insert_job,
)

mcp = FastMCP("hawk")
init_db()

# ── Supported Operation Constants ─────────────────────────────────────────────
SUPPORTED_SESSION_ACTIONS: tuple[str, ...] = ("launch", "status", "wait_login", "close")
SUPPORTED_INTERACT_ACTIONS: tuple[str, ...] = ("click", "type", "fill", "select", "upload")
SUPPORTED_EXTRACT_MODES: tuple[str, ...] = ("jobs_list", "job_details", "auto")
SUPPORTED_DOC_TYPES: tuple[str, ...] = ("resume", "cv", "cover_letter", "letter")
SUPPORTED_PROFILE_ACTIONS: tuple[str, ...] = ("get", "update", "learn", "query_kb", "sync")
SUPPORTED_STATS_ACTIONS: tuple[str, ...] = ("daily_count", "get_app", "save_app", "get_job")
RECRUITER_NOTE_MAX_CHARS: int = MAX_NOTE_LENGTH


# ── DRY Helper Utilities ───────────────────────────────────────────────────────

def _to_json(data: Any) -> str:
    """Serialize data structure to formatted JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False)


def _error_json(message: str, **kwargs: Any) -> str:
    """Format a structured JSON error response."""
    payload: dict[str, Any] = {"error": message}
    payload.update(kwargs)
    return _to_json(payload)


def _parse_list(val: str | list[str] | None, sep: str = ",") -> list[str] | None:
    """Parse comma-separated string or list into a clean list of non-empty strings."""
    if val is None:
        return None
    if isinstance(val, list):
        items = [str(x).strip() for x in val if str(x).strip()]
        return items if items else None
    if isinstance(val, str):
        items = [s.strip() for s in val.split(sep) if s.strip()]
        return items if items else None
    return None


def _parse_paragraphs(val: str | list[str] | None) -> list[str] | None:
    """Parse double-newline separated string or list into a clean list of paragraph strings."""
    if val is None:
        return None
    if isinstance(val, list):
        items = [str(x).strip() for x in val if str(x).strip()]
        return items if items else None
    if isinstance(val, str):
        items = [p.strip() for p in val.split("\n\n") if p.strip()]
        return items if items else None
    return None


def _update_nested_field(root: Any, field_path: str, value: Any) -> str | None:
    """Update a nested attribute or dictionary key using dot-notation.

    Returns:
        None on success, or an error message string on failure.
    """
    parts = field_path.strip().split(".")
    obj: Any = root
    for part in parts[:-1]:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return f"Cannot resolve nested path '{part}' in '{field_path}'"

    last = parts[-1]
    if hasattr(obj, last):
        setattr(obj, last, value)
        return None
    elif isinstance(obj, dict):
        obj[last] = value
        return None
    return f"Field '{last}' cannot be set on target object"


# ── 1. Browser Tools ───────────────────────────────────────────────────────────

@mcp.tool()
async def browser_session(
    action: str = "status",
    timeout: int = 120,
    headless: bool = False,
) -> str:
    """Manage Playwright browser lifecycle and LinkedIn authentication session.

    Args:
        action: Lifecycle action - 'launch', 'status', 'wait_login', or 'close'.
        timeout: Seconds to wait for user to complete manual login when action='wait_login'.
        headless: Run in headless mode if action='launch' (default False for interactive login/inspection).

    Returns:
        JSON string with session action status and details.
    """
    try:
        act = action.lower().strip()
        if act not in SUPPORTED_SESSION_ACTIONS:
            return _error_json(
                f"Unknown session action '{action}'",
                supported_actions=list(SUPPORTED_SESSION_ACTIONS),
            )
        if act == "launch":
            await browser.launch(headless=headless)
            return _to_json({"action": "launch", "status": "browser_launched", "headless": headless})
        elif act == "status":
            session_status = await browser.check_session()
            return _to_json({"action": "status", "status": session_status})
        elif act == "wait_login":
            login_status = await browser.wait_for_login(timeout=timeout)
            return _to_json({"action": "wait_login", "status": login_status, "timeout": timeout})
        elif act == "close":
            await browser.close()
            return _to_json({"action": "close", "status": "browser_closed"})
        return _error_json(
            f"Unknown session action '{action}'",
            supported_actions=list(SUPPORTED_SESSION_ACTIONS),
        )
    except Exception as exc:
        logger.error("browser_session failed: {}", exc)
        return _error_json(str(exc), action=action)


@mcp.tool()
async def browser_navigate(url: str) -> str:
    """Navigate browser to a URL and automatically dismiss guest overlays and popups.

    Args:
        url: The target web address to load.

    Returns:
        JSON string with navigation result and loaded URL.
    """
    try:
        if not url or not url.strip():
            return _error_json("URL parameter is required and cannot be empty")
        target_url = url.strip()
        res = await browser.navigate(target_url)
        if res.startswith("error:"):
            return _error_json(res.replace("error:", "").strip(), url=target_url)
        return _to_json({"status": "navigated", "url": target_url, "detail": res})
    except Exception as exc:
        logger.error("browser_navigate failed for {}: {}", url, exc)
        return _error_json(str(exc), url=url)


@mcp.tool()
async def browser_snapshot(include_hidden: bool = False) -> str:
    """Extract accessibility DOM tree snapshot with indexed interactive elements, form validation errors, and active modals.

    Args:
        include_hidden: Whether to include non-visible elements in the accessibility tree snapshot.

    Returns:
        JSON string containing url, title, form_errors, and indexed elements with data-hawk-id for atomic interaction.
    """
    try:
        snap = await browser.snapshot(include_hidden=include_hidden)
        return _to_json(snap)
    except Exception as exc:
        logger.error("browser_snapshot failed: {}", exc)
        return _error_json(str(exc))


@mcp.tool()
async def browser_interact(
    element_index: int,
    action: str,
    value: str = "",
) -> str:
    """Execute atomic DOM interaction on a snapshot element by index.

    Args:
        element_index: Zero-based index from `browser_snapshot()` elements.
        action: Atomic action type - 'click', 'type', 'fill', 'select', or 'upload'.
        value: Input text for 'type'/'fill', option label/value for 'select', or absolute file path for 'upload'.

    Returns:
        JSON string with interaction status and execution details.
    """
    try:
        act = action.lower().strip()
        if act not in SUPPORTED_INTERACT_ACTIONS:
            return _error_json(
                f"Unknown interaction action '{action}'",
                supported_actions=list(SUPPORTED_INTERACT_ACTIONS),
                element_index=element_index,
            )
        res = await browser.interact(element_index, act, value)
        if res.startswith("error:"):
            return _error_json(
                res.replace("error:", "").strip(),
                element_index=element_index,
                action=act,
            )
        return _to_json({
            "status": "success",
            "element_index": element_index,
            "action": act,
            "detail": res,
        })
    except Exception as exc:
        logger.error("browser_interact failed on index {}: {}", element_index, exc)
        return _error_json(str(exc), element_index=element_index, action=action)


@mcp.tool()
async def browser_screenshot(output_path: str = "") -> str:
    """Capture page screenshot for inspection, debugging, or logging visual state.

    Args:
        output_path: Optional file path to save PNG image. If omitted, returns base64-encoded PNG.

    Returns:
        JSON string with screenshot status and file path or base64 data.
    """
    try:
        clean_path = output_path.strip()
        res = await browser.screenshot(output_path=clean_path or None)
        if res.startswith("error:"):
            return _error_json(res.replace("error:", "").strip(), output_path=clean_path)
        if clean_path:
            return _to_json({"status": "saved", "path": res})
        return _to_json({"status": "captured", "base64_length": len(res), "image_base64": res})
    except Exception as exc:
        logger.error("browser_screenshot failed: {}", exc)
        return _error_json(str(exc), output_path=output_path)


# ── 2. LinkedIn Tools ─────────────────────────────────────────────────────────

@mcp.tool()
async def linkedin_search(
    positions: str | list[str] = "",
    locations: str | list[str] = "",
    easy_apply: bool = True,
) -> str:
    """Search LinkedIn jobs with configured criteria and navigate browser to results.

    Args:
        positions: Target job title keywords (comma-separated string or list, e.g. "DevOps Engineer, Cloud Architect"). Defaults to settings.yaml if omitted.
        locations: Target locations (comma-separated string or list, e.g. "Remote, Spain"). Defaults to settings.yaml if omitted.
        easy_apply: Filter exclusively for LinkedIn Easy Apply postings (default True).

    Returns:
        JSON string with search navigation status, active keywords, and locations.
    """
    try:
        pos_list = _parse_list(positions)
        loc_list = _parse_list(locations)
        res = await search(positions=pos_list, locations=loc_list, easy_apply=easy_apply)
        if res.startswith("error:"):
            return _error_json(res.replace("error:", "").strip())
        return _to_json({
            "status": "navigated",
            "positions": pos_list or get_settings().linkedin.positions,
            "locations": loc_list or get_settings().linkedin.locations,
            "easy_apply": easy_apply,
            "detail": res,
        })
    except Exception as exc:
        logger.error("linkedin_search failed: {}", exc)
        return _error_json(str(exc))


@mcp.tool()
async def linkedin_extract(mode: str = "auto") -> str:
    """Extract job listing cards from search results or detailed posting metadata from current job page.

    Args:
        mode: Extraction target - 'jobs_list' (extract search result cards), 'job_details' (extract active job description & hiring team), or 'auto' (detect from URL).

    Returns:
        JSON string containing list of extracted job cards or detailed job specification object.
    """
    try:
        page = browser.get_page()
        if not page:
            return _error_json("Browser is not started. Launch browser first with browser_session(action='launch').")

        extract_mode = mode.lower().strip()
        if extract_mode not in SUPPORTED_EXTRACT_MODES:
            return _error_json(
                f"Unknown extract mode '{mode}'",
                supported_modes=list(SUPPORTED_EXTRACT_MODES),
            )

        url = page.url
        if extract_mode == "jobs_list" or (extract_mode == "auto" and "jobs/search" in url):
            jobs = await extract_jobs_list()
            for j in jobs:
                jid = str(j.get("job_id", "")).strip()
                if jid:
                    insert_job(
                        job_id=jid,
                        role=j.get("role", ""),
                        company=j.get("company", ""),
                        link=j.get("link", ""),
                        location=j.get("location", ""),
                    )
            return _to_json(jobs)
        else:
            details = await extract_job_details()
            import re
            m = re.search(r"/jobs/view/(\d+)", url)
            if m:
                insert_job(
                    job_id=m.group(1),
                    role=details.get("role", ""),
                    company=details.get("company", ""),
                    link=url,
                    location=details.get("location", ""),
                    description=details.get("description", ""),
                    recruiter_link=details.get("recruiter_link", ""),
                )
            return _to_json(details)
    except Exception as exc:
        logger.error("linkedin_extract failed: {}", exc)
        return _error_json(str(exc), mode=mode)


@mcp.tool()
async def linkedin_apply_step(
    resume_path: str = "",
    auto_advance: bool = True,
    dry_run: bool = True,
) -> str:
    """Autofill current LinkedIn Easy Apply modal step with candidate profile data and advance.

    Instructs the automation engine to detect form fields on the active modal, match them against candidate
    profile facts, attach the tailored ATS resume PDF, and advance or review before submission.

    Args:
        resume_path: Optional absolute file path to tailored ATS resume PDF to upload.
        auto_advance: If True, automatically clicks 'Next', 'Review', or 'Submit application' when form is filled.
        dry_run: If True, safely stops before final submission on review step to prevent accidental real submissions.

    Returns:
        JSON string with step execution result, filled fields, unhandled questions, and submission status.
    """
    try:
        page = browser.get_page()
        if not page:
            return _error_json("Browser is not started. Launch browser first with browser_session(action='launch').")

        if await page.locator(EASY_APPLY_MODAL_SELECTOR).count() == 0:
            click_res = await click_easy_apply()
            if click_res != "clicked_easy_apply":
                return _error_json(f"Could not open Easy Apply modal: {click_res}", status=click_res)

        res = await apply_step(
            resume_path=resume_path.strip() or None,
            auto_advance=auto_advance,
            dry_run=dry_run,
        )
        return _to_json(res)
    except Exception as exc:
        logger.error("linkedin_apply_step failed: {}", exc)
        return _error_json(str(exc))


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
    """Send personalized connection request (<300 chars) to recruiter or hiring manager.

    Dynamic Generation Directive:
        You (the agent) must dynamically compose `custom_note` strictly grounded in candidate profile facts
        and the specific job context. Always compose the note in the primary language of the job posting
        (Spanish for Spanish roles, English for English roles) and ensure length is under 300 characters.

    Args:
        recruiter_url: Profile URL of the recruiter or hiring manager.
        job_title: Applied position title (e.g. "Senior DevOps Engineer").
        company: Target company name.
        recruiter_name: First name of recruiter/hirer for personalized greeting.
        custom_note: Agent-generated custom connection pitch (<300 characters, strictly grounded in candidate facts).
        dry_run: If True, prepares the note and logs intent without sending actual LinkedIn request (default True).
        language: Language code ('en', 'es', or 'auto').

    Returns:
        JSON string with connection status, recipient URL, prepared note, and dry_run flag.
    """
    try:
        if not recruiter_url or not recruiter_url.strip():
            return _error_json("recruiter_url parameter is required and cannot be empty")

        target_url = recruiter_url.strip()
        note = custom_note.strip() or generate_recruiter_pitch(
            job_title=job_title.strip(),
            company=company.strip(),
            recruiter_name=recruiter_name.strip(),
            language=language,
        )
        note = note[:RECRUITER_NOTE_MAX_CHARS]

        res = await connect_recruiter(recruiter_url=target_url, note=note, dry_run=dry_run)
        if res.startswith("error:"):
            return _error_json(res.replace("error:", "").strip(), recruiter_url=target_url)
        return _to_json({
            "status": res,
            "recruiter_url": target_url,
            "note": note,
            "dry_run": dry_run,
        })
    except Exception as exc:
        logger.error("linkedin_connect_recruiter failed for {}: {}", recruiter_url, exc)
        return _error_json(str(exc), recruiter_url=recruiter_url)


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
    body_paragraphs: str | list[str] = "",
    highlighted_skills: str | list[str] = "",
    language: str = "auto",
) -> str:
    """Compile a professional, clean ATS-compliant PDF resume or cover letter tailored to a job description.

    Dynamic Generation Directives:
        1. Zero Hardcoding: Ground all summaries, headlines, and skills in actual candidate profile & KB facts.
        2. Language Matching: Match the exact primary language of the target job posting (Spanish for ES, English for EN).
        3. ATS Truthfulness: Highlight candidate's genuine skills and project achievements without fabrication or emojis.

    Args:
        doc_type: Document format - 'resume' / 'cv' or 'cover_letter' / 'letter'.
        job_id: Unique LinkedIn job identifier used for naming output PDF files.
        job_title: Target job role title (e.g. "Lead Cloud Architect").
        company: Name of target employer company (required for cover letters).
        tailored_headline: Dynamic ATS headline tailored to the role matching candidate's seniority.
        tailored_summary: Concise, tailored professional summary highlighting relevant experience and impact.
        hiring_manager: Optional hiring manager or recruiter name for cover letter salutation.
        body_paragraphs: Cover letter body paragraphs (list of strings or double-newline '\\n\\n' separated text).
        highlighted_skills: Comma-separated string or list of specific candidate skills to highlight for the job.
        language: Language code ('en', 'es', or 'auto' for automatic language matching).

    Returns:
        JSON string with generated PDF file path, document type, job ID, and status.
    """
    try:
        if not job_id or not job_id.strip():
            return _error_json("job_id parameter is required and cannot be empty", doc_type=doc_type)
        if not job_title or not job_title.strip():
            return _error_json("job_title parameter is required and cannot be empty", doc_type=doc_type, job_id=job_id)

        clean_job_id = job_id.strip()
        clean_job_title = job_title.strip()
        clean_company = company.strip()
        dtype = doc_type.lower().strip()
        if dtype not in SUPPORTED_DOC_TYPES:
            return _error_json(
                f"Unknown doc_type '{doc_type}'",
                supported_types=list(SUPPORTED_DOC_TYPES),
                job_id=clean_job_id,
            )

        skills_list = _parse_list(highlighted_skills)
        paragraphs_list = _parse_paragraphs(body_paragraphs)

        if dtype in ("resume", "cv"):
            pdf_path = await generate_tailored_pdf(
                job_id=clean_job_id,
                job_title=clean_job_title,
                tailored_headline=tailored_headline.strip(),
                tailored_summary=tailored_summary.strip(),
                highlighted_skills=skills_list,
                language=language,
            )
            return _to_json({
                "status": "generated",
                "doc_type": "resume",
                "job_id": clean_job_id,
                "path": pdf_path,
                "language": language,
            })
        elif dtype in ("cover_letter", "letter"):
            if not clean_company:
                return _error_json(
                    "company parameter is required for cover letters",
                    doc_type=doc_type,
                    job_id=clean_job_id,
                )
            pdf_path = await generate_tailored_cover_letter(
                job_id=clean_job_id,
                job_title=clean_job_title,
                company=clean_company,
                hiring_manager=hiring_manager.strip(),
                tailored_body=paragraphs_list,
                language=language,
            )
            return _to_json({
                "status": "generated",
                "doc_type": "cover_letter",
                "job_id": clean_job_id,
                "company": clean_company,
                "path": pdf_path,
                "language": language,
            })
        return _error_json(
            f"Unknown doc_type '{doc_type}'",
            supported_types=list(SUPPORTED_DOC_TYPES),
        )
    except Exception as exc:
        logger.error("hawk_generate_document failed for job {}: {}", job_id, exc)
        return _error_json(str(exc), job_id=job_id, doc_type=doc_type)


# ── 4. Profile, KB & Storage Tools ───────────────────────────────────────────

@mcp.tool()
async def hawk_profile(
    action: str = "get",
    field: str = "",
    value: str = "",
    query: str = "",
) -> str:
    """Manage candidate profile, knowledge base queries, and learned form Q&A pairs.

    Dynamic Context Directives:
        Use action='get' to inspect full profile data.
        Use action='query_kb' with job keywords to retrieve candidate STAR project stories, metrics,
        and factual achievements for answering screening questions and tailoring documents.

    Args:
        action: Profile operation - 'get', 'update', 'learn', 'query_kb', or 'sync'.
        field: Dot-notated field path for 'update' (e.g. 'personal.phone') or question key for 'learn'.
        value: New value to set for 'update' or learned answer string for 'learn'.
        query: Search query or screening question when action='query_kb'.

    Returns:
        JSON string containing profile data, knowledge base context, or operation result.
    """
    try:
        act = action.lower().strip()
        if act not in SUPPORTED_PROFILE_ACTIONS:
            return _error_json(
                f"Unknown profile action '{action}'",
                supported_actions=list(SUPPORTED_PROFILE_ACTIONS),
            )

        profile = load_profile()

        if act == "get":
            return _to_json(profile.model_dump())

        elif act == "update":
            if not field or not field.strip():
                return _error_json("Field path is required for profile update (e.g. 'personal.phone')")
            clean_field = field.strip()
            err = _update_nested_field(profile, clean_field, value)
            if err:
                return _error_json(err, field=clean_field)
            save_profile(profile)
            return _to_json({"status": "updated", "field": clean_field, "value": value})

        elif act == "learn":
            if not field or not field.strip() or not value or not value.strip():
                return _error_json("Both 'field' (question) and 'value' (answer) are required for 'learn'")
            clean_field = field.strip()
            clean_value = value.strip()
            learn_answer(profile, clean_field, clean_value)
            save_profile(profile)
            return _to_json({"status": "learned", "question": clean_field, "answer": clean_value})

        elif act == "query_kb":
            search_query = query.strip() or field.strip()
            if not search_query:
                return _error_json("A search 'query' or 'field' is required for query_kb")
            kb_result = query_knowledge_base(profile, search_query)
            return _to_json(kb_result)

        elif act == "sync":
            sync_profile_to_resume(profile)
            return _to_json({
                "status": "synced",
                "message": "Successfully synchronized profile to plain_text_resume.yaml",
            })

        return _error_json(
            f"Unknown profile action '{action}'",
            supported_actions=list(SUPPORTED_PROFILE_ACTIONS),
        )
    except Exception as exc:
        logger.error("hawk_profile action '{}' failed: {}", action, exc)
        return _error_json(str(exc), action=action)


@mcp.tool()
async def hawk_stats(
    action: str = "daily_count",
    job_id: str = "",
    status: str = "applied",
    score: int = 10,
    resume_path: str = "",
    dry_run: bool = True,
) -> str:
    """Query application history, track daily submission limits, and persist job application records.

    Args:
        action: Stats operation - 'daily_count', 'get_app', 'save_app', or 'get_job'.
        job_id: LinkedIn job ID to retrieve or associate with application.
        status: Application outcome status when saving ('applied', 'submitted', 'skipped', 'failed').
        score: Job fit score (1-10) evaluated by the agent.
        resume_path: File path of the tailored ATS resume PDF used for this application.
        dry_run: Whether the application was executed in dry-run mode (if False, increments daily submission count).

    Returns:
        JSON string with daily counts, application records, or save confirmations.
    """
    try:
        act = action.lower().strip()
        if act not in SUPPORTED_STATS_ACTIONS:
            return _error_json(
                f"Unknown stats action '{action}'",
                supported_actions=list(SUPPORTED_STATS_ACTIONS),
            )

        settings = get_settings()

        if act == "daily_count":
            count = get_daily_count()
            daily_max = settings.apply.daily_max
            return _to_json({
                "today_count": count,
                "daily_max": daily_max,
                "limit_reached": count >= daily_max,
            })

        elif act == "get_app":
            if not job_id or not job_id.strip():
                return _error_json("job_id is required for 'get_app'")
            app = get_application(job_id.strip())
            return _to_json(app or {})

        elif act == "save_app":
            if not job_id or not job_id.strip():
                return _error_json("job_id is required for 'save_app'")
            clean_job_id = job_id.strip()
            clean_status = status.strip()
            if get_job(clean_job_id) is None:
                insert_job(
                    job_id=clean_job_id,
                    role="",
                    company="",
                    link=f"https://www.linkedin.com/jobs/view/{clean_job_id}/",
                )
            ok = insert_application(
                job_id=clean_job_id,
                status=clean_status,
                score=score,
                resume_path=resume_path.strip(),
                dry_run=dry_run,
            )
            if not dry_run and clean_status == "submitted":
                increment_daily_count()
            return _to_json({
                "status": "saved",
                "inserted": ok,
                "job_id": clean_job_id,
                "app_status": clean_status,
                "score": score,
                "dry_run": dry_run,
            })

        elif act == "get_job":
            if not job_id or not job_id.strip():
                return _error_json("job_id is required for 'get_job'")
            job = get_job(job_id.strip())
            return _to_json(job or {})

        return _error_json(
            f"Unknown stats action '{action}'",
            supported_actions=list(SUPPORTED_STATS_ACTIONS),
        )
    except Exception as exc:
        logger.error("hawk_stats action '{}' failed: {}", action, exc)
        return _error_json(str(exc), action=action)


def create_server() -> FastMCP:
    """Factory for MCP server instance."""
    return mcp


if __name__ == "__main__":
    mcp.run()
