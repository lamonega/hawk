"""hawk MCP server - exposes hawk tools via Model Context Protocol."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from mcp.server import MCPServer

from hawk import __version__

server = MCPServer(
    name="hawk",
    version=__version__,
    description="AI-powered LinkedIn Easy Apply job applier. Tools for browser control, job search, and application.",
)


# ── Browser tools ──────────────────────────────────────────────────────────────


@server.tool()
async def browser_launch(headless: bool = False) -> str:
    """Launch the browser with a persistent LinkedIn profile.

    The browser uses a persistent profile directory so your login session is preserved
    between runs. On first use, you must manually log in to LinkedIn.

    Args:
        headless: Run in headless mode (no visible window).

    Returns:
        Status message with the current URL.
    """
    from hawk.browser.driver import launch

    try:
        page = await launch(headless=headless)
        return f"Browser launched. Current URL: {page.url}"
    except Exception as e:
        logger.error("browser_launch failed: {}", e)
        return f"error: {e}"


@server.tool()
async def browser_check_session() -> str:
    """Check if the browser has an active LinkedIn session.

    Returns:
        'logged_in' if session is valid, 'not_logged_in' if you need to log in manually.
    """
    from hawk.browser.driver import check_linkedin_session

    return await check_linkedin_session()


@server.tool()
async def browser_wait_for_login(timeout: int = 120) -> str:
    """Wait actively for the user to complete LinkedIn login in the browser window.

    Checks for the authentication session cookie and interface elements,
    then automatically saves the session state once logged in.

    Args:
        timeout: Maximum seconds to wait (default 120).

    Returns:
        'logged_in', 'timeout: ...', or error message.
    """
    from hawk.browser.driver import wait_for_login

    return await wait_for_login(timeout=timeout)


@server.tool()
async def browser_navigate(url: str) -> str:
    """Navigate the browser to a URL.

    Args:
        url: The URL to navigate to.

    Returns:
        The page title and URL after navigation.
    """
    from hawk.browser.driver import get_page
    try:
        from hawk.browser.driver import dismiss_guest_overlays
    except ImportError:
        dismiss_guest_overlays = None

    page = get_page()
    if page is None:
        return "error: Browser not started. Call browser_launch first."

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if dismiss_guest_overlays:
            await dismiss_guest_overlays(page)
        return f"Navigated to: {page.url}\nTitle: {await page.title()}"
    except Exception as e:
        logger.error("browser_navigate failed: {}", e)
        return f"error: {e}"


@server.tool()
async def browser_snapshot() -> str:
    """Take an accessibility tree snapshot of the current page.

    Returns a JSON with indexed interactive elements (role, name, value).
    Use element indices for browser_click, browser_type, browser_select.

    Returns:
        JSON string with page URL, title, and indexed interactive elements.
    """
    import sys
    sys.modules.pop("hawk.browser.dom", None)
    import hawk.browser.dom

    return await hawk.browser.dom.snapshot()


@server.tool()
async def browser_click(element_index: int) -> str:
    """Click an element by its index from the last snapshot.

    Args:
        element_index: The index of the element to click (from browser_snapshot).

    Returns:
        Result of the click action.
    """
    import sys
    sys.modules.pop("hawk.browser.dom", None)
    import hawk.browser.dom

    return await hawk.browser.dom.click_element(element_index)


@server.tool()
async def browser_type(element_index: int, text: str, clear: bool = False) -> str:
    """Type text into an element by its index.

    Args:
        element_index: The index of the element to type into.
        text: Text to type.
        clear: Clear the field first.

    Returns:
        Result of the type action.
    """
    import sys
    sys.modules.pop("hawk.browser.dom", None)
    import hawk.browser.dom

    return await hawk.browser.dom.type_element(element_index, text, clear)


@server.tool()
async def browser_select(element_index: int, value: str) -> str:
    """Select an option from a dropdown/select element.

    Args:
        element_index: The index of the select element.
        value: The value or label text to select.

    Returns:
        Result of the select action.
    """
    from hawk.browser.driver import get_page
    page = get_page()
    if page is None:
        return "error: Browser not started"

    try:
        # Match option across all dropdowns in active modal or document
        selected = await page.evaluate("""
            (targetVal) => {
                const modal = document.querySelector('.jobs-easy-apply-modal') ||
                              document.querySelector('[role="dialog"]') ||
                              document.querySelector('.artdeco-modal') ||
                              document.body;
                const selects = Array.from(modal.querySelectorAll('select'));
                const valLower = targetVal.toLowerCase().trim();

                for (const sel of selects) {
                    for (let i = 0; i < sel.options.length; i++) {
                        const opt = sel.options[i];
                        const optText = (opt.text || '').toLowerCase().trim();
                        const optVal = (opt.value || '').toLowerCase().trim();
                        if (optText === valLower || optText.includes(valLower) || optVal === valLower) {
                            sel.selectedIndex = i;
                            opt.selected = true;
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('input', { bubbles: true }));
                            sel.dispatchEvent(new Event('change', { bubbles: true }));
                            sel.dispatchEvent(new Event('blur', { bubbles: true }));
                            return opt.text.trim();
                        }
                    }
                }
                return null;
            }
        """, value)

        if selected:
            return f"Selected: '{selected}'"
        return f"error: Could not find option matching '{value}'"
    except Exception as e:
        return f"error: {e}"


@server.tool()
async def browser_upload_file(element_index: int, file_path: str) -> str:
    """Upload a file to a file input element.

    Args:
        element_index: The index of the file input element.
        file_path: Path to the file to upload.

    Returns:
        Result of the upload.
    """
    import sys
    sys.modules.pop("hawk.browser.dom", None)
    import hawk.browser.dom

    return await hawk.browser.dom.upload_file(element_index, file_path)


@server.tool()
async def browser_screenshot() -> str:
    """Take a screenshot of the current page.

    Returns:
        Base64-encoded PNG screenshot.
    """
    from hawk.browser.dom import take_screenshot

    return await take_screenshot()


@server.tool()
async def browser_print_pdf(output_path: str) -> str:
    """Convert the current page to PDF.

    Args:
        output_path: File path for the output PDF.

    Returns:
        Path to the saved PDF file.
    """
    from hawk.browser.pdf import print_to_pdf

    return await print_to_pdf(output_path)


@server.tool()
async def browser_close() -> str:
    """Close the browser and save session.

    Returns:
        Confirmation message.
    """
    from hawk.browser.driver import close, save_session

    try:
        await save_session()
        await close()
        return "Browser closed. Session saved."
    except Exception as e:
        return f"error: {e}"


# ── LinkedIn tools ─────────────────────────────────────────────────────────────


@server.tool()
async def linkedin_search(
    positions: str = "",
    locations: str = "",
    easy_apply: bool = True,
) -> str:
    """Search LinkedIn for Easy Apply jobs.

    Builds a LinkedIn search URL with filters and navigates to it.

    Args:
        positions: Comma-separated job titles/keywords.
        locations: Comma-separated locations.
        easy_apply: Filter for Easy Apply only.

    Returns:
        The search results page URL and count of results.
    """
    from hawk.linkedin.operations import search_and_navigate

    return await search_and_navigate(positions, locations, easy_apply)


@server.tool()
async def linkedin_extract_job() -> str:
    """Extract job details from the current LinkedIn job page.

    Returns:
        JSON with role, company, location, description, easy_apply status, link.
    """
    import importlib
    import hawk.linkedin.operations
    importlib.reload(hawk.linkedin.operations)

    return await hawk.linkedin.operations.extract_job_details()


@server.tool()
async def linkedin_extract_jobs_list() -> str:
    """Extract a list of jobs from a LinkedIn search results page.

    Returns:
        JSON array of job summaries with job_id, role, company, location, link, easy_apply.
    """
    import importlib
    import hawk.linkedin.operations
    importlib.reload(hawk.linkedin.operations)

    return await hawk.linkedin.operations.extract_jobs_list()


@server.tool()
async def linkedin_click_easy_apply() -> str:
    """Click the Easy Apply button on the current job page.

    Returns:
        Result of clicking Easy Apply.
    """
    from hawk.linkedin.operations import click_easy_apply

    return await click_easy_apply()


@server.tool()
async def linkedin_auto_fill_step(resume_path: str | None = None) -> str:
    """Inspect and auto-fill the current Easy Apply form step using user profile data.

    Automatically completes phone, location, experience questions, yes/no radios,
    unfollows company checkbox, and clicks Next/Review.
    If resume_path is specified and current step is resume upload, uploads the file.

    Args:
        resume_path: Optional path to a tailored PDF resume to upload.

    Returns:
        JSON with filled fields, status, and whether next step was reached.
    """
    import importlib
    import hawk.linkedin.autofill
    importlib.reload(hawk.linkedin.autofill)

    result = await hawk.linkedin.autofill.step_easy_apply_wizard(auto_advance=True, resume_path=resume_path)
    return json.dumps(result, indent=2)


@server.tool()
async def linkedin_auto_apply(
    max_steps: int = 8,
    dry_run: bool | None = None,
    resume_path: str | None = None,
) -> str:
    """Execute the entire Easy Apply wizard automatically until review/submit.

    Auto-fills all screens (contact info, experience, legal, resume selection/upload)
    and stops before final submission if dry_run=true (or apply.dry_run=true in settings).

    Args:
        max_steps: Maximum wizard steps to attempt (default 8).
        dry_run: Optional override for dry_run mode (True = stop before submit, False = submit).
        resume_path: Optional path to a tailored PDF resume to upload.

    Returns:
        JSON summary of the application flow and filled fields.
    """
    import importlib
    import hawk.linkedin.autofill
    importlib.reload(hawk.linkedin.autofill)

    result = await hawk.linkedin.autofill.auto_apply_full_flow(
        max_steps=max_steps,
        override_dry_run=dry_run,
        resume_path=resume_path,
    )
    return json.dumps(result, indent=2)


@server.tool()
async def linkedin_upload_resume(resume_path: str) -> str:
    """Upload a custom resume PDF in the current LinkedIn Easy Apply modal.

    Args:
        resume_path: Path to the PDF file to upload.

    Returns:
        Confirmation or error message.
    """
    import importlib
    import hawk.linkedin.operations
    importlib.reload(hawk.linkedin.operations)

    return await hawk.linkedin.operations.upload_resume(resume_path)



@server.tool()
async def linkedin_detect_fields() -> str:
    """Detect form fields in the current Easy Apply modal.

    Returns JSON with fields array (type, name, required, options) and has_submit/has_next flags.
    Use this to understand what needs to be filled before calling browser_type/browser_select.
    """
    import importlib
    import hawk.linkedin.operations
    importlib.reload(hawk.linkedin.operations)

    return await hawk.linkedin.operations.detect_form_fields()


@server.tool()
async def linkedin_next_step() -> str:
    """Click Next/Continue/Submit in the Easy Apply wizard.

    Returns:
        Which button was clicked (clicked_next, clicked_submit, or no_button_found).
    """
    import importlib
    import hawk.linkedin.operations
    importlib.reload(hawk.linkedin.operations)

    return await hawk.linkedin.operations.click_next_or_submit()


@server.tool()
async def linkedin_submit(dry_run: bool | None = None) -> str:
    """Submit the Easy Apply application.

    Automatically unchecks 'Follow Company' before submitting.
    Respects dry_run setting — if dry_run=true (or apply.dry_run=true in settings), does NOT click Submit.

    Args:
        dry_run: Optional override (False to force live submission, True to block).

    Returns:
        'submitted', 'dry_run_blocked', or error.
    """
    import importlib
    import hawk.linkedin.operations
    importlib.reload(hawk.linkedin.operations)

    return await hawk.linkedin.operations.submit_application(override_dry_run=dry_run)


@server.tool()
async def linkedin_unfollow_company() -> str:
    """Uncheck the 'Follow [Company]' checkbox in the Easy Apply modal.

    Returns:
        'unchecked', 'not_found', or error.
    """
    from hawk.linkedin.operations import unfollow_company

    return await unfollow_company()


@server.tool()
async def linkedin_get_page_text() -> str:
    """Get the visible text content of the current page.

    Useful for reading job descriptions, form labels, or any page content.
    Returns up to 10k characters of visible text.
    """
    from hawk.linkedin.operations import get_page_text

    return await get_page_text()


@server.tool()
def linkedin_build_search_url(
    positions: str = "",
    locations: str = "",
    easy_apply: bool = True,
) -> str:
    """Build a LinkedIn job search URL with filters (does NOT navigate).

    Args:
        positions: Comma-separated job titles/keywords.
        locations: Comma-separated locations.
        easy_apply: Filter for Easy Apply only.

    Returns:
        The constructed search URL.
    """
    from hawk.linkedin.operations import build_search_url

    return build_search_url(positions, locations, easy_apply)


# ── Storage tools ──────────────────────────────────────────────────────────────


@server.tool()
def store_job(
    job_id: str,
    role: str,
    company: str,
    link: str,
    location: str = "",
    description: str = "",
) -> str:
    """Store a job in the database.

    Args:
        job_id: Unique job identifier.
        role: Job title.
        company: Company name.
        link: URL to the job posting.
        location: Job location.
        description: Job description.

    Returns:
        Confirmation message.
    """
    from hawk.storage.db import insert_job

    try:
        insert_job(
            job_id=job_id,
            role=role,
            company=company,
            link=link,
            location=location,
            description=description,
        )
        return f"Job stored: {role} at {company} (id={job_id})"
    except Exception as e:
        return f"error: {e}"


@server.tool()
def store_application(
    job_id: str,
    status: str = "applied",
    score: int = 0,
    dry_run: bool = True,
    resume_path: str = "",
    cover_letter_path: str = "",
) -> str:
    """Record an application in the database.

    Args:
        job_id: Unique job identifier.
        status: Application status.
        score: Suitability score.
        dry_run: Whether this was a dry run.
        resume_path: Path to the tailored resume PDF used.
        cover_letter_path: Path to the tailored cover letter used.

    Returns:
        Confirmation message with daily count and remaining quota.
    """
    from hawk.settings import get_settings
    from hawk.storage.db import get_today_application_count, increment_daily_count, insert_application

    try:
        settings = get_settings()
        today_count = get_today_application_count()

        if not dry_run and today_count >= settings.apply.daily_max:
            return (
                f"DAILY_LIMIT_REACHED: {today_count}/{settings.apply.daily_max}. "
                "Stop applying and alert the human."
            )

        inserted = insert_application(
            job_id=job_id,
            status=status,
            score=score,
            dry_run=dry_run,
            resume_path=resume_path,
            cover_letter_path=cover_letter_path,
        )
        if not inserted:
            return f"Already recorded: {job_id} (duplicate application)"

        count = increment_daily_count()
        remaining = max(0, settings.apply.daily_max - count)
        return (
            f"Application recorded: {job_id} (status={status}, dry_run={dry_run}, resume={resume_path}). "
            f"Today: {count}/{settings.apply.daily_max}, remaining: {remaining}"
        )
    except Exception as e:
        return f"error: {e}"


@server.tool()
def get_daily_count() -> str:
    """Get the number of applications submitted today.

    Returns:
        Count of today's applications and the daily limit.
    """
    from hawk.settings import get_settings
    from hawk.storage.db import get_today_application_count

    try:
        count = get_today_application_count()
        settings = get_settings()
        return json.dumps({
            "today": count,
            "daily_max": settings.apply.daily_max,
            "remaining": max(0, settings.apply.daily_max - count),
        })
    except Exception as e:
        return f"error: {e}"


@server.tool()
def get_application_history(job_id: str) -> str:
    """Check if you've already applied to a job.

    Args:
        job_id: The job ID to check.

    Returns:
        Application history or 'not_applied'.
    """
    from hawk.storage.db import get_application_history as db_get_history

    try:
        result = db_get_history(job_id)
        if result:
            return json.dumps(dict(result))
        return "not_applied"
    except Exception as e:
        return f"error: {e}"


# ── Utility tools ──────────────────────────────────────────────────────────────


@server.tool()
def hawk_read_resume() -> str:
    """Read the resume YAML file (config/plain_text_resume.yaml).

    Returns the full content of your resume template. Use this to score jobs
    against your experience or to generate tailored resumes.

    Returns:
        The resume content as a string.
    """
    from pathlib import Path

    resume_path = Path(__file__).resolve().parent.parent / "config" / "plain_text_resume.yaml"
    if not resume_path.exists():
        return f"error: Resume file not found at {resume_path}"

    try:
        return resume_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"error: {e}"


@server.tool()
def hawk_read_profile() -> str:
    """Read the user profile (config/profile.yaml).

    This profile is used to auto-fill LinkedIn Easy Apply form fields.
    Returns the full profile content. Fill it in so hawk can answer
    form questions automatically.

    Returns:
        The profile content as a JSON string.
    """
    from hawk.profile import load_profile

    try:
        profile = load_profile()
        return json.dumps(profile.model_dump(), indent=2, default=str)
    except Exception as e:
        return f"error: {e}"


@server.tool()
def hawk_check_profile() -> str:
    """Check if the user profile is complete enough to start applying.

    Returns:
      - is_complete: false if any required field is missing
      - completed_at: timestamp (empty = never completed)
      - missing_required: fields you MUST ask the human about
      - missing_optional: fields you CAN ask about if you want
      - filled_count / total_count: progress

    IMPORTANT: If is_complete is false and completed_at is empty,
    you MUST ask the human to fill the profile before applying.
    Use the missing_required questions to guide the conversation.

    Returns:
        JSON with completeness status and missing fields.
    """
    from hawk.profile import check_profile_completeness, load_profile

    try:
        profile = load_profile()
        result = check_profile_completeness(profile)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"error: {e}"


@server.tool()
def hawk_mark_profile_complete() -> str:
    """Mark the profile as complete (sets completed_at timestamp).

    Call this AFTER you've finished asking the human all required questions
    and saved them with hawk_update_profile.

    Returns:
        Confirmation with the timestamp.
    """
    from hawk.profile import load_profile, mark_profile_complete

    try:
        profile = load_profile()
        profile = mark_profile_complete(profile)
        return f"Profile marked complete at {profile.completed_at}"
    except Exception as e:
        return f"error: {e}"


@server.tool()
def hawk_update_profile(field_path: str, value: str) -> str:
    """Update a single field in the user profile.

    Uses dot notation to set values. Examples:
      - field_path="personal.first_name", value="John"
      - field_path="skills.python", value="4"
      - field_path="common_answers.what is your gpa", value="3.8"

    After updating, the profile is saved to disk automatically.

    Args:
        field_path: Dot-notation path to the field (e.g. "personal.email").
        value: The value to set.

    Returns:
        Confirmation message.
    """
    from hawk.profile import load_profile, save_profile, UserProfile

    try:
        profile = load_profile()

        # Navigate to the parent and set the value
        parts = field_path.split(".")
        obj = profile
        for part in parts[:-1]:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict):
                obj = obj[part]
            else:
                return f"error: Cannot navigate to '{part}' in path '{field_path}'"

        last_key = parts[-1]
        if isinstance(obj, dict):
            obj[last_key] = value
        else:
            setattr(obj, last_key, value)

        # Re-validate the entire profile before saving
        try:
            UserProfile(**profile.model_dump())
        except Exception as val_err:
            return f"error: Validation failed after update: {val_err}"

        save_profile(profile)
        return f"Profile updated: {field_path} = '{value}'"
    except Exception as e:
        return f"error: {e}"


@server.tool()
def hawk_learn_answer(question: str, answer: str) -> str:
    """Save a question-answer pair to the profile's common_answers cache.

    Call this after you answer a LinkedIn form question via ask_human,
    so hawk remembers the answer for next time.

    Args:
        question: The question text (e.g. "Are you authorized to work in the US?").
        answer: The answer text (e.g. "Yes").

    Returns:
        Confirmation message.
    """
    from hawk.profile import learn_answer, load_profile, save_profile

    try:
        profile = load_profile()
        profile = learn_answer(profile, question, answer)
        save_profile(profile)
        return f"Learned: '{question}' -> '{answer}'"
    except Exception as e:
        return f"error: {e}"


@server.tool()
def hawk_import_file(file_path: str) -> str:
    """Read a user-provided file and return its content as text.

    Use this to auto-fill the profile and resume from a file the user provides.
    Supports: PDF, TXT, MD, YAML, JSON, CSV.

    Workflow:
      1. Ask the human: "Do you have a file I can use to fill your profile? (CV, resume, LinkedIn export...)"
      2. Get the file path from them.
      3. Call this tool with the path.
      4. Read the content and extract profile fields.
      5. Save each field with hawk_update_profile().
      6. Call hawk_mark_profile_complete() when done.

    Args:
        file_path: Path to the file (absolute or relative to working directory).

    Returns:
        The file content as text, or an error message.
    """
    from hawk.file_reader import read_file

    return read_file(file_path)


@server.tool()
def hawk_list_profile_fields() -> str:
    """List all profile fields with their current values.

    Returns a dict of field_path -> current_value.
    Use this to see what's filled and what's empty before/after importing.

    Returns:
        JSON dict of all profile fields and their values.
    """
    from hawk.file_reader import list_profile_fields

    try:
        fields = list_profile_fields()
        return json.dumps(fields, indent=2, default=str)
    except Exception as e:
        return f"error: {e}"


@server.tool()
def hawk_read_settings() -> str:
    """Read the current settings file (config/settings.yaml).

    Returns the full content of the settings file. Useful to check
    daily_max, dry_run, min_score, blacklists, etc.

    Returns:
        The settings content as a string.
    """
    from pathlib import Path

    settings_path = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    if not settings_path.exists():
        return f"error: Settings file not found at {settings_path}"

    try:
        return settings_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"error: {e}"


@server.tool()
def hawk_update_settings(field_path: str, value: Any) -> str:
    """Update a setting in config/settings.yaml.

    Args:
        field_path: Dot-notation path (e.g. "linkedin.positions", "linkedin.locations", "apply.daily_max", "scoring.min_score").
        value: The new value to set (can be a list, boolean, integer, or string).

    Returns:
        Confirmation message.
    """
    from hawk.settings import update_setting

    try:
        update_setting(field_path, value)
        return f"Setting updated: {field_path} = {value}"
    except Exception as e:
        return f"error: {e}"


@server.tool()
def hawk_sync_resume() -> str:
    """Synchronize user profile data from config/profile.yaml into config/plain_text_resume.yaml.

    Populates contact details, education, experience, skills, and languages
    so the plain text resume is fully populated and ready for tailoring or scoring.

    Returns:
        Confirmation message.
    """
    from hawk.profile import load_profile, sync_profile_to_resume

    try:
        profile = load_profile()
        sync_profile_to_resume(profile)
        return "Resume synchronized successfully from profile.yaml to plain_text_resume.yaml"
    except Exception as e:
        return f"error: {e}"


@server.tool()
async def hawk_generate_tailored_resume(
    job_id: str,
    job_title: str = "",
    tailored_headline: str = "",
    tailored_summary: str = "",
    highlighted_skills: list[str] | dict[str, list[str]] | None = None,
    custom_experience: list[dict[str, Any]] | None = None,
) -> str:
    """Generate an ATS-optimized tailored PDF resume for a specific job application.

    Reads the user profile, combines it with job-specific tailoring (summary, headline, skills),
    and exports a professional PDF to output/resumes/resume_{job_id}.pdf.

    Args:
        job_id: Unique job identifier or posting hash.
        job_title: Target job title (e.g. 'Data Platform Engineer').
        tailored_headline: Headline emphasizing skills matching the job.
        tailored_summary: Professional summary tailored to job requirements.
        highlighted_skills: List of keywords/skills or categorized skill dict.
        custom_experience: Optional tailored list of experience entries with bullets.

    Returns:
        Absolute path to the generated PDF resume file.
    """
    import sys
    sys.modules.pop("hawk.resume.generator", None)
    from hawk.resume.generator import generate_tailored_pdf

    try:
        pdf_path = await generate_tailored_pdf(
            job_id=job_id,
            job_title=job_title,
            tailored_headline=tailored_headline,
            tailored_summary=tailored_summary,
            highlighted_skills=highlighted_skills,
            custom_experience=custom_experience,
        )
        return pdf_path
    except Exception as e:
        logger.error("Failed to generate tailored resume: {}", e)
        return f"error: {e}"


@server.tool()
def ask_human(question: str) -> str:
    """Ask the human operator a question and wait for their response.

    Use this when you encounter:
    - A form field that doesn't match the profile
    - A CAPTCHA
    - An ambiguous choice
    - Any situation requiring human judgment

    After receiving the answer, call hawk_learn_answer() to save it
    for future use.

    Args:
        question: The question to ask the human.

    Returns:
        The human's response.
    """
    return f"HUMAN_INPUT_REQUIRED: {question}"


def create_server() -> MCPServer:
    """Create and return the hawk MCP server."""
    return server


if __name__ == "__main__":
    import asyncio
    asyncio.run(server.run_stdio_async())
