import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from dotenv import dotenv_values
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


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
    submitted: bool


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def config_values(env_file: Path | None = None) -> dict[str, str | None]:
    return {**dotenv_values(env_file or ENV_FILE), **os.environ}


def required_env(name: str, values: dict[str, str | None]) -> str:
    value = (values.get(name) or "").strip()
    if not value:
        raise ValueError(f"Falta la variable {name}. Cópiala desde .env.example a .env.")
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
    try:
        return clean_text(locator.text_content())
    except PlaywrightTimeoutError:
        return ""


def open_page(page: Page, url: str) -> None:
    response = page.goto(url, wait_until="domcontentloaded")
    if response is None or response.status >= 400:
        status = response.status if response is not None else "sin respuesta"
        raise RuntimeError(f"Moodle no pudo cargar la página (HTTP {status}): {url}")


def login(page: Page, config: Config) -> None:
    open_page(page, f"{config.base_url}/login/index.php")
    login_form = page.locator("form#login, form[action*='login']")
    if login_form.count() == 0:
        if page.locator("a[href*='/login/logout.php']").count():
            return
        raise RuntimeError("No se encontró el formulario de acceso ni una sesión iniciada en Moodle.")

    page.locator("input[name='username']").fill(config.username)
    page.locator("input[name='password']").fill(config.password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_load_state("domcontentloaded")

    if "/login/" in page.url:
        message = first_text(page, "[data-region='messages'], .alert-danger, .loginerrors")
        suffix = f": {message}" if message else "."
        raise RuntimeError(f"Moodle no aceptó el inicio de sesión{suffix}")


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


def read_assignment(page: Page, url: str) -> Assignment:
    open_page(page, url)
    title = first_text(page, "h1, .page-header-headings h1") or "Tarea sin título"
    content = first_text(
        page,
        ".activity-description, .mod_introbox, .box.generalbox, "
        "[data-region='activity-information']",
    ) or "No se encontró una descripción visible."
    due_date = first_text(
        page,
        "[data-region='activity-information'] .description, .activity-dates, .assign-dates",
    ) or "Fecha de vencimiento no indicada."
    status = first_text(
        page,
        "[data-region='submissions'], .submissionstatus, .submissionstatustable",
    ) or "Estado de entrega no visible."
    submitted = bool(re.search(r"submitted|entregad|enviado|calificad", status, re.IGNORECASE))
    return Assignment(title, page.url, content, due_date, status, submitted)


def collect_assignments(config: Config) -> tuple[list[Assignment], list[str]]:
    tasks: list[Assignment] = []
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.headless)
        try:
            page = browser.new_page()
            page.set_default_timeout(15_000)
            login(page, config)
            for url in find_assignment_links(page, config):
                try:
                    tasks.append(read_assignment(page, url))
                except Exception as error:
                    errors.append(f"No se pudo leer {url}: {error}")
        finally:
            browser.close()
    return tasks, errors


def print_tasks(tasks: list[Assignment], incomplete: bool = False) -> None:
    pending = [task for task in tasks if not task.submitted]
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
        print(f"   Vence: {task.due_date}")
        print(f"   Estado: {task.status}")
        print(f"   Contenido: {task.content}")
        print(f"   Enlace: {task.url}\n")


def main() -> None:
    try:
        config = load_config()
        tasks, errors = collect_assignments(config)
        for error in errors:
            print(error, file=sys.stderr)
        print_tasks(tasks, incomplete=bool(errors))
    except Exception as error:
        print(f"\n❌ No fue posible consultar Moodle: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
