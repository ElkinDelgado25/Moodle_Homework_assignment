"""Subida explícita de entregables a una tarea de Moodle."""

import os
import re
import shutil
import stat
import tempfile
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import Locator, Page

from .errors import redact_credentials
from .main import Config, open_authenticated_page, read_assignment, submission_state
from .paths import check_upload_file


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
CLOSED = re.compile(
    r"(?:(?:this )?assignment (?:is )?closed|submissions? (?:are |is )?closed|closed for submissions|"
    r"env[ií]os? cerrad[oa]s?|entregas? cerrad[oa]s?|no se permiten (?:env[ií]os|entregas)|"
    r"submission period has ended|no more submissions are accepted|"
    r"submissions are not accepted|you cannot make a submission to this assignment|"
    r"(?:esta )?(?:tarea|actividad) (?:est[aá] )?cerrada|no se aceptan (?:env[ií]os|entregas)|"
    r"ya no se aceptan (?:env[ií]os|entregas)|no puedes realizar una entrega|"
    r"el per[ií]odo de entrega ha finalizado|el plazo de entrega ha finalizado|"
    r"se cerr[oó] el plazo de (?:entrega|env[ií]o))",
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
MOODLE_FILE_CHARACTERS = re.compile("[\x00-\x1f\x7f&<>\"`|':\\\\/]")
SAVE = re.compile(r"^(?:save changes|guardar cambios)$", re.IGNORECASE)
GRADING = re.compile(
    r"enviar (?:la )?tarea|enviar para calific|submit assignment|submit for grading",
    re.IGNORECASE,
)
UPLOAD_REPOSITORY = re.compile(r"^(?:upload a file|subir un archivo|subir archivo)$", re.IGNORECASE)
UPLOAD_FILE = re.compile(r"^(?:upload this file|subir este archivo)$", re.IGNORECASE)
SELECT_FILE = re.compile(r"^(?:select this file|seleccionar este archivo|seleccionar archivo)$", re.IGNORECASE)
DELETE = re.compile(r"^(?:yes|s[ií]|delete|eliminar|borrar)$", re.IGNORECASE)
CANCEL = re.compile(r"^(?:cancel|cancelar|close|cerrar|ok|aceptar)$", re.IGNORECASE)
POLL_SECONDS = 0.25
TOTAL_BUDGET_SECONDS = 240  # por debajo del límite habitual de 300 s de los clientes MCP


def forbids_upload(text: str) -> bool:
    """Solo una prohibición sin matices, y sin otra frase que pida subir el trabajo, bloquea la entrega."""
    if not text:
        return False
    sentences = [sentence for sentence in re.split(r"[.;:!?\n]+", text) if sentence.strip()]
    if any(UPLOAD_REQUEST.search(sentence) and not NO_UPLOAD.search(sentence) for sentence in sentences):
        return False
    return any(NO_UPLOAD.search(sentence) and not UPLOAD_QUALIFIER.search(sentence) for sentence in sentences)


def moodle_name(name: str) -> str:
    """Nombre tal como lo guarda Moodle (PARAM_FILE), normalizado para comparar."""
    cleaned = MOODLE_FILE_CHARACTERS.sub("", unicodedata.normalize("NFC", name))
    return " ".join(cleaned.split()).casefold()


def moodle_exact(name: str) -> str:
    """Nombre exacto con el que Moodle guarda el archivo (sin cambiar mayúsculas ni espacios internos)."""
    return MOODLE_FILE_CHARACTERS.sub("", unicodedata.normalize("NFC", name)).strip()


def _file_seconds(path: Path) -> float:
    return min(60.0, 15.0 + path.stat().st_size / (1024 * 1024) * 5)


def _control_text(control: Locator) -> str:
    tag = control.evaluate("element => element.tagName.toLowerCase()")
    if tag == "input":
        raw = control.get_attribute("value") or control.get_attribute("aria-label") or ""
    else:
        raw = control.inner_text() or control.get_attribute("aria-label") or ""
    return " ".join(raw.replace("\xa0", " ").split())


def _is_save_control(control: Locator) -> bool:
    text = _control_text(control)
    if not text or GRADING.search(text):
        return False
    name = (control.get_attribute("id") or "") + " " + (control.get_attribute("name") or "")
    if "submitbutton" in name and not GRADING.search(text):
        return True
    return bool(SAVE.fullmatch(text))


def _click_control(root: Locator | Page, pattern: re.Pattern[str], selectors: str = "a, button, input[type='submit']") -> bool:
    controls = root.locator(selectors)
    for index in range(controls.count()):
        control = controls.nth(index)
        try:
            if control.is_visible() and pattern.fullmatch(_control_text(control).strip()):
                control.click()
                return True
        except Exception:
            continue
    return False


def _file_names(filemanager: Locator) -> list[str]:
    files = filemanager.locator(".fp-file")
    names: list[str] = []
    for index in range(files.count()):
        item = files.nth(index)
        if item.locator(".fp-folder").count():
            continue
        name = item.locator(".fp-filename").first.inner_text() if item.locator(".fp-filename").count() else ""
        name = name.strip() or (item.get_attribute("data-filename") or item.get_attribute("title") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _file_error(error: Exception, path: Path, config: Config) -> str:
    message = str(error).replace(str(path), "[archivo local]")
    return redact_credentials(message, (config.username, config.password))[:500]


def _has_control(root: Locator | Page, pattern: re.Pattern[str]) -> bool:
    controls = root.locator("a, button, input[type='submit']")
    for index in range(controls.count()):
        control = controls.nth(index)
        try:
            if control.is_visible() and pattern.fullmatch(_control_text(control).strip()):
                return True
        except Exception:
            continue
    return False


def _upload_input(page: Page) -> Locator | None:
    # Prefer the file input inside Moodle's active picker. A filemanager may also
    # contain a separate hidden drag-and-drop input on the underlying form.
    for selector in (
        "[role='dialog']:not([data-mcp-foreign]) .fp-file input[type='file']",
        ".filepicker:not([data-mcp-foreign]) .fp-file input[type='file']",
        ".moodle-dialogue:not([data-mcp-foreign]) .fp-file input[type='file']",
        "[role='dialog']:not([data-mcp-foreign]) input[type='file']",
        ".filepicker:not([data-mcp-foreign]) input[type='file']",
        ".moodle-dialogue:not([data-mcp-foreign]) input[type='file']",
    ):
        inputs = page.locator(selector)
        if inputs.count():
            return inputs.last
    inputs = page.locator("input[type='file']")
    return inputs.last if inputs.count() else None


def _upload_error_message(page: Page) -> str | None:
    for selector in (
        "[role='dialog']:not([data-mcp-foreign]) .fp-msg-error",
        ".filepicker:not([data-mcp-foreign]) .fp-msg-error",
        ".moodle-dialogue:not([data-mcp-foreign]) .fp-msg-error",
        "[role='dialog']:not([data-mcp-foreign]) .alert-danger",
        ".filepicker:not([data-mcp-foreign]) .alert-danger",
        ".moodle-dialogue:not([data-mcp-foreign]) .alert-danger",
        ".filemanager .fp-msg-error",
    ):
        messages = page.locator(selector)
        for index in range(messages.count()):
            message = messages.nth(index)
            try:
                text = message.inner_text().strip()
                if message.is_visible() and text:
                    return text
            except Exception:
                continue
    return None


def _wait_for_filemanager_ready(page: Page, filemanager: Locator) -> None:
    for _ in range(60):
        classes = (filemanager.get_attribute("class") or "").split()
        loaded_empty = "fm-nofiles" in classes or "fm-noitems" in classes
        loaded_with_files = bool(_file_names(filemanager))
        # Tras quitar los archivos previos, el área puede quedar vacía sin la clase fm-nofiles.
        ready = loaded_empty or loaded_with_files or _add_control(filemanager) is not None
        if "fm-updating" not in classes and "fm-loading" not in classes and ready:
            return
        page.wait_for_timeout(250)
    raise RuntimeError("Moodle no terminó de cargar el área de entrega.")


def _find_dialog_action(page: Page, pattern: re.Pattern[str], *, page_fallback: bool = True) -> bool:
    dialogs = page.locator("[role='dialog']:not([data-mcp-foreign]), .filepicker:not([data-mcp-foreign]), .moodle-dialogue:not([data-mcp-foreign])")
    for index in reversed(range(dialogs.count())):
        dialog = dialogs.nth(index)
        if dialog.is_visible() and _click_control(dialog, pattern):
            return True
    return page_fallback and _click_control(page, pattern)


def _dismiss_filepicker(page: Page) -> None:
    # Nunca busca "Cancelar" fuera de un diálogo: el formulario de entrega tiene su propio Cancelar.
    if _find_dialog_action(page, CANCEL, page_fallback=False):
        return
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _submit_upload_form(page: Page) -> bool:
    buttons = page.locator(".fp-upload-btn")
    for index in range(buttons.count()):
        button = buttons.nth(index)
        if button.is_visible():
            button.click()
            return True
    return _find_dialog_action(page, UPLOAD_FILE)


def _add_control(filemanager: Locator) -> Locator | None:
    selectors = ".fp-btn-add a, .fp-btn-add button, a.fp-btn-add, button.fp-btn-add, [data-action='add']"
    controls = filemanager.locator(selectors)
    for index in range(controls.count()):
        control = controls.nth(index)
        try:
            if control.is_visible():
                return control
        except Exception:
            continue
    container = filemanager.locator(".fp-btn-add")
    if container.count():
        return container.first
    return None


def _mark_foreign_dialogs(page: Page) -> None:
    """Diálogos visibles que no son del selector de archivos (cookies, avisos) no se tocan ni se leen."""
    page.evaluate("""() => document.querySelectorAll("[role='dialog'], .filepicker, .moodle-dialogue").forEach(d => {
        const visible = !!(d.offsetWidth || d.offsetHeight || d.getClientRects().length);
        if (visible && !d.querySelector('input[type=file], .fp-repo-area, .fp-upload-form, .fp-file, .fp-upload-btn'))
            d.setAttribute('data-mcp-foreign', '1');
    })""")


def _stage_file(page: Page, filemanager: Locator, path: Path) -> None:
    _mark_foreign_dialogs(page)
    _wait_for_filemanager_ready(page, filemanager)
    if "fm-maxfiles" in (filemanager.get_attribute("class") or "").split():
        raise RuntimeError("El área de entrega ya alcanzó el número máximo de archivos.")
    if page.locator("[role='dialog']:not([data-mcp-foreign]):visible, .filepicker:not([data-mcp-foreign]):visible, .moodle-dialogue:not([data-mcp-foreign]):visible").count():
        _dismiss_filepicker(page)
    add = _add_control(filemanager)
    if add is None:
        raise RuntimeError("Moodle no muestra el control para agregar archivos.")
    try:
        add.scroll_into_view_if_needed(timeout=2_000)
    except Exception:
        pass
    add.click()

    # El selector de Moodle puede abrir directamente el repositorio de subida o mostrar
    # primero la lista de repositorios disponibles.
    for _ in range(60):
        if _has_control(page, UPLOAD_REPOSITORY) or _upload_input(page):
            break
        if error := _upload_error_message(page):
            raise RuntimeError(f"Moodle no pudo abrir el selector de archivos: {error}")
        page.wait_for_timeout(250)
    else:
        raise RuntimeError("Moodle no abrió el selector de archivos.")

    _find_dialog_action(page, UPLOAD_REPOSITORY)

    upload_input: Locator | None = None
    for _ in range(60):
        upload_input = _upload_input(page)
        if upload_input:
            break
        if error := _upload_error_message(page):
            raise RuntimeError(f"Moodle no pudo preparar la subida: {error}")
        page.wait_for_timeout(250)
    if upload_input is None:
        raise RuntimeError("El selector de Moodle no mostró el campo para elegir un archivo.")
    upload_input.set_input_files(str(path))

    for _ in range(60):
        if page.locator(".fp-upload-btn:visible").count() or _has_control(page, UPLOAD_FILE):
            break
        if error := _upload_error_message(page):
            raise RuntimeError(f"Moodle rechazó el archivo: {error}")
        page.wait_for_timeout(250)
    else:
        raise RuntimeError("Moodle no mostró el botón para subir el archivo.")

    if _submit_upload_form(page):
        # Moodle puede presentar una pantalla de confirmación del repositorio antes
        # de volver al selector de archivos.
        _find_dialog_action(page, SELECT_FILE)
    elif _find_dialog_action(page, SELECT_FILE):
        pass

    expected = moodle_name(path.name)
    deadline = time.monotonic() + _file_seconds(path)
    while time.monotonic() < deadline:
        if error := _upload_error_message(page):
            _dismiss_filepicker(page)
            raise RuntimeError(f"Moodle rechazó el archivo: {error}")
        if expected in {moodle_name(name) for name in _file_names(filemanager)}:
            return
        page.wait_for_timeout(250)
    _dismiss_filepicker(page)
    raise RuntimeError("Moodle no confirmó el archivo en el área de entrega.")


def _remove_existing_files(page: Page, filemanager: Locator) -> list[str]:
    removed: list[str] = []
    if not _file_names(filemanager):
        return removed

    # Moodle only exposes the select-and-delete controls in details/table view.
    details = filemanager.locator(".fp-vb-details")
    if not details.count():
        raise RuntimeError("Moodle no permite seleccionar los archivos existentes para reemplazarlos.")
    if "checked" not in (details.first.get_attribute("class") or "").split():
        details.first.click()
    for _ in range(40):
        if filemanager.locator("[data-togglegroup][data-toggle='slave']").count():
            break
        page.wait_for_timeout(250)
    else:
        raise RuntimeError("Moodle no mostró la selección de archivos necesaria para reemplazarlos.")

    while _file_names(filemanager):
        before = _file_names(filemanager)
        checkboxes = filemanager.locator("[data-togglegroup][data-toggle='slave']")
        for name in before:
            selected = False
            for index in range(checkboxes.count()):
                checkbox = checkboxes.nth(index)
                full_name = checkbox.get_attribute("data-fullname") or ""
                row_text = checkbox.evaluate(
                    "element => element.closest('.fp-file')?.innerText || element.parentElement?.innerText || ''"
                )
                if full_name == name or name in row_text:
                    checkbox.check(force=True)
                    selected = True
                    break
            if not selected:
                raise RuntimeError(f"Moodle no permitió seleccionar el archivo existente {name}.")

        delete = filemanager.locator(".fp-btn-delete a, .fp-btn-delete button, button.fp-btn-delete, a.fp-btn-delete, [data-action='delete']")
        if not delete.count() or not delete.first.is_visible():
            raise RuntimeError("No se encontró la opción de Moodle para reemplazar los archivos existentes.")
        delete.first.click()
        if not _find_dialog_action(page, DELETE):
            raise RuntimeError("Moodle no mostró la confirmación para quitar un archivo existente.")
        after = before
        for _ in range(240):
            after = _file_names(filemanager)
            if len(after) < len(before):
                break
            page.wait_for_timeout(250)
        if len(after) >= len(before):
            raise RuntimeError("Moodle no confirmó que quitó un archivo existente.")
        removed.extend(name for name in before if name not in after)
    return removed


def _submission_file_names(page: Page) -> set[str]:
    """Nombres normalizados de los archivos ya guardados en la entrega (texto del enlace y su URL)."""
    names: set[str] = set()
    links = page.locator("#region-main a[href*='assignsubmission_file']")
    for index in range(links.count()):
        try:
            text = links.nth(index).inner_text().strip()
            href = links.nth(index).get_attribute("href") or ""
        except Exception:
            continue
        if text:
            names.add(moodle_name(text))
        segment = unquote(urlsplit(href).path.rsplit("/", 1)[-1])
        if segment:
            names.add(moodle_name(segment))
    return names


def _submission_files(page: Page) -> list[str]:
    files: list[str] = []
    links = page.locator("#region-main a[href*='assignsubmission_file']")
    for index in range(links.count()):
        try:
            text = links.nth(index).inner_text().strip()
        except Exception:
            continue
        if text and text not in files:
            files.append(text)
    return files


def _limit(page: Page, filemanager: Locator, name: str) -> int | None:
    value = filemanager.get_attribute(f"data-{name}")
    if value is None:
        content = page.content()
        client = (filemanager.get_attribute("id") or "").removeprefix("filemanager-")
        scope = None
        if client:
            # La configuración de este filemanager es el objeto JSON que contiene su client_id.
            for match in re.finditer(r"\{[^{}]*\}", content):
                if f'"client_id":"{client}"' in match.group(0).replace(" ", ""):
                    scope = match.group(0)
                    break
        matches = re.findall(rf'"{name}"\s*:\s*"?(-?\d+)', scope if scope is not None else content)
        # Sin client_id solo se confía en un valor único: otro editor de la página puede declarar el suyo.
        value = matches[0] if scope is not None and matches else (matches[0] if len(matches) == 1 else None)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _submission_state(page: Page, status_text: str) -> dict:
    status = ""
    for row in page.locator(".submissionstatustable tr").all():
        try:
            label = " ".join(row.locator("th, td").first.inner_text().split())
        except Exception:
            continue
        if re.search(r"submission status|estado de (?:la )?entrega", label, re.IGNORECASE):
            status = " ".join(row.locator("td").last.inner_text().split())
            break
    status = status or status_text
    if re.search(r"borrador|draft", status, re.IGNORECASE):
        state = "draft"
    elif submission_state(status) is True:
        state = "submitted"
    elif submission_state(status) is False:
        state = "not_submitted"
    else:
        state = "unknown"
    grading = page.locator("#region-main a, #region-main button, #region-main input[type='submit']")
    requires = False
    for index in range(grading.count()):
        try:
            control = grading.nth(index)
            if control.is_visible() and GRADING.search(_control_text(control)):
                requires = True
                break
        except Exception:
            continue
    if state == "submitted":
        note = "Moodle muestra la entrega como enviada para calificar."
    elif requires:
        note = "Los archivos quedaron guardados como borrador: el estudiante debe pulsar «Enviar tarea» en Moodle para entregarla."
    else:
        note = "Los archivos quedaron guardados en la entrega; revisa en Moodle si la actividad exige otro paso."
    return {"state": state, "status_text": status, "requires_submit_for_grading": requires,
            "submitted_by_tool": False, "note": note}


def _form_error(page: Page) -> str | None:
    for selector in ("#region-main .invalid-feedback", "#region-main [id^='id_error_']",
                     "#region-main .form-control-feedback", "#region-main .error"):
        nodes = page.locator(selector)
        for index in range(nodes.count()):
            try:
                node = nodes.nth(index)
                text = " ".join(node.inner_text().split())
                if node.is_visible() and text:
                    return text[:300]
            except Exception:
                continue
    return None


def _save_control(page: Page, filemanager: Locator) -> Locator | None:
    roots = [page.locator("#id_submitbutton, [name='submitbutton']")]
    forms = page.locator("form").filter(has=filemanager)
    if forms.count():
        roots.append(forms.first.locator("button, input[type='submit']"))
    roots.append(page.locator("#region-main button, #region-main input[type='submit'], button, input[type='submit']"))
    for controls in roots:
        for index in range(controls.count()):
            control = controls.nth(index)
            try:
                if control.is_visible() and _is_save_control(control):
                    return control
            except Exception:
                continue
    return None


def _preflight_files(file_paths: list[str]) -> tuple[list[Path], list[dict[str, str]]]:
    """Valida tipo, contenido y ubicación de todos los archivos antes de abrir Moodle."""
    paths: list[Path] = []
    errors: list[dict[str, str]] = []
    seen_paths: set[Path] = set()
    seen_names: set[str] = set()
    for raw in file_paths:
        name = Path(raw).name if isinstance(raw, str) else "archivo"
        try:
            path = check_upload_file(raw)
        except FileNotFoundError:
            errors.append({"name": name or "archivo", "status": "failed", "error": "El archivo local no existe."})
            continue
        except PermissionError:
            errors.append({"name": name or "archivo", "status": "failed", "error": "No se puede leer el archivo local."})
            continue
        except (OSError, RuntimeError):
            errors.append({"name": name or "archivo", "status": "failed", "error": "La ruta local no corresponde a un archivo legible."})
            continue
        except ValueError as error:
            errors.append({"name": name or "archivo", "status": "failed", "error": str(error)})
            continue
        if path in seen_paths:
            errors.append({"name": path.name, "status": "failed", "error": "El mismo archivo aparece más de una vez."})
            continue
        if moodle_name(path.name) in seen_names:
            errors.append({"name": path.name, "status": "failed",
                           "error": "Hay más de un archivo con el mismo nombre una vez que Moodle lo guarde."})
            continue
        seen_paths.add(path)
        seen_names.add(moodle_name(path.name))
        paths.append(path)
    return paths, errors


def _result(assignment_id: int, title: str | None, status: str, *, files: list[dict], errors: list[str],
            existing: list[str] | None = None, replaced: list[str] | None = None,
            submission: dict | None = None, complete: bool = False, warnings: list[str] | None = None) -> dict:
    """Forma única de respuesta de la subida."""
    return {
        "assignment_id": assignment_id,
        "title": title,
        "status": status,
        "files": files,
        "uploaded_files": [item["name"] for item in files if item["status"] in ("uploaded", "already_present")],
        "failed_files": [item["name"] for item in files if item["status"] == "failed"],
        "existing_files": existing or [],
        "replaced_files": replaced or [],
        "submission": submission or {"state": "unknown", "status_text": "", "requires_submit_for_grading": None,
                                     "submitted_by_tool": False, "note": "No se modificó la entrega."},
        "complete": complete,
        "warnings": warnings or [],
        "errors": errors,
    }


def preflight_result(assignment_id: int, file_paths: list[str]) -> dict | None:
    """Resultado bloqueado si algún archivo no es válido; None si todos se pueden subir."""
    paths, preflight_errors = _preflight_files(file_paths)
    if not file_paths:
        preflight_errors = [{"name": "archivo", "status": "failed", "error": "Indica al menos un archivo."}]
    if not preflight_errors:
        return None
    return _result(assignment_id, None, "blocked",
                   files=preflight_errors + [{"name": path.name, "status": "not_uploaded"} for path in paths],
                   errors=[item["error"] for item in preflight_errors])


def upload_files(
    page: Page,
    config: Config,
    assignment_id: int,
    file_paths: list[str],
    *,
    replace_existing: bool = False,
) -> dict:
    """Agrega archivos y guarda la entrega sin enviarla para calificación."""
    blocked = preflight_result(assignment_id, file_paths)
    if blocked is not None:
        return blocked
    validated, _ = _preflight_files(file_paths)
    # Se sube una copia privada tomada al validar: cambiar el archivo original después no cambia lo que se envía.
    with tempfile.TemporaryDirectory(prefix="moodle-upload-") as staging:
        try:
            paths = _stage_copies(validated, Path(staging))
        except (OSError, ValueError) as error:
            return _result(assignment_id, None, "blocked",
                           files=[{"name": path.name, "status": "not_uploaded"} for path in validated],
                           errors=[f"Un archivo cambió después de validarlo: {error}"])
        return _upload_validated(page, config, assignment_id, paths, replace_existing)


def _stage_copies(paths: list[Path], staging: Path) -> list[Path]:
    copies = []
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    for path in paths:
        expected = check_upload_file(str(path))
        before = expected.stat()
        descriptor = os.open(expected, flags)
        try:
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino) or not stat.S_ISREG(info.st_mode):
                raise ValueError(path.name)
            target = staging / path.name
            with os.fdopen(descriptor, "rb", closefd=False) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
        finally:
            os.close(descriptor)
        copies.append(target)
    return copies


def _upload_validated(page: Page, config: Config, assignment_id: int, paths: list[Path], replace_existing: bool) -> dict:
    started = time.monotonic()
    secrets = (config.username, config.password)

    def pending(status="not_uploaded"):
        return [{"name": path.name, "status": status} for path in paths]

    url = f"{config.base_url}/mod/assign/view.php?id={assignment_id}"
    task = read_assignment(page, url, config)
    region = page.locator("#region-main, main").first
    page_text = region.inner_text() if region.count() else ""
    # La descripción del docente no decide si la actividad está cerrada: solo el estado y las fechas.
    flat = lambda value: " ".join(value.replace("\xa0", " ").split())  # noqa: E731
    status_text = flat(page_text).replace(flat(task.content), " ") if task.content else page_text
    if forbids_upload(task.content):
        return _result(assignment_id, task.title, "blocked", files=pending(),
                       errors=["Las instrucciones indican que no se deben subir archivos."])
    if CLOSED.search(status_text):
        return _result(assignment_id, task.title, "blocked", files=pending(),
                       errors=["La actividad está cerrada para entregas."])
    view_files = _submission_files(page)
    requested = {moodle_name(path.name) for path in paths}

    open_authenticated_page(page, f"{url}&action=editsubmission", config)
    managers = page.locator(".filemanager")
    if not managers.count():
        return _result(assignment_id, task.title, "blocked", files=pending(),
                       errors=["La actividad no muestra un área para adjuntar archivos."])
    filemanager = managers.first
    _wait_for_filemanager_ready(page, filemanager)
    existing = _file_names(filemanager)
    form_existing = list(existing)
    if view_files and not existing:
        # La página de la tarea muestra archivos que el formulario aún no cargó: se tratan como existentes.
        existing = view_files
    if existing and not replace_existing:
        if {moodle_exact(name) for name in existing} == {moodle_exact(path.name) for path in paths}:
            return _result(assignment_id, task.title, "already_uploaded", files=pending("already_present"),
                           existing=existing, complete=True, errors=[],
                           submission=_submission_state(page, task.status),
                           warnings=["Moodle ya tiene archivos con estos mismos nombres; no se comparó su contenido."])
        return _result(assignment_id, task.title, "blocked_existing_files", files=pending(), existing=existing,
                       errors=["La entrega ya contiene archivos; no se reemplazó ninguno."])

    maxfiles = _limit(page, filemanager, "maxfiles")
    if maxfiles is not None and maxfiles >= 0 and (maxfiles == 0 or len(paths) > maxfiles):
        return _result(assignment_id, task.title, "blocked", files=pending(), existing=existing,
                       errors=[f"La actividad admite como máximo {maxfiles} archivo(s)."])
    maxbytes = _limit(page, filemanager, "maxbytes") or 0
    oversized = [path for path in paths if maxbytes > 0 and path.stat().st_size > maxbytes]
    if oversized:
        failed = [{"name": path.name, "status": "failed", "error": "El archivo supera el tamaño máximo indicado por Moodle."} for path in oversized]
        names = {item["name"] for item in failed}
        return _result(assignment_id, task.title, "blocked", existing=existing,
                       files=failed + [item for item in pending() if item["name"] not in names],
                       errors=[item["error"] for item in failed])
    statement = page.locator("input[name='submissionstatement']")
    if statement.count() and not statement.first.is_checked():
        label = page.locator("label[for='id_submissionstatement']")
        text = " ".join(label.first.inner_text().split()) if label.count() else ""
        return _result(assignment_id, task.title, "requires_statement", files=pending(), existing=existing,
                       errors=["La actividad exige aceptar la declaración de originalidad; el estudiante debe hacerlo en Moodle."]
                       + ([f"Declaración: {text}"] if text else []))

    replaced: list[str] = []
    if existing and replace_existing:
        try:
            replaced = _remove_existing_files(page, filemanager)
        except Exception as error:
            return _result(assignment_id, task.title, "blocked", files=pending(), existing=existing,
                           errors=[redact_credentials(error, secrets)[:500]])

    file_results: list[dict[str, str]] = []
    for path in paths:
        if time.monotonic() - started > TOTAL_BUDGET_SECONDS:
            file_results.append({"name": path.name, "status": "failed", "error": "Se agotó el tiempo disponible para subir archivos."})
            continue
        try:
            _stage_file(page, filemanager, path)
            file_results.append({"name": path.name, "status": "staged"})
        except Exception as error:
            _dismiss_filepicker(page)
            file_results.append({"name": path.name, "status": "failed", "error": _file_error(error, path, config)})

    failures = [item for item in file_results if item["status"] == "failed"]
    if failures:
        # Todo o nada: no se guarda una entrega incompleta; Moodle descarta el borrador del formulario.
        status = "replacement_cancelled" if replaced else "failed"
        message = ("La sustitución se canceló porque falló al menos un archivo; la entrega existente se conserva."
                   if replaced else "No se guardó la entrega porque falló al menos un archivo.")
        files = [item if item["status"] == "failed" else {"name": item["name"], "status": "not_saved"} for item in file_results]
        return _result(assignment_id, task.title, status, files=files, existing=existing,
                       errors=[message] + [item["error"] for item in failures])

    save = _save_control(page, filemanager)
    if save is None:
        return _result(assignment_id, task.title, "failed", files=pending("not_saved"), existing=existing,
                       errors=["Moodle no mostró el botón Guardar cambios; no se guardó la entrega."])

    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=60_000):
            save.click()
    except Exception as error:
        return _result(assignment_id, task.title, "save_unconfirmed", files=pending("save_unconfirmed"),
                       existing=existing, replaced=replaced,
                       errors=[f"Moodle no confirmó el guardado: {redact_credentials(error, secrets)[:300]}"])
    if "action=editsubmission" in page.url or page.locator(".filemanager").count():
        problem = _form_error(page) or "Moodle volvió a mostrar el formulario sin guardar."
        return _result(assignment_id, task.title, "failed", files=pending("not_saved"), existing=existing,
                       errors=[f"Moodle rechazó el formulario: {problem}"])

    try:
        final_task = read_assignment(page, url, config)
    except Exception as error:
        return _result(assignment_id, task.title, "save_unconfirmed", files=pending("save_unconfirmed"),
                       existing=existing, replaced=replaced,
                       errors=[f"No se pudo releer la entrega: {redact_credentials(error, secrets)[:300]}"])
    saved = _submission_file_names(page)
    if replace_existing and existing and not form_existing and not replaced:
        # Los archivos anteriores solo se veían en la tarea: guardar el formulario los sustituyó.
        replaced = list(existing)
    files = [{"name": path.name, "status": "uploaded" if moodle_name(path.name) in saved else "save_unconfirmed"}
             for path in paths]
    unconfirmed = [item["name"] for item in files if item["status"] != "uploaded"]
    return _result(assignment_id, final_task.title or task.title, "uploaded" if not unconfirmed else "save_unconfirmed",
                   files=files, existing=existing, replaced=replaced,
                   submission=_submission_state(page, final_task.status), complete=not unconfirmed,
                   errors=["Moodle guardó el formulario, pero no muestra estos archivos: " + ", ".join(unconfirmed)] if unconfirmed else [])
