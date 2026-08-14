# hawk

MCP LinkedIn Easy Apply job applier — an AI agent's toolbox.

hawk provides MCP tools for searching LinkedIn Easy Apply jobs, extracting details,
screening them, generating tailored resumes, and filling Easy Apply forms. The agent
(opencode, agy, Claude Code, etc.) is the brain; hawk is the hands.

## Install

```bash
git clone https://github.com/youruser/hawk.git
cd hawk
pip install -e .
playwright install chromium
hawk doctor
```

`hawk doctor` verifies config, browser profile directory, and Playwright.

## MCP wiring

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

## First run

1. Launch browser: `browser_launch(headless=false)`
2. Log in to LinkedIn **manually** in the browser window
3. Tell the agent: "Check my session" → `browser_check_session()`
4. The agent checks your profile → asks you to fill it (or imports from a file)
5. Start applying: "Postulate to backend jobs in Berlin"

## Configuration
Templates are provided in `config/*.example.yaml`. Copy them to customize your setup:

| File | Template | Purpose |
|------|----------|---------|
| `config/settings.yaml` | `config/settings.example.yaml` | Search filters, scoring threshold, daily caps, dry_run |
| `config/profile.yaml` | `config/profile.example.yaml` | Your personal info (auto-fills LinkedIn forms) |
| `config/plain_text_resume.yaml` | `config/plain_text_resume.example.yaml` | Your resume in structured YAML |

Settings auto-reload when you edit `config/settings.yaml` at runtime.

## How it works

- **Persistent browser profile** — login once, hawk reuses the session
- **Agent-driven** — the LLM decides what to apply to, hawk provides tools
- **Human-in-the-loop** — CAPTCHAs and unknown fields ask you
- **Daily rate limits** — configurable cap (default 5/day)
- **Dry-run mode** — test without actually submitting (default: on)
- **Anti-detection** — stealth plugin, canvas/WebGL noise, realistic fingerprint

## Anti-detection

hawk uses multiple layers to avoid LinkedIn bot detection:

- **playwright-stealth v2** — patches navigator.webdriver, chrome.runtime, plugins
- **Canvas fingerprint noise** — subtle per-pixel noise on getImageData/toDataURL
- **WebGL spoofing** — realistic Intel UHD 630 vendor/renderer strings
- **AudioContext perturbation** — tiny frequency noise on oscillators
- **Realistic user agent** — Chrome 129-131 on Windows/Mac, rotated per session
- **Real viewport sizes** — 1920x1080, 1366x768, 1536x864
- **Persistent profile** — cookies persist, looks like a returning user

## Available tools (35)

**Browser (11)** — launch, session check, navigate, snapshot, click, type, select, upload, screenshot, PDF, close

**LinkedIn (10)** — search, extract job list, extract job details, Easy Apply wizard (click, detect fields, next step, submit), unfollow company, page text

**Storage (4)** — save jobs, record applications (with dedup), daily count, check history

**Profile (6)** — read/update profile (with Pydantic validation), check completeness, learn Q&A pairs, import from file, list fields

**Utility (4)** — read resume template, read settings (auto-reload), ask human

## Safety

- **Dry-run by default** — no applications are submitted until you set `dry_run: false`
- **Daily cap** — defaults to 5 applications/day, configurable
- **Human-in-the-loop** — CAPTCHAs and unknown fields always ask you
- **No automated login** — you log in manually, hawk reuses the session
- **Path traversal protection** — file import restricted to safe directories
- **File size limits** — max 10MB for imported files

## ⚠️ Disclaimer

Automating LinkedIn may violate their Terms of Service (Section 8.2). Use at your own risk.
hawk is designed for personal use with your own account. Always use dry-run mode first.
