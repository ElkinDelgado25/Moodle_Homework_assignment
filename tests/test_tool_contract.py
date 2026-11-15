"""Contrato entre el servidor y el agente: datos limpios, errores con código y reintentos baratos."""

import asyncio
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from docx import Document
from mcp import Client
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

import helpers  # noqa: F401 - aísla las pruebas de la configuración real
from moodle_tasks import linked_content
from moodle_tasks.document import MissingCoverFields, cover_values
from moodle_tasks.document_model import CoverFields
from moodle_tasks.downloads import download_attachment
from moodle_tasks.errors import MoodleHTTPError
from moodle_tasks.extract import extract_text
from moodle_tasks.main import Assignment, Config, course_name, read_assignment
from moodle_tasks.profile import load_profile, remember_teacher, teacher_for
from moodle_tasks.server import create_server, slim_schema

SETTINGS = Config("https://moodle.test", "test", "test")
TASK_URL = "https://moodle.test/mod/assign/view.php?id=9"

# Estructura de una tarea real de Moodle 4: descripción con árbol de anexos, tabla de estado con el formulario
# de comentarios y rúbrica con sus niveles.
ASSIGNMENT_PAGE = """
<nav class="breadcrumb"><a href="/course/view.php?id=4">A -- SEGURIDAD--1208690--20262-1</a></nav>
<section id="region-main"><h1>U3-A3: Pipeline</h1>
<div class="activity-dates"><div><strong>Apertura:</strong> lunes, 9 de noviembre de 2026, 09:00</div>
  <div><strong>Cierre:</strong> jueves, 12 de noviembre de 2026, 09:00</div></div>
<div class="activity-description" id="intro"><div class="box generalbox"><div class="no-overflow">
  <p>Objetivo: configurar un flujo de CI.</p><img src="/pluginfile.php/7/intro/esquema.png" alt="Esquema">
  <img class="icon" src="/theme/icon.png"></div>
  <div id="assign_files_tree1"><ul><li><div><div class="fileuploadsubmission"><img class="icon" src="/i.png">
    <a href="/pluginfile.php/7/mod_assign/introattachment/0/Gu%C3%ADa.docx?forcedownload=1">Guía.docx</a></div>
    <div class="fileuploadsubmissiontime">26 de octubre de 2026, 09:43</div></div></li></ul></div></div></div>
<div class="submissionstatustable"><h3>Estado de la entrega</h3><table class="generaltable"><tbody>
  <tr><th>Grupo</th><td>Grupo 8</td></tr>
  <tr><th>Estado de la entrega</th><td>No se ha enviado nada en esta tarea</td></tr>
  <tr><th>Estado de la calificación</th><td>Sin calificar</td></tr>
  <tr><th>Comentarios de la entrega</th><td><div class="commentscontainer"><span>___picture___</span>
    <textarea></textarea><a>Guardar comentario</a></div></td></tr></tbody></table>
  <h4>Criterios de calificación</h4><div class="gradingform_rubric-description"><p>Rúbrica U3-A3</p></div>
  <div class="gradingform_rubric"><table class="criteria"><tbody><tr class="criterion">
    <td class="description">Configuración del YAML</td><td class="levels"><table><tbody><tr>
      <td class="level"><div class="definition">No se presenta.</div><div class="score"><span class="scorevalue">0</span> puntos</div></td>
      <td class="level"><div class="definition">Funciona completo.</div><div class="score"><span class="scorevalue">3</span> puntos</div></td>
    </tr></tbody></table></td></tr></tbody></table></div></div></section>"""


@contextmanager
def fake_browser():
    browser, page = MagicMock(name="browser"), MagicMock(name="page")
    with patch("moodle_tasks.server.moodle_page") as session:
        session.return_value.__enter__.return_value = (browser, page)
        yield session


def text_of(result) -> str:
    return " ".join(block.text for block in result.content if block.type == "text")


def document() -> dict:
    return {"title": "Informe", "blocks": [{"type": "paragraph", "text": "Desarrollo de la práctica."}]}


class AssignmentPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_status_rubric_group_and_description_are_read_as_separate_fields(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.route("**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=ASSIGNMENT_PAGE))
        task = read_assignment(page, TASK_URL)
        # El estado es la celda de la tabla, no el volcado de la rúbrica y los comentarios.
        self.assertEqual(task.status, "No se ha enviado nada en esta tarea")
        self.assertIs(task.submitted, False)
        self.assertEqual(task.group, "Grupo 8")
        self.assertEqual(task.grading_status, "Sin calificar")
        self.assertEqual(task.rubric, {"description": "Rúbrica U3-A3", "criteria": [{
            "criterion": "Configuración del YAML",
            "levels": [{"points": "0", "definition": "No se presenta."}, {"points": "3", "definition": "Funciona completo."}]}]})
        # La consigna no arrastra el nombre del anexo ni su fecha, y el anexo sigue listado aparte.
        self.assertEqual(task.content, "Objetivo: configurar un flujo de CI.")
        self.assertEqual([item["name"] for item in task.attachments], ["Guía.docx"])
        self.assertEqual(task.images, [{"name": "Esquema", "url": "https://moodle.test/pluginfile.php/7/intro/esquema.png"}])
        self.assertEqual(course_name(task.course), "SEGURIDAD")
        for noise in ("___picture___", "Guardar comentario", "puntos"):
            self.assertNotIn(noise, task.status)

    def test_course_name_is_the_same_for_the_list_and_the_detail(self):
        self.assertEqual(course_name("A -- VISUALIZACIÓN DE DATOS / SOFTWARE 2024 - NS--20262-1"), "VISUALIZACIÓN DE DATOS")
        self.assertEqual(course_name("A -- VISUALIZACIÓN DE DATOS--1208690--20262-1"), "VISUALIZACIÓN DE DATOS")
        self.assertEqual(course_name(""), "")


class ErrorContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_argument_errors_are_short_spanish_and_coded(self):
        with patch("moodle_tasks.server.load_config", return_value=SETTINGS):
            async with Client(create_server()) as client:
                unknown = await client.call_tool("get_assignment", {"assignmentId": 5})
                self.assertTrue(unknown.is_error)
                self.assertEqual(unknown.structured_content["error_code"], "invalid_arguments")
                self.assertIn("assignmentId", text_of(unknown))
                self.assertIn("assignment_id", text_of(unknown))

                invalid = await client.call_tool("build_delivery_document", {"document": {"title": "T", "blocks": [
                    {"type": "paragraph", "text": "ok"}, {"type": "heading", "text": "sin nivel"}]}})
                self.assertEqual(invalid.structured_content["error_code"], "invalid_arguments")
                self.assertIn("document.blocks.1: El bloque heading necesita: level.", text_of(invalid))
                for noise in ("pydantic", "input_value", "Error executing tool", "For further information"):
                    self.assertNotIn(noise, text_of(invalid))

                for wrong in (True, 11.5, " 11", "-3", "0"):
                    rejected = await client.call_tool("get_assignment", {"assignment_id": wrong})
                    self.assertEqual(rejected.structured_content["error_code"], "invalid_arguments", wrong)

    async def test_numeric_text_is_accepted_as_an_identifier(self):
        task = Assignment("Tarea", TASK_URL, "Consigna", "", "Sin entrega", False)
        linked = {"linked_resources": [], "links_omitted": 0, "linked_content_incomplete": False}
        with fake_browser(), patch("moodle_tasks.server.load_config", return_value=SETTINGS), \
                patch("moodle_tasks.server.read_assignment", return_value=task) as read, \
                patch("moodle_tasks.server.read_linked_resources", return_value=linked):
            async with Client(create_server()) as client:
                result = await client.call_tool("get_assignment", {"assignment_id": "9"})
                self.assertFalse(result.is_error, text_of(result))
                self.assertEqual(result.structured_content["assignment_id"], 9)
                self.assertTrue(read.call_args.args[1].endswith("view.php?id=9"))

    async def test_browser_and_http_failures_have_stable_codes_without_internal_logs(self):
        timeout = PlaywrightTimeoutError('Locator.wait_for: Timeout 15000ms exceeded.\nCall log:\n  - waiting for locator("a")\n')
        cases = ((timeout, "timeout", True), (MoodleHTTPError(404, TASK_URL), "not_found", False),
                 (MoodleHTTPError(502, TASK_URL), "moodle_server_error", True))
        for failure, code, retryable in cases:
            with fake_browser(), patch("moodle_tasks.server.load_config", return_value=SETTINGS), \
                    patch("moodle_tasks.server.read_assignment", side_effect=failure):
                async with Client(create_server()) as client:
                    result = await client.call_tool("get_assignment", {"assignment_id": 9})
            self.assertTrue(result.is_error)
            self.assertEqual(result.structured_content["error_code"], code)
            self.assertEqual(result.structured_content["retryable"], retryable)
            self.assertNotIn("Call log", text_of(result))
            self.assertNotIn("locator(", text_of(result))

    async def test_missing_configuration_is_reported_with_its_own_code(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            async with Client(create_server(Path(directory) / "vacío.env")) as client:
                result = await client.call_tool("list_assignments")
        self.assertEqual(result.structured_content["error_code"], "not_configured")


class ListingContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_timeline_is_a_complete_answer(self):
        def collect(config, **options):
            options["stats"].update(source="dashboard", candidates_checked=0, timeline_status="empty")
            return [], []

        with patch("moodle_tasks.server.collect_assignments", side_effect=collect), \
                patch("moodle_tasks.server.load_config", return_value=SETTINGS):
            async with Client(create_server()) as client:
                data = (await client.call_tool("list_assignments")).structured_content
        self.assertFalse(data["incomplete"])
        self.assertEqual(data["errors"], [])
        self.assertIn("No se encontraron tareas pendientes", data["response_markdown"])

    async def test_unreadable_timeline_stays_incomplete(self):
        with patch("moodle_tasks.server.collect_assignments", return_value=([], [])), \
                patch("moodle_tasks.server.load_config", return_value=SETTINGS):
            async with Client(create_server()) as client:
                data = (await client.call_tool("list_assignments")).structured_content
        self.assertTrue(data["incomplete"])
        self.assertIn("incompleta", data["response_markdown"])

    async def test_has_more_tells_when_the_limit_left_rows_out(self):
        tasks = [Assignment(f"Tarea {index}", f"https://moodle.test/mod/assign/view.php?id={index}", "", "", "", False,
                            due_at="2999-01-01T10:00:00") for index in range(1, 4)]
        with patch("moodle_tasks.server.collect_assignments", return_value=(tasks, [])) as collect, \
                patch("moodle_tasks.server.load_config", return_value=SETTINGS):
            async with Client(create_server()) as client:
                cut = (await client.call_tool("list_assignments", {"limit": 2})).structured_content
                self.assertEqual(collect.call_args.kwargs["limit"], 3)
                whole = (await client.call_tool("list_assignments", {"limit": 3})).structured_content
        self.assertTrue(cut["has_more"])
        self.assertEqual([row["assignment_id"] for row in cut["assignments"]], [1, 2])
        self.assertEqual(cut["response_markdown"].count("view.php?id="), 2)
        self.assertFalse(whole["has_more"])


class CoverContractTests(unittest.TestCase):
    PROFILE = {"subject": "Seguridad", "teacher": "Ing. Uno", "student_1": "Ana Pérez", "degree": "Software",
               "class_group": "6A", "year": "2026"}

    def test_saved_teacher_is_only_used_for_its_own_subject(self):
        own = cover_values(CoverFields(), self.PROFILE, "SEGURIDAD")
        self.assertEqual((own["materia"], own["nombre_docente"]), ("SEGURIDAD", "Ing. Uno"))
        with self.assertRaises(MissingCoverFields) as caught:
            cover_values(CoverFields(), self.PROFILE, "Visualización de Datos")
        # Otra materia nunca hereda al docente guardado: se pide, con lo ya resuelto a la vista.
        self.assertEqual(caught.exception.fields, ["nombre_docente"])
        self.assertEqual(caught.exception.known["materia"], "Visualización de Datos")
        self.assertEqual(teacher_for({**self.PROFILE, "teachers": {"Visualización de datos": "Ing. Dos"}},
                                     "VISUALIZACION DE DATOS"), "Ing. Dos")

    def test_subject_taken_from_the_profile_is_flagged(self):
        notes: list[str] = []
        values = cover_values(CoverFields(), self.PROFILE, None, notes)
        self.assertEqual(values["materia"], "Seguridad")
        self.assertIn("perfil guardado", notes[0])

    def test_teacher_is_remembered_per_subject(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "document_profile.json").write_text(json.dumps(self.PROFILE))
            self.assertTrue(remember_teacher("Visualización de Datos", "Ing. Dos", folder))
            self.assertTrue(remember_teacher("visualizacion de datos", "Ing. Tres", folder))
            profile = load_profile(folder)
            self.assertEqual(profile["teachers"], {"visualizacion de datos": "Ing. Tres"})
            self.assertEqual(profile["teacher"], "Ing. Uno")


class BuildRetryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "config"
        self.config.mkdir()
        (self.config / "document_profile.json").write_text(json.dumps(CoverContractTests.PROFILE))
        for target, value in (("moodle_tasks.server.user_config_dir", self.config),
                              ("moodle_tasks.paths.user_config_dir", self.config),
                              ("moodle_tasks.paths.user_cache_dir", self.root / "cache"),
                              ("moodle_tasks.delivery.user_cache_dir", self.root / "cache"),
                              ("moodle_tasks.document.find_soffice", None),
                              ("moodle_tasks.server.open_file", True),
                              ("moodle_tasks.server.load_config", SETTINGS)):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_cover_retry_reuses_the_draft_and_uses_the_subject_of_the_assignment(self):
        task = Assignment("Tablero", TASK_URL, "Consigna", "", "Sin entrega", False,
                          course="A -- VISUALIZACIÓN DE DATOS--1208690--20262-1")
        linked = {"linked_resources": [], "links_omitted": 0, "linked_content_incomplete": False}
        destination = str(self.root / "Entregas")

        async def run():
            with fake_browser(), patch("moodle_tasks.server.read_assignment", return_value=task), \
                    patch("moodle_tasks.server.read_linked_resources", return_value=linked):
                async with Client(create_server()) as client:
                    await client.call_tool("get_assignment", {"assignment_id": 9})
                    first = await client.call_tool("build_delivery_document", {
                        "document": document(), "assignment_id": 9, "destination_directory": destination})
                    retry = await client.call_tool("build_delivery_document", {
                        "draft_id": first.structured_content["draft_id"], "assignment_id": 9,
                        "cover": {"nombre_docente": "Ing. Dos"}, "destination_directory": destination})
                    again = await client.call_tool("build_delivery_document", {
                        "document": document(), "assignment_id": 9, "destination_directory": destination})
                    lost = await client.call_tool("build_delivery_document", {"draft_id": "no-existe"})
                    return first, retry, again, lost

        first, retry, again, lost = asyncio.run(run())
        data = first.structured_content
        # La materia sale de la tarea, no del perfil, y el docente de otra materia no se reutiliza.
        self.assertEqual(data["status"], "missing_cover_fields")
        self.assertEqual(data["missing_cover_fields"], ["nombre_docente"])
        self.assertEqual(data["known_cover"]["materia"], "VISUALIZACIÓN DE DATOS")
        self.assertIsNone(data["docx_path"])
        # El reintento solo envía la portada: el documento ya está en el servidor.
        built = retry.structured_content
        self.assertEqual(built["status"], "ok", text_of(retry))
        self.assertEqual(built["cover"]["nombre_docente"], "Ing. Dos")
        self.assertTrue(Path(built["pdf_path"]).is_file())
        # El docente indicado queda guardado para esa materia.
        self.assertEqual(again.structured_content["status"], "ok", text_of(again))
        self.assertEqual(again.structured_content["cover"]["nombre_docente"], "Ing. Dos")
        self.assertEqual(lost.structured_content["error_code"], "invalid_arguments")
        self.assertIn("draft_id", text_of(lost))


class AttachmentTextTests(unittest.TestCase):
    def test_docx_text_is_extracted_in_document_order_and_truncated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guia.docx"
            guide = Document()
            guide.add_paragraph("Paso 1: crea el repositorio.")
            table = guide.add_table(rows=1, cols=2)
            table.cell(0, 0).text, table.cell(0, 1).text = "Criterio", "Puntos"
            guide.add_paragraph("Paso 2: configura el pipeline.")
            guide.save(path)
            full = extract_text(path)
            self.assertEqual(full["text"], "Paso 1: crea el repositorio.\nCriterio | Puntos\nPaso 2: configura el pipeline.")
            cut = extract_text(path, 10)
            self.assertEqual((cut["text"], cut["text_truncated"], cut["text_chars"]), ("Paso 1: cr", True, len(full["text"])))
            self.assertEqual(extract_text(Path(directory) / "video.mp4"), {})
            broken = Path(directory) / "roto.pdf"
            broken.write_bytes(b"no es un pdf")
            self.assertIn("text_error", extract_text(broken))

    def test_repeating_a_download_reuses_the_identical_file(self):
        page, response = MagicMock(), MagicMock()
        response.status, response.headers = 200, {"content-type": "text/plain"}
        response.body.return_value = b"contenido del anexo"
        page.context.request.get.return_value = response
        url = "https://moodle.test/pluginfile.php/1/mod_assign/introattachment/0/notas.txt"
        with tempfile.TemporaryDirectory() as directory:
            first = download_attachment(page, SETTINGS, url, Path(directory))
            second = download_attachment(page, SETTINGS, url, Path(directory))
            response.body.return_value = b"otra version"
            third = download_attachment(page, SETTINGS, url, Path(directory))
            self.assertEqual((first["reused"], second["reused"], third["reused"]), (False, True, False))
            self.assertEqual(first["path"], second["path"])
            self.assertEqual(sorted(item.name for item in Path(directory).iterdir()), ["notas (1).txt", "notas.txt"])
            self.assertEqual(first["source_url"], url)

    def test_oversized_attachment_is_refused_before_reading_it(self):
        page, response = MagicMock(), MagicMock()
        response.status, response.headers = 200, {"content-type": "video/mp4", "content-length": str(300 * 1024 * 1024)}
        page.context.request.get.return_value = response
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(RuntimeError, "100 MB"):
            download_attachment(page, SETTINGS, "https://moodle.test/pluginfile.php/1/clase.mp4", Path(directory))
        response.body.assert_not_called()

    def test_download_tool_returns_the_text_and_a_folder_per_assignment(self):
        task = Assignment("Guía: práctica 3", TASK_URL, "", "", "", False,
                          attachments=[{"name": "notas.txt", "url": "https://moodle.test/pluginfile.php/1/notas.txt"}])

        async def run(documents):
            def fake_download(page, settings, url, directory):
                target = directory / "notas.txt"
                target.write_text("Requisito: entregar el informe.", encoding="utf-8")
                return {"name": target.name, "path": str(target), "size_bytes": 31, "content_type": "text/plain",
                        "source_url": url, "reused": False}

            with fake_browser(), patch("moodle_tasks.server.load_config", return_value=SETTINGS), \
                    patch("moodle_tasks.server.read_assignment", return_value=task), \
                    patch("moodle_tasks.downloads.documents_directory", return_value=documents), \
                    patch("moodle_tasks.server.download_attachment", side_effect=fake_download):
                async with Client(create_server()) as client:
                    with_text = await client.call_tool("download_assignment_attachments", {"assignment_id": 9})
                    without = await client.call_tool("download_assignment_attachments",
                                                     {"assignment_id": 9, "include_text": False})
                    return with_text.structured_content, without.structured_content

        with tempfile.TemporaryDirectory() as directory:
            with_text, without = asyncio.run(run(Path(directory)))
            self.assertEqual(with_text["destination_directory"], str(Path(directory).resolve() / "Moodle" / "Guía_ práctica 3"))
        self.assertEqual(with_text["files"][0]["text"], "Requisito: entregar el informe.")
        self.assertNotIn("text", without["files"][0])


class LinkedContinuationTests(unittest.TestCase):
    def test_truncated_link_can_be_continued_from_its_next_offset(self):
        result: dict = {}
        linked_content._slice(result, "abcdefghij", 0, 4)
        self.assertEqual(result, {"content": "abcd", "truncated": True, "total_chars": 10, "next_offset": 4})
        rest: dict = {}
        linked_content._slice(rest, "abcdefghij", 4, 30)
        self.assertEqual(rest, {"content": "efghij", "truncated": False, "total_chars": 10, "offset": 4})

    def test_continuation_only_reads_a_link_of_the_assignment(self):
        links = [{"name": "", "url": "https://example.com/guia"}]

        def fake_read(browser, link, max_chars=linked_content.MAX_CONTENT, offset=0):
            return dict(link, content=f"desde {offset}", truncated=False)

        with patch("moodle_tasks.linked_content.read_link", side_effect=fake_read):
            result = linked_content.read_linked_resources(None, links, only_url="https://example.com/guia#parte", offset=30_000)
            self.assertEqual(result["linked_resources"][0]["content"], "desde 30000")
            with self.assertRaisesRegex(ValueError, "resource_url"):
                linked_content.read_linked_resources(None, links, only_url="https://otro.example/", offset=0)


class SchemaContractTests(unittest.IsolatedAsyncioTestCase):
    def test_slim_schema_keeps_fields_named_title(self):
        schema = {"title": "Args", "properties": {"title": {"title": "Title", "anyOf": [{"type": "string"}, {"type": "null"}],
                                                            "default": None, "description": "Título"}}}
        self.assertEqual(slim_schema(schema), {"properties": {"title": {"type": "string", "description": "Título"}}})

    async def test_published_schemas_are_lean_and_describe_real_outputs(self):
        async with Client(create_server()) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        for tool in tools.values():
            self.assertTrue(tool.title, tool.name)
            self.assertNotIn("anyOf", json.dumps(tool.input_schema.get("properties", {})), tool.name)
            self.assertNotIn('"title"', json.dumps({key: value for key, value in tool.input_schema.items() if key != "$defs"}
                                                   | {"properties": {name: {k: v for k, v in item.items() if k != "properties"}
                                                                     for name, item in tool.input_schema.get("properties", {}).items()}}))
            self.assertTrue(tool.output_schema["properties"], tool.name)
        self.assertNotIn("maximum", tools["get_assignment"].input_schema["properties"]["assignment_id"])
        self.assertIn("missing_cover_fields", tools["build_delivery_document"].output_schema["properties"]["status"]["enum"])
        self.assertIn("save_unconfirmed", tools["upload_assignment_files"].output_schema["properties"]["status"]["enum"])
        self.assertFalse(tools["configuration_status"].annotations.open_world_hint)
        total = sum(len(json.dumps(tool.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False)) for tool in tools.values())
        self.assertLess(total, 17_000)


if __name__ == "__main__":
    unittest.main()
