"""Batería fuera de rango con entradas aleatorias reproducibles (semillas fijas, solo biblioteca estándar)."""

import os
import random
import tempfile
import unicodedata
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

import helpers  # noqa: F401 - desactiva la caché de sesión
from moodle_tasks.document import MissingCoverFields, build_docx, cover_values, safe_file_name
from moodle_tasks.document_model import TEMPLATE_TOKEN, CoverFields, DeliveryDocument, parse_inline
from moodle_tasks.downloads import attachment_name
from moodle_tasks.paths import UnsafePathError, check_upload_file, resolve_destination_directory
from moodle_tasks.uploads import moodle_name
from moodle_tasks.urls import assignment_view_id, parse_id

ALPHABET = (
    "abcXYZ019 _-.,;:/\\?&=#%+~*[]()<>\"'`|!@$^{}\n\t\r"
    "\x00\x01\x0b\x1f\x7fñÑáé😀\u202e\u200b\u2066\ufeff５١² 　"
)
URL_PARTS = ["https://", "http://", "HTTPS://", "javascript:", "file://", "ftp://", "", "//"]
HOSTS = ["moodle.test", "MOODLE.test", "moodle.test:443", "moodle.test:8443", "otro.test", "user@moodle.test",
         "[::1]", "127.0.0.1", "xn--mdle-0qa.test", ""]
PATHS = ["/mod/assign/view.php", "/MOD/assign/view.php", "/mod/assign/view.php/", "/moodle/mod/assign/view.php",
         "/mod/url/view.php", "/mod/assign/%2e%2e/view.php", "/mod/assign/view.php;x", ""]
IDS = ["1", "42", "0", "-1", "+5", " 5", "5 ", "1_000", "0x1f", "1e3", "５", "١٢", "²", "9" * 19,
       "9223372036854775807", "9223372036854775808", "", "abc", "5&id=6"]


def random_text(rng: random.Random, length: int) -> str:
    return "".join(rng.choice(ALPHABET) for _ in range(length))


class OutOfRangeTests(unittest.TestCase):
    def test_ids(self):
        rng = random.Random(1)
        values = [True, False, None, 0, -1, 1, 2**63 - 1, 2**63, 1.0, 1.5, float("nan"), [], {}, b"1", *IDS]
        values += [random_text(rng, rng.randint(0, 12)) for _ in range(400)]
        for value in values:
            result = parse_id(value)
            if result is not None:
                self.assertIsInstance(result, int, repr(value))
                self.assertGreaterEqual(result, 1)
                self.assertLessEqual(result, 2**63 - 1)
                self.assertNotIsInstance(value, bool)
                if isinstance(value, str):
                    self.assertTrue(value.isascii() and value.isdigit(), repr(value))

    def test_assignment_urls(self):
        rng = random.Random(2)
        base = "https://moodle.test"
        for _ in range(600):
            url = (rng.choice(URL_PARTS) + rng.choice(HOSTS) + rng.choice(PATHS) + "?" +
                   rng.choice(["id=", "ID=", "id[]=", ""]) + rng.choice(IDS) + rng.choice(["", "#f", "&x=1", "&id=2"]))
            if rng.random() < 0.2:
                url += random_text(rng, rng.randint(1, 20))
            identifier = assignment_view_id(url, base)
            if identifier is not None:
                self.assertTrue(url.lower().startswith("https://moodle.test"), url)
                self.assertNotIn("@", url.split("?")[0])
                self.assertIn(f"id={identifier}", url)

    def test_paths_never_escape_into_protected_locations(self):
        rng = random.Random(3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.mkdir()
            secret = config / "credentials.env"
            secret.write_text("MOODLE_PASSWORD=x")
            (root / "ok").mkdir()
            good = helpers.make_pdf(root / "ok" / "entrega.pdf")
            try:
                (root / "ok" / "enlace.pdf").symlink_to(secret)
            except OSError:
                pass  # Windows sin privilegios para crear enlaces simbólicos
            fragments = ["..", ".", "config", "credentials.env", "ok", "entrega.pdf", "enlace.pdf", ".ssh", "~",
                         "/etc/passwd", "/proc/self/environ", "/dev/zero", "\x00", "a" * 300, "ñ😀", "\u202e"]
            with patch("moodle_tasks.paths.user_config_dir", return_value=config), \
                    patch("moodle_tasks.paths.default_env_file", return_value=secret), \
                    patch("moodle_tasks.paths.user_cache_dir", return_value=root / "cache"):
                accepted = 0
                for _ in range(500):
                    parts = [rng.choice(fragments) for _ in range(rng.randint(1, 5))]
                    raw = rng.choice([str(root) + "/", "", "/", "~/"]) + "/".join(parts)
                    for function in (check_upload_file, resolve_destination_directory):
                        try:
                            path = function(raw)
                        except (ValueError, OSError):
                            continue
                        accepted += 1
                        real = Path(os.path.realpath(path))
                        self.assertFalse(str(real).startswith(str(config)), raw)
                        self.assertFalse(str(real).startswith(("/proc", "/etc", "/dev", "/sys")), raw)
                        self.assertFalse(any(part.startswith(".") for part in real.relative_to("/").parts if part not in (".", "..")), raw)
                self.assertEqual(check_upload_file(str(good)), good.resolve())
                self.assertGreater(accepted, 0)

    def test_names_are_safe_and_stable(self):
        rng = random.Random(4)
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
        for _ in range(500):
            raw = random_text(rng, rng.randint(0, 400))
            for name in (attachment_name("https://m.test/pluginfile.php/1/" + raw.replace("/", "%2F").replace("?", "%3F").replace("#", "%23")),
                         safe_file_name(raw)):
                self.assertTrue(name)
                self.assertFalse(any(character in name for character in '/\\:*?"<>|\x00'), repr(name))
                self.assertFalse(any(unicodedata.category(c) in ("Cc", "Cf") for c in name), repr(name))
                self.assertLessEqual(len(name.encode("utf-8")), 200)
                self.assertNotIn(name.split(".", 1)[0].upper(), reserved)
                self.assertFalse(name.startswith((" ", ".")) or name.endswith((" ", ".")), repr(name))
            self.assertEqual(safe_file_name(safe_file_name(raw)), safe_file_name(raw))
            self.assertEqual(moodle_name(moodle_name(raw)), moodle_name(raw))

    def test_inline_markup_never_crashes(self):
        rng = random.Random(5)
        pieces = ["**", "*", "***", "[", "]", "(", ")", "\\", "https://", "github.com/a/b", "texto", " ", "](", "javascript:"]
        for _ in range(800):
            text = "".join(rng.choice(pieces + [random_text(rng, 3)]) for _ in range(rng.randint(1, 30)))
            try:
                segments = parse_inline(text)
            except ValueError:
                continue
            for segment in segments:
                if segment["link"]:
                    self.assertTrue(segment["link"].startswith(("http://", "https://")), text)

    def test_random_cover_and_content_produce_valid_documents(self):
        rng = random.Random(6)
        with tempfile.TemporaryDirectory() as directory:
            for index in range(25):
                fields = {name: random_text(rng, rng.randint(0, 60)) for name in
                          ("subject", "teacher", "student_1", "student_2", "degree", "class_group", "year")}
                try:
                    cover = CoverFields(**fields)
                    document = DeliveryDocument(title=random_text(rng, rng.randint(1, 80)) + "x",
                                                blocks=[{"type": "paragraph", "text": random_text(rng, rng.randint(1, 500)) + "x"},
                                                        {"type": "bullets", "items": [random_text(rng, 30) + "x"]}])
                    values = cover_values(cover, {"student_1": "Estudiante"})
                except (ValidationError, MissingCoverFields, ValueError):
                    continue
                output = Path(directory) / f"{index}.docx"
                build_docx(document, values, output)
                with zipfile.ZipFile(output) as archive:
                    self.assertIsNone(archive.testzip())
                    xml = archive.read("word/document.xml").decode("utf-8")
                    self.assertIsNone(TEMPLATE_TOKEN.search(xml))
                    self.assertNotIn("\u202e", xml)


if __name__ == "__main__":
    unittest.main()
