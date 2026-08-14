"""ATS-optimized resume and cover letter generation using Jinja2 templates and Playwright PDF rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from hawk.browser import browser
from hawk.config import PROJECT_ROOT, UserProfile, load_profile, _read_yaml, RESUME_PATH, RESUME_EXAMPLE_PATH

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def load_plain_text_resume(path: Path | None = None) -> dict[str, Any]:
    """Load plain_text_resume.yaml or plain_text_resume.example.yaml."""
    target = path or (RESUME_PATH if RESUME_PATH.exists() else RESUME_EXAMPLE_PATH)
    return _read_yaml(target)


def render_ats_resume_html(
    profile_data: dict[str, Any] | None = None,
    resume_data: dict[str, Any] | None = None,
    job_title: str = "",
    tailored_headline: str = "",
    tailored_summary: str = "",
    highlighted_skills: list[str] | dict[str, list[str]] | None = None,
    custom_experience: list[dict[str, Any]] | None = None,
    language: str = "auto",
) -> str:
    """Render ATS resume HTML from profile and tailored inputs."""
    p = profile_data or load_profile().model_dump()
    r = resume_data or load_plain_text_resume()

    personal = r.get("personal_information") or p.get("personal") or {}
    first_name = personal.get("name") or personal.get("first_name", "")
    last_name = personal.get("surname") or personal.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip()

    loc_parts = [personal.get("city", ""), personal.get("country", "")]
    location = ", ".join(filter(None, loc_parts))

    links = p.get("links") or {}
    linkedin = personal.get("linkedin") or links.get("linkedin", "")
    github = personal.get("github") or links.get("github", "")

    skills_list = []
    if highlighted_skills:
        if isinstance(highlighted_skills, list):
            skills_list = highlighted_skills
        elif isinstance(highlighted_skills, dict):
            for sks in highlighted_skills.values():
                skills_list.extend(sks)
    elif p.get("skills"):
        skills_list = [k.capitalize() for k in p["skills"].keys()]

    exp = custom_experience or r.get("experience_details") or p.get("experience") or []
    edu = r.get("education_details") or ([p["education"]] if p.get("education") else [])

    is_es = language.lower() in ("es", "spanish", "español") or any(
        w in f"{job_title} {tailored_headline}".lower() for w in ("ingeniero", "desarrollador", "remoto", "sistemas")
    )

    template = _jinja_env.get_template("resume.html")
    return template.render(
        language="es" if is_es else "en",
        is_es=is_es,
        full_name=full_name,
        headline=tailored_headline or p.get("professional", {}).get("headline") or job_title,
        location=location,
        email=personal.get("email", ""),
        phone=personal.get("phone", ""),
        linkedin=linkedin,
        github=github,
        summary=tailored_summary or p.get("professional", {}).get("summary", ""),
        skills=skills_list,
        experience=exp,
        education=edu,
    )


def render_ats_cover_letter_html(
    profile_data: dict[str, Any] | None = None,
    job_title: str = "",
    company: str = "",
    hiring_manager: str = "",
    tailored_body_paragraphs: list[str] | str | None = None,
    language: str = "auto",
) -> str:
    """Render ATS cover letter HTML."""
    p = profile_data or load_profile().model_dump()
    personal = p.get("personal", {})
    full_name = f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()

    loc_parts = [personal.get("city", ""), personal.get("country", "")]
    location = ", ".join(filter(None, loc_parts))

    is_es = language.lower() in ("es", "spanish", "español") or any(
        w in f"{job_title} {company}".lower() for w in ("ingeniero", "desarrollador", "remoto", "sistemas", "empresa")
    )

    if is_es:
        salutation = f"Estimado/a {hiring_manager}:" if hiring_manager else (f"Estimado equipo de {company}:" if company else "Estimado/a responsable de selección:")
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
        if is_es:
            paragraphs = [
                f"Me dirijo a ustedes con gran interés en la posición de {job_title} en {company}.",
                f"Con mi experiencia en DevOps, automatización de CI/CD y gestión de infraestructura en la nube, puedo aportar valor inmediato a los objetivos de su equipo.",
                "Agradezco su consideración y quedo a disposición para conversar sobre cómo mi perfil se alinea con sus necesidades.",
            ]
        else:
            paragraphs = [
                f"I am writing to express my strong interest in the {job_title} role at {company}.",
                f"With my background in DevOps, CI/CD pipeline automation, and cloud infrastructure, I can deliver immediate value to your team's initiatives.",
                "Thank you for your time and consideration. I look forward to discussing how my experience aligns with your goals.",
            ]

    template = _jinja_env.get_template("cover_letter.html")
    return template.render(
        language="es" if is_es else "en",
        full_name=full_name,
        headline=p.get("professional", {}).get("headline", ""),
        location=location,
        email=personal.get("email", ""),
        phone=personal.get("phone", ""),
        linkedin=p.get("links", {}).get("linkedin", ""),
        company=company,
        job_title=job_title,
        hiring_manager=hiring_manager,
        salutation=salutation,
        paragraphs=paragraphs,
        signoff_text=signoff_text,
    )


async def generate_tailored_pdf(
    job_id: str,
    job_title: str,
    tailored_headline: str = "",
    tailored_summary: str = "",
    highlighted_skills: list[str] | None = None,
    custom_experience: list[dict[str, Any]] | None = None,
    language: str = "auto",
    output_dir: Path | None = None,
) -> str:
    """Generate ATS PDF resume and save to output/resumes/resume_{job_id}.pdf."""
    out_dir = output_dir or (PROJECT_ROOT / "output" / "resumes")
    out_path = out_dir / f"resume_{job_id}.pdf"

    html = render_ats_resume_html(
        job_title=job_title,
        tailored_headline=tailored_headline,
        tailored_summary=tailored_summary,
        highlighted_skills=highlighted_skills,
        custom_experience=custom_experience,
        language=language,
    )
    return await browser.render_pdf(html, str(out_path))


async def generate_tailored_cover_letter(
    job_id: str,
    job_title: str,
    company: str,
    hiring_manager: str = "",
    tailored_body: list[str] | str | None = None,
    language: str = "auto",
    output_dir: Path | None = None,
) -> str:
    """Generate ATS PDF cover letter and save to output/cover_letters/cover_letter_{job_id}.pdf."""
    out_dir = output_dir or (PROJECT_ROOT / "output" / "cover_letters")
    out_path = out_dir / f"cover_letter_{job_id}.pdf"

    html = render_ats_cover_letter_html(
        job_title=job_title,
        company=company,
        hiring_manager=hiring_manager,
        tailored_body_paragraphs=tailored_body,
        language=language,
    )
    return await browser.render_pdf(html, str(out_path))
