"""Configuración de la cuenta de Moodle: credentials.env y variables de entorno.

No importa Playwright ni el resto de la aplicación: el CLI la lee al arrancar cualquier comando.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from .storage import default_env_file


@dataclass(frozen=True)
class Config:
    base_url: str
    username: str
    password: str = field(repr=False)
    session_cache: bool = True


ENV_FILE = default_env_file()


def config_values(env_file: Path | None = None) -> dict[str, str | None]:
    return {**dotenv_values(env_file or default_env_file(), interpolate=False), **os.environ}


def required_env(name: str, values: dict[str, str | None]) -> str:
    value = (values.get(name) or "").strip()
    if not value:
        raise ValueError(f"Falta la variable {name}. Ejecuta mcp-moodle run para configurar tu cuenta.")
    return value


OPT_OUT = ("0", "false", "no", "off", "n")


def load_config(env_file: Path | None = None) -> Config:
    # El archivo se lee una sola vez: el entorno gana sobre él, salvo en la opción de privacidad de abajo.
    file_values = dotenv_values(env_file or default_env_file(), interpolate=False)
    values = {**file_values, **os.environ}
    return Config(
        base_url=required_env("MOODLE_URL", values).rstrip("/"),
        username=required_env("MOODLE_USERNAME", values),
        password=required_env("MOODLE_PASSWORD", values),
        # Desactivar la caché de sesión es una opción de privacidad: gana si lo indica el archivo o el entorno.
        session_cache=not any((value or "").strip().lower() in OPT_OUT for value in (
            values.get("MOODLE_SESSION_CACHE"), file_values.get("MOODLE_SESSION_CACHE"))),
    )
