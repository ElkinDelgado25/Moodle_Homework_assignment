import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

import helpers  # noqa: F401 - aísla las pruebas de la configuración real
from moodle_tasks.config import load_config


class ConfigTests(unittest.TestCase):
    def test_explicit_env_file_works_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text("MOODLE_URL=https://moodle.test/\nMOODLE_USERNAME=test\nMOODLE_PASSWORD=test\n")
            config = load_config(path)
            self.assertEqual(config.base_url, "https://moodle.test")
            self.assertEqual(config.username, "test")

    def test_environment_has_priority_and_file_is_reloaded(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"MOODLE_USERNAME": "override"}, clear=True):
            path = Path(directory) / ".env"
            path.write_text("MOODLE_URL=https://moodle.test\nMOODLE_USERNAME=file\nMOODLE_PASSWORD=first\n")
            self.assertEqual(load_config(path).username, "override")
            path.write_text("MOODLE_URL=https://moodle.test\nMOODLE_PASSWORD=second\n")
            self.assertEqual(load_config(path).password, "second")

    def test_the_credentials_file_is_read_once(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text("MOODLE_URL=https://moodle.test\nMOODLE_USERNAME=test\nMOODLE_PASSWORD=test\n")
            with patch("moodle_tasks.config.dotenv_values", wraps=dotenv_values) as read:
                load_config(path)
            self.assertEqual(read.call_count, 1)

    def test_the_session_cache_opt_out_in_the_file_wins_over_the_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"MOODLE_SESSION_CACHE": "true"}, clear=True):
            path = Path(directory) / ".env"
            path.write_text("MOODLE_URL=https://moodle.test\nMOODLE_USERNAME=test\nMOODLE_PASSWORD=test\n"
                            "MOODLE_SESSION_CACHE=false\n")
            self.assertFalse(load_config(path).session_cache)
