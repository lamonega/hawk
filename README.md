# hawk

AI-powered LinkedIn Easy Apply job applier via MCP.

## What it does

hawk automates LinkedIn Easy Apply job applications using:
- **MCP tools** exposed to an AI agent (opencode, agy, Claude Code, etc.)
- **Persistent browser profile** with manual LinkedIn login (no automated login)
- **LLM screening** to only apply to relevant jobs
- **Tailored resumes and cover letters** per job
- **Human-in-the-loop** for unknown fields and CAPTCHAs
- **Daily rate limits** and dry-run mode for safety

## Quick start

```bash
cd hawk
pip install -e .
hawk doctor          # verify configuration
hawk mcp             # start MCP server for your agent
```

## MCP wiring

Add to your agent config (e.g., `opencode.json`):

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

Then ask your agent: "Postulate to Easy Apply backend jobs in Berlin"

## Configuration

- `config/settings.yaml` — job search filters, scoring threshold, daily caps
- `config/secrets.yaml` — LLM API keys (gitignored)
- `config/plain_text_resume.yaml` — your resume in structured YAML

## ⚠️ Disclaimer

Automating LinkedIn may violate their Terms of Service (Section 8.2). Use at your own risk.
hawk is designed for personal use with your own account. Always use dry-run mode first.
