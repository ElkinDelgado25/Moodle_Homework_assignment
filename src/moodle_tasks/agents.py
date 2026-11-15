"""Registro del servidor en la configuración de usuario de cada cliente."""

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import tomlkit

from .storage import ConcurrentChangeError, atomic_write, read_bytes


AGENTS = {"codex": "Codex", "claude": "Claude Code", "cursor": "Cursor",
          "antigravity": "Google Antigravity", "copilot": "Copilot en VS Code"}


def ordered_agents() -> dict[str, str]:
    """Mismo orden alfabético en el menú y en el número que elige el usuario."""
    return dict(sorted(AGENTS.items(), key=lambda item: item[1].casefold()))


@dataclass(frozen=True)
class AgentDetection:
    availability: str
    moodle_configured: bool = False
    installed: bool = False


@dataclass
class AgentSyncResult:
    paths: dict[str, list[Path]]
    errors: dict[str, str]


def read_json_config(agent: str, path: Path, content: bytes | None = None) -> dict:
    """content permite analizar una copia ya leída del archivo en vez de volver a leerlo."""
    if content is None:
        content = read_bytes(path)
    if content is None:
        return {}
    text = content.decode("utf-8-sig")
    if not text.strip():
        return {}
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"La configuración de {AGENTS[agent]} contiene JSON inválido en {path} "
            f"(línea {error.lineno}, columna {error.colno}). "
            "Corrige el formato del archivo y vuelve a intentarlo; su contenido se conservó."
        ) from None
    if not isinstance(document, dict):
        raise ValueError(f"La configuración de {AGENTS[agent]} en {path} debe ser un objeto JSON.")
    return document


def detect_agents() -> dict[str, AgentDetection]:
    """Inspeccionar comandos y configuración local sin ejecutar los agentes."""
    commands = {"codex": ("codex",), "claude": ("claude",), "cursor": ("cursor-agent", "cursor"),
                "antigravity": ("agy", "antigravity"), "copilot": ("code", "code-insiders")}
    detected = {}
    for agent, names in commands.items():
        installed = any(shutil.which(name) for name in names)
        if agent == "cursor" and not installed and shutil.which("agent"):
            # «agent» es un nombre muy genérico: solo es Cursor si existe su carpeta personal.
            try:
                installed = (Path.home() / ".cursor").is_dir()
            except (OSError, RuntimeError):
                installed = False
        availability = "Instalado" if installed else "No detectado"
        if agent == "copilot":
            try:
                home = Path.home()
                copilot = any(
                    any((home / folder).glob("github.copilot-*"))
                    or any((home / folder).glob("github.copilot-chat-*"))
                    for folder in (".vscode/extensions", ".vscode-insiders/extensions")
                )
            except (OSError, RuntimeError):
                copilot = False
            if installed and not copilot:
                availability = "VS Code instalado; Copilot sin confirmar"
            elif copilot and not installed:
                availability = "Extensión Copilot encontrada; VS Code sin confirmar"
            installed = copilot
        configured = False
        try:
            path = agent_config_file(agent)
            if path.is_file():
                if not installed:
                    availability = "Configuración encontrada"
                document = tomlkit.parse(path.read_text(encoding="utf-8")) if agent == "codex" else read_json_config(agent, path)
                key = "mcp_servers" if agent == "codex" else "servers" if agent == "copilot" else "mcpServers"
                servers = document.get(key, {}) if isinstance(document, dict) else {}
                configured = isinstance(servers, dict) and isinstance(servers.get("moodle"), dict)
        except (OSError, RuntimeError, ValueError, tomlkit.exceptions.ParseError):
            # Un archivo ilegible o inválido no impide detectar los demás clientes.
            pass
        detected[agent] = AgentDetection(availability, configured, installed)
    return detected


def agent_config_file(agent: str) -> Path:
    home = Path.home()
    if agent == "codex":
        return Path(os.environ.get("CODEX_HOME", home / ".codex")) / "config.toml"
    if agent == "claude":
        return home / ".claude.json"
    if agent == "cursor":
        return home / ".cursor/mcp.json"
    if agent == "antigravity":
        return home / ".gemini/config/mcp_config.json"
    if agent == "copilot":
        if sys.platform == "win32":
            return Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Code/User/mcp.json"
        if sys.platform == "darwin":
            return home / "Library/Application Support/Code/User/mcp.json"
        return Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "Code/User/mcp.json"
    raise ValueError("Agente desconocido.")


REGISTER_ATTEMPTS = 3


def _registered_config(agent: str, path: Path, original: bytes | None, entry: dict) -> str:
    entry = dict(entry)
    if agent == "codex":
        if original is None:
            document = tomlkit.document()
        else:
            # Mismos saltos de línea que read_text: atomic_write escribe en modo texto y los vuelve a convertir.
            document = tomlkit.parse(original.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"))
        document.setdefault("mcp_servers", {})["moodle"] = {
            **entry, "enabled": True, "tool_timeout_sec": 300,
        }
        return tomlkit.dumps(document)
    document = read_json_config(agent, path, original)
    key = "servers" if agent == "copilot" else "mcpServers"
    if not isinstance(document.get(key, {}), dict):
        raise ValueError(f"El campo {key} no es un objeto JSON válido.")
    if agent == "copilot":
        entry["type"] = "stdio"
    document.setdefault(key, {})["moodle"] = entry
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def register_agent(agent: str, env_file: Path, config_file: Path | None = None) -> Path:
    path = config_file or agent_config_file(agent)
    # El intérprete absoluto pertenece al entorno aislado de uv tool install.
    # No depende del PATH del editor ni de un checkout del repositorio.
    entry = {"command": sys.executable,
             "args": ["-m", "moodle_tasks.cli", "serve", "--env-file", str(env_file.resolve())]}
    # Clientes como Claude Code reescriben su archivo a menudo: si cambió mientras se preparaba
    # la nueva versión, se vuelve a leer en lugar de descartar sus cambios.
    for _ in range(REGISTER_ATTEMPTS):
        original = read_bytes(path)
        try:
            atomic_write(path, _registered_config(agent, path, original, entry), expected=original)
            return path
        except ConcurrentChangeError:
            continue
    raise RuntimeError(f"La configuración de {AGENTS[agent]} cambió durante el registro; vuelve a intentarlo.")


def _existing_account(agent: str, fallback: Path) -> Path:
    """Conservar la cuenta explícita de un agente ya conectado al sincronizarlo."""
    path = agent_config_file(agent)
    document = (tomlkit.parse(path.read_text(encoding="utf-8")) if agent == "codex"
                else read_json_config(agent, path))
    key = "mcp_servers" if agent == "codex" else "servers" if agent == "copilot" else "mcpServers"
    arguments = document.get(key, {}).get("moodle", {}).get("args", [])
    if isinstance(arguments, list):
        for index, argument in enumerate(arguments):
            if argument == "--env-file" and index + 1 < len(arguments):
                value = arguments[index + 1]
            elif isinstance(argument, str) and argument.startswith("--env-file="):
                value = argument.split("=", 1)[1]
            else:
                continue
            if isinstance(value, str) and value and Path(value).is_absolute():
                return Path(value)
    return fallback


def synchronize_agents(env_file: Path, *, selected_agent: str | None = None,
                       selected_config: Path | None = None) -> AgentSyncResult:
    """Registrar instalados y conexiones existentes, aislando los fallos de cada cliente."""
    detected = detect_agents()
    targets = {agent for agent, state in detected.items() if state.installed or state.moodle_configured}
    if selected_agent and selected_config is None:
        targets.add(selected_agent)
    result = AgentSyncResult({}, {})
    for agent in AGENTS:
        if agent not in targets:
            continue
        try:
            account = env_file
            if (agent != selected_agent or selected_config is not None) and detected[agent].moodle_configured:
                account = _existing_account(agent, env_file)
            # Un perfil alternativo no sustituye la configuración global del mismo agente.
            if agent == selected_agent and selected_config == agent_config_file(agent):
                account = env_file
            result.paths[agent] = [register_agent(agent, account)]
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, tomlkit.exceptions.ParseError):
            # No devolver el contenido de configuraciones que puedan contener secretos.
            result.errors[agent] = "No se pudo sincronizar su configuración; se conservó el archivo original."
    if selected_agent and selected_config is not None:
        try:
            path = register_agent(selected_agent, env_file, selected_config)
            paths = result.paths.setdefault(selected_agent, [])
            if path not in paths:
                paths.append(path)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, tomlkit.exceptions.ParseError):
            result.errors[selected_agent] = "No se pudo sincronizar el perfil solicitado; se conservó el archivo original."
    return result
