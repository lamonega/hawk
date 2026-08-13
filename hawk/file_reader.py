"""File reader utility for importing profile data from user files."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def read_file(file_path: str) -> str:
    """Read a file and return its content as text.

    Supports: PDF, TXT, MD, YAML, JSON, CSV, and any text-based file.

    Args:
        file_path: Path to the file to read.

    Returns:
        The file content as a string, or an error message.
    """
    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        return f"error: File not found: {path}"

    if not path.is_file():
        return f"error: Not a file: {path}"

    suffix = path.suffix.lower()

    # PDF files
    if suffix == ".pdf":
        return _read_pdf(path)

    # Text-based files
    try:
        content = path.read_text(encoding="utf-8")
        # Cap at 30k chars to avoid overwhelming the agent
        if len(content) > 30000:
            content = content[:30000] + "\n\n... (truncated, file too long)"
        return content
    except UnicodeDecodeError:
        try:
            content = path.read_text(encoding="latin-1")
            if len(content) > 30000:
                content = content[:30000] + "\n\n... (truncated, file too long)"
            return content
        except Exception as e:
            return f"error: Cannot read file (encoding issue): {e}"
    except Exception as e:
        return f"error: {e}"


def _read_pdf(path: Path) -> str:
    """Extract text from a PDF file."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text_parts = []

        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

        content = "\n\n".join(text_parts)

        if not content.strip():
            return f"error: PDF has no extractable text (may be scanned/image-based): {path}"

        if len(content) > 30000:
            content = content[:30000] + "\n\n... (truncated, PDF too long)"

        return content
    except ImportError:
        return "error: pypdf not installed. Run: pip install pypdf"
    except Exception as e:
        return f"error reading PDF: {e}"


def list_profile_fields() -> str:
    """Return a structured list of all profile fields with their current values.

    Useful for the agent to know what to fill when importing from a file.
    """
    from hawk.profile import load_profile, check_profile_completeness

    profile = load_profile()
    completeness = check_profile_completeness(profile)

    fields = {
        "personal.first_name": profile.personal.first_name,
        "personal.last_name": profile.personal.last_name,
        "personal.email": profile.personal.email,
        "personal.phone": profile.personal.phone,
        "personal.city": profile.personal.city,
        "personal.state": profile.personal.state,
        "personal.country": profile.personal.country,
        "personal.postal_code": profile.personal.postal_code,
        "links.linkedin": profile.links.linkedin,
        "links.github": profile.links.github,
        "links.portfolio": profile.links.portfolio,
        "professional.headline": profile.professional.headline,
        "professional.summary": profile.professional.summary,
        "professional.years_of_experience": profile.professional.years_of_experience,
        "professional.current_title": profile.professional.current_title,
        "professional.current_company": profile.professional.current_company,
        "work_authorization.authorized": profile.work_authorization.authorized,
        "work_authorization.sponsorship_required": profile.work_authorization.sponsorship_required,
        "work_authorization.country": profile.work_authorization.country,
        "work_authorization.work_status": profile.work_authorization.work_status,
        "education.degree": profile.education.degree,
        "education.field": profile.education.field,
        "education.school": profile.education.school,
        "education.graduation_year": profile.education.graduation_year,
        "salary.current": profile.salary.current,
        "salary.expected": profile.salary.expected,
        "salary.currency": profile.salary.currency,
        "preferences.remote_only": profile.preferences.remote_only,
        "preferences.notice_period": profile.preferences.notice_period,
        "preferences.start_date": profile.preferences.start_date,
    }

    # Add skills
    for skill, level in profile.skills.items():
        fields[f"skills.{skill}"] = level

    # Add languages
    for lang, proficiency in profile.languages.items():
        fields[f"languages.{lang}"] = proficiency

    return fields
