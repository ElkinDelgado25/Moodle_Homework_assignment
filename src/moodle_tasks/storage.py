"""Configuración personal independiente de la carpeta donde se instaló el paquete."""

import os
import sys
import tempfile
from pathlib import Path


def user_config_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library/Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "moodle-homework-assignment"


def default_env_file() -> Path:
    personal = user_config_dir() / "credentials.env"
    if personal.is_file():
        return personal
    # Compatibilidad con el .env de un checkout de desarrollo.
    project = Path(__file__).resolve().parents[2]
    if (project / "pyproject.toml").is_file() and (project / ".env").is_file():
        return project / ".env"
    return personal


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".moodle-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_credentials(path: Path, url: str, username: str, password: str) -> None:
    def quoted(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    values = {"MOODLE_URL": url, "MOODLE_USERNAME": username,
              "MOODLE_PASSWORD": password, "MOODLE_HEADLESS": "true"}
    atomic_write(path, "".join(f"{name}={quoted(value)}\n" for name, value in values.items()))
