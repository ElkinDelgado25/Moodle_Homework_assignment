"""Nombre y materias leídos en Moodle al verificar la cuenta."""

import json
import re
import unicodedata
from pathlib import Path

from playwright.sync_api import Page

from .core import open_page

from .config import Config
from .storage import atomic_write, user_config_dir


TEXT_FIELDS = ("materia", "nombre_docente", "carrera", "curso", "anio",
               # Claves de versiones anteriores, que se siguen leyendo.
               "subject", "teacher", "degree", "class_group", "year")
# Hasta 0.4.4 los nombres se guardaban en student_1 (la cuenta verificada) y student_2.
# Al leer el perfil se convierten en «estudiantes», la única clave que se escribe ahora.
LEGACY_STUDENT_KEYS = ("student_1", "student_2")
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
    if not isinstance(students, list):
        students = [data.get(key) for key in LEGACY_STUDENT_KEYS]
    cleaned_students = [text for text in (_profile_text(item) for item in students) if text]
    if cleaned_students:
        result["estudiantes"] = list(dict.fromkeys(cleaned_students))
    courses = data.get("courses")
    if isinstance(courses, list):
        cleaned = [text for text in (_profile_text(item) for item in courses) if text]
        if cleaned:
            result["courses"] = list(dict.fromkeys(cleaned))
    teachers = data.get("teachers")
    if isinstance(teachers, dict):
        cleaned_teachers = {subject: teacher for subject, teacher in (
            (_profile_text(key), _profile_text(value)) for key, value in list(teachers.items())[:60]) if subject and teacher}
        if cleaned_teachers:
            result["teachers"] = cleaned_teachers
    return result


def subject_key(value: object) -> str:
    """Materia sin tildes, mayúsculas ni espacios repetidos, para comparar nombres escritos distinto."""
    text = unicodedata.normalize("NFD", " ".join(str(value or "").split()))
    return "".join(character for character in text if not unicodedata.combining(character)).casefold()


def teacher_for(profile: dict, subject: str) -> str:
    """Docente guardado para esa materia; el docente general del perfil solo vale para su propia materia."""
    key = subject_key(subject)
    for saved, teacher in (profile.get("teachers") or {}).items():
        if subject_key(saved) == key:
            return teacher
    general = profile.get("nombre_docente") or profile.get("teacher") or ""
    own = profile.get("materia") or profile.get("subject") or ""
    return general if general and (not own or subject_key(own) == key) else ""


def remember_teacher(subject: str, teacher: str, directory: Path | None = None) -> bool:
    """Guarda el docente indicado para una materia, para no volver a pedirlo en su próxima tarea."""
    subject, teacher = _profile_text(subject), _profile_text(teacher)
    if not subject or not teacher:
        return False
    path = profile_file(directory)
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(current, dict):
            return False
        teachers = current.get("teachers") if isinstance(current.get("teachers"), dict) else {}
        teachers = {key: value for key, value in teachers.items() if subject_key(key) != subject_key(subject)}
        teachers[subject] = teacher
        current["teachers"] = teachers
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(current, ensure_ascii=False, indent=2) + "\n")
        return True
    except (OSError, ValueError):
        return False


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
    """Actualiza nombre y materias. No escribe docente, curso ni año.

    El nombre verificado es siempre el primero de «estudiantes»; los compañeros que sigan se conservan.
    Devuelve {"nombre": ..., "courses": [...]}.
    """
    name, courses = read_identity(page, config)
    path = profile_file(directory)
    current: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            current = public_profile(loaded) if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            current = {}
    if name:
        partners = current.get("estudiantes", [])[1:]
        current["estudiantes"] = list(dict.fromkeys([name, *partners]))
    if courses:
        current["courses"] = courses
    if name or courses:
        atomic_write(path, json.dumps(current, ensure_ascii=False, indent=2) + "\n")
    return {"nombre": name or (current.get("estudiantes") or [""])[0], "courses": list(current.get("courses", []))}
