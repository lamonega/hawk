"""User profile for auto-filling LinkedIn Easy Apply forms."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, Field

PROFILE_PATH = Path(__file__).resolve().parent.parent / "config" / "profile.yaml"

# Fields the agent MUST ask about if empty
REQUIRED_FIELDS = {
    "personal.first_name": "What is your first name?",
    "personal.last_name": "What is your last name?",
    "personal.email": "What is your email address?",
    "personal.phone": "What is your phone number?",
    "personal.city": "What city do you live in?",
    "personal.country": "What country do you live in?",
    "work_authorization.work_status": "What is your work authorization status? (e.g. US Citizen, Green Card, H1B, OPT, No authorization)",
    "education.degree": "What is your highest education level? (e.g. Bachelor's, Master's, PhD)",
    "education.field": "What did you study? (e.g. Computer Science)",
    "education.school": "What university/school did you attend?",
    "professional.years_of_experience": "How many years of experience do you have?",
}

# Fields that are nice to have but not critical
OPTIONAL_FIELDS = {
    "personal.state": "What state/province do you live in?",
    "personal.postal_code": "What is your postal/zip code?",
    "links.linkedin": "What is your LinkedIn profile URL?",
    "links.github": "What is your GitHub profile URL?",
    "professional.headline": "What is your professional headline? (e.g. Senior Software Engineer)",
    "professional.summary": "Write a brief professional summary.",
    "professional.current_title": "What is your current job title?",
    "professional.current_company": "What company do you currently work at?",
    "education.graduation_year": "What year did you graduate?",
    "salary.expected": "What is your expected salary?",
    "salary.currency": "What currency? (e.g. USD, EUR, ARS)",
    "work_authorization.country": "In which country are you authorized to work?",
}


class PersonalInfo(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    postal_code: str = ""


class Links(BaseModel):
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    website: str = ""


class ProfessionalInfo(BaseModel):
    headline: str = ""
    summary: str = ""
    years_of_experience: str = ""
    current_title: str = ""
    current_company: str = ""


class WorkAuthorization(BaseModel):
    authorized: bool = True
    sponsorship_required: bool = False
    country: str = ""
    work_status: str = ""


class Education(BaseModel):
    degree: str = ""
    field: str = ""
    school: str = ""
    graduation_year: str = ""


class Salary(BaseModel):
    current: str = ""
    expected: str = ""
    currency: str = "USD"
    negotiable: bool = True


class Preferences(BaseModel):
    remote_only: bool = True
    min_salary: str = ""
    notice_period: str = "2 weeks"
    start_date: str = "Immediately"


class UserProfile(BaseModel):
    completed_at: str = ""
    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    links: Links = Field(default_factory=Links)
    professional: ProfessionalInfo = Field(default_factory=ProfessionalInfo)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    education: Education = Field(default_factory=Education)
    skills: dict[str, int] = Field(default_factory=dict)
    experience: list[dict[str, str]] = Field(default_factory=list)
    salary: Salary = Field(default_factory=Salary)
    languages: dict[str, str] = Field(default_factory=dict)
    preferences: Preferences = Field(default_factory=Preferences)
    common_answers: dict[str, str] = Field(default_factory=dict)


def load_profile(path: Path | None = None) -> UserProfile:
    """Load user profile from YAML."""
    path = path or PROFILE_PATH
    if not path.exists():
        logger.warning("Profile not found at {}, using empty profile", path)
        return UserProfile()

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # YAML returns None for commented-out dicts/lists; replace with defaults
    for key in ("skills", "languages", "common_answers"):
        if data.get(key) is None:
            data[key] = {}
    if data.get("experience") is None:
        data["experience"] = []

    return UserProfile(**data)


def save_profile(profile: UserProfile, path: Path | None = None) -> None:
    """Save user profile to YAML."""
    path = path or PROFILE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(profile.model_dump(), f, default_flow_style=False, allow_unicode=True)

    logger.info("Profile saved to {}", path)


def mark_profile_complete(profile: UserProfile, path: Path | None = None) -> UserProfile:
    """Set completed_at timestamp and save."""
    profile.completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_profile(profile, path)
    return profile


def get_profile_value(profile: UserProfile, key: str) -> str:
    """Get a value from the profile using dot notation (e.g. 'personal.first_name')."""
    from pydantic import BaseModel

    parts = key.split(".")
    obj: Any = profile
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return ""
    # Don't return model repr or complex types — only primitives
    if isinstance(obj, BaseModel) or isinstance(obj, (list, dict)):
        return ""
    return str(obj) if obj is not None else ""


def check_profile_completeness(profile: UserProfile) -> dict[str, Any]:
    """Check which required/optional fields are missing.

    Returns a dict with:
      - is_complete: bool (True if all REQUIRED fields are filled)
      - completed_at: str (timestamp or "")
      - missing_required: list of (field_path, question) tuples
      - missing_optional: list of (field_path, question) tuples
      - filled_count: int
      - total_count: int
    """
    missing_required = []
    missing_optional = []
    filled = 0
    total = len(REQUIRED_FIELDS) + len(OPTIONAL_FIELDS)

    for field_path, question in REQUIRED_FIELDS.items():
        value = get_profile_value(profile, field_path)
        if value:
            filled += 1
        else:
            missing_required.append({"field": field_path, "question": question})

    for field_path, question in OPTIONAL_FIELDS.items():
        value = get_profile_value(profile, field_path)
        if value:
            filled += 1
        else:
            missing_optional.append({"field": field_path, "question": question})

    return {
        "is_complete": len(missing_required) == 0,
        "completed_at": profile.completed_at,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "filled_count": filled,
        "total_count": total,
    }


# ── Field matching ─────────────────────────────────────────────────────────────

_FIELD_RULES: list[tuple[str, str]] = [
    # Personal
    (r"first\s*name|primer\s*nombre|nombre(?!\s*completo)", "personal.first_name"),
    (r"last\s*name|surname|family\s*name|apellido", "personal.last_name"),
    (r"full\s*name|nombre\s*completo", "_full_name"),
    (r"e-?mail|correo|direcci[oó]n\s*de\s*correo", "personal.email"),
    (r"phone|mobile|telephone|cell|tel[eé]fono|celular|m[oó]vil|whatsapp", "personal.phone"),
    (r"city|ciudad|localidad|municipio", "personal.city"),
    (r"state|province|region|provincia|estado", "personal.state"),
    (r"country|pa[ií]s|nacionalidad", "personal.country"),
    (r"postal|zip\s*code|zip|c[oó]digo\s*postal", "personal.postal_code"),

    # Links
    (r"linkedin\s*url|linkedin\s*profile|perfil\s*de\s*linkedin|linkedin", "links.linkedin"),
    (r"github", "links.github"),
    (r"portfolio|personal\s*website|personal\s*url|portafolio|sitio\s*web|enlace\s*web", "links.portfolio"),
    (r"website|sitio", "links.website"),

    # Professional
    (r"headline|job\s*title|t[ií]tulo\s*profesional|cargo", "professional.headline"),
    (r"summary|about|acerca\s*de|resumen\s*profesional", "professional.summary"),
    (r"years?\s*of\s*experience|experience\s*(years?|level)|a[ñn]os\s*de\s*experiencia|cu[aá]ntos\s*a[ñn]os", "professional.years_of_experience"),
    (r"current\s*title|current\s*role|puesto\s*actual|cargo\s*actual", "professional.current_title"),
    (r"current\s*company|employer|empresa\s*actual|empleador", "professional.current_company"),

    # Work authorization
    (r"authorized?\s*to\s*work|work\s*authorization|right\s*to\s*work|autorizaci[oó]n|autorizad[oa]|habilitaci[oó]n|habilitad[oa]\s*para\s*trabajar|permiso\s*de\s*trabajo", "_auth_authorized"),
    (r"sponsorship|visa\s*sponsorship|h-?1[bB]|need\s*visa|patrocinio|requiere\s*visa|sponsor", "_auth_sponsorship"),
    (r"work\s*status|immigration\s*status|legal\s*status|estado\s*migratorio|estatus\s*legal", "work_authorization.work_status"),

    # Education
    (r"degree|education\s*level|highest\s*education|nivel\s*de\s*estudios|t[ií]tulo\s*acad[eé]mico|grado", "education.degree"),
    (r"field\s*of\s*study|major|specialization|carrera|campo\s*de\s*estudio", "education.field"),
    (r"university|school|college|institution|universidad|instituci[oó]n|facultad", "education.school"),
    (r"graduation\s*year|year\s*of\s*graduation|a[ñn]o\s*de\s*graduaci[oó]n", "education.graduation_year"),

    # Salary
    (r"salary\s*expectation|expected\s*salary|desired\s*salary|compensation|salario|remuneraci[oó]n|pretensi[oó]n\s*salarial|sueldo", "salary.expected"),
    (r"current\s*salary|present\s*salary|salario\s*actual", "salary.current"),
    (r"salary\s*currency|currency|moneda", "salary.currency"),

    # Preferences
    (r"notice\s*period|availability|start\s*date|disponibilidad|per[ií]odo\s*de\s*preaviso|fecha\s*de\s*inicio", "preferences.notice_period"),
    (r"remote|work\s*from\s*home|telecommute|remoto|trabajo\s*remoto", "_preferences_remote"),

    # Languages
    (r"english\s*(level|proficiency|fluency)|english|ingl[eé]s", "_lang_english"),
    (r"spanish|español|castellano", "_lang_spanish"),
    (r"portuguese|portugu[eé]s", "_lang_portuguese"),
    (r"french|fran[cç]ais|franc[eé]s", "_lang_french"),
    (r"german|deutsch|alem[aá]n", "_lang_german"),
]


def match_field(question: str, profile: UserProfile) -> str | None:
    """Try to match a LinkedIn form question to a profile value."""
    import difflib

    q = question.lower().strip()

    # Check common_answers cache — exact match first, then fuzzy
    for pattern, answer in profile.common_answers.items():
        p = pattern.lower().strip()
        if p == q:
            logger.debug("Exact common answer match: '{}' -> '{}'", pattern, answer)
            return answer
        # Fuzzy match with high threshold to avoid false positives
        ratio = difflib.SequenceMatcher(None, p, q).ratio()
        if ratio > 0.85:
            logger.debug("Fuzzy common answer match ({:.0%}): '{}' -> '{}'", ratio, pattern, answer)
            return answer

    # Try field rules
    for pattern, key in _FIELD_RULES:
        if re.search(pattern, q, re.IGNORECASE):
            if key == "_full_name":
                name = f"{profile.personal.first_name} {profile.personal.last_name}".strip()
                return name or None
            if key == "_auth_authorized":
                return "Yes" if profile.work_authorization.authorized else "No"
            if key == "_auth_sponsorship":
                return "Yes" if profile.work_authorization.sponsorship_required else "No"
            if key == "_preferences_remote":
                return "Yes" if profile.preferences.remote_only else "No"
            if key.startswith("_lang_"):
                lang = key[len("_lang_"):]
                return profile.languages.get(lang, None)

            value = get_profile_value(profile, key)
            if value:
                logger.debug("Matched field: '{}' -> '{}' = '{}'", question, key, value)
                return value

    # Try skills match
    for skill in profile.skills:
        if skill.lower() in q:
            level = profile.skills[skill]
            return str(level)

    return None


def learn_answer(profile: UserProfile, question: str, answer: str) -> UserProfile:
    """Save a new Q&A pair to the profile's common_answers cache."""
    key = question.lower().strip()
    key = re.sub(r"[^a-z0-9\s]", "", key)
    key = re.sub(r"\s+", " ", key)

    if key and answer:
        profile.common_answers[key] = answer
        logger.info("Learned answer: '{}' -> '{}'", key, answer)

    return profile
