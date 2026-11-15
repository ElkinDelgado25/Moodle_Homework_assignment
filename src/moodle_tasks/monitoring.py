"""Configuración opcional y privada de Sentry."""

from collections.abc import Mapping

from .errors import redact_credentials

_initialized = False


def _redact(value, credentials: tuple[str | None, ...]):
    if isinstance(value, str):
        return redact_credentials(value, credentials)
    if isinstance(value, dict):
        return {key: _redact(item, credentials) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, credentials) for item in value]
    return value


def scrub_event(event: dict, credentials: tuple[str | None, ...]) -> dict:
    """Quita el contexto privado y oculta las credenciales en todos los textos del evento.

    Cubre mensajes de excepción y de logging aunque el código que los lanzó no haya
    pasado antes por redact_credentials.
    """
    for key in ("request", "user", "breadcrumbs", "contexts"):
        event.pop(key, None)
    return _redact(event, credentials)


def initialize_sentry(values: Mapping[str, str | None]) -> None:
    """Activa Sentry solo con DSN y omite contexto potencialmente privado."""
    global _initialized
    dsn = (values.get("SENTRY_DSN") or "").strip()
    if _initialized or not dsn:
        return

    import sentry_sdk

    # Usuario primero y contraseña después: así también se oculta la pareja en base64.
    credentials = (values.get("MOODLE_USERNAME"), values.get("MOODLE_PASSWORD"))

    sentry_sdk.init(
        dsn=dsn,
        environment=(values.get("SENTRY_ENVIRONMENT") or "production").strip(),
        send_default_pii=False,
        include_local_variables=False,
        traces_sample_rate=0,
        before_send=lambda event, hint: scrub_event(event, credentials),
    )
    _initialized = True
