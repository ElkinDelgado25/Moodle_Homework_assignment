import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import helpers  # noqa: F401 - aísla las pruebas de la configuración real
from moodle_tasks import cli, server


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


if __name__ == "__main__":
    unittest.main()
