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
    html = render_ats_cover_letter_html(
        job_title="DevOps Engineer",
        company="TechCorp",
        hiring_manager="Jane Smith",
    )
    assert "Jane Smith" in html
    assert "TechCorp" in html
    assert "DevOps Engineer" in html
    assert "Laureano" in html
    assert "lflamonega@gmail.com" in html


def test_application_harness_init():
    harness = ApplicationHarness(dry_run=True)
    assert harness.dry_run is True
    assert harness.max_steps == 8
