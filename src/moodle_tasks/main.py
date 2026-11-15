import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .errors import MoodleAuthenticationError, MoodleHTTPError, redact_credentials
from .storage import default_env_file


@dataclass(frozen=True)
class Config:
    base_url: str
    username: str
    password: str = field(repr=False)
    session_cache: bool = True


@dataclass(frozen=True)
class Assignment:
    title: str
    url: str
    content: str
    due_date: str
    status: str
    submitted: bool | None
    course: str = ""
    attachments: list[dict[str, str]] = field(default_factory=list)
    opens_at: str | None = None
    due_at: str | None = None
    grade: str | None = None
    requires_submission: bool | None = None
    links: list[dict[str, str]] = field(default_factory=list)
    group: str | None = None
    grading_status: str | None = None
    rubric: dict | None = None
    images: list[dict[str, str]] = field(default_factory=list)


# Partes que Moodle añade al nombre completo del curso, sea cual sea la carrera:
# el paralelo delante («A -- »), la carrera con el año de la malla («/ SOFTWARE 2024 - NS»)
# y los códigos del curso y del periodo («--1208690--20262-1»).
COURSE_SECTION = re.compile(r"^[A-Z0-9]{1,3}\s*--\s*")
COURSE_SUFFIX = re.compile(r"\s*/\s*[^/]*\b(?:19|20)\d{2}\b[^/]*$|\s*--\s*\d.*$")


def course_name(raw: str | None) -> str:
    """Nombre de la materia sin el paralelo, la carrera ni los códigos del periodo que Moodle le añade.

    Una barra dentro del nombre («ÉTICA / DEONTOLOGÍA») se conserva: solo se recorta si lo que sigue
    lleva el año de la malla, como el segmento de la carrera.
    """
    name = COURSE_SECTION.sub("", clean_text(raw))
    return COURSE_SUFFIX.sub("", name).strip()


def is_pending(task: Assignment) -> bool:
    return task.submitted is not True and task.requires_submission is not False


ENV_FILE = default_env_file()
NO_DESCRIPTION = "No se encontró una descripción visible."


def config_values(env_file: Path | None = None) -> dict[str, str | None]:
    return {**dotenv_values(env_file or default_env_file(), interpolate=False), **os.environ}


def required_env(name: str, values: dict[str, str | None]) -> str:
    value = (values.get(name) or "").strip()
    if not value:
        raise ValueError(f"Falta la variable {name}. Ejecuta mcp-moodle run para configurar tu cuenta.")
    return value


OPT_OUT = ("0", "false", "no", "off", "n")


def load_config(env_file: Path | None = None) -> Config:
    # El archivo se lee una sola vez: el entorno gana sobre él, salvo en la opción de privacidad de abajo.
    file_values = dotenv_values(env_file or default_env_file(), interpolate=False)
    values = {**file_values, **os.environ}
    return Config(
        base_url=required_env("MOODLE_URL", values).rstrip("/"),
        username=required_env("MOODLE_USERNAME", values),
        password=required_env("MOODLE_PASSWORD", values),
        # Desactivar la caché de sesión es una opción de privacidad: gana si lo indica el archivo o el entorno.
        session_cache=not any((value or "").strip().lower() in OPT_OUT for value in (
            values.get("MOODLE_SESSION_CACHE"), file_values.get("MOODLE_SESSION_CACHE"))),
    )


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def first_text(page: Page, selectors: str) -> str:
    locator = page.locator(selectors).first
    if not locator.count():
        return ""
    try:
        return clean_text(locator.text_content())
    except PlaywrightTimeoutError:
        return ""


def open_page(page: Page, url: str) -> None:
    response = page.goto(url, wait_until="domcontentloaded")
    if response is None:
        raise RuntimeError(f"Moodle no pudo cargar la página (sin respuesta): {url}")
    if response.status >= 400:
        raise MoodleHTTPError(response.status, url)


def login(page: Page, config: Config) -> None:
    open_page(page, f"{config.base_url}/login/index.php")
    microsoft = page.get_by_role("link", name="Microsoft 365 Uleam", exact=True)
    if microsoft.count() and config.username.lower().endswith(("@live.uleam.edu.ec", "@uleam.edu.ec")):
        login_microsoft(page, config)
        return
    login_form = page.locator("form#login, form[action*='login']")
    if login_form.count() == 0:
        if page.locator("a[href*='/login/logout.php']").count():
            return
        raise RuntimeError("No se encontró el formulario de acceso ni una sesión iniciada en Moodle.")

    page.locator("input[name='username']").fill(config.username)
    page.locator("input[name='password']").fill(config.password)
    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
        page.locator("button[type='submit'], input[type='submit']").first.click()
    response = navigation.value
    if response is not None and response.status >= 400:
        raise MoodleHTTPError(response.status, page.url)

    if "/login/" in page.url:
        if page.locator("input[name='username'], input[name='password']").count():
            raise MoodleAuthenticationError("Moodle no aceptó el usuario o la contraseña.")
        raise RuntimeError("No se pudo confirmar el inicio de sesión en Moodle.")

    if not page.locator("a[href*='/login/logout.php']").count():
        raise RuntimeError("No se pudo confirmar una sesión iniciada en Moodle.")


def submit_microsoft_password(page: Page, password_value: str) -> None:
    """Espera la etapa de contraseña y actualiza el formulario con teclado."""
    password = page.locator('input[name="passwd"]')
    submit = page.get_by_role("button", name=re.compile(r"^(Sign in|Iniciar sesión|Acceder)$", re.I))
    try:
        password.wait_for(state="visible", timeout=30_000)
        submit.wait_for(state="visible", timeout=30_000)
        for _ in range(2):
            password.fill("")
            password.press_sequentially(password_value, delay=40)
            password.press("Tab")
            if password.input_value() == password_value:
                submit.click()
                return
    except Exception:
        # Los errores de escritura de Playwright pueden incluir el argumento.
        raise RuntimeError("No se pudo completar el campo de contraseña de Microsoft. El formulario no terminó de estar disponible.") from None
    raise RuntimeError("Microsoft vació el campo de contraseña antes de enviarlo. No se pudo completar el formulario.")


def login_microsoft(page: Page, config: Config) -> None:
    """Acceso institucional observado en ULEAM; no resuelve códigos ni MFA."""
    page.get_by_role("link", name="Microsoft 365 Uleam", exact=True).click()
    email = page.locator('input[name="loginfmt"]')
    email.wait_for(state="visible", timeout=30_000)
    email.fill(config.username)
    page.locator("#idSIButton9").click()
    submit_microsoft_password(page, config.password)
    selected_again = False
    retried_empty_field = False
    for _ in range(120):
        if page.url.startswith(config.base_url + "/") and page.locator("a[href*='/login/logout.php']").count():
            return
        for selector in ("#passwordError", "#usernameError", "#errorText"):
            error = page.locator(selector).first
            if error.count() and error.is_visible() and clean_text(error.inner_text()):
                message = clean_text(error.inner_text())
                if re.search(r"please enter your password|(?:escriba|introduzca|ingresa|ingrese) (?:su |tu |la )?contraseña", message, re.I):
                    if not retried_empty_field:
                        retried_empty_field = True
                        submit_microsoft_password(page, config.password)
                        break
                    raise RuntimeError("Microsoft sigue detectando el campo de contraseña vacío. Falló el envío del formulario; no se confirmó el acceso.")
                raise MoodleAuthenticationError("Microsoft no aceptó el acceso: " + message)
        alternate = page.get_by_role("link", name=re.compile(
            r"Use a different account|Usar una cuenta diferente|Utilizar otra cuenta", re.I))
        if not selected_again and alternate.count() and alternate.first.is_visible():
            alternate.first.click()
            profile = page.get_by_text(config.username, exact=True).first
            profile.wait_for(state="visible", timeout=20_000)
            profile.click()
            selected_again = True
        stay = page.get_by_role("button", name="No", exact=True)
        if stay.count() and stay.first.is_visible() and page.get_by_text(re.compile(
            r"Stay signed in|mantener la sesión iniciada", re.I)).count():
            stay.first.click()
        page.wait_for_timeout(500)
    raise RuntimeError("Microsoft requiere completar el acceso o una verificación adicional. No se confirmó una sesión de Moodle.")


def submission_state(status: str) -> bool | None:
    if re.search(r"not submitted|no (?:se ha )?(?:entregad|enviado)|sin entrega|borrador|draft|no attempt|ning[uú]n env[ií]o|todav[ií]a no se han realizado env[ií]os", status, re.IGNORECASE):
        return False
    if re.search(r"submitted for grading|entregad[oa] para|enviad[oa] para|^submitted$|^entregad[oa]$|^enviad[oa]$", status, re.IGNORECASE):
        return True
    return None


STATUS_ROWS = """table => Array.from(table.querySelectorAll('tr')).map(row => {
    const cells = row.querySelectorAll('th, td');
    if (cells.length < 2) return null;
    const value = cells[cells.length - 1];
    // La fila de comentarios trae el formulario y su plantilla, no un estado.
    if (value.querySelector('.commentscontainer, textarea')) return null;
    return [cells[0].innerText || cells[0].textContent || '', value.innerText || value.textContent || ''];
}).filter(Boolean)"""
RUBRIC = """root => {
    const text = node => node ? (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
    const criteria = Array.from(root.querySelectorAll('tr.criterion')).map(row => ({
        criterion: text(row.querySelector('td.description')),
        levels: Array.from(row.querySelectorAll('td.level')).map(level => ({
            points: text(level.querySelector('.scorevalue')), definition: text(level.querySelector('.definition'))})),
    })).filter(item => item.criterion || item.levels.length);
    return criteria.length ? criteria : null;
}"""
STATUS_LABELS = {
    "status": r"submission status|estado de (?:la )?entrega",
    "grading_status": r"grading status|estado de (?:la )?calificaci[oó]n",
    "group": r"^(?:group|grupo)$",
}


def read_submission_summary(page: Page) -> dict:
    """Filas de la tabla «Estado de la entrega» por separado y la rúbrica como criterios y niveles."""
    summary: dict = {}
    table = page.locator(".submissionstatustable table").first
    rows = table.evaluate(STATUS_ROWS) if table.count() else []
    for label, value in rows:
        label, value = clean_text(label), clean_text(value)
        for key, pattern in STATUS_LABELS.items():
            if key not in summary and value and re.search(pattern, label, re.IGNORECASE):
                summary[key] = value[:300]
    rubric = page.locator(".gradingform_rubric").first
    criteria = rubric.evaluate(RUBRIC) if rubric.count() else None
    if criteria:
        summary["rubric"] = {"description": first_text(page, ".gradingform_rubric-description")[:2_000],
                             "criteria": criteria[:60]}
    return summary


def open_authenticated_page(page: Page, url: str, config: Config) -> None:
    """Renueva una sesión vencida una vez, sin leer el formulario como una tarea."""
    for attempt in range(2):
        open_page(page, url)
        if not ("/login/" in page.url or page.locator("input[name='username'], input[name='password'], input[name='loginfmt']").count()):
            return
        if attempt == 0:
            login(page, config)
    raise MoodleAuthenticationError("La sesión de Moodle sigue vencida después de volver a iniciar sesión.")


def read_assignment(page: Page, url: str, config: Config | None = None) -> Assignment:
    if config is not None:
        open_authenticated_page(page, url, config)
    else:
        open_page(page, url)
    title = first_text(page, "h1, .page-header-headings h1") or "Tarea sin título"
    from .linked_content import assignment_description, assignment_images, assignment_links

    content = assignment_description(page) or NO_DESCRIPTION
    due_date = first_text(
        page,
        ".activity-dates, .assign-dates, [data-region='activity-information'] .description",
    ) or "Fecha de vencimiento no indicada."
    summary = read_submission_summary(page)
    # Sin tabla reconocible se conserva el texto visible, recortado: nunca el volcado de la rúbrica y los comentarios.
    status = summary.get("status") or first_text(
        page,
        "[data-region='submissions'], .submissionstatus, .submissionstatustable",
    )[:300] or "Estado de entrega no visible."
    submitted = submission_state(status)
    from .search import parse_moodle_date

    region = page.locator("#region-main, main").first
    raw = region.inner_text() if region.count() else ""
    date_region = page.locator(".activity-dates, .assign-dates").first
    dates = date_region.inner_text() if date_region.count() else raw
    opening = re.search(r"(?:Apertura|Opened|Opens):\s*([^\n]+)", dates, re.I)
    closing = re.search(r"(?:Cierre|Due(?: date)?|Fecha de entrega):\s*([^\n]+)", dates, re.I)
    # inner_text conserva las filas de la tabla de calificaciones.
    grade_match = re.search(r"(?:^|\n)(?:Calificación|Grade)\s+([\d.,]+)\s*/\s*[\d.,]+", raw, re.I)
    grade = grade_match.group(1) if grade_match else None
    from .uploads import forbids_upload

    no_upload = forbids_upload(content)
    attachments = page.locator(
        "#region-main a[href*='/mod_assign/introattachment/'], #intro a[href*='pluginfile.php'], "
        ".activity-description a[href*='pluginfile.php'], .mod_introbox a[href*='pluginfile.php'], "
        "[data-region='activity-description'] a[href*='pluginfile.php'], "
        "[data-region='activity-information'] .description a[href*='pluginfile.php'], "
        ".box.generalbox a[href*='pluginfile.php']"
    ).evaluate_all("aa => aa.map(a => ({name: (a.innerText || a.getAttribute('title') || '').trim(), url: a.href}))")
    course = first_text(page, ".breadcrumb a[href*='/course/view.php']")
    links = assignment_links(page, content, attachments)
    return Assignment(title, page.url, content, closing.group(1) if closing else due_date, status, submitted,
                      course=course, attachments=attachments, links=links,
                      opens_at=parse_moodle_date(opening.group(1)) if opening else None,
                      due_at=parse_moodle_date(closing.group(1)) if closing else None,
                      grade=grade, requires_submission=False if grade or no_upload or submitted is True else True if submitted is False else None,
                      group=summary.get("group"), grading_status=summary.get("grading_status"),
                      rubric=summary.get("rubric"), images=assignment_images(page))


def collect_assignments(config: Config, *, mode: str = "all", limit: int | None = None,
                        only_pending: bool = False, stats: dict | None = None, progress=None) -> tuple[list[Assignment], list[str]]:
    from .search import search_assignments
    from .session import ensure_login, moodle_page

    with moodle_page(config) as (_, page):
        ensure_login(page, config)
        return search_assignments(page, config, mode=mode, limit=limit,
                                  only_pending=only_pending, stats=stats, progress=progress)


def print_tasks(tasks: list[Assignment], incomplete: bool = False, reviewed_count: int | None = None,
                timeline_empty: bool = False) -> None:
    pending = [task for task in tasks if is_pending(task)]
    if pending:
        from .server import pending_table
        print(pending_table(pending))
        return
    if not tasks and timeline_empty and not incomplete:
        # Una línea de tiempo vacía es una consulta completa: Moodle no muestra actividades próximas.
        print("\nNo hay tareas próximas en la línea de tiempo de Moodle.")
        return
    stamp = datetime.now().astimezone().strftime("%A, %d/%m/%Y %H:%M")
    print(f"\nConsulta de Moodle: {stamp}")
    reviewed_count = len(tasks) if reviewed_count is None else reviewed_count
    print(f"Tareas revisadas: {reviewed_count}")

    if not tasks:
        if reviewed_count and not incomplete:
            print("\nNo se encontraron tareas que cumplan esta búsqueda entre las actividades revisadas.")
        else:
            print("\n⚠️ No se pudieron revisar tareas. No se puede confirmar si tienes entregas pendientes.")
        return

    if incomplete:
        print("\n⚠️ La consulta quedó incompleta; no se pueden descartar tareas pendientes.")
    else:
        print("\n✅ No se encontraron tareas pendientes entre las actividades revisadas.")


def main(argv: list[str] | None = None) -> None:
    from .console import configure_utf8_streams
    configure_utf8_streams()

    import argparse
    from .search import MODES

    parser = argparse.ArgumentParser(description="Consulta tareas de Moodle.")
    parser.add_argument("--mode", choices=MODES, default="upcoming")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("El límite debe ser mayor que cero.")
    limit = args.limit if args.limit is not None else None if args.mode == "all" else 5
    config = None
    try:
        config = load_config()
        stats = {}
        tasks, errors = collect_assignments(config, mode=args.mode, limit=limit,
                                          only_pending=True, stats=stats)
        for error in errors:
            print(redact_credentials(error, (config.username, config.password)), file=sys.stderr)
        print_tasks(tasks, incomplete=bool(errors), reviewed_count=stats.get("candidates_checked"),
                    timeline_empty=stats.get("timeline_status") == "empty")
        print(f"Alcance: {stats.get('coverage', '')}")
    except Exception as error:
        secrets = (config.username, config.password) if config else ()
        print(f"\n❌ No fue posible consultar Moodle: {redact_credentials(error, secrets)}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
