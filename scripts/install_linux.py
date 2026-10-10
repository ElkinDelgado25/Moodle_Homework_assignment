"""Instalacion interactiva de Moodle MCP en Linux."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm


PROJECT_DIR = Path(__file__).resolve().parent.parent
console = Console()


def run(*command: str) -> None:
    subprocess.run(command, check=True)


def prepare_system_dependencies(family: str) -> None:
    if family == "debian":
        console.rule("[bold cyan]1 de 3 - Dependencias del sistema")
        console.print("Chromium puede necesitar paquetes del sistema. Tiempo estimado: 2 a 5 minutos.")
        if not Confirm.ask("Quieres instalarlos ahora", default=False):
            console.print("[yellow]Se omitieron. Puedes instalarlos despues con:[/yellow]")
            console.print("  uv run playwright install --with-deps chromium")
            return
        console.print("[cyan]Se pedira tu contrasena de sudo una sola vez.[/cyan]")
        run("sudo", "-v")
        console.print("[cyan]Instalando dependencias de Chromium...[/cyan]")
        run("uv", "--directory", str(PROJECT_DIR), "run", "playwright", "install", "--with-deps", "chromium")
    else:
        console.rule("[bold cyan]1 de 3 - Dependencias del sistema")
        console.print("Se instalara Chromium. Tiempo estimado: 1 a 3 minutos.")
        console.print("[cyan]Se pedira tu contrasena de sudo una sola vez.[/cyan]")
        run("sudo", "-v")
        run("sudo", "pacman", "-S", "--needed", "chromium")
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("debian", "arch"), required=True)
    args = parser.parse_args(argv)
    console.print(Panel.fit(
        "[bold red]MOODLE MCP[/bold red]\nInstalacion desde un repositorio clonado",
        border_style="red",
    ))
    prepare_system_dependencies(args.family)
    console.rule("[bold cyan]2 de 3 - Dependencias de Python")
    console.print("Preparando el entorno del proyecto. Tiempo estimado: 1 a 3 minutos.")
    run("uv", "--directory", str(PROJECT_DIR), "sync")
    console.rule("[bold cyan]3 de 3 - Configuracion de Moodle")
    console.print("Se abrira el asistente para configurar la cuenta y el agente.")
    run("uv", "--directory", str(PROJECT_DIR), "run", "mcp-moodle", "setup")


if __name__ == "__main__":
    main()
