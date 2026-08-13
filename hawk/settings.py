"""hawk settings via pydantic-settings + YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


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
    positions: list[str] = Field(default_factory=lambda: ["backend", "full stack"])
    locations: list[str] = Field(default_factory=lambda: ["remote"])
    location_blacklist: list[str] = Field(default_factory=list)
    distance: int = 25
    company_blacklist: list[str] = Field(default_factory=list)
    title_blacklist: list[str] = Field(default_factory=list)


class ScoringSettings(BaseModel):
    min_score: int = Field(default=7, ge=1, le=10)


class ApplySettings(BaseModel):
    daily_max: int = Field(default=5, ge=1)
    min_delay: float = 2.0
    max_delay: float = 6.0
    dry_run: bool = True


class BrowserSettings(BaseModel):
    profile_dir: str = "profiles/linkedin"
    stealth: bool = False
    headless: bool = False


class Settings(BaseModel):
    linkedin: LinkedInSettings = Field(default_factory=LinkedInSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    apply: ApplySettings = Field(default_factory=ApplySettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_dir: Path | None = None) -> Settings:
    config_dir = config_dir or CONFIG_DIR
    data = _load_yaml(config_dir / "settings.yaml")
    return Settings(**data)


# Singleton for convenience
_settings: Settings | None = None
_settings_mtime: float = 0


def get_settings() -> Settings:
    global _settings, _settings_mtime
    config_path = CONFIG_DIR / "settings.yaml"
    try:
        current_mtime = config_path.stat().st_mtime if config_path.exists() else 0
    except Exception:
        current_mtime = 0

    # Reload if settings file changed or first load
    if _settings is None or current_mtime > _settings_mtime:
        _settings = load_settings()
        _settings_mtime = current_mtime
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from disk."""
    global _settings, _settings_mtime
    _settings = None
    _settings_mtime = 0
    return get_settings()
