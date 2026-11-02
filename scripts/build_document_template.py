"""Reconstruye la portada editable ULEAM con estilos APA 7 compatibles con Word, WPS y LibreOffice."""

from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ASSETS = Path(__file__).resolve().parents[1] / "src/moodle_tasks/assets"
FONT = "Times New Roman"
LANGUAGE = "es-EC"
THEME_ATTRIBUTES = ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme")


def explicit_fonts(r_pr, font: str = FONT) -> None:
    """Fuentes explícitas para los cuatro rangos y sin atributos de tema, que Word y WPS priorizan."""
    fonts = r_pr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        r_pr.insert(0, fonts)
    for attribute in THEME_ATTRIBUTES:
        if fonts.get(qn(attribute)) is not None:
            del fonts.attrib[qn(attribute)]
    for attribute in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(attribute), font)


def language(r_pr) -> None:
    lang = r_pr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        r_pr.append(lang)
    for attribute in ("w:val", "w:eastAsia", "w:bidi"):
        lang.set(qn(attribute), LANGUAGE)


def style_r_pr(style):
    return style.element.get_or_add_rPr()


def configure_styles(document) -> None:
    defaults = document.styles.element.find(qn("w:docDefaults"))
    r_pr = defaults.find(qn("w:rPrDefault")).find(qn("w:rPr"))
    explicit_fonts(r_pr)
    language(r_pr)
    size = r_pr.find(qn("w:sz"))
    if size is not None:
        size.set(qn("w:val"), "24")

    normal = document.styles["Normal"]
    normal.font.size = Pt(12)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    explicit_fonts(style_r_pr(normal))
    language(style_r_pr(normal))
    paragraph = normal.paragraph_format
    paragraph.space_after = paragraph.space_before = Pt(0)
    paragraph.line_spacing = 2
    paragraph.first_line_indent = Cm(1.27)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.widow_control = True

    # Niveles APA 7: 1 centrado en negrita, 2 izquierda en negrita, 3 izquierda en negrita cursiva.
    for name, align, italic in (("Title", WD_ALIGN_PARAGRAPH.CENTER, False),
                                ("Heading 1", WD_ALIGN_PARAGRAPH.CENTER, False),
                                ("Heading 2", WD_ALIGN_PARAGRAPH.LEFT, False),
                                ("Heading 3", WD_ALIGN_PARAGRAPH.LEFT, True)):
        style = document.styles[name]
        style.font.size = Pt(12)
        style.font.bold = True
        style.font.italic = italic
        style.font.color.rgb = RGBColor(0, 0, 0)
        explicit_fonts(style_r_pr(style))
        for border in style.element.xpath(".//w:pBdr"):
            border.getparent().remove(border)
        for spacing in style.element.xpath("./w:rPr/w:spacing | ./w:rPr/w:kern"):
            spacing.getparent().remove(spacing)
        format_ = style.paragraph_format
        format_.line_spacing = 2
        format_.space_before = format_.space_after = Pt(0)
        format_.first_line_indent = Cm(0)
        format_.alignment = align
        format_.keep_with_next = True

    for name in ("List Bullet", "List Number"):
        style = document.styles[name]
        explicit_fonts(style_r_pr(style))
        style.paragraph_format.line_spacing = 2

    hyperlink = document.styles.add_style("Hyperlink", WD_STYLE_TYPE.CHARACTER)
    hyperlink.font.color.rgb = RGBColor(0x05, 0x63, 0xC1)
    hyperlink.font.underline = True
    hyperlink.hidden = False
    hyperlink.unhide_when_used = True

    # Ningún estilo (Heading 4-9, estilos *Char vinculados...) conserva fuentes del tema.
    for fonts in document.styles.element.iter(qn("w:rFonts")):
        if any(fonts.get(qn(attribute)) is not None for attribute in THEME_ATTRIBUTES):
            explicit_fonts(fonts.getparent())

    code = document.styles.add_style("Source Code", WD_STYLE_TYPE.PARAGRAPH)
    code.base_style = normal
    code.font.size = Pt(10)
    explicit_fonts(style_r_pr(code), "Courier New")
    code.paragraph_format.line_spacing = 1
    code.paragraph_format.first_line_indent = Cm(0)
    code.paragraph_format.left_indent = Cm(0.5)


def page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph.paragraph_format.first_line_indent = Cm(0)
    paragraph.paragraph_format.line_spacing = 1
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    explicit_fonts(properties)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "000000")
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "24")
    properties.extend([color, size])
    run.append(properties)
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


def floating_logo(paragraph, image: Path, *, width, left, top) -> None:
    """Imagen anclada a la página, sin ajuste de texto, con identificadores válidos (no 0) para WPS."""
    inline = paragraph.add_run().add_picture(str(image), width=width)._inline
    extent = inline.find(qn("wp:extent"))
    anchor = OxmlElement("wp:anchor")
    for name, value in (("distT", "0"), ("distB", "0"), ("distL", "0"), ("distR", "0"), ("simplePos", "0"),
                        ("relativeHeight", "251659264"), ("behindDoc", "0"), ("locked", "0"),
                        ("layoutInCell", "1"), ("allowOverlap", "1")):
        anchor.set(name, value)
    simple = OxmlElement("wp:simplePos")
    simple.set("x", "0")
    simple.set("y", "0")
    anchor.append(simple)
    for axis, relative, offset in (("wp:positionH", "page", left), ("wp:positionV", "page", top)):
        position = OxmlElement(axis)
        position.set("relativeFrom", relative)
        value = OxmlElement("wp:posOffset")
        value.text = str(int(offset))
        position.append(value)
        anchor.append(position)
    anchor.append(extent)
    effect = OxmlElement("wp:effectExtent")
    for side in ("l", "t", "r", "b"):
        effect.set(side, "0")
    anchor.append(effect)
    anchor.append(OxmlElement("wp:wrapNone"))
    doc_pr = inline.find(qn("wp:docPr"))
    doc_pr.set("id", "1001")
    doc_pr.set("name", "Logo ULEAM")
    doc_pr.set("descr", "Logo de la Universidad Laica Eloy Alfaro de Manabí")
    anchor.append(doc_pr)
    anchor.append(inline.find(qn("wp:cNvGraphicFramePr")))
    graphic = inline.find(qn("a:graphic"))
    graphic.find(".//" + qn("pic:cNvPr")).set("id", "1001")
    anchor.append(graphic)
    inline.getparent().replace(inline, anchor)


def drop_part(document, suffix: str) -> None:
    """Quita partes heredadas de la plantilla base de python-docx (efectos de Word 2010, miniatura)."""
    for owner in (document.part, document.part.package):
        for key, relation in list(owner.rels.items()):
            if not relation.is_external and str(relation.target_part.partname).endswith(suffix):
                del owner.rels[key]


def modern_compatibility(document) -> None:
    settings = document.settings.element
    for setting in settings.xpath(".//w:compatSetting[@w:name='compatibilityMode']"):
        setting.set(qn("w:val"), "15")


def build_cover(output: Path) -> None:
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21.59), Cm(27.94)
    section.left_margin = section.right_margin = Cm(2.54)
    section.top_margin = section.bottom_margin = Cm(2.54)
    section.header_distance = Cm(1.27)
    section.different_first_page_header_footer = True
    configure_styles(document)

    page_number(section.header.paragraphs[0])
    # Primera página: número a la derecha y logo flotante anclado a la página (x 2,54 cm, y 1,27 cm).
    # Sin tabla: así el encabezado no supera el margen superior ni desplaza la portada en Word o WPS.
    first_paragraph = section.first_page_header.paragraphs[0]
    page_number(first_paragraph)
    floating_logo(first_paragraph, ASSETS / "uleam-logo.png", width=Cm(3.75), left=Cm(2.54), top=Cm(1.27))

    lines = [
        ("Universidad Laica “Eloy Alfaro de Manabí”", True, 72),
        ("{{title}}", True, 120),
        ("Materia:", True, 168),
        ("{{subject}}", False, 192),
        ("Docente:", True, 216),
        ("{{teacher}}", False, 240),
        ("Estudiantes:", True, 288),
        ("{{student_1}}", False, 312),
        ("{{student_2}}", False, 336),
        ("Carrera:", True, 384),
        ("{{degree}}", False, 408),
        ("Curso:", True, 456),
        ("{{class_group}}", False, 480),
        ("Año:", True, 504),
        ("{{year}}", False, 528),
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

    drop_part(document, "stylesWithEffects.xml")
    drop_part(document, "thumbnail.jpeg")
    modern_compatibility(document)
    properties = document.core_properties
    properties.title = ""
    properties.subject = ""
    properties.author = ""
    properties.last_modified_by = ""
    properties.comments = ""
    properties.keywords = ""
    properties.revision = 1
    properties.created = properties.modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    properties.language = LANGUAGE
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)


if __name__ == "__main__":
    build_cover(ASSETS / "academic-cover.docx")
