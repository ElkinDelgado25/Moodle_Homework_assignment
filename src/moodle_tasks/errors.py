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
