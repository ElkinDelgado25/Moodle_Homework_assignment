"""Carpeta de trabajo, copia final sin sobrescribir y apertura segura del PDF."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .paths import resolve_destination_directory, resolve_local_file
from .storage import user_cache_dir
from .verification import DocumentCheckError, check_delivery_pair


WORKSPACE_MAX_AGE_SECONDS = 7 * 24 * 3600


def workspaces_root() -> Path:
    return user_cache_dir() / "workspaces"


def cleanup_workspaces(now: float | None = None) -> int:
    """Borra carpetas de trabajo antiguas; nunca toca la carpeta de entrega."""
    root = workspaces_root()
    if not root.is_dir():
        return 0
    limit = (now or time.time()) - WORKSPACE_MAX_AGE_SECONDS
    removed = 0
    for child in root.iterdir():
        try:
            if child.is_dir() and not child.is_symlink() and child.name.startswith("moodle-doc-") and child.stat().st_mtime < limit:
                shutil.rmtree(child)
                removed += 1
        except OSError:
            continue
    return removed


def prepare_workspace() -> Path:
    """Directorio propio de la aplicación, sin depender del nombre de la carpeta final."""
    root = workspaces_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    cleanup_workspaces()
    return Path(tempfile.mkdtemp(prefix="moodle-doc-", dir=root))


def has_display() -> bool:
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def open_file(path: Path) -> bool:
    """Abre con la aplicación predeterminada sin heredar el stdio del servidor MCP."""
    if not has_display():
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - ruta local validada
            return True
        command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
        if not shutil.which(command[0]):
            return False
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        return True
    except OSError:
        return False


def available_pair(directory: Path, stem: str) -> tuple[Path, Path]:
    """Primer nombre base libre para el DOCX y el PDF a la vez: nombre, nombre (1), ..."""
    for index in range(1000):
        base = stem if index == 0 else f"{stem} ({index})"
        docx, pdf = directory / f"{base}.docx", directory / f"{base}.pdf"
        if not docx.exists() and not pdf.exists() and not docx.is_symlink() and not pdf.is_symlink():
            return docx, pdf
    raise FileExistsError("Hay demasiadas versiones con ese nombre en la carpeta de entrega.")


def copy_pair(docx: Path, pdf: Path, destination: Path) -> tuple[Path, Path]:
    """Copia ambos archivos o ninguno: primero a temporales, luego renombra."""
    destination.mkdir(parents=True, exist_ok=True)
    final_docx, final_pdf = available_pair(destination, docx.stem)
    staged: list[tuple[Path, Path]] = []
    placed: list[Path] = []
    try:
        for source, target in ((docx, final_docx), (pdf, final_pdf)):
            descriptor, temporary = tempfile.mkstemp(dir=destination, prefix=".moodle-", suffix=target.suffix)
            os.close(descriptor)
            staged.append((Path(temporary), target))
            shutil.copy2(source, temporary)
        for temporary, target in staged:
            if target.exists():
                raise FileExistsError(f"{target.name} apareció durante la copia.")
            os.replace(temporary, target)
            placed.append(target)
    except BaseException:
        for target in placed:
            target.unlink(missing_ok=True)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return final_docx, final_pdf


def finish_delivery(docx_path: str, pdf_path: str, destination_directory: str, *, open_pdf: bool = True) -> dict:
    """Verifica el par DOCX/PDF, lo copia sin sobrescribir y abre el PDF."""
    docx = resolve_local_file(docx_path)
    pdf = resolve_local_file(pdf_path)
    for path, suffix, label in ((docx, ".docx", "DOCX exportable"), (pdf, ".pdf", "PDF exportado desde ese DOCX")):
        if path.suffix.lower() != suffix or not path.is_file():
            raise ValueError(f"Se necesita el archivo {label}.")
    checks = check_delivery_pair(docx, pdf)
    if not checks["ok"]:
        raise DocumentCheckError("La entrega no pasó la verificación: " + " ".join(checks["errors"]))
    destination = resolve_destination_directory(destination_directory)
    if docx.parent == destination and pdf.parent == destination:
        final_docx, final_pdf = docx, pdf
    else:
        final_docx, final_pdf = copy_pair(docx, pdf, destination)
    opened = open_file(final_pdf) if open_pdf else False
    return {
        "docx_path": str(final_docx),
        "pdf_path": str(final_pdf),
        "opened": opened,
        "checks": checks,
    }
