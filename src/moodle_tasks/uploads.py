"""Subida explícita de entregables a una tarea de Moodle."""

import re
from pathlib import Path

from playwright.sync_api import Locator, Page

from .errors import redact_credentials
from .main import Config, read_assignment


NO_UPLOAD = re.compile(
    r"(?:no (?:se )?(?:debe|deben) (?:subir|entregar|presentar)|"
    r"no (?:se )?(?:requiere|permite) (?:subir|entregar|presentar)|"
    r"no (?:es necesario|hace falta) (?:subir|entregar|presentar)|"
    r"do not (?:submit|upload)|don't (?:submit|upload)|"
    r"you (?:do not|don't) need to (?:submit|upload)|"
    r"no (?:files|documents) (?:are )?(?:required|allowed)|"
    r"(?:files|documents) (?:are )?not required to (?:be )?(?:submitted|uploaded))",
    re.IGNORECASE,
)
CLOSED = re.compile(
    r"(?:(?:this )?assignment (?:is )?closed|submission (?:is )?closed|closed for submissions|"
    r"submission period has ended|no more submissions are accepted|"
    r"submissions are not accepted|you cannot make a submission to this assignment|"
    r"(?:esta )?(?:tarea|actividad) (?:est[aá] )?cerrada|no se aceptan (?:env[ií]os|entregas)|"
    r"ya no se aceptan (?:env[ií]os|entregas)|no puedes realizar una entrega|"
    r"el per[ií]odo de entrega ha finalizado|el plazo de entrega ha finalizado|"
    r"se cerr[oó] el plazo de (?:entrega|env[ií]o))",
    re.IGNORECASE,
)
ACTION = re.compile(r"^(?:add|edit) submission$|^(?:agregar|a[nñ]adir|editar) entrega$", re.IGNORECASE)
SAVE = re.compile(r"^(?:save changes|guardar cambios)$", re.IGNORECASE)
UPLOAD_REPOSITORY = re.compile(r"^(?:upload a file|subir un archivo|subir archivo)$", re.IGNORECASE)
UPLOAD_FILE = re.compile(r"^(?:upload this file|subir este archivo)$", re.IGNORECASE)
SELECT_FILE = re.compile(r"^(?:select this file|seleccionar este archivo|seleccionar archivo)$", re.IGNORECASE)
DELETE = re.compile(r"^(?:yes|s[ií]|delete|eliminar|borrar)$", re.IGNORECASE)
CANCEL = re.compile(r"^(?:cancel|cancelar|close|cerrar|ok|aceptar)$", re.IGNORECASE)
POLL_ATTEMPTS = 240  # up to 60 seconds for Moodle's asynchronous file picker and uploads


def _control_text(control: Locator) -> str:
    tag = control.evaluate("element => element.tagName.toLowerCase()")
    if tag == "input":
        return control.get_attribute("value") or control.get_attribute("aria-label") or ""
    return control.inner_text()


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
        "[role='dialog'] .fp-file input[type='file']",
        ".filepicker .fp-file input[type='file']",
        ".moodle-dialogue .fp-file input[type='file']",
        "[role='dialog'] input[type='file']",
        ".filepicker input[type='file']",
        ".moodle-dialogue input[type='file']",
    ):
        inputs = page.locator(selector)
        if inputs.count():
            return inputs.last
    inputs = page.locator("input[type='file']")
    return inputs.last if inputs.count() else None


def _upload_error_message(page: Page) -> str | None:
    for selector in (
        "[role='dialog'] .fp-msg-error",
        ".filepicker .fp-msg-error",
        ".moodle-dialogue .fp-msg-error",
        "[role='dialog'] .alert-danger",
        ".filepicker .alert-danger",
        ".moodle-dialogue .alert-danger",
        ".notification-error",
        ".alert-danger",
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
        if "fm-updating" not in classes and (loaded_empty or loaded_with_files):
            return
        page.wait_for_timeout(250)
    raise RuntimeError("Moodle no terminó de cargar el área de entrega.")


def _find_dialog_action(page: Page, pattern: re.Pattern[str]) -> bool:
    dialogs = page.locator("[role='dialog'], .filepicker, .moodle-dialogue")
    for index in reversed(range(dialogs.count())):
        dialog = dialogs.nth(index)
        if dialog.is_visible() and _click_control(dialog, pattern):
            return True
    return _click_control(page, pattern)


def _dismiss_filepicker(page: Page) -> None:
    if _find_dialog_action(page, CANCEL):
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


def _stage_file(page: Page, filemanager: Locator, path: Path) -> None:
    add = filemanager.locator(".fp-btn-add, [data-action='add']")
    if not add.count() or not add.first.is_visible():
        raise RuntimeError("Moodle no muestra el control para agregar archivos.")
    add.first.click()

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

    for _ in range(POLL_ATTEMPTS):
        if error := _upload_error_message(page):
            _dismiss_filepicker(page)
            raise RuntimeError(f"Moodle rechazó el archivo: {error}")
        if path.name in _file_names(filemanager):
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
        for _ in range(POLL_ATTEMPTS):
            after = _file_names(filemanager)
            if len(after) < len(before):
                break
            page.wait_for_timeout(250)
        if len(after) >= len(before):
            raise RuntimeError("Moodle no confirmó que quitó un archivo existente.")
        removed.extend(name for name in before if name not in after)
    return removed


def _submission_file_names(page: Page) -> tuple[str, str]:
    regions = page.locator(".submissionstatustable, [data-region='submissions'], .submissionstatus")
    text_parts: list[str] = []
    for index in range(regions.count()):
        try:
            text_parts.append(regions.nth(index).inner_text())
        except Exception:
            continue
    links = page.locator("#region-main a[href*='assignsubmission_file']")
    for index in range(links.count()):
        try:
            text_parts.append(links.nth(index).inner_text())
            text_parts.append(links.nth(index).get_attribute("href") or "")
        except Exception:
            continue
    return "\n".join(text_parts), "\n".join(text_parts).casefold()


def _save_control(page: Page, filemanager: Locator) -> Locator | None:
    forms = page.locator("form").filter(has=filemanager)
    if not forms.count():
        return None
    form = forms.first
    controls = form.locator("button, input[type='submit']")
    for index in range(controls.count()):
        control = controls.nth(index)
        try:
            if control.is_visible() and SAVE.fullmatch(_control_text(control).strip()):
                return control
        except Exception:
            continue
    return None


def _preflight_files(file_paths: list[str]) -> tuple[list[Path], list[dict[str, str]]]:
    paths: list[Path] = []
    errors: list[dict[str, str]] = []
    seen_paths: set[Path] = set()
    seen_names: set[str] = set()
    for raw in file_paths:
        candidate = Path(raw).expanduser()
        try:
            path = candidate.resolve(strict=True)
            if not path.is_file():
                raise OSError("La ruta no corresponde a un archivo.")
            with path.open("rb"):
                pass
        except FileNotFoundError:
            errors.append({"name": candidate.name or "archivo", "status": "failed", "error": "El archivo local no existe."})
            continue
        except PermissionError:
            errors.append({"name": candidate.name or "archivo", "status": "failed", "error": "No se puede leer el archivo local."})
            continue
        except (OSError, RuntimeError):
            errors.append({"name": candidate.name or "archivo", "status": "failed", "error": "La ruta local no corresponde a un archivo legible."})
            continue
        if path in seen_paths:
            errors.append({"name": path.name, "status": "failed", "error": "El mismo archivo aparece más de una vez."})
            continue
        if path.name.casefold() in seen_names:
            errors.append({"name": path.name, "status": "failed", "error": "Hay más de un archivo con el mismo nombre."})
            continue
        seen_paths.add(path)
        seen_names.add(path.name.casefold())
        paths.append(path)
    return paths, errors


def upload_files(
    page: Page,
    config: Config,
    assignment_id: int,
    file_paths: list[str],
    *,
    replace_existing: bool = False,
) -> dict:
    """Agrega archivos sin enviar la tarea para calificación."""
    paths, preflight_errors = _preflight_files(file_paths)
    if preflight_errors:
        return {
            "assignment_id": assignment_id,
            "title": None,
            "status": "blocked",
            "submission_status": None,
            "files": preflight_errors + [{"name": path.name, "status": "not_uploaded"} for path in paths],
            "uploaded_files": [],
            "failed_files": [item["name"] for item in preflight_errors],
            "existing_files": [],
            "replaced_files": [],
            "sent_for_grading": False,
            "complete": False,
            "errors": [item["error"] for item in preflight_errors],
        }

    url = f"{config.base_url}/mod/assign/view.php?id={assignment_id}"
    task = read_assignment(page, url, config)
    page_text = page.locator("#region-main, main").first.inner_text() if page.locator("#region-main, main").count() else ""
    if NO_UPLOAD.search(task.content):
        return _blocked_result(assignment_id, task.title, task.status, paths, "Las instrucciones indican que no se deben subir archivos.")
    if CLOSED.search(page_text):
        return _blocked_result(assignment_id, task.title, task.status, paths, "La actividad está cerrada para entregas.")

    action = page.locator("a, button, input[type='submit']")
    action_control: Locator | None = None
    for index in range(action.count()):
        control = action.nth(index)
        try:
            if control.is_visible() and ACTION.fullmatch(_control_text(control).strip()):
                action_control = control
                break
        except Exception:
            continue
    if action_control is None:
        return _blocked_result(assignment_id, task.title, task.status, paths, "Moodle no muestra un formulario de entrega disponible.")
    action_control.click()

    managers = page.locator(".filemanager")
    if not managers.count():
        return _blocked_result(assignment_id, task.title, task.status, paths, "La actividad no muestra un área para adjuntar archivos.")
    filemanager = managers.first
    _wait_for_filemanager_ready(page, filemanager)
    existing = _file_names(filemanager)
    if existing and not replace_existing:
        return {
            "assignment_id": assignment_id,
            "title": task.title,
            "status": "blocked_existing_files",
            "submission_status": task.status,
            "files": [{"name": path.name, "status": "not_uploaded"} for path in paths],
            "uploaded_files": [],
            "failed_files": [],
            "existing_files": existing,
            "replaced_files": [],
            "sent_for_grading": False,
            "complete": False,
            "errors": ["La entrega ya contiene archivos; no se reemplazó ninguno."],
        }

    maxfiles_value = filemanager.get_attribute("data-maxfiles")
    try:
        maxfiles = int(maxfiles_value) if maxfiles_value is not None else -1
    except ValueError:
        maxfiles = -1
    if maxfiles == 0 or (maxfiles > 0 and len(paths) > maxfiles):
        return _blocked_result(assignment_id, task.title, task.status, paths, "La actividad no admite esa cantidad de archivos.")
    maxbytes_value = filemanager.get_attribute("data-maxbytes")
    try:
        maxbytes = int(maxbytes_value) if maxbytes_value else 0
    except ValueError:
        maxbytes = 0
    oversized = [path for path in paths if maxbytes > 0 and path.stat().st_size > maxbytes]
    if oversized:
        failed = [{"name": path.name, "status": "failed", "error": "El archivo supera el tamaño máximo indicado por Moodle."} for path in oversized]
        failed_names = {item["name"] for item in failed}
        return {
            "assignment_id": assignment_id,
            "title": task.title,
            "status": "blocked",
            "submission_status": task.status,
            "files": failed + [{"name": path.name, "status": "not_uploaded"} for path in paths if path.name not in failed_names],
            "uploaded_files": [],
            "failed_files": [item["name"] for item in failed],
            "existing_files": existing,
            "replaced_files": [],
            "sent_for_grading": False,
            "complete": False,
            "errors": [item["error"] for item in failed],
        }

    replaced: list[str] = []
    if existing and replace_existing:
        try:
            replaced = _remove_existing_files(page, filemanager)
        except Exception as error:
            message = redact_credentials(error, (config.username, config.password))[:500]
            return _blocked_result(assignment_id, task.title, task.status, paths, message, existing_files=existing)

    file_results: list[dict[str, str]] = []
    staged: list[Path] = []
    for path in paths:
        try:
            _stage_file(page, filemanager, path)
            staged.append(path)
            file_results.append({"name": path.name, "status": "staged"})
        except Exception as error:
            _dismiss_filepicker(page)
            file_results.append({"name": path.name, "status": "failed", "error": _file_error(error, path, config)})

    if not staged:
        return {
            "assignment_id": assignment_id,
            "title": task.title,
            "status": "failed",
            "submission_status": task.status,
            "files": file_results,
            "uploaded_files": [],
            "failed_files": [item["name"] for item in file_results if item["status"] == "failed"],
            "existing_files": existing,
            "replaced_files": [],
            "sent_for_grading": False,
            "complete": False,
            "errors": [item.get("error", "No se pudo adjuntar el archivo.") for item in file_results],
        }

    failed = any(item["status"] == "failed" for item in file_results)
    if failed and existing and replace_existing:
        return {
            "assignment_id": assignment_id,
            "title": task.title,
            "status": "replacement_cancelled",
            "submission_status": task.status,
            "files": [{"name": path.name, "status": "not_saved" if path in staged else "failed",
                       **({"error": next((item["error"] for item in file_results if item["name"] == path.name and item["status"] == "failed"), "")}
                          if path not in staged else {})} for path in paths],
            "uploaded_files": [],
            "failed_files": [item["name"] for item in file_results if item["status"] == "failed"],
            "existing_files": existing,
            "replaced_files": [],
            "sent_for_grading": False,
            "complete": False,
            "errors": ["La sustitución se canceló porque falló al menos un archivo; la entrega existente se conserva."],
        }

    save = _save_control(page, filemanager)
    if save is None:
        return {
            "assignment_id": assignment_id,
            "title": task.title,
            "status": "failed",
            "submission_status": task.status,
            "files": [{"name": path.name, "status": "not_saved"} for path in staged] + [item for item in file_results if item["status"] == "failed"],
            "uploaded_files": [],
            "failed_files": [item["name"] for item in file_results if item["status"] == "failed"],
            "existing_files": existing,
            "replaced_files": [],
            "sent_for_grading": False,
            "complete": False,
            "errors": ["Moodle no mostró el botón Guardar cambios; no se guardó la entrega."],
        }

    try:
        save.click()
        final_task = read_assignment(page, url, config)
    except Exception as error:
        message = redact_credentials(error, (config.username, config.password))[:500]
        return {
            "assignment_id": assignment_id,
            "title": task.title,
            "status": "save_unconfirmed",
            "submission_status": task.status,
            "files": [{"name": path.name, "status": "save_unconfirmed"} for path in staged] + [item for item in file_results if item["status"] == "failed"],
            "uploaded_files": [],
            "failed_files": [item["name"] for item in file_results if item["status"] == "failed"],
            "existing_files": existing,
            "replaced_files": replaced,
            "sent_for_grading": False,
            "complete": False,
            "errors": [f"Moodle no confirmó el guardado: {message}"],
        }

    _, verification_folded = _submission_file_names(page)
    for item in file_results:
        if item["status"] not in ("staged", "failed"):
            continue
        if item["name"].casefold() in verification_folded:
            item["status"] = "uploaded"
            item.pop("error", None)
        elif item["status"] == "staged":
            item["status"] = "saved_unconfirmed"

    uploaded = [item["name"] for item in file_results if item["status"] == "uploaded"]
    failed_names = [item["name"] for item in file_results if item["status"] == "failed"]
    unconfirmed = [item["name"] for item in file_results if item["status"] == "saved_unconfirmed"]
    final_status = "uploaded" if not failed_names and not unconfirmed else "partial"
    errors = [item["error"] for item in file_results if "error" in item]
    if unconfirmed:
        errors.append("Moodle guardó el formulario, pero no confirmó todos los nombres en la página de entrega.")
    return {
        "assignment_id": assignment_id,
        "title": task.title,
        "status": final_status,
        "submission_status": final_task.status,
        "files": file_results,
        "uploaded_files": uploaded,
        "failed_files": failed_names,
        "existing_files": existing,
        "replaced_files": replaced,
        "sent_for_grading": False,
        "complete": final_status == "uploaded",
        "errors": errors,
    }


def _blocked_result(
    assignment_id: int,
    title: str,
    submission_status: str,
    paths: list[Path],
    message: str,
    *,
    existing_files: list[str] | None = None,
) -> dict:
    return {
        "assignment_id": assignment_id,
        "title": title,
        "status": "blocked",
        "submission_status": submission_status,
        "files": [{"name": path.name, "status": "not_uploaded"} for path in paths],
        "uploaded_files": [],
        "failed_files": [],
        "existing_files": existing_files or [],
        "replaced_files": [],
        "sent_for_grading": False,
        "complete": False,
        "errors": [message],
    }
