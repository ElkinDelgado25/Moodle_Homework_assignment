import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from moodle_tasks.errors import MoodleAuthenticationError, MoodleHTTPError
from moodle_tasks.main import load_config
from moodle_tasks.setup import main, valid_username


class SetupTests(unittest.TestCase):
    def test_username_validation(self):
        self.assertTrue(valid_username("student"))
        self.assertTrue(valid_username("student@example.edu"))
        for username in ("", "student name", "student@", "student@@example.edu"):
            self.assertFalse(valid_username(username))

    def run_wizard(self, root, responses, checks):
        output = io.StringIO()
        with patch("moodle_tasks.setup.prepare_browser"), patch("builtins.input", side_effect=responses), patch("moodle_tasks.setup.getpass.getpass", return_value="private-password"), patch("moodle_tasks.setup.verify_credentials", side_effect=checks), patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
            main(["--config-dir", str(root / "account"), "--agent-config", str(root / "agent.json")])
        self.assertNotIn("private-password", output.getvalue())
        return output.getvalue()

    def test_invalid_credentials_are_retried_before_registering_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self.run_wizard(root, ["first", "correct", "2"], [MoodleAuthenticationError("Rechazado"), None])
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(load_config(root / "account/credentials.env").username, "correct")
            self.assertIn("Cuenta verificada correctamente", output)
            self.assertTrue((root / "agent.json").is_file())

    def test_502_allows_setup_but_does_not_claim_credentials_are_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self.run_wizard(root, ["student", "4"], [MoodleHTTPError(502, "https://moodle.test")])
            self.assertIn("validación de la cuenta está pendiente", output)
            self.assertNotIn("Cuenta verificada correctamente", output)
            self.assertTrue((root / "agent.json").is_file())

    def test_repeated_invalid_credentials_do_not_save_or_register(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                self.run_wizard(root, ["student"] * 3, [MoodleAuthenticationError("Rechazado")] * 3)
            self.assertEqual(caught.exception.code, 1)
            self.assertFalse((root / "account/credentials.env").exists())
            self.assertFalse((root / "agent.json").exists())

    def test_connect_only_reuses_credentials_without_questions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "credentials.env").write_text("MOODLE_USERNAME=test\n")
            with patch("builtins.input") as ask, patch("moodle_tasks.setup.prepare_browser") as browser, redirect_stdout(io.StringIO()):
                main(["--connect-only", "--agent", "antigravity", "--config-dir", str(root), "--agent-config", str(root / "agent.json")])
            ask.assert_not_called()
            browser.assert_not_called()
            self.assertTrue((root / "agent.json").is_file())
