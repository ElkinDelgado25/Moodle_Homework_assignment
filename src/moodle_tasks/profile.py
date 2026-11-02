"""Nombre y materias leídos en Moodle al verificar la cuenta."""

import json
import re
from pathlib import Path

from playwright.sync_api import Page

from .main import Config, open_page
from .storage import atomic_write, user_config_dir


TEXT_FIELDS = ("materia", "nombre_docente", "carrera", "curso", "anio",
               # Claves de versiones anteriores, que se siguen leyendo.
               "subject", "teacher", "student_1", "student_2", "degree", "class_group", "year")
SKIP_COURSES = re.compile(r"^(?:mis cursos|all courses|cursos|courses)$", re.IGNORECASE)


def profile_file(directory: Path | None = None) -> Path:
    return (directory or user_config_dir()) / "document_profile.json"


CONTROL = re.compile("[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


def _profile_text(value: object) -> str | None:
    """Texto limpio de una línea; los números (p. ej. el año) se aceptan como texto."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = " ".join(CONTROL.sub(" ", value).split())
    return value[:200] if value else None


def public_profile(data: object) -> dict:
    """Conserva los campos de portada válidos y la lista de materias; descarta solo lo inválido."""
    if not isinstance(data, dict):
        raise ValueError("Se esperaba un objeto JSON con valores de texto.")
    result: dict = {}
    for key in TEXT_FIELDS:
        value = _profile_text(data.get(key))
        if value:
            result[key] = value
    students = data.get("estudiantes")
    if isinstance(students, list):
        cleaned_students = [text for text in (_profile_text(item) for item in students) if text]
        if cleaned_students:
            result["estudiantes"] = list(dict.fromkeys(cleaned_students))
    courses = data.get("courses")
    if isinstance(courses, list):
        cleaned = [text for text in (_profile_text(item) for item in courses) if text]
        if cleaned:
            result["courses"] = list(dict.fromkeys(cleaned))
    return result


def load_profile(directory: Path | None = None) -> dict:
    path = profile_file(directory)
    if not path.is_file():
        return {}
    return public_profile(json.loads(path.read_text(encoding="utf-8")))


def _clean_label(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def read_identity(page: Page, config: Config) -> tuple[str, list[str]]:
    """Lee el nombre visible y las materias de Mis cursos, sin inventar otros datos."""
    name = ""
    for selector in (".usermenu .usertext", "#usermenu .usertext", ".logininfo .usertext", ".usertext"):
        nodes = page.locator(selector)
        if not nodes.count():
            continue
        candidate = _clean_label(nodes.first.inner_text())
        if candidate and "@" not in candidate:
            name = candidate
            break
    open_page(page, config.base_url.rstrip("/") + "/my/courses.php")
    titles = page.locator("a[href*='/course/view.php']").evaluate_all(
        "(anchors) => anchors.map((anchor) => (anchor.innerText || '').replace(/\\s+/g, ' ').trim())"
    )
    courses: list[str] = []
    seen: set[str] = set()
    for title in titles:
        if not isinstance(title, str):
            continue
        label = _clean_label(title)
        key = label.casefold()
        if not label or SKIP_COURSES.fullmatch(label) or key in seen:
            continue
        seen.add(key)
        courses.append(label)
    return name, courses


def record_verified_profile(page: Page, config: Config, directory: Path | None = None) -> dict:
    """Actualiza nombre y materias. No escribe docente, curso ni año."""
    name, courses = read_identity(page, config)
    path = profile_file(directory)
    current: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            current = public_profile(loaded) if isinstance(loaded, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            current = {}
    if name:
        current["student_1"] = name
    if courses:
        current["courses"] = courses
    if name or courses:
        atomic_write(path, json.dumps(current, ensure_ascii=False, indent=2) + "\n")
    return {"student_1": current.get("student_1", ""), "courses": list(current.get("courses", []))}
