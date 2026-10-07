import unittest
from unittest.mock import patch

from moodle_tasks.system import describe_system


class SystemTests(unittest.TestCase):
    def test_arch_and_derivatives_are_recognized_from_os_release(self):
        for data, expected in (
            ({"ID": "cachyos", "ID_LIKE": "arch", "PRETTY_NAME": "CachyOS"}, "CachyOS (basado en Arch Linux)"),
            ({"ID": "arch", "PRETTY_NAME": "Arch Linux"}, "Arch Linux"),
            ({"ID": "ubuntu", "ID_LIKE": "debian", "PRETTY_NAME": "Ubuntu 24.04"}, "Ubuntu 24.04"),
        ):
            with self.subTest(system=data), patch("moodle_tasks.system.platform.system", return_value="Linux"), patch("moodle_tasks.system.platform.freedesktop_os_release", return_value=data):
                self.assertEqual(describe_system(), expected)

    def test_other_systems_and_missing_linux_metadata(self):
        with patch("moodle_tasks.system.platform.system", return_value="Windows"), patch("moodle_tasks.system.platform.release", return_value="11"):
            self.assertEqual(describe_system(), "Windows 11")
        with patch("moodle_tasks.system.platform.system", return_value="Darwin"):
            self.assertEqual(describe_system(), "macOS")
        with patch("moodle_tasks.system.platform.system", return_value="Linux"), patch("moodle_tasks.system.platform.freedesktop_os_release", side_effect=OSError):
            self.assertEqual(describe_system(), "Linux")
