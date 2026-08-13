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

| File | Purpose |
|------|---------|
| `config/settings.yaml` | Search filters, scoring threshold, daily caps, dry_run |
| `config/profile.yaml` | Your personal info (auto-fills LinkedIn forms) |
| `config/plain_text_resume.yaml` | Your resume in structured YAML |

## How it works

- **Persistent browser profile** — login once, hawk reuses the session
- **Agent-driven** — the LLM decides what to apply to, hawk provides tools
- **Human-in-the-loop** — CAPTCHAs and unknown fields ask you
- **Daily rate limits** — configurable cap (default 5/day)
- **Dry-run mode** — test without actually submitting (default: on)

## Available tools (35)

**Browser** — launch, session check, navigate, snapshot, click, type, select, upload, screenshot, PDF, close

**LinkedIn** — search, extract job list, extract job details, Easy Apply wizard (click, detect fields, next step, submit), unfollow company, page text

**Storage** — save jobs, record applications, daily count, check history

**Profile** — read/update profile, check completeness, learn Q&A pairs, import from file, list fields

**Utility** — read resume template, read settings, ask human

## ⚠️ Disclaimer

Automating LinkedIn may violate their Terms of Service (Section 8.2). Use at your own risk.
hawk is designed for personal use with your own account. Always use dry-run mode first.
