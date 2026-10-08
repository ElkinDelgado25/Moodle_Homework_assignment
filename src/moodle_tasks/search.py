"""Búsqueda por línea de tiempo o índices de tareas, con alcance explícito."""

import hashlib
import json
import re
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .main import Assignment, Config, is_pending, open_page, read_assignment, submission_state
from .storage import atomic_write, user_config_dir


MODES = ("upcoming", "recent", "overdue", "all")
CACHE_SECONDS = 900
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
    parsed = urlsplit(url)
    base = urlsplit(base_url)
    identifier = parse_qs(parsed.query).get("id", [""])[0]
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        return None
    if parsed.path != "/mod/assign/view.php" or not identifier.isdigit():
        return None
    # Evita seguir botones de editar, borrar o entregar una actividad.
    return f"{base_url}/mod/assign/view.php?id={identifier}"


def dashboard_candidates(page: Page, config: Config, stats: dict):
    open_page(page, config.base_url + "/my/")
    stats["dashboard_pages_read"] += 1
    region = page.locator(".block_timeline, [data-block='timeline']").first
    if not region.count():
        return
    try:
        region.locator("[data-region='event-list-item']").first.wait_for(state="attached", timeout=10_000)
    except PlaywrightTimeoutError:
        return
    stats["dashboard_filter"] = " ".join(region.locator("button").all_text_contents()).strip()
    stats["dashboard_filter"] = " ".join(stats["dashboard_filter"].split())
    if re.search(r"Ordenar por cursos|Sort by courses", stats["dashboard_filter"], re.I):
        return
    seen = set()
    for _ in range(100):
        links = region.locator("[data-region='event-list-item'] a[href*='/mod/assign/view.php']").evaluate_all(
            "aa => aa.map(a => ({url:a.href, title:a.innerText}))")
        for link in links:
            url = assignment_url(link["url"], config.base_url)
            if url and url not in seen:
                seen.add(url)
                yield {"url": url, "title": link["title"], "course": "", "row": None}
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


def index_candidates(page: Page, config: Config, stats: dict, errors: list[str]) -> list[dict]:
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
            course_id = parse_qs(parsed.query).get("id", [""])[0]
            if parsed.netloc == urlsplit(config.base_url).netloc and course_id.isdigit():
                courses.setdefault(course_id, link["title"])
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
    for course_id, course in courses.items():
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


def cache_path(config: Config) -> Path:
    identity = hashlib.sha256((config.base_url + "\0" + config.username).encode()).hexdigest()
    return user_config_dir() / "cache" / (identity + ".json")


def search_assignments(page: Page, config: Config, *, mode: str = "upcoming", limit: int | None = 5,
                       only_pending: bool = True, refresh: bool = False,
                       stats: dict | None = None) -> tuple[list[Assignment], list[str]]:
    if mode not in MODES or limit is not None and limit < 1:
        raise ValueError("Modo o límite de consulta inválido.")
    stats = stats if stats is not None else {}
    stats.update(mode=mode, source="course_indexes", dashboard_pages_read=0, dashboard_load_more=0,
                 index_pages_read=0, detail_pages_read=0, cached_details=0, candidates_checked=0)
    errors = []
    tasks = []
    seen = set()
    now = datetime.now()
    cache_file = cache_path(config)
    try:
        cache = json.loads(cache_file.read_text())
        if not isinstance(cache, dict) or cache.get("version") != 1:
            cache = {"version": 1, "entries": {}}
    except (OSError, ValueError):
        cache = {"version": 1, "entries": {}}
    if not isinstance(cache.get("entries"), dict):
        cache["entries"] = {}

    def inspect(candidate):
        url = candidate["url"]
        if url in seen:
            return
        seen.add(url)
        stats["candidates_checked"] += 1
        if only_pending and not candidate_pending(candidate):
            return
        fingerprint = candidate.get("row")
        entry = cache.get("entries", {}).get(url, {})
        if not isinstance(entry, dict):
            entry = {}
        try:
            # La caché solo se usa con un índice de entregas recién consultado.
            cached_task = None
            try:
                if (not refresh and fingerprint and entry.get("row") == fingerprint
                        and 0 <= time.time() - entry.get("time", 0) < CACHE_SECONDS):
                    cached_task = Assignment(**entry["task"])
            except (TypeError, ValueError, KeyError):
                pass
            if cached_task is not None:
                task = cached_task
                stats["cached_details"] += 1
            else:
                stats["detail_pages_read"] += 1
                task = read_assignment(page, url)
                task = replace(task, course=candidate.get("course") or task.course,
                               title=candidate.get("title") or task.title)
                cache.setdefault("entries", {})[url] = {"row": fingerprint, "time": time.time(), "task": asdict(task)}
            if only_pending and not is_pending(task):
                return
            due = datetime.fromisoformat(task.due_at) if task.due_at else None
            opening = datetime.fromisoformat(task.opens_at) if task.opens_at else None
            if mode == "upcoming" and (due is None or due < now):
                return
            if mode == "overdue" and (due is None or due >= now):
                return
            if mode == "recent" and (opening is None or opening > now):
                return
            tasks.append(task)
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
    if mode != "upcoming" or not tasks or errors:
        stats["source"] = "course_indexes" if not tasks else "dashboard_and_course_indexes"
        for candidate in index_candidates(page, config, stats, errors):
            inspect(candidate)
    if mode == "recent":
        tasks.sort(key=lambda task: task.opens_at or "", reverse=True)
    else:
        tasks.sort(key=lambda task: task.due_at or "9999")
    stats["matched_count"] = len(tasks)
    stats["coverage"] = (
        "Línea de tiempo con su filtro actual; no incluye necesariamente tareas vencidas, sin fecha o fuera del filtro."
        if stats["source"] == "dashboard" else
        "Índices de tareas de los cursos visibles en Mis cursos; otras actividades o cursos ocultos pueden quedar fuera."
    )
    try:
        atomic_write(cache_file, json.dumps(cache, ensure_ascii=False))
    except OSError:
        errors.append("No se pudo actualizar la caché local; la consulta de Moodle sí se realizó.")
    return tasks[:limit] if limit is not None else tasks, errors
