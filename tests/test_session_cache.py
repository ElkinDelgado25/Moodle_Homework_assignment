import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright

from moodle_tasks import session
from moodle_tasks.errors import MoodleAuthenticationError
from moodle_tasks.main import Config
from moodle_tasks.paths import UnsafePathError, check_upload_file

CONFIG = Config("https://moodle.test", "estudiante@uleam.edu.ec", "secreto", True)
MOODLE_COOKIE = {"name": "MoodleSession", "value": "abc", "domain": "moodle.test", "path": "/",
                 "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"}
FOREIGN_COOKIE = dict(MOODLE_COOKIE, name="ESTSAUTH", domain=".login.microsoftonline.com")


class SessionCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config_dir = Path(self.temporary.name) / "config"
        for target in ("moodle_tasks.session.user_config_dir", "moodle_tasks.paths.user_config_dir"):
            patcher = patch(target, return_value=self.config_dir)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.dict(os.environ, {"MOODLE_SESSION_CACHE": "true"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def context(self, cookies):
        context = MagicMock()
        context.cookies.return_value = cookies
        return context

    def test_only_moodle_cookies_are_saved_with_private_permissions(self):
        self.assertTrue(session.save_state(self.context([MOODLE_COOKIE, FOREIGN_COOKIE]), CONFIG))
        path = session.session_file(CONFIG)
        data = json.loads(path.read_text())
        self.assertEqual([cookie["name"] for cookie in data["cookies"]], ["MoodleSession"])
        self.assertNotIn("secreto", path.read_text())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(session.load_state(CONFIG), {"cookies": [MOODLE_COOKIE], "origins": []})

    def test_invalid_old_or_foreign_states_are_ignored(self):
        path = session.session_file(CONFIG)
        session.save_state(self.context([MOODLE_COOKIE]), CONFIG)
        data = json.loads(path.read_text())
        for broken in ("{no es json", json.dumps([1, 2]), json.dumps(dict(data, version=99)),
                       json.dumps(dict(data, saved_at=time.time() - 13 * 3600)),
                       json.dumps(dict(data, saved_at=time.time() + 3600)),
                       json.dumps(dict(data, base_url="https://otro.test")),
                       json.dumps(dict(data, cookies=[MOODLE_COOKIE, FOREIGN_COOKIE])),
                       json.dumps(dict(data, cookies=[]))):
            path.write_text(broken)
            self.assertIsNone(session.load_state(CONFIG), broken[:40])

    def test_each_account_has_its_own_file(self):
        other = Config(CONFIG.base_url, "otra@uleam.edu.ec", "x", True)
        self.assertNotEqual(session.session_file(CONFIG), session.session_file(other))
        session.save_state(self.context([MOODLE_COOKIE]), CONFIG)
        self.assertIsNone(session.load_state(other))

    def test_opt_out_disables_reading_and_writing(self):
        with patch.dict(os.environ, {"MOODLE_SESSION_CACHE": "false"}):
            self.assertFalse(session.save_state(self.context([MOODLE_COOKIE]), CONFIG))
        self.assertFalse(session.session_file(CONFIG).exists())
        session.save_state(self.context([MOODLE_COOKIE]), CONFIG)
        with patch.dict(os.environ, {"MOODLE_SESSION_CACHE": "0"}):
            self.assertIsNone(session.load_state(CONFIG))

    def test_non_list_cookies_never_write(self):
        self.assertFalse(session.save_state(self.context(MagicMock()), CONFIG))
        self.assertFalse(session.save_state(self.context([]), CONFIG))

    def test_the_session_file_can_never_be_uploaded(self):
        session.save_state(self.context([MOODLE_COOKIE]), CONFIG)
        with self.assertRaises(UnsafePathError):
            check_upload_file(str(session.session_file(CONFIG)))

    def test_authentication_error_deletes_the_saved_session(self):
        session.save_state(self.context([MOODLE_COOKIE]), CONFIG)
        playwright = MagicMock()
        with patch("moodle_tasks.session.sync_playwright", return_value=playwright):
            with self.assertRaises(MoodleAuthenticationError):
                with session.moodle_page(CONFIG):
                    raise MoodleAuthenticationError("Moodle no aceptó el usuario o la contraseña.")
        self.assertFalse(session.session_file(CONFIG).exists())

    def test_other_errors_keep_the_session_and_successful_runs_refresh_it(self):
        session.save_state(self.context([MOODLE_COOKIE]), CONFIG)
        playwright = MagicMock()
        context = playwright.__enter__.return_value.chromium.launch.return_value.new_context.return_value
        context.cookies.return_value = [dict(MOODLE_COOKIE, value="nuevo")]
        with patch("moodle_tasks.session.sync_playwright", return_value=playwright):
            with self.assertRaises(RuntimeError):
                with session.moodle_page(CONFIG):
                    raise RuntimeError("fallo de red")
            self.assertEqual(session.load_state(CONFIG)["cookies"][0]["value"], "abc")
            with session.moodle_page(CONFIG):
                pass
        launch = playwright.__enter__.return_value.chromium.launch.return_value
        self.assertEqual(launch.new_context.call_args.kwargs["storage_state"]["cookies"][0]["value"], "abc")
        self.assertEqual(session.load_state(CONFIG)["cookies"][0]["value"], "nuevo")
        self.assertEqual(launch.close.call_count, 2)


class EnsureLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def respond(self, route):
        cookie = route.request.headers.get("cookie", "")
        if "MoodleSession=valida" in cookie:
            route.fulfill(content_type="text/html", body='<a href="/login/logout.php">Salir</a>')
        else:
            route.fulfill(content_type="text/html", body="<form id='login'><input name='username'></form>")

    def run_case(self, cookies):
        context = self.browser.new_context()
        try:
            if cookies:
                context.add_cookies(cookies)
            context.route("**/my/", self.respond)
            context.route("**/login/index.php", lambda route: route.fulfill(content_type="text/html", body="<form id='login'></form>"))
            page = context.new_page()
            with patch("moodle_tasks.session.login") as login:
                logged = session.ensure_login(page, CONFIG)
            return logged, login.call_count
        finally:
            context.close()

    def test_valid_saved_session_skips_the_login(self):
        cookie = {"name": "MoodleSession", "value": "valida", "domain": "moodle.test", "path": "/"}
        self.assertEqual(self.run_case([cookie]), (False, 0))

    def test_expired_session_logs_in_again(self):
        cookie = {"name": "MoodleSession", "value": "vencida", "domain": "moodle.test", "path": "/"}
        self.assertEqual(self.run_case([cookie]), (True, 1))

    def test_no_cookies_goes_straight_to_login(self):
        self.assertEqual(self.run_case([]), (True, 1))


if __name__ == "__main__":
    unittest.main()
