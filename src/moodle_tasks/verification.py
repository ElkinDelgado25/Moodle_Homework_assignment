"""Comprobaciones de DOCX y PDF terminados, sin depender del agente que los creó."""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from pypdf import PdfReader
from pypdf.errors import PdfReadError


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
HYPERLINK_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
# Solo los campos de la portada: un informe puede citar código con {{ variable }} (Vue, Jinja...).
TEMPLATE_FIELDS = ("title", "subject", "teacher", "student_1", "student_2", "degree", "class_group", "year")
PLACEHOLDER = re.compile(r"\{\{\s*(?:" + "|".join(TEMPLATE_FIELDS) + r")\s*\}\}")
THEME_ATTRIBUTES = ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme")
EXPECTED_FONT = "Times New Roman"


class DocumentCheckError(ValueError):
    """El archivo no es un entregable válido."""


def _text_parts(archive: zipfile.ZipFile) -> list[str]:
    return [name for name in archive.namelist()
            if re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml", name)]


def inspect_docx(path: Path) -> dict:
    """Abre el DOCX como paquete OOXML y devuelve hallazgos; lanza error si no es un DOCX."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise DocumentCheckError("El DOCX no es un paquete válido (archivo dañado o de otro tipo).") from None
    with archive:
        if "word/document.xml" not in archive.namelist():
            raise DocumentCheckError("El DOCX no contiene word/document.xml.")
        text = []
        for name in _text_parts(archive):
            try:
                root = ET.fromstring(archive.read(name))
            except ET.ParseError:
                raise DocumentCheckError(f"El DOCX tiene XML dañado en {name}.") from None
            for paragraph in root.iter(W + "p"):
                text.append("".join(node.text or "" for node in paragraph.iter(W + "t")))
        joined = "\n".join(text)
        placeholders = sorted(set(PLACEHOLDER.findall(joined)))
        links = []
        for name in archive.namelist():
            if name.startswith("word/_rels/") and name.endswith(".rels"):
                for relation in ET.fromstring(archive.read(name)).iter(REL + "Relationship"):
                    if relation.get("Type") == HYPERLINK_TYPE:
                        links.append(relation.get("Target", ""))
        theme_styles, fonts = [], set()
        if "word/styles.xml" in archive.namelist():
            styles = ET.fromstring(archive.read("word/styles.xml"))
            for style in styles.iter(W + "style"):
                style_id = style.get(W + "styleId", "")
                for node in style.iter(W + "rFonts"):
                    if node.get(W + "ascii"):
                        fonts.add(node.get(W + "ascii"))
                    if any(node.get(W + attribute) for attribute in THEME_ATTRIBUTES):
                        theme_styles.append(style_id)
            defaults = styles.find(W + "docDefaults")
            if defaults is not None:
                for node in defaults.iter(W + "rFonts"):
                    if any(node.get(W + attribute) for attribute in THEME_ATTRIBUTES):
                        theme_styles.append("docDefaults")
    return {
        "placeholders": placeholders,
        "hyperlinks": sorted(set(links)),
        "theme_font_styles": sorted(set(theme_styles)),
        "fonts": sorted(fonts),
        "characters": len(joined),
    }


def inspect_pdf(path: Path) -> dict:
    """Cuenta páginas y enlaces del PDF; lanza error si no es un PDF legible."""
    try:
        with path.open("rb") as handle:
            if not handle.read(5).startswith(b"%PDF-"):
                raise DocumentCheckError("El PDF no tiene una cabecera %PDF- válida.")
        reader = PdfReader(str(path))
        pages = len(reader.pages)
        links, fonts = set(), set()
        for page in reader.pages:
            for annotation in page.get("/Annots") or []:
                action = annotation.get_object().get("/A")
                if action and action.get("/URI"):
                    links.add(str(action["/URI"]))
            resources = page.get("/Resources") or {}
            for font in (resources.get("/Font") or {}).values():
                name = str(font.get_object().get("/BaseFont", ""))
                if name:
                    fonts.add(name.split("+", 1)[-1].lstrip("/"))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except DocumentCheckError:
        raise
    except (PdfReadError, OSError, ValueError, KeyError):
        raise DocumentCheckError("El PDF está dañado o no se puede leer.") from None
    return {
        "pages": pages,
        "hyperlinks": sorted(links),
        "fonts": sorted(fonts),
        "placeholders": sorted(set(PLACEHOLDER.findall(text))),
    }


def check_delivery_pair(docx: Path, pdf: Path) -> dict:
    """Une las comprobaciones del par DOCX/PDF y separa errores de advertencias."""
    errors, warnings = [], []
    if docx.stem != pdf.stem:
        errors.append("El DOCX y el PDF deben tener el mismo nombre base.")
    word = inspect_docx(docx)
    portable = inspect_pdf(pdf)
    if word["placeholders"] or portable["placeholders"]:
        errors.append("Quedan campos sin completar: " + ", ".join(sorted(set(word["placeholders"] + portable["placeholders"]))))
    if portable["pages"] < 1:
        errors.append("El PDF no tiene páginas.")
    if pdf.stat().st_mtime + 1 < docx.stat().st_mtime:
        warnings.append("El PDF es anterior al DOCX; puede no reflejar la última versión.")
    missing_links = [link for link in word["hyperlinks"] if link not in portable["hyperlinks"]]
    if missing_links:
        warnings.append("Enlaces del DOCX sin enlace en el PDF: " + ", ".join(missing_links))
    if word["theme_font_styles"]:
        warnings.append("Estilos con fuente del tema (pueden no salir en Times New Roman): " + ", ".join(word["theme_font_styles"]))
    if portable["fonts"] and not any("Times" in font for font in portable["fonts"]):
        warnings.append("El PDF no incrusta Times New Roman: " + ", ".join(portable["fonts"]))
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "pages": portable["pages"], "hyperlinks": portable["hyperlinks"], "pdf_fonts": portable["fonts"]}
