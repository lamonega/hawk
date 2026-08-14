"""Tests for profile & resume synchronization, settings updates, and session wait helpers."""
import pytest
from pathlib import Path
import yaml
from playwright.async_api import async_playwright

from hawk.profile import UserProfile, PersonalInfo, Education, ProfessionalInfo, sync_profile_to_resume, save_profile
from hawk.settings import Settings, update_setting, load_settings, save_settings
from hawk.browser.driver import dismiss_guest_overlays, wait_for_login
import hawk.browser.driver as driver_module


def test_sync_profile_to_resume(tmp_path: Path):
    resume_file = tmp_path / "plain_text_resume.yaml"
    profile = UserProfile(
        personal=PersonalInfo(
            first_name="Alex",
            last_name="Taylor",
            email="alex.taylor@example.com",
            phone="+1 555 123 4567",
            city="San Francisco",
            country="United States",
            postal_code="94105",
        ),
        education=Education(
            degree="Bachelor's",
            field="Computer Science",
            school="University of Technology",
            graduation_year="2024",
        ),
        professional=ProfessionalInfo(
            current_title="DevOps Engineer",
            current_company="Tech Solutions Inc.",
            summary="CI/CD and Linux administration",
        ),
        languages={"english": "Native", "spanish": "Professional"},
        skills={"docker": 3, "linux": 4},
    )

    sync_profile_to_resume(profile, resume_path=resume_file)

    assert resume_file.exists()
    with open(resume_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["personal_information"]["name"] == "Alex"
    assert data["personal_information"]["surname"] == "Taylor"
    assert data["personal_information"]["email"] == "alex.taylor@example.com"
    assert data["personal_information"]["zip_code"] == "94105"
    assert data["education_details"][0]["education_level"] == "Bachelor's"
    assert data["education_details"][0]["institution"] == "University of Technology"
    assert data["education_details"][0]["year_of_completion"] == 2024
    assert data["experience_details"][0]["position"] == "DevOps Engineer"
    assert data["experience_details"][0]["company"] == "Tech Solutions Inc."
    assert len(data["languages"]) == 2


def test_update_settings(tmp_path: Path):
    settings_file = tmp_path / "settings.yaml"
    init_settings = Settings()
    save_settings(init_settings, config_dir=tmp_path)

    # 1. Update list via list
    s1 = update_setting("linkedin.positions", ["devops", "sre"], config_dir=tmp_path)
    assert s1.linkedin.positions == ["devops", "sre"]

    # 2. Update list via comma-separated string
    s2 = update_setting("linkedin.positions", "cloud, platform", config_dir=tmp_path)
    assert s2.linkedin.positions == ["cloud", "platform"]

    # 3. Update int via string
    s3 = update_setting("apply.daily_max", "15", config_dir=tmp_path)
    assert s3.apply.daily_max == 15

    # 4. Update bool via string
    s4 = update_setting("apply.dry_run", "false", config_dir=tmp_path)
    assert s4.apply.dry_run is False


@pytest.mark.asyncio
async def test_dismiss_guest_overlays():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()

    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="contextual-sign-in-modal">
            <button aria-label="Descartar" class="contextual-sign-in-modal__modal-dismiss-btn">Descartar</button>
        </div>
    </body>
    </html>
    """
    await page.set_content(html)
    driver_module._page = page

    # Modal should be dismissed
    dismissed = await dismiss_guest_overlays(page)
    assert dismissed is True

    await browser.close()
    await pw.stop()
    driver_module._page = None
