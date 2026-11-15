import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import helpers  # noqa: F401 - aísla las pruebas de la configuración real


def load_install_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "install.py"
    spec = importlib.util.spec_from_file_location("install", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class InstallCommandTests(unittest.TestCase):
    def test_tool_install_uses_the_dependencies_pinned_in_the_lockfile(self):
        module = load_install_script()
        project, constraints = Path("/tmp/moodle"), Path("/tmp/requirements.txt")
        self.assertEqual(
            module.export_constraints_command(project, constraints),
            ["uv", "export", "-q", "--project", str(project), "--locked", "--no-dev", "--no-emit-project",
             "--no-hashes", "--format", "requirements.txt", "--output-file", str(constraints)],
        )
        self.assertEqual(
            module.tool_install_command(project, constraints),
            ["uv", "tool", "install", "-q", "--force", "--python", "3.11", "--reinstall-package",
             "moodle-homework-assignment", "--constraints", str(constraints), str(project)],
        )

    def test_every_family_puts_the_command_on_path_before_setup(self):
        module = load_install_script()
        for family in ("windows", "debian", "arch", "macos"):
            with self.subTest(family=family), patch.object(module, "run") as run, patch.object(
                module, "tool_python", return_value="/tool/python"
            ), patch.object(module.Confirm, "ask", return_value=False):
                module.main(["--family", family])
                commands = [call.args for call in run.call_args_list]
                self.assertEqual(commands[0][:2], ("uv", "export"))
                constraints = Path(commands[0][commands[0].index("--output-file") + 1])
                self.assertEqual(commands[1], tuple(module.tool_install_command(module.PROJECT_DIR, constraints)))
                self.assertEqual(commands[2], ("uv", "tool", "update-shell"))
                # El asistente usa el Python de la herramienta recién instalada, no el PATH.
                self.assertEqual(commands[-1], ("/tool/python", "-m", "moodle_tasks.cli", "setup"))
                self.assertNotIn(("mcp-moodle", "setup"), commands)

    def test_every_installer_runs_the_shared_script(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("INSTALAR-ARCH.sh", "INSTALAR-DEBIAN.sh", "INSTALAR-MACOS.sh", "INSTALAR-WINDOWS.ps1"):
            with self.subTest(installer=name):
                self.assertIn("scripts/install.py", (root / name).read_text(encoding="utf-8"))
