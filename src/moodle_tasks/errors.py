from urllib.parse import quote, quote_plus


def redact_credentials(error: object, credentials: tuple[str | None, ...]) -> str:
    """Oculta credenciales conocidas, incluso si aparecen escapadas en un error."""
    message = str(error)
    variants = set()
    for value in credentials:
        if value:
            variants.update((value, quote(value, safe=""), quote_plus(value), repr(value)[1:-1]))
    for value in sorted(variants, key=len, reverse=True):
        message = message.replace(value, "[oculto]")
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
