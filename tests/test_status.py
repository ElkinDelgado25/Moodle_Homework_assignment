import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import helpers  # noqa: F401 - aísla las pruebas de la configuración real
from moodle_tasks.errors import MoodleHTTPError
from moodle_tasks.status import main
from moodle_tasks.storage import save_credentials
from moodle_tasks.updates import UpdateStatus


class StatusTests(unittest.TestCase):
    def setUp(self):
        # status consulta la API de GitHub y guarda release-check.json: las pruebas no salen a la red.
        patcher = patch("moodle_tasks.status.check_for_updates", return_value=UpdateStatus("0.0.0"))
        self.check_for_updates = patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_checks_for_updates_without_contacting_github(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), \
                patch("moodle_tasks.updates.urlopen") as urlopen, redirect_stdout(io.StringIO()):
            main(["--env-file", str(Path(directory) / "missing.env")])
        self.check_for_updates.assert_called_once_with()
        urlopen.assert_not_called()

    def test_explicit_credentials_path_does_not_require_a_home_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "credentials.env"
            save_credentials(path, "https://moodle.test", "student", "private-password")
            with patch("pathlib.Path.home", side_effect=RuntimeError("No home directory")), patch("moodle_tasks.status.verify_credentials"), redirect_stdout(io.StringIO()):
                main(["--env-file", str(path)])

    def test_no_account_is_not_connected_and_does_not_consult_moodle(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            output = io.StringIO()
            with patch("moodle_tasks.status.verify_credentials") as verify, redirect_stdout(output):
                main(["--env-file", str(Path(directory) / "missing.env")])
            verify.assert_not_called()
            self.assertIn("Sin iniciar", output.getvalue())
            self.assertIn("Sin cuenta configurada", output.getvalue())

    def test_the_update_check_runs_while_moodle_is_verified(self):
        # Las dos consultas solapan: el estado no espera a GitHub y luego a Moodle una tras otra.
        import threading

        both_running = threading.Barrier(2, timeout=5)

        def slow_check():
            both_running.wait()
            return UpdateStatus("0.0.0")

        def slow_verify(config):
            both_running.wait()
            return {}

        self.check_for_updates.side_effect = slow_check
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "credentials.env"
            save_credentials(path, "https://moodle.test", "student", "private-password")
            output = io.StringIO()
            with patch("moodle_tasks.status.verify_credentials", side_effect=slow_verify), redirect_stdout(output):
                main(["--env-file", str(path)])
        self.assertIn("Conectado", output.getvalue())

    def test_connection_state_reflects_live_validation_and_never_shows_password(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "credentials.env"
            save_credentials(path, "https://moodle.test", "student@example.edu", "private-password")
            for failure, expected in ((None, "Conectado"), (MoodleHTTPError(502, "https://moodle.test"), "Con problemas")):
                with self.subTest(state=expected):
                    output = io.StringIO()
                    with patch("moodle_tasks.status.verify_credentials", side_effect=failure), redirect_stdout(output):
                        if failure:
                            with self.assertRaises(SystemExit) as caught:
                                main(["--env-file", str(path)])
                            self.assertEqual(caught.exception.code, 1)
                        else:
                            main(["--env-file", str(path)])
                    self.assertIn(expected, output.getvalue())
                    self.assertIn("student@example.edu", output.getvalue())
                    self.assertNotIn("private-password", output.getvalue())
