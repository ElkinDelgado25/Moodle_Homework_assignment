"""Comprobación explícita del estado para la terminal."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .errors import redact_credentials
from .config import config_values, load_config
from .setup import verify_credentials
from .ui import ConnectionState, show_dashboard
from .updates import check_for_updates, show_update_notice


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mcp-moodle status", description=__doc__)
    # config_values/load_config resuelven la ruta personal solo si no se indicó una.
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args(argv)
    # La consulta a GitHub corre mientras se verifica Moodle: el aviso ya no retrasa la comprobación.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="update-check") as pool:
        update = pool.submit(check_for_updates)
        username, state, detail = connection_state(args.env_file)
        show_update_notice(update.result())
    show_dashboard(username, state, detail=detail)
    if state is ConnectionState.PROBLEMS:
        raise SystemExit(1)


def connection_state(env_file: Path | None) -> tuple[str | None, ConnectionState, str]:
    """(usuario, estado, detalle) sin imprimir nada: el aviso de versión se muestra antes del panel."""
    values = config_values(env_file)
    username = values.get("MOODLE_USERNAME")
    if any(not (values.get(key) or "").strip() for key in ("MOODLE_URL", "MOODLE_USERNAME", "MOODLE_PASSWORD")):
        return username, ConnectionState.NOT_STARTED, "Ejecuta mcp-moodle run para configurar tu cuenta."
    config = load_config(env_file)
    try:
        identity = verify_credentials(config)
    except Exception as error:
        return username, ConnectionState.PROBLEMS, redact_credentials(error, (config.username, config.password))
    detail = "Acceso a Moodle verificado en esta consulta."
    if isinstance(identity, dict):
        if identity.get("nombre"):
            detail += f" Nombre: {identity['nombre']}."
        courses = identity.get("courses") or []
        if courses:
            detail += f" Materias: {len(courses)}."
    return username, ConnectionState.CONNECTED, detail
