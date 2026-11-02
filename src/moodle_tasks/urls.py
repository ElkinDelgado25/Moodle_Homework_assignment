"""URLs e identificadores de Moodle: mismo origen, subrutas e ids estrictos."""

import re
from urllib.parse import parse_qs, urlsplit


ID_PATTERN = re.compile(r"[1-9][0-9]{0,17}", re.ASCII)
MAX_ID = 2**63 - 1


def _origin(value: str):
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or (443 if scheme == "https" else 80)


def same_origin(url: str, base_url: str) -> bool:
    try:
        return _origin(url) == _origin(base_url) and not urlsplit(url).username and not urlsplit(url).password
    except ValueError:
        return False


def moodle_path(url: str, base_url: str) -> str | None:
    """Ruta relativa a la raíz de Moodle (admite instalaciones en subcarpeta) o None si es otro sitio."""
    if not same_origin(url, base_url):
        return None
    prefix = urlsplit(base_url).path.rstrip("/")
    path = urlsplit(url).path
    if prefix and not (path == prefix or path.startswith(prefix + "/")):
        return None
    return path[len(prefix):] or "/"


def parse_id(value: object) -> int | None:
    """Entero positivo; rechaza bool, decimales, signos, espacios y dígitos no ASCII."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= MAX_ID else None
    if isinstance(value, str) and ID_PATTERN.fullmatch(value):
        number = int(value)
        return number if number <= MAX_ID else None
    return None


def assignment_view_id(url: str, base_url: str) -> int | None:
    try:
        if moodle_path(url, base_url) != "/mod/assign/view.php":
            return None
        values = parse_qs(urlsplit(url).query).get("id", [])
    except ValueError:
        return None
    return parse_id(values[0]) if len(values) == 1 else None
