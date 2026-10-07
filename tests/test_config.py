import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from moodle_tasks.main import load_config


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
