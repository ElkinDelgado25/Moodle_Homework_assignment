import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from moodle_tasks.setup import prepare_browser


class BrowserInstallTests(unittest.TestCase):
    def test_fallback_warnings_are_hidden_when_installation_succeeds(self):
        result = subprocess.CompletedProcess([], 0, "BEWARE: unsupported OS", "fallback build for ubuntu24.04-x64")
        output = io.StringIO()
        with patch("moodle_tasks.setup.subprocess.run", return_value=result) as run, redirect_stdout(output):
            prepare_browser()
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertIn("Chromium listo", output.getvalue())
        self.assertNotIn("BEWARE", output.getvalue())
        self.assertNotIn("fallback", output.getvalue())

    def test_real_failure_is_reported_and_diagnostics_are_preserved(self):
        result = subprocess.CompletedProcess([], 1, "Downloading chromium", "Download failed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("moodle_tasks.setup.subprocess.run", return_value=result), patch("moodle_tasks.setup.user_config_dir", return_value=root), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "No se pudo preparar Chromium"):
                    prepare_browser()
            log = (root / "browser-install.log").read_text()
            self.assertIn("Download failed", log)
            self.assertIn("Downloading chromium", log)
