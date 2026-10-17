import json
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from moodle_tasks.main import Config
from moodle_tasks.profile import load_profile, public_profile, record_verified_profile


class ProfileTests(unittest.TestCase):
    def test_verified_name_and_courses_do_not_replace_teacher_or_year(self):
        with tempfile.TemporaryDirectory() as directory, sync_playwright() as playwright:
            root = Path(directory)
            (root / "document_profile.json").write_text(
                json.dumps({"teacher": "Ing. María Esther", "year": "Octubre-2026", "student_1": "Nombre anterior"}),
                encoding="utf-8",
            )
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(
                '<div class="usermenu"><span class="usertext">Elkin Delgado Licoa</span></div>'
                '<a href="/my/courses.php">Mis cursos</a>'
            )
            page.route("**/*", lambda route: route.fulfill(
                content_type="text/html; charset=utf-8",
                body='''<a href="/course/view.php?id=1">Ciberseguridad</a>
                        <a href="/course/view.php?id=1">Ciberseguridad</a>
                        <a href="/course/view.php?id=2">Mis cursos</a>
                        <a href="/course/view.php?id=3">Metodología</a>''',
            ))
            try:
                saved = record_verified_profile(page, Config("https://moodle.test", "student", "secret", True), root)
            finally:
                browser.close()
            self.assertEqual(saved["student_1"], "Elkin Delgado Licoa")
            self.assertEqual(saved["courses"], ["Ciberseguridad", "Metodología"])
            stored = json.loads((root / "document_profile.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["teacher"], "Ing. María Esther")
            self.assertEqual(stored["year"], "Octubre-2026")
            self.assertEqual(load_profile(root)["courses"], ["Ciberseguridad", "Metodología"])

    def test_invalid_profile_values_are_rejected(self):
        with self.assertRaises(ValueError):
            public_profile({"student_1": 123})
        with self.assertRaises(ValueError):
            public_profile({"courses": ["Ciberseguridad", 5]})
        self.assertEqual(public_profile({"student_1": "Ana", "password": "oculto"})["student_1"], "Ana")
        self.assertNotIn("password", public_profile({"student_1": "Ana", "password": "oculto"}))
