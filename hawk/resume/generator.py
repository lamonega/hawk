"""Tailored resume generation with ATS-optimized HTML/PDF output."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from hawk.browser.pdf import html_to_pdf
from hawk.profile import load_profile
from hawk.settings import PROJECT_ROOT


def render_ats_resume_html(
    profile_data: dict[str, Any],
    job_title: str = "",
    tailored_headline: str = "",
    tailored_summary: str = "",
    highlighted_skills: list[str] | dict[str, list[str]] | None = None,
    custom_experience: list[dict[str, Any]] | None = None,
) -> str:
    """Generate ATS-optimized clean HTML resume."""
    personal = profile_data.get("personal", {})
    links = profile_data.get("links", {})
    prof = profile_data.get("professional", {})
    educ = profile_data.get("education", {})
    languages = profile_data.get("languages", {})

    first_name = personal.get("first_name", "")
    last_name = personal.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip() or "Laureano Francisco Lamonega"

    headline = tailored_headline or job_title or prof.get("headline", "DevOps Engineer")
    summary = tailored_summary or prof.get("summary", "")

    email = personal.get("email", "lflamonega@gmail.com")
    phone = personal.get("phone", "+54 221 695 9945")
    city = personal.get("city", "Berisso")
    state = personal.get("state", "Buenos Aires")
    country = personal.get("country", "Argentina")
    location_str = f"{city}, {country}" if city else country

    linkedin_url = links.get("linkedin", "linkedin.com/in/lflamonega")
    github_url = links.get("github", "github.com/lflamonega")

    # Format skills section
    skills_html = ""
    if highlighted_skills:
        if isinstance(highlighted_skills, dict):
            categories_html = []
            for cat_name, skill_list in highlighted_skills.items():
                items = ", ".join(skill_list)
                categories_html.append(f"<p><strong>{cat_name}:</strong> {items}</p>")
            skills_html = "".join(categories_html)
        elif isinstance(highlighted_skills, list):
            items = " • ".join(highlighted_skills)
            skills_html = f"<p>{items}</p>"
    else:
        # Default skills based on profile
        skills_html = """
        <p><strong>Cloud & Infrastructure:</strong> AWS (EC2, EKS, S3, IAM, CloudWatch), Linux Server Administration, Virtualization (VMware, VirtualBox)</p>
        <p><strong>CI/CD & Automation:</strong> GitHub Actions, Forgejo Actions, Docker, Bash/PowerShell Scripting, Terraform</p>
        <p><strong>Web Servers & Monitoring:</strong> Nginx, Reverse Proxy Configuration, SSL/TLS, Nagios Monitoring, Prometheus</p>
        """

    # Format experience section
    exp_list = custom_experience or profile_data.get("experience", [])
    exp_html = ""
    if exp_list:
        items = []
        for exp in exp_list:
            role = exp.get("position") or exp.get("role") or "DevOps Engineer"
            comp = exp.get("company", "Municipalidad de Berisso")
            period = exp.get("employment_period") or exp.get("period") or "2023 - Present"
            loc = exp.get("location", "Buenos Aires, Argentina")
            bullets = exp.get("key_responsibilities") or exp.get("bullets") or []

            bullets_html = ""
            for b in bullets:
                b_text = b.get("description", b) if isinstance(b, dict) else str(b)
                bullets_html += f"<li>{b_text}</li>"

            items.append(f"""
            <div class="entry">
                <div class="entry-header">
                    <span class="entry-title"><strong>{role}</strong> — {comp}</span>
                    <span class="entry-date">{period}</span>
                </div>
                <div class="entry-sub">{loc}</div>
                <ul class="entry-bullets">
                    {bullets_html}
                </ul>
            </div>
            """)
        exp_html = "".join(items)
    else:
        # Default experience block from profile
        exp_html = f"""
        <div class="entry">
            <div class="entry-header">
                <span class="entry-title"><strong>DevOps Engineer</strong> — Municipalidad de Berisso</span>
                <span class="entry-date">2023 - Present</span>
            </div>
            <div class="entry-sub">Buenos Aires, Argentina</div>
            <ul class="entry-bullets">
                <li>Designed and maintained automated CI/CD deployment pipelines using GitHub Actions and Forgejo Actions, increasing release reliability.</li>
                <li>Containerized application workloads using Docker and configured Nginx reverse proxies with automated SSL certificates.</li>
                <li>Administered Linux production servers, implemented monitoring and alerting with Nagios to ensure high availability.</li>
                <li>Managed cloud infrastructure and automation using AWS (EC2, EKS) and Terraform Infrastructure-as-Code.</li>
                <li>Developed automation scripts in PowerShell and Bash for system administration, backup routines, and routine maintenance.</li>
            </ul>
        </div>
        """

    # Education block
    degree = educ.get("degree", "Bachelor's")
    field = educ.get("field", "Information Systems")
    school = educ.get("school", "Facultad de Informática - UNLP")
    grad_year = educ.get("graduation_year", "2027")

    # Languages block
    lang_items = []
    for lang, level in languages.items():
        lang_items.append(f"{lang.capitalize()} ({level})")
    lang_str = ", ".join(lang_items) if lang_items else "Spanish (Native), English (Professional)"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{full_name} - Resume</title>
<style>
    @page {{
        size: A4;
        margin: 12mm 15mm;
    }}
    * {{
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        color: #1a202c;
        background: #ffffff;
        font-size: 10.5pt;
        line-height: 1.45;
    }}
    .header {{
        text-align: center;
        margin-bottom: 14px;
        padding-bottom: 8px;
        border-bottom: 1.5px solid #2b6cb0;
    }}
    .name {{
        font-size: 20pt;
        font-weight: 700;
        color: #1a365d;
        letter-spacing: 0.5px;
    }}
    .headline {{
        font-size: 11pt;
        font-weight: 600;
        color: #2b6cb0;
        margin-top: 3px;
    }}
    .contact {{
        font-size: 9pt;
        color: #4a5568;
        margin-top: 5px;
    }}
    .contact span {{
        margin: 0 4px;
    }}
    .section {{
        margin-top: 12px;
    }}
    .section-title {{
        font-size: 10.5pt;
        font-weight: 700;
        color: #2b6cb0;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        border-bottom: 1px solid #e2e8f0;
        padding-bottom: 3px;
        margin-bottom: 6px;
    }}
    .summary-text {{
        font-size: 10pt;
        color: #2d3748;
        text-align: justify;
    }}
    .entry {{
        margin-bottom: 10px;
    }}
    .entry-header {{
        display: flex;
        justify-content: space-between;
        font-size: 10.5pt;
    }}
    .entry-title {{
        color: #1a202c;
    }}
    .entry-date {{
        font-size: 9.5pt;
        color: #4a5568;
        font-weight: 500;
    }}
    .entry-sub {{
        font-size: 9pt;
        color: #718096;
        margin-bottom: 3px;
    }}
    .entry-bullets {{
        margin-left: 18px;
        margin-top: 3px;
    }}
    .entry-bullets li {{
        font-size: 9.5pt;
        color: #2d3748;
        margin-bottom: 2.5px;
        line-height: 1.38;
    }}
    .skills-block p {{
        font-size: 9.5pt;
        color: #2d3748;
        margin-bottom: 3px;
        line-height: 1.38;
    }}
    .education-entry {{
        display: flex;
        justify-content: space-between;
        font-size: 10pt;
    }}
</style>
</head>
<body>

<div class="header">
    <div class="name">{full_name}</div>
    <div class="headline">{headline}</div>
    <div class="contact">
        <span>📍 {location_str}</span> • 
        <span>✉️ {email}</span> • 
        <span>📞 {phone}</span> • 
        <span>🔗 {linkedin_url}</span> • 
        <span>💻 {github_url}</span>
    </div>
</div>

{f'''<div class="section">
    <div class="section-title">Professional Summary</div>
    <div class="summary-text">{summary}</div>
</div>''' if summary else ''}

<div class="section">
    <div class="section-title">Technical Skills</div>
    <div class="skills-block">
        {skills_html}
    </div>
</div>

<div class="section">
    <div class="section-title">Work Experience</div>
    {exp_html}
</div>

<div class="section">
    <div class="section-title">Education</div>
    <div class="education-entry">
        <span><strong>{degree} in {field}</strong> — {school}</span>
        <span class="entry-date">Expected {grad_year}</span>
    </div>
</div>

<div class="section">
    <div class="section-title">Languages</div>
    <p style="font-size: 9.5pt; color: #2d3748;">{lang_str}</p>
</div>

</body>
</html>"""
    return html


async def generate_tailored_pdf(
    job_id: str,
    job_title: str = "",
    tailored_headline: str = "",
    tailored_summary: str = "",
    highlighted_skills: list[str] | dict[str, list[str]] | None = None,
    custom_experience: list[dict[str, Any]] | None = None,
    output_dir: Path | None = None,
) -> str:
    """Generate and save a tailored PDF resume for a specific job.

    Args:
        job_id: Job ID used for naming output file.
        job_title: Target job title.
        tailored_headline: Headline tailored to the posting.
        tailored_summary: Professional summary tailored to match job requirements.
        highlighted_skills: Specific skills to highlight.
        custom_experience: Optional custom responsibilities tailored for the role.
        output_dir: Destination directory. Defaults to output/resumes.

    Returns:
        Absolute path to the created PDF file.
    """
    profile = load_profile()
    profile_data = profile.model_dump()

    html = render_ats_resume_html(
        profile_data=profile_data,
        job_title=job_title,
        tailored_headline=tailored_headline,
        tailored_summary=tailored_summary,
        highlighted_skills=highlighted_skills,
        custom_experience=custom_experience,
    )

    if output_dir is None:
        output_dir = PROJECT_ROOT / "output" / "resumes"
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_id = "".join(c for c in str(job_id) if c.isalnum() or c in ("-", "_"))
    pdf_path = output_dir / f"resume_{clean_id}.pdf"

    result = await html_to_pdf(html, str(pdf_path))
    if result.startswith("error"):
        raise RuntimeError(f"Failed to compile tailored PDF: {result}")

    logger.info("Tailored resume generated at {}", pdf_path)
    return str(pdf_path.resolve())
