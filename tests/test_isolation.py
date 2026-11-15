import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import helpers
from moodle_tasks.storage import user_cache_dir, user_config_dir


class TestIsolationTests(unittest.TestCase):
    def test_every_test_module_loads_the_common_bootstrap(self):
        imports_helpers = re.compile(r"^(import helpers\b|from helpers import )", re.MULTILINE)
        missing = [path.name for path in sorted(Path(__file__).parent.glob("test_*.py"))
                   if not imports_helpers.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(missing, [])

    def test_personal_folders_point_to_the_temporary_home(self):
        for environment in (dict(os.environ), {}):
            with self.subTest(cleared=not environment), patch.dict(os.environ, environment, clear=True):
                for path in (user_config_dir(), user_cache_dir()):
                    self.assertTrue(path.resolve().is_relative_to(helpers.TEST_HOME), path)


if __name__ == "__main__":
    unittest.main()
