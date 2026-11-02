import base64
import html
import json
import re
from urllib.parse import quote, quote_plus


def _variants(value: str) -> set[str]:
    """Formas en que una credencial puede aparecer dentro de un error: URL, JSON, HTML o repr."""
    forms = {value, quote(value, safe=""), quote_plus(value), repr(value)[1:-1], json.dumps(value)[1:-1],
             html.escape(value, quote=True), html.escape(value, quote=False)}
    return {form for form in forms if form}


def redact_credentials(error: object, credentials: tuple[str | None, ...]) -> str:
    """Oculta credenciales conocidas, incluso escapadas o con otras mayúsculas.

    Un secreto de menos de 4 caracteres solo se oculta como palabra completa, para no
    destrozar el mensaje sustituyendo letras sueltas.
    """
    message = str(error)
    values = [value for value in credentials if value]
    patterns: list[tuple[str, bool]] = []
    for value in values:
        short = len(value) < 4
        patterns.extend((variant, short) for variant in _variants(value))
    if len(values) >= 2:
        pair = f"{values[0]}:{values[1]}".encode()
        patterns.append((base64.b64encode(pair).decode(), False))
    for variant, short in sorted(set(patterns), key=lambda item: len(item[0]), reverse=True):
        expression = re.escape(variant)
        if short:
            expression = rf"(?<![\w]){expression}(?![\w])"
        message = re.sub(expression, "[oculto]", message, flags=re.IGNORECASE)
    return message


class MoodleAuthenticationError(RuntimeError):
    """Moodle rechazó las credenciales introducidas."""


class MoodleHTTPError(RuntimeError):
    """Error HTTP con un mensaje comprensible para la persona que consulta."""

    def __init__(self, status: int, url: str):
        self.status = status
        if 500 <= status < 600:
            message = (
                "Por ahora no se pudieron consultar tus tareas porque Moodle tiene un error "
                "del servidor. Inténtalo de nuevo más tarde."
            )
        else:
            message = f"Moodle no pudo cargar la página (HTTP {status}): {url}"
        super().__init__(message)
