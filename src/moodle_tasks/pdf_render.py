"""Renderizador PDF integrado: misma portada y formato APA 7 que el DOCX, sin LibreOffice ni Word."""

import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import TableBordersLayout, XPos, YPos
from PIL import Image

from .document_model import DeliveryDocument, parse_inline


# fontTools registra cada paso del subconjunto de fuentes en INFO: llenaría los registros del cliente MCP.
for _logger in ("fontTools", "fontTools.subset", "fpdf"):
    logging.getLogger(_logger).setLevel(logging.WARNING)

ASSETS = Path(__file__).resolve().parent / "assets"
PT = 25.4 / 72
MARGIN = 25.4
HEADER_Y = 12.7
INDENT = 12.7
LINE = 12 * 1.149 * 2 * PT          # interlineado doble de Times New Roman en Word y WPS
SINGLE = 12 * 1.149 * PT
LINK_COLOR = (5, 99, 193)
# Posición (en puntos) de cada línea de la portada, igual que scripts/build_document_template.py.
COVER_LINES = [
    ("Universidad Laica “Eloy Alfaro de Manabí”", True, 72), ("{{title}}", True, 120),
    ("Materia:", True, 168), ("{{subject}}", False, 192), ("Docente:", True, 216), ("{{teacher}}", False, 240),
    ("Estudiantes:", True, 288), ("{{student_1}}", False, 312), ("{{student_2}}", False, 336),
    ("Carrera:", True, 384), ("{{degree}}", False, 408), ("Curso:", True, 456), ("{{class_group}}", False, 480),
    ("Año:", True, 504), ("{{year}}", False, 528),
]
TIMES_FILES = {
    "win32": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "darwin": ("Times New Roman.ttf", "Times New Roman Bold.ttf", "Times New Roman Italic.ttf",
               "Times New Roman Bold Italic.ttf"),
}
STYLES = ("", "B", "I", "BI")
FC_STYLES = ("Regular", "Bold", "Italic", "Bold Italic")


def _fontconfig(family: str) -> list[Path] | None:
    if not shutil.which("fc-match"):
        return None
    files = []
    for style in FC_STYLES:
        try:
            output = subprocess.run(["fc-match", "-f", "%{family}\t%{file}", f"{family}:style={style}"],
                                    capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        names, _, path = output.partition("\t")
        if family.casefold() not in names.casefold() or not path.lower().endswith((".ttf", ".otf")):
            return None
        files.append(Path(path))
    return files if all(path.is_file() for path in files) else None


def find_serif_fonts() -> tuple[str, list[Path] | None]:
    """Times New Roman si está instalada; si no, una serif compatible; None = fuente base del PDF."""
    if sys.platform == "win32":
        root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        files = [root / name for name in TIMES_FILES["win32"]]
        if all(path.is_file() for path in files):
            return "Times New Roman", files
    if sys.platform == "darwin":
        for root in (Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"), Path.home() / "Library/Fonts"):
            files = [root / name for name in TIMES_FILES["darwin"]]
            if all(path.is_file() for path in files):
                return "Times New Roman", files
    for family in ("Times New Roman", "Liberation Serif", "Tinos", "DejaVu Serif"):
        files = _fontconfig(family)
        if files:
            return family, files
    return "Times", None


class _Renderer(FPDF):
    def __init__(self, family: str, files: list[Path] | None):
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, MARGIN)
        self.unicode = files is not None
        if files:
            for style, path in zip(STYLES, files):
                self.add_font("Serif", style, str(path))
            self.family_name = "Serif"
        else:
            self.family_name = "Times"
        self.font_label = family
        self.cover = True

    def text(self, value: str) -> str:  # noqa: D401 - convierte para la fuente base
        return value if self.unicode else value.encode("latin-1", "replace").decode("latin-1")

    def header(self):
        self.set_font(self.family_name, "", 12)
        self.set_text_color(0, 0, 0)
        if self.cover and self.page_no() == 1:
            self.image(str(ASSETS / "uleam-logo.png"), x=MARGIN, y=HEADER_Y, w=37.5)
        self.set_xy(MARGIN, HEADER_Y)
        self.cell(0, SINGLE, str(self.page_no()), align="R")
        self.set_xy(MARGIN, MARGIN)

    def style(self, bold=False, italic=False, size=12, underline=False):
        self.set_font(self.family_name, ("B" if bold else "") + ("I" if italic else "") + ("U" if underline else ""), size)

    def segments(self, text: str, *, bold=False, italic=False, height=LINE):
        for segment in parse_inline(text):
            link = segment["link"]
            self.style(segment["bold"] or bold, segment["italic"] or italic, underline=bool(link))
            if link:
                self.set_text_color(*LINK_COLOR)
            self.write(height, self.text(segment["text"]), link=link or "")
            self.set_text_color(0, 0, 0)

    def plain(self, text: str) -> str:
        return "".join(segment["text"] for segment in parse_inline(text))

    def keep_room(self, height: float):
        if self.will_page_break(height):
            self.add_page()

    def paragraph(self, text: str, *, indent=INDENT, left=0.0, hanging=False):
        self.keep_room(LINE)
        base = self.l_margin
        self.set_left_margin(base + left + (INDENT if hanging else 0))
        self.set_x(base + left + (0 if hanging else indent))
        self.segments(text)
        self.ln(LINE)
        self.set_left_margin(base)

    def centered(self, text: str, *, bold=True, italic=False):
        self.style(bold, italic)
        self.multi_cell(0, LINE, self.text(self.plain(text)), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _paragraphs(text: str) -> list[str]:
    return [" ".join(part.split()) for part in re.split(r"\n\s*\n", text) if part.strip()]


def render_cover(pdf: _Renderer, values: dict[str, str]) -> None:
    lines = [(text.replace("{{" + key + "}}", value) if "{{" in text else text, bold, position)
             for text, bold, position in COVER_LINES
             for key, value in [(text.strip("{}"), values.get(text.strip("{}"), ""))]]
    y = MARGIN
    carry = 0.0
    for index, (text, bold, position) in enumerate(lines):
        gap = (lines[index + 1][2] - position - 24) * PT if index + 1 < len(lines) else 0
        if COVER_LINES[index][0] == "{{student_2}}" and not values.get("student_2"):
            carry += (24 * PT) + gap
            y += 0  # la línea vacía no ocupa altura propia; su hueco pasa al siguiente
            continue
        y += carry
        carry = 0.0
        pdf.set_xy(MARGIN, y)
        pdf.style(bold)
        pdf.multi_cell(0, LINE, pdf.text(text), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        y = pdf.get_y() + gap


def render_pdf(content: DeliveryDocument, values: dict[str, str], output: Path) -> str:
    """Escribe el PDF y devuelve la familia tipográfica usada."""
    family, files = find_serif_fonts()
    pdf = _Renderer(family, files)
    pdf.set_title(content.title)
    pdf.set_author("; ".join(value for value in (values.get("student_1"), values.get("student_2")) if value))
    pdf.set_subject(values.get("subject", ""))
    pdf.set_creator("moodle-homework-assignment")
    pdf.set_lang("es-EC")
    pdf.set_creation_date(datetime.now(timezone.utc))
    pdf.add_page()
    render_cover(pdf, {**values, "title": content.title})

    pdf.cover = False
    pdf.add_page()
    pdf.centered(content.title)
    tables = figures = 0
    for block in content.blocks:
        if block.type == "page_break":
            pdf.add_page()
        elif block.type == "heading":
            pdf.keep_room(LINE * 2)
            if block.level == 1:
                pdf.centered(block.text)
            else:
                pdf.set_x(pdf.l_margin)
                pdf.segments(" ".join(block.text.split()), bold=True, italic=block.level == 3)
                pdf.ln(LINE)
        elif block.type == "paragraph":
            for text in _paragraphs(block.text):
                pdf.paragraph(text)
        elif block.type == "quote":
            for text in _paragraphs(block.text):
                pdf.paragraph(text, indent=0, left=INDENT)
        elif block.type in ("bullets", "numbered"):
            for number, item in enumerate(block.items, start=1):
                pdf.keep_room(LINE)
                base = pdf.l_margin
                pdf.style()
                pdf.set_x(base + INDENT * 0.5)
                marker = "•" if block.type == "bullets" and pdf.unicode else "-" if block.type == "bullets" else f"{number}."
                pdf.cell(INDENT, LINE, marker)
                pdf.set_left_margin(base + INDENT * 1.5)
                pdf.set_x(base + INDENT * 1.5)
                pdf.segments(" ".join(item.split()))
                pdf.ln(LINE)
                pdf.set_left_margin(base)
        elif block.type == "code":
            pdf.set_font("Courier", "", 10)
            pdf.set_left_margin(MARGIN + 5)
            pdf.multi_cell(0, 10 * 1.2 * PT, block.text.encode("latin-1", "replace").decode("latin-1"),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_left_margin(MARGIN)
            pdf.ln(SINGLE)
        elif block.type == "table":
            tables += 1
            pdf.keep_room(LINE * 4)
            pdf.style(bold=True)
            pdf.cell(0, LINE, f"Tabla {tables}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.style(italic=True)
            pdf.multi_cell(0, LINE, pdf.text(pdf.plain(block.title)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.style()
            with pdf.table(borders_layout=TableBordersLayout.HORIZONTAL_LINES, line_height=SINGLE + 1,
                           text_align="LEFT", first_row_as_headings=True, padding=1) as table:
                for row in block.rows:
                    cells = table.row()
                    for value in row:
                        cells.cell(pdf.text(pdf.plain(value)))
            if block.note:
                pdf.set_x(pdf.l_margin)
                pdf.style(italic=True)
                pdf.write(LINE, "Nota. ")
                pdf.segments(block.note)
                pdf.ln(LINE)
        elif block.type == "figure":
            figures += 1
            with Image.open(block.path) as image:
                ratio = image.height / image.width
            width = (block.width_cm or 14) * 10
            height = width * ratio
            pdf.keep_room(LINE * 2 + height)
            pdf.style(bold=True)
            pdf.cell(0, LINE, f"Figura {figures}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.style(italic=True)
            pdf.multi_cell(0, LINE, pdf.text(pdf.plain(block.title)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.image(block.path, x=pdf.l_margin, w=width)
            if block.note:
                pdf.set_x(pdf.l_margin)
                pdf.style(italic=True)
                pdf.write(LINE, "Nota. ")
                pdf.segments(block.note)
                pdf.ln(LINE)

    if content.references:
        pdf.add_page()
        pdf.centered("Referencias")
        for reference in sorted(content.references, key=lambda value: re.sub(r"[*\[\]]", "", value).casefold()):
            pdf.paragraph(reference, indent=0, hanging=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output))
    return pdf.font_label
