import io
import unittest
from contextlib import redirect_stdout

from playwright.sync_api import sync_playwright

from moodle_tasks.main import Config, find_assignment_links, login, print_tasks, read_assignment, submission_state


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
        self.page.set_default_timeout(250)
        self.config = Config("https://moodle.test", "test", "test", True)

    def tearDown(self):
        self.page.close()

    def test_gateway_error_is_not_a_successful_login(self):
        self.page.route("**/*", lambda route: route.fulfill(
            status=502, content_type="text/html", body="<h1>502 Bad Gateway</h1>"
        ))
        with self.assertRaisesRegex(RuntimeError, "HTTP 502"):
            login(self.page, self.config)

    def test_missing_login_form_requires_authenticated_session(self):
        self.page.route("**/*", lambda route: route.fulfill(
            content_type="text/html", body="<h1>Mantenimiento</h1>"
        ))
        with self.assertRaisesRegex(RuntimeError, "sesión iniciada"):
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


if __name__ == "__main__":
    unittest.main()
