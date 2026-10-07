import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client, StdioServerParameters

from moodle_tasks.main import Assignment, Config
from moodle_tasks.server import create_server


class MCPTests(unittest.IsolatedAsyncioTestCase):
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
            async with Client(params) as client:
                tools = await client.list_tools()
                self.assertEqual({tool.name for tool in tools.tools}, {
                    "configuration_status", "check_moodle_connection", "list_assignments", "get_assignment"
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
