"""Comprobación explícita del estado para la terminal."""

import argparse
from pathlib import Path

from .main import config_values, load_config
from .setup import verify_credentials
from .storage import default_env_file
from .ui import ConnectionState, show_dashboard


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mcp-moodle status", description=__doc__)
    parser.add_argument("--env-file", type=Path, default=default_env_file())
    args = parser.parse_args(argv)
    values = config_values(args.env_file)
    username = values.get("MOODLE_USERNAME")
    if any(not (values.get(key) or "").strip() for key in ("MOODLE_URL", "MOODLE_USERNAME", "MOODLE_PASSWORD")):
        show_dashboard(username, detail="Ejecuta mcp-moodle run para configurar tu cuenta.")
        return
    config = load_config(args.env_file)
    try:
        verify_credentials(config)
    except Exception as error:
        detail = str(error)
        for value in (config.username, config.password):
            detail = detail.replace(value, "[oculto]")
        show_dashboard(username, ConnectionState.PROBLEMS, detail=detail)
        raise SystemExit(1) from None
    show_dashboard(username, ConnectionState.CONNECTED, detail="Acceso a Moodle verificado en esta consulta.")
