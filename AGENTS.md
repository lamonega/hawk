# hawk — Agent Instructions

You are driving the **hawk** job application agent. hawk provides MCP tools to search
LinkedIn Easy Apply jobs, extract details, screen them, generate tailored resumes,
and fill Easy Apply forms.

You (the agent) are the brain. You use your own LLM to score jobs, tailor resumes,
and make decisions. hawk only provides browser automation and storage.

## How to Run hawk

hawk must be installed and available as an MCP server. The agent calls hawk tools
via the MCP protocol.

### Setup

```bash
cd hawk
pip install -e .
playwright install chromium
hawk doctor    # verify config and browser profile
```

### MCP wiring

Add to your agent's MCP config (e.g., `opencode.json`):

```json
{
  "mcpServers": {
    "hawk": {
      "command": "hawk",
      "args": ["mcp"],
      "cwd": "/path/to/hawk"
    }
  }
}
```

## Workflow

Follow this pipeline when asked to apply to jobs:

### 1. Bootstrap

1. Call `browser_launch(headless=false)` to start the browser with the persistent profile.
2. Call `browser_check_session()` to verify LinkedIn login.
   - If `not_logged_in`: ask the human to log in manually, then call `browser_wait_for_login(timeout=120)`.
   - If `logged_in`: proceed.
3. Call `hawk_check_profile()` to verify the user profile is complete.
   - If `is_complete` is **false** and `completed_at` is empty: **you MUST ask the human** to fill the profile.
     - **Option A (fast)**: Ask "Do you have a file I can use? (CV, resume, PDF, LinkedIn export...)"
       - If yes: call `hawk_import_file(path)`, read the content, extract fields, save each with `hawk_update_profile()`.
     - **Option B (manual)**: Ask each question from `missing_required` one by one via `ask_human()`.
     - Save each answer with `hawk_update_profile(field_path, value)`.
     - After all required fields are filled, call `hawk_mark_profile_complete()` (which auto-syncs `plain_text_resume.yaml`).
     - Ask the user for desired job titles/locations and update settings with `hawk_update_settings("linkedin.positions", ...)` and `hawk_update_settings("linkedin.locations", ...)`.
   - If `is_complete` is true: proceed (you can call `hawk_sync_resume()` to ensure resume sync, or update search filters).

### 2. Discover

1. Build search URL: call `linkedin_search(positions=..., locations=..., easy_apply=true)`.
   - Search filters (experience levels, job types, date range, distance) are automatically applied from `config/settings.yaml`.
2. Extract jobs: call `linkedin_extract_jobs_list()`.
3. For each job: check `get_application_history(job_id)` — skip if already applied.

### 3. Screen (for each job)

1. Call `browser_navigate(job_url)` then `linkedin_extract_job()`.
2. **You** score the job: read the job description and your resume, decide if score >= 7.
   Use your own LLM reasoning. Consider: skills match, experience level, location, company.

### 4. Tailor (optional, if score >= 7)

1. **You** generate a tailored resume: call `hawk_generate_tailored_resume(job_id=..., job_title=..., tailored_headline=..., tailored_summary=..., highlighted_skills=...)`.
   This compiles a clean ATS-optimized PDF saved to `output/resumes/resume_{job_id}.pdf`.
2. Save the returned `resume_path` to use during application.

### 5. Apply (Easy Apply)

1. Navigate to the job page.
2. Call `linkedin_click_easy_apply()`.
3. Auto-fill with tailored resume:
   - Call `linkedin_auto_apply(resume_path=resume_path)` OR loop with `linkedin_auto_fill_step(resume_path=resume_path)`.
   - The wizard automatically completes all screens and uploads the tailored PDF on the resume step.
   - For unknown fields or CAPTCHAs: `ask_human("What should I enter for field X?")`.
4. Check `apply.dry_run` setting. If dry_run is true: **do not call `linkedin_submit()`**.
5. Call `store_application(job_id=..., status="applied", score=..., dry_run=..., resume_path=resume_path)`.

### 6. Rate limit

- After each application, call `get_daily_count()`.
- If count >= `apply.daily_max`: **stop** and tell the human you've hit the daily limit.

### 7. Human-in-the-loop

Always ask the human before:
- Submitting a real application (not dry_run)
- Handling CAPTCHAs
- Filling fields you're unsure about
- When you've been blocked or see unexpected behavior

## Rules

- **Never** automate the LinkedIn login. Always use the persistent profile and ask the
  human to log in manually if the session is expired.
- **Never** submit without checking `apply.dry_run`.
- **Never** exceed the daily cap.
- Add humanized delays between actions (2-6 seconds).
- If anything looks wrong (LinkedIn shows a warning, account restriction message, etc.):
  **stop immediately** and alert the human.

## Stealth & Anti-Detection

hawk uses multiple layers of anti-detection:

| Layer | What it does |
|-------|--------------|
| **playwright-stealth v2** | Patches navigator.webdriver, chrome.runtime, plugins, permissions |
| **Canvas noise** | Subtle per-pixel noise (max +-1, 2% of pixels) on getImageData/toDataURL |
| **WebGL spoof** | Vendor: "Google Inc. (Intel)", Renderer: "ANGLE (Intel, UHD 630)" |
| **AudioContext** | Tiny perturbation on createOscillator.frequency |
| **Realistic UA** | Chrome 129-131 on Windows/Mac, rotated per session |
| **Realistic viewport** | 1920x1080 / 1366x768 / 1536x864 — real resolutions |
| **Locale + Timezone** | en-US, America/New_York |
| **Real plugins** | Chrome PDF Plugin, Chrome PDF Viewer, Native Client |
| **Persistent profile** | Cookies and storage persist between sessions |
| **Anti-detection args** | --disable-blink-features=AutomationControlled |

## File Locations

- Config: `config/settings.yaml`
- Profile: `config/profile.yaml`
- Browser profile: `profiles/linkedin/`
- Output (PDFs, JSON): `output/`
- Database: `output/hawk.db`
- Resume: `config/plain_text_resume.yaml`
- Screenshots: `output/screenshots/`

## Project Structure

```
hawk/
├── hawk/
│   ├── __init__.py              # version
│   ├── cli.py                   # CLI: hawk doctor|mcp|run
│   ├── mcp_server.py            # MCP server with 38 tools
│   ├── settings.py              # Pydantic settings (auto-reloads on file change)
│   ├── profile.py               # User profile: load/save, field matching, completeness check, resume sync
│   ├── file_reader.py           # File import (PDF/TXT/MD/YAML/JSON) with size limits
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── driver.py            # Playwright + stealth launch, persistent profile, session check, login wait
│   │   ├── dom.py               # DOM snapshot, click/type/select/upload via element index
│   │   └── pdf.py               # printToPDF with headless fallback for headed mode
│   ├── linkedin/
│   │   ├── __init__.py
│   │   └── operations.py        # LinkedIn search, extract, Easy Apply wizard, form detection
│   ├── storage/
│   │   ├── __init__.py
│   │   └── db.py                # SQLite: jobs, applications, daily_runs tables
│   └── resume/
│       └── __init__.py
├── config/
│   ├── settings.yaml            # Runtime configuration
│   ├── profile.yaml             # User profile (auto-fills LinkedIn forms)
│   └── plain_text_resume.yaml   # Resume template
├── output/                      # PDFs, DB, job data, screenshots
├── profiles/linkedin/           # Browser persistent profile
├── AGENTS.md                    # This file
├── opencode.json                # MCP wiring for opencode
├── PLAN.md                      # Architecture plan
└── pyproject.toml               # Project metadata
```

## Available Tools (38 total)

### Browser (12)
| Tool | Description |
|------|-------------|
| `browser_launch` | Start browser with persistent profile |
| `browser_check_session` | Verify LinkedIn login status |
| `browser_wait_for_login` | Actively wait for user manual login & auto-save session |
| `browser_navigate` | Navigate to a URL (auto-dismisses guest popups) |
| `browser_snapshot` | Accessibility tree of interactive elements |
| `browser_click` | Click element by index |
| `browser_type` | Type text into element |
| `browser_select` | Select dropdown option |
| `browser_upload_file` | Upload file to input |
| `browser_screenshot` | Capture page screenshot |
| `browser_print_pdf` | Convert page to PDF (auto headless fallback) |
| `browser_close` | Close browser and save session |

### LinkedIn (11)
| Tool | Description |
|------|-------------|
| `linkedin_search` | Navigate to LinkedIn job search |
| `linkedin_extract_jobs_list` | Extract job cards from search results |
| `linkedin_extract_job` | Extract details from a job page |
| `linkedin_click_easy_apply` | Click Easy Apply button (detects already-applied) |
| `linkedin_auto_fill_step` | Auto-fill current wizard step (with optional resume upload & auto-advance) |
| `linkedin_auto_apply` | Execute entire Easy Apply flow automatically (supports tailored resume upload) |
| `linkedin_upload_resume` | Upload custom resume PDF into Easy Apply modal |
| `linkedin_detect_fields` | Detect form fields + progress % in Easy Apply modal |
| `linkedin_next_step` | Click Next/Continue/Submit in wizard |
| `linkedin_submit` | Submit application (unfollows company, verifies modal closed) |
| `linkedin_unfollow_company` | Uncheck "Follow Company" checkbox |
| `linkedin_get_page_text` | Get visible page text |
| `linkedin_build_search_url` | Build search URL (no navigation) |

### Storage (4)
| Tool | Description |
|------|-------------|
| `store_job` | Save job to database |
| `store_application` | Record application (enforces daily cap, deduplicates, saves resume path) |
| `get_daily_count` | Get today's application count |
| `get_application_history` | Check if already applied |

### Utility (13)
| Tool | Description |
|------|-------------|
| `hawk_generate_tailored_resume` | Generate ATS-optimized custom PDF resume matching job keywords |
| `hawk_read_resume` | Read resume YAML template |
| `hawk_sync_resume` | Synchronize profile data into plain text resume template |
| `hawk_read_profile` | Read user profile |
| `hawk_check_profile` | Check profile completeness + missing fields |
| `hawk_mark_profile_complete` | Set completed_at timestamp (auto-syncs resume) |
| `hawk_update_profile` | Update a profile field (with Pydantic validation & auto-sync) |
| `hawk_learn_answer` | Save a Q&A pair for future form questions |
| `hawk_import_file` | Read a user-provided file (PDF/TXT/MD/YAML/JSON) for profile import |
| `hawk_list_profile_fields` | List all profile fields with current values |
| `hawk_read_settings` | Read current settings (auto-reloads on file change) |
| `hawk_update_settings` | Update settings.yaml fields (positions, limits, filters) |
| `ask_human` | Signal need for human input |


