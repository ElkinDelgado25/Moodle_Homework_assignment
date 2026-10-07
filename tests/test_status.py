import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from moodle_tasks.errors import MoodleHTTPError
from moodle_tasks.status import main
from moodle_tasks.storage import save_credentials


class StatusTests(unittest.TestCase):
    def test_no_account_is_not_connected_and_does_not_consult_moodle(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            output = io.StringIO()
            with patch("moodle_tasks.status.verify_credentials") as verify, redirect_stdout(output):
                main(["--env-file", str(Path(directory) / "missing.env")])
            verify.assert_not_called()
            self.assertIn("Sin iniciar", output.getvalue())
            self.assertIn("Sin cuenta configurada", output.getvalue())

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
