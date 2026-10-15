"""Consulta releases estables y actualiza una instalación creada desde el clon Git."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, url2pathname, urlopen

from rich.console import Console
from rich.prompt import Confirm

from .storage import atomic_write, user_config_dir


PROJECT_NAME = "moodle-homework-assignment"
REPOSITORY = "ElkinDelgado25/Moodle_Homework_assignment"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases/tag"
DEFAULT_CHECK_HOURS = 24.0
FAILURE_RETRY_SECONDS = 300
CHECK_TIMEOUT_SECONDS = 2.5
VERSION_PATTERN = re.compile(r"^v?(\d+(?:\.\d+){0,3})$")
TAG_PATTERN = re.compile(r"^v\d+(?:\.\d+){1,3}$")


class UpdateError(RuntimeError):
    """Error claro y seguro que impide completar una actualización."""


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    url: str


@dataclass(frozen=True)
class UpdateStatus:
    installed_version: str
    release: Release | None = None
    error: str | None = None
    cached: bool = False
    stale: bool = False

    @property
    def update_available(self) -> bool:
        if self.release is None:
            return False
        try:
            return version_key(self.release.version) > version_key(self.installed_version)
        except ValueError:
            return False


def version_key(value: str) -> tuple[int, int, int, int]:
    match = VERSION_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError("La versión no usa el formato numérico esperado.")
    parts = [int(part) for part in match.group(1).split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])


def _project_version_from_text(content: str) -> str:
    try:
        project = tomllib.loads(content)["project"]
        name, version = project["name"], str(project["version"])
    except (KeyError, TypeError, tomllib.TOMLDecodeError):
        raise UpdateError("No se pudo leer el nombre y la versión del proyecto en pyproject.toml.") from None
    if name != PROJECT_NAME:
        raise UpdateError("El clon no corresponde a Moodle MCP.")
    version_key(version)
    return version


def _project_version(root: Path) -> str:
    try:
        return _project_version_from_text((root / "pyproject.toml").read_text(encoding="utf-8"))
    except OSError:
        raise UpdateError("No se encontró pyproject.toml en el clon de Moodle MCP.") from None


def installed_version() -> str:
    try:
        version = metadata.version(PROJECT_NAME)
    except metadata.PackageNotFoundError:
        source_root = Path(__file__).resolve().parents[2]
        version = _project_version(source_root)
    try:
        version_key(version)
    except ValueError:
        raise UpdateError("No se pudo interpretar la versión instalada de Moodle MCP.") from None
    return version


def _parse_release(data: dict) -> Release:
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
        raise UpdateError("GitHub devolvió una etiqueta de release no compatible.")
    version = tag.removeprefix("v")
    version_key(version)
    if data.get("draft") or data.get("prerelease"):
        raise UpdateError("GitHub no devolvió una release estable publicada.")
    url = data.get("html_url")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (parsed is None or parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
            or parsed.path.rstrip("/").lower() != f"/{REPOSITORY}/releases/tag/{tag}".lower()):
        url = f"{RELEASE_PAGE}/{tag}"
    return Release(tag, version, url)


def fetch_latest_release(timeout: float = CHECK_TIMEOUT_SECONDS) -> Release:
    request = Request(
        LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": PROJECT_NAME},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(512_000).decode("utf-8"))
    except HTTPError as error:
        raise UpdateError(f"GitHub respondió con HTTP {error.code} al consultar la release.") from None
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise UpdateError("No se pudo consultar GitHub. Revisa la conexión e inténtalo más tarde.") from None
    if not isinstance(payload, dict):
        raise UpdateError("GitHub devolvió una respuesta de release no válida.")
    return _parse_release(payload)


def _cache_file() -> Path:
    return user_config_dir() / "release-check.json"


def _read_cache() -> dict | None:
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("format") != 1:
            return None
        checked_at = float(data["checked_at"])
        release_data = data.get("release")
        release = _parse_release({
            "tag_name": release_data.get("tag"),
            "html_url": release_data.get("url"),
            "draft": False,
            "prerelease": False,
        }) if isinstance(release_data, dict) else None
        error = data.get("error")
        return {"checked_at": checked_at, "release": release,
                "error": error if isinstance(error, str) else None}
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError, UpdateError):
        return None


def _write_cache(release: Release | None, error: str | None) -> None:
    try:
        data = {
            "format": 1,
            "checked_at": datetime.now(timezone.utc).timestamp(),
            "release": ({"tag": release.tag, "url": release.url} if release else None),
            "error": error,
        }
        atomic_write(_cache_file(), json.dumps(data, ensure_ascii=False) + "\n")
    except (OSError, RuntimeError):
        pass


def _check_hours() -> float:
    raw = os.environ.get("MOODLE_UPDATE_CHECK_HOURS", str(DEFAULT_CHECK_HOURS))
    try:
        hours = float(raw)
    except ValueError:
        return DEFAULT_CHECK_HOURS
    return hours if 0 <= hours <= 8760 else DEFAULT_CHECK_HOURS


def check_for_updates(*, force: bool = False) -> UpdateStatus:
    try:
        current = installed_version()
    except UpdateError as error:
        return UpdateStatus("desconocida", error=str(error))

    cache = _read_cache()
    now = datetime.now(timezone.utc).timestamp()
    interval = _check_hours() * 3600
    age = now - cache["checked_at"] if cache else None
    cache_interval = interval
    if interval > 0 and cache and cache["error"]:
        cache_interval = FAILURE_RETRY_SECONDS
    if (not force and cache and cache_interval > 0 and age is not None and 0 <= age < cache_interval):
        return UpdateStatus(
            current,
            cache["release"],
            cache["error"],
            cached=True,
            stale=bool(cache["error"] and cache["release"]),
        )

    try:
        release = fetch_latest_release()
    except UpdateError as error:
        message = str(error)
        _write_cache(cache["release"] if cache else None, message)
        if cache and cache["release"]:
            return UpdateStatus(current, cache["release"], message, cached=True, stale=True)
        return UpdateStatus(current, error=message)
    _write_cache(release, None)
    return UpdateStatus(current, release)


def show_update_notice(status: UpdateStatus, console: Console | None = None) -> None:
    console = console or Console()
    if status.update_available and status.release:
        console.print(
            f"[yellow]Hay una versión nueva: {status.installed_version} → {status.release.version}.[/yellow]"
        )
        console.print(f"Release: {status.release.url}")
        console.print("Actualiza con: [bold]mcp-moodle update[/bold]")
        if status.stale and status.error:
            console.print("[dim]No se pudo renovar el aviso; se muestra la última consulta guardada.[/dim]")
    elif status.error:
        console.print("[dim]No se pudo comprobar si hay una release nueva; puedes continuar normalmente.[/dim]")


def _run_git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        raise UpdateError("No se encontró Git. Instala Git y vuelve a intentar.") from None
    if check and result.returncode:
        raise UpdateError("Git no pudo preparar la actualización. No se reemplazaron archivos locales.")
    return result


def _source_candidates() -> list[Path]:
    candidates = [Path(__file__).resolve().parents[2]]
    try:
        direct_url = metadata.distribution(PROJECT_NAME).read_text("direct_url.json")
        data = json.loads(direct_url) if direct_url else {}
        parsed = urlsplit(data.get("url", ""))
        if parsed.scheme == "file":
            candidates.insert(0, Path(url2pathname(unquote(parsed.path))))
    except (metadata.PackageNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return candidates


def checkout_root() -> Path:
    for candidate in _source_candidates():
        try:
            root_text = _run_git(candidate, "rev-parse", "--show-toplevel").stdout.strip()
            root = Path(root_text).resolve()
            _project_version(root)
            return root
        except (UpdateError, OSError):
            continue
    raise UpdateError(
        "No se encontró el clon Git desde el que se instaló Moodle MCP. "
        "Reinstálalo desde el repositorio clonado para habilitar las actualizaciones."
    )


def _canonical_remote(remote: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(?:[^@/:]+@)?([^:/]+):(.+)", remote)
    if match and "://" not in remote:
        host, path = match.groups()
    else:
        parsed = urlsplit(remote)
        host, path = parsed.hostname or "", parsed.path
    if not host:
        return None
    return host.lower(), path.strip("/").removesuffix(".git").lower()


def _run_step(command: list[str], root: Path, label: str) -> None:
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
    except OSError:
        raise UpdateError(f"No se pudo iniciar {label}. Comprueba que uv siga instalado.") from None
    if result.returncode:
        raise UpdateError(f"Falló {label}. No se pudo completar la actualización.")


def _ancestor(root: Path, older: str, newer: str) -> bool:
    result = _run_git(root, "merge-base", "--is-ancestor", older, newer, check=False)
    if result.returncode not in (0, 1):
        raise UpdateError("Git no pudo comparar la versión instalada con la release.")
    return result.returncode == 0


def _version_at_tag(root: Path, tag: str) -> str:
    content = _run_git(root, "show", f"{tag}:pyproject.toml").stdout
    return _project_version_from_text(content)


def _restore_checkout(root: Path, branch: str, previous: str) -> bool:
    if branch == "HEAD":
        result = _run_git(root, "checkout", "--detach", previous, check=False)
    else:
        result = _run_git(root, "checkout", branch, check=False)
    return result.returncode == 0


def _apply_release(release: Release, console: Console) -> None:
    root = checkout_root()
    remote = _run_git(root, "remote", "get-url", "origin").stdout.strip()
    if _canonical_remote(remote) != ("github.com", REPOSITORY.lower()):
        raise UpdateError("El remoto origin no corresponde al repositorio oficial; no se modificó el clon.")

    if _run_git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout.strip():
        raise UpdateError(
            "El clon tiene cambios locales o archivos sin seguimiento. Se detuvo la actualización "
            "para conservarlos; guarda o confirma esos cambios y vuelve a intentarlo."
        )

    branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch not in ("main", "HEAD"):
        raise UpdateError("El clon no está en la rama main ni en una release separada; no se modificó.")
    previous = _run_git(root, "rev-parse", "HEAD").stdout.strip()
    _project_version(root)

    if not TAG_PATTERN.fullmatch(release.tag):
        raise UpdateError("La release tiene una etiqueta no compatible; no se modificó el clon.")
    _run_git(root, "fetch", "--no-tags", "origin",
             f"refs/tags/{release.tag}:refs/tags/{release.tag}")
    target = _run_git(root, "rev-parse", f"refs/tags/{release.tag}^{{commit}}").stdout.strip()
    if _version_at_tag(root, release.tag) != release.version:
        raise UpdateError("La versión del proyecto no coincide con la release de GitHub.")

    target_is_in_current = _ancestor(root, target, previous)
    current_is_in_target = _ancestor(root, previous, target)
    if not target_is_in_current and not current_is_in_target:
        raise UpdateError(
            "La release no pertenece a la misma línea de historial que el clon actual. "
            "Se conservó el código y no se hizo ningún cambio."
        )
    checkout_needed = previous != target

    console.print(f"Actualizando Moodle MCP a la release {release.version}…")
    try:
        if checkout_needed:
            # Instala el código publicado en la release, aunque main ya tenga
            # commits posteriores que todavía no forman parte de una versión estable.
            _run_git(root, "checkout", "--detach", f"refs/tags/{release.tag}")

        _run_step(["uv", "sync", "--locked"], root, "la sincronización de dependencias del clon")
        with tempfile.TemporaryDirectory(prefix="moodle-update-") as temporary:
            requirements = Path(temporary) / "requirements.txt"
            _run_step(
                ["uv", "export", "--locked", "--no-dev", "--no-emit-project", "--no-hashes",
                 "--format", "requirements.txt", "--output-file", str(requirements)],
                root,
                "la exportación de dependencias fijadas",
            )
            _run_step(
                ["uv", "tool", "install", "--python", "3.11", "--force",
                 "--reinstall-package", PROJECT_NAME, "--constraints", str(requirements), str(root)],
                root,
                "la reinstalación del comando mcp-moodle",
            )
    except UpdateError as error:
        if checkout_needed and not _restore_checkout(root, branch, previous):
            raise UpdateError(
                f"{error} No se pudo restaurar la rama; conserva el clon y revisa Git antes de continuar."
            ) from None
        raise

    console.print(f"[green]Moodle MCP quedó actualizado a {release.version}.[/green]")


def update_latest(*, expected: Release | None = None, already_confirmed: bool = False,
                  console: Console | None = None) -> bool:
    console = console or Console()
    release = fetch_latest_release()
    current = installed_version()
    status = UpdateStatus(current, release)
    if not status.update_available:
        console.print(f"Moodle MCP ya está en la última release estable ({release.version}).")
        return False

    show_update_notice(status, console)
    release_changed = expected is not None and expected.tag != release.tag
    if release_changed:
        console.print("La release cambió desde la última comprobación.")
    if not already_confirmed or release_changed:
        if not sys.stdin.isatty():
            console.print("La actualización requiere confirmación en una terminal; no se modificó nada.")
            return False
        if not Confirm.ask(f"¿Actualizar ahora a la versión {release.version}?", default=False):
            console.print("Actualización cancelada; no se modificó nada.")
            return False

    _apply_release(release, console)
    return True


def update_from_setup(console: Console | None = None) -> bool:
    """Buscar e instalar la release estable al abrir setup, sin otra confirmación."""
    console = console or Console()
    try:
        return update_latest(already_confirmed=True, console=console)
    except UpdateError as error:
        console.print(f"[yellow]No se actualizó: {error} La configuración continuará.[/yellow]")
        return False


def continue_with_updated_setup(arguments: list[str]) -> None:
    """Continuar en el intérprete recién instalado, también desde un checkout de desarrollo."""
    try:
        result = subprocess.run(["uv", "tool", "dir"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except OSError:
        raise UpdateError("No se encontró uv para continuar con la instalación actualizada.") from None
    if result.returncode or not result.stdout.strip():
        raise UpdateError("No se pudo localizar la instalación actualizada de Moodle MCP.")
    python = Path(result.stdout.strip()) / PROJECT_NAME / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    if not python.is_file():
        raise UpdateError("No se encontró el intérprete actualizado. Vuelve a ejecutar mcp-moodle setup.")
    try:
        # argv es una lista, sin shell; conserva rutas con espacios y opciones del usuario.
        completed = subprocess.run([str(python), "-m", "moodle_tasks.setup", "--skip-update",
                                    "--sync-after-update", *arguments])
    except OSError:
        raise UpdateError("No se pudo continuar el asistente. Vuelve a ejecutar mcp-moodle setup.") from None
    if completed.returncode:
        raise SystemExit(completed.returncode)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mcp-moodle update", description=__doc__)
    parser.parse_args(argv)
    console = Console()
    try:
        release = fetch_latest_release()
        if UpdateStatus(installed_version(), release).update_available:
            if update_latest(expected=release, console=console):
                continue_with_updated_setup(["--sync-only"])
        else:
            from .setup import main as setup_main

            console.print(f"Moodle MCP ya está en la última release estable ({release.version}).")
            setup_main(["--skip-update", "--sync-only"])
    except UpdateError as error:
        console.print(f"[red]No se pudo actualizar Moodle MCP: {error}[/red]", stderr=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
