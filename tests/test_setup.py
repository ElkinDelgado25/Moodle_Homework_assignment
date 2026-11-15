import io
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from rich.console import Console

import helpers  # noqa: F401 - aísla las pruebas de la configuración real
from moodle_tasks.agents import AGENTS, AgentDetection, AgentSyncResult
from moodle_tasks.errors import MoodleAuthenticationError, MoodleHTTPError
from moodle_tasks.main import Config, load_config
from moodle_tasks.setup import ask_agent, main, valid_username, verify_credentials
from moodle_tasks.storage import save_credentials


class VerifyCredentialsTests(unittest.TestCase):
    def test_login_uses_the_shared_page_without_the_saved_session(self):
        page, calls = MagicMock(), []

        @contextmanager
        def fake_moodle_page(config, **options):
            calls.append(options)
            yield MagicMock(), page

        config = Config("https://moodle.test", "student", "secret")
        with patch("moodle_tasks.setup.moodle_page", fake_moodle_page), \
                patch("moodle_tasks.setup.login") as login, \
                patch("moodle_tasks.setup.record_verified_profile", return_value={"student_1": "Ana", "courses": []}):
            identity = verify_credentials(config)
        self.assertEqual(calls, [{"fresh": True}])
        login.assert_called_once_with(page, config)
        self.assertEqual(identity["student_1"], "Ana")

    def test_a_profile_failure_does_not_cancel_the_verified_access(self):
        @contextmanager
        def fake_moodle_page(config, **options):
            yield MagicMock(), MagicMock()

        config = Config("https://moodle.test", "student", "secret")
        with patch("moodle_tasks.setup.moodle_page", fake_moodle_page), patch("moodle_tasks.setup.login"), \
                patch("moodle_tasks.setup.record_verified_profile", side_effect=RuntimeError("perfil")):
            self.assertEqual(verify_credentials(config), {"student_1": "", "courses": []})


class SetupTests(unittest.TestCase):
    def setUp(self):
        update = patch("moodle_tasks.setup.update_from_setup", return_value=False)
        update.start()
        self.addCleanup(update.stop)
        detection = patch("moodle_tasks.agents.detect_agents", return_value={
            agent: AgentDetection("No detectado") for agent in AGENTS
        })
        detection.start()
        self.addCleanup(detection.stop)

    def test_option_four_selects_cursor_and_the_prompt_includes_every_agent(self):
        prompts = []

        def fake_input(prompt):
            prompts.append(prompt)
            return "4"

        with patch("moodle_tasks.setup.show_agent_menu") as menu, patch(
            "moodle_tasks.setup.detect_agents", return_value={}
        ), patch("builtins.input", side_effect=fake_input):
            selected = ask_agent()
        self.assertEqual(selected, "cursor")
        self.assertEqual(prompts, [f"Selecciona una opción (1-{len(AGENTS)}): "])
        self.assertEqual(list(menu.call_args.args[0]), ["claude", "codex", "copilot", "cursor", "antigravity"])

    def test_updated_setup_continues_with_original_options_before_reading_account(self):
        arguments = ["--agent", "cursor", "--config-dir", "/tmp/account with spaces"]
        with patch("moodle_tasks.setup.update_from_setup", return_value=True), patch(
            "moodle_tasks.setup.continue_with_updated_setup"
        ) as continuation, patch("moodle_tasks.setup.ask_account") as account, patch(
            "moodle_tasks.setup.config_values"
        ) as values:
            main(arguments)
        continuation.assert_called_once_with(arguments)
        values.assert_not_called()
        account.assert_not_called()

    def test_sync_only_uses_saved_account_without_questions_and_can_skip_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_credentials(root / "credentials.env", "https://moodle.test", "saved", "secret")
            with patch("moodle_tasks.setup.update_from_setup") as update, patch(
                "moodle_tasks.setup.sync_agent_configurations"
            ) as sync, patch("moodle_tasks.setup.prepare_browser") as browser, patch("builtins.input") as ask:
                main(["--skip-update", "--sync-only", "--config-dir", str(root)])
            update.assert_not_called()
            sync.assert_called_once_with(root.resolve() / "credentials.env", selected_agent=None, selected_config=None)
            browser.assert_not_called()
            ask.assert_not_called()

    def test_after_update_syncs_before_saved_account_menu_even_when_user_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_credentials(root / "credentials.env", "https://moodle.test", "saved", "secret")
            events = []
            with patch("moodle_tasks.setup.prepare_browser", side_effect=lambda *_: events.append("browser")), patch(
                "moodle_tasks.setup.sync_agent_configurations", side_effect=lambda *_a, **_k: events.append("sync")
            ), patch("moodle_tasks.setup.ask_setup_action", side_effect=lambda: events.append("menu") or "4"), patch(
                "moodle_tasks.setup.show_dashboard"
            ), patch("moodle_tasks.setup.show_agent_menu"), redirect_stdout(io.StringIO()):
                main(["--skip-update", "--sync-after-update", "--config-dir", str(root)])
            self.assertEqual(events, ["browser", "sync", "menu"])

    def test_a_failing_agent_sync_after_an_update_does_not_stop_the_wizard(self):
        broken = next(iter(AGENTS))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_credentials(root / "credentials.env", "https://moodle.test", "saved", "secret")
            events, errors = [], io.StringIO()
            with patch("moodle_tasks.setup.prepare_browser"), patch(
                "moodle_tasks.setup.synchronize_agents",
                return_value=AgentSyncResult({}, {broken: "JSON inválido"}),
            ), patch("moodle_tasks.setup.ask_setup_action", side_effect=lambda: events.append("menu") or "4"), patch(
                "moodle_tasks.setup.show_dashboard"
            ), patch("moodle_tasks.setup.show_agent_menu"), redirect_stdout(io.StringIO()), redirect_stderr(errors):
                main(["--skip-update", "--sync-after-update", "--config-dir", str(root)])
            self.assertEqual(events, ["menu"])
            self.assertIn("JSON inválido", errors.getvalue())

    def test_sync_only_still_fails_when_an_agent_cannot_be_synchronized(self):
        broken = next(iter(AGENTS))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_credentials(root / "credentials.env", "https://moodle.test", "saved", "secret")
            with patch("moodle_tasks.setup.synchronize_agents", return_value=AgentSyncResult({}, {broken: "JSON inválido"})), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(["--skip-update", "--sync-only", "--config-dir", str(root)])
            self.assertEqual(caught.exception.code, 1)

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
                with patch("moodle_tasks.setup.prepare_browser"), patch("builtins.input", return_value="3"), patch.dict(os.environ, {}, clear=True), patch("moodle_tasks.setup.ask_account") as account, patch("moodle_tasks.setup.ask_agent") as agent, patch("moodle_tasks.setup.synchronize_agents") as register, patch("moodle_tasks.status.verify_credentials", side_effect=failure) as verify, redirect_stdout(output):
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

    def test_exit_is_the_last_option_of_the_saved_account_menu(self):
        from moodle_tasks.ui import show_setup_menu

        output = io.StringIO()
        with patch("moodle_tasks.ui.Console", side_effect=lambda: Console(file=output, width=100)):
            show_setup_menu()
        lines = [line.strip(" │") for line in output.getvalue().splitlines() if line.strip(" │")[:1].isdigit()]
        self.assertEqual(lines, ["1  Cambiar credenciales", "2  Configurar otro agente", "3  Validar cuenta", "4  Salir"])

    def test_exit_from_saved_account_menu_preserves_credentials_and_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "account/credentials.env"
            save_credentials(path, "https://moodle.test", "saved", "saved-password")
            before = path.read_bytes()
            with patch("moodle_tasks.setup.ask_account") as account, patch("moodle_tasks.setup.synchronize_agents") as register:
                output = self.run_wizard(root, ["4"], [])
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
