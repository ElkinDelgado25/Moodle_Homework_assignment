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

    def test_password_form_receives_keyboard_events_before_submission(self):
        self.run_flow(False, keyboard_required=True)

    def test_empty_field_message_is_retried_once_without_treating_it_as_bad_credentials(self):
        self.run_flow(False, empty_submissions=1)

    def test_repeated_empty_field_stops_after_one_retry(self):
        with self.assertRaisesRegex(RuntimeError, 'campo de contraseña vacío'):
            self.run_flow(False, empty_submissions=2)

    def run_flow(self, rejected, keyboard_required=False, empty_submissions=0):
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
        if keyboard_required:
            pages['https://login.test/password'] = '''
              <form action="/secure" onsubmit="if (!window.passwordReady) {event.preventDefault(); document.querySelector('#passwordError').textContent='Please enter your password.';}">
                <input name="passwd" type="password" onkeyup="if (event.key !== 'Tab' && this.value) window.passwordReady=true">
                <input id="idSIButton9" type="submit" value="Next">
                <div id="passwordError"></div>
              </form>
              <script>setTimeout(() => {document.querySelector('#idSIButton9').value='Sign in';}, 500)</script>
            '''
        secure_submissions = 0

        def respond(route):
            nonlocal secure_submissions
            url = route.request.url.split("?")[0]
            visited.append(url)
            if url.endswith("/secure"):
                # La contraseña llega al formulario correcto.
                self.assertIn("passwd=test-password", route.request.url)
                secure_submissions += 1
                if secure_submissions <= empty_submissions:
                    route.fulfill(content_type='text/html; charset=utf-8', body=pages['https://login.test/password'] + '<div id="passwordError">Please enter your password.</div>')
                    return
            route.fulfill(content_type="text/html; charset=utf-8", body=pages.get(url, ""))

        page.route("**/*", respond)
        try:
            if rejected:
                with self.assertRaises(MoodleAuthenticationError):
                    login(page, config)
                self.assertNotIn("https://moodle.test/my/", visited)
                self.assertEqual(secure_submissions, 1)
            else:
                login(page, config)
                self.assertIn("https://login.test/picker", visited)
                self.assertEqual(page.url, "https://moodle.test/my/")
                self.assertEqual(secure_submissions, empty_submissions + 1)
        finally:
            page.close()
