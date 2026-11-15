"""Presentación de listados de tareas: nombre de la materia, cierre legible y tabla Markdown.

Lo usan el servidor MCP y mcp-moodle tasks sin que la terminal cargue el servidor.
"""

import re
from datetime import datetime

from .core import Assignment, clean_text


# Partes que Moodle añade al nombre completo del curso, sea cual sea la carrera:
# el paralelo delante («A -- »), la carrera con el año de la malla («/ SOFTWARE 2024 - NS»)
# y los códigos del curso y del periodo («--1208690--20262-1»).
COURSE_SECTION = re.compile(r"^[A-Z0-9]{1,3}\s*--\s*")
COURSE_SUFFIX = re.compile(r"\s*/\s*[^/]*\b(?:19|20)\d{2}\b[^/]*$|\s*--\s*\d.*$")


def course_name(raw: str | None) -> str:
    """Nombre de la materia sin el paralelo, la carrera ni los códigos del periodo que Moodle le añade.

    Una barra dentro del nombre («ÉTICA / DEONTOLOGÍA») se conserva: solo se recorta si lo que sigue
    lleva el año de la malla, como el segmento de la carrera.
    """
    name = COURSE_SECTION.sub("", clean_text(raw))
    return COURSE_SUFFIX.sub("", name).strip()


def deadline_display(task: Assignment, now: datetime) -> str:
    if not task.due_at:
        return task.due_date
    due = datetime.fromisoformat(task.due_at)
    seconds = (due - now).total_seconds()
    if seconds < 0:
        remaining = "plazo vencido"
    elif seconds == 0:
        remaining = "vence ahora"
    elif seconds < 60:
        remaining = "queda menos de 1 minuto"
    else:
        minutes = int(seconds // 60)
        days, minutes = divmod(minutes, 24 * 60)
        hours, minutes = divmod(minutes, 60)
        if days:
            remaining = f"quedan {days} {'día' if days == 1 else 'días'} y {hours} {'hora' if hours == 1 else 'horas'}"
        elif hours:
            remaining = f"{'queda' if hours == 1 else 'quedan'} {hours} {'hora' if hours == 1 else 'horas'}"
        else:
            remaining = f"{'queda' if minutes == 1 else 'quedan'} {minutes} {'minuto' if minutes == 1 else 'minutos'}"
    return f"{due:%d/%m/%Y %H:%M} ({remaining})"


def pending_table(tasks: list[Assignment], *, now: datetime | None = None, mode: str = "upcoming",
                  only_pending: bool = True, incomplete: bool = False) -> str:
    """Tabla lista para mostrar; el encabezado dice qué se listó de verdad."""
    now = now or datetime.now()
    kind = "tareas pendientes" if only_pending else "tareas"
    heading = {"overdue": "Estas son las tareas vencidas", "all": f"Estas son las {kind} de todas las materias"}.get(
        mode, f"Estas son las {kind}")
    if not tasks:
        return ("No se pudo confirmar si hay tareas: la consulta quedó incompleta." if incomplete
                else f"No se encontraron {kind} entre las actividades revisadas.")

    def cell(value: str) -> str:
        return " ".join(value.split()).replace("\\", "\\\\").replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")

    rows = [heading, "", "| Tarea | Materia | Cierre (fecha y hora) |",
            "|---|---|---|"]
    for task in tasks:
        course = course_name(task.course)
        due = deadline_display(task, now)
        rows.append(f"| [{cell(task.title)}]({task.url}) | {cell(course) or 'Sin identificar'} | {cell(due)} |")
    return "\n".join(rows)
