import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import helpers  # noqa: F401 - aísla las pruebas de la configuración real
from moodle_tasks.core import Assignment
from moodle_tasks.server import SDK_CHANGED, MoodleTools, assignment_resources, create_server, publish_schemas


class MoodleToolsTests(unittest.TestCase):
    """La lógica de las herramientas se prueba sin levantar el SDK de MCP."""

    def test_configuration_status_lists_only_the_missing_variables(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env_file = Path(directory) / "credentials.env"
            env_file.write_text("MOODLE_URL=https://moodle.test\nMOODLE_USERNAME=student\n")
            status = MoodleTools(env_file).configuration_status()
        self.assertEqual(status, {"configured": False, "missing_variables": ["MOODLE_PASSWORD"]})

    def test_errors_hide_the_credentials_and_follow_a_changed_password(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env_file = Path(directory) / "credentials.env"
            env_file.write_text("MOODLE_USERNAME=student\nMOODLE_PASSWORD=first-secret\n")
            tools = MoodleTools(env_file)
            self.assertNotIn("first-secret", tools.safe_error("fallo con first-secret"))
            env_file.write_text("MOODLE_USERNAME=student\nMOODLE_PASSWORD=second-secret\n")
            self.assertNotIn("second-secret", tools.safe_error("fallo con second-secret"))

    def test_known_tasks_are_bounded(self):
        tools = MoodleTools(Path("unused.env"))
        task = Assignment("Taller", "https://moodle.test/mod/assign/view.php?id=1", "", "", "", False, course="Redes")
        for identifier in range(1, 503):
            tools.remember_task(identifier, task)
        self.assertEqual(len(tools.known_tasks), 500)
        self.assertNotIn(1, tools.known_tasks)
        self.assertEqual(tools.known_tasks[502]["course"], "Redes")

    def test_assignment_resources_are_unique_and_resources_redirect_to_their_file(self):
        task = Assignment(
            "Taller", "https://moodle.test/mod/assign/view.php?id=1", "", "", "", False,
            attachments=[{"name": "guia.pdf", "url": "https://moodle.test/pluginfile.php/1/guia.pdf"}],
            links=[{"name": "Lectura", "url": "https://moodle.test/mod/resource/view.php?id=7#inicio"},
                   {"name": "Externo", "url": "https://example.com/guia"}],
            images=[{"name": "", "url": "https://moodle.test/pluginfile.php/1/guia.pdf"},
                    {"name": "", "url": "https://example.com/foto.png"}],
            feedback={"files": [{"name": "corregido.pdf", "url": "https://moodle.test/pluginfile.php/2/corregido.pdf"}]},
        )
        self.assertEqual(assignment_resources(task, "https://moodle.test"), [
            "https://moodle.test/pluginfile.php/1/guia.pdf",
            "https://moodle.test/mod/resource/view.php?id=7&redirect=1",
            "https://moodle.test/pluginfile.php/2/corregido.pdf",
        ])


class SdkGuardTests(unittest.TestCase):
    def test_a_changed_sdk_fails_at_startup_with_a_clear_message(self):
        with self.assertRaisesRegex(RuntimeError, "_tool_manager"):
            publish_schemas(SimpleNamespace())
        broken = SimpleNamespace(_tool_manager=SimpleNamespace(get_tool=lambda name: SimpleNamespace()))
        with self.assertRaises(RuntimeError) as caught:
            publish_schemas(broken)
        self.assertEqual(str(caught.exception), SDK_CHANGED)

    def test_the_current_sdk_publishes_every_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            create_server(Path(directory) / "credentials.env")


if __name__ == "__main__":
    unittest.main()
