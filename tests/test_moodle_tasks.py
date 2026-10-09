import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from moodle_tasks.main import Config, find_assignment_links, login, print_tasks, read_assignment, submission_state
from moodle_tasks.errors import MoodleAuthenticationError, MoodleHTTPError


class MoodleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        # Comprobamos los resultados de Moodle, no el rendimiento del runner.
        self.page.set_default_timeout(15_000)
        self.config = Config("https://moodle.test", "test", "test", True)

    def tearDown(self):
        self.page.close()

    def test_gateway_error_is_not_a_successful_login(self):
        self.page.route("**/*", lambda route: route.fulfill(
            status=502, content_type="text/html", body="<h1>502 Bad Gateway</h1>"
        ))
        with self.assertRaises(MoodleHTTPError) as caught:
            login(self.page, self.config)
        self.assertEqual(caught.exception.status, 502)
        self.assertIn("Por ahora no se pudieron consultar tus tareas", str(caught.exception))
        self.assertIn("error del servidor", str(caught.exception))

    def test_server_failures_share_friendly_message_without_hiding_other_errors(self):
        for status in (500, 502, 503, 504):
            self.assertIn("error del servidor", str(MoodleHTTPError(status, "https://moodle.test")))
        self.assertIn("HTTP 403", str(MoodleHTTPError(403, "https://moodle.test")))
        self.assertNotIn("error del servidor", str(MoodleHTTPError(403, "https://moodle.test")))

    def test_missing_login_form_requires_authenticated_session(self):
        self.page.route("**/*", lambda route: route.fulfill(
            content_type="text/html", body="<h1>Mantenimiento</h1>"
        ))
        with self.assertRaisesRegex(RuntimeError, "sesión iniciada"):
            login(self.page, self.config)

    def test_login_checks_credentials_and_post_login_server_failures(self):
        form = '''<form id="login" method="post" action="/login/index.php">
          <input name="username"><input name="password"><button type="submit">Acceder</button>
        </form>'''
        for status, body, expected in (
            (200, form, MoodleAuthenticationError),
            (502, "<h1>502 Bad Gateway</h1>", MoodleHTTPError),
        ):
            with self.subTest(status=status):
                self.page.unroute("**/*")

                def respond(route):
                    route.fulfill(content_type="text/html", status=status if route.request.method == "POST" else 200,
                                  body=body if route.request.method == "POST" else form)

                self.page.route("**/*", respond)
                with self.assertRaises(expected):
                    login(self.page, self.config)

    def test_valid_credentials_require_an_authenticated_session(self):
        form = '''<form id="login" method="post" action="/my/">
          <input name="username"><input name="password"><button type="submit">Acceder</button>
        </form>'''
        for authenticated in (True, False):
            with self.subTest(authenticated=authenticated):
                self.page.unroute("**/*")

                def respond(route):
                    if route.request.method == "POST":
                        route.fulfill(content_type="text/html", body=(
                            '<a href="/login/logout.php">Salir</a>' if authenticated else '<h1>Error</h1>'
                        ))
                    else:
                        route.fulfill(content_type="text/html", body=form)

                self.page.route("**/*", respond)
                if authenticated:
                    login(self.page, self.config)
                else:
                    with self.assertRaisesRegex(RuntimeError, "confirmar una sesión"):
                        login(self.page, self.config)

    def test_tasks_are_found_inside_courses_and_deduplicated(self):
        visited = []

        def respond(route):
            visited.append(route.request.url)
            body = (
                '<a href="/mod/assign/view.php?id=7">Tarea</a>' * 2
                if "/course/view.php" in route.request.url
                else '<a href="/course/view.php?id=3">Curso</a>'
            )
            route.fulfill(content_type="text/html", body=body)

        self.page.route("**/*", respond)
        self.assertEqual(
            find_assignment_links(self.page, self.config),
            ["https://moodle.test/mod/assign/view.php?id=7"],
        )
        self.assertEqual(visited.count("https://moodle.test/course/view.php?id=3"), 1)

    def test_empty_results_do_not_claim_no_pending_tasks(self):
        output = io.StringIO()
        with redirect_stdout(output):
            print_tasks([])
        self.assertIn("No se puede confirmar", output.getvalue())
        self.assertNotIn("✅", output.getvalue())

    def test_zero_matches_after_review_reports_the_search_scope(self):
        output = io.StringIO()
        with redirect_stdout(output):
            print_tasks([], reviewed_count=12)
        self.assertIn("Tareas revisadas: 12", output.getvalue())
        self.assertIn("cumplan esta búsqueda", output.getvalue())
        self.assertNotIn("No se pudieron revisar", output.getvalue())

    def test_submission_state_does_not_confuse_negative_or_unknown_status(self):
        for text in ("Not submitted", "No entregado", "Borrador (no enviado)"):
            self.assertIs(submission_state(text), False)
        self.assertIs(submission_state("Submitted for grading"), True)
        self.assertIs(submission_state("Entregado para calificar"), True)
        self.assertIsNone(submission_state("Estado de entrega no visible."))
        self.assertIsNone(submission_state("No calificado"))

    def test_submission_row_takes_priority_over_grading_text(self):
        self.page.route("**/*", lambda route: route.fulfill(content_type="text/html", body='''
            <h1>Tarea</h1><table class="submissionstatustable">
              <tr><th>Estado de la entrega</th><td>No entregado</td></tr>
              <tr><th>Estado de calificación</th><td>No calificado</td></tr>
            </table>'''))
        task = read_assignment(self.page, "https://moodle.test/mod/assign/view.php?id=1")
        self.assertIs(task.submitted, False)

    def test_assignment_keeps_web_links_from_a_url_only_description(self):
        self.page.route("**/*", lambda route: route.fulfill(content_type="text/html", body='''
            <h1>Práctica Android</h1>
            <div id="intro"><a href="https://developer.android.com/codelabs">https://developer.android.com/codelabs</a>
            <a href="/pluginfile.php/1/material.pdf">Material PDF</a></div>'''))
        task = read_assignment(self.page, "https://moodle.test/mod/assign/view.php?id=1")
        self.assertIn("https://developer.android.com/codelabs", task.content)
        self.assertEqual(task.links, [{"name": "https://developer.android.com/codelabs",
                                       "url": "https://developer.android.com/codelabs"}])
        self.assertEqual(task.attachments[0]["url"], "https://moodle.test/pluginfile.php/1/material.pdf")

    def test_expired_assignment_session_is_renewed_before_reading(self):
        authenticated = False

        def respond(route):
            if not authenticated:
                route.fulfill(
                    content_type="text/html", body='<form id="login"><input name="username"></form>'
                )
            else:
                route.fulfill(content_type="text/html", body='<h1>Taller</h1><div id="intro">Instrucciones reales</div>')

        def renew(*args):
            nonlocal authenticated
            authenticated = True

        self.page.route("**/*", respond)
        with patch("moodle_tasks.main.login", side_effect=renew) as login_again:
            task = read_assignment(self.page, "https://moodle.test/mod/assign/view.php?id=1", self.config)
        self.assertEqual(task.title, "Taller")
        self.assertEqual(task.content, "Instrucciones reales")
        login_again.assert_called_once()

    def test_persistent_expiration_is_an_error_instead_of_a_fake_task(self):
        self.page.route("**/*", lambda route: route.fulfill(
            content_type="text/html", body='<h1>Acceder</h1><input name="username">'
        ))
        with patch("moodle_tasks.main.login") as renew:
            with self.assertRaises(MoodleAuthenticationError):
                read_assignment(self.page, "https://moodle.test/mod/assign/view.php?id=1", self.config)
            renew.assert_called_once()


if __name__ == "__main__":
    unittest.main()
