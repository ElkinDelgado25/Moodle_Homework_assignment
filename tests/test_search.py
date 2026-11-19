import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import helpers  # noqa: F401 - aísla las pruebas de la configuración real
from moodle_tasks.assignment import read_assignment
from moodle_tasks.core import is_pending
from moodle_tasks.config import Config
from moodle_tasks.main import collect_assignments
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
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.config = Config("https://moodle.test", "student", "password")
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
        # Servicios AJAX de Moodle: desactivados salvo en las pruebas que los usan.
        self.service = False
        self.service_error = False
        self.service_ids = (1, 2, 3, 4)
        # Tareas de cursos con la matrícula suspendida: Moodle solo las omite si se pide limittononsuspendedevents.
        self.suspended_ids = ()
        self.grouping = "inprogress"
        self.service_calls = []
        self.context.route("**/*", self.respond)

    def tearDown(self):
        self.context.close()

    def date(self, days):
        date = self.now + timedelta(days=days)
        months = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
        return f"{date.day} de {months[date.month - 1]} de {date.year}, {date:%H:%M}"

    def event(self, identifier):
        task = self.tasks[identifier]
        action = (f'<a href="/mod/assign/view.php?id={identifier}&action=editsubmission">{task.get("action_text", "Agregar entrega")}</a>'
                  if task['open'] <= 0 and task['grade'] == '-' and task['status'] != 'Enviado para calificar' else '')
        return (f'<div data-region="event-list-item"><div class="event-name-container">'
                f'<a aria-label="Pendiente para {self.date(task["due"])}" href="/mod/assign/view.php?id={identifier}">Tarea {identifier}</a>'
                f'<small>Vencimiento de Tarea · Materia A</small></div>{action}</div>')

    def service_event(self, identifier):
        task = self.tasks[identifier]
        actionable = task['open'] <= 0 and task['grade'] == '-' and task['status'] != 'Enviado para calificar'
        due = self.now + timedelta(days=task['due'])
        return {"id": 100 + identifier, "modulename": "assign", "activityname": f"Tarea {identifier}",
                "name": f"Tarea {identifier} está en fecha de entrega", "timesort": int(due.timestamp()),
                "url": f"https://moodle.test/mod/assign/view.php?id={identifier}",
                "course": {"id": 7, "fullname": "Materia A"},
                "action": {"name": task.get("action_text", "Agregar entrega"), "actionable": actionable,
                           "url": f"https://moodle.test/mod/assign/view.php?id={identifier}&action=editsubmission"}}

    def service_response(self, call):
        if self.service_error:
            return [{"error": True, "exception": {"errorcode": "invalidparameter", "message": "Invalid parameter"}}]
        args = call["args"]
        if call["methodname"] == "core_course_get_enrolled_courses_by_timeline_classification":
            return [{"error": False, "data": {"courses": [{"id": 7, "fullname": "Materia A"}, {"id": 8, "fullname": "Materia B"}],
                                              "nextoffset": 2}}]
        quiz = {"id": 99, "modulename": "quiz", "name": "Cuestionario", "url": "https://moodle.test/mod/quiz/view.php?id=9",
                "timesort": int((self.now + timedelta(days=1)).timestamp())}
        ids = list(self.service_ids)
        if not args.get("limittononsuspendedevents"):
            ids += list(self.suspended_ids)
        events = sorted([*(self.service_event(i) for i in ids), quiz], key=lambda event: event["timesort"])
        events = [event for event in events if event["timesort"] >= args["timesortfrom"]]
        if "aftereventid" in args:
            events = events[[event["id"] for event in events].index(args["aftereventid"]) + 1:]
        page = events[:args["limitnum"]]
        return [{"error": False, "data": {"events": page, "firstid": page[0]["id"] if page else 0,
                                          "lastid": page[-1]["id"] if page else 0}}]

    def respond(self, route):
        url = route.request.url
        self.visited.append(url)
        if "/lib/ajax/service.php" in url:
            if not self.service:
                route.fulfill(status=404, content_type="text/html", body="")
                return
            call = json.loads(route.request.post_data)[0]
            self.service_calls.append({"url": url, **call})
            route.fulfill(content_type="application/json", body=json.dumps(self.service_response(call)))
            return
        if url.endswith("/my/"):
            more = json.dumps(self.event(4))
            body = '<div class="block_timeline"><button>Próximos 30 días</button>' + ''.join(self.event(i) for i in self.timeline_ids)
            body += f'<button onclick=\'this.insertAdjacentHTML("beforebegin", {more}); this.remove()\'>Mostrar más actividades</button></div>'
            if getattr(self, "logged_in", False):
                body += '<a href="/login/logout.php?sesskey=abc">Salir</a>'
            if self.service:
                body += "<script>window.M = {cfg: {sesskey: 'clave123'}};</script>"
        elif url.endswith("/my/courses.php"):
            body = '<a href="/course/view.php?id=7">Materia A</a><a href="/course/view.php?id=8">Materia B</a>'
            if self.service:
                body = (f'<div data-region="courses-view" data-grouping="{self.grouping}"></div>'
                        "<script>window.M = {cfg: {sesskey: 'clave123'}};</script>") + body
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
        tasks, stats = self.query(mode='upcoming', limit=2)
        self.assertEqual([task.url.rsplit('=', 1)[1] for task in tasks], ['3', '4'])
        self.assertEqual(stats['dashboard_load_more'], 1)
        self.assertTrue(all(task.course == 'Materia A' and task.due_at for task in tasks))
        self.assertTrue(all(not task.content and not task.attachments for task in tasks))
        self.assertFalse(any('/mod/assign/view.php' in url or '/pluginfile.php' in url for url in self.visited))
        # Profundizar se hace solo en la actividad seleccionada.
        detail = read_assignment(self.page, tasks[0].url)
        self.assertIn('Instrucciones', detail.content)
        self.assertEqual(detail.attachments[0]['name'], 'guia.pdf')

    def test_surface_complete_search_uses_only_indexes_and_preserves_pending_count(self):
        tasks, stats = self.query(mode='all', limit=None)
        self.assertEqual([task.title for task in tasks], ['Vencida', 'Pendiente reciente', 'Pendiente anterior', 'Aún no abierta'])
        self.assertEqual(stats['courses_found'], 2)
        self.assertEqual(stats['index_pages_read'], 2)
        self.assertEqual(stats['candidates_checked'], 6)
        self.assertFalse(any('/mod/assign/view.php' in url for url in self.visited))

    def timeline_ids_found(self, **wording):
        self.tasks[3].update(wording)
        self.timeline_ids = (3,)
        tasks, stats = self.query(mode='upcoming', limit=1)
        return [task.url.rsplit('=', 1)[1] for task in tasks], stats

    def test_timeline_recognizes_other_wordings_of_the_add_submission_action(self):
        for text in ("Añadir envío", "Add submission", "Agregar entrega"):
            with self.subTest(text=text):
                found, stats = self.timeline_ids_found(action_text=text)
                self.assertEqual(found, ['3'])
                self.assertNotIn('availability_unconfirmed', stats)

    def test_timeline_keeps_a_task_whose_action_text_is_not_recognized_as_unconfirmed(self):
        found, stats = self.timeline_ids_found(action_text="Hantar tugasan")
        self.assertEqual(found, ['3'])
        self.assertEqual(stats['availability_unconfirmed'], 1)
        self.assertEqual(stats['unrecognized_action_texts'], ["Hantar tugasan"])

    def test_timeline_still_skips_a_task_that_is_already_submitted(self):
        found, _ = self.timeline_ids_found(action_text="Editar entrega")
        self.assertNotIn('3', found)

    def test_surface_index_fallback_returns_tasks_with_unconfirmed_availability(self):
        self.context.unroute('**/*', self.respond)

        def respond(route):
            if route.request.url.endswith('/my/'):
                route.fulfill(content_type='text/html', body='<main>Sin línea de tiempo</main>')
            else:
                self.respond(route)

        self.context.route('**/*', respond)
        tasks, stats = self.query(mode='upcoming', limit=5)
        self.assertEqual([task.title for task in tasks], ['Pendiente reciente', 'Pendiente anterior', 'Aún no abierta'])
        self.assertEqual(stats['availability_unconfirmed'], 3)
        self.assertEqual(stats['timeline_status'], 'missing')
        self.assertEqual(stats['source'], 'course_indexes')
        self.assertFalse(any('/mod/assign/view.php' in url for url in self.visited))

    def test_empty_timeline_does_not_fall_back_to_course_indexes(self):
        self.context.unroute('**/*', self.respond)

        def respond(route):
            if route.request.url.endswith('/my/'):
                route.fulfill(content_type='text/html', body='<div class="block_timeline"><div data-region="no-events-empty-message">Sin actividades</div></div>')
            else:
                self.respond(route)

        self.context.route('**/*', respond)
        tasks, stats = self.query(mode='upcoming', limit=5)
        self.assertEqual(tasks, [])
        self.assertEqual(stats['timeline_status'], 'empty')
        self.assertFalse(any('/mod/assign/index.php' in url or 'courses.php' in url for url in self.visited))

    def test_assignment_urls_support_moodle_in_a_subfolder(self):
        from moodle_tasks.search import assignment_url
        base = "https://moodle.test/moodle"
        self.assertEqual(assignment_url("https://moodle.test/moodle/mod/assign/view.php?id=3&action=editsubmission", base),
                         "https://moodle.test/moodle/mod/assign/view.php?id=3")
        self.assertIsNone(assignment_url("https://moodle.test/mod/assign/view.php?id=3", base))
        self.assertIsNone(assignment_url("https://moodle.test/moodle/mod/assign/view.php?id=\uff13", base))

    def test_terminal_collector_supports_separate_timeline_and_detail_pages(self):
        def configure_routes(page, config):
            page.context.route('**/*', self.respond)

        with patch('moodle_tasks.main.ensure_login', side_effect=configure_routes), ThreadPoolExecutor(max_workers=1) as executor:
            tasks, errors = executor.submit(collect_assignments, self.config, mode='upcoming', limit=2, only_pending=True).result()
        self.assertEqual(errors, [])
        self.assertEqual([task.title for task in tasks], ['Tarea 3', 'Tarea 4'])

    def test_the_dashboard_loaded_by_the_login_check_is_not_loaded_again(self):
        self.logged_in = True
        self.page.goto("https://moodle.test/my/")
        self.visited.clear()
        tasks, stats = self.query(mode="upcoming", limit=2)
        self.assertEqual([task.title for task in tasks], ["Tarea 3", "Tarea 4"])
        self.assertEqual(stats["dashboard_pages_read"], 1)
        self.assertNotIn("https://moodle.test/my/", self.visited)

    def test_another_page_still_opens_the_dashboard(self):
        self.logged_in = True
        self.page.goto("https://moodle.test/my/courses.php")
        self.visited.clear()
        tasks, _ = self.query(mode="upcoming", limit=2)
        self.assertEqual([task.title for task in tasks], ["Tarea 3", "Tarea 4"])
        self.assertEqual(self.visited.count("https://moodle.test/my/"), 1)

    def service_query(self, **kwargs):
        self.service = True
        self.page.goto("https://moodle.test/my/")
        self.visited.clear()
        return self.query(**kwargs)

    def test_the_timeline_service_finds_the_same_tasks_without_waiting_for_the_dashboard(self):
        tasks, stats = self.service_query(mode="upcoming", limit=2)
        self.assertEqual([task.title for task in tasks], ["Tarea 3", "Tarea 4"])
        self.assertEqual(stats["timeline_source"], "service")
        self.assertEqual(stats["dashboard_load_more"], 0)
        self.assertTrue(all(task.course == "Materia A" and task.due_at for task in tasks))
        self.assertEqual(tasks[0].due_at, (self.now + timedelta(days=3)).isoformat())
        self.assertIn("todas las entregas futuras", stats["coverage"])
        # Una sola petición JSON con la clave de sesión de la página; ni índices ni actividades abiertas.
        self.assertEqual(len(self.service_calls), 1)
        self.assertIn("sesskey=clave123", self.service_calls[0]["url"])
        self.assertEqual(self.service_calls[0]["methodname"], "core_calendar_get_action_events_by_timesort")
        self.assertFalse(any("/mod/assign/" in url or "/my/" in url for url in self.visited))

    def test_the_timeline_service_asks_for_more_events_only_when_needed(self):
        with patch("moodle_tasks.moodle_api.EVENTS_PER_REQUEST", 2):
            tasks, _ = self.service_query(mode="upcoming", limit=2)
        self.assertEqual([task.title for task in tasks], ["Tarea 3", "Tarea 4"])
        # Páginas de dos eventos: [Tarea 1, cuestionario], [Tarea 2, Tarea 3], [Tarea 4]. Se detiene al tener dos tareas.
        self.assertEqual([call["args"].get("aftereventid") for call in self.service_calls], [None, 99, 103])

    def test_the_timeline_service_skips_courses_where_the_enrolment_is_suspended(self):
        # Igual que el bloque de línea de tiempo de Moodle, que siempre pide limittononsuspendedevents=true.
        self.service_ids = (1, 2, 3)
        self.suspended_ids = (4,)
        tasks, _ = self.service_query(mode="upcoming", limit=5)
        self.assertEqual([task.title for task in tasks], ["Tarea 3"])
        self.assertTrue(all(call["args"].get("limittononsuspendedevents") is True for call in self.service_calls))

    def test_the_timeline_service_keeps_the_rules_for_action_texts(self):
        self.tasks[3]["action_text"] = "Hantar tugasan"
        self.tasks[4]["action_text"] = "Editar entrega"
        tasks, stats = self.service_query(mode="upcoming", limit=5)
        self.assertEqual([task.title for task in tasks], ["Tarea 3"])
        self.assertEqual(stats["availability_unconfirmed"], 1)
        self.assertEqual(stats["unrecognized_action_texts"], ["Hantar tugasan"])

    def test_an_empty_timeline_service_is_a_complete_answer(self):
        self.service_ids = ()
        tasks, stats = self.service_query(mode="upcoming", limit=5)
        self.assertEqual(tasks, [])
        self.assertEqual(stats["timeline_status"], "empty")
        self.assertFalse(any("/mod/assign/index.php" in url or "courses.php" in url for url in self.visited))

    def test_a_failing_service_falls_back_to_the_dashboard(self):
        self.service_error = True
        tasks, stats = self.service_query(mode="upcoming", limit=2)
        self.assertEqual([task.title for task in tasks], ["Tarea 3", "Tarea 4"])
        self.assertEqual(stats["timeline_source"], "page")
        self.assertIn("invalidparameter", stats["service_error"])
        self.assertEqual(stats["dashboard_load_more"], 1)

    def test_the_courses_service_uses_the_filter_chosen_in_my_courses(self):
        tasks, stats = self.service_query(mode="all", limit=None)
        self.assertEqual([task.title for task in tasks], ["Vencida", "Pendiente reciente", "Pendiente anterior", "Aún no abierta"])
        self.assertEqual(stats["courses_source"], "service")
        self.assertEqual(stats["courses_found"], 2)
        self.assertEqual([call["args"]["classification"] for call in self.service_calls], ["inprogress"])

    def test_a_filter_the_service_cannot_reproduce_reads_the_course_cards(self):
        self.grouping = "customfield"
        tasks, stats = self.service_query(mode="all", limit=None)
        self.assertEqual(len(tasks), 4)
        self.assertEqual(stats["courses_source"], "page")
        self.assertEqual(self.service_calls, [])

    def test_overdue_excludes_future_deadlines(self):
        overdue, _ = self.query(mode="overdue", limit=None)
        self.assertEqual([task.title for task in overdue], ['Vencida'])

    def test_timeline_loads_more_to_replace_a_task_that_is_not_yet_open(self):
        self.timeline_ids = (6, 3)
        tasks, stats = self.query(mode='upcoming', limit=2)
        self.assertEqual([task.url.rsplit('=', 1)[1] for task in tasks], ['3', '4'])
        self.assertEqual(stats['dashboard_load_more'], 1)

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
