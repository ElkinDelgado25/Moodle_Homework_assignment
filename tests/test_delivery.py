import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from moodle_tasks.delivery import finish_delivery, prepare_workspace


class DeliveryTests(unittest.TestCase):
    def test_finish_copies_files_and_opens_the_pdf_as_one_address(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as destination:
            work = Path(source)
            docx = work / "entrega.docx"
            pdf = work / "entrega.pdf"
            docx.write_bytes(b"docx")
            pdf.write_bytes(b"pdf")
            opened = []
            with patch("moodle_tasks.delivery.webbrowser.open", side_effect=lambda url: opened.append(url) or True):
                result = finish_delivery(str(docx), str(pdf), destination)
            final_pdf = Path(destination) / "entrega.pdf"
            self.assertEqual(Path(result["pdf_path"]).read_bytes(), b"pdf")
            self.assertEqual(Path(result["docx_path"]).read_bytes(), b"docx")
            self.assertTrue(result["opened_in_browser"])
            self.assertEqual(opened, [final_pdf.resolve().as_uri()])
            self.assertTrue(final_pdf.is_file())

    def test_workspace_is_a_temporary_directory(self):
        directory = prepare_workspace()
        self.addCleanup(lambda: directory.rmdir() if directory.exists() else None)
        self.assertTrue(directory.is_dir())
        self.assertTrue(directory.name.startswith("moodle-doc-"))
