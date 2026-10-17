"""Carpeta de trabajo y apertura del PDF en el navegador predeterminado."""

import shutil
import tempfile
import webbrowser
from pathlib import Path


def prepare_workspace() -> Path:
    """Directorio temporal sin depender del nombre de la carpeta final."""
    return Path(tempfile.mkdtemp(prefix="moodle-doc-"))


def finish_delivery(docx_path: str, pdf_path: str, destination_directory: str) -> dict:
    """Copia el Word y el PDF ya exportados y abre el PDF como un solo archivo."""
    docx = Path(docx_path).expanduser().resolve(strict=True)
    pdf = Path(pdf_path).expanduser().resolve(strict=True)
    if docx.suffix.lower() != ".docx" or not docx.is_file():
        raise ValueError("Se necesita el archivo DOCX exportable.")
    if pdf.suffix.lower() != ".pdf" or not pdf.is_file():
        raise ValueError("Se necesita el PDF exportado desde ese DOCX.")
    destination = Path(destination_directory).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise ValueError("La carpeta de entrega no es válida.")
    final_docx = destination / docx.name
    final_pdf = destination / pdf.name
    if final_docx != docx:
        shutil.copy2(docx, final_docx)
    if final_pdf != pdf:
        shutil.copy2(pdf, final_pdf)
    opened = webbrowser.open(final_pdf.as_uri())
    return {
        "docx_path": str(final_docx),
        "pdf_path": str(final_pdf),
        "opened_in_browser": bool(opened),
    }
