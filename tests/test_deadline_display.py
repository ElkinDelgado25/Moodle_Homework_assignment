import unittest
from datetime import datetime, timedelta

from moodle_tasks.main import Assignment
from moodle_tasks.server import deadline_display, pending_table


class DeadlineDisplayTests(unittest.TestCase):
    def test_remaining_time_handles_days_hours_minutes_and_expiration(self):
        now = datetime(2026, 10, 8, 15, 59)
        cases = [
            (timedelta(days=3, hours=8), 'quedan 3 días y 8 horas'),
            (timedelta(days=1, hours=1), 'quedan 1 día y 1 hora'),
            (timedelta(hours=1), 'queda 1 hora'),
            (timedelta(hours=2), 'quedan 2 horas'),
            (timedelta(minutes=25), 'quedan 25 minutos'),
            (timedelta(minutes=1), 'queda 1 minuto'),
            (timedelta(seconds=30), 'queda menos de 1 minuto'),
            (timedelta(), 'vence ahora'),
            (timedelta(seconds=-1), 'plazo vencido'),
        ]
        for delta, expected in cases:
            with self.subTest(delta=delta):
                due = now + delta
                task = Assignment('Tarea', 'https://moodle.test/task', '', '', '', False, due_at=due.isoformat())
                self.assertEqual(deadline_display(task, now), f'{due:%d/%m/%Y %H:%M} ({expected})')

    def test_table_places_remaining_time_inside_deadline_cell(self):
        task = Assignment('Tarea', 'https://moodle.test/task', '', '', '', False,
                          course='Materia', due_at='2026-10-11T23:59:00')
        table = pending_table([task], now=datetime(2026, 10, 8, 15, 59))
        self.assertIn('| 11/10/2026 23:59 (quedan 3 días y 8 horas) |', table)

    def test_unknown_deadline_does_not_invent_remaining_time(self):
        task = Assignment('Tarea', 'https://moodle.test/task', '', 'Sin fecha', '', False)
        self.assertEqual(deadline_display(task, datetime(2026, 10, 8)), 'Sin fecha')
