"""Nombre del sistema operativo para la instalación guiada."""

import platform


def describe_system() -> str:
    system = platform.system()
    if system == "Windows":
        return "Windows " + platform.release()
    if system == "Darwin":
        return "macOS"
    if system != "Linux":
        return system or "Sistema desconocido"
    try:
        data = platform.freedesktop_os_release()
    except OSError:
        return "Linux"
    name = data.get("PRETTY_NAME") or data.get("NAME") or "Linux"
    identifiers = {data.get("ID", ""), *data.get("ID_LIKE", "").split()}
    if "arch" in identifiers and data.get("ID") != "arch":
        return name + " (basado en Arch Linux)"
    return name
