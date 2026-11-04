"""Configuración portable de la salida de la terminal."""

import sys


def configure_utf8_streams() -> None:
    """Evita errores al imprimir Unicode en terminales de Windows (cp1252, SSH, redirecciones)."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass
