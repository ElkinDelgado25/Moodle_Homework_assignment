"""Núcleo de Moodle: la tarea leída, la navegación básica y la lectura de las tablas de una tarea.

Solo importa errors, así que todos los módulos pueden importarlo sin dependencias circulares.
El inicio de sesión vive en auth.py y la configuración en config.py.
"""

import re
from dataclasses import dataclass, field

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .errors import MoodleHTTPError


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


NO_DESCRIPTION = "No se encontró una descripción visible."


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
