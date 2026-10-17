"""Comprobación explícita del estado para la terminal."""

import argparse
from pathlib import Path

from .errors import redact_credentials
from .main import config_values, load_config
from .setup import verify_credentials
from .ui import ConnectionState, show_dashboard
from .updates import check_for_updates, show_update_notice


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mcp-moodle status", description=__doc__)
    # config_values/load_config resuelven la ruta personal solo si no se indicó una.
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args(argv)
    show_update_notice(check_for_updates())
    values = config_values(args.env_file)
    username = values.get("MOODLE_USERNAME")
    if any(not (values.get(key) or "").strip() for key in ("MOODLE_URL", "MOODLE_USERNAME", "MOODLE_PASSWORD")):
        show_dashboard(username, detail="Ejecuta mcp-moodle run para configurar tu cuenta.")
        return
    config = load_config(args.env_file)
    try:
        identity = verify_credentials(config)
    except Exception as error:
        detail = redact_credentials(error, (config.username, config.password))
        show_dashboard(username, ConnectionState.PROBLEMS, detail=detail)
        raise SystemExit(1) from None
    detail = "Acceso a Moodle verificado en esta consulta."
    if isinstance(identity, dict):
        if identity.get("student_1"):
            detail += f" Nombre: {identity['student_1']}."
        courses = identity.get("courses") or []
        if courses:
            detail += f" Materias: {len(courses)}."
    show_dashboard(username, ConnectionState.CONNECTED, detail=detail)
