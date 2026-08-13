# hawk — plan de reescritura

Reescritura moderna de `jobs_applier_ai_agent_aihawk` (AIHawk). Mismo objetivo: postular
automaticamente a trabajos **Easy Apply de LinkedIn** usando la cuenta personal, con un
modelo controlando el navegador. La diferencia: en vez de `selenium + scripts con selectores
hardcodeados + cadenas de prompts internas`, hawk expone **servidores MCP** y deja que un
agente CLI (opencode, agy/Antigravity, Claude Code, etc.) orqueste el flujo.

## 1. Investigacion (resumen)

| Problema del viejo | Moderno hoy |
|---|---|
| Selenium + ChromeDriver + undetected-chromedriver | Playwright / CDP directo, o `invisible_playwright` (Firefox patcheado a nivel C++, del mismo autor de AIHawk, pasa suites de deteccion) |
| LLM embebido via langchain + prompts internos | Agente externo via MCP (opencode/agy) + LLM directo para screening/tailoring |
| Cadenas hardcodeadas de campos | Agente de browser: loop percibir-actuar sobre el DOM (accesibility tree) en vez de selectores |
| Validacion a mano (ConfigValidator) | pydantic-settings + YAML |
| Login automatizado (riesgo alto de ban) | Sesion con perfil persistente, login manual 1 vez |
| Sin limite de ritmo (con la cuenta de AIHawk banearon cuentas) | Dry-run + tope diario (3-5) + delays humanizados + human-in-the-loop |

Tecnologias clave relevadas:
- **MCP** (Model Context Protocol): estandar para conectar agentes a herramientas. Servidores de browser: Playwright MCP, Chrome DevTools MCP, Browser MCP (extension Chrome que reusa el perfil real).
- **browser-use** (Python, ~100k stars): da al LLM control de un browser real via CDP; expone su propio MCP server/client; BYOK LLMs; `Controller` para side-effects (guardar, llamar APIs). Es el "navegador que el agente ve", pero en nuestra arquitectura el agente CLI ya ve el browser via MCP, asi que lo usamos solo como referencia/utilidad opcional.
- **invisible_playwright** (feder-cr): drop-in de Playwright con Firefox anti-detect; resuelve el problema de deteccion que AIHawk tenia a escala.
- **Framework de agentes**: LangGraph (patron web_voyager), OpenAI Agents SDK, CrewAI. En esta arquitectura el agente CLI es el orquestador; no hace falta otro framework.
- **Stealth**: patchright, nodriver, camoufox, CloakBrowser, undetected-playwright. Session reuse >> login automatizado (el autor de AIHawk recomienda explícitamente reusar sesion en vez de automatizar el login).

## 2. Arquitectura

```
+--------------------------------------------------------------+
|  Agente CLI (opencode / agy / claude code ...)  <- cerebro    |
|  ve herramientas MCP, decide, llama, confirma con el humano  |
+--------------------------+-----------------------------------+
                           | MCP (stdio)
+--------------------------v-----------------------------------+
|  hawk-mcp (servidor MCP, python, FastMCP)                    |
|                                                              |
|  browser_*    snapshot DOM/a11y, click, type, scroll,        |
|               upload file, screenshot, printToPDF            |
|  session_*    chequear/levantar sesion LinkedIn              |
|  search_*     armar URLs de busqueda Easy Apply              |
|  job_*        extraer detalles, score de aptitud             |
|  tailor_*     generar CV + cover letter PDF                  |
|  apply_*      llenar el formulario Easy Apply (con heuristica|
|               + human-in-the-loop)                           |
|  store_*      guardar aplicaciones y estado (SQLite + JSON)  |
+--------------------------+-----------------------------------+
                           | CDP
+--------------------------v-----------------------------------+
|  Browser con perfil persistente (Chromium o invisible_ff)    |
|  sesion de LinkedIn logueada manualmente una vez             |
+--------------------------------------------------------------+
```

- El agente CLI es el orquestador: recibe el objetivo ("postulate a backend roles en Berlin,
  Easy Apply"), arma el plan, y llama las herramientas MCP de hawk en el orden correcto.
- hawk no decide: provee tools bien descriptas + un doc de workflow (`docs/workflow.md`) y
  `AGENTS.md` para que el agente sepa como encadenar el pipeline.
- `hawk run` = modo script deterministico (sin agente) para debug y para CI/dry-run.

## 3. Pipeline (workflow que ejecuta el agente)

1. **Bootstrap**: levantar browser con perfil persistente (`profiles/linkedin/`), verificar
   sesion (`session_check`). Si no hay sesion -> aviso al humano para loguear manualmente.
2. **Discover**: armar URL de busqueda con filtros (Easy Apply `f_AL=true`, experiencia,
   ubicacion, fecha, distancia) y listar trabajos.
3. **Extract**: para cada trabajo, snapshot del DOM/a11y -> rol, empresa, ubicacion, link,
   descripcion. (a11y tree > screenshots: mas barato y estructurado).
4. **Screen**: score de aptitud con LLM (umbral >= 7, igual que JOB_SUITABILITY_SCORE),
   blacklists de empresa/titulo/ubicacion.
5. **Tailor**: generar resume y cover letter por trabajo (prompts + templates HTML/CSS) y
   exportar a PDF via CDP `Page.printToPDF` (igual que el viejo).
6. **Apply**: llenar el wizard Easy Apply (texto, numerico, selects, radios, checkbox, upload
   de archivo). Campos no reconocidos -> `ask_human` (pausa y pregunta al usuario). Al final
   confirmar el Submit.
7. **Record + rate limit**: guardar aplicacion (JSON + PDFs, como ApplicationSaver), tope
   diario configurable (default 3-5), delays humanizados entre pasos, dry-run mode.

## 4. Tech stack

- Python 3.12, `uv` (venv + deps), `pyproject.toml`
- MCP: `mcp` (python-sdk) con `FastMCP`
- Browser: Playwright-Python + CDP (con `invisible_playwright` como opcion stealth)
- LLM: abstraccion propia (`hawk/llm/provider.py`) para openai / anthropic / gemini / ollama;
  keys en `secrets.yaml` o `.env`
- Modelos: pydantic (Resume, JobApplicationProfile, Settings)
- Templates: jinja2 + CSS (se reusan los estilos del proyecto viejo si conviene)
- Storage: SQLite (stdlib) + carpeta `output/` con JSON/PDF por aplicacion
- Lint/test: ruff + pytest

## 5. Estructura de directorios

```
hawk/
├── pyproject.toml
├── uv.lock
├── README.md
├── AGENTS.md                 # instrucciones para opencode/agy sobre como usar hawk
├── opencode.json             # ejemplo de wiring MCP (mcpServers -> hawk)
├── config/
│   ├── settings.yaml         # preferencias de busqueda, threshold, topes, dry_run
│   └── secrets.yaml          # llm keys  (gitignored)
├── profiles/                 # perfiles de browser persistente (gitignored)
├── output/                   # PDFs y JSONs de aplicaciones (gitignored)
├── hawk/
│   ├── __init__.py
│   ├── cli.py                # `hawk mcp` | `hawk run` | `hawk doctor` | `hawk session`
│   ├── mcp_server.py         # FastMCP: registra todos los tools
│   ├── settings.py           # pydantic-settings
│   ├── browser/
│   │   ├── driver.py         # launch persistente + stealth
│   │   ├── dom.py            # snapshot a11y/DOM con indices estables, click/type/upload
│   │   └── pdf.py            # printToPDF
│   ├── linkedin/
│   │   ├── session.py        # check/refresh de sesion
│   │   ├── search.py         # URLs de busqueda Easy Apply + listado
│   │   ├── extract.py        # extraccion de detalles
│   │   └── easy_apply.py     # heuristica de formulario + ask_human
│   ├── llm/
│   │   ├── provider.py       # openai/anthropic/gemini/ollama
│   │   ├── screening.py      # score de aptitud
│   │   └── tailoring.py      # resume + cover letter
│   ├── resume/
│   │   ├── models.py         # pydantic Resume / JobApplicationProfile
│   │   └── templates/        # HTML base + estilos CSS
│   ├── storage/
│   │   ├── db.py             # schema SQLite
│   │   └── saver.py          # ApplicationSaver modernizado
│   └── workflow.py           # pipeline de referencia (lo usa `hawk run` y documenta al agente)
└── tests/
```

## 6. Mapeo viejo -> nuevo

| AIHawk (viejo) | hawk (nuevo) |
|---|---|
| `config.py` + `ConfigValidator` | `settings.py` (pydantic-settings) + `config/settings.yaml` |
| `FileManager.validate_data_folder` | `settings.py` + `hawk doctor` |
| `src/resume_schemas/resume.py` | `hawk/resume/models.py` (pydantic, ya lo era) |
| `GPTAnswerer` (llm_manager) | `hawk/llm/provider.py` + `screening.py` + `tailoring.py` |
| `LLMLogger` | storage en SQLite + `output/open_ai_calls.json` |
| `chrome_utils.init_browser` (selenium) | `browser/driver.py` (CDP + perfil persistente) |
| `HTML_to_PDF` | `browser/pdf.py` (mismo `Page.printToPDF`) |
| `ResumeFacade` / `ResumeGenerator` / `StyleManager` | `resume/templates/` + `llm/tailoring.py` |
| `ApplicationSaver` | `storage/saver.py` |
| `prompt_user_action` (inquirer) | el agente CLI decide; `ask_human` para campos desconocidos |
| login automatizado | sesion persistente (manual 1 vez) |

## 7. Roadmap

- **F0 - Esqueleto**: `pyproject.toml` + uv, config/settings, storage (SQLite), `cli.py`, servidor MCP stub que se levanta y se ve desde opencode (`hawk mcp`).
- **F1 - Browser**: launch con perfil persistente, snapshot DOM/a11y, click/type, `printToPDF`. Test manual: `hawk run --check-session` abre LinkedIn logueado.
- **F2 - Discovery/Extract**: URLs de busqueda Easy Apply, listado de trabajos, extraccion de detalles.
- **F3 - Screening**: score de aptitud LLM + blacklists.
- **F4 - Tailoring**: generacion de resume/cover PDF (reusar templates de estilos viejos).
- **F5 - Easy Apply**: wizard de formulario con heuristica + `ask_human`, dry-run, tope diario, delays.
- **F6 - Wiring del agente**: `AGENTS.md` + `docs/workflow.md` + `opencode.json`/`.mcp.json`; probar "postulate a 5 backend roles en Berlin con easy apply".

## 8. Riesgos y mitigaciones

- **Riesgo principal: restriccion de cuenta.** LinkedIn User Agreement 8.2 prohibe bots/automatizacion; las herramientas de Easy Apply tienen historial malo. Mitigaciones: perfil persistente y sesion manual (sin automatizar login), volumen bajo (tope diario default 3-5), delays humanizados, `dry_run` default, pausa + `ask_human` ante CAPTCHA o campo desconocido, correr desde IP propia.
- **Cambios del DOM de LinkedIn**: el agente + snapshot semanticos (a11y) aguantan redisenos mejor que selectores hardcodeados; se mantienen selectors solo como fallback.
- **Costo**: model barato para screening y parsing; `max_steps` y tope diario como rail de seguridad.
- **Sesion que caduca**: `session_check` al inicio y refresh manual cada tanto.

## 9. Fuentes

- Codigo original: `C:\Users\Laureano\Código\Ajeno\jobs_applier_ai_agent_aihawk`
- MCP: anthropic.com/news/model-context-protocol; repos `microsoft/playwright-mcp`, `browsermcp/mcp`, `browser-use/browser-use`
- Stealth: `feder-cr/invisible_playwright` (docs: session-reuse > login-automation, ai-browser-agents-stealth)
- Easy Apply: ejemplos `Bavishsaireddy/Linkedin-Easy-Apply`, `tmykhaylovsky/linkedin-job-automation2`; advertencias de restriccion en resumly/resuminder/teemo
