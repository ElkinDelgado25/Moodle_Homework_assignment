import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

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

    def test_saving_credentials_keeps_the_other_user_options(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "credentials.env"
            path.write_text("MOODLE_URL='https://old.test'\nMOODLE_SESSION_CACHE='false'\n"
                            "SENTRY_ENVIRONMENT='staging'\nSENTRY_DSN='https://key@sentry.test/1'\n", encoding="utf-8")
            save_credentials(path, "https://moodle.test", "test", "secret")
            values = dotenv_values(path)
            self.assertEqual(values["MOODLE_URL"], "https://moodle.test")
            self.assertEqual(values["MOODLE_PASSWORD"], "secret")
            self.assertEqual(values["MOODLE_SESSION_CACHE"], "false")
            self.assertEqual(values["SENTRY_ENVIRONMENT"], "staging")
            self.assertEqual(values["SENTRY_DSN"], "https://key@sentry.test/1")
            self.assertEqual(list(values).count("MOODLE_URL"), 1)

    def test_personal_config_takes_priority_over_development_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "credentials.env"
            save_credentials(path, "https://moodle.test", "test", "test")
            with patch("moodle_tasks.storage.user_config_dir", return_value=root):
                self.assertEqual(default_env_file(), path)
