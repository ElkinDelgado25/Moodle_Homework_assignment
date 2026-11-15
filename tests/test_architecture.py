import ast
import subprocess
import sys
import unittest
from pathlib import Path

import helpers  # noqa: F401 - aísla las pruebas de la configuración real

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "moodle_tasks"


def local_imports(module: str) -> set[str]:
    """Módulos del paquete que importa module, también dentro de funciones."""
    tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            found.update([node.module] if node.module else [alias.name for alias in node.names])
    return found


class ArchitectureTests(unittest.TestCase):
    def test_the_core_only_depends_on_errors_and_storage(self):
        self.assertLessEqual(local_imports("core"), {"errors", "storage"})

    def test_only_the_entry_points_import_the_terminal_command(self):
        importers = sorted(path.stem for path in PACKAGE.glob("*.py") if "main" in local_imports(path.stem))
        self.assertEqual(importers, ["cli", "server"])

    def test_the_terminal_query_does_not_load_the_mcp_server_or_the_document_builders(self):
        # print_tasks con una tarea pendiente es lo que antes cargaba todo el servidor para pending_table.
        code = ("import contextlib, io, sys\n"
                "from moodle_tasks.core import Assignment\n"
                "from moodle_tasks.main import print_tasks\n"
                "import moodle_tasks.assignment\n"
                "with contextlib.redirect_stdout(io.StringIO()):\n"
                "    print_tasks([Assignment('T', 'https://moodle.test/mod/assign/view.php?id=1', '', '', '', False)])\n"
                "print(sorted(name for name in ('moodle_tasks.server', 'mcp', 'docx', 'fpdf') if name in sys.modules))")
        output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
        self.assertEqual(output.strip().splitlines()[-1], "[]")


if __name__ == "__main__":
    unittest.main()
