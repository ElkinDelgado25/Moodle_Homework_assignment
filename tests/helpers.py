"""Generadores de DOCX y PDF reales para las pruebas, sin LibreOffice."""

from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject


def make_docx(path: Path, text: str = "Desarrollo de la práctica.", link: str | None = None) -> Path:
    document = Document()
    paragraph = document.add_paragraph(text)
    if link:
        relation = document.part.relate_to(link, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), relation)
        run = OxmlElement("w:r")
        node = OxmlElement("w:t")
        node.text = link
        run.append(node)
        hyperlink.append(run)
        paragraph._p.append(hyperlink)
    document.save(path)
    return path


def make_pdf(path: Path, pages: int = 2, link: str | None = None) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if link:
        annotation = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): ArrayObject([FloatObject(72), FloatObject(700), FloatObject(300), FloatObject(720)]),
            NameObject("/A"): DictionaryObject({NameObject("/S"): NameObject("/URI"),
                                                NameObject("/URI"): TextStringObject(link)}),
        })
        writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    with path.open("wb") as output:
        writer.write(output)
    return path
