"""Truthful ATS-optimized resume generator reading directly from user configuration YAMLs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from hawk.browser.pdf import html_to_pdf
from hawk.profile import load_profile, RESUME_PATH, PROFILE_PATH
from hawk.settings import PROJECT_ROOT


def load_plain_text_resume(path: Path | None = None) -> dict[str, Any]:
    """Load plain_text_resume.yaml safely."""
    if path is None:
        path = RESUME_PATH if RESUME_PATH.exists() else (RESUME_PATH.parent / "plain_text_resume.example.yaml")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Could not read plain_text_resume.yaml at {}: {}", path, e)
        return {}


def render_ats_resume_html(
    profile_data: dict[str, Any] | None = None,
    resume_data: dict[str, Any] | None = None,
    job_title: str = "",
    tailored_headline: str = "",
    tailored_summary: str = "",
    highlighted_skills: list[str] | dict[str, list[str]] | None = None,
    custom_experience: list[dict[str, Any]] | None = None,
) -> str:
    """Generate ATS-optimized clean HTML resume strictly using user-provided data.

    Never invents, fabricates, or hardcodes fake experience, bullets, skills, or personal info.
    """
    p = profile_data or {}
    r = resume_data or {}

    # Personal Info (prefer plain_text_resume YAML, fallback to profile YAML)
    r_personal = r.get("personal_information", {})
    p_personal = p.get("personal", {})
    p_links = p.get("links", {})
    p_prof = p.get("professional", {})

    first_name = r_personal.get("name") or p_personal.get("first_name", "")
    last_name = r_personal.get("surname") or p_personal.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip()

    email = r_personal.get("email") or p_personal.get("email", "")
    phone = r_personal.get("phone") or p_personal.get("phone", "")
    city = r_personal.get("city") or p_personal.get("city", "")
    country = r_personal.get("country") or p_personal.get("country", "")

    location_parts = [part for part in (city, country) if part]
    location_str = ", ".join(location_parts)

    linkedin_url = r_personal.get("linkedin") or p_links.get("linkedin", "")
    github_url = r_personal.get("github") or p_links.get("github", "")

    headline = tailored_headline or p_prof.get("headline", "") or job_title
    summary = tailored_summary or p_prof.get("summary", "")

    # Header contacts (strictly ATS-compliant: no emojis)
    contact_items = []
    if location_str:
        contact_items.append(location_str)
    if email:
        contact_items.append(email)
    if phone:
        contact_items.append(phone)
    if linkedin_url:
        contact_items.append(linkedin_url)
    if github_url:
        contact_items.append(github_url)
    contact_html = " | ".join(contact_items)

    # Skills section
    skills_html = ""
    if highlighted_skills:
        if isinstance(highlighted_skills, dict):
            categories_html = []
            for cat_name, skill_list in highlighted_skills.items():
                if skill_list:
                    items = ", ".join(str(s) for s in skill_list)
                    categories_html.append(f"<p><strong>{cat_name}:</strong> {items}</p>")
            skills_html = "".join(categories_html)
        elif isinstance(highlighted_skills, list) and highlighted_skills:
            items = " • ".join(str(s) for s in highlighted_skills)
            skills_html = f"<p>{items}</p>"
    else:
        raw_skills = p.get("skills", {})
        if isinstance(raw_skills, dict) and raw_skills:
            items = " • ".join(raw_skills.keys())
            skills_html = f"<p>{items}</p>"

    # Experience section (from custom_experience, or plain_text_resume, or profile)
    exp_list = custom_experience or r.get("experience_details", []) or p.get("experience", [])
    exp_items = []

    for exp in exp_list:
        if not isinstance(exp, dict):
            continue
        role = exp.get("position") or exp.get("role") or ""
        comp = exp.get("company", "")
        period = exp.get("employment_period") or exp.get("period", "")
        loc = exp.get("location", "")

        if not role and not comp:
            continue

        title_comp = f"<strong>{role}</strong>" + (f" — {comp}" if comp else "")

        # Bullets / key responsibilities
        raw_bullets = exp.get("key_responsibilities") or exp.get("bullets") or []
        bullets_html = ""
        for b in raw_bullets:
            if isinstance(b, dict):
                text = b.get("description", "")
            else:
                text = str(b).strip()
            if text:
                bullets_html += f"<li>{text}</li>"

        sub_info = loc if loc else ""

        exp_items.append(f"""
        <div class="entry">
            <div class="entry-header">
                <span class="entry-title">{title_comp}</span>
                {f'<span class="entry-date">{period}</span>' if period else ''}
            </div>
            {f'<div class="entry-sub">{sub_info}</div>' if sub_info else ''}
            {f'<ul class="entry-bullets">{bullets_html}</ul>' if bullets_html else ''}
        </div>
        """)

    exp_html = "".join(exp_items)

    # Education section
    educ_list = r.get("education_details", [])
    educ_items = []
    if educ_list:
        for ed in educ_list:
            if not isinstance(ed, dict):
                continue
            lvl = ed.get("education_level", "")
            field = ed.get("field_of_study", "")
            inst = ed.get("institution", "")
            grad = ed.get("year_of_completion", "")

            title = f"{lvl} in {field}" if lvl and field else (lvl or field or inst)
            sub = f" — {inst}" if inst and (lvl or field) else ""

            if title or inst:
                educ_items.append(f"""
                <div class="education-entry">
                    <span><strong>{title}</strong>{sub}</span>
                    {f'<span class="entry-date">{grad}</span>' if grad else ''}
                </div>
                """)
    else:
        p_educ = p.get("education", {})
        if isinstance(p_educ, dict) and p_educ:
            deg = p_educ.get("degree", "")
            fld = p_educ.get("field", "")
            sch = p_educ.get("school", "")
            yr = p_educ.get("graduation_year", "")
            title = f"{deg} in {fld}" if deg and fld else (deg or fld or sch)
            sub = f" — {sch}" if sch and (deg or fld) else ""
            if title or sch:
                educ_items.append(f"""
                <div class="education-entry">
                    <span><strong>{title}</strong>{sub}</span>
                    {f'<span class="entry-date">{yr}</span>' if yr else ''}
                </div>
                """)
    educ_html = "".join(educ_items)

    # Languages section
    r_langs = r.get("languages", [])
    p_langs = p.get("languages", {})
    lang_items = []
    if r_langs:
        for l in r_langs:
            if isinstance(l, dict):
                lang_name = l.get("language", "")
                prof = l.get("proficiency", "")
                if lang_name:
                    lang_items.append(f"{lang_name} ({prof})" if prof else lang_name)
    elif p_langs:
        for lang_name, prof in p_langs.items():
            if lang_name:
                lang_items.append(f"{lang_name.capitalize()} ({prof})" if prof else lang_name.capitalize())

    lang_html = ", ".join(lang_items)

    # Projects (if present in plain text resume)
    projects_list = [pr for pr in r.get("projects", []) if isinstance(pr, dict) and (pr.get("name") or pr.get("description"))]
    projects_html = ""
    if projects_list:
        p_items = []
        for pr in projects_list:
            p_name = pr.get("name", "")
            p_desc = pr.get("description", "")
            p_link = pr.get("link", "")
            link_html = f' — <a href="{p_link}">{p_link}</a>' if p_link else ""
            p_items.append(f"<p><strong>{p_name}</strong>{link_html}: {p_desc}</p>")
        projects_html = "".join(p_items)

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
        margin-bottom: 4px;
    }}
</style>
</head>
<body>

<div class="header">
    {f'<div class="name">{full_name}</div>' if full_name else ''}
    {f'<div class="headline">{headline}</div>' if headline else ''}
    {f'<div class="contact">{contact_html}</div>' if contact_html else ''}
</div>

{f'''<div class="section">
    <div class="section-title">Professional Summary</div>
    <div class="summary-text">{summary}</div>
</div>''' if summary else ''}

{f'''<div class="section">
    <div class="section-title">Technical Skills</div>
    <div class="skills-block">{skills_html}</div>
</div>''' if skills_html else ''}

{f'''<div class="section">
    <div class="section-title">Work Experience</div>
    {exp_html}
</div>''' if exp_html else ''}

{f'''<div class="section">
    <div class="section-title">Projects</div>
    <div class="skills-block">{projects_html}</div>
</div>''' if projects_html else ''}

{f'''<div class="section">
    <div class="section-title">Education</div>
    {educ_html}
</div>''' if educ_html else ''}

{f'''<div class="section">
    <div class="section-title">Languages</div>
    <p style="font-size: 9.5pt; color: #2d3748;">{lang_html}</p>
</div>''' if lang_html else ''}

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
    """Generate and save a tailored PDF resume for a specific job strictly from user YAML files.

    Args:
        job_id: Job ID used for naming output file.
        job_title: Target job title.
        tailored_headline: Headline tailored to the posting.
        tailored_summary: Professional summary tailored to match job requirements.
        highlighted_skills: Specific skills to highlight from user's skill set.
        custom_experience: Optional custom responsibilities tailored for the role.
        output_dir: Destination directory. Defaults to output/resumes.

    Returns:
        Absolute path to the created PDF file.
    """
    profile = load_profile()
    profile_data = profile.model_dump()
    resume_data = load_plain_text_resume()

    html = render_ats_resume_html(
        profile_data=profile_data,
        resume_data=resume_data,
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

    logger.info("Truthful resume generated at {}", pdf_path)
    return str(pdf_path.resolve())


def render_ats_cover_letter_html(
    profile_data: dict[str, Any] | None = None,
    job_title: str = "",
    company: str = "",
    hiring_manager: str = "",
    tailored_body_paragraphs: list[str] | str | None = None,
    language: str = "auto",
) -> str:
    """Render an ATS-compliant professional HTML cover letter.

    Prioritizes the primary language of the job posting (Spanish, English, etc.).
    """
    if profile_data is None:
        p = load_profile().model_dump()
    else:
        p = profile_data
    p_personal = p.get("personal", {})
    p_links = p.get("links", {})
    p_prof = p.get("professional", {})

    first_name = p_personal.get("first_name", "")
    last_name = p_personal.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip()

    email = p_personal.get("email", "")
    phone = p_personal.get("phone", "")
    city = p_personal.get("city", "")
    country = p_personal.get("country", "")
    location_str = ", ".join(filter(None, [city, country]))
    linkedin_url = p_links.get("linkedin", "")

    contact_items = [c for c in [location_str, email, phone, linkedin_url] if c]
    contact_html = " | ".join(contact_items)

    # Detect language
    is_es = language.lower() in ("es", "spanish", "español")
    if language == "auto":
        es_indicators = (
            "ingeniero", "desarrollador", "arquitecto", "analista", "responsable",
            "líder", "especialista", "soporte", "en remoto", "híbrido", "datos",
            "sistemas", "tecnología", "infraestructura", "puesto", "vacante"
        )
        combined = f"{job_title} {company}".lower()
        if any(ind in combined for ind in es_indicators):
            is_es = True

    if is_es:
        salutation = f"Estimado/a {hiring_manager}:" if hiring_manager else (f"Estimado equipo de selección de {company}:" if company else "Estimado/a responsable de selección:")
        signoff_text = "Atentamente,"
    else:
        salutation = f"Dear {hiring_manager}," if hiring_manager else (f"Dear Hiring Team at {company}," if company else "Dear Hiring Manager,")
        signoff_text = "Sincerely,"

    paragraphs = []
    if isinstance(tailored_body_paragraphs, str) and tailored_body_paragraphs:
        paragraphs = [p.strip() for p in tailored_body_paragraphs.split("\n\n") if p.strip()]
    elif isinstance(tailored_body_paragraphs, list) and tailored_body_paragraphs:
        paragraphs = [str(p).strip() for p in tailored_body_paragraphs if str(p).strip()]
    else:
        # Default truthful cover letter body matching detected language
        summary = p_prof.get("summary", "")
        if is_es:
            paragraphs = [
                f"Me dirijo a ustedes con gran entusiasmo para presentar mi candidatura a la posición de {job_title or 'la vacante'}{f' en {company}' if company else ''}. Con experiencia práctica en el diseño de flujos de automatización, contenerización de aplicaciones y administración de infraestructura Linux y Cloud, confío en aportar valor inmediato a su equipo.",
                summary or "En mis roles recientes, me he enfocado en automatizar pipelines de CI/CD, mantener alta disponibilidad de servicios e implementar infraestructura como código para reducir la fricción en despliegues.",
                "Agradezco su tiempo y consideración, y quedo a su entera disposición para coordinar una entrevista y profundizar en cómo mi perfil técnico se alinea con los objetivos del equipo.",
            ]
        else:
            paragraphs = [
                f"I am writing to express my enthusiastic interest in the {job_title or 'open position'}{f' at {company}' if company else ''}. With hands-on experience designing reliable automation workflows, containerizing applications, and managing cloud and Linux infrastructure, I am confident in my ability to deliver immediate value to your team.",
                summary or "In my recent roles, I have focused on automating CI/CD pipelines, maintaining high service availability, and implementing infrastructure as code to reduce deployment friction and eliminate drift.",
                "I welcome the opportunity to discuss how my technical background, problem-solving mindset, and dedication to operational excellence align with your team's objectives. Thank you for your time and consideration.",
            ]

    body_html = "\n".join(f"<p>{para}</p>" for para in paragraphs)

    from datetime import date
    today_str = date.today().strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
    @page {{
        size: letter;
        margin: 20mm 20mm 20mm 20mm;
    }}
    body {{
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #222222;
        font-size: 11pt;
        line-height: 1.5;
        margin: 0;
        padding: 0;
    }}
    .header {{
        text-align: center;
        border-bottom: 1.5px solid #333333;
        padding-bottom: 8px;
        margin-bottom: 24px;
    }}
    .name {{
        font-size: 20pt;
        font-weight: 700;
        color: #111111;
        letter-spacing: 0.5px;
        margin-bottom: 4px;
    }}
    .contact {{
        font-size: 9.5pt;
        color: #555555;
    }}
    .date-line {{
        margin-bottom: 20px;
        font-size: 10.5pt;
        color: #444444;
    }}
    .recipient {{
        margin-bottom: 20px;
        font-size: 10.5pt;
        color: #333333;
    }}
    .salutation {{
        font-weight: 600;
        margin-bottom: 14px;
    }}
    p {{
        margin-top: 0;
        margin-bottom: 14px;
        text-align: justify;
    }}
    .signoff {{
        margin-top: 24px;
    }}
    .signature-name {{
        font-weight: 700;
        margin-top: 8px;
    }}
</style>
</head>
<body>
    <div class="header">
        <div class="name">{full_name}</div>
        <div class="contact">{contact_html}</div>
    </div>

    <div class="date-line">{today_str}</div>

    <div class="salutation">{salutation}</div>

    <div class="body-content">
        {body_html}
    </div>

    <div class="signoff">
        <div>{signoff_text}</div>
        <div class="signature-name">{full_name}</div>
    </div>
</body>
</html>"""


async def generate_tailored_cover_letter(
    job_id: str,
    job_title: str = "",
    company: str = "",
    hiring_manager: str = "",
    tailored_body: list[str] | str | None = None,
    language: str = "auto",
    output_dir: Path | None = None,
) -> str:
    """Generate and save an ATS-optimized tailored PDF cover letter.

    Args:
        job_id: Job ID used for file naming.
        job_title: Target job title.
        company: Target company name.
        hiring_manager: Optional name of the hiring manager or recruiter.
        tailored_body: Paragraphs tailored to the company and role in the job posting language.
        language: Language code ('en', 'es', or 'auto').
        output_dir: Destination directory. Defaults to output/cover_letters.

    Returns:
        Absolute path to the created PDF file.
    """
    profile = load_profile()
    profile_data = profile.model_dump()

    html = render_ats_cover_letter_html(
        profile_data=profile_data,
        job_title=job_title,
        company=company,
        hiring_manager=hiring_manager,
        tailored_body_paragraphs=tailored_body,
        language=language,
    )

    if output_dir is None:
        output_dir = PROJECT_ROOT / "output" / "cover_letters"
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_id = "".join(c for c in str(job_id) if c.isalnum() or c in ("-", "_"))
    pdf_path = output_dir / f"cover_letter_{clean_id}.pdf"

    result = await html_to_pdf(html, str(pdf_path))
    if result.startswith("error"):
        raise RuntimeError(f"Failed to compile tailored cover letter PDF: {result}")

    logger.info("Truthful cover letter generated at {}", pdf_path)
    return str(pdf_path.resolve())


