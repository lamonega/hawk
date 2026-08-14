"""Unified configuration and profile management with Pydantic V2."""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
SETTINGS_EXAMPLE_PATH = CONFIG_DIR / "settings.example.yaml"
PROFILE_PATH = CONFIG_DIR / "profile.yaml"
PROFILE_EXAMPLE_PATH = CONFIG_DIR / "profile.example.yaml"
RESUME_PATH = CONFIG_DIR / "plain_text_resume.yaml"
RESUME_EXAMPLE_PATH = CONFIG_DIR / "plain_text_resume.example.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Error reading YAML {}: {}", path, e)
        return {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ── Settings Models ───────────────────────────────────────────────────────────

class LinkedInSettings(BaseModel):
    easy_apply_only: bool = True
    experience_levels: list[str] = ["entry", "associate", "mid_senior_level"]
    job_types: dict[str, bool] = Field(default_factory=lambda: {
        "full_time": True,
        "contract": False,
        "part_time": False,
        "temporary": False,
        "internship": False,
        "other": False,
        "volunteer": False,
    })
    date_filter: str = "month"
    positions: list[str] = Field(default_factory=lambda: ["DevOps Engineer", "Cloud Engineer"])
    locations: list[str] = Field(default_factory=lambda: ["remote"])
    location_blacklist: list[str] = Field(default_factory=list)
    distance: int = 25
    company_blacklist: list[str] = Field(default_factory=list)
    title_blacklist: list[str] = Field(default_factory=list)


class ScoringSettings(BaseModel):
    min_score: int = Field(default=7, ge=1, le=10)


class ApplySettings(BaseModel):
    daily_max: int = Field(default=10, ge=1)
    min_delay: float = 2.0
    max_delay: float = 5.0
    dry_run: bool = True


class BrowserSettings(BaseModel):
    profile_dir: str = "profiles/linkedin"
    stealth: bool = True
    headless: bool = False


class Settings(BaseModel):
    linkedin: LinkedInSettings = Field(default_factory=LinkedInSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    apply: ApplySettings = Field(default_factory=ApplySettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)


_cached_settings: Settings | None = None
_cached_settings_mtime: float = 0


def load_settings(config_dir: Path | None = None) -> Settings:
    """Load settings from config/settings.yaml with fallback to settings.example.yaml."""
    cfg_dir = config_dir or CONFIG_DIR
    target = cfg_dir / "settings.yaml"
    if not target.exists():
        target = cfg_dir / "settings.example.yaml"
    data = _read_yaml(target)
    return Settings(**data)


def get_settings() -> Settings:
    """Get settings with automatic reload on file changes."""
    global _cached_settings, _cached_settings_mtime
    target = SETTINGS_PATH if SETTINGS_PATH.exists() else SETTINGS_EXAMPLE_PATH
    try:
        mtime = target.stat().st_mtime if target.exists() else 0
    except Exception:
        mtime = 0

    if _cached_settings is None or mtime > _cached_settings_mtime:
        _cached_settings = load_settings()
        _cached_settings_mtime = mtime
    return _cached_settings


def save_settings(settings: Settings, config_dir: Path | None = None) -> None:
    """Save settings to config/settings.yaml."""
    global _cached_settings, _cached_settings_mtime
    cfg_dir = config_dir or CONFIG_DIR
    target = cfg_dir / "settings.yaml"
    _write_yaml(target, settings.model_dump())
    _cached_settings = settings
    try:
        _cached_settings_mtime = target.stat().st_mtime
    except Exception:
        _cached_settings_mtime = 0


def update_setting(field_path: str, value: Any, config_dir: Path | None = None) -> Settings:
    """Update a specific setting using dot-notation (e.g. 'apply.daily_max', 'linkedin.positions')."""
    settings = load_settings(config_dir)
    data = settings.model_dump()

    parts = field_path.split(".")
    obj = data
    for part in parts[:-1]:
        if part not in obj or not isinstance(obj[part], dict):
            obj[part] = {}
        obj = obj[part]

    last_key = parts[-1]
    if isinstance(value, str):
        val_lower = value.strip().lower()
        if val_lower == "true":
            value = True
        elif val_lower == "false":
            value = False
        elif value.isdigit():
            value = int(value)
        elif "," in value and last_key in ("positions", "locations", "experience_levels", "company_blacklist", "title_blacklist"):
            value = [p.strip() for p in value.split(",") if p.strip()]

    obj[last_key] = value
    new_settings = Settings(**data)
    save_settings(new_settings, config_dir)
    return new_settings


# ── Profile Models ────────────────────────────────────────────────────────────

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


class ProjectStory(BaseModel):
    name: str = ""
    company_or_context: str = ""
    challenge: str = ""
    action: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    result_metrics: str = ""


class ScreeningPreferences(BaseModel):
    b2b_contractor_ok: bool = True
    us_work_auth: bool = False
    requires_sponsorship: bool = False
    timezone_overlap_hours: int = 4
    willing_to_relocate: bool = False


class UserProfile(BaseModel):
    completed_at: str = ""
    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    links: Links = Field(default_factory=Links)
    professional: ProfessionalInfo = Field(default_factory=ProfessionalInfo)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    education: Education = Field(default_factory=Education)
    skills: dict[str, int] = Field(default_factory=dict)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    salary: Salary = Field(default_factory=Salary)
    languages: dict[str, str] = Field(default_factory=dict)
    preferences: Preferences = Field(default_factory=Preferences)
    screening_preferences: ScreeningPreferences = Field(default_factory=ScreeningPreferences)
    project_stories: list[ProjectStory] = Field(default_factory=list)
    common_answers: dict[str, str] = Field(default_factory=dict)


def load_profile(path: Path | None = None) -> UserProfile:
    """Load user profile from config/profile.yaml with fallback to profile.example.yaml."""
    if path is None:
        path = PROFILE_PATH if PROFILE_PATH.exists() else PROFILE_EXAMPLE_PATH
    data = _read_yaml(path)
    # Ensure nested collections are not None
    for k in ("skills", "languages", "common_answers"):
        if data.get(k) is None:
            data[k] = {}
    for k in ("experience", "project_stories"):
        if data.get(k) is None:
            data[k] = []
    return UserProfile(**data)


def save_profile(profile: UserProfile, path: Path | None = None, sync_resume: bool = True) -> None:
    """Save user profile to YAML and synchronize plain text resume."""
    path = path or PROFILE_PATH
    _write_yaml(path, profile.model_dump())
    if sync_resume:
        sync_profile_to_resume(profile)


def sync_profile_to_resume(profile: UserProfile, resume_path: Path | None = None) -> None:
    """Synchronize UserProfile into plain_text_resume.yaml."""
    resume_path = resume_path or RESUME_PATH
    target = resume_path if resume_path.exists() else (resume_path.parent / "plain_text_resume.example.yaml")
    data = _read_yaml(target)

    personal = data.get("personal_information") or {}
    if profile.personal.first_name:
        personal["name"] = profile.personal.first_name
    if profile.personal.last_name:
        personal["surname"] = profile.personal.last_name
    if profile.personal.city:
        personal["city"] = profile.personal.city
    if profile.personal.country:
        personal["country"] = profile.personal.country
    if profile.personal.postal_code:
        personal["zip_code"] = profile.personal.postal_code
    if profile.personal.email:
        personal["email"] = profile.personal.email
    if profile.personal.phone:
        personal["phone"] = profile.personal.phone
    if profile.links.github:
        personal["github"] = profile.links.github
    if profile.links.linkedin:
        personal["linkedin"] = profile.links.linkedin
    data["personal_information"] = personal

    if profile.education.degree or profile.education.school:
        edu_list = data.get("education_details") or [{}]
        edu = edu_list[0] if isinstance(edu_list[0], dict) else {}
        if profile.education.degree:
            edu["education_level"] = profile.education.degree
        if profile.education.school:
            edu["institution"] = profile.education.school
        if profile.education.field:
            edu["field_of_study"] = profile.education.field
        if profile.education.graduation_year:
            try:
                edu["year_of_completion"] = int(profile.education.graduation_year)
            except ValueError:
                edu["year_of_completion"] = profile.education.graduation_year
        edu_list[0] = edu
        data["education_details"] = edu_list

    if profile.experience:
        data["experience_details"] = profile.experience
    elif profile.professional.current_title or profile.professional.current_company:
        exp_list = data.get("experience_details") or [{}]
        exp = exp_list[0] if isinstance(exp_list[0], dict) else {}
        if profile.professional.current_title:
            exp["position"] = profile.professional.current_title
        if profile.professional.current_company:
            exp["company"] = profile.professional.current_company
        if profile.professional.summary:
            exp["key_responsibilities"] = [{"description": profile.professional.summary}]
        exp_list[0] = exp
        data["experience_details"] = exp_list

    if profile.languages:
        data["languages"] = [
            {"language": lang.capitalize(), "proficiency": str(lvl)}
            for lang, lvl in profile.languages.items()
        ]

    for key in ("projects", "achievements", "certifications", "interests"):
        data.setdefault(key, [])

    _write_yaml(resume_path, data)


def get_profile_value(profile: UserProfile, field_path: str) -> str:
    """Retrieve string value from profile using dot-notation."""
    parts = field_path.split(".")
    obj: Any = profile
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return ""
    if isinstance(obj, (BaseModel, list, dict)):
        return ""
    return str(obj) if obj is not None else ""


# ── Field Matching & Knowledge Base ──────────────────────────────────────────

_MATCH_RULES = [
    (r"first\s*name|primer\s*nombre|nombre(?!\s*completo)", "personal.first_name"),
    (r"last\s*name|surname|family\s*name|apellido", "personal.last_name"),
    (r"full\s*name|nombre\s*completo", "_full_name"),
    (r"e-?mail|correo", "personal.email"),
    (r"phone|mobile|tel[eé]fono|celular|m[oó]vil", "personal.phone"),
    (r"city|ciudad|localidad", "personal.city"),
    (r"state|province|provincia|estado", "personal.state"),
    (r"country|pa[ií]s", "personal.country"),
    (r"postal|zip\s*code|c[oó]digo\s*postal", "personal.postal_code"),
    (r"linkedin", "links.linkedin"),
    (r"github", "links.github"),
    (r"portfolio|portafolio|website|sitio", "links.portfolio"),
    (r"headline|t[ií]tulo\s*profesional", "professional.headline"),
    (r"summary|resumen|acerca\s*de", "professional.summary"),
    (r"years?\s*of\s*experience|a[ñn]os\s*de\s*experiencia", "professional.years_of_experience"),
    (r"current\s*title|puesto\s*actual", "professional.current_title"),
    (r"current\s*company|empresa\s*actual", "professional.current_company"),
    (r"authorized?\s*to\s*work|work\s*authorization|autorizaci[oó]n|habilitad[oa]", "_auth_authorized"),
    (r"sponsorship|visa|patrocinio|sponsor", "_auth_sponsorship"),
    (r"work\s*status|estatus\s*legal", "work_authorization.work_status"),
    (r"degree|nivel\s*de\s*estudios|t[ií]tulo", "education.degree"),
    (r"field\s*of\s*study|carrera|campo", "education.field"),
    (r"university|school|universidad|instituci[oó]n", "education.school"),
    (r"graduation\s*year|a[ñn]o\s*de\s*graduaci[oó]n", "education.graduation_year"),
    (r"salary|salario|remuneraci[oó]n|sueldo|pretensi[oó]n", "salary.expected"),
    (r"notice\s*period|disponibilidad|preaviso|start\s*date", "preferences.notice_period"),
    (r"remote|remoto", "_preferences_remote"),
]


def match_field(question: str, profile: UserProfile) -> str | None:
    """Match a form label or question to a profile field value."""
    q = question.lower().strip()

    # 1. Exact & Fuzzy matching in learned common answers
    for pattern, answer in profile.common_answers.items():
        p = pattern.lower().strip()
        if p == q or difflib.SequenceMatcher(None, p, q).ratio() > 0.85:
            return answer

    # 2. Rule-based regex matching
    for regex_pat, target_key in _MATCH_RULES:
        if re.search(regex_pat, q, re.IGNORECASE):
            if target_key == "_full_name":
                return f"{profile.personal.first_name} {profile.personal.last_name}".strip() or None
            if target_key == "_auth_authorized":
                return "Yes" if profile.work_authorization.authorized else "No"
            if target_key == "_auth_sponsorship":
                return "Yes" if profile.work_authorization.sponsorship_required else "No"
            if target_key == "_preferences_remote":
                return "Yes" if profile.preferences.remote_only else "No"

            val = get_profile_value(profile, target_key)
            if val:
                return val

    # 3. Skills match (e.g. "How many years of Python?")
    for skill_name, years in profile.skills.items():
        if skill_name.lower() in q:
            return str(years)

    # 4. Languages match
    for lang, level in profile.languages.items():
        if lang.lower() in q:
            return level

    return None


def learn_answer(profile: UserProfile, question: str, answer: str) -> UserProfile:
    """Cache question and answer pair into common_answers."""
    key = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", question.lower())).strip()
    if key and answer:
        profile.common_answers[key] = answer
    return profile


def query_knowledge_base(profile: UserProfile, query: str) -> dict[str, Any]:
    """Retrieve grounded candidate context and STAR project stories for answers."""
    tokens = set(re.findall(r"\w+", query.lower()))
    stories = []
    for story in profile.project_stories:
        text = f"{story.name} {story.company_or_context} {story.challenge} {story.action} {' '.join(story.tech_stack)} {story.result_metrics}".lower()
        score = sum(1 for t in tokens if len(t) > 2 and t in text)
        if score > 0 or not tokens:
            stories.append({
                "name": story.name,
                "context": story.company_or_context,
                "challenge": story.challenge,
                "action": story.action,
                "tech_stack": story.tech_stack,
                "result": story.result_metrics,
                "relevance": score,
            })
    stories.sort(key=lambda s: s["relevance"], reverse=True)

    matched_skills = {k: v for k, v in profile.skills.items() if any(t in k.lower() for t in tokens if len(t) > 2)}

    return {
        "query": query,
        "direct_answer": match_field(query, profile),
        "direct_facts": {
            "candidate_name": f"{profile.personal.first_name} {profile.personal.last_name}".strip(),
            "headline": profile.professional.headline,
            "years_of_experience": profile.professional.years_of_experience,
            "current_title": profile.professional.current_title,
            "current_company": profile.professional.current_company,
            "location": f"{profile.personal.city}, {profile.personal.country}".strip(", "),
            "education": f"{profile.education.degree} in {profile.education.field} ({profile.education.school})",
            "work_authorization": {
                "authorized": profile.work_authorization.authorized,
                "country": profile.work_authorization.country,
                "sponsorship_required": profile.work_authorization.sponsorship_required,
                "b2b_contractor_ok": profile.screening_preferences.b2b_contractor_ok,
            },
            "salary_expected": profile.salary.expected,
            "remote_only": profile.preferences.remote_only,
            "notice_period": profile.preferences.notice_period,
        },
        "relevant_skills": matched_skills,
        "matched_stories": stories[:3],
    }
