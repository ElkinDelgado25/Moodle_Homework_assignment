"""Reconstruye la portada editable; requiere python-docx solo para desarrollo."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ASSETS = Path(__file__).resolve().parents[1] / "src/moodle_tasks/assets"


def build_cover(output: Path) -> None:
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21.59), Cm(27.94)
    section.left_margin = section.right_margin = Cm(2.54)
    section.top_margin = section.bottom_margin = Cm(2.54)
    section.header_distance = Cm(1.27)
    section.different_first_page_header_footer = True
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 2
    normal.paragraph_format.first_line_indent = Cm(1.27)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        style = document.styles[name]
        style.font.name = "Times New Roman"
        style.font.size = Pt(12)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.line_spacing = 2
        style.paragraph_format.space_before = style.paragraph_format.space_after = Pt(0)
        style.paragraph_format.first_line_indent = Cm(0)
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER if name in ("Title", "Heading 1") else WD_ALIGN_PARAGRAPH.LEFT
        for border in style._element.xpath(".//w:pBdr"):
            border.getparent().remove(border)

    def page_number(paragraph):
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.line_spacing = 1
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        run = OxmlElement("w:r")
        properties = OxmlElement("w:rPr")
        size = OxmlElement("w:sz")
        size.set(qn("w:val"), "24")
        color = OxmlElement("w:color")
        color.set(qn("w:val"), "000000")
        fonts = OxmlElement("w:rFonts")
        fonts.set(qn("w:ascii"), "Times New Roman")
        fonts.set(qn("w:hAnsi"), "Times New Roman")
        properties.extend([size, color, fonts])
        run.append(properties)
        text = OxmlElement("w:t")
        text.text = "1"
        run.append(text)
        field.append(run)
        paragraph._p.append(field)

    regular_header = section.header.paragraphs[0]
    page_number(regular_header)
    first_header = section.first_page_header
    first_header.paragraphs[0].paragraph_format.line_spacing = Pt(1)
    table = first_header.add_table(rows=1, cols=2, width=Cm(16.51))
    table.autofit = False
    indent = OxmlElement("w:tblInd")
    indent.set(qn("w:w"), "0")
    indent.set(qn("w:type"), "dxa")
    table._tbl.tblPr.append(indent)
    for cell in table.rows[0].cells:
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        cell.paragraphs[0].paragraph_format.first_line_indent = Cm(0)
        cell.paragraphs[0].paragraph_format.line_spacing = 1
    table.cell(0, 0).paragraphs[0].add_run().add_picture(str(ASSETS / "uleam-logo.png"), width=Cm(3.75))
    page_number(table.cell(0, 1).paragraphs[0])

    lines = [
        ("Universidad Laica “Eloy Alfaro de Manabí”", True, 72),
        ("Materia:", True, 120),
        ("{{subject}}", False, 144),
        ("Docente:", True, 168),
        ("{{teacher}}", True, 192),
        ("Estudiantes:", True, 240),
        ("{{student_1}}", False, 264),
        ("{{student_2}}", False, 288),
        ("Carrera:", True, 336),
        ("{{degree}}", False, 360),
        ("Curso:", True, 408),
        ("{{class_group}}", False, 432),
        ("Año:", True, 456),
        ("{{year}}", False, 480),
    ]
    for index, (text, bold, position) in enumerate(lines):
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.line_spacing = 2
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.keep_with_next = False
        if index + 1 < len(lines):
            paragraph.paragraph_format.space_after = Pt(lines[index + 1][2] - position - 24)
        paragraph.add_run(text).bold = bold
    document.core_properties.title = "Plantilla de portada académica ULEAM"
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)


if __name__ == "__main__":
    build_cover(ASSETS / "academic-cover.docx")
