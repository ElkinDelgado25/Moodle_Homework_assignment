"""Texto de los anexos descargados, para que el agente lea la consigna sin abrir el archivo."""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_FILE_CHARS = 15_000
MAX_SOURCE_BYTES = 30 * 1024 * 1024
PLAIN_SUFFIXES = frozenset({".txt", ".md", ".csv", ".json", ".xml", ".html", ".py", ".java", ".js", ".ts", ".sql",
                            ".c", ".cpp", ".h", ".cs", ".php", ".yml", ".yaml"})
DRAWING_TEXT = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
DRAWING_PARAGRAPH = "{http://schemas.openxmlformats.org/drawingml/2006/main}p"


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    return "\n\n".join((page.extract_text() or "").strip() for page in PdfReader(str(path)).pages)


def _docx(path: Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(str(path))
    parts: list[str] = []
    # En el orden del documento: una tabla entre dos párrafos se lee donde está.
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            parts.append(Paragraph(child, document).text)
        elif child.tag.endswith("}tbl"):
            for row in Table(child, document).rows:
                cells = list(dict.fromkeys(" ".join(cell.text.split()) for cell in row.cells))
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _pptx(path: Path) -> str:
    slides: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted((name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                       key=lambda name: int(re.search(r"\d+", name.rsplit("/", 1)[-1]).group()))
        for index, name in enumerate(names, start=1):
            root = ET.fromstring(archive.read(name))
            lines = ["".join(node.text or "" for node in paragraph.iter(DRAWING_TEXT))
                     for paragraph in root.iter(DRAWING_PARAGRAPH)]
            slides.append(f"[Diapositiva {index}]\n" + "\n".join(line for line in lines if line.strip()))
    return "\n\n".join(slides)


def _plain(path: Path) -> str:
    return path.read_bytes().decode("utf-8", "replace")


READERS = {".pdf": _pdf, ".docx": _docx, ".pptx": _pptx, **{suffix: _plain for suffix in PLAIN_SUFFIXES}}


def extract_text(path: Path, max_chars: int = MAX_FILE_CHARS) -> dict:
    """Campos de texto para el resultado de una descarga; vacío si el formato no tiene texto legible aquí.

    El texto es material de la actividad: se entrega tal cual, recortado a max_chars.
    """
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        return {}
    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            return {"text_error": "El archivo es demasiado grande para extraer su texto; ábrelo desde su ruta."}
        text = reader(path)
    except Exception:
        return {"text_error": "No se pudo extraer el texto; abre el archivo desde su ruta."}
    text = re.sub(r"[ \t\f\v]+", " ", text.replace("\x00", ""))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if not text:
        return {"text_error": "El archivo no contiene texto extraíble (puede ser un documento escaneado)."}
    if max_chars <= 0:
        return {"text_chars": len(text), "text_truncated": True}
    result: dict = {"text": text[:max_chars], "text_chars": len(text)}
    if len(text) > max_chars:
        result["text_truncated"] = True
    return result
