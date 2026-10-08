import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client, StdioServerParameters

from moodle_tasks.main import Assignment, Config
from moodle_tasks.server import create_server
from moodle_tasks.errors import MoodleHTTPError


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_failure_is_a_clear_tool_error_for_task_queries(self):
        failure = MoodleHTTPError(502, "https://moodle.test/login/index.php")
        config = Config("https://moodle.test", "test", "test", True)
        with patch("moodle_tasks.server.load_config", return_value=config), patch("moodle_tasks.server.collect_assignments", side_effect=failure), patch("moodle_tasks.server.login", side_effect=failure):
            async with Client(create_server()) as client:
                for tool, arguments in (("list_assignments", {}), ("list_all_assignments", {}), ("get_assignment", {"assignment_id": 1})):
                    result = await client.call_tool(tool, arguments)
                    self.assertTrue(result.is_error)
                    message = " ".join(block.text for block in result.content if block.type == "text")
                    self.assertIn(str(failure), message)
                    self.assertNotIn("No se encontraron tareas pendientes", message)
                connection = await client.call_tool("check_moodle_connection")
                self.assertEqual(connection.structured_content, {
                    "connected": False, "error": str(failure), "http_status": 502, "error_code": "server_error"
                })

    async def test_standard_stdio_discovery_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("MOODLE_URL=https://moodle.test\nMOODLE_USERNAME=test\nMOODLE_PASSWORD=private-test-password\n")
            environment = {key: value for key, value in os.environ.items() if not key.startswith("MOODLE_")}
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "moodle_tasks.server", "--env-file", str(env_file)],
                cwd=directory,
                env=environment,
            )
            # Comprueba también el handshake initialize usado por clientes MCP anteriores.
            async with Client(params, mode="legacy") as client:
                tools = await client.list_tools()
                self.assertEqual({tool.name for tool in tools.tools}, {
                    "configuration_status", "check_moodle_connection", "list_assignments", "list_all_assignments", "get_assignment"
                })
                self.assertTrue(all(tool.annotations.read_only_hint for tool in tools.tools))
                result = await client.call_tool("configuration_status")
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content, {"configured": True, "missing_variables": []})
                self.assertNotIn("private-test-password", str(result))
                invalid = await client.call_tool("get_assignment", {"assignment_id": -1})
                self.assertTrue(invalid.is_error)

    async def test_pending_filter_includes_unknown_and_reports_partial_results(self):
        tasks = [Assignment("Tarea", "https://moodle.test/task", "Texto", "Mañana", "Estado", state)
                 for state in (True, False, None)]
        with patch("moodle_tasks.server.collect_assignments", return_value=(tasks, ["Error de lectura"])), patch("moodle_tasks.server.load_config", return_value=Config("https://moodle.test", "test", "test", True)):
            async with Client(create_server()) as client:
                result = await client.call_tool("list_assignments")
                self.assertFalse(result.is_error)
                data = result.structured_content
                self.assertEqual(data["reviewed_count"], 3)
                self.assertTrue(data["incomplete"])
                self.assertEqual([task["submitted"] for task in data["assignments"]], [False, None])

    async def test_default_response_provides_one_table_with_the_requested_intro(self):
        tasks = [Assignment('App de cuadrícula', 'https://moodle.test/mod/assign/view.php?id=3', '', '', '', False,
                            course='A -- Aplicaciones Móviles Nativas--1208706--20262-1', due_at='2026-10-11T23:59:00')]
        with patch('moodle_tasks.server.collect_assignments', return_value=(tasks, [])), patch('moodle_tasks.server.load_config', return_value=Config('https://moodle.test', 'test', 'test', True)):
            async with Client(create_server()) as client:
                result = await client.call_tool('list_assignments')
                markdown = result.structured_content['response_markdown']
                self.assertTrue(markdown.startswith('Estas son las tareas pendientes\n\n'))
                self.assertIn('| Tarea | Materia | Fecha límite | Anexos |', markdown)
                self.assertIn('Aplicaciones Móviles Nativas | 11/10/2026 23:59 | Sin anexos', markdown)
                self.assertNotIn('1208706', markdown)
                complete = await client.call_tool('list_all_assignments')
                self.assertNotIn('response_markdown', complete.structured_content)

    async def test_complete_tool_has_no_limit_and_quick_tool_uses_five_by_default(self):
        settings = Config("https://moodle.test", "test", "test", True)
        with patch("moodle_tasks.server.collect_assignments", return_value=([], [])) as collect, patch("moodle_tasks.server.load_config", return_value=settings):
            async with Client(create_server()) as client:
                await client.call_tool("list_assignments")
                self.assertEqual(collect.call_args.kwargs['mode'], 'upcoming')
                self.assertEqual(collect.call_args.kwargs['limit'], 5)
                await client.call_tool("list_all_assignments", {"refresh": True})
                self.assertEqual(collect.call_args.kwargs['mode'], 'all')
                self.assertIsNone(collect.call_args.kwargs['limit'])
                self.assertTrue(collect.call_args.kwargs['refresh'])
                count = collect.call_count
                invalid = await client.call_tool("list_assignments", {"limit": 0})
                self.assertTrue(invalid.is_error)
                self.assertEqual(collect.call_count, count)

    async def test_graded_activities_do_not_inflate_pending_count(self):
        tasks = [
            Assignment("Pendiente", "https://moodle.test/task", "", "", "", False),
            Assignment("Laboratorio calificado", "https://moodle.test/graded", "", "", "", False,
                       grade="10,00", requires_submission=False),
            Assignment("No abierta", "https://moodle.test/future", "", "", "", False,
                       opens_at="2999-01-01T00:00:00"),
        ]
        with patch("moodle_tasks.server.collect_assignments", return_value=(tasks, [])), patch("moodle_tasks.server.load_config", return_value=Config("https://moodle.test", "test", "test", True)):
            async with Client(create_server()) as client:
                result = await client.call_tool("list_all_assignments")
                data = result.structured_content
                self.assertEqual(data['pending_count'], 2)
                self.assertEqual(data['not_yet_open_count'], 1)
                self.assertEqual([task['title'] for task in data['assignments']], ['Pendiente', 'No abierta'])

    async def test_complete_review_can_report_zero_pending_after_checking_activities(self):
        def collect(config, **options):
            options['stats'].update(candidates_checked=12, source='course_indexes')
            return [], []

        with patch('moodle_tasks.server.collect_assignments', side_effect=collect), patch('moodle_tasks.server.load_config', return_value=Config('https://moodle.test', 'test', 'test', True)):
            async with Client(create_server()) as client:
                result = await client.call_tool('list_all_assignments')
                self.assertFalse(result.structured_content['incomplete'])
                self.assertEqual(result.structured_content['reviewed_count'], 12)
                self.assertEqual(result.structured_content['pending_count'], 0)

    async def test_server_errors_hide_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("MOODLE_USERNAME=private-user\nMOODLE_PASSWORD=private-password\n")
            with patch("moodle_tasks.server.collect_assignments", side_effect=RuntimeError("private-password private-user")), patch("moodle_tasks.server.load_config", return_value=Config("https://moodle.test", "private-user", "private-password", True)):
                async with Client(create_server(path)) as client:
                    result = await client.call_tool("list_assignments")
                    self.assertTrue(result.is_error)
                    self.assertNotIn("private-password", str(result))
                    self.assertNotIn("private-user", str(result))
