import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from moodle_tasks import delivery
from moodle_tasks.delivery import cleanup_workspaces, copy_pair, finish_delivery, open_file, prepare_workspace
from moodle_tasks.verification import DocumentCheckError, check_delivery_pair, inspect_docx, inspect_pdf

from helpers import make_docx, make_pdf


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "trabajo"
        self.destination = self.root / "Documentos"
        self.source.mkdir()
        for target, value in (("moodle_tasks.storage.user_cache_dir", self.root / "cache"),
                              ("moodle_tasks.delivery.user_cache_dir", self.root / "cache"),
                              ("moodle_tasks.paths.user_cache_dir", self.root / "cache"),
                              ("moodle_tasks.paths.user_config_dir", self.root / "config")):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.opened = []
        patcher = patch("moodle_tasks.delivery.open_file", side_effect=lambda path: self.opened.append(path) or True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pair(self, stem="entrega", link=None):
        return make_docx(self.source / f"{stem}.docx", link=link), make_pdf(self.source / f"{stem}.pdf", link=link)

    def test_finish_copies_verified_files_and_opens_the_pdf(self):
        docx, pdf = self.pair(link="https://github.com/usuario/proyecto")
        result = finish_delivery(str(docx), str(pdf), str(self.destination))
        final_pdf = self.destination / "entrega.pdf"
        self.assertEqual(Path(result["pdf_path"]), final_pdf.resolve())
        self.assertEqual(Path(result["docx_path"]).read_bytes(), docx.read_bytes())
        self.assertTrue(result["opened"])
        self.assertEqual(self.opened, [final_pdf.resolve()])
        self.assertTrue(result["checks"]["ok"])
        self.assertEqual(result["checks"]["pages"], 2)
        self.assertEqual(result["checks"]["hyperlinks"], ["https://github.com/usuario/proyecto"])

    def test_existing_files_are_never_overwritten(self):
        self.destination.mkdir()
        (self.destination / "entrega.docx").write_bytes(b"version del usuario")
        docx, pdf = self.pair()
        result = finish_delivery(str(docx), str(pdf), str(self.destination), open_pdf=False)
        self.assertEqual((self.destination / "entrega.docx").read_bytes(), b"version del usuario")
        self.assertEqual(Path(result["docx_path"]).name, "entrega (1).docx")
        self.assertEqual(Path(result["pdf_path"]).name, "entrega (1).pdf")
        self.assertFalse(result["opened"])
        self.assertEqual(self.opened, [])

    @unittest.skipIf(os.name == "nt", "Crear enlaces simbólicos requiere privilegios en Windows")
    def test_symlink_in_destination_is_not_followed(self):
        self.destination.mkdir()
        victim = self.root / "victima.txt"
        victim.write_text("intacto")
        (self.destination / "entrega.pdf").symlink_to(victim)
        docx, pdf = self.pair()
        result = finish_delivery(str(docx), str(pdf), str(self.destination), open_pdf=False)
        self.assertEqual(victim.read_text(), "intacto")
        self.assertEqual(Path(result["pdf_path"]).name, "entrega (1).pdf")

    def test_copy_is_atomic_when_the_second_copy_fails(self):
        docx, pdf = self.pair()
        real_copy = delivery.shutil.copy2
        calls = []

        def failing(source, target):
            calls.append(source)
            if len(calls) == 2:
                raise OSError(28, "No space left on device")
            return real_copy(source, target)

        with patch("moodle_tasks.delivery.shutil.copy2", side_effect=failing):
            with self.assertRaises(OSError):
                copy_pair(docx, pdf, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_invalid_pairs_are_rejected(self):
        docx, pdf = self.pair()
        other_pdf = make_pdf(self.source / "otro.pdf")
        with self.assertRaises(DocumentCheckError):
            finish_delivery(str(docx), str(other_pdf), str(self.destination))
        junk = self.source / "basura.docx"
        junk.write_bytes(b"docx")
        junk_pdf = make_pdf(self.source / "basura.pdf")
        with self.assertRaises(DocumentCheckError):
            finish_delivery(str(junk), str(junk_pdf), str(self.destination))
        fake_pdf = self.source / "entrega2.pdf"
        fake_pdf.write_bytes(b"pdf")
        make_docx(self.source / "entrega2.docx")
        with self.assertRaises(DocumentCheckError):
            finish_delivery(str(self.source / "entrega2.docx"), str(fake_pdf), str(self.destination))
        with self.assertRaises(ValueError):
            finish_delivery(str(pdf), str(docx), str(self.destination))
        with self.assertRaises(ValueError):
            finish_delivery(str(docx), str(pdf), "Entregas")
        self.assertFalse(self.destination.exists())

    def test_unfilled_placeholders_block_the_delivery(self):
        docx = make_docx(self.source / "portada.docx", text="Docente: {{teacher}}")
        pdf = make_pdf(self.source / "portada.pdf")
        with self.assertRaises(DocumentCheckError) as caught:
            finish_delivery(str(docx), str(pdf), str(self.destination))
        self.assertIn("{{teacher}}", str(caught.exception))

    def test_missing_pdf_link_and_stale_pdf_are_warnings(self):
        docx, _ = self.pair(link="https://github.com/a/b")
        pdf = make_pdf(self.source / "entrega.pdf")
        old = time.time() - 3600
        os.utime(pdf, (old, old))
        checks = check_delivery_pair(docx, pdf)
        self.assertTrue(checks["ok"])
        self.assertTrue(any("anterior" in warning for warning in checks["warnings"]))
        self.assertTrue(any("https://github.com/a/b" in warning for warning in checks["warnings"]))

    def test_inspectors_report_damaged_files(self):
        broken = self.source / "roto.docx"
        broken.write_bytes(b"PK\x03\x04roto")
        with self.assertRaises(DocumentCheckError):
            inspect_docx(broken)
        truncated = self.source / "corto.pdf"
        truncated.write_bytes(b"%PDF-1.7\n")
        with self.assertRaises(DocumentCheckError):
            inspect_pdf(truncated)

    def test_workspace_lives_in_the_app_cache_and_old_ones_are_removed(self):
        directory = prepare_workspace()
        self.assertTrue(directory.is_dir())
        self.assertTrue(directory.name.startswith("moodle-doc-"))
        self.assertEqual(directory.parent, self.root / "cache" / "workspaces")
        old = time.time() - 8 * 24 * 3600
        os.utime(directory, (old, old))
        keep = directory.parent / "no-es-mio"
        keep.mkdir()
        os.utime(keep, (old, old))
        self.assertEqual(cleanup_workspaces(), 1)
        self.assertFalse(directory.exists())
        self.assertTrue(keep.exists())


class OpenFileTests(unittest.TestCase):
    def test_open_never_inherits_the_mcp_stdio(self):
        with patch.object(delivery.sys, "platform", "linux"), patch.dict(os.environ, {"DISPLAY": ":0"}), \
                patch("moodle_tasks.delivery.shutil.which", return_value="/usr/bin/xdg-open"), \
                patch("moodle_tasks.delivery.subprocess.Popen") as popen:
            self.assertTrue(open_file(Path("/tmp/x.pdf")))
        kwargs = popen.call_args.kwargs
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(kwargs[stream], delivery.subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(popen.call_args.args[0], ["xdg-open", "/tmp/x.pdf"])

    def test_no_display_skips_opening(self):
        environment = {key: value for key, value in os.environ.items() if key not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with patch.object(delivery.sys, "platform", "linux"), patch.dict(os.environ, environment, clear=True), \
                patch("moodle_tasks.delivery.subprocess.Popen") as popen:
            self.assertFalse(open_file(Path("/tmp/x.pdf")))
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
