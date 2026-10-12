"""Instalacion interactiva de Moodle MCP."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm


PROJECT_DIR = Path(__file__).resolve().parent.parent
console = Console()


def run(*command: str) -> None:
    subprocess.run(command, check=True)


def tool_install_command(project_dir: Path) -> list[str]:
    """Instala una copia aislada y sustituye una instalacion anterior del mismo equipo."""
    return ["uv", "tool", "install", "--force", "--python", "3.11", str(project_dir)]


def tool_python() -> str:
    tool_root = Path(subprocess.check_output(["uv", "tool", "dir"], text=True).strip())
    environment = tool_root / "moodle-homework-assignment"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(python)


def install_user_command(project_dir: Path) -> None:
    console.rule("[bold cyan]1 de 3 - Comando en el PATH")
    console.print("Se instalara mcp-moodle para ejecutarlo desde cualquier carpeta.")
    console.print("Tiempo estimado: 1 a 3 minutos.")
    run(*tool_install_command(project_dir))
    run("uv", "tool", "update-shell")
    console.print("[green]mcp-moodle quedo en el PATH. Las terminales que ya estaban abiertas hay que cerrarlas y abrirlas de nuevo.[/green]")


def prepare_system_dependencies(family: str) -> None:
    console.rule("[bold cyan]2 de 3 - Dependencias del sistema")
    if family in ("windows", "macos"):
        console.print("Chromium se descarga durante el asistente. No hace falta instalar paquetes del sistema.")
        return
    if family == "debian":
        console.print("Chromium puede necesitar paquetes del sistema. Tiempo estimado: 2 a 5 minutos.")
        if not Confirm.ask("Quieres instalarlos ahora", default=False):
            console.print("[yellow]Se omitieron. Puedes instalarlos despues con:[/yellow]")
            console.print(f"  {tool_python()} -m playwright install --with-deps chromium")
            return
        console.print("[cyan]Se pedira tu contrasena de sudo una sola vez.[/cyan]")
        run("sudo", "-v")
        console.print("[cyan]Instalando dependencias de Chromium...[/cyan]")
        run(tool_python(), "-m", "playwright", "install", "--with-deps", "chromium")
        return
    console.print("Se instalara Chromium. Tiempo estimado: 1 a 3 minutos.")
    console.print("[cyan]Se pedira tu contrasena de sudo una sola vez.[/cyan]")
    run("sudo", "-v")
    run("sudo", "pacman", "-S", "--needed", "chromium")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("windows", "debian", "arch", "macos"), required=True)
    args = parser.parse_args(argv)
    console.print(Panel.fit(
        "[bold red]MOODLE MCP[/bold red]\nInstalacion desde un repositorio clonado",
        border_style="red",
    ))
    # El asistente debe ejecutarse con el comando instalado: asi el agente queda
    # registrado con el Python de esa instalacion y no con el entorno del repositorio.
    install_user_command(PROJECT_DIR)
    prepare_system_dependencies(args.family)
    console.rule("[bold cyan]3 de 3 - Configuracion de Moodle")
    console.print("Se abrira el asistente para configurar la cuenta y el agente.")
    run("mcp-moodle", "setup")


if __name__ == "__main__":
    main()
