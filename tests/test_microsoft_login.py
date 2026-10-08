import unittest

from playwright.sync_api import sync_playwright

from moodle_tasks.errors import MoodleAuthenticationError
from moodle_tasks.main import Config, login


class MicrosoftLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_institutional_login_selects_microsoft_and_reselects_same_profile(self):
        self.run_flow(False)

    def test_microsoft_rejection_is_reported_without_claiming_a_moodle_session(self):
        self.run_flow(True)

    def run_flow(self, rejected):
        page = self.browser.new_page()
        config = Config("https://moodle.test", "student@live.uleam.edu.ec", "test-password", True)
        visited = []
        pages = {
            "https://moodle.test/login/index.php": '<a href="https://login.test/email">Microsoft 365 Uleam</a>',
            "https://login.test/email": '<form action="/password"><input name="loginfmt"><input id="idSIButton9" type="submit" value="Next"></form>',
            "https://login.test/password": '<form action="/secure"><input name="passwd" type="password"><input id="idSIButton9" type="submit" value="Sign in"></form>',
            "https://login.test/secure": '<div id="passwordError">Incorrect password.</div>' if rejected else '<a href="/picker">Use a different account</a>',
            "https://login.test/picker": '<a href="https://moodle.test/my/">student@live.uleam.edu.ec</a>',
            "https://moodle.test/my/": '<a href="/login/logout.php">Salir</a>',
        }

        def respond(route):
            url = route.request.url.split("?")[0]
            visited.append(url)
            if url.endswith("/secure"):
                # La contraseña llega al formulario correcto.
                self.assertIn("passwd=test-password", route.request.url)
            route.fulfill(content_type="text/html", body=pages.get(url, ""))

        page.route("**/*", respond)
        try:
            if rejected:
                with self.assertRaises(MoodleAuthenticationError):
                    login(page, config)
                self.assertNotIn("https://moodle.test/my/", visited)
            else:
                login(page, config)
                self.assertIn("https://login.test/picker", visited)
                self.assertEqual(page.url, "https://moodle.test/my/")
        finally:
            page.close()
