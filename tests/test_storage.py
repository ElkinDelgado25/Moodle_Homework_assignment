import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from moodle_tasks.main import load_config
from moodle_tasks.storage import default_env_file, save_credentials


class StorageTests(unittest.TestCase):
    def test_password_characters_are_preserved_and_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "credentials.env"
            password = "quotes'\\\"${HOME}#=$"
            save_credentials(path, "https://moodle.test", "test", password)
            self.assertEqual(load_config(path).password, password)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_personal_config_takes_priority_over_development_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "credentials.env"
            save_credentials(path, "https://moodle.test", "test", "test")
            with patch("moodle_tasks.storage.user_config_dir", return_value=root):
                self.assertEqual(default_env_file(), path)
