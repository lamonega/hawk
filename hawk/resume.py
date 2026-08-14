"""ATS-optimized resume and cover letter generation using Jinja2 templates and Playwright PDF rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from hawk.browser import browser
from hawk.config import PROJECT_ROOT, RESUME_EXAMPLE_PATH, RESUME_PATH, _read_yaml, load_profile

# ── Constants ────────────────────────────────────────────────────────────────

TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "templates"
RESUMES_OUTPUT_DIR: Path = PROJECT_ROOT / "output" / "resumes"
COVER_LETTERS_OUTPUT_DIR: Path = PROJECT_ROOT / "output" / "cover_letters"

# Maximum number of skills to surface when building a fallback cover letter body
_TOP_SKILLS_COUNT: int = 4

SPANISH_LANG_CODES: frozenset[str] = frozenset({
    "es",
    "spa",
    "spanish",
    "español",
    "es-es",
    "es-la",
    "es-ar",
    "es-mx",
})

SPANISH_JOB_KEYWORDS: tuple[str, ...] = (
    "ingeniero",
    "desarrollador",
    "remoto",
    "sistemas",
    "empresa",
    "analista",
    "programador",
    "arquitecto",
    "licenciado",
    "administrador",
    "tecnico",
    "técnico",
    "consultor",
)

# ── Fallback Cover Letter Content & Salutations ──────────────────────────────
_SIGNOFF_ES: str = "Atentamente,"
_SIGNOFF_EN: str = "Sincerely,"

_SALUTATION_MANAGER_ES: str = "Estimado/a {name}:"
_SALUTATION_TEAM_ES: str = "Estimado equipo de {company}:"
_SALUTATION_GENERIC_ES: str = "Estimado/a responsable de selección:"

_SALUTATION_MANAGER_EN: str = "Dear {name},"
_SALUTATION_TEAM_EN: str = "Dear Hiring Team at {company},"
_SALUTATION_GENERIC_EN: str = "Dear Hiring Manager,"

_INTRO_COMPANY_ES: str = "Me dirijo a ustedes con gran interés en la posición de {job_title} en {company}."
_INTRO_GENERIC_ES: str = "Me dirijo a ustedes con gran interés en la posición de {job_title}."
_OUTRO_ES: str = (
    "Agradezco de antemano su tiempo y consideración. Quedo a su entera disposición "
    "para profundizar en mi trayectoria durante una entrevista."
)

_INTRO_COMPANY_EN: str = "I am writing to express my strong interest in the {job_title} role at {company}."
_INTRO_GENERIC_EN: str = "I am writing to express my strong interest in the {job_title} role."
_OUTRO_EN: str = (
    "Thank you for your time and consideration. I welcome the opportunity to discuss "
    "how my background can support your goals."
)

_BODY_HEADLINE_SKILLS_ES: str = "Con trayectoria como {headline} y competencias en {top_skills}, aporto experiencia práctica orientada a resultados."
_BODY_HEADLINE_ES: str = "Con trayectoria profesional como {headline}, aporto experiencia y enfoque analítico al equipo."
_BODY_SKILLS_ES: str = "Con competencias técnicas en {top_skills}, puedo aportar valor inmediato a los objetivos de su equipo."
_BODY_GENERIC_ES: str = "Cuento con formación y experiencia profesional alineadas con los requerimientos de la vacante."

_BODY_HEADLINE_SKILLS_EN: str = "With my background as {headline} and practical expertise in {top_skills}, I offer proven capabilities aligned with your needs."
_BODY_HEADLINE_EN: str = "With my background as {headline}, I bring dedicated problem-solving and professional commitment to your team."
_BODY_SKILLS_EN: str = "With demonstrated expertise in {top_skills}, I can deliver immediate value to your engineering initiatives."
_BODY_GENERIC_EN: str = "My professional background and skill set align with the qualifications outlined for this position."

_jinja_env: Environment = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_plain_text_resume(path: Path | None = None) -> dict[str, Any]:
    """Load plain_text_resume.yaml or plain_text_resume.example.yaml fallback.

    Args:
        path: Optional explicit path to resume YAML.

    Returns:
        Dictionary with parsed resume data.
    """
    target = path or (RESUME_PATH if RESUME_PATH.exists() else RESUME_EXAMPLE_PATH)
    return _read_yaml(target)


def detect_is_spanish(language: str = "auto", *text_samples: str) -> bool:
    """Detect whether target document language is Spanish.

    Args:
        language: Language code or 'auto'.
        *text_samples: Contextual text strings (job title, headline, company) to scan for keywords.

    Returns:
        True if document should be rendered in Spanish, False otherwise.
    """
    lang_clean = language.strip().lower()
    if lang_clean in SPANISH_LANG_CODES:
        return True
    if lang_clean not in ("auto", ""):
        return False
    combined = " ".join(t for t in text_samples if t).lower()
    return any(kw in combined for kw in SPANISH_JOB_KEYWORDS)


def _extract_contact_info(
    profile_data: dict[str, Any] | None = None,
    resume_data: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Extract unified candidate contact details from profile and resume dicts.

    Args:
        profile_data: Raw profile dictionary.
        resume_data: Raw plain text resume dictionary.

    Returns:
        Normalized dictionary with full_name, location, email, phone, linkedin, and github.
    """
    p = profile_data or {}
    r = resume_data or {}
    personal = r.get("personal_information") or p.get("personal") or {}

    first_name = personal.get("first_name") or personal.get("name", "")
    last_name = personal.get("last_name") or personal.get("surname", "")
    full_name = f"{first_name} {last_name}".strip()

    location = ", ".join(filter(None, [personal.get("city", ""), personal.get("country", "")]))

    links = p.get("links") or {}
    return {
        "full_name": full_name,
        "location": location,
        "email": personal.get("email", "") or "",
        "phone": personal.get("phone", "") or "",
        "linkedin": personal.get("linkedin") or links.get("linkedin", "") or "",
        "github": personal.get("github") or links.get("github", "") or "",
    }


def _extract_skills(
    highlighted_skills: list[str] | dict[str, list[str]] | None = None,
    profile_skills: dict[str, Any] | list[str] | None = None,
) -> list[str]:
    """Extract normalized skills list from highlights or factual profile skills.

    Args:
        highlighted_skills: Explicit skill list or categorized dictionary.
        profile_skills: Skills from candidate profile dictionary or list.

    Returns:
        List of formatted skill strings.
    """
    def _clean(items: list[Any]) -> list[str]:
        return [s for s in (str(i).strip() for i in items) if s]

    if highlighted_skills:
        if isinstance(highlighted_skills, list):
            return _clean(highlighted_skills)
        if isinstance(highlighted_skills, dict):
            flattened: list[str] = []
            for group in highlighted_skills.values():
                if isinstance(group, list):
                    flattened.extend(_clean(group))
                elif isinstance(group, str) and group.strip():
                    flattened.append(group.strip())
            return flattened

    if isinstance(profile_skills, dict):
        return [str(k).strip().capitalize() for k in profile_skills if str(k).strip()]
    if isinstance(profile_skills, list):
        return _clean(profile_skills)
    return []


def _select_cover_letter_body(
    summary: str,
    headline: str,
    top_skills: str,
    is_es: bool,
) -> str:
    """Select the most informative body sentence for a fallback cover letter.

    Priority: profile summary > headline + skills > headline only > skills only > generic fallback.

    Args:
        summary: Candidate professional summary.
        headline: Candidate professional headline.
        top_skills: Comma-separated top skills string.
        is_es: Whether the output language is Spanish.

    Returns:
        A single body paragraph string.
    """
    if summary:
        return summary
    if is_es:
        if headline and top_skills:
            return _BODY_HEADLINE_SKILLS_ES.format(headline=headline, top_skills=top_skills)
        if headline:
            return _BODY_HEADLINE_ES.format(headline=headline)
        if top_skills:
            return _BODY_SKILLS_ES.format(top_skills=top_skills)
        return _BODY_GENERIC_ES
    else:
        if headline and top_skills:
            return _BODY_HEADLINE_SKILLS_EN.format(headline=headline, top_skills=top_skills)
        if headline:
            return _BODY_HEADLINE_EN.format(headline=headline)
        if top_skills:
            return _BODY_SKILLS_EN.format(top_skills=top_skills)
        return _BODY_GENERIC_EN


def _build_cover_letter_paragraphs(
    tailored_body_paragraphs: list[str] | str | None,
    profile_data: dict[str, Any],
    job_title: str,
    company: str,
    is_es: bool,
) -> list[str]:
    """Construct cover letter paragraphs grounded strictly in candidate profile facts.

    If agent-provided paragraphs are supplied they are used directly; otherwise a
    minimal but accurate fallback is built from profile data.

    Args:
        tailored_body_paragraphs: Agent-provided paragraphs (list or double-newline separated string).
        profile_data: Candidate profile dictionary.
        job_title: Target job title.
        company: Target hiring company.
        is_es: Whether the letter is in Spanish.

    Returns:
        List of body paragraph strings.
    """
    if isinstance(tailored_body_paragraphs, str) and tailored_body_paragraphs.strip():
        return [p.strip() for p in tailored_body_paragraphs.split("\n\n") if p.strip()]
    if isinstance(tailored_body_paragraphs, list) and tailored_body_paragraphs:
        return [str(p).strip() for p in tailored_body_paragraphs if str(p).strip()]

    prof = profile_data.get("professional", {})
    summary = str(prof.get("summary", "")).strip()
    headline = str(prof.get("headline", "")).strip()
    skills_raw = profile_data.get("skills", {})
    skill_keys = list(skills_raw.keys()) if isinstance(skills_raw, dict) else list(skills_raw)
    top_skills = ", ".join(s for s in (str(k).strip() for k in skill_keys[:_TOP_SKILLS_COUNT]) if s)

    if is_es:
        intro = (
            _INTRO_COMPANY_ES.format(job_title=job_title, company=company)
            if company
            else _INTRO_GENERIC_ES.format(job_title=job_title)
        )
        outro = _OUTRO_ES
    else:
        intro = (
            _INTRO_COMPANY_EN.format(job_title=job_title, company=company)
            if company
            else _INTRO_GENERIC_EN.format(job_title=job_title)
        )
        outro = _OUTRO_EN

    body = _select_cover_letter_body(summary, headline, top_skills, is_es)
    return [intro, body, outro]


def _build_salutation(hiring_manager: str, company: str, is_es: bool) -> str:
    """Construct an appropriate salutation line for a cover letter.

    Args:
        hiring_manager: Optional hiring manager name.
        company: Target company name.
        is_es: Whether the output language is Spanish.

    Returns:
        Formatted salutation string.
    """
    if is_es:
        if hiring_manager:
            return _SALUTATION_MANAGER_ES.format(name=hiring_manager)
        return _SALUTATION_TEAM_ES.format(company=company) if company else _SALUTATION_GENERIC_ES
    else:
        if hiring_manager:
            return _SALUTATION_MANAGER_EN.format(name=hiring_manager)
        return _SALUTATION_TEAM_EN.format(company=company) if company else _SALUTATION_GENERIC_EN


# ── HTML Renderers ───────────────────────────────────────────────────────────

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
    """Render ATS-compliant resume HTML from profile data and tailored inputs.

    Args:
        profile_data: Optional candidate profile dict (defaults to loaded profile).
        resume_data: Optional plain text resume dict (defaults to loaded resume).
        job_title: Target job title.
        tailored_headline: Tailored professional headline.
        tailored_summary: Tailored professional summary narrative.
        highlighted_skills: List or dictionary of highlighted skills for the role.
        custom_experience: Optional customized experience entries.
        language: Language code ('en', 'es', or 'auto').

    Returns:
        Rendered HTML string.
    """
    p = profile_data or load_profile().model_dump()
    r = resume_data or load_plain_text_resume()

    contact = _extract_contact_info(profile_data=p, resume_data=r)
    skills = _extract_skills(highlighted_skills=highlighted_skills, profile_skills=p.get("skills"))

    exp = custom_experience or r.get("experience_details") or p.get("experience") or []
    # education_details from resume takes precedence; fall back to single-entry profile education
    edu = r.get("education_details") or ([p["education"]] if p.get("education") else [])

    is_es = detect_is_spanish(language, job_title, tailored_headline)
    lang_code = "es" if is_es else "en"
    prof = p.get("professional", {})

    template = _jinja_env.get_template("resume.html")
    return template.render(
        language=lang_code,
        is_es=is_es,
        full_name=contact["full_name"],
        headline=tailored_headline or prof.get("headline") or job_title,
        location=contact["location"],
        email=contact["email"],
        phone=contact["phone"],
        linkedin=contact["linkedin"],
        github=contact["github"],
        summary=tailored_summary or prof.get("summary", ""),
        skills=skills,
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
    """Render ATS-compliant cover letter HTML.

    Args:
        profile_data: Optional candidate profile dict (defaults to loaded profile).
        job_title: Target job title.
        company: Target hiring company name.
        hiring_manager: Optional name of the hiring manager.
        tailored_body_paragraphs: Custom paragraphs (list or double-newline separated string).
        language: Language code ('en', 'es', or 'auto').

    Returns:
        Rendered HTML string.
    """
    p = profile_data or load_profile().model_dump()
    contact = _extract_contact_info(profile_data=p)
    is_es = detect_is_spanish(language, job_title, company)
    lang_code = "es" if is_es else "en"

    paragraphs = _build_cover_letter_paragraphs(
        tailored_body_paragraphs=tailored_body_paragraphs,
        profile_data=p,
        job_title=job_title,
        company=company,
        is_es=is_es,
    )

    template = _jinja_env.get_template("cover_letter.html")
    return template.render(
        language=lang_code,
        full_name=contact["full_name"],
        headline=p.get("professional", {}).get("headline", ""),
        location=contact["location"],
        email=contact["email"],
        phone=contact["phone"],
        linkedin=contact["linkedin"],
        github=contact["github"],
        company=company,
        job_title=job_title,
        hiring_manager=hiring_manager,
        salutation=_build_salutation(hiring_manager, company, is_es),
        paragraphs=paragraphs,
        signoff_text=_SIGNOFF_ES if is_es else _SIGNOFF_EN,
    )


# ── PDF Generators ───────────────────────────────────────────────────────────

async def _render_doc_pdf(html: str, out_path: Path) -> str:
    """Render an HTML string to a PDF file via the browser singleton.

    Args:
        html: Rendered HTML string.
        out_path: Absolute destination path for the PDF file.

    Returns:
        Absolute string path to the rendered PDF file.
    """
    return await browser.render_pdf(html, str(out_path))

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
    """Generate ATS PDF resume and save to output/resumes/resume_{job_id}.pdf.

    Args:
        job_id: LinkedIn or target job identifier.
        job_title: Target job title.
        tailored_headline: Tailored headline for candidate header.
        tailored_summary: Tailored professional summary narrative.
        highlighted_skills: List of highlighted skills for this application.
        custom_experience: Custom experience entries.
        language: Target document language ('en', 'es', or 'auto').
        output_dir: Optional custom output directory.

    Returns:
        Absolute string path to rendered PDF file.
    """
    out_path = (output_dir or RESUMES_OUTPUT_DIR) / f"resume_{job_id}.pdf"
    html = render_ats_resume_html(
        job_title=job_title,
        tailored_headline=tailored_headline,
        tailored_summary=tailored_summary,
        highlighted_skills=highlighted_skills,
        custom_experience=custom_experience,
        language=language,
    )
    return await _render_doc_pdf(html, out_path)


async def generate_tailored_cover_letter(
    job_id: str,
    job_title: str,
    company: str,
    hiring_manager: str = "",
    tailored_body: list[str] | str | None = None,
    language: str = "auto",
    output_dir: Path | None = None,
) -> str:
    """Generate ATS PDF cover letter and save to output/cover_letters/cover_letter_{job_id}.pdf.

    Args:
        job_id: LinkedIn or target job identifier.
        job_title: Target job title.
        company: Target hiring company name.
        hiring_manager: Optional hiring manager name.
        tailored_body: Paragraph list or raw body text.
        language: Target document language ('en', 'es', or 'auto').
        output_dir: Optional custom output directory.

    Returns:
        Absolute string path to rendered PDF file.
    """
    out_path = (output_dir or COVER_LETTERS_OUTPUT_DIR) / f"cover_letter_{job_id}.pdf"
    html = render_ats_cover_letter_html(
        job_title=job_title,
        company=company,
        hiring_manager=hiring_manager,
        tailored_body_paragraphs=tailored_body,
        language=language,
    )
    return await _render_doc_pdf(html, out_path)
