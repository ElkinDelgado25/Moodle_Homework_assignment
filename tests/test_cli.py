import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from moodle_tasks.cli import main


class CLITests(unittest.TestCase):
    def test_run_opens_interactive_setup_instead_of_stdio_server(self):
        with patch("moodle_tasks.cli.setup.main") as setup, patch("moodle_tasks.cli.server.main") as server:
            main(["run", "--agent", "codex"])
            setup.assert_called_once_with(["--agent", "codex"])
            server.assert_not_called()

    def test_serve_forwards_the_credentials_path_without_running_setup(self):
        with patch("moodle_tasks.cli.server.main") as server, patch("moodle_tasks.cli.setup.main") as setup:
            main(["serve", "--env-file", "/tmp/credentials.env"])
            server.assert_called_once_with(["--env-file", "/tmp/credentials.env"])
            setup.assert_not_called()

    def test_tasks_runs_the_terminal_consultation(self):
        with patch("moodle_tasks.cli.tasks.main") as tasks:
            main(["tasks"])
            tasks.assert_called_once_with()

    def test_no_subcommand_displays_help(self):
        output = io.StringIO()
        with redirect_stdout(output):
            main([])
        self.assertIn("mcp-moodle", output.getvalue())
        self.assertIn("run", output.getvalue())
