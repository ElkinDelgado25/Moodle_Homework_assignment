"""Arranque común de las pruebas y generadores de DOCX y PDF reales, sin LibreOffice.

Todo módulo de prueba importa este archivo: así ninguna prueba lee ni escribe la
configuración, la caché o las credenciales reales del usuario que la ejecuta.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject

# Las pruebas nunca leen ni guardan la sesión real de Moodle del usuario.
os.environ["MOODLE_SESSION_CACHE"] = "false"

# Carpeta personal temporal para toda la ejecución: las rutas de configuración y caché
# (XDG en Linux, APPDATA/LOCALAPPDATA en Windows, ~/Library en macOS) apuntan dentro de ella.
def _playwright_browsers() -> str:
    """Carpeta real de los navegadores de Playwright, que se busca a partir de HOME."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return os.environ["PLAYWRIGHT_BROWSERS_PATH"]
    if sys.platform == "win32":
        return str(Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "ms-playwright")
    if sys.platform == "darwin":
        return str(Path.home() / "Library/Caches/ms-playwright")
    return str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright")


os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _playwright_browsers()
TEST_HOME = Path(tempfile.mkdtemp(prefix="moodle-tests-home-")).resolve()
atexit.register(shutil.rmtree, TEST_HOME, ignore_errors=True)
os.environ.update({
    "HOME": str(TEST_HOME),
    "USERPROFILE": str(TEST_HOME),
    "XDG_CONFIG_HOME": str(TEST_HOME / ".config"),
    "XDG_CACHE_HOME": str(TEST_HOME / ".cache"),
    "APPDATA": str(TEST_HOME / "AppData" / "Roaming"),
    "LOCALAPPDATA": str(TEST_HOME / "AppData" / "Local"),
})
# Las pruebas que vacían os.environ caen en Path.home(), que sin HOME consultaría la
# base de usuarios del sistema y devolvería la carpeta real.
Path.home = classmethod(lambda cls: cls(TEST_HOME))


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
