import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright

from moodle_tasks.downloads import attachment_name, download_attachment
from moodle_tasks.errors import MoodleAuthenticationError, MoodleHTTPError
from moodle_tasks.main import Config


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.page = MagicMock()
        self.settings = Config("https://moodle.test", "test", "test", True)
        self.url = "https://moodle.test/pluginfile.php/7/mod_assign/introattachment/0/Taller%20Semana%206.pdf"

    def response(self, body=b"%PDF-1.7\nexample", status=200, content_type="application/pdf", location=None):
        result = MagicMock()
        result.status = status
        result.headers = {"content-type": content_type}
        if location:
            result.headers["location"] = location
        result.body.return_value = body
        return result

    def test_decoded_filename_and_existing_file_are_preserved(self):
        self.page.context.request.get.return_value = self.response()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            original = destination / "Taller Semana 6.pdf"
            original.write_bytes(b"existing")
            result = download_attachment(self.page, self.settings, self.url, destination)
            self.assertEqual(original.read_bytes(), b"existing")
            self.assertEqual(result["name"], "Taller Semana 6 (1).pdf")
            self.assertTrue(Path(result["path"]).read_bytes().startswith(b"%PDF-"))
        self.page.context.request.get.return_value.dispose.assert_called_once()

    def test_login_redirect_and_html_retry_once_before_saving(self):
        for first in (self.response(status=302, location="/login/index.php"), self.response(
            body=b"<!DOCTYPE html><html>Login</html>", content_type="application/octet-stream"
        ), self.response(status=401), self.response(status=403)):
            with self.subTest(first=first):
                self.page.context.request.get.side_effect = [first, self.response()]
                with tempfile.TemporaryDirectory() as directory, patch("moodle_tasks.downloads.login") as renew:
                    result = download_attachment(self.page, self.settings, self.url, Path(directory))
                    self.assertEqual(result["name"], "Taller Semana 6.pdf")
                    renew.assert_called_once_with(self.page, self.settings)

    def test_persistent_login_page_is_never_saved(self):
        self.page.context.request.get.return_value = self.response(body=b"<html>Login</html>", content_type="text/html")
        with tempfile.TemporaryDirectory() as directory, patch("moodle_tasks.downloads.login") as renew:
            with self.assertRaises(MoodleAuthenticationError):
                download_attachment(self.page, self.settings, self.url, Path(directory))
            renew.assert_called_once()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_invalid_pdf_empty_file_and_server_error_are_not_saved_or_retried(self):
        for response, expected in ((self.response(body=b"not a pdf"), RuntimeError),
                                   (self.response(body=b""), RuntimeError),
                                   (self.response(status=502), MoodleHTTPError)):
            with self.subTest(response=response):
                self.page.context.request.get.return_value = response
                with tempfile.TemporaryDirectory() as directory, patch("moodle_tasks.downloads.login") as renew:
                    with self.assertRaises(expected):
                        download_attachment(self.page, self.settings, self.url, Path(directory))
                    renew.assert_not_called()
                    self.assertEqual(list(Path(directory).iterdir()), [])

    def test_external_links_are_rejected_and_redirects_never_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            for url in ("https://other.test/pluginfile.php/a.pdf", "https://moodle.test/not-an-attachment"):
                with self.assertRaises(ValueError):
                    download_attachment(self.page, self.settings, url, Path(directory))
            self.page.context.request.get.assert_not_called()
            self.page.context.request.get.return_value = self.response(status=302, location="https://other.test/login")
            with patch("moodle_tasks.downloads.login"):
                with self.assertRaises(MoodleAuthenticationError):
                    download_attachment(self.page, self.settings, self.url, Path(directory))
            self.assertTrue(all(call.args[0] == self.url for call in self.page.context.request.get.call_args_list))

    def test_filename_cannot_escape_the_destination(self):
        self.assertEqual(attachment_name("https://moodle.test/pluginfile.php/%2E%2E%2Fsecret.pdf"), "_secret.pdf")
        self.assertEqual(attachment_name("https://moodle.test/pluginfile.php/CON.pdf"), "_CON.pdf")

    def test_real_playwright_download_uses_browser_session_cookies(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/start":
                    self.send_response(200)
                    self.send_header("Set-Cookie", "MoodleSession=test-session; Path=/; HttpOnly")
                    self.end_headers()
                    self.wfile.write(b"<html>Session</html>")
                elif self.headers.get("Cookie") == "MoodleSession=test-session":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.end_headers()
                    self.wfile.write(b"%PDF-1.7\nauthenticated attachment")
                else:
                    self.send_response(302)
                    self.send_header("Location", "/login/index.php")
                    self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as playwright, tempfile.TemporaryDirectory() as directory:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(base + "/start")
                    result = download_attachment(page, Config(base, "test", "test", True), base + "/pluginfile.php/Taller.pdf", Path(directory))
                    self.assertEqual(Path(result["path"]).read_bytes(), b"%PDF-1.7\nauthenticated attachment")
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
