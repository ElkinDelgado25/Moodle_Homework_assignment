"""Búsqueda por línea de tiempo o índices de tareas, con alcance explícito."""

import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .core import Assignment, Config, is_pending, open_page, submission_state
from .urls import assignment_view_id, moodle_path, parse_id


MODES = ("upcoming", "overdue", "all")
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_moodle_date(text: str) -> str | None:
    """Conserva la hora mostrada por Moodle; no inventa una zona horaria."""
    spanish = re.search(r"(\d{1,2}) de (\w+) de (\d{4}),?\s+(\d{1,2}):(\d{2})", text, re.I)
    english = re.search(r"(\d{1,2}) (\w+) (\d{4}),?\s+(\d{1,2}):(\d{2})(?:\s*([ap]m))?", text, re.I)
    match = spanish or english
    if not match:
        return None
    day, month, year, hour, minute = match.groups()[:5]
    month_number = MONTHS.get(month.lower())
    if not month_number:
        return None
    hour_number = int(hour)
    if match is english and match.group(6):
        hour_number = hour_number % 12 + (12 if match.group(6).lower() == "pm" else 0)
    try:
        return datetime(int(year), month_number, int(day), hour_number, int(minute)).isoformat()
    except ValueError:
        return None


def assignment_url(url: str, base_url: str) -> str | None:
    identifier = assignment_view_id(url, base_url)
    # Evita seguir botones de editar, borrar o entregar una actividad.
    return f"{base_url}/mod/assign/view.php?id={identifier}" if identifier else None


# El enlace action=editsubmission de la línea de tiempo sirve para «Agregar entrega» (sin entregar) y para
# «Editar entrega» (ya entregada): solo el texto los distingue. Un texto que no se reconoce deja la disponibilidad
# sin confirmar (null) en vez de descartar la tarea, que haría desaparecer pendientes sin ningún aviso.
TIMELINE_EVENTS = """events => events.flatMap(e => {
    const a = e.querySelector('a[href*="/mod/assign/view.php"]');
    if (!a) return [];
    const ADD = /Agregar entrega|Agregar envío|Añadir entrega|Añadir envío|Add submission|Adicionar (?:entrega|envio)|Ajouter un travail|Abgabe hinzufügen/i;
    const EDIT = /Editar entrega|Editar envío|Modificar entrega|Edit submission|Editar tarefa|Modifier le travail|Abgabe bearbeiten/i;
    const link = Array.from(e.querySelectorAll('a')).find(l => /[?&]action=editsubmission(?:&|$)/.test(l.href));
    const label = link ? link.textContent.trim() : '';
    const available = !link ? false : ADD.test(label) ? true : EDIT.test(label) ? false : null;
    return [{url:a.href, title:a.innerText.trim(),
        deadline:a.getAttribute('aria-label') || '',
        course:e.querySelector('.event-name-container > small')?.innerText.split('·').slice(1).join('·').trim() || '',
        available:available, actionText: available === null ? label : ''}];
})"""


def dashboard_candidates(page: Page, config: Config, stats: dict):
    open_page(page, config.base_url + "/my/")
    stats["dashboard_pages_read"] += 1
    region = page.locator(".block_timeline, [data-block='timeline']").first
    if not region.count():
        stats["timeline_status"] = "missing"
        return
    items = region.locator("[data-region='event-list-item']")
    # El mensaje de lista vacía ya existe oculto en el HTML inicial; solo cuenta cuando se muestra.
    empty = region.locator(
        "[data-region='no-events-empty-message'], [data-region='empty-message'], .empty-placeholder-image-lg"
    ).filter(visible=True)
    try:
        # Espera lo que aparezca primero: actividades o el mensaje de lista vacía visible.
        items.first.or_(empty.first).wait_for(state="attached", timeout=10_000)
    except PlaywrightTimeoutError:
        stats["timeline_status"] = "timeout"
        return
    if not items.count():
        stats["timeline_status"] = "empty"
        return
    stats["timeline_status"] = "ok"
    stats["dashboard_filter"] = " ".join(region.locator("button").all_text_contents()).strip()
    stats["dashboard_filter"] = " ".join(stats["dashboard_filter"].split())
    if re.search(r"Ordenar por cursos|Sort by courses", stats["dashboard_filter"], re.I):
        stats["timeline_status"] = "sorted_by_course"
        return
    seen = set()
    for _ in range(100):
        links = region.locator("[data-region='event-list-item']").evaluate_all(TIMELINE_EVENTS)
        for link in links:
            url = assignment_url(link["url"], config.base_url)
            if url and url not in seen:
                seen.add(url)
                if link.get("actionText"):
                    unknown = stats.setdefault("unrecognized_action_texts", [])
                    if link["actionText"] not in unknown and len(unknown) < 5:
                        unknown.append(link["actionText"][:60])
                yield dict(link, url=url, row=None)
        more = region.get_by_role("button", name=re.compile(r"Mostrar más actividades|Show more activities", re.I))
        if not more.count() or not more.first.is_visible() or more.first.is_disabled():
            return
        before = region.locator("[data-region='event-list-item']").count()
        more.first.click()
        stats["dashboard_load_more"] += 1
        try:
            page.wait_for_function(
                "n => document.querySelectorAll('.block_timeline [data-region=event-list-item], [data-block=timeline] [data-region=event-list-item]').length > n",
                arg=before, timeout=10_000)
        except PlaywrightTimeoutError:
            raise RuntimeError("La línea de tiempo no terminó de cargar más actividades.") from None
    raise RuntimeError("Se alcanzó el límite de paginación de la línea de tiempo.")


def index_candidates(page: Page, config: Config, stats: dict, errors: list[str], progress=None) -> list[dict]:
    open_page(page, config.base_url + "/my/courses.php")
    try:
        page.locator("a[href*='/course/view.php']").first.wait_for(state="attached", timeout=10_000)
    except PlaywrightTimeoutError:
        errors.append("No se encontraron cursos en la vista Mis cursos.")
        return []
    courses = {}
    for _ in range(100):
        links = page.locator("a[href*='/course/view.php']").evaluate_all(
            "aa => aa.map(a => ({url:a.href, title:a.innerText.trim()}))")
        for link in links:
            parsed = urlsplit(link["url"])
            values = parse_qs(parsed.query).get("id", [])
            course_id = parse_id(values[0]) if len(values) == 1 else None
            if course_id and moodle_path(link["url"], config.base_url) == "/course/view.php":
                courses.setdefault(str(course_id), link["title"])
        more = page.get_by_role("button", name=re.compile(r"Mostrar más cursos|Show more courses", re.I))
        next_page = page.locator(".block_myoverview").get_by_role("link", name=re.compile(r"^Next$|^Siguiente$|Página siguiente", re.I))
        control = more.first if more.count() and more.first.is_visible() and not more.first.is_disabled() else next_page.first
        if not control.count() or not control.is_visible() or control.get_attribute("aria-disabled") == "true":
            break
        before = sorted(courses)
        control.click()
        try:
            page.wait_for_function(
                "ids => Array.from(document.querySelectorAll('a[href*=\"/course/view.php\"]')).some(a => !ids.includes(new URL(a.href).searchParams.get('id')))",
                arg=before, timeout=10_000)
        except PlaywrightTimeoutError:
            errors.append("No se pudo terminar de recorrer la paginación de Mis cursos.")
            break
    else:
        errors.append("Se alcanzó el límite de paginación de Mis cursos.")
    stats["courses_found"] = len(courses)
    candidates = {}
    for position, (course_id, course) in enumerate(courses.items()):
        if progress is not None:
            progress(position, len(courses), f"Revisando {course}")
        try:
            open_page(page, f"{config.base_url}/mod/assign/index.php?id={course_id}")
            stats["index_pages_read"] += 1
            links = page.locator("a[href*='/mod/assign/view.php']").evaluate_all(
                "aa => aa.map(a => ({url:a.href, title:a.innerText.trim(), row:a.closest('tr')?.innerText, cells:Array.from(a.closest('tr')?.querySelectorAll('td') || []).map(c=>c.innerText.trim())}))")
            for link in links:
                url = assignment_url(link["url"], config.base_url)
                if url:
                    candidates[url] = dict(link, url=url, course=course)
        except Exception as error:
            errors.append(f"No se pudo revisar el índice de {course}: {error}")
    return list(candidates.values())


def candidate_pending(candidate: dict) -> bool:
    cells = candidate.get("cells", [])
    if len(cells) < 4:
        return True
    # Índice Moodle: sección, título, fecha, entrega, calificación.
    if submission_state(cells[-2]) is True:
        return False
    return not bool(re.fullmatch(r"\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?", cells[-1]))


def search_assignments(page: Page, config: Config, *, mode: str = "upcoming", limit: int | None = 5,
                       only_pending: bool = True, stats: dict | None = None,
                       progress=None) -> tuple[list[Assignment], list[str]]:
    """Tareas de la línea de tiempo o de los índices de cada curso, sin abrir la página de cada una."""
    if mode not in MODES or limit is not None and limit < 1:
        raise ValueError("Modo o límite de consulta inválido.")
    stats = stats if stats is not None else {}
    stats.update(mode=mode, source="course_indexes", dashboard_pages_read=0, dashboard_load_more=0,
                 index_pages_read=0, candidates_checked=0)
    errors = []
    tasks = []
    seen = set()
    now = datetime.now()
    def inspect(candidate):
        url = candidate["url"]
        if url in seen:
            return
        seen.add(url)
        stats["candidates_checked"] += 1
        unconfirmed = False
        if only_pending and not candidate_pending(candidate):
            return
        try:
            cells = candidate.get("cells", [])
            due_text = candidate.get("deadline") or (cells[2] if len(cells) >= 3 else "")
            due_at = parse_moodle_date(due_text)
            available = candidate.get("available")
            if mode == "upcoming" and available is False:
                return
            # Una fila de un índice de curso (available=None) se acepta con disponibilidad sin confirmar.
            unconfirmed = mode == "upcoming" and available is None
            status = cells[-2] if len(cells) >= 5 else "Disponible para entregar" if available else "Estado desconocido"
            task = Assignment(candidate["title"], url, "", due_text, status,
                              submission_state(status) if cells else False if available else None,
                              course=candidate.get("course", ""), due_at=due_at)
            if only_pending and not is_pending(task):
                return
            due = datetime.fromisoformat(task.due_at) if task.due_at else None
            if mode == "upcoming" and (due is None or due < now):
                return
            if mode == "overdue" and (due is None or due >= now):
                return
            tasks.append(task)
            if unconfirmed:
                stats["availability_unconfirmed"] = stats.get("availability_unconfirmed", 0) + 1
        except Exception as error:
            errors.append(f"No se pudo leer {url}: {error}")

    if mode == "upcoming":
        stats["source"] = "dashboard"
        # Una página separada conserva la paginación mientras se leen detalles.
        timeline = page.context.new_page()
        try:
            for candidate in dashboard_candidates(timeline, config, stats):
                inspect(candidate)
                if limit is not None and len(tasks) >= limit:
                    break
        except Exception as error:
            errors.append(f"La consulta de la línea de tiempo quedó incompleta: {error}")
        finally:
            timeline.close()
    timeline_ok = stats.get("timeline_status") in ("ok", "empty")
    if mode != "upcoming" or errors or (not tasks and not timeline_ok):
        stats["source"] = "course_indexes" if not tasks else "dashboard_and_course_indexes"
        for candidate in index_candidates(page, config, stats, errors, progress):
            inspect(candidate)
    tasks.sort(key=lambda task: task.due_at or "9999")
    stats["matched_count"] = len(tasks)
    stats["coverage"] = (
        "Línea de tiempo con su filtro actual; no incluye necesariamente tareas vencidas, sin fecha o fuera del filtro."
        if stats["source"] == "dashboard" else
        "Índices de tareas de los cursos visibles en Mis cursos; otras actividades o cursos ocultos pueden quedar fuera."
    )
    return tasks[:limit] if limit is not None else tasks, errors
