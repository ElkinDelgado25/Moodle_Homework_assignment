"""Configuración opcional y privada de Sentry."""

from collections.abc import Mapping

_initialized = False


def initialize_sentry(values: Mapping[str, str | None]) -> None:
    """Activa Sentry solo con DSN y omite contexto potencialmente privado."""
    global _initialized
    dsn = (values.get("SENTRY_DSN") or "").strip()
    if _initialized or not dsn:
        return

    import sentry_sdk

    def scrub_event(event: dict, hint: dict) -> dict:
        event.pop("request", None)
        event.pop("user", None)
        event.pop("breadcrumbs", None)
        event.pop("contexts", None)
        return event

    sentry_sdk.init(
        dsn=dsn,
        environment=(values.get("SENTRY_ENVIRONMENT") or "production").strip(),
        send_default_pii=False,
        include_local_variables=False,
        traces_sample_rate=0,
        before_send=scrub_event,
    )
    _initialized = True
