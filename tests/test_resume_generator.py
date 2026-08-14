import pytest
from pathlib import Path
from hawk.resume.generator import render_ats_resume_html, generate_tailored_pdf


def test_render_ats_resume_html():
    profile_data = {
        "personal": {
            "first_name": "Laureano",
            "last_name": "Francisco Lamonega",
            "email": "lflamonega@gmail.com",
            "phone": "221 695 9945",
            "city": "Berisso",
            "country": "Argentina",
        },
        "links": {
            "linkedin": "linkedin.com/in/lflamonega",
            "github": "github.com/lflamonega",
        },
        "professional": {
            "headline": "DevOps Engineer",
            "summary": "Experienced DevOps Engineer with AWS and CI/CD background.",
        },
        "education": {
            "degree": "Bachelor's",
            "field": "Information Systems",
            "school": "UNLP",
            "graduation_year": "2027",
        },
        "languages": {
            "english": "Professional",
        },
    }

    html = render_ats_resume_html(
        profile_data=profile_data,
        job_title="Data Platform Engineer",
        tailored_headline="Data Platform & DevOps Engineer",
        tailored_summary="Tailored summary for data engineering role.",
        highlighted_skills=["AWS", "Terraform", "CI/CD", "Docker"],
    )

    assert "Laureano Francisco Lamonega" in html
    assert "Data Platform & DevOps Engineer" in html
    assert "Tailored summary for data engineering role." in html
    assert "AWS • Terraform • CI/CD • Docker" in html
    assert "UNLP" in html


@pytest.mark.asyncio
async def test_generate_tailored_pdf(tmp_path):
    pdf_path = await generate_tailored_pdf(
        job_id="test_unit_123",
        job_title="DevOps Engineer",
        tailored_headline="DevOps Specialist",
        tailored_summary="Unit test summary.",
        highlighted_skills=["Linux", "Docker", "AWS"],
        output_dir=tmp_path,
    )

    assert Path(pdf_path).exists()
    assert Path(pdf_path).stat().st_size > 1000
