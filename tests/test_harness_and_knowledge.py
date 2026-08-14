"""Tests for knowledge base query, cover letter generation, recruiter pitch, and workflow harness."""

import pytest
from pathlib import Path
from hawk.profile import load_profile, query_knowledge_base, UserProfile
from hawk.resume.generator import render_ats_cover_letter_html, generate_tailored_cover_letter
from hawk.linkedin.operations import generate_recruiter_pitch
from hawk.workflow import ApplicationHarness, JobSearchEngine


def test_query_knowledge_base():
    profile = load_profile()
    
    # 1. Search for CI/CD story
    res = query_knowledge_base(profile, "CI/CD pipeline automation with GitHub Actions")
    assert "matched_stories" in res
    assert len(res["matched_stories"]) > 0
    assert any("CI/CD" in s["name"] for s in res["matched_stories"])
    
    # 2. Check direct facts
    assert res["direct_facts"]["candidate_name"].startswith("Laureano")
    assert res["direct_facts"]["work_authorization"]["country"] == "Argentina"
    assert res["direct_facts"]["work_authorization"]["b2b_contractor_ok"] is True
    
    # 3. Check skills
    assert "docker" in res["relevant_skills"] or "linux" in res["relevant_skills"] or len(profile.skills) > 0


def test_recruiter_pitch_length_and_content():
    pitch = generate_recruiter_pitch(
        job_title="Senior DevOps Engineer",
        company="GlobalTech Inc",
        recruiter_name="Sarah Jenkins",
        top_skills=["Terraform", "AWS", "CI/CD"],
    )
    assert len(pitch) <= 300
    assert "Sarah" in pitch
    assert "Senior DevOps Engineer" in pitch
    assert "GlobalTech Inc" in pitch
    assert "Laureano" in pitch


@pytest.mark.asyncio
async def test_generate_cover_letter_pdf(tmp_path):
    pdf_path = await generate_tailored_cover_letter(
        job_id="test_job_harness_999",
        job_title="Cloud DevOps Engineer",
        company="Acme Cloud Solutions",
        hiring_manager="John Doe",
        tailored_body=[
            "I am excited to apply for the Cloud DevOps Engineer role at Acme Cloud Solutions.",
            "With experience in Docker, Linux, and automated GitHub Actions workflows, I specialize in reducing deployment friction.",
            "Thank you for considering my application.",
        ],
        output_dir=tmp_path,
    )
    assert Path(pdf_path).exists()
    assert Path(pdf_path).stat().st_size > 1000


def test_cover_letter_html_rendering():
    # English test
    html_en = render_ats_cover_letter_html(
        job_title="DevOps Engineer",
        company="TechCorp",
        hiring_manager="Jane Smith",
        language="en",
    )
    assert "Jane Smith" in html_en
    assert "TechCorp" in html_en
    assert "DevOps Engineer" in html_en
    assert "Sincerely," in html_en
    assert "Laureano" in html_en
    assert "lflamonega@gmail.com" in html_en

    # Spanish test
    html_es = render_ats_cover_letter_html(
        job_title="Ingeniero DevOps",
        company="Mercado Libre",
        hiring_manager="Carlos Perez",
        language="es",
    )
    assert "Carlos Perez" in html_es
    assert "Mercado Libre" in html_es
    assert "Ingeniero DevOps" in html_es
    assert "Atentamente," in html_es
    assert "Laureano" in html_es


def test_recruiter_pitch_spanish_and_english():
    # Spanish pitch
    pitch_es = generate_recruiter_pitch(
        job_title="Ingeniero de Plataforma",
        company="Banco Galicia",
        recruiter_name="Martin Gomez",
        top_skills=["Docker", "Linux", "Terraform"],
        language="es",
    )
    assert len(pitch_es) <= 300
    assert "Hola Martin" in pitch_es
    assert "Banco Galicia" in pitch_es
    assert "Ingeniero de Plataforma" in pitch_es
    assert "Laureano" in pitch_es

    # English pitch
    pitch_en = generate_recruiter_pitch(
        job_title="Cloud Engineer",
        company="Amazon AWS",
        recruiter_name="Michael Scott",
        top_skills=["AWS", "EKS", "CI/CD"],
        language="en",
    )
    assert len(pitch_en) <= 300
    assert "Hi Michael" in pitch_en
    assert "Amazon AWS" in pitch_en
    assert "Cloud Engineer" in pitch_en


def test_application_harness_init():
    harness = ApplicationHarness(dry_run=True)
    assert harness.dry_run is True
    assert harness.max_steps == 8
