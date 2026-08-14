"""Unified configuration and profile management with Pydantic V2."""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, Field

# ── Paths ────────────────────────────────────────────────────────────────────

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
CONFIG_DIR: Path = PROJECT_ROOT / "config"

SETTINGS_PATH: Path = CONFIG_DIR / "settings.yaml"
SETTINGS_EXAMPLE_PATH: Path = CONFIG_DIR / "settings.example.yaml"
PROFILE_PATH: Path = CONFIG_DIR / "profile.yaml"
PROFILE_EXAMPLE_PATH: Path = CONFIG_DIR / "profile.example.yaml"
RESUME_PATH: Path = CONFIG_DIR / "plain_text_resume.yaml"
RESUME_EXAMPLE_PATH: Path = CONFIG_DIR / "plain_text_resume.example.yaml"

# ── Constants & Defaults ─────────────────────────────────────────────────────

DEFAULT_DISTANCE: int = 25
DEFAULT_MIN_SCORE: int = 7
DEFAULT_DAILY_MAX: int = 10
DEFAULT_MIN_DELAY: float = 2.0
DEFAULT_MAX_DELAY: float = 5.0
DEFAULT_PROFILE_DIR: str = "profiles/linkedin"
DEFAULT_CURRENCY: str = "USD"
DEFAULT_TIMEZONE_OVERLAP_HOURS: int = 4
DEFAULT_DATE_FILTER: str = "month"

FUZZY_MATCH_THRESHOLD: float = 0.85
MAX_MATCHED_STORIES: int = 3
MIN_KEYWORD_LENGTH: int = 3

LIST_SETTING_KEYS: frozenset[str] = frozenset({
    "positions",
    "locations",
    "experience_levels",
    "location_blacklist",
    "company_blacklist",
    "title_blacklist",
})

DEFAULT_EXPERIENCE_LEVELS: list[str] = ["entry", "associate", "mid_senior_level"]

DEFAULT_JOB_TYPES: dict[str, bool] = {
    "full_time": True,
    "contract": False,
    "part_time": False,
    "temporary": False,
    "internship": False,
    "other": False,
    "volunteer": False,
}

# Mapping of plain_text_resume personal keys to UserProfile attribute paths
PERSONAL_TO_RESUME_MAP: dict[str, str] = {
    "name": "personal.first_name",
    "surname": "personal.last_name",
    "city": "personal.city",
    "country": "personal.country",
    "zip_code": "personal.postal_code",
    "email": "personal.email",
    "phone": "personal.phone",
    "github": "links.github",
    "linkedin": "links.linkedin",
}

# Mapping of plain_text_resume education keys to UserProfile attribute paths
EDUCATION_TO_RESUME_MAP: dict[str, str] = {
    "education_level": "education.degree",
    "institution": "education.school",
    "field_of_study": "education.field",
}

_CLEAN_KEY_REGEX: re.Pattern[str] = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_REGEX: re.Pattern[str] = re.compile(r"\s+")


# ── YAML Helpers ─────────────────────────────────────────────────────────────

def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file into a dictionary, returning an empty dict on failure."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Error reading YAML {}: {}", path, e)
        return {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Serialize and write a dictionary to a YAML file with unicode support."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ── Settings Models ──────────────────────────────────────────────────────────

class LinkedInSettings(BaseModel):
    """LinkedIn search criteria and filtering parameters."""

    easy_apply_only: bool = True
    experience_levels: list[str] = Field(default_factory=lambda: list(DEFAULT_EXPERIENCE_LEVELS))
    job_types: dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_JOB_TYPES))
    date_filter: str = DEFAULT_DATE_FILTER
    positions: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=lambda: ["remote"])
    location_blacklist: list[str] = Field(default_factory=list)
    distance: int = DEFAULT_DISTANCE
    company_blacklist: list[str] = Field(default_factory=list)
    title_blacklist: list[str] = Field(default_factory=list)


class ScoringSettings(BaseModel):
    """Job screening threshold settings."""

    min_score: int = Field(default=DEFAULT_MIN_SCORE, ge=1, le=10)


class ApplySettings(BaseModel):
    """Rate-limiting, throttling, and safety controls for Easy Apply."""

    daily_max: int = Field(default=DEFAULT_DAILY_MAX, ge=1)
    min_delay: float = DEFAULT_MIN_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    dry_run: bool = True


class BrowserSettings(BaseModel):
    """Playwright browser execution and session persistence options."""

    profile_dir: str = DEFAULT_PROFILE_DIR
    stealth: bool = True
    headless: bool = False


class Settings(BaseModel):
    """Root configuration aggregating all application settings."""

    linkedin: LinkedInSettings = Field(default_factory=LinkedInSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    apply: ApplySettings = Field(default_factory=ApplySettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)


_cached_settings: Settings | None = None
_cached_settings_mtime: float = 0.0


def load_settings(config_dir: Path | None = None) -> Settings:
    """Load settings from config/settings.yaml with fallback to settings.example.yaml."""
    cfg_dir = config_dir or CONFIG_DIR
    target = cfg_dir / "settings.yaml"
    if not target.exists():
        target = cfg_dir / "settings.example.yaml"
    data = _read_yaml(target)
    return Settings(**data)


def get_settings() -> Settings:
    """Get cached settings with automatic reload when the file is modified on disk."""
    global _cached_settings, _cached_settings_mtime
    target = SETTINGS_PATH if SETTINGS_PATH.exists() else SETTINGS_EXAMPLE_PATH
    try:
        mtime = target.stat().st_mtime if target.exists() else 0.0
    except Exception:
        mtime = 0.0

    if _cached_settings is None or mtime > _cached_settings_mtime:
        _cached_settings = load_settings()
        _cached_settings_mtime = mtime
    return _cached_settings


def save_settings(settings: Settings, config_dir: Path | None = None) -> None:
    """Save settings to config/settings.yaml and update cached instance."""
    global _cached_settings, _cached_settings_mtime
    cfg_dir = config_dir or CONFIG_DIR
    target = cfg_dir / "settings.yaml"
    _write_yaml(target, settings.model_dump())
    _cached_settings = settings
    try:
        _cached_settings_mtime = target.stat().st_mtime
    except Exception:
        _cached_settings_mtime = 0.0


def _coerce_setting_value(key: str, value: Any) -> Any:
    """Coerce string inputs from CLI or API into appropriate types."""
    if not isinstance(value, str):
        return value

    val_stripped = value.strip()
    val_lower = val_stripped.lower()

    if val_lower == "true":
        return True
    if val_lower == "false":
        return False
    if val_stripped.isdigit():
        return int(val_stripped)
    if key in LIST_SETTING_KEYS and "," in val_stripped:
        return [item.strip() for item in val_stripped.split(",") if item.strip()]

    return value


def update_setting(field_path: str, value: Any, config_dir: Path | None = None) -> Settings:
    """Update a specific setting using dot-notation (e.g. 'apply.daily_max', 'linkedin.positions')."""
    settings = load_settings(config_dir)
    data = settings.model_dump()

    parts = field_path.split(".")
    target_dict = data
    for part in parts[:-1]:
        if part not in target_dict or not isinstance(target_dict[part], dict):
            target_dict[part] = {}
        target_dict = target_dict[part]

    last_key = parts[-1]
    target_dict[last_key] = _coerce_setting_value(last_key, value)

    new_settings = Settings(**data)
    save_settings(new_settings, config_dir)
    return new_settings


# ── Profile Models ────────────────────────────────────────────────────────────

class PersonalInfo(BaseModel):
    """Candidate personal and contact details."""

    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    postal_code: str = ""


class Links(BaseModel):
    """Professional online profile links."""

    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    website: str = ""


class ProfessionalInfo(BaseModel):
    """High-level professional background and career positioning."""

    headline: str = ""
    summary: str = ""
    years_of_experience: str = ""
    current_title: str = ""
    current_company: str = ""


class WorkAuthorization(BaseModel):
    """Legal right to work and visa requirements."""

    authorized: bool = True
    sponsorship_required: bool = False
    country: str = ""
    work_status: str = ""


class Education(BaseModel):
    """Academic background and degree credentials."""

    degree: str = ""
    field: str = ""
    school: str = ""
    graduation_year: str = ""


class Salary(BaseModel):
    """Compensation expectations and flexibility."""

    current: str = ""
    expected: str = ""
    currency: str = DEFAULT_CURRENCY
    negotiable: bool = True


class Preferences(BaseModel):
    """Job search availability and working preferences."""

    remote_only: bool = True
    min_salary: str = ""
    notice_period: str = ""
    start_date: str = ""


class ProjectStory(BaseModel):
    """STAR format grounded project story used for screening questions and interview pitches."""

    name: str = ""
    company_or_context: str = ""
    challenge: str = ""
    action: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    result_metrics: str = ""


class ScreeningPreferences(BaseModel):
    """Pre-qualification criteria for automated screening decisions."""

    b2b_contractor_ok: bool = True
    us_work_auth: bool = False
    requires_sponsorship: bool = False
    timezone_overlap_hours: int = DEFAULT_TIMEZONE_OVERLAP_HOURS
    willing_to_relocate: bool = False


class UserProfile(BaseModel):
    """Comprehensive candidate profile used for autofill, tailoring, and ATS generation."""

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

    # Ensure nested dictionary and list collections default properly
    for dict_key in ("skills", "languages", "common_answers"):
        if data.get(dict_key) is None:
            data[dict_key] = {}
    for list_key in ("experience", "project_stories"):
        if data.get(list_key) is None:
            data[list_key] = []

    return UserProfile(**data)


def save_profile(profile: UserProfile, path: Path | None = None, sync_resume: bool = True) -> None:
    """Save user profile to YAML and optionally synchronize plain text resume."""
    target_path = path or PROFILE_PATH
    _write_yaml(target_path, profile.model_dump())
    if sync_resume:
        sync_profile_to_resume(profile)


def get_profile_value(profile: UserProfile, field_path: str) -> str:
    """Retrieve string value from profile using dot-notation (e.g. 'personal.first_name')."""
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


def sync_profile_to_resume(profile: UserProfile, resume_path: Path | None = None) -> None:
    """Synchronize UserProfile into plain_text_resume.yaml following DRY principles."""
    target_path = resume_path or RESUME_PATH
    source = target_path if target_path.exists() else (target_path.parent / "plain_text_resume.example.yaml")
    data = _read_yaml(source)

    # 1. Sync personal information
    personal = data.get("personal_information") or {}
    for resume_key, profile_key in PERSONAL_TO_RESUME_MAP.items():
        val = get_profile_value(profile, profile_key)
        if val:
            personal[resume_key] = val
    data["personal_information"] = personal

    # 2. Sync education details
    if profile.education.degree or profile.education.school:
        edu_list = data.get("education_details") or [{}]
        edu = edu_list[0] if isinstance(edu_list[0], dict) else {}
        for resume_key, profile_key in EDUCATION_TO_RESUME_MAP.items():
            val = get_profile_value(profile, profile_key)
            if val:
                edu[resume_key] = val

        if profile.education.graduation_year:
            grad_year = profile.education.graduation_year.strip()
            edu["year_of_completion"] = int(grad_year) if grad_year.isdigit() else grad_year

        edu_list[0] = edu
        data["education_details"] = edu_list

    # 3. Sync experience details
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

    # 4. Sync languages
    if profile.languages:
        data["languages"] = [
            {"language": lang.capitalize(), "proficiency": str(lvl)}
            for lang, lvl in profile.languages.items()
        ]

    # Ensure required plain text resume lists exist
    for key in ("projects", "achievements", "certifications", "interests"):
        data.setdefault(key, [])

    _write_yaml(target_path, data)


# ── Field Matching & Knowledge Base ──────────────────────────────────────────

# Compiled match pattern definitions
_MATCH_PATTERNS: list[tuple[str, str]] = [
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

_COMPILED_MATCH_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern, re.IGNORECASE), target_key)
    for pattern, target_key in _MATCH_PATTERNS
]

# Resolvers for computed/composite target fields
_COMPUTED_FIELD_RESOLVERS: dict[str, Callable[[UserProfile], str | None]] = {
    "_full_name": lambda p: f"{p.personal.first_name} {p.personal.last_name}".strip() or None,
    "_auth_authorized": lambda p: "Yes" if p.work_authorization.authorized else "No",
    "_auth_sponsorship": lambda p: "Yes" if p.work_authorization.sponsorship_required else "No",
    "_preferences_remote": lambda p: "Yes" if p.preferences.remote_only else "No",
}


def match_field(question: str, profile: UserProfile) -> str | None:
    """Match a form label or application question to an accurate profile field value."""
    q = question.lower().strip()

    # 1. Exact & Fuzzy matching in learned common answers
    for pattern, answer in profile.common_answers.items():
        p = pattern.lower().strip()
        if p == q or difflib.SequenceMatcher(None, p, q).ratio() > FUZZY_MATCH_THRESHOLD:
            return answer

    # 2. Rule-based pre-compiled regex matching
    for pattern, target_key in _COMPILED_MATCH_RULES:
        if pattern.search(q):
            if target_key in _COMPUTED_FIELD_RESOLVERS:
                return _COMPUTED_FIELD_RESOLVERS[target_key](profile)

            val = get_profile_value(profile, target_key)
            if val:
                return val

    # 3. Skills match (e.g. "How many years of Python experience do you have?")
    for skill_name, years in profile.skills.items():
        if skill_name.lower() in q:
            return str(years)

    # 4. Languages match (e.g. "English proficiency level")
    for lang, level in profile.languages.items():
        if lang.lower() in q:
            return level

    return None


def learn_answer(profile: UserProfile, question: str, answer: str) -> UserProfile:
    """Cache question and answer pair into profile common_answers for future reuse."""
    clean_q = _CLEAN_KEY_REGEX.sub("", question.lower())
    key = _WHITESPACE_REGEX.sub(" ", clean_q).strip()
    if key and answer:
        profile.common_answers[key] = answer
    return profile


def query_knowledge_base(profile: UserProfile, query: str) -> dict[str, Any]:
    """Retrieve grounded candidate context and ranked STAR project stories for screening queries."""
    query_tokens = {
        token
        for token in re.findall(r"\w+", query.lower())
        if len(token) >= MIN_KEYWORD_LENGTH
    }

    stories: list[dict[str, Any]] = []
    for story in profile.project_stories:
        story_content = " ".join([
            story.name,
            story.company_or_context,
            story.challenge,
            story.action,
            " ".join(story.tech_stack),
            story.result_metrics,
        ]).lower()

        score = sum(1 for token in query_tokens if token in story_content)
        if score > 0 or not query_tokens:
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

    matched_skills = {
        skill_name: years
        for skill_name, years in profile.skills.items()
        if any(token in skill_name.lower() for token in query_tokens)
    }

    # Format education text cleanly
    edu_parts = [
        f"{profile.education.degree} in {profile.education.field}"
        if profile.education.degree and profile.education.field
        else (profile.education.degree or profile.education.field),
        f"({profile.education.school})" if profile.education.school else "",
    ]
    formatted_education = " ".join(filter(None, edu_parts)).strip()

    candidate_name = f"{profile.personal.first_name} {profile.personal.last_name}".strip()
    location = f"{profile.personal.city}, {profile.personal.country}".strip(", ")

    return {
        "query": query,
        "direct_answer": match_field(query, profile),
        "direct_facts": {
            "candidate_name": candidate_name,
            "headline": profile.professional.headline,
            "years_of_experience": profile.professional.years_of_experience,
            "current_title": profile.professional.current_title,
            "current_company": profile.professional.current_company,
            "location": location,
            "education": formatted_education,
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
        "matched_stories": stories[:MAX_MATCHED_STORIES],
    }
