import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp import Client, StdioServerParameters

import helpers  # noqa: F401 - desactiva la caché de sesión
from moodle_tasks.errors import MoodleHTTPError
from moodle_tasks.main import Assignment, Config
from moodle_tasks.server import INSTRUCTIONS, assignment_id_from_reference, create_server

SETTINGS = Config("https://moodle.test", "test", "test", True)


@contextmanager
def fake_browser():
    """Sustituye el navegador de session.moodle_page sin abrir Chromium ni guardar sesiones."""
    browser, page = MagicMock(name="browser"), MagicMock(name="page")
    with patch("moodle_tasks.server.moodle_page") as session:
        session.return_value.__enter__.return_value = (browser, page)
        yield session


def text_of(result) -> str:
    return " ".join(block.text for block in result.content if block.type == "text")


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_instructions_are_short_and_keep_the_key_rules(self):
        self.assertLess(len(INSTRUCTIONS), 2500)
        for phrase in ("solo muestra una URL", "No explores archivos locales", "build_delivery_document",
                       "response_markdown", "Nunca se envía para calificar", "error del servidor"):
            self.assertIn(phrase, INSTRUCTIONS)

    async def test_assignment_reference_rules(self):
        base = "https://moodle.test"
        self.assertEqual(assignment_id_from_reference(None, "https://moodle.test/mod/assign/view.php?id=362681", base), 362681)
        self.assertEqual(assignment_id_from_reference(None, "https://MOODLE.test:443/mod/assign/view.php?id=5", base), 5)
        self.assertEqual(assignment_id_from_reference(362681, None, base), 362681)
        self.assertEqual(assignment_id_from_reference(None, "https://u.test/moodle/mod/assign/view.php?id=7", "https://u.test/moodle"), 7)
        for url in ("https://other.test/mod/assign/view.php?id=362681", "https://moodle.test/mod/url/view.php?id=362681",
                    "https://moodle.test/mod/assign/view.php?id=５", "https://moodle.test/mod/assign/view.php?id=1&id=2",
                    "https://moodle.test/mod/assign/view.php?id=0", "https://user@moodle.test/mod/assign/view.php?id=1",
                    "javascript:alert(1)", "https://moodle.test/mod/assign/view.php?id=1_0", "http://[::1"):
            with self.assertRaises(ValueError, msg=url):
                assignment_id_from_reference(None, url, base)
        for value in (True, 0, -1, 2**64):
            with self.assertRaises(ValueError, msg=value):
                assignment_id_from_reference(value, None, base)
        with self.assertRaises(ValueError):
            assignment_id_from_reference(1, "https://moodle.test/mod/assign/view.php?id=1", base)

    async def test_get_assignment_is_lean_and_never_writes_files(self):
        task = Assignment("Práctica", "https://moodle.test/mod/assign/view.php?id=9",
                          "Desarrollar la aplicación y presentar un informe.", "", "", False)
        linked = {"linked_resources": [], "links_omitted": 0, "linked_content_incomplete": False}
        with tempfile.TemporaryDirectory() as directory, fake_browser(), patch(
            "moodle_tasks.server.user_config_dir", return_value=Path(directory)
        ), patch("moodle_tasks.server.load_config", return_value=SETTINGS), patch(
            "moodle_tasks.server.read_assignment", return_value=task
        ), patch("moodle_tasks.server.read_linked_resources", return_value=linked) as read_links, patch(
            "moodle_tasks.server.download_attachment"
        ) as download, patch("moodle_tasks.server.upload_files") as upload:
            async with Client(create_server()) as client:
                result = await client.call_tool("get_assignment", {"url": task.url})
                self.assertFalse(result.is_error)
                data = result.structured_content
                self.assertEqual(data["assignment_id"], 9)
                self.assertEqual(data["description"], task.content)
                self.assertTrue(data["description_found"])
                for removed in ("assignment_workflow", "document_template", "instructions", "links"):
                    self.assertNotIn(removed, data)
                self.assertEqual(json.loads(text_of(result)), data)
                self.assertNotIn("\n  ", text_of(result))
                self.assertLess(len(text_of(result)), 2500)
                self.assertEqual(read_links.call_args.kwargs["config"], SETTINGS)
                self.assertEqual(list(Path(directory).iterdir()), [])
                download.assert_not_called()
                upload.assert_not_called()

    async def test_server_failure_is_a_clear_tool_error_for_task_queries(self):
        failure = MoodleHTTPError(502, "https://moodle.test/login/index.php")
        with fake_browser(), patch("moodle_tasks.server.load_config", return_value=SETTINGS), \
                patch("moodle_tasks.server.collect_assignments", side_effect=failure), \
                patch("moodle_tasks.server.read_assignment", side_effect=failure), \
                patch("moodle_tasks.server.login", side_effect=failure):
            async with Client(create_server()) as client:
                for tool, arguments in (("list_assignments", {}), ("list_assignments", {"mode": "all"}),
                                        ("get_assignment", {"assignment_id": 1})):
                    result = await client.call_tool(tool, arguments)
                    self.assertTrue(result.is_error)
                    self.assertIn(str(failure), text_of(result))
                connection = await client.call_tool("check_moodle_connection")
                self.assertEqual(connection.structured_content, {
                    "connected": False, "error": str(failure), "http_status": 502, "error_code": "server_error"
                })

    async def test_standard_stdio_discovery_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("MOODLE_URL=https://moodle.test\nMOODLE_USERNAME=test\nMOODLE_PASSWORD=private-test-password\n")
            environment = {key: value for key, value in os.environ.items() if not key.startswith("MOODLE_")}
            params = StdioServerParameters(command=sys.executable, args=["-m", "moodle_tasks.server", "--env-file", str(env_file)],
                                           cwd=directory, env=environment)
            async with Client(params, mode="legacy") as client:
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertEqual(names, {"configuration_status", "check_moodle_connection", "list_assignments",
                                         "get_assignment", "download_assignment_attachments", "upload_assignment_files",
                                         "get_document_template", "build_delivery_document", "finish_delivery"})
                writers = ("download_assignment_attachments", "upload_assignment_files", "build_delivery_document", "finish_delivery")
                self.assertTrue(all(tool.annotations.read_only_hint for tool in tools.tools if tool.name not in writers))
                upload = next(tool for tool in tools.tools if tool.name == "upload_assignment_files")
                self.assertTrue(upload.annotations.destructive_hint)
                for tool in tools.tools:
                    self.assertLess(len(tool.description or ""), 700, tool.name)
                total = sum(len(json.dumps(tool.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False)) for tool in tools.tools)
                self.assertLess(total, 16000)
                result = await client.call_tool("configuration_status")
                self.assertEqual(result.structured_content, {"configured": True, "missing_variables": []})
                self.assertNotIn("private-test-password", str(result))
                for tool, arguments in (("get_assignment", {"assignment_id": -1}),
                                        ("download_assignment_attachments", {"assignment_id": 0}),
                                        ("upload_assignment_files", {"assignment_id": 1, "file_paths": []}),
                                        ("list_assignments", {"limit": 0}), ("list_assignments", {"mode": "recent"})):
                    invalid = await client.call_tool(tool, arguments)
                    self.assertTrue(invalid.is_error, (tool, arguments))

    async def test_document_template_points_to_the_builder(self):
        from zipfile import ZipFile
        with tempfile.TemporaryDirectory() as directory, patch("moodle_tasks.server.user_config_dir", return_value=Path(directory)):
            async with Client(create_server()) as client:
                result = await client.call_tool("get_document_template")
        data = result.structured_content
        self.assertEqual(data["tool"], "build_delivery_document")
        self.assertEqual(data["local_defaults"], {})
        self.assertEqual(data["formatting"]["font"], "Times New Roman")
        self.assertIn("gh repo view", data["content_policy"])
        self.assertTrue(Path(data["logo_path"]).is_file())
        with ZipFile(data["template_path"]) as document:
            xml = document.read("word/document.xml").decode()
            for field in data["fields"]:
                self.assertIn("{{" + field + "}}", xml)

    async def test_cover_profile_is_local_filtered_and_validated(self):
        with tempfile.TemporaryDirectory() as directory, patch("moodle_tasks.server.user_config_dir", return_value=Path(directory)):
            profile = Path(directory) / "document_profile.json"
            profile.write_text('{"student_1": "Test Student", "password": "excluded-test-value", "year": 2026}')
            async with Client(create_server()) as client:
                result = await client.call_tool("get_document_template")
                self.assertEqual(result.structured_content["local_defaults"], {"student_1": "Test Student", "year": "2026"})
                self.assertNotIn("excluded-test-value", str(result))
                profile.write_text('["no es un objeto"]')
                invalid = await client.call_tool("get_document_template")
                self.assertTrue(invalid.is_error)
                self.assertIn("perfil local", str(invalid))

    async def test_download_validates_the_folder_first_and_reports_partial_results(self):
        task = Assignment("Tarea", "https://moodle.test/mod/assign/view.php?id=9", "", "", "", False,
                          attachments=[{"url": "https://moodle.test/pluginfile.php/good.pdf"},
                                       {"url": "https://moodle.test/pluginfile.php/good.pdf"},
                                       {"url": "https://moodle.test/pluginfile.php/bad.pdf"}])
        with tempfile.TemporaryDirectory() as directory, fake_browser() as session, patch(
            "moodle_tasks.server.load_config", return_value=SETTINGS
        ), patch("moodle_tasks.server.read_assignment", return_value=task), patch(
            "moodle_tasks.server.download_attachment", side_effect=[{"path": str(Path(directory) / "good.pdf")}, RuntimeError("HTTP 403")]
        ) as download:
            async with Client(create_server()) as client:
                result = await client.call_tool("download_assignment_attachments",
                                                {"url": task.url, "destination_directory": str(Path(directory) / "nueva")})
                data = result.structured_content
                self.assertTrue(data["incomplete"])
                self.assertEqual(data["attachment_count"], 2)
                self.assertEqual(data["downloaded_count"], 1)
                self.assertIn("HTTP 403", data["errors"][0]["error"])
                self.assertEqual(download.call_count, 2)
                self.assertTrue((Path(directory) / "nueva").is_dir())
                calls = session.call_count
                for destination in ("relativa", directory + "/.oculta"):
                    bad = await client.call_tool("download_assignment_attachments", {"assignment_id": 9, "destination_directory": destination})
                    self.assertTrue(bad.is_error, destination)
                self.assertEqual(session.call_count, calls)

    async def test_pending_filter_includes_unknown_and_reports_partial_results(self):
        tasks = [Assignment("Tarea", "https://moodle.test/mod/assign/view.php?id=4", "Texto", "Mañana", "Estado", state)
                 for state in (True, False, None)]
        with patch("moodle_tasks.server.collect_assignments", return_value=(tasks, ["Error de lectura"])), \
                patch("moodle_tasks.server.load_config", return_value=SETTINGS):
            async with Client(create_server()) as client:
                data = (await client.call_tool("list_assignments")).structured_content
                self.assertEqual(data["reviewed_count"], 3)
                self.assertTrue(data["incomplete"])
                self.assertEqual([task["submitted"] for task in data["assignments"]], [False, None])
                self.assertEqual(data["assignments"][0]["assignment_id"], 4)

    async def test_default_response_provides_one_table_with_minimal_rows(self):
        tasks = [Assignment('App de cuadrícula', 'https://moodle.test/mod/assign/view.php?id=3', 'texto largo', '', '', False,
                            course='A -- Aplicaciones Móviles Nativas--1208706--20262-1', due_at='2026-10-11T23:59:00',
                            attachments=[{"url": "x"}], links=[{"url": "y"}])]
        with patch('moodle_tasks.server.collect_assignments', return_value=(tasks, [])), \
                patch('moodle_tasks.server.load_config', return_value=SETTINGS):
            async with Client(create_server()) as client:
                data = (await client.call_tool('list_assignments')).structured_content
                markdown = data['response_markdown']
                self.assertTrue(markdown.startswith('Estas son las tareas pendientes\n\n'))
                self.assertIn('Aplicaciones Móviles Nativas | 11/10/2026 23:59 (', markdown)
                self.assertIn(data['assignments'][0]['due_display'], markdown)
                self.assertNotIn('1208706', markdown)
                self.assertEqual(set(data['assignments'][0]), {"assignment_id", "title", "course", "due_at",
                                                               "due_display", "submitted", "url"})
                complete = await client.call_tool('list_assignments', {'mode': 'all'})
                self.assertNotIn('response_markdown', complete.structured_content)

    async def test_modes_and_limits(self):
        with patch("moodle_tasks.server.collect_assignments", return_value=([], [])) as collect, \
                patch("moodle_tasks.server.load_config", return_value=SETTINGS):
            async with Client(create_server()) as client:
                await client.call_tool("list_assignments")
                self.assertEqual((collect.call_args.kwargs['mode'], collect.call_args.kwargs['limit']), ('upcoming', 5))
                await client.call_tool("list_assignments", {"mode": "all"})
                self.assertEqual((collect.call_args.kwargs['mode'], collect.call_args.kwargs['limit']), ('all', None))
                await client.call_tool("list_assignments", {"mode": "overdue", "limit": 20})
                self.assertEqual((collect.call_args.kwargs['mode'], collect.call_args.kwargs['limit']), ('overdue', 20))
                self.assertNotIn("refresh", collect.call_args.kwargs)

    async def test_graded_activities_do_not_inflate_pending_count(self):
        tasks = [
            Assignment("Pendiente", "https://moodle.test/task", "", "", "", False),
            Assignment("Laboratorio calificado", "https://moodle.test/graded", "", "", "", False,
                       grade="10,00", requires_submission=False),
            Assignment("No abierta", "https://moodle.test/future", "", "", "", False, opens_at="2999-01-01T00:00:00"),
        ]
        with patch("moodle_tasks.server.collect_assignments", return_value=(tasks, [])), \
                patch("moodle_tasks.server.load_config", return_value=SETTINGS):
            async with Client(create_server()) as client:
                data = (await client.call_tool("list_assignments", {"mode": "all"})).structured_content
                self.assertEqual(data['pending_count'], 2)
                self.assertFalse(data['availability_confirmed'])
                self.assertEqual([task['title'] for task in data['assignments']], ['Pendiente', 'No abierta'])

    async def test_index_rows_without_confirmed_availability_are_flagged(self):
        def collect(config, **options):
            options['stats'].update(candidates_checked=2, source='course_indexes', availability_unconfirmed=1)
            return [Assignment("A", "https://moodle.test/mod/assign/view.php?id=1", "", "", "", False, due_at="2999-01-01T00:00:00")], []

        with patch('moodle_tasks.server.collect_assignments', side_effect=collect), \
                patch('moodle_tasks.server.load_config', return_value=SETTINGS):
            async with Client(create_server()) as client:
                data = (await client.call_tool('list_assignments')).structured_content
                self.assertFalse(data['availability_confirmed'])
                self.assertEqual(data['returned_count'], 1)

    async def test_complete_review_can_report_zero_pending_after_checking_activities(self):
        def collect(config, **options):
            options['stats'].update(candidates_checked=12, source='course_indexes')
            return [], []

        with patch('moodle_tasks.server.collect_assignments', side_effect=collect), \
                patch('moodle_tasks.server.load_config', return_value=SETTINGS):
            async with Client(create_server()) as client:
                data = (await client.call_tool('list_assignments', {'mode': 'all'})).structured_content
                self.assertFalse(data['incomplete'])
                self.assertEqual(data['reviewed_count'], 12)
                self.assertEqual(data['pending_count'], 0)

    async def test_server_errors_hide_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("MOODLE_USERNAME=private-user\nMOODLE_PASSWORD=private/pass+word\n")
            leak = 'private/pass+word private%2Fpass%2Bword PRIVATE-USER "private\\/pass+word"'
            with patch("moodle_tasks.server.collect_assignments", side_effect=RuntimeError(leak)), \
                    patch("moodle_tasks.server.load_config", return_value=Config("https://moodle.test", "private-user", "private/pass+word", True)):
                async with Client(create_server(path)) as client:
                    result = await client.call_tool("list_assignments")
                    self.assertTrue(result.is_error)
                    for secret in ("private/pass+word", "private-user", "PRIVATE-USER", "private%2Fpass%2Bword"):
                        self.assertNotIn(secret, str(result))


class SourceHygieneTests(unittest.TestCase):
    def test_no_invisible_or_bidi_characters_in_source(self):
        root = Path(__file__).resolve().parents[1]
        pattern = re.compile("[\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")
        offenders = [str(path.relative_to(root)) for folder in ("src", "tests", "scripts")
                     for path in (root / folder).rglob("*.py") if pattern.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
