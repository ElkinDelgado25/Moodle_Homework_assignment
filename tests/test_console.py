import io
import unittest
from unittest.mock import patch

from rich.console import Console

from moodle_tasks import console


class ConsoleEncodingTests(unittest.TestCase):
    def legacy_streams(self):
        return (io.TextIOWrapper(io.BytesIO(), encoding="cp1252"),
                io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))

    def test_windows_streams_switch_to_utf8_and_print_arrows(self):
        stdout, stderr = self.legacy_streams()
        with patch.object(console.sys, "platform", "win32"), patch.object(console.sys, "stdout", stdout), \
                patch.object(console.sys, "stderr", stderr):
            console.configure_utf8_streams()
        self.assertEqual(stdout.encoding, "utf-8")
        self.assertEqual(stderr.encoding, "utf-8")
        Console(file=stdout, force_terminal=False).print("0.4.0 → 0.4.3")
        stdout.flush()
        self.assertIn("→".encode(), stdout.buffer.getvalue())

    def test_other_platforms_and_unusual_streams_are_left_alone(self):
        stdout, stderr = self.legacy_streams()
        with patch.object(console.sys, "platform", "linux"), patch.object(console.sys, "stdout", stdout), \
                patch.object(console.sys, "stderr", stderr):
            console.configure_utf8_streams()
        self.assertEqual(stdout.encoding, "cp1252")
        with patch.object(console.sys, "platform", "win32"), patch.object(console.sys, "stdout", object()), \
                patch.object(console.sys, "stderr", None):
            console.configure_utf8_streams()


if __name__ == "__main__":
    unittest.main()
