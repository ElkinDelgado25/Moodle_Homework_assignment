import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from moodle_tasks.errors import MoodleAuthenticationError, MoodleHTTPError
from moodle_tasks.main import load_config
from moodle_tasks.setup import main, valid_username
from moodle_tasks.storage import save_credentials


class SetupTests(unittest.TestCase):
    def test_validate_saved_account_preserves_credentials_and_agents(self):
        failures = (
            None,
            MoodleAuthenticationError("Credenciales rechazadas"),
            MoodleHTTPError(502, "https://custom.moodle.test"),
            PlaywrightTimeoutError("Moodle tardó demasiado"),
            RuntimeError("Error con saved-password"),
        )
        for failure in failures:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "account/credentials.env"
                save_credentials(path, "https://custom.moodle.test", "saved", "saved-password")
                before = path.read_bytes()
                agent_path = root / "agent.json"
                agent_path.write_text('{"existing": true}')
                agent_before = agent_path.read_bytes()
                output = io.StringIO()
                with patch("moodle_tasks.setup.prepare_browser"), patch("builtins.input", return_value="4"), patch.dict(os.environ, {}, clear=True), patch("moodle_tasks.setup.ask_account") as account, patch("moodle_tasks.setup.ask_agent") as agent, patch("moodle_tasks.setup.register_agent") as register, patch("moodle_tasks.status.verify_credentials", side_effect=failure) as verify, redirect_stdout(output):
                    arguments = ["--config-dir", str(path.parent), "--agent-config", str(agent_path)]
                    if failure:
                        with self.assertRaises(SystemExit) as caught:
                            main(arguments)
                        self.assertEqual(caught.exception.code, 1)
                    else:
                        main(arguments)
                account.assert_not_called()
                agent.assert_not_called()
                register.assert_not_called()
                verify.assert_called_once()
                config = verify.call_args.args[0]
                self.assertEqual(config.base_url, "https://custom.moodle.test")
                self.assertEqual(config.username, "saved")
                self.assertEqual(config.password, "saved-password")
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(agent_path.read_bytes(), agent_before)
                self.assertNotIn("saved-password", output.getvalue())
                self.assertIn("Validar cuenta", output.getvalue())
                self.assertIn("Con problemas" if failure else "Conectado", output.getvalue())

    def test_exit_from_saved_account_menu_preserves_credentials_and_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "account/credentials.env"
            save_credentials(path, "https://moodle.test", "saved", "saved-password")
            before = path.read_bytes()
            with patch("moodle_tasks.setup.ask_account") as account, patch("moodle_tasks.setup.register_agent") as register:
                output = self.run_wizard(root, ["3"], [])
            account.assert_not_called()
            register.assert_not_called()
            self.assertEqual(path.read_bytes(), before)
            self.assertIn("Tu configuración se conserva", output)

    def test_saved_account_menu_can_register_another_agent_without_asking_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "account/credentials.env"
            save_credentials(path, "https://moodle.test", "saved", "saved-password")
            before = path.read_bytes()
            with patch("moodle_tasks.setup.ask_account") as account:
                self.run_wizard(root, ["2", "3"], [])
            account.assert_not_called()
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue((root / "agent.json").is_file())

    def test_change_credentials_preserves_moodle_url_and_does_not_ask_for_an_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "account/credentials.env"
            save_credentials(path, "https://custom.moodle.test", "saved", "saved-password")
            with patch("moodle_tasks.setup.ask_agent") as agent:
                output = self.run_wizard(root, ["1", "updated"], [None])
            agent.assert_not_called()
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
            self.assertEqual(config.username, "updated")
            self.assertEqual(config.base_url, "https://custom.moodle.test")
            self.assertIn("Credenciales actualizadas", output)
            self.assertFalse((root / "agent.json").exists())

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
            self.assertIn("Conectado", output)
            self.assertTrue((root / "agent.json").is_file())

    def test_502_allows_setup_but_does_not_claim_credentials_are_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = self.run_wizard(root, ["student", "4"], [MoodleHTTPError(502, "https://moodle.test")])
            self.assertIn("validación de la cuenta está pendiente", output)
            self.assertNotIn("Cuenta verificada correctamente", output)
            self.assertIn("Con problemas", output)
            self.assertIn("Tu cuenta quedó guardada", output)
            self.assertIn("mcp-moodle status", output)
            self.assertTrue((root / "agent.json").is_file())

    def test_browser_preparation_finishes_before_showing_cover_and_asking_account(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = []
            def ask_account(_url):
                events.append("account")
                raise EOFError()

            with patch("moodle_tasks.setup.prepare_browser", side_effect=lambda *_: events.append("prepare")), patch("moodle_tasks.setup.show_dashboard", side_effect=lambda *_args, **_kwargs: events.append("cover")), patch("moodle_tasks.setup.ask_account", side_effect=ask_account), redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                main(["--config-dir", str(root)])
            self.assertEqual(events, ["prepare", "cover", "account"])

    def test_pending_account_survives_cancellation_at_agent_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def select_agent():
                # The account must already be on disk while the menu is open.
                self.assertEqual(load_config(root / "account/credentials.env").username, "student")
                raise EOFError()

            with patch("moodle_tasks.setup.ask_agent", side_effect=select_agent), self.assertRaises(SystemExit) as caught:
                self.run_wizard(root, ["student"], [MoodleHTTPError(502, "https://moodle.test")])
            self.assertEqual(caught.exception.code, 130)
            self.assertFalse((root / "agent.json").exists())

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
