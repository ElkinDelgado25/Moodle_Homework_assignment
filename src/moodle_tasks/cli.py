"""Comandos de terminal de Moodle MCP."""

import argparse

from .console import configure_utf8_streams
from .core import config_values
from .monitoring import initialize_sentry


def main(argv: list[str] | None = None) -> None:
    configure_utf8_streams()
    parser = argparse.ArgumentParser(prog="mcp-moodle", description=__doc__)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("run", add_help=False, help="Configurar cuenta y agente con preguntas en la terminal")
    commands.add_parser("setup", add_help=False, help="Actualizar Moodle MCP, configurar cuenta y sincronizar agentes")
    commands.add_parser("serve", add_help=False, help="Iniciar el servidor MCP para un cliente, sin preguntas")
    commands.add_parser("tasks", add_help=False, help="Consultar tareas directamente en la terminal")
    commands.add_parser("status", add_help=False, help="Ver cuenta y comprobar el estado de conexión")
    commands.add_parser("update", add_help=False, help="Actualizar Moodle MCP a la última release estable")
    args, options = parser.parse_known_args(argv)
    if args.command != "serve":
        # serve lee su propio --env-file y es quien inicia Sentry con ese archivo.
        initialize_sentry(config_values())
    # Cada comando se importa al usarlo: `status` o `tasks` no cargan mcp, Playwright ni los
    # generadores de documentos. Así el arranque de la terminal baja de ~1,7 s a ~0,3 s.
    if args.command in ("run", "setup"):
        from . import setup

        setup.main(options)
    elif args.command == "serve":
        from . import server

        server.main(options)
    elif args.command == "status":
        from . import status

        status.main(options)
    elif args.command == "update":
        from . import updates

        updates.main(options)
    elif args.command == "tasks":
        from . import main as tasks

        tasks.main(options)
    else:
        if options:
            parser.error("Argumentos desconocidos: " + " ".join(options))
        from .ui import show_dashboard

        show_dashboard(config_values().get("MOODLE_USERNAME"))
        parser.print_help()


if __name__ == "__main__":
    main()
