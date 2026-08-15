"""Interactive onboarding wizard and resume parser for hawk."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import click
import pypdf
import yaml

from hawk.config import (
    DATA_DIR,
    PROFILE_PATH,
    SETTINGS_PATH,
    ApplySettings,
    Education,
    LinkedInSettings,
    Links,
    PersonalInfo,
    Preferences,
    ProfessionalInfo,
    Salary,
    ScoringSettings,
    ScreeningPreferences,
    Settings,
    UserProfile,
    WorkAuthorization,
    save_profile,
    save_settings,
)
from hawk.storage import init_db

# Common tech skills dictionary for regex matching
_TECH_SKILLS_CATALOG: list[str] = [
    "Python", "JavaScript", "TypeScript", "Go", "Golang", "Rust", "Java", "C++", "C#", ".NET",
    "Docker", "Kubernetes", "EKS", "GKE", "AKS", "Terraform", "Ansible", "Helm", "OpenShift",
    "AWS", "Amazon Web Services", "GCP", "Google Cloud", "Azure", "Linux", "Bash", "Shell",
    "CI/CD", "GitHub Actions", "GitLab CI", "Jenkins", "ArgoCD", "Flux", "Prometheus", "Grafana",
    "ELK", "Elasticsearch", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka", "RabbitMQ",
    "FastAPI", "Django", "Flask", "Node.js", "Express", "React", "Vue", "Next.js", "Angular",
    "GraphQL", "REST API", "Microservices", "Nginx", "Apache", "Git", "SRE", "DevOps",
]


def extract_text_from_file(file_path: Path | str) -> str:
    """Extract full raw text content from PDF, YAML, JSON, Markdown, or TXT file."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()
    if ext == ".pdf":
        reader = pypdf.PdfReader(str(path))
        pages_text = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages_text)
    elif ext in (".yaml", ".yml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return json.dumps(data, indent=2, ensure_ascii=False) if isinstance(data, dict) else str(data)
    elif ext == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(data, indent=2, ensure_ascii=False) if isinstance(data, dict) else str(data)
    else:
        return path.read_text(encoding="utf-8", errors="ignore")


def parse_entities_from_resume_text(text: str) -> dict[str, Any]:
    """Parse candidate entities, contact details, and skills from resume text."""
    entities: dict[str, Any] = {
        "first_name": "",
        "last_name": "",
        "email": "",
        "phone": "",
        "city": "",
        "country": "",
        "linkedin": "",
        "github": "",
        "headline": "",
        "summary": "",
        "years_of_experience": "3",
        "current_title": "",
        "skills": {},
    }

    # 1. Email extraction
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    if email_match:
        entities["email"] = email_match.group(0).strip()

    # 2. Phone extraction
    phone_match = re.search(r"(\+?\d{1,3}[\s-]?)?(\(?\d{2,4}\)?[\s-]?)?\d{3,5}[\s-]?\d{4}", text)
    if phone_match:
        entities["phone"] = phone_match.group(0).strip()

    # 3. LinkedIn & GitHub links
    li_match = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)", text, re.IGNORECASE)
    if li_match:
        entities["linkedin"] = f"linkedin.com/in/{li_match.group(1)}"

    gh_match = re.search(r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_-]+)", text, re.IGNORECASE)
    if gh_match:
        entities["github"] = f"github.com/{gh_match.group(1)}"

    # 4. Name extraction from header
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:5]:
        # Filter out lines that look like emails, urls, or phone numbers
        if "@" in line or "http" in line or "linkedin" in line or re.search(r"\d{4,}", line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            entities["first_name"] = words[0]
            entities["last_name"] = " ".join(words[1:])
            break

    # 5. Skills extraction
    text_lower = text.lower()
    detected_skills: dict[str, int] = {}
    for skill in _TECH_SKILLS_CATALOG:
        skill_lower = skill.lower()
        if re.search(r"\b" + re.escape(skill_lower) + r"\b", text_lower):
            detected_skills[skill_lower] = 3
    entities["skills"] = detected_skills

    # 6. Experience years
    exp_match = re.search(r"(\d+)\+?\s*(?:years|años)\s*(?:of experience|de experiencia)?", text, re.IGNORECASE)
    if exp_match:
        entities["years_of_experience"] = exp_match.group(1)

    return entities


def run_interactive_onboarding() -> None:
    """Execute guided onboarding CLI interview and persist user data."""
    click.echo("\n" + "=" * 60)
    click.echo(click.style("   🦅 Bienvenido al Asistente de Onboarding de hawk", fg="cyan", bold=True))
    click.echo("=" * 60 + "\n")
    click.echo("Vamos a configurar tu perfil profesional y tus preferencias de búsqueda.")
    click.echo("Toda tu información personal se guardará en " + click.style("data/", fg="yellow") + " (100% ignorada en Git).\n")

    has_cv = click.confirm("¿Tienes un archivo de CV / currículum para importar (PDF/YAML/TXT)?", default=False)
    parsed: dict[str, Any] = {}

    if has_cv:
        while True:
            cv_path_str = click.prompt("Ruta a tu archivo de CV", type=str)
            cv_path = Path(cv_path_str.strip('"').strip("'")).resolve()
            if cv_path.exists():
                try:
                    click.echo(f"Leyendo y analizando {cv_path.name}...")
                    raw_text = extract_text_from_file(cv_path)
                    parsed = parse_entities_from_resume_text(raw_text)
                    click.echo(click.style("✓ Información extraída del CV con éxito.", fg="green"))
                    break
                except Exception as exc:
                    click.echo(click.style(f"Error al leer el archivo: {exc}", fg="red"))
                    if not click.confirm("¿Intentar con otra ruta?", default=True):
                        break
            else:
                click.echo(click.style(f"No se encontró el archivo en: {cv_path}", fg="red"))
                if not click.confirm("¿Intentar con otra ruta?", default=True):
                    break

    # ── 1. Personal Information ───────────────────────────────────────────────
    click.echo("\n" + click.style("── 1. Información Personal ──", fg="cyan", bold=True))
    first_name = click.prompt("Nombre", default=parsed.get("first_name", ""))
    last_name = click.prompt("Apellido", default=parsed.get("last_name", ""))
    email = click.prompt("Email", default=parsed.get("email", ""))
    phone = click.prompt("Teléfono (con prefijo de país, ej: +54 9 11 ...)", default=parsed.get("phone", ""))
    city = click.prompt("Ciudad", default=parsed.get("city", "Buenos Aires"))
    country = click.prompt("País", default=parsed.get("country", "Argentina"))
    linkedin_url = click.prompt("LinkedIn Profile URL (o path)", default=parsed.get("linkedin", ""))
    github_url = click.prompt("GitHub Profile URL (o path)", default=parsed.get("github", ""))

    # ── 2. Professional Profile ───────────────────────────────────────────────
    click.echo("\n" + click.style("── 2. Perfil Profesional ──", fg="cyan", bold=True))
    current_title = click.prompt("Título profesional actual", default=parsed.get("current_title", "DevOps Engineer"))
    years_exp = click.prompt("Años totales de experiencia", default=str(parsed.get("years_of_experience", "3")))
    headline = click.prompt(
        "Titular profesional (Headline para CV y LinkedIn)",
        default=parsed.get("headline", f"{current_title} | Cloud Infrastructure | CI/CD | Docker | Kubernetes"),
    )
    summary = click.prompt(
        "Resumen profesional (Summary)",
        default=parsed.get(
            "summary",
            f"{current_title} con experiencia en automatización de infraestructura, pipelines CI/CD y despliegues en contenedores.",
        ),
    )

    # ── 3. Skills ─────────────────────────────────────────────────────────────
    click.echo("\n" + click.style("── 3. Habilidades Técnicas (Skills) ──", fg="cyan", bold=True))
    default_skills_str = ", ".join(parsed.get("skills", {}).keys()) or "Docker, Kubernetes, AWS, Terraform, CI/CD, Linux, Python, Bash"
    skills_raw = click.prompt("Habilidades separadas por coma", default=default_skills_str)
    skills_dict: dict[str, int] = {}
    for s in skills_raw.split(","):
        s_clean = s.strip().lower()
        if s_clean:
            skills_dict[s_clean] = int(years_exp) if str(years_exp).isdigit() else 3

    # ── 4. Job Preferences & Settings ─────────────────────────────────────────
    click.echo("\n" + click.style("── 4. Preferencias de Búsqueda y Filtros ──", fg="cyan", bold=True))
    target_positions_raw = click.prompt("Puestos objetivo a buscar (separados por coma)", default=current_title)
    target_positions = [p.strip() for p in target_positions_raw.split(",") if p.strip()]

    target_locations_raw = click.prompt("Ubicaciones objetivo (separadas por coma)", default="Remote, Argentina")
    target_locations = [loc.strip() for loc in target_locations_raw.split(",") if loc.strip()]

    remote_only = click.confirm("¿Filtrar exclusivamente puestos remotos?", default=True)
    expected_salary = click.prompt("Pretensión salarial (ej: $5000 USD/month)", default="$5000 USD/month")
    daily_max = click.prompt("Máximo de aplicaciones diarias (safety limit)", default=10, type=int)

    # ── 5. Work Authorization ─────────────────────────────────────────────────
    click.echo("\n" + click.style("── 5. Autorización Laboral ──", fg="cyan", bold=True))
    work_auth = click.confirm(f"¿Estás legalmente autorizado/a para trabajar en {country}?", default=True)
    sponsorship = click.confirm("¿Requiere patrocinio de visa (Visa sponsorship)?", default=False)
    b2b_ok = click.confirm("¿Aceptas contratos como Contractor independiente (B2B)?", default=True)

    # ── Building Profile & Settings Objects ───────────────────────────────────
    personal = PersonalInfo(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        city=city,
        country=country,
    )
    links = Links(
        linkedin=linkedin_url,
        github=github_url,
    )
    prof = ProfessionalInfo(
        headline=headline,
        summary=summary,
        years_of_experience=str(years_exp),
        current_title=current_title,
    )
    work_auth_obj = WorkAuthorization(
        authorized=work_auth,
        sponsorship_required=sponsorship,
        country=country,
    )
    pref_obj = Preferences(
        remote_only=remote_only,
    )
    screening_obj = ScreeningPreferences(
        b2b_contractor_ok=b2b_ok,
        us_work_auth=work_auth,
        requires_sponsorship=sponsorship,
    )
    salary_obj = Salary(
        expected=expected_salary,
    )

    profile = UserProfile(
        personal=personal,
        links=links,
        professional=prof,
        work_authorization=work_auth_obj,
        education=Education(),
        skills=skills_dict,
        salary=salary_obj,
        preferences=pref_obj,
        screening_preferences=screening_obj,
    )

    settings = Settings(
        linkedin=LinkedInSettings(
            positions=target_positions,
            locations=target_locations,
            easy_apply_only=True,
        ),
        apply=ApplySettings(
            daily_max=daily_max,
            dry_run=True,
        ),
        scoring=ScoringSettings(),
    )

    # ── Persist & Initialize data/ structure ──────────────────────────────────
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "resumes").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "cover_letters").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "browser").mkdir(parents=True, exist_ok=True)

    # Initialize SQLite database (tables: jobs, applications, daily_limits)
    init_db(output_dir=DATA_DIR)

    # Save active profile and settings
    save_profile(profile, path=PROFILE_PATH)
    save_settings(settings, data_dir=DATA_DIR)

    click.echo("\n" + "=" * 60)
    click.echo(click.style("   🎉 ¡Onboarding completado con éxito!", fg="green", bold=True))
    click.echo("=" * 60)
    click.echo(f"  ✓ Perfil personal guardado en:      {PROFILE_PATH}")
    click.echo(f"  ✓ Configuración guardada en:        {SETTINGS_PATH}")
    click.echo(f"  ✓ Base de datos inicializada en:    {DATA_DIR / 'hawk.db'}")
    click.echo(f"  ✓ Directorios de CVs y cartas:      {DATA_DIR / 'resumes'} y {DATA_DIR / 'cover_letters'}")
    click.echo(f"  ✓ Directorio del navegador:         {DATA_DIR / 'browser'}")
    click.echo(click.style("\nTodo el directorio data/ está listo, protegido y excluido de Git.", fg="yellow"))
    click.echo("Ya puedes usar 'hawk run' o controlar hawk desde tu agente MCP.\n")
