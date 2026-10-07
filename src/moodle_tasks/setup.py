"""Asistente interactivo de configuración e integración global."""

import argparse
import getpass
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
from rich.console import Console
from rich.text import Text

from .agents import AGENTS, detect_agents, register_agent
from .errors import MoodleAuthenticationError, MoodleHTTPError
from .main import Config, config_values, login
from .storage import atomic_write, save_credentials, user_config_dir
from .system import describe_system
from .ui import ConnectionState, show_agent_menu, show_dashboard, show_setup_menu


DEFAULT_URL = "https://aulavirtualmoodle.uleam.edu.ec"


def valid_username(username: str) -> bool:
    if not username or any(character.isspace() for character in username):
        return False
    return "@" not in username or bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", username))


def prepare_browser(log_dir: Path | None = None) -> None:
    console = Console()
    console.print(Text(f"Sistema detectado: {describe_system()}"))
    with console.status("Preparando Moodle MCP · instalando Chromium en segundo plano...", spinner="dots", spinner_style="#ff6555"):
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    if result.returncode:
        log_file = (log_dir or user_config_dir()) / "browser-install.log"
        atomic_write(log_file, (result.stdout or "") + "\n" + (result.stderr or ""))
        raise RuntimeError(
            "No se pudo preparar Chromium. Revisa los detalles del fallo e inténtalo de nuevo. "
            f"Los detalles del fallo están en: {log_file}"
        )
    console.print(Text("✓ Chromium listo.", style="green"))


def verify_credentials(config: Config) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(15_000)
            login(page, config)
        finally:
            browser.close()


def ask_account(url: str) -> tuple[Config, bool]:
    for attempt in range(3):
        username = input("Usuario o correo de Moodle: ").strip()
        if not valid_username(username):
            print("Introduce un usuario sin espacios o un correo con formato válido.")
            continue
        password = getpass.getpass("Contraseña de Moodle (no se mostrará): ")
        if not password or "\n" in password or "\r" in password:
            print("La contraseña no puede estar vacía ni contener saltos de línea.")
            continue
        config = Config(url, username, password, True)
        try:
            with Console().status("Comprobando el acceso a Moodle...", spinner="dots", spinner_style="#ff6555"):
                verify_credentials(config)
        except MoodleAuthenticationError:
            show_dashboard(username, ConnectionState.PROBLEMS, refresh=True)
            print("Moodle no aceptó el usuario o la contraseña. Vuelve a introducirlos.")
            continue
        except MoodleHTTPError as error:
            if 500 <= error.status < 600:
                print(str(error))
                return config, False
            raise
        except PlaywrightTimeoutError:
            print("Por ahora no se pudo comprobar tu cuenta porque Moodle tardó demasiado en responder.")
            return config, False
        print("Cuenta verificada correctamente.")
        return config, True
    raise ValueError("No se pudo configurar la cuenta después de tres intentos. Ejecuta mcp-moodle run para intentarlo otra vez.")


def ask_agent() -> str:
    choices = list(AGENTS)
    show_agent_menu(AGENTS, detect_agents())
    while True:
        choice = input("Selecciona una opción (1-4): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(choices):
            return choices[int(choice) - 1]
        print("Selecciona un número entre 1 y 4.")


def ask_setup_action() -> str:
    show_setup_menu()
    while True:
        choice = input("Selecciona una opción (1-3): ").strip()
        if choice in ("1", "2", "3"):
            return choice
        print("Selecciona un número entre 1 y 3.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Dirección de Moodle; por defecto la guardada o ULEAM")
    parser.add_argument("--agent", choices=AGENTS, help="Agente que se desea configurar")
    parser.add_argument("--config-dir", type=Path, help="Carpeta personal alternativa para las credenciales")
    parser.add_argument("--agent-config", type=Path, help="Configuración alternativa del agente, por ejemplo un perfil de VS Code")
    parser.add_argument("--connect-only", action="store_true", help="Conectar otro agente usando la cuenta ya guardada")
    args = parser.parse_args(argv)
    env_file = (args.config_dir or user_config_dir()).resolve() / "credentials.env"
    username = None
    try:
        values = config_values(env_file)
        username = values.get("MOODLE_USERNAME")
        url = (args.url or values.get("MOODLE_URL") or DEFAULT_URL).rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            parser.error("La dirección debe ser una URL HTTP o HTTPS de Moodle, sin credenciales, parámetros ni fragmentos.")
        connect_only = args.connect_only
        edit_only = False
        if not connect_only:
            prepare_browser(env_file.parent)
            show_dashboard(username, refresh=True)
            show_agent_menu(AGENTS, detect_agents(), title="Agentes en este equipo")
            if env_file.is_file() and all((values.get(key) or "").strip() for key in ("MOODLE_URL", "MOODLE_USERNAME", "MOODLE_PASSWORD")):
                choice = ask_setup_action()
                if choice == "3":
                    print("Hasta luego. Tu configuración se conserva.")
                    return
                connect_only = choice == "2"
                edit_only = choice == "1"
        if not connect_only:
            config, verified = ask_account(url)
            username = config.username
            save_credentials(env_file, config.base_url, config.username, config.password)
            show_dashboard(username, ConnectionState.CONNECTED if verified else ConnectionState.PROBLEMS, refresh=True)
            if not verified:
                print("Por ahora Moodle no responde; no se pudo comprobar el acceso al servidor.")
                print("Tu cuenta quedó guardada en este equipo; la validación de la cuenta está pendiente.")
                print("La instalación puede continuar. Cuando Moodle vuelva a responder, la próxima consulta intentará validar el acceso con tu cuenta guardada.")
                print("También puedes comprobar el acceso más tarde con: mcp-moodle status")
            if edit_only:
                print("Credenciales actualizadas. Los agentes configurados con esta cuenta usarán los nuevos datos.")
                return
        elif not env_file.is_file():
            raise ValueError("Todavía no hay una cuenta guardada. Ejecuta mcp-moodle run primero.")
        else:
            show_dashboard(username, refresh=True)
        agent = args.agent or ask_agent()
        path = register_agent(agent, env_file, args.agent_config)
        state = (ConnectionState.CONNECTED if verified else ConnectionState.PROBLEMS) if not connect_only else ConnectionState.NOT_STARTED
        show_dashboard(username, state, agent=AGENTS[agent], refresh=True)
        print(f"\nMCP registrado en {AGENTS[agent]} para tu usuario.")
        print(f"Configuración del agente: {path}")
        print(f"Credenciales guardadas localmente en: {env_file}")
        if not connect_only and not verified:
            print("La validación de la cuenta está pendiente; la próxima consulta intentará iniciar sesión.")
        print("Reinicia el agente y pide: Usa el MCP moodle para consultar mis tareas pendientes.")
    except (KeyboardInterrupt, EOFError):
        print("\nConfiguración cancelada.")
        raise SystemExit(130) from None
    except Exception as error:
        # Las excepciones de validación y configuración no incluyen las credenciales.
        show_dashboard(username, ConnectionState.PROBLEMS, refresh=True)
        print(f"No se pudo completar la configuración: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
