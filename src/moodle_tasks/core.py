"""Núcleo de Moodle: configuración, inicio de sesión y lectura de páginas autenticadas.

No importa ningún otro módulo de la aplicación salvo errors y storage, así que todos pueden
importarlo sin dependencias circulares.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .errors import MoodleAuthenticationError, MoodleHTTPError
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
    feedback: dict | None = None
    # Con una prórroga, due_at es la fecha prorrogada y original_due_at el cierre que tenía la tarea.
    original_due_at: str | None = None
    cutoff_at: str | None = None


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
    "extension_due": r"extension due date|fecha de entrega (?:extendida|ampliada)|pr[oó]rroga|extensi[oó]n",
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


FEEDBACK_LABELS = {
    "grade": r"^(?:calificaci[oó]n|grade)$",
    "graded_at": r"calificado sobre|graded on",
    "graded_by": r"calificado por|graded by",
    "comments": r"comentarios de (?:la )?retroalimentaci[oó]n|feedback comments",
}
FEEDBACK_FILES = ("#region-main .feedback a[href*='/assignfeedback_file/'], "
                  ".feedbacktable a[href*='/assignfeedback_file/']")
MAX_FEEDBACK_COMMENTS = 5_000


def multiline_text(value: str | None) -> str:
    """Como clean_text, pero conserva los párrafos de un comentario."""
    lines = (clean_text(line) for line in (value or "").splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def read_feedback(page: Page) -> dict | None:
    """Tabla «Comentario» de una tarea calificada: nota, fecha, docente, comentarios y archivos corregidos.

    La fecha se devuelve como la muestra Moodle; quien la lee la convierte. Sin tabla ni archivos, None.
    """
    feedback: dict = {}
    table = page.locator("#region-main .feedback table, .feedbacktable table").first
    rows = table.evaluate(STATUS_ROWS) if table.count() else []
    for label, value in rows:
        label = clean_text(label)
        for key, pattern in FEEDBACK_LABELS.items():
            if key in feedback or not re.search(pattern, label, re.IGNORECASE):
                continue
            text = multiline_text(value) if key == "comments" else clean_text(value)
            if text:
                feedback[key] = text[:MAX_FEEDBACK_COMMENTS] if key == "comments" else text[:300]
    files = page.locator(FEEDBACK_FILES).evaluate_all(
        "aa => aa.map(a => ({name: (a.innerText || a.getAttribute('title') || '').trim(), url: a.href}))")
    unique = list({item["url"]: item for item in files if item.get("url")}.values())
    if unique:
        feedback["files"] = unique
    return feedback or None


def open_authenticated_page(page: Page, url: str, config: Config) -> None:
    """Renueva una sesión vencida una vez, sin leer el formulario como una tarea."""
    for attempt in range(2):
        open_page(page, url)
        if not ("/login/" in page.url or page.locator("input[name='username'], input[name='password'], input[name='loginfmt']").count()):
            return
        if attempt == 0:
            login(page, config)
    raise MoodleAuthenticationError("La sesión de Moodle sigue vencida después de volver a iniciar sesión.")
