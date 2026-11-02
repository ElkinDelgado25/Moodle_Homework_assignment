import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from moodle_tasks.paths import UnsafePathError, check_upload_file, resolve_destination_directory
from moodle_tasks.uploads import preflight_result

from helpers import make_docx, make_pdf


class UploadSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config_dir = self.root / "config" / "moodle-homework-assignment"
        self.config_dir.mkdir(parents=True)
        self.credentials = self.config_dir / "credentials.env"
        self.credentials.write_text("MOODLE_PASSWORD=secreto\n")
        for target in ("moodle_tasks.paths.user_config_dir",):
            patcher = patch(target, return_value=self.config_dir)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("moodle_tasks.paths.default_env_file", return_value=self.credentials)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("moodle_tasks.paths.user_cache_dir", return_value=self.root / "cache")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.work = self.root / "entrega"
        self.work.mkdir()

    def rejected(self, raw: str) -> str:
        with self.assertRaises((ValueError, OSError)) as caught:
            check_upload_file(raw)
        return str(caught.exception)

    def test_valid_docx_and_pdf_are_accepted(self):
        docx = make_docx(self.work / "Informe final.docx")
        pdf = make_pdf(self.work / "Informe final.pdf")
        self.assertEqual(check_upload_file(str(docx)), docx.resolve())
        self.assertEqual(check_upload_file(str(pdf)), pdf.resolve())
        self.assertIsNone(preflight_result(1, [str(docx), str(pdf)]))

    def test_credentials_and_config_directory_are_rejected(self):
        self.assertIn("configuración", self.rejected(str(self.credentials)))
        other = self.config_dir / "session.json"
        other.write_text("{}")
        self.assertIn("configuración", self.rejected(str(other)))

    def test_symlink_to_credentials_is_rejected_by_its_target(self):
        link = self.work / "entrega.txt"
        link.symlink_to(self.credentials)
        self.assertIn("configuración", self.rejected(str(link)))

    def test_traversal_into_protected_paths_is_rejected(self):
        traversal = str(self.work / ".." / "config" / "moodle-homework-assignment" / "credentials.env")
        self.assertIn("configuración", self.rejected(traversal))

    @unittest.skipIf(os.name == "nt", "Rutas del sistema de Unix")
    def test_system_files_are_rejected(self):
        for raw in ("/proc/self/environ", "/etc/hostname", "/dev/null", "/sys/kernel/notes"):
            self.assertIsInstance(self.rejected(raw), str, raw)

    def test_hidden_files_and_folders_are_rejected(self):
        hidden_dir = self.work / ".ssh"
        hidden_dir.mkdir()
        key = hidden_dir / "id_rsa.txt"
        key.write_text("clave")
        self.assertIn("oculta", self.rejected(str(key)))
        dotfile = self.work / ".bashrc.txt"
        dotfile.write_text("x")
        self.assertIn("oculta", self.rejected(str(dotfile)))

    def test_relative_empty_and_nul_paths_are_rejected(self):
        for raw in ("entrega.pdf", "", "   ", "/tmp/a\x00b.pdf"):
            self.assertIsInstance(self.rejected(raw), str, repr(raw))

    def test_type_size_and_signature_are_checked(self):
        empty = self.work / "vacio.pdf"
        empty.write_bytes(b"")
        self.assertIn("vacío", self.rejected(str(empty)))
        fake = self.work / "falso.docx"
        fake.write_bytes(b"no es un zip")
        self.assertIn("válido", self.rejected(str(fake)))
        fake_pdf = self.work / "falso.pdf"
        fake_pdf.write_bytes(b"<html>login</html>")
        self.assertIn("válido", self.rejected(str(fake_pdf)))
        script = self.work / "instalar.exe"
        script.write_bytes(b"MZ")
        self.assertIn("no es un formato", self.rejected(str(script)))
        no_suffix = self.work / "README"
        no_suffix.write_text("x")
        self.assertIn("sin extensión", self.rejected(str(no_suffix)))
        self.assertIn("no existe", self.rejected(str(self.work / "falta.pdf")))
        self.assertIn("archivo legible", self.rejected(str(self.work)))

    def test_size_limit(self):
        large = self.work / "grande.txt"
        with large.open("wb") as handle:
            handle.truncate(100 * 1024 * 1024 + 1)
        self.assertIn("100 MB", self.rejected(str(large)))

    def test_unicode_and_spaces_in_names_are_accepted(self):
        path = make_pdf(self.work / "Práctica Nº 3 — análisis 😀.pdf")
        self.assertEqual(check_upload_file(str(path)), path.resolve())

    def test_preflight_blocks_the_whole_call_and_reports_each_file(self):
        good = make_pdf(self.work / "a.pdf")
        result = preflight_result(7, [str(good), str(self.credentials), str(good)])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["uploaded_files"], [])
        statuses = [item["status"] for item in result["files"]]
        self.assertIn("not_uploaded", statuses)
        self.assertEqual(statuses.count("failed"), 2)
        self.assertTrue(any("configuración" in error for error in result["errors"]))
        self.assertTrue(any("más de una vez" in error for error in result["errors"]))
        self.assertEqual(preflight_result(7, [])["status"], "blocked")

    def test_upload_tool_validates_before_launching_the_browser(self):
        from moodle_tasks.server import create_server
        from moodle_tasks.main import Config
        import asyncio
        from mcp import Client

        async def run():
            settings = Config("https://moodle.test", "u", "p", True)
            with patch("moodle_tasks.server.load_config", return_value=settings), \
                    patch("moodle_tasks.server.sync_playwright", side_effect=AssertionError("no debe abrir Chromium")):
                async with Client(create_server()) as client:
                    return await client.call_tool("upload_assignment_files",
                                                  {"assignment_id": 3, "file_paths": [str(self.credentials)]})

        result = asyncio.run(run())
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["status"], "blocked")

    def test_destination_directory_rules(self):
        self.assertEqual(resolve_destination_directory(str(self.work)), self.work.resolve())
        with self.assertRaises(ValueError):
            resolve_destination_directory("Entregas")
        with self.assertRaises(UnsafePathError):
            resolve_destination_directory(str(self.config_dir))
        file_destination = make_pdf(self.work / "x.pdf")
        with self.assertRaises(ValueError):
            resolve_destination_directory(str(file_destination))
        with self.assertRaises(UnsafePathError):
            resolve_destination_directory(str(self.work / ".oculta"))


if __name__ == "__main__":
    unittest.main()
