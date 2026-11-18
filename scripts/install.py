"""Instalacion interactiva de Moodle MCP desde un clon, comun a Windows, macOS y Linux."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from moodle_tasks import PYTHON_VERSION


PROJECT_DIR = Path(__file__).resolve().parent.parent
PROJECT_NAME = "moodle-homework-assignment"
console = Console()


def run(*command: str) -> None:
    subprocess.run(command, check=True)


def export_constraints_command(project_dir: Path, output: Path) -> list[str]:
    """Versiones fijadas en uv.lock, las mismas que prueba el CI y que usa mcp-moodle update."""
    return ["uv", "export", "-q", "--project", str(project_dir), "--locked", "--no-dev", "--no-emit-project",
            "--no-hashes", "--format", "requirements.txt", "--output-file", str(output)]


def tool_install_command(project_dir: Path, constraints: Path) -> list[str]:
    """Instala una copia aislada y sustituye una instalacion anterior del mismo equipo."""
    # --compile-bytecode deja el código listo en la primera instalación: los arranques
    # posteriores no compilan módulos y el comando responde antes en Windows y macOS.
    return ["uv", "tool", "install", "-q", "--force", "--compile-bytecode", "--python", PYTHON_VERSION,
            "--reinstall-package", PROJECT_NAME, "--constraints", str(constraints), str(project_dir)]


def tool_python() -> str:
    tool_root = Path(subprocess.check_output(["uv", "tool", "dir"], text=True).strip())
    environment = tool_root / PROJECT_NAME
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(python)


def install_user_command(project_dir: Path) -> None:
    console.rule("[bold cyan]1 de 3 - Comando en el PATH")
    console.print("Se instalara mcp-moodle para ejecutarlo desde cualquier carpeta.")
    console.print("Tiempo estimado: 1 a 3 minutos.")
    with tempfile.TemporaryDirectory(prefix="moodle-install-") as temporary:
        constraints = Path(temporary) / "requirements.txt"
        run(*export_constraints_command(project_dir, constraints))
        run(*tool_install_command(project_dir, constraints))
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
    # El asistente debe ejecutarse con el Python de la herramienta instalada: asi el agente
    # queda registrado con esa instalacion y no con el entorno del repositorio. No se busca
    # mcp-moodle en el PATH, que en esta terminal puede no incluirla todavia o apuntar a otra.
    install_user_command(PROJECT_DIR)
    prepare_system_dependencies(args.family)
    console.rule("[bold cyan]3 de 3 - Configuracion de Moodle")
    console.print("Se abrira el asistente para configurar la cuenta y el agente.")
    run(tool_python(), "-m", "moodle_tasks.cli", "setup")


if __name__ == "__main__":
    main()
