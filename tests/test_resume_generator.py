import pytest
from pathlib import Path
from hawk.resume.generator import render_ats_resume_html, generate_tailored_pdf


def test_render_ats_resume_html():
    profile_data = {
        "personal": {
            "first_name": "Alex",
            "last_name": "Smith",
            "email": "alex.smith@example.com",
            "phone": "+1 555 0199",
            "city": "Austin",
            "country": "United States",
        },
        "links": {
            "linkedin": "linkedin.com/in/alexsmith",
            "github": "github.com/alexsmith",
        },
        "professional": {
            "headline": "Systems Engineer",
            "summary": "Experienced systems engineer with infrastructure and automation background.",
        },
        "education": {
            "degree": "Bachelor's",
            "field": "Computer Science",
            "school": "State University",
            "graduation_year": "2025",
        },
        "languages": {
            "english": "Native",
        },
    }

    resume_data = {
        "experience_details": [
            {
                "position": "Infrastructure Engineer",
                "company": "Tech Corp",
                "employment_period": "2022 - Present",
                "location": "Austin, TX",
                "key_responsibilities": [
                    {"description": "Automated deployment pipelines and server configurations."}
                ],
            }
        ]
    }

    html = render_ats_resume_html(
        profile_data=profile_data,
        resume_data=resume_data,
        job_title="DevOps Engineer",
        tailored_headline="DevOps & Infrastructure Engineer",
        tailored_summary="Experienced in CI/CD and cloud automation.",
        highlighted_skills=["Docker", "Kubernetes", "CI/CD"],
    )

    assert "Alex Smith" in html
    assert "DevOps & Infrastructure Engineer" in html
    assert "Experienced in CI/CD and cloud automation." in html
    assert "Docker • Kubernetes • CI/CD" in html
    assert "Tech Corp" in html
    assert "Automated deployment pipelines" in html
    assert "State University" in html


@pytest.mark.asyncio
async def test_generate_tailored_pdf(tmp_path):
    pdf_path = await generate_tailored_pdf(
        job_id="test_unit_456",
        job_title="Systems Engineer",
        tailored_headline="Systems Specialist",
        tailored_summary="Automated infrastructure expert.",
        highlighted_skills=["Linux", "Python", "Docker"],
        output_dir=tmp_path,
    )

    assert Path(pdf_path).exists()
    assert Path(pdf_path).stat().st_size > 1000
