import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


def load_install_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "install_linux.py"
    spec = importlib.util.spec_from_file_location("install_linux", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class InstallCommandTests(unittest.TestCase):
    def test_tool_install_command_replaces_the_user_install(self):
        module = load_install_script()
        project = Path("/tmp/moodle")
        self.assertEqual(
            module.tool_install_command(project),
            ["uv", "tool", "install", "--force", "--python", "3.11", str(project)],
        )

    def test_every_family_puts_the_command_on_path_before_setup(self):
        module = load_install_script()
        for family in ("windows", "debian", "arch", "macos"):
            with self.subTest(family=family), patch.object(module, "run") as run, patch.object(
                module, "tool_python", return_value="/tool/python"
            ), patch.object(module.Confirm, "ask", return_value=False):
                module.main(["--family", family])
                commands = [call.args for call in run.call_args_list]
                self.assertEqual(commands[0], tuple(module.tool_install_command(module.PROJECT_DIR)))
                self.assertEqual(commands[1], ("uv", "tool", "update-shell"))
                self.assertEqual(commands[-1], ("mcp-moodle", "setup"))
