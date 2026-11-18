"""Servicios AJAX de Moodle que usan sus propias páginas, llamados con la sesión del navegador.

Son los mismos que usan la línea de tiempo y Mis cursos: devuelven JSON en una petición en vez de
esperar a que el tema dibuje las tarjetas y pulsar «Mostrar más». Quien los llama debe tener un
respaldo: un Moodle antiguo, un servicio desactivado o una respuesta inesperada lanzan
MoodleServiceError y la búsqueda vuelve a leer la página.
"""

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page

from .config import Config

SERVICE_TIMEOUT_MS = 15_000
EVENTS_PER_REQUEST = 50          # máximo que admite core_calendar_get_action_events_by_timesort
MAX_EVENT_REQUESTS = 20
FETCH_JSON = """async ([url, body, timeout]) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
        const response = await fetch(url, {method: 'POST', credentials: 'same-origin', body, signal: controller.signal,
                                           headers: {'Content-Type': 'application/json'}});
        return {status: response.status, text: await response.text()};
    } finally {
        clearTimeout(timer);
    }
}"""
SESSKEY = "() => (window.M && M.cfg && typeof M.cfg.sesskey === 'string') ? M.cfg.sesskey : null"
SESSKEY_PATTERN = re.compile(r"^[A-Za-z0-9]{6,32}$")


class MoodleServiceError(RuntimeError):
    """El servicio no está disponible o no respondió como se esperaba: hay que leer la página."""


def sesskey(page: Page) -> str:
    """Clave de sesión de la página de Moodle abierta (M.cfg o el enlace de salir)."""
    try:
        key = page.evaluate(SESSKEY)
        logout = page.locator("a[href*='/login/logout.php']").first
        if not key and logout.count():
            # El enlace llega en el HTML inicial: no se espera a que aparezca.
            key = (parse_qs(urlsplit(logout.get_attribute("href") or "").query).get("sesskey") or [None])[0]
    except Exception as error:
        raise MoodleServiceError("No se pudo leer la clave de sesión de Moodle.") from error
    if not isinstance(key, str) or not SESSKEY_PATTERN.fullmatch(key):
        raise MoodleServiceError("La página no tiene una clave de sesión de Moodle.")
    return key


def call_service(page: Page, config: Config, method: str, args: dict) -> dict:
    """Un servicio de /lib/ajax/service.php con la sesión y la clave de la página abierta."""
    url = f"{config.base_url}/lib/ajax/service.php?sesskey={sesskey(page)}&info={method}"
    body = json.dumps([{"index": 0, "methodname": method, "args": args}])
    try:
        response = page.evaluate(FETCH_JSON, [url, body, SERVICE_TIMEOUT_MS])
    except Exception as error:
        raise MoodleServiceError(f"No se pudo llamar a {method}.") from error
    if not isinstance(response, dict) or response.get("status") != 200:
        raise MoodleServiceError(f"{method} respondió con HTTP {(response or {}).get('status')}.")
    try:
        payload = json.loads(response.get("text") or "")
    except ValueError:
        raise MoodleServiceError(f"{method} no devolvió JSON.") from None
    if isinstance(payload, dict) and payload.get("error"):
        # Así responde Moodle a una sesión vencida o a un servicio que no existe en esa versión.
        raise MoodleServiceError(f"{method} devolvió un error: {payload.get('errorcode') or payload.get('error')}")
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise MoodleServiceError(f"{method} devolvió una respuesta inesperada.")
    result = payload[0]
    if result.get("error"):
        exception = result.get("exception") or {}
        raise MoodleServiceError(f"{method} devolvió un error: {exception.get('errorcode') or 'desconocido'}")
    data = result.get("data")
    if not isinstance(data, dict):
        raise MoodleServiceError(f"{method} devolvió datos inesperados.")
    return data


def action_events(page: Page, config: Config, since: datetime):
    """Eventos de la línea de tiempo desde since, en orden de fecha, pidiendo más solo si hacen falta.

    El primer error se lanza antes de producir ningún evento; uno posterior deja la lista incompleta.
    """
    after = None
    for _ in range(MAX_EVENT_REQUESTS):
        args = {"timesortfrom": int(since.timestamp()), "limitnum": EVENTS_PER_REQUEST}
        if after is not None:
            args["aftereventid"] = after
        data = call_service(page, config, "core_calendar_get_action_events_by_timesort", args)
        events = data.get("events")
        if not isinstance(events, list):
            raise MoodleServiceError("La línea de tiempo devolvió eventos inesperados.")
        yield from (event for event in events if isinstance(event, dict))
        last = data.get("lastid")
        if len(events) < EVENTS_PER_REQUEST or not isinstance(last, int) or last == after:
            return
        after = last
    raise RuntimeError("Se alcanzó el límite de paginación de la línea de tiempo.")


def enrolled_courses(page: Page, config: Config, classification: str) -> list[dict]:
    """Cursos de Mis cursos con el mismo filtro que eligió el estudiante (classification)."""
    data = call_service(page, config, "core_course_get_enrolled_courses_by_timeline_classification",
                        {"classification": classification, "limit": 0, "offset": 0, "sort": "fullname"})
    courses = data.get("courses")
    if not isinstance(courses, list):
        raise MoodleServiceError("Mis cursos devolvió cursos inesperados.")
    return [course for course in courses if isinstance(course, dict)]
