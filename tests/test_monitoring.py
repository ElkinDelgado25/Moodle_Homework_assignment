import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import helpers  # noqa: F401 - aísla las pruebas de la configuración real
from moodle_tasks import cli, monitoring, server


class SentryInitializationTests(unittest.TestCase):
    def test_serve_starts_sentry_with_the_env_file_it_was_given(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env_file = Path(directory) / "otro-perfil.env"
            env_file.write_text("SENTRY_DSN='https://perfil@sentry.test/2'\n", encoding="utf-8")
            with patch("moodle_tasks.monitoring.initialize_sentry") as initialize, \
                    patch.object(server, "create_server", return_value=MagicMock()):
                server.main(["--env-file", str(env_file)])
        initialize.assert_called_once()
        self.assertEqual(initialize.call_args.args[0]["SENTRY_DSN"], "https://perfil@sentry.test/2")

    def test_the_cli_leaves_serve_to_start_sentry_with_its_own_arguments(self):
        with patch("moodle_tasks.cli.initialize_sentry") as initialize, patch.object(cli.server, "main") as serve:
            cli.main(["serve", "--env-file", "/tmp/perfil.env"])
        initialize.assert_not_called()
        serve.assert_called_once_with(["--env-file", "/tmp/perfil.env"])

    def test_the_cli_starts_sentry_once_for_the_other_commands(self):
        with patch("moodle_tasks.cli.initialize_sentry") as initialize, patch.object(cli.status, "main"):
            cli.main(["status"])
        initialize.assert_called_once()


class SentryScrubbingTests(unittest.TestCase):
    def before_send(self, values):
        with patch.object(monitoring, "_initialized", False), patch("sentry_sdk.init") as init:
            monitoring.initialize_sentry(values)
        init.assert_called_once()
        return init.call_args.kwargs["before_send"]

    def test_exception_and_log_messages_never_carry_the_credentials(self):
        before_send = self.before_send({"SENTRY_DSN": "https://key@sentry.test/1",
                                        "MOODLE_USERNAME": "estudiante@uleam.edu.ec",
                                        "MOODLE_PASSWORD": "Clave-Secreta%9"})
        pair = base64.b64encode(b"estudiante@uleam.edu.ec:Clave-Secreta%9").decode()
        event = {
            "exception": {"values": [{"type": "RuntimeError",
                                      "value": "login https://moodle.test/?u=estudiante%40uleam.edu.ec&p=Clave-Secreta%259 falló",
                                      "stacktrace": {"frames": [{"function": "login"}]}}]},
            "logentry": {"message": "Authorization: Basic %s", "params": [pair]},
            "message": "contraseña Clave-Secreta%9",
            "extra": {"detalle": ("ESTUDIANTE@ULEAM.EDU.EC",)},
            "request": {"data": "Clave-Secreta%9"}, "user": {"email": "estudiante@uleam.edu.ec"},
            "level": "error",
        }
        scrubbed = before_send(event, {})
        text = str(scrubbed)
        for secret in ("Clave-Secreta", "estudiante", "ESTUDIANTE", pair):
            self.assertNotIn(secret, text)
        self.assertNotIn("request", scrubbed)
        self.assertNotIn("user", scrubbed)
        self.assertEqual(scrubbed["level"], "error")
        self.assertEqual(scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]["function"], "login")
        self.assertIn("[oculto]", scrubbed["exception"]["values"][0]["value"])

    def test_events_without_configured_credentials_are_kept(self):
        before_send = self.before_send({"SENTRY_DSN": "https://key@sentry.test/1"})
        event = {"exception": {"values": [{"value": "Tiempo de espera agotado"}]}, "contexts": {"os": {}}}
        self.assertEqual(before_send(event, {}), {"exception": {"values": [{"value": "Tiempo de espera agotado"}]}})


if __name__ == "__main__":
    unittest.main()
