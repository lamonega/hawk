# hawk

AI-powered LinkedIn Easy Apply job application agent via MCP.

`hawk` provides an MCP toolkit for searching LinkedIn Easy Apply jobs, extracting descriptions, generating tailored ATS resumes & cover letters, and automating form filling. The agent (Claude, OpenCode, Antigravity, etc.) acts as the brain; hawk provides the browser automation and document compilation.

---

## Installation

```bash
git clone https://github.com/youruser/hawk.git
cd hawk
pip install -e .
playwright install chromium
hawk doctor
```

---

## MCP Configuration

Add hawk to your MCP client configuration (e.g. `opencode.json`):

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

---

## Configuration & Onboarding

Run the guided onboarding wizard to create your personal profile (stored in `data/`, 100% ignored in Git):

```bash
hawk onboard    # Interactive wizard: import existing CV (PDF/YAML/TXT) or step-by-step interview
```

### Directory Structure & Templates

| File | Template | Purpose |
|---|---|---|
| `data/settings.yaml` | `hawk/templates/yaml/settings.example.yaml` | Search filters, rate limits, dry_run toggle |
| `data/profile.yaml` | `hawk/templates/yaml/profile.example.yaml` | Candidate facts, STAR stories, skills |
| `hawk/templates/html/` | `resume.html`, `cover_letter.html` | Jinja2 HTML templates for PDF rendering |

---

## Key Features

- **Consolidated 12 MCP Tools**: Streamlined high-level tool suite for minimal token overhead and fast agent execution.
- **Interactive Onboarding (`hawk onboard`)**: Auto-imports text and entities from PDF/YAML/TXT resumes or runs a guided interview.
- **Protected Personal Data**: All personal profiles and settings are stored in `data/`, fully excluded from Git.
- **Multilingual ATS Resumes & Cover Letters**: Generates clean, ATS-compliant PDFs matching the language of the job posting via Jinja2 & Playwright.
- **Stealth Browser Automation**: Anti-detection fingerprinting (canvas noise, WebGL spoofing, UA rotation, persistent session storage).
- **Self-Healing Easy Apply Engine**: Deterministic DOM accessibility tree tagging (`data-hawk-id`) and validation recovery.
- **Human-in-the-Loop & Rate Limits**: Configurable daily application limits and `dry_run` safety guard.

---

## CLI Commands

```bash
hawk onboard   # Interactive onboarding wizard (import CV or guided interview)
hawk doctor    # Verify configuration files, templates, data directory, and Playwright
hawk mcp       # Start the FastMCP server over stdio
hawk run       # Run autonomous job application pipeline
```

---

## License

MIT License. Automating LinkedIn may violate their Terms of Service. Use at your own discretion.
