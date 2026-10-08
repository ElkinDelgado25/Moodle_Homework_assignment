import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from dotenv import dotenv_values
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .errors import MoodleAuthenticationError, MoodleHTTPError
from .storage import default_env_file


@dataclass(frozen=True)
class Config:
    base_url: str
    username: str
    password: str
    headless: bool


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


def is_pending(task: Assignment) -> bool:
    return task.submitted is not True and task.requires_submission is not False


ENV_FILE = default_env_file()


def config_values(env_file: Path | None = None) -> dict[str, str | None]:
    return {**dotenv_values(env_file or default_env_file(), interpolate=False), **os.environ}


def required_env(name: str, values: dict[str, str | None]) -> str:
    value = (values.get(name) or "").strip()
    if not value:
        raise ValueError(f"Falta la variable {name}. Ejecuta mcp-moodle run para configurar tu cuenta.")
    return value


def load_config(env_file: Path | None = None) -> Config:
    values = config_values(env_file)
    return Config(
        base_url=required_env("MOODLE_URL", values).rstrip("/"),
        username=required_env("MOODLE_USERNAME", values),
        password=required_env("MOODLE_PASSWORD", values),
        headless=(values.get("MOODLE_HEADLESS") or "true").lower() != "false",
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


def login_microsoft(page: Page, config: Config) -> None:
    """Acceso institucional observado en ULEAM; no resuelve códigos ni MFA."""
    page.get_by_role("link", name="Microsoft 365 Uleam", exact=True).click()
    email = page.locator('input[name="loginfmt"]')
    email.wait_for(state="visible", timeout=30_000)
    email.fill(config.username)
    page.locator("#idSIButton9").click()
    password = page.locator('input[name="passwd"]')
    password.wait_for(state="visible", timeout=30_000)
    # La pantalla de Microsoft actualiza sus campos después de la transición.
    page.wait_for_timeout(1500)
    password.fill(config.password)
    password.press("Tab")
    page.locator("#idSIButton9").click()
    selected_again = False
    for _ in range(120):
        if page.url.startswith(config.base_url + "/") and page.locator("a[href*='/login/logout.php']").count():
            return
        for selector in ("#passwordError", "#usernameError", "#errorText"):
            error = page.locator(selector).first
            if error.count() and error.is_visible() and clean_text(error.inner_text()):
                raise MoodleAuthenticationError("Microsoft no aceptó el acceso: " + clean_text(error.inner_text()))
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


def find_assignment_links(page: Page, config: Config) -> list[str]:
    links: set[str] = set()
    courses: set[str] = set()
    for path in ("/my/", "/my/courses.php"):
        open_page(page, urljoin(f"{config.base_url}/", path.lstrip("/")))
        # La lista de cursos puede cargarse después mediante JavaScript.
        try:
            page.locator("a[href*='/course/view.php'], a[href*='/mod/assign/view.php']").first.wait_for(
                state="attached", timeout=10_000
            )
        except PlaywrightTimeoutError:
            pass
        courses.update(page.locator("a[href*='/course/view.php']").evaluate_all(
            "(anchors) => anchors.map((anchor) => anchor.href)"
        ))
        hrefs = page.locator("a[href*='/mod/assign/view.php']").evaluate_all(
            "(anchors) => anchors.map((anchor) => anchor.href)"
        )
        links.update(hrefs)
    for course_url in sorted(courses):
        open_page(page, course_url)
        links.update(page.locator("a[href*='/mod/assign/view.php']").evaluate_all(
            "(anchors) => anchors.map((anchor) => anchor.href)"
        ))
    return sorted(links)


def submission_state(status: str) -> bool | None:
    if re.search(r"not submitted|no (?:se ha )?(?:entregad|enviado)|sin entrega|borrador|draft|no attempt|ning[uú]n env[ií]o|todav[ií]a no se han realizado env[ií]os", status, re.IGNORECASE):
        return False
    if re.search(r"submitted for grading|entregad[oa] para|enviad[oa] para|^submitted$|^entregad[oa]$|^enviad[oa]$", status, re.IGNORECASE):
        return True
    return None


def read_assignment(page: Page, url: str) -> Assignment:
    open_page(page, url)
    title = first_text(page, "h1, .page-header-headings h1") or "Tarea sin título"
    content = first_text(
        page,
        ".activity-description, .mod_introbox, #intro, .box.generalbox, "
        "[data-region='activity-information']",
    ) or "No se encontró una descripción visible."
    due_date = first_text(
        page,
        ".activity-dates, .assign-dates, [data-region='activity-information'] .description",
    ) or "Fecha de vencimiento no indicada."
    status = first_text(
        page,
        "[data-region='submissions'], .submissionstatus, .submissionstatustable",
    ) or "Estado de entrega no visible."
    submission = ""
    for row in page.locator(".submissionstatustable tr").all():
        label = clean_text(row.locator("th, td").first.text_content())
        if re.search(r"submission status|estado de (?:la )?entrega", label, re.IGNORECASE):
            submission = clean_text(row.locator("td").last.text_content())
            break
    submitted = submission_state(submission or status)
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
    no_upload = bool(re.search(r"no deben subir|no (?:se )?requiere (?:subir|entrega)|do not (?:submit|upload)", content, re.I))
    attachments = page.locator(
        "#region-main a[href*='/mod_assign/introattachment/'], #intro a[href*='pluginfile.php'], "
        ".activity-description a[href*='pluginfile.php'], .mod_introbox a[href*='pluginfile.php']"
    ).evaluate_all("aa => aa.map(a => ({name: (a.innerText || a.getAttribute('title') || '').trim(), url: a.href}))")
    course = first_text(page, ".breadcrumb a[href*='/course/view.php']")
    return Assignment(title, page.url, content, closing.group(1) if closing else due_date, status, submitted,
                      course=course, attachments=attachments,
                      opens_at=parse_moodle_date(opening.group(1)) if opening else None,
                      due_at=parse_moodle_date(closing.group(1)) if closing else None,
                      grade=grade, requires_submission=False if grade or no_upload or submitted is True else True if submitted is False else None)


def collect_assignments(config: Config, *, mode: str = "all", limit: int | None = None,
                        only_pending: bool = False, refresh: bool = False,
                        stats: dict | None = None) -> tuple[list[Assignment], list[str]]:
    from .search import search_assignments

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.headless)
        try:
            page = browser.new_page()
            page.set_default_timeout(15_000)
            login(page, config)
            return search_assignments(page, config, mode=mode, limit=limit,
                                      only_pending=only_pending, refresh=refresh, stats=stats)
        finally:
            browser.close()


def print_tasks(tasks: list[Assignment], incomplete: bool = False) -> None:
    pending = [task for task in tasks if is_pending(task)]
    stamp = datetime.now().astimezone().strftime("%A, %d/%m/%Y %H:%M")
    print(f"\nConsulta de Moodle: {stamp}")
    print(f"Tareas revisadas: {len(tasks)}")

    if not tasks:
        print("\n⚠️ No se pudieron revisar tareas. No se puede confirmar si tienes entregas pendientes.")
        return

    if not pending:
        if incomplete:
            print("\n⚠️ La consulta quedó incompleta; no se pueden descartar tareas pendientes.")
        else:
            print("\n✅ No se encontraron tareas pendientes entre las actividades revisadas.")
        return

    print(f"\n⚠️ Tienes {len(pending)} tarea(s) pendiente(s):\n")
    for index, task in enumerate(pending, start=1):
        print(f"{index}. {task.title}")
        print(f"   Materia: {task.course or 'No identificada'}")
        print(f"   Vence: {task.due_date}")
        print(f"   Estado: {task.status}")
        print(f"   Contenido: {task.content}")
        for attachment in task.attachments:
            print(f"   Anexo: {attachment['name']} — {attachment['url']}")
        print(f"   Enlace: {task.url}\n")


def main(argv: list[str] | None = None) -> None:
    import argparse
    from .search import MODES

    parser = argparse.ArgumentParser(description="Consulta tareas de Moodle.")
    parser.add_argument("--mode", choices=MODES, default="upcoming")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--refresh", action="store_true", help="Releer los detalles sin usar la caché")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("El límite debe ser mayor que cero.")
    limit = args.limit if args.limit is not None else None if args.mode == "all" else 5
    try:
        config = load_config()
        stats = {}
        tasks, errors = collect_assignments(config, mode=args.mode, limit=limit,
                                          only_pending=True, refresh=args.refresh, stats=stats)
        for error in errors:
            print(error, file=sys.stderr)
        print_tasks(tasks, incomplete=bool(errors))
        print(f"Alcance: {stats.get('coverage', '')}")
    except Exception as error:
        print(f"\n❌ No fue posible consultar Moodle: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
