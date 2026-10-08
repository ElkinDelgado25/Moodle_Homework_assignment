import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from moodle_tasks.main import Config, collect_assignments, is_pending, read_assignment
from moodle_tasks.search import assignment_url, parse_moodle_date, search_assignments


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.cache_patch = patch("moodle_tasks.search.user_config_dir", return_value=Path(self.directory.name))
        self.cache_patch.start()
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.config = Config("https://moodle.test", "student", "password", True)
        self.visited = []
        self.now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        self.tasks = {
            1: {"title": "Calificada", "status": "Todavía no se han realizado envíos", "grade": "8,00", "open": -4, "due": 1},
            2: {"title": "Entregada", "status": "Enviado para calificar", "grade": "-", "open": -3, "due": 2},
            3: {"title": "Pendiente reciente", "status": "Todavía no se han realizado envíos", "grade": "-", "open": -1, "due": 3},
            4: {"title": "Pendiente anterior", "status": "Todavía no se han realizado envíos", "grade": "-", "open": -2, "due": 4},
            5: {"title": "Vencida", "status": "Todavía no se han realizado envíos", "grade": "-", "open": -9, "due": -1},
            6: {"title": "Aún no abierta", "status": "Todavía no se han realizado envíos", "grade": "-", "open": 5, "due": 6},
        }
        self.timeline_ids = (1, 2, 3)
        self.context.route("**/*", self.respond)

    def tearDown(self):
        self.context.close()
        self.cache_patch.stop()
        self.directory.cleanup()

    def date(self, days):
        date = self.now + timedelta(days=days)
        months = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
        return f"{date.day} de {months[date.month - 1]} de {date.year}, {date:%H:%M}"

    def event(self, identifier):
        task = self.tasks[identifier]
        action = (f'<a href="/mod/assign/view.php?id={identifier}&action=editsubmission">Agregar entrega</a>'
                  if task['open'] <= 0 and task['grade'] == '-' and task['status'] != 'Enviado para calificar' else '')
        return (f'<div data-region="event-list-item"><div class="event-name-container">'
                f'<a aria-label="Pendiente para {self.date(task["due"])}" href="/mod/assign/view.php?id={identifier}">Tarea {identifier}</a>'
                f'<small>Vencimiento de Tarea · Materia A</small></div>{action}</div>')

    def respond(self, route):
        url = route.request.url
        self.visited.append(url)
        if url.endswith("/my/"):
            more = json.dumps(self.event(4))
            body = '<div class="block_timeline"><button>Próximos 30 días</button>' + ''.join(self.event(i) for i in self.timeline_ids)
            body += f'<button onclick=\'this.insertAdjacentHTML("beforebegin", {more}); this.remove()\'>Mostrar más actividades</button></div>'
        elif url.endswith("/my/courses.php"):
            body = '<a href="/course/view.php?id=7">Materia A</a><a href="/course/view.php?id=8">Materia B</a>'
        elif "/mod/assign/index.php" in url:
            ids = (1, 2, 3) if "id=7" in url else (4, 5, 6)
            body = '<table>'
            for identifier in ids:
                task = self.tasks[identifier]
                body += f'<tr><td>Unidad</td><td><a href="/mod/assign/view.php?id={identifier}">{task["title"]}</a></td><td>{self.date(task["due"])}</td><td>{task["status"]}</td><td>{task["grade"]}</td></tr>'
            body += '</table>'
        elif "/mod/assign/view.php" in url:
            identifier = int(url.split("id=")[1])
            task = self.tasks[identifier]
            body = f'<h1>{task["title"]}</h1><nav class="breadcrumb"><a href="/course/view.php?id=7">Materia A</a></nav><main id="region-main">'
            body += f'<div class="activity-dates">Apertura: {self.date(task["open"])}<br>Cierre: {self.date(task["due"])}</div>'
            body += '<div id="intro">Instrucciones y <a href="/pluginfile.php/1/mod_assign/introattachment/0/guia.pdf">guia.pdf</a></div>'
            body += f'<table class="submissionstatustable"><tr><th>Estado de la entrega</th><td>{task["status"]}</td></tr></table>'
            body += '<a href="/pluginfile.php/1/assignsubmission_file/submission_files/1/mi-entrega.pdf">Mi entrega</a>'
            if task['grade'] != '-':
                body += f'<div>Calificación\t{task["grade"]} / 10,00</div>'
            body += '</main>'
        else:
            body = ''
        route.fulfill(content_type="text/html; charset=utf-8", body=body)

    def query(self, **kwargs):
        stats = {}
        tasks, errors = search_assignments(self.page, self.config, stats=stats, **kwargs)
        self.assertEqual(errors, [])
        return tasks, stats

    def test_surface_list_reads_no_activity_or_attachment_and_skips_future_tasks(self):
        self.timeline_ids = (1, 2, 5, 6, 3)
        with patch('moodle_tasks.search.read_assignment', side_effect=AssertionError('No abrir detalles')):
            tasks, stats = self.query(mode='upcoming', limit=2, summary_only=True)
        self.assertEqual([task.url.rsplit('=', 1)[1] for task in tasks], ['3', '4'])
        self.assertEqual(stats['detail_pages_read'], 0)
        self.assertEqual(stats['dashboard_load_more'], 1)
        self.assertTrue(all(task.course == 'Materia A' and task.due_at for task in tasks))
        self.assertTrue(all(not task.content and not task.attachments for task in tasks))
        self.assertFalse(any('/mod/assign/view.php' in url or '/pluginfile.php' in url for url in self.visited))
        # Profundizar se hace solo en la actividad seleccionada.
        detail = read_assignment(self.page, tasks[0].url)
        self.assertIn('Instrucciones', detail.content)
        self.assertEqual(detail.attachments[0]['name'], 'guia.pdf')

    def test_surface_complete_search_uses_only_indexes_and_preserves_pending_count(self):
        with patch('moodle_tasks.search.read_assignment', side_effect=AssertionError('No abrir detalles')):
            tasks, stats = self.query(mode='all', limit=None, summary_only=True)
        self.assertEqual([task.title for task in tasks], ['Vencida', 'Pendiente reciente', 'Pendiente anterior', 'Aún no abierta'])
        self.assertEqual(stats['index_pages_read'], 2)
        self.assertEqual(stats['detail_pages_read'], 0)
        self.assertFalse(any('/mod/assign/view.php' in url for url in self.visited))

    def test_quick_search_paginates_deduplicates_and_stops_after_matching_limit(self):
        tasks, stats = self.query(mode="upcoming", limit=2)
        self.assertEqual([task.url.rsplit('=', 1)[1] for task in tasks], ['3', '4'])
        self.assertEqual(stats['source'], 'dashboard')
        self.assertEqual(stats['dashboard_load_more'], 1)
        self.assertEqual(stats['detail_pages_read'], 4)
        self.assertFalse(any('/mod/assign/index.php' in url for url in self.visited))
        self.assertFalse(any('action=' in url for url in self.visited))

    def test_terminal_collector_supports_separate_timeline_and_detail_pages(self):
        def configure_routes(page, config):
            page.context.route('**/*', self.respond)

        with patch('moodle_tasks.main.login', side_effect=configure_routes), ThreadPoolExecutor(max_workers=1) as executor:
            tasks, errors = executor.submit(collect_assignments, self.config, mode='upcoming', limit=2, only_pending=True).result()
        self.assertEqual(errors, [])
        self.assertEqual([task.title for task in tasks], ['Tarea 3', 'Tarea 4'])

    def test_complete_search_checks_both_courses_and_skips_graded_and_submitted_details(self):
        tasks, stats = self.query(mode="all", limit=None)
        self.assertEqual({task.title for task in tasks}, {'Pendiente reciente', 'Pendiente anterior', 'Vencida', 'Aún no abierta'})
        self.assertEqual(stats['courses_found'], 2)
        self.assertEqual(stats['index_pages_read'], 2)
        self.assertEqual(stats['detail_pages_read'], 4)
        self.assertEqual(stats['candidates_checked'], 6)

    def test_recent_excludes_future_openings_and_overdue_excludes_future_deadlines(self):
        recent, _ = self.query(mode="recent", limit=5)
        self.assertEqual([task.title for task in recent], ['Pendiente reciente', 'Pendiente anterior'])
        overdue, _ = self.query(mode="overdue", limit=None)
        self.assertEqual([task.title for task in overdue], ['Vencida'])

    def test_upcoming_skips_future_openings_and_expired_tasks_in_index_fallback(self):
        self.context.unroute('**/*', self.respond)

        def respond(route):
            if route.request.url.endswith('/my/'):
                route.fulfill(content_type='text/html', body='<main>Sin línea de tiempo</main>')
            else:
                self.respond(route)

        self.context.route('**/*', respond)
        tasks, stats = self.query(mode='upcoming', limit=5)
        self.assertEqual([task.title for task in tasks], ['Pendiente reciente', 'Pendiente anterior'])
        self.assertEqual(stats['source'], 'course_indexes')

    def test_timeline_loads_more_to_replace_a_task_that_is_not_yet_open(self):
        self.timeline_ids = (6, 3)
        tasks, stats = self.query(mode='upcoming', limit=2)
        self.assertEqual([task.url.rsplit('=', 1)[1] for task in tasks], ['3', '4'])
        self.assertEqual(stats['dashboard_load_more'], 1)
        self.assertEqual(stats['detail_pages_read'], 3)

    def test_cache_reuses_details_but_rechecks_indexes_and_invalidates_changed_rows(self):
        self.query(mode="all", limit=None)
        self.visited.clear()
        _, stats = self.query(mode="all", limit=None)
        self.assertEqual(stats['index_pages_read'], 2)
        self.assertEqual(stats['cached_details'], 4)
        self.assertEqual(stats['detail_pages_read'], 0)
        self.tasks[3]['due'] = 7
        _, stats = self.query(mode="all", limit=None)
        self.assertEqual(stats['cached_details'], 3)
        self.assertEqual(stats['detail_pages_read'], 1)
        self.tasks[4]['grade'] = '10,00'
        tasks, _ = self.query(mode="all", limit=None)
        self.assertNotIn('Pendiente anterior', [task.title for task in tasks])

    def test_refresh_bypasses_cached_details(self):
        self.query(mode="all", limit=None)
        _, stats = self.query(mode="all", limit=None, refresh=True)
        self.assertEqual(stats['cached_details'], 0)
        self.assertEqual(stats['detail_pages_read'], 4)

    def test_details_identify_dates_course_grade_and_only_teacher_attachments(self):
        task = read_assignment(self.page, 'https://moodle.test/mod/assign/view.php?id=1')
        self.assertEqual(task.course, 'Materia A')
        self.assertEqual(task.opens_at, (self.now - timedelta(days=4)).isoformat())
        self.assertEqual(task.due_at, (self.now + timedelta(days=1)).isoformat())
        self.assertEqual(task.grade, '8,00')
        self.assertFalse(is_pending(task))
        self.assertEqual([file['name'] for file in task.attachments], ['guia.pdf'])

    def test_links_are_normalized_without_following_actions_or_foreign_sites(self):
        self.assertEqual(assignment_url('https://moodle.test/mod/assign/view.php?id=3&action=editsubmission', self.config.base_url), 'https://moodle.test/mod/assign/view.php?id=3')
        self.assertIsNone(assignment_url('https://other.test/mod/assign/view.php?id=3', self.config.base_url))

    def test_moodle_dates_preserve_midnight_and_reject_invalid_dates(self):
        self.assertEqual(parse_moodle_date('jueves, 3 de diciembre de 2026, 00:00'), '2026-12-03T00:00:00')
        self.assertEqual(parse_moodle_date('Monday, 5 October 2026, 11:00 AM'), '2026-10-05T11:00:00')
        self.assertIsNone(parse_moodle_date('31 de febrero de 2026, 00:00'))
