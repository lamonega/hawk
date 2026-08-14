# hawk — Agent Instructions

You are driving the **hawk** job application agent. hawk provides 12 high-level MCP tools
to automate LinkedIn Easy Apply job discovery, ATS tailored resume generation, form autofilling,
and recruiter networking.

You (the agent) are the brain. You use your own LLM to score jobs, tailor resumes,
and make decisions. hawk provides the browser automation, template rendering, and persistence.

---

## Architecture & Project Structure

```
hawk/
├── config/
│   ├── profile.example.yaml          # Profile template
│   ├── settings.example.yaml         # Settings template
│   └── plain_text_resume.example.yaml# Plain text resume template
├── hawk/
│   ├── __init__.py                   # Package version (v1.0.0)
│   ├── config.py                     # Centralized Pydantic models, settings & profile
│   ├── browser.py                    # Playwright engine, stealth patches & DOM snapshot
│   ├── linkedin.py                   # LinkedIn search, job extractor & Easy Apply engine
│   ├── resume.py                     # ATS resume & cover letter compiler
│   ├── storage.py                    # SQLite database storage (jobs, apps, daily limits)
│   ├── mcp.py                        # FastMCP server with 12 high-level tools
│   ├── cli.py                        # CLI entrypoint (doctor, mcp, run)
│   └── templates/                    # Jinja2 templates (resume.html, cover_letter.html)
├── pyproject.toml                    # Package metadata & dependencies
└── README.md                         # Documentation
```

---

## The 12 Consolidated MCP Tools

| Tool | Parameters | Description |
|---|---|---|
| `browser_session` | `action`, `timeout`, `headless` | Manage browser lifecycle: `'launch'`, `'status'`, `'wait_login'`, `'close'`. |
| `browser_navigate` | `url` | Navigate to any URL and auto-dismiss guest modal popups. |
| `browser_snapshot` | `include_hidden` | Extract accessibility DOM tree with indexed elements and error diagnostics. |
| `browser_interact` | `element_index`, `action`, `value` | Execute atomic DOM interaction (`'click'`, `'type'`, `'select'`, `'upload'`). |
| `browser_screenshot`| `output_path` | Capture page screenshot for debugging. |
| `linkedin_search` | `positions`, `locations`, `easy_apply` | Navigate to LinkedIn job search with preconfigured filters. |
| `linkedin_extract` | `mode` | Extract job listings (`'jobs_list'`) or active job description (`'job_details'`). |
| `linkedin_apply_step` | `resume_path`, `auto_advance`, `dry_run` | Autofill current Easy Apply modal step with tailored resume and advance. |
| `linkedin_connect_recruiter` | `recruiter_url`, `job_title`, `company`, `custom_note`, `dry_run` | Generate note (<300 chars) and send connection request. |
| `hawk_generate_document` | `doc_type`, `job_id`, `job_title`, `company`, `tailored_headline`, `tailored_summary`, `language` | Compile clean ATS PDF resume or cover letter. |
| `hawk_profile` | `action`, `field`, `value`, `query` | Profile management: `'get'`, `'update'`, `'learn'`, `'query_kb'`, `'sync'`. |
| `hawk_stats` | `action`, `job_id`, `status`, `score`, `resume_path`, `dry_run` | Application history and rate limits: `'daily_count'`, `'get_app'`, `'save_app'`. |

---

## Workflow Pipeline

Follow this 5-stage pipeline when applying to jobs:

### 1. Bootstrap
1. Call `browser_session(action="launch", headless=false)` to launch the browser.
2. Call `browser_session(action="status")` to verify LinkedIn session.
   - If `not_logged_in`: Ask user to log in manually, then call `browser_session(action="wait_login")`.
   - If `logged_in`: Proceed.
3. Call `hawk_profile(action="get")` to inspect candidate data.

### 2. Discover
1. Call `linkedin_search(positions=..., locations=..., easy_apply=true)`.
2. Call `linkedin_extract(mode="jobs_list")` to extract available job cards.
3. For each job: Call `hawk_stats(action="get_app", job_id=job_id)` — skip if already applied.

### 3. Screen
1. Call `browser_navigate(job_url)` then `linkedin_extract(mode="job_details")`.
2. **You** evaluate skills match, experience level, location, and description. Decide score (1-10).

### 4. Tailor (Score >= 7)
1. **Detect Language**: Check if the posting is Spanish, English, etc.
2. Call `hawk_generate_document(doc_type="resume", job_id=job_id, job_title=job_title, tailored_headline=..., tailored_summary=..., highlighted_skills=..., language=...)`.
3. Optionally call `hawk_generate_document(doc_type="cover_letter", job_id=job_id, job_title=job_title, company=company, language=...)`.

### 5. Apply (Easy Apply)
1. Navigate to the job page.
2. Call `linkedin_apply_step(resume_path=resume_pdf, auto_advance=true, dry_run=dry_run)`.
3. If blocked or questions appear:
   - Call `browser_snapshot()` to inspect invalid fields and error messages.
   - Call `hawk_profile(action="query_kb", query=...)` to retrieve factual candidate project stories.
   - Use `browser_interact()` to fill specific inputs.
   - Call `linkedin_apply_step()` again to advance.
4. Record result: Call `hawk_stats(action="save_app", job_id=job_id, status="applied", resume_path=resume_pdf, dry_run=dry_run)`.

---

## Agent Rules

- **Zero Hardcoding & 100% Dynamic Generation**: Never assume or hardcode candidate skills, titles, or experiences. Always inspect `hawk_profile(action="get")` and retrieve relevant project context using `hawk_profile(action="query_kb", query=...)`. All summaries, headlines, cover letters, and connection pitches must be dynamically generated to match the candidate's actual background and the target job description.
- **Language Matching**: Always generate headlines, summaries, cover letters, and connection notes in the **exact primary language of the job posting** (Spanish for Spanish jobs, English for English jobs).
- **Truthful ATS Compliance**: Never fabricate skills, companies, or experiences. Resumes must remain clean, professional, and emoji-free.
- **Safety First**: Always verify `dry_run` before final submission and respect daily limits (`apply.daily_max`).

