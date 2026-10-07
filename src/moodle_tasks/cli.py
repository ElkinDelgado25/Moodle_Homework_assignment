"""Comandos de terminal de Moodle MCP."""

import argparse

from . import main as tasks
from . import server, setup


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mcp-moodle", description=__doc__)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("run", add_help=False, help="Configurar cuenta y agente con preguntas en la terminal")
    commands.add_parser("setup", add_help=False, help="Alias de run")
    commands.add_parser("serve", add_help=False, help="Iniciar el servidor MCP para un cliente, sin preguntas")
    commands.add_parser("tasks", add_help=False, help="Consultar tareas directamente en la terminal")
    args, options = parser.parse_known_args(argv)
    if args.command in ("run", "setup"):
        setup.main(options)
    elif args.command == "serve":
        server.main(options)
    elif args.command == "tasks":
        if options:
            parser.error("El comando tasks no acepta opciones.")
        tasks.main()
    else:
        if options:
            parser.error("Argumentos desconocidos: " + " ".join(options))
        parser.print_help()


if __name__ == "__main__":
    main()
