import asyncio
import json
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from pydantic import ValidationError
from pypdf import PdfReader

from moodle_tasks.document import (MissingCoverFields, build_delivery, build_docx, cover_values, export_pdf,
                                   export_with_libreoffice, find_soffice, safe_file_name)
from moodle_tasks.document_model import CoverFields, DeliveryDocument, parse_inline
from moodle_tasks.verification import check_delivery_pair, inspect_docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEMPLATE = Path(__file__).resolve().parents[1] / "src/moodle_tasks/assets/academic-cover.docx"
COVER = CoverFields(subject="Desarrollo Móvil", teacher="Ing. Ana & <Asoc>", degree="Software",
                    class_group="Quinto \"A\"", year=2026)
PROFILE = {"student_1": "Elkin Delgado"}


def make_png(path: Path, size=(40, 20)) -> Path:
    from PIL import Image
    Image.new("RGB", size, (200, 30, 30)).save(path, "PNG")
    return path


def sample(**overrides) -> DeliveryDocument:
    data = {
        "title": "Informe de la práctica 3",
        "blocks": [
            {"type": "heading", "level": 1, "text": "Introducción"},
            {"type": "paragraph", "text": "Texto con **negrita**, *cursiva* y https://github.com/usuario/proyecto.\n\nSegundo párrafo."},
            {"type": "numbered", "items": ["Uno", "Dos"]},
            {"type": "numbered", "items": ["Otra lista"]},
            {"type": "table", "title": "Resultados", "rows": [["Prueba", "Estado"], ["A", "OK"]]},
        ],
        "references": ["Zeta, A. (2020). *Libro*.", "Alfa, B. (2021). *Otro*. https://doi.org/10.1000/x"],
    }
    data.update(overrides)
    return DeliveryDocument.model_validate(data)


def document_xml(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def all_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        parts = [name for name in archive.namelist() if re.fullmatch(r"word/(document|header\d+)\.xml", name)]
        return "\n".join("".join(node.text or "" for node in ET.fromstring(archive.read(name)).iter(W + "t")) for name in parts)


class TemplateTests(unittest.TestCase):
    def test_template_has_explicit_fonts_language_and_styles(self):
        with zipfile.ZipFile(TEMPLATE) as archive:
            styles = archive.read("word/styles.xml").decode()
            settings = archive.read("word/settings.xml").decode()
            names = archive.namelist()
        self.assertNotIn("Theme=", styles)
        self.assertNotIn("cstheme", styles)
        self.assertIn('w:lang w:val="es-EC"', styles)
        self.assertIn('w:styleId="Hyperlink"', styles)
        self.assertIn('w:styleId="SourceCode"', styles)
        self.assertRegex(settings, r'compatibilityMode"[^>]*w:val="15"')
        self.assertNotIn("word/stylesWithEffects.xml", names)
        self.assertNotIn("docProps/thumbnail.jpeg", names)
        root = ET.fromstring(styles)
        for style_id in ("Normal", "Title", "Heading1", "Heading2", "Heading3", "ListBullet", "ListNumber"):
            style = root.find(f"{W}style[@{W}styleId='{style_id}']")
            fonts = style.find(f"{W}rPr/{W}rFonts")
            for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                self.assertEqual(fonts.get(W + attribute), "Times New Roman", (style_id, attribute))
        heading3 = root.find(f"{W}style[@{W}styleId='Heading3']/{W}rPr")
        self.assertIsNotNone(heading3.find(W + "i"))

    def test_template_metadata_is_neutral(self):
        with zipfile.ZipFile(TEMPLATE) as archive:
            core = archive.read("docProps/core.xml").decode()
        self.assertNotIn("python-docx", core)
        self.assertNotIn("ULEAM", core)
        self.assertIn("es-EC", core)

    def test_first_page_header_does_not_end_with_a_table(self):
        with zipfile.ZipFile(TEMPLATE) as archive:
            for name in archive.namelist():
                if re.fullmatch(r"word/header\d+\.xml", name):
                    root = ET.fromstring(archive.read(name))
                    self.assertEqual(list(root)[-1].tag, W + "p", name)

    def test_cover_has_title_and_all_fields(self):
        text = all_text(TEMPLATE)
        for field in ("title", "subject", "teacher", "student_1", "student_2", "degree", "class_group", "year"):
            self.assertIn("{{" + field + "}}", text)


class ModelTests(unittest.TestCase):
    def test_inline_markup(self):
        segments = parse_inline("Hola **mundo** *cursiva* [sitio](https://example.com) y https://a.test/x).")
        self.assertEqual([s["text"] for s in segments], ["Hola ", "mundo", " ", "cursiva", " ", "sitio", " y ", "https://a.test/x", ")."])
        self.assertTrue(segments[1]["bold"])
        self.assertTrue(segments[3]["italic"])
        self.assertEqual(segments[5]["link"], "https://example.com")
        self.assertEqual(segments[7]["link"], "https://a.test/x")
        self.assertEqual(parse_inline(r"precio \*no\* cursiva")[0]["text"], "precio *no* cursiva")
        self.assertEqual(parse_inline("2 * 3 * 4")[0]["text"], "2 * 3 * 4")

    def test_github_link_must_show_exact_url(self):
        with self.assertRaises(ValidationError) as caught:
            sample(blocks=[{"type": "paragraph", "text": "[mi repo](https://github.com/u/p)"}])
        self.assertIn("URL exacta", str(caught.exception))
        sample(blocks=[{"type": "paragraph", "text": "[https://github.com/u/p](https://github.com/u/p)"}])

    def test_unsafe_links_are_rejected(self):
        for text in ("[x](javascript:alert(1))", "[x](file:///etc/passwd)", "[x](https://user:pw@a.test)",
                     "[x](https://a.test/\u200bpath)", "[x](ftp://a.test)"):
            with self.assertRaises(ValidationError, msg=text):
                sample(blocks=[{"type": "paragraph", "text": text}])

    def test_block_requirements_and_limits(self):
        invalid = [
            {"type": "heading", "text": "Sin nivel"},
            {"type": "heading", "level": 4, "text": "Nivel 4"},
            {"type": "paragraph"},
            {"type": "table", "title": "T", "rows": [["a", "b"], ["c"]]},
            {"type": "table", "title": "T", "rows": [["solo encabezado"]]},
            {"type": "figure", "title": "F"},
            {"type": "bullets", "items": []},
            {"type": "desconocido", "text": "x"},
            {"type": "paragraph", "text": "x", "extra": 1},
        ]
        for block in invalid:
            with self.assertRaises(ValidationError, msg=block):
                sample(blocks=[block])
        with self.assertRaises(ValidationError):
            sample(blocks=[])
        with self.assertRaises(ValidationError):
            sample(title="   ")
        with self.assertRaises(ValidationError):
            sample(blocks=[{"type": "paragraph", "text": "x" * 20_000}] * 21)

    def test_control_characters_and_bidi_are_removed(self):
        document = sample(title="Título\x00\x0b con \u202eoculto", blocks=[{"type": "paragraph", "text": "a\x01b\x7fc"}])
        self.assertEqual(document.title, "Título con oculto")
        self.assertEqual(document.blocks[0].text, "abc")
        with self.assertRaises(ValidationError):
            sample(blocks=[{"type": "paragraph", "text": "sustituto \ud800 suelto"}])

    def test_cover_fields_normalization(self):
        cover = CoverFields(year=2026, teacher="  Ing.\n Ana  ", student_2="   ")
        self.assertEqual(cover.year, "2026")
        self.assertEqual(cover.teacher, "Ing. Ana")
        self.assertIsNone(cover.student_2)
        with self.assertRaises(ValidationError):
            CoverFields(year=True)
        with self.assertRaises(ValidationError):
            CoverFields(teacher="x" * 201)
        with self.assertRaises(ValidationError):
            CoverFields(career="no existe")

    def test_missing_cover_fields_are_reported_and_profile_fills_student(self):
        with self.assertRaises(MissingCoverFields) as caught:
            cover_values(CoverFields(subject="Materia"), {})
        self.assertEqual(caught.exception.fields, ["teacher", "student_1", "degree", "class_group", "year"])
        values = cover_values(COVER, PROFILE)
        self.assertEqual(values["student_1"], "Elkin Delgado")
        self.assertEqual(values["student_2"], "")

    def test_template_tokens_cannot_be_injected(self):
        with self.assertRaises(ValidationError):
            CoverFields(teacher="{{year}}")
        with self.assertRaises(ValidationError):
            sample(title="Informe {{ teacher }}")
        self.assertEqual(sample(blocks=[{"type": "code", "text": "<p>{{ nombre }}</p>"}]).blocks[0].text, "<p>{{ nombre }}</p>")

    def test_safe_file_name_drops_invisible_characters(self):
        self.assertEqual(safe_file_name("Infor\u200bme\ufeff final\u202e"), "Infor me final")

    def test_safe_file_name(self):
        self.assertEqual(safe_file_name('Informe: "final"/v2?.docx'), "Informe final v2")
        self.assertEqual(safe_file_name("CON"), "_CON")
        self.assertEqual(safe_file_name(" ... "), "Entrega")
        self.assertLessEqual(len(safe_file_name("á" * 500).encode()), 150)
        self.assertEqual(safe_file_name("Práctica Nº 3 😀"), "Práctica Nº 3 😀")


class DocxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def build(self, content=None, cover=COVER):
        path = self.root / "entrega.docx"
        build_docx(content or sample(), cover_values(cover, PROFILE), path)
        return path

    def test_cover_is_filled_and_xml_special_characters_are_escaped(self):
        path = self.build()
        text = all_text(path)
        self.assertNotIn("{{", text)
        for value in ("Informe de la práctica 3", "Desarrollo Móvil", "Ing. Ana & <Asoc>", "Elkin Delgado",
                      "Quinto \"A\"", "2026", "Software"):
            self.assertIn(value, text)
        self.assertEqual(inspect_docx(path)["placeholders"], [])

    def test_empty_second_student_paragraph_is_removed(self):
        path = self.build()
        paragraphs = ["".join(n.text or "" for n in p.iter(W + "t")) for p in document_xml(path).iter(W + "p")]
        index = paragraphs.index("Elkin Delgado")
        self.assertEqual(paragraphs[index + 1], "Carrera:")
        with_partner = CoverFields(**{**COVER.model_dump(), "student_2": "María López"})
        paragraphs = ["".join(n.text or "" for n in p.iter(W + "t")) for p in document_xml(self.build(cover=with_partner)).iter(W + "p")]
        self.assertEqual(paragraphs[paragraphs.index("Elkin Delgado") + 1], "María López")

    def test_body_starts_on_page_two_with_title(self):
        root = document_xml(self.build())
        titles = [p for p in root.iter(W + "p") if p.find(f"{W}pPr/{W}pStyle") is not None
                  and p.find(f"{W}pPr/{W}pStyle").get(W + "val") == "Title"]
        self.assertEqual(len(titles), 1)
        self.assertIsNotNone(titles[0].find(f"{W}pPr/{W}pageBreakBefore"))

    def test_hyperlinks_are_external_relationships_with_style(self):
        path = self.build()
        self.assertEqual(inspect_docx(path)["hyperlinks"], ["https://doi.org/10.1000/x", "https://github.com/usuario/proyecto"])
        root = document_xml(path)
        link = root.find(f".//{W}hyperlink")
        self.assertEqual(link.find(f"{W}r/{W}rPr/{W}rStyle").get(W + "val"), "Hyperlink")

    def test_numbered_lists_restart(self):
        root = document_xml(self.build())
        ids = [p.find(f"{W}pPr/{W}numPr/{W}numId").get(W + "val") for p in root.iter(W + "p")
               if p.find(f"{W}pPr/{W}numPr/{W}numId") is not None]
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[1], ids[2])

    def test_references_sorted_on_new_page_with_hanging_indent(self):
        root = document_xml(self.build())
        paragraphs = list(root.iter(W + "p"))
        texts = ["".join(n.text or "" for n in p.iter(W + "t")) for p in paragraphs]
        start = texts.index("Referencias")
        self.assertIsNotNone(paragraphs[start].find(f"{W}pPr/{W}pageBreakBefore"))
        self.assertTrue(texts[start + 1].startswith("Alfa"))
        self.assertTrue(texts[start + 2].startswith("Zeta"))
        indent = paragraphs[start + 1].find(f"{W}pPr/{W}ind")
        self.assertEqual(indent.get(W + "hanging"), "720")

    def test_no_references_means_no_heading(self):
        text = all_text(self.build(sample(references=[])))
        self.assertNotIn("Referencias", text)

    def test_emoji_long_text_and_code(self):
        long_text = "palabra " * 1250
        content = sample(blocks=[{"type": "paragraph", "text": "Emoji 😀 y acentos ñ"},
                                 {"type": "paragraph", "text": long_text},
                                 {"type": "code", "text": "a = 1\n  b = 2"}])
        text = all_text(self.build(content))
        self.assertIn("😀", text)
        self.assertIn("  b = 2", text)

    def test_figures_validate_the_image(self):
        image = make_png(self.root / "captura.png")
        path = self.build(sample(blocks=[{"type": "figure", "title": "Pantalla", "path": str(image), "width_cm": 5}]))
        with zipfile.ZipFile(path) as archive:
            self.assertTrue(any(name.startswith("word/media/") for name in archive.namelist()))
        fake = self.root / "falsa.png"
        fake.write_text("no soy imagen")
        with self.assertRaises(ValueError):
            self.build(sample(blocks=[{"type": "figure", "title": "F", "path": str(fake)}]))
        with self.assertRaises(ValueError):
            self.build(sample(blocks=[{"type": "figure", "title": "F", "path": "relativa.png"}]))


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        patcher = patch("moodle_tasks.document.find_soffice", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_builtin_pdf_matches_the_document(self):
        result = build_delivery(sample(), cover_values(COVER, PROFILE), self.root, "Informe: práctica 3")
        self.assertEqual(result["engine"], "builtin")
        self.assertEqual(result["docx"].name, "Informe práctica 3.docx")
        self.assertEqual(result["docx"].stem, result["pdf"].stem)
        checks = check_delivery_pair(result["docx"], result["pdf"])
        self.assertTrue(checks["ok"], checks)
        self.assertGreaterEqual(checks["pages"], 3)
        self.assertIn("https://github.com/usuario/proyecto", checks["hyperlinks"])
        reader = PdfReader(str(result["pdf"]))
        self.assertEqual(reader.metadata.title, "Informe de la práctica 3")
        cover_text = reader.pages[0].extract_text()
        self.assertIn("Ing. Ana & <Asoc>", cover_text)
        self.assertNotIn("{{", "".join(page.extract_text() for page in reader.pages))
        self.assertEqual(checks["warnings"], [] if "Times" in "".join(checks["pdf_fonts"]) else checks["warnings"])

    def test_code_with_template_syntax_passes_verification(self):
        content = sample(blocks=[{"type": "code", "text": "<template>{{ titulo }}</template>"},
                                 {"type": "paragraph", "text": "Vue usa {{ variable }} en las plantillas."}])
        result = build_delivery(content, cover_values(COVER, PROFILE), self.root, "vue")
        self.assertTrue(check_delivery_pair(result["docx"], result["pdf"])["ok"])

    def test_builtin_pdf_without_any_truetype_font_falls_back(self):
        with patch("moodle_tasks.pdf_render.find_serif_fonts", return_value=("Times", None)):
            result = build_delivery(sample(blocks=[{"type": "paragraph", "text": "Emoji 😀 ñ"}]),
                                    cover_values(COVER, PROFILE), self.root, "fallback")
        self.assertTrue(result["pdf"].is_file())
        self.assertTrue(any("Times New Roman no está instalada" in warning for warning in result["warnings"]))

    def test_libreoffice_is_preferred_when_present_and_failures_fall_back(self):
        def fake_export(command, docx, outdir, timeout=120):
            raise RuntimeError("LibreOffice no generó el PDF.")

        with patch("moodle_tasks.document.find_soffice", return_value=["/usr/bin/soffice"]), \
                patch("moodle_tasks.document.export_with_libreoffice", side_effect=fake_export):
            result = build_delivery(sample(), cover_values(COVER, PROFILE), self.root, "lo")
        self.assertEqual(result["engine"], "builtin")
        self.assertTrue(any("LibreOffice falló" in warning for warning in result["warnings"]))
        with patch("moodle_tasks.document.find_soffice", return_value=None):
            with self.assertRaises(RuntimeError):
                export_pdf(sample(), cover_values(COVER, PROFILE), self.root / "x.docx", engine="libreoffice")

    def test_libreoffice_argv_keeps_the_path_as_one_argument(self):
        docx = self.root / "carpeta con espacios" / "entrega final.docx"
        docx.parent.mkdir()
        docx.write_bytes(b"PK")
        calls = []

        class FakeProcess:
            def __init__(self, argv, **kwargs):
                calls.append((argv, kwargs))
                (docx.parent / "entrega final.pdf").write_bytes(b"%PDF-1.7")

            def communicate(self, timeout=None):
                return b"", b""

        with patch("moodle_tasks.document.subprocess.Popen", FakeProcess), \
                patch("moodle_tasks.document.user_cache_dir", return_value=self.root / "cache"):
            result = export_with_libreoffice(["soffice"], docx, docx.parent)
        argv, kwargs = calls[0]
        self.assertEqual(argv[-1], str(docx))
        self.assertTrue(argv[1].startswith("-env:UserInstallation=file://"))
        self.assertIn("--headless", argv)
        self.assertEqual(kwargs["stdin"], -3)
        self.assertEqual(result, docx.parent / "entrega final.pdf")

    def test_libreoffice_timeout_and_missing_output(self):
        import subprocess

        class Hanging:
            killed = False

            def __init__(self, argv, **kwargs):
                pass

            def communicate(self, timeout=None):
                if timeout is not None and not Hanging.killed:
                    raise subprocess.TimeoutExpired("soffice", timeout)
                return b"", b""

            def kill(self):
                Hanging.killed = True

        docx = self.root / "a.docx"
        docx.write_bytes(b"PK")
        with patch("moodle_tasks.document.subprocess.Popen", Hanging), \
                patch("moodle_tasks.document.user_cache_dir", return_value=self.root / "cache"):
            with self.assertRaises(RuntimeError):
                export_with_libreoffice(["soffice"], docx, self.root, timeout=1)
        self.assertTrue(Hanging.killed)

    def test_soffice_discovery(self):
        patch.stopall()
        with patch.dict(os.environ, {"MOODLE_SOFFICE": "/no/existe"}):
            self.assertIsNone(find_soffice())
        fake = self.root / "soffice"
        fake.write_text("")
        with patch.dict(os.environ, {"MOODLE_SOFFICE": str(fake)}):
            self.assertEqual(find_soffice(), [str(fake)])
        environment = {key: value for key, value in os.environ.items() if key != "MOODLE_SOFFICE"}
        with patch.dict(os.environ, environment, clear=True), \
                patch("moodle_tasks.document.shutil.which", side_effect=lambda name: "/bin/lowriter" if name == "lowriter" else None):
            self.assertEqual(find_soffice(), ["/bin/lowriter"])
        with patch.dict(os.environ, environment, clear=True), \
                patch("moodle_tasks.document.shutil.which", return_value=None), \
                patch("moodle_tasks.document.sys.platform", "linux"), \
                patch("moodle_tasks.document.Path.is_file", return_value=False):
            self.assertIsNone(find_soffice())


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "config"
        self.config.mkdir()
        (self.config / "document_profile.json").write_text(json.dumps({"student_1": "Elkin Delgado", "courses": ["Desarrollo Móvil"]}))
        for target, value in (("moodle_tasks.server.user_config_dir", self.config),
                              ("moodle_tasks.paths.user_config_dir", self.config),
                              ("moodle_tasks.paths.user_cache_dir", self.root / "cache"),
                              ("moodle_tasks.delivery.user_cache_dir", self.root / "cache"),
                              ("moodle_tasks.document.find_soffice", None)):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.opened = []
        patcher = patch("moodle_tasks.server.open_file", side_effect=lambda path: self.opened.append(path) or True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, arguments):
        from mcp import Client
        from moodle_tasks.server import create_server

        async def run():
            async with Client(create_server()) as client:
                return await client.call_tool("build_delivery_document", arguments)
        return asyncio.run(run())

    def test_tool_builds_verifies_and_never_overwrites(self):
        destination = self.root / "Entregas"
        arguments = {"document": sample().model_dump(exclude_none=True),
                     "cover": {"subject": "Desarrollo Móvil", "teacher": "Ing. Ana", "degree": "Software",
                               "class_group": "5A", "year": "2026"},
                     "destination_directory": str(destination)}
        first = self.call(arguments)
        self.assertFalse(first.is_error, first)
        data = first.structured_content
        self.assertEqual(data["status"], "ok")
        self.assertEqual(Path(data["docx_path"]).name, "Informe de la práctica 3.docx")
        self.assertEqual(data["pdf_engine"], "builtin")
        self.assertEqual(self.opened, [Path(data["pdf_path"])])
        second = self.call(arguments).structured_content
        self.assertEqual(Path(second["docx_path"]).name, "Informe de la práctica 3 (1).docx")
        self.assertEqual(sorted(p.name for p in destination.iterdir()),
                         ["Informe de la práctica 3 (1).docx", "Informe de la práctica 3 (1).pdf",
                          "Informe de la práctica 3.docx", "Informe de la práctica 3.pdf"])
        self.assertEqual(list((self.root / "cache" / "workspaces").iterdir()), [])

    def test_missing_cover_fields_write_nothing(self):
        destination = self.root / "Entregas"
        result = self.call({"document": sample().model_dump(exclude_none=True), "cover": {"subject": "X"},
                            "destination_directory": str(destination)})
        data = result.structured_content
        self.assertEqual(data["status"], "missing_cover_fields")
        self.assertEqual(data["missing_cover_fields"], ["teacher", "degree", "class_group", "year"])
        self.assertFalse(destination.exists())

    def test_schema_rejects_unknown_fields_and_bad_destinations(self):
        cover = {"subject": "X", "teacher": "Y", "degree": "Z", "class_group": "W", "year": "2026"}
        bad = self.call({"document": {**sample().model_dump(exclude_none=True), "autor": "x"}, "cover": cover})
        self.assertTrue(bad.is_error)
        relative = self.call({"document": sample().model_dump(exclude_none=True), "cover": cover,
                              "destination_directory": "Entregas"})
        self.assertTrue(relative.is_error)
        protected = self.call({"document": sample().model_dump(exclude_none=True), "cover": cover,
                               "destination_directory": str(self.config)})
        self.assertTrue(protected.is_error)


@unittest.skipUnless(find_soffice() or os.environ.get("MOODLE_REQUIRE_SOFFICE"), "LibreOffice no está instalado")
class RealLibreOfficeTests(unittest.TestCase):
    def test_real_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            result = build_delivery(sample(), cover_values(COVER, PROFILE), Path(directory), "real", engine="libreoffice")
            checks = check_delivery_pair(result["docx"], result["pdf"])
            self.assertTrue(checks["ok"], checks)
            self.assertGreaterEqual(checks["pages"], 3)


if __name__ == "__main__":
    unittest.main()
