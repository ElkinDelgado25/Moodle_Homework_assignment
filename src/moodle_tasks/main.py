import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

from dotenv import load_dotenv
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


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Falta la variable {name}. Cópiala desde .env.example a .env.")
    return value


def load_config() -> Config:
    load_dotenv()
    return Config(
        base_url=required_env("MOODLE_URL").rstrip("/"),
        username=required_env("MOODLE_USERNAME"),
        password=required_env("MOODLE_PASSWORD"),
        headless=os.getenv("MOODLE_HEADLESS", "true").lower() != "false",
    )


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def first_text(page: Page, selectors: str) -> str:
    locator = page.locator(selectors).first
    try:
        return clean_text(locator.text_content())
    except PlaywrightTimeoutError:
        return ""


def login(page: Page, config: Config) -> None:
    page.goto(f"{config.base_url}/login/index.php", wait_until="domcontentloaded")
    login_form = page.locator("form#login, form[action*='login']")
    if login_form.count() == 0:
        return

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
    for path in ("/my/", "/my/courses.php"):
        page.goto(urljoin(f"{config.base_url}/", path.lstrip("/")), wait_until="domcontentloaded")
        hrefs = page.locator("a[href*='/mod/assign/view.php']").evaluate_all(
            "(anchors) => anchors.map((anchor) => anchor.href)"
        )
        links.update(hrefs)
    return sorted(links)


def read_assignment(page: Page, url: str) -> Assignment:
    page.goto(url, wait_until="domcontentloaded")
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


def print_tasks(tasks: list[Assignment]) -> None:
    pending = [task for task in tasks if not task.submitted]
    stamp = datetime.now().astimezone().strftime("%A, %d/%m/%Y %H:%M")
    print(f"\nConsulta de Moodle: {stamp}")
    print(f"Tareas revisadas: {len(tasks)}")

    if not pending:
        print("\n✅ No se encontraron tareas pendientes de entrega.")
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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=config.headless)
            page = browser.new_page()
            page.set_default_timeout(15_000)
            try:
                login(page, config)
                tasks = []
                for url in find_assignment_links(page, config):
                    try:
                        tasks.append(read_assignment(page, url))
                    except Exception as error:
                        print(f"No se pudo leer {url}: {error}", file=sys.stderr)
                print_tasks(tasks)
            finally:
                browser.close()
    except Exception as error:
        print(f"\n❌ No fue posible consultar Moodle: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
