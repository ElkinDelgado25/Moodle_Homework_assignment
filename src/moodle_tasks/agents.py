"""Registro del servidor en la configuración de usuario de cada cliente."""

import json
import os
import sys
from pathlib import Path

import tomlkit

from .storage import atomic_write


AGENTS = {"codex": "Codex", "claude": "Claude Code",
          "antigravity": "Google Antigravity", "copilot": "Copilot en VS Code"}


def agent_config_file(agent: str) -> Path:
    home = Path.home()
    if agent == "codex":
        return Path(os.environ.get("CODEX_HOME", home / ".codex")) / "config.toml"
    if agent == "claude":
        return home / ".claude.json"
    if agent == "antigravity":
        return home / ".gemini/config/mcp_config.json"
    if agent == "copilot":
        if sys.platform == "win32":
            return Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Code/User/mcp.json"
        if sys.platform == "darwin":
            return home / "Library/Application Support/Code/User/mcp.json"
        return Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "Code/User/mcp.json"
    raise ValueError("Agente desconocido.")


def register_agent(agent: str, env_file: Path, config_file: Path | None = None) -> Path:
    path = config_file or agent_config_file(agent)
    # El intérprete absoluto pertenece al entorno aislado de uv tool install.
    # No depende del PATH del editor ni de un checkout del repositorio.
    entry = {"command": sys.executable,
             "args": ["-m", "moodle_tasks.cli", "serve", "--env-file", str(env_file.resolve())]}
    if agent == "codex":
        document = tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()
        document.setdefault("mcp_servers", {})["moodle"] = {
            **entry, "enabled": True, "tool_timeout_sec": 300,
        }
        content = tomlkit.dumps(document)
    else:
        document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(document, dict):
            raise ValueError(f"La configuración de {AGENTS[agent]} debe ser un objeto JSON.")
        key = "servers" if agent == "copilot" else "mcpServers"
        if not isinstance(document.get(key, {}), dict):
            raise ValueError(f"El campo {key} no es un objeto JSON válido.")
        if agent == "copilot":
            entry["type"] = "stdio"
        document.setdefault(key, {})["moodle"] = entry
        content = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    atomic_write(path, content)
    return path
