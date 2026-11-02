"""Construye el entregable DOCX + PDF con la portada ULEAM y formato APA 7."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from .document_model import COVER_FIELDS, REQUIRED_COVER_FIELDS, CoverFields, DeliveryDocument, parse_inline
from .paths import resolve_local_file
from .storage import user_cache_dir


ASSETS = Path(__file__).resolve().parent / "assets"
TEMPLATE = ASSETS / "academic-cover.docx"
LOGO = ASSETS / "uleam-logo.png"
HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
EXPORT_TIMEOUT_SECONDS = 120
_export_lock = threading.Lock()


class MissingCoverFields(ValueError):
    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__("Faltan datos de portada: " + ", ".join(fields))


def safe_file_name(value: str) -> str:
    """Nombre base válido en Windows, macOS y Linux, sin extensión."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]', " ", value)
    name = " ".join(name.split()).strip(" .")
    if name.lower().endswith((".docx", ".pdf")):
        name = name.rsplit(".", 1)[0].strip(" .")
    while len(name.encode("utf-8")) > 150:
        name = name[:-1].rstrip(" .")
    if not name:
        name = "Entrega"
    if name.split(".", 1)[0].upper() in RESERVED:
        name = "_" + name
    return name


def cover_values(cover: CoverFields, profile: dict) -> dict[str, str]:
    """Une los datos dados con el perfil verificado; el docente, curso y año nunca se deducen."""
    values = {field: getattr(cover, field) or "" for field in COVER_FIELDS}
    if not values["student_1"] and isinstance(profile.get("student_1"), str):
        values["student_1"] = " ".join(profile["student_1"].split())
    for field in ("teacher", "degree", "class_group", "year", "subject"):
        if not values[field] and isinstance(profile.get(field), str):
            values[field] = " ".join(profile[field].split())
    missing = [field for field in REQUIRED_COVER_FIELDS if not values[field]]
    if missing:
        raise MissingCoverFields(missing)
    return values


# ---------------------------------------------------------------- DOCX


def _add_hyperlink(paragraph, text: str, url: str, *, bold=False, italic=False) -> None:
    relation = paragraph.part.relate_to(url, HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relation)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    style = OxmlElement("w:rStyle")
    style.set(qn("w:val"), "Hyperlink")
    properties.append(style)
    for flag, tag in ((bold, "w:b"), (italic, "w:i")):
        if flag:
            properties.append(OxmlElement(tag))
    run.append(properties)
    node = OxmlElement("w:t")
    node.set(qn("xml:space"), "preserve")
    node.text = text
    run.append(node)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _write_inline(paragraph, text: str, *, force_bold=False, force_italic=False) -> None:
    for segment in parse_inline(text):
        bold, italic = segment["bold"] or force_bold, segment["italic"] or force_italic
        if segment["link"]:
            _add_hyperlink(paragraph, segment["text"], segment["link"], bold=bold, italic=italic)
        else:
            run = paragraph.add_run(segment["text"])
            run.bold = bold or None
            run.italic = italic or None


def _paragraphs(text: str) -> list[str]:
    return [" ".join(part.split()) for part in re.split(r"\n\s*\n", text) if part.strip()]


def _fill_cover(document, values: dict[str, str]) -> None:
    placeholders = {f"{{{{{key}}}}}": value for key, value in values.items()}
    body = list(document.paragraphs)
    student_1 = next((p for p in body if p.text.strip() == "{{student_1}}"), None)
    for paragraph in body:
        if paragraph.text.strip() == "{{student_2}}" and not values.get("student_2"):
            # Conserva la posición de "Carrera:" sumando el hueco al párrafo anterior.
            if student_1 is not None:
                before = student_1.paragraph_format.space_after or Pt(0)
                after = paragraph.paragraph_format.space_after or Pt(0)
                student_1.paragraph_format.space_after = Pt(before.pt + 24 + after.pt)
            paragraph._p.getparent().remove(paragraph._p)
            continue
        for run in paragraph.runs:
            for placeholder, value in placeholders.items():
                if placeholder in run.text:
                    run.text = run.text.replace(placeholder, value)


def _restart_numbering(document, paragraph) -> str:
    """Nueva instancia de numeración para que cada lista numerada empiece en 1."""
    numbering = document.part.numbering_part.element
    style = document.styles["List Number"].element
    num_pr = style.pPr.find(qn("w:numPr")) if style.pPr is not None else None
    base_id = num_pr.find(qn("w:numId")).get(qn("w:val")) if num_pr is not None else None
    abstract = None
    for num in numbering.findall(qn("w:num")):
        if num.get(qn("w:numId")) == base_id:
            abstract = num.find(qn("w:abstractNumId")).get(qn("w:val"))
    if abstract is None:
        return ""
    new_id = str(max(int(num.get(qn("w:numId"))) for num in numbering.findall(qn("w:num"))) + 1)
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), new_id)
    abstract_ref = OxmlElement("w:abstractNumId")
    abstract_ref.set(qn("w:val"), abstract)
    num.append(abstract_ref)
    override = OxmlElement("w:lvlOverride")
    override.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:startOverride")
    start.set(qn("w:val"), "1")
    override.append(start)
    num.append(override)
    numbering.append(num)
    return new_id


def _set_num(paragraph, num_id: str) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num = OxmlElement("w:numId")
    num.set(qn("w:val"), num_id)
    num_pr.extend([ilvl, num])
    p_pr.append(num_pr)


def _border(parent, edge: str, value: str = "single") -> None:
    element = OxmlElement(f"w:{edge}")
    element.set(qn("w:val"), value)
    element.set(qn("w:sz"), "6" if value != "nil" else "0")
    element.set(qn("w:space"), "0")
    element.set(qn("w:color"), "000000")
    parent.append(element)


def _apa_table(document, rows: list[list[str]]):
    table = document.add_table(rows=len(rows), cols=len(rows[0]))
    properties = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge, value in (("top", "single"), ("left", "nil"), ("bottom", "single"),
                        ("right", "nil"), ("insideH", "nil"), ("insideV", "nil")):
        _border(borders, edge, value)
    properties.append(borders)
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            cell = table.cell(row_index, column)
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.first_line_indent = Cm(0)
            paragraph.paragraph_format.line_spacing = 1
            _write_inline(paragraph, value, force_bold=row_index == 0)
            if row_index == 0:
                cell_borders = OxmlElement("w:tcBorders")
                _border(cell_borders, "bottom")
                cell._tc.get_or_add_tcPr().append(cell_borders)
    return table


def _label(document, label: str, title: str) -> None:
    number = document.add_paragraph()
    number.paragraph_format.first_line_indent = Cm(0)
    number.paragraph_format.keep_with_next = True
    number.add_run(label).bold = True
    caption = document.add_paragraph()
    caption.paragraph_format.first_line_indent = Cm(0)
    caption.paragraph_format.keep_with_next = True
    _write_inline(caption, title, force_italic=True)


def _note(document, note: str | None) -> None:
    if not note:
        return
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.first_line_indent = Cm(0)
    paragraph.add_run("Nota. ").italic = True
    _write_inline(paragraph, note)


def build_docx(content: DeliveryDocument, values: dict[str, str], output: Path) -> dict:
    document = Document(str(TEMPLATE))
    _fill_cover(document, {**values, "title": content.title})

    title = document.add_paragraph(style="Title")
    title.paragraph_format.page_break_before = True
    _write_inline(title, content.title)
    tables = figures = 0
    pending_break = False

    def new_paragraph(style=None):
        nonlocal pending_break
        paragraph = document.add_paragraph(style=style)
        if pending_break:
            paragraph.paragraph_format.page_break_before = True
            pending_break = False
        return paragraph

    for block in content.blocks:
        if block.type == "page_break":
            pending_break = True
        elif block.type == "heading":
            _write_inline(new_paragraph(f"Heading {block.level}"), " ".join(block.text.split()))
        elif block.type == "paragraph":
            for text in _paragraphs(block.text):
                _write_inline(new_paragraph(), text)
        elif block.type == "quote":
            for text in _paragraphs(block.text):
                paragraph = new_paragraph()
                paragraph.paragraph_format.left_indent = Cm(1.27)
                paragraph.paragraph_format.first_line_indent = Cm(0)
                _write_inline(paragraph, text)
        elif block.type in ("bullets", "numbered"):
            num_id = None
            for item in block.items:
                paragraph = new_paragraph("List Bullet" if block.type == "bullets" else "List Number")
                paragraph.paragraph_format.first_line_indent = None
                if block.type == "numbered":
                    num_id = num_id or _restart_numbering(document, paragraph)
                    if num_id:
                        _set_num(paragraph, num_id)
                _write_inline(paragraph, " ".join(item.split()))
        elif block.type == "code":
            paragraph = new_paragraph("Source Code")
            for index, line in enumerate(block.text.split("\n")):
                run = paragraph.add_run()
                if index:
                    run.add_break()
                run.add_text(line)
        elif block.type == "table":
            tables += 1
            if pending_break:
                new_paragraph().paragraph_format.first_line_indent = Cm(0)
            _label(document, f"Tabla {tables}", block.title)
            _apa_table(document, block.rows)
            _note(document, block.note)
        elif block.type == "figure":
            figures += 1
            image = resolve_local_file(block.path)
            with image.open("rb") as handle:
                head = handle.read(8)
            if not (head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff")):
                raise ValueError(f"La figura {figures} no es una imagen PNG o JPEG válida.")
            if image.stat().st_size > 20 * 1024 * 1024:
                raise ValueError(f"La figura {figures} supera 20 MB.")
            if pending_break:
                new_paragraph().paragraph_format.first_line_indent = Cm(0)
            _label(document, f"Figura {figures}", block.title)
            picture = document.add_paragraph()
            picture.paragraph_format.first_line_indent = Cm(0)
            picture.paragraph_format.keep_with_next = bool(block.note)
            picture.add_run().add_picture(str(image), width=Cm(block.width_cm or 14))
            _note(document, block.note)

    if content.references:
        heading = document.add_paragraph(style="Heading 1")
        heading.paragraph_format.page_break_before = True
        heading.add_run("Referencias")
        for reference in sorted(content.references, key=lambda value: re.sub(r"[*\[\]]", "", value).casefold()):
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Cm(1.27)
            paragraph.paragraph_format.first_line_indent = Cm(-1.27)
            _write_inline(paragraph, reference)

    properties = document.core_properties
    now = datetime.now(timezone.utc).replace(microsecond=0)
    properties.title = content.title
    properties.subject = values.get("subject", "")
    properties.author = "; ".join(value for value in (values.get("student_1"), values.get("student_2")) if value)
    properties.last_modified_by = properties.author
    properties.created = properties.modified = now
    properties.revision = 1
    properties.language = "es-EC"
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output))
    return {"tables": tables, "figures": figures}


# ---------------------------------------------------------------- PDF


def find_soffice() -> list[str] | None:
    """Ejecutable de LibreOffice instalado (opcional); None si no existe."""
    override = os.environ.get("MOODLE_SOFFICE")
    if override:
        return [override] if Path(override).is_file() else None
    for name in ("soffice", "libreoffice", "lowriter"):
        found = shutil.which(name)
        if found:
            return [found]
    candidates = []
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                candidates.append(Path(root) / "LibreOffice/program/soffice.exe")
    elif sys.platform == "darwin":
        candidates += [Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
                       Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice"]
    else:
        candidates += [Path("/opt/libreoffice/program/soffice"), Path("/snap/bin/libreoffice")]
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]
    return None


def export_with_libreoffice(command: list[str], docx: Path, outdir: Path, timeout: int = EXPORT_TIMEOUT_SECONDS) -> Path:
    profile = user_cache_dir() / "libreoffice-profile"
    profile.mkdir(parents=True, exist_ok=True)
    argv = [*command, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
            "--nolockcheck", "--convert-to", "pdf", "--outdir", str(outdir), str(docx)]
    expected = outdir / (docx.stem + ".pdf")
    expected.unlink(missing_ok=True)
    with _export_lock:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=sys.platform != "win32")
        try:
            _, error = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError("LibreOffice no terminó la exportación a PDF a tiempo.") from None
    if not expected.is_file() or expected.stat().st_size == 0:
        detail = (error or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise RuntimeError("LibreOffice no generó el PDF. " + detail[0])
    return expected


def export_pdf(content: DeliveryDocument, values: dict[str, str], docx: Path, engine: str = "auto") -> tuple[Path, str, list[str]]:
    """LibreOffice si está instalado; si no, el renderizador integrado con la misma maquetación."""
    from .pdf_render import render_pdf

    warnings: list[str] = []
    pdf = docx.with_suffix(".pdf")
    command = find_soffice() if engine in ("auto", "libreoffice") else None
    if command:
        try:
            return export_with_libreoffice(command, docx, docx.parent), "libreoffice", warnings
        except (OSError, RuntimeError) as error:
            if engine == "libreoffice":
                raise
            warnings.append(f"LibreOffice falló ({error}); se usó el renderizador integrado.")
    elif engine == "libreoffice":
        raise RuntimeError("No se encontró LibreOffice instalado.")
    fonts = render_pdf(content, values, pdf)
    if fonts != "Times New Roman":
        warnings.append(f"Times New Roman no está instalada; el PDF usa {fonts}.")
    return pdf, "builtin", warnings


def build_delivery(content: DeliveryDocument, values: dict[str, str], workspace: Path, file_name: str,
                   engine: str = "auto") -> dict:
    """DOCX y PDF en la carpeta de trabajo; la copia final la hace delivery.copy_pair."""
    stem = safe_file_name(file_name)
    # El nombre interno es ASCII: evita problemas de rutas con tildes al exportar.
    staging = Path(tempfile.mkdtemp(prefix="build-", dir=workspace))
    docx = staging / "entrega.docx"
    counts = build_docx(content, values, docx)
    pdf, used, warnings = export_pdf(content, values, docx, engine)
    final_docx, final_pdf = staging / f"{stem}.docx", staging / f"{stem}.pdf"
    os.replace(docx, final_docx)
    os.replace(pdf, final_pdf)
    return {"docx": final_docx, "pdf": final_pdf, "engine": used, "warnings": warnings, **counts}

