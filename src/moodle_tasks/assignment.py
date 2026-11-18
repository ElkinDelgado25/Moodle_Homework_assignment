"""Lectura completa de una tarea de Moodle y de lo que su consigna dice sobre la entrega."""

import re

from playwright.sync_api import Page

from .auth import open_authenticated_page
from .config import Config
from .core import (NO_DESCRIPTION, Assignment, first_text, open_page, read_feedback, read_submission_summary,
                   submission_state)
from .linked_content import assignment_description, assignment_images, assignment_links
from .search import parse_moodle_date


NO_UPLOAD = re.compile(
    r"(?:no (?:se )?(?:debe|deben) (?:subir|entregar|presentar)|"
    r"no (?:se )?(?:requiere|permite) (?:subir|entregar|presentar)|"
    r"no (?:es necesario|hace falta) (?:subir|entregar|presentar)|"
    r"do not (?:submit|upload)|don't (?:submit|upload)|"
    r"you (?:do not|don't) need to (?:submit|upload)|"
    r"no (?:files|documents) (?:are )?(?:required|allowed)|"
    r"(?:files|documents) (?:are )?not required to (?:be )?(?:submitted|uploaded)|"
    r"^\s*no (?:subir|entregar|enviar|adjuntar)\b|"
    r"no (?:files|documents) (?:should|must|need to) be (?:submitted|uploaded))",
    re.IGNORECASE,
)
# Una frase con matices (formato, compresión, plazo...) no prohíbe entregar el informe.
UPLOAD_QUALIFIER = re.compile(
    r"comprimid|\bzip\b|\brar\b|formato|tarde|late\b|captura|screenshot|c[oó]digo fuente|source code|"
    r"\bsino\b|en lugar|instead|m[aá]s de|more than|\.\w{2,4}\b",
    re.IGNORECASE,
)
UPLOAD_REQUEST = re.compile(
    r"\b(?:s[uú]b(?:a|an|ir|e)|entreg(?:ue|uen|ar|a)|adjunt(?:e|en|ar|a)|upload|submit)\b.{0,60}?"
    r"\b(?:pdf|docx?|archivo|archivos|informe|documento|file|files|report)\b",
    re.IGNORECASE,
)

def forbids_upload(text: str) -> bool:
    """Solo una prohibición sin matices, y sin otra frase que pida subir el trabajo, bloquea la entrega."""
    if not text:
        return False
    sentences = [sentence for sentence in re.split(r"[.;:!?\n]+", text) if sentence.strip()]
    if any(UPLOAD_REQUEST.search(sentence) and not NO_UPLOAD.search(sentence) for sentence in sentences):
        return False
    return any(NO_UPLOAD.search(sentence) and not UPLOAD_QUALIFIER.search(sentence) for sentence in sentences)


def read_assignment(page: Page, url: str, config: Config | None = None) -> Assignment:
    if config is not None:
        open_authenticated_page(page, url, config)
    else:
        open_page(page, url)
    title = first_text(page, "h1, .page-header-headings h1") or "Tarea sin título"

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

    region = page.locator("#region-main, main").first
    raw = region.inner_text() if region.count() else ""
    date_region = page.locator(".activity-dates, .assign-dates").first
    dates = date_region.inner_text() if date_region.count() else raw
    opening = re.search(r"(?:Apertura|Opened|Opens):\s*([^\n]+)", dates, re.I)
    closing = re.search(r"(?:Cierre|Due(?: date)?|Fecha de entrega):\s*([^\n]+)", dates, re.I)
    cutoff = re.search(r"(?:Fecha l[ií]mite|Cut-off date):\s*([^\n]+)", dates, re.I)
    due_at = parse_moodle_date(closing.group(1)) if closing else None
    due_text = closing.group(1) if closing else due_date
    # Una prórroga concedida al estudiante (o a su grupo) reemplaza el cierre; el original se conserva aparte.
    extension_text = summary.get("extension_due", "")
    extension_at = parse_moodle_date(extension_text)
    original_due_at = None
    if extension_at and extension_at != due_at:
        original_due_at, due_at, due_text = due_at, extension_at, extension_text
    # inner_text conserva las filas de la tabla de calificaciones.
    grade_match = re.search(r"(?:^|\n)(?:Calificación|Grade)\s+([\d.,]+)\s*/\s*[\d.,]+", raw, re.I)
    feedback = read_feedback(page)
    if feedback and feedback.get("graded_at"):
        feedback["graded_at"] = parse_moodle_date(feedback["graded_at"])
    # Sin la fila en el texto, la nota numérica de la tabla de retroalimentación; una escala no cuenta como nota.
    feedback_grade = re.match(r"([\d.,]*\d)\s*/", (feedback or {}).get("grade", ""))
    grade = grade_match.group(1) if grade_match else feedback_grade.group(1) if feedback_grade else None

    no_upload = forbids_upload(content)
    attachments = page.locator(
        "#region-main a[href*='/mod_assign/introattachment/'], #intro a[href*='pluginfile.php'], "
        ".activity-description a[href*='pluginfile.php'], .mod_introbox a[href*='pluginfile.php'], "
        "[data-region='activity-description'] a[href*='pluginfile.php'], "
        "[data-region='activity-information'] .description a[href*='pluginfile.php'], "
        ".box.generalbox a[href*='pluginfile.php']"
    ).evaluate_all("aa => aa.map(a => ({name: (a.innerText || a.getAttribute('title') || '').trim(), url: a.href}))")
    # Los archivos entregados y los corregidos no son anexos de la consigna.
    attachments = [item for item in attachments if not re.search(r"/assign(?:feedback|submission)_", item["url"])]
    course = first_text(page, ".breadcrumb a[href*='/course/view.php']")
    links = assignment_links(page, content, attachments)
    return Assignment(title, page.url, content, due_text, status, submitted,
                      course=course, attachments=attachments, links=links,
                      opens_at=parse_moodle_date(opening.group(1)) if opening else None,
                      due_at=due_at, original_due_at=original_due_at,
                      cutoff_at=parse_moodle_date(cutoff.group(1)) if cutoff else None,
                      grade=grade, requires_submission=False if grade or no_upload or submitted is True else True if submitted is False else None,
                      group=summary.get("group"), grading_status=summary.get("grading_status"),
                      rubric=summary.get("rubric"), images=assignment_images(page), feedback=feedback)
