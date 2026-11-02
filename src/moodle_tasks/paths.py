"""Validación de rutas locales antes de leer, copiar o subir archivos."""

import os
import sys
from pathlib import Path

from .storage import default_env_file, user_cache_dir, user_config_dir


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
UPLOAD_EXTENSIONS = frozenset({
    ".pdf", ".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xls", ".ods", ".csv", ".pptx", ".ppt", ".odp",
    ".zip", ".rar", ".7z", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".md",
    ".py", ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".js", ".ts", ".jsx", ".tsx", ".html",
    ".css", ".sql", ".ipynb", ".json", ".xml", ".php", ".dart", ".swift", ".go", ".rs", ".r", ".m",
})
# Contenedores ZIP (Office moderno, OpenDocument y .zip) y PDF se reconocen por su firma.
SIGNATURES = {
    ".pdf": (b"%PDF-",),
    **{suffix: (b"PK\x03\x04",) for suffix in (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".zip")},
}
# /run queda fuera: /run/media contiene memorias USB y discos externos del usuario.
SYSTEM_ROOTS = ("/proc", "/sys", "/dev", "/etc", "/boot")


class UnsafePathError(ValueError):
    """La ruta apunta a datos que no deben salir del equipo."""


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _protected_roots() -> list[Path]:
    roots = [user_config_dir()]
    if sys.platform != "win32":
        roots += [Path(root) for root in SYSTEM_ROOTS]
    env_file = default_env_file()
    roots.append(env_file)
    resolved = []
    for root in roots:
        try:
            resolved.append(Path(os.path.realpath(root)))
        except OSError:
            continue
    return resolved


def _hidden_component(path: Path) -> str | None:
    """Primer componente oculto de la ruta, salvo las carpetas de trabajo de esta aplicación."""
    workspace = Path(os.path.realpath(user_cache_dir()))
    if _inside(path, workspace):
        relative = path.relative_to(workspace).parts
        return next((part for part in relative if part.startswith(".")), None)
    return next((part for part in path.parts if part.startswith(".") and part not in (".", "..")), None)


def resolve_local_file(raw: str) -> Path:
    """Resuelve enlaces simbólicos y rechaza rutas protegidas antes de abrir el archivo."""
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise ValueError("La ruta local está vacía o no es válida.")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("Usa una ruta absoluta (o que empiece por ~) para el archivo local.")
    path = Path(os.path.realpath(candidate))
    for root in _protected_roots():
        if path == root or _inside(path, root):
            raise UnsafePathError("La ruta apunta a la configuración o a archivos del sistema; no se puede usar.")
    hidden = _hidden_component(path)
    if hidden:
        raise UnsafePathError(f"La ruta pasa por un archivo o carpeta oculta ({hidden}); no se puede usar.")
    return path


def check_upload_file(raw: str) -> Path:
    """Archivo regular, legible, de un tipo de entrega habitual y con contenido coherente."""
    path = resolve_local_file(raw)
    if not path.exists():
        raise FileNotFoundError("El archivo local no existe.")
    if not path.is_file():
        raise ValueError("La ruta local no corresponde a un archivo legible.")
    suffix = path.suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        raise ValueError(f"El tipo de archivo {suffix or 'sin extensión'} no es un formato de entrega admitido.")
    size = path.stat().st_size
    if size == 0:
        raise ValueError("El archivo está vacío.")
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("El archivo supera 100 MB.")
    with path.open("rb") as handle:
        head = handle.read(8)
    expected = SIGNATURES.get(suffix)
    if expected and not head.startswith(expected):
        raise ValueError(f"El contenido no corresponde a un archivo {suffix} válido.")
    return path


def resolve_destination_directory(raw: str) -> Path:
    """Carpeta de salida absoluta, fuera de la configuración y de rutas del sistema."""
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise ValueError("La carpeta de destino está vacía o no es válida.")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("Usa una carpeta absoluta (o que empiece por ~) como destino.")
    path = Path(os.path.realpath(candidate))
    for root in _protected_roots():
        if path == root or _inside(path, root):
            raise UnsafePathError("La carpeta de destino es de configuración o del sistema; elige otra.")
    if _hidden_component(path):
        raise UnsafePathError("La carpeta de destino es oculta; elige una carpeta visible.")
    if path.exists() and not path.is_dir():
        raise ValueError("La carpeta de destino es un archivo.")
    return path
