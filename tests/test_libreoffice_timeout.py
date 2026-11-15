import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from moodle_tasks.document import export_with_libreoffice


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as stat:
            # Sin un init que los recoja (contenedores de CI), un proceso ya muerto queda como zombi (Z).
            return stat.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


@unittest.skipIf(sys.platform == "win32", "Comprueba el grupo de procesos de POSIX")
class LibreOfficeTimeoutTests(unittest.TestCase):
    def test_a_timeout_kills_the_child_started_by_the_launcher(self):
        child = None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "child.pid"
            # Como «soffice»: un lanzador que arranca a otro proceso, el verdadero trabajador, y espera.
            launcher = root / "fake_soffice.py"
            launcher.write_text(
                "import subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
                "time.sleep(30)\n", encoding="utf-8")
            docx = root / "entrega.docx"
            docx.write_bytes(b"PK")
            try:
                started = time.monotonic()
                with patch("moodle_tasks.document.user_cache_dir", return_value=root / "cache"):
                    with self.assertRaisesRegex(RuntimeError, "a tiempo"):
                        export_with_libreoffice([sys.executable, str(launcher)], docx, root, timeout=2)
                # Matar solo el lanzador dejaba la lectura de las tuberías esperando al hijo hasta que terminara solo.
                self.assertLess(time.monotonic() - started, 15)
                child = int(pid_file.read_text())
                deadline = time.monotonic() + 5
                while alive(child) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(alive(child), "El proceso hijo de LibreOffice siguió vivo tras el tiempo límite.")
            finally:
                if child and alive(child):
                    os.kill(child, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
