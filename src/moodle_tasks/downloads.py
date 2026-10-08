"""Descargas de anexos con las cookies del mismo contexto de Moodle."""

import re
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from playwright.sync_api import Page

from .errors import MoodleAuthenticationError, MoodleHTTPError
from .main import Config, login


def documents_directory() -> Path:
    spanish = Path.home() / "Documentos"
    return spanish if spanish.is_dir() else Path.home() / "Documents"


def same_origin(url: str, base_url: str) -> bool:
    def origin(value: str):
        parts = urlsplit(value)
        return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    return origin(url) == origin(base_url) and not urlsplit(url).username


def attachment_name(url: str) -> str:
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name).strip(" .")
    if not name:
        name = "anexo"
    if name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name


def authenticated_content(page: Page, config: Config, url: str) -> tuple[bytes, str]:
    """Sigue solo redirecciones de Moodle; nunca exporta cookies al agente."""
    if not same_origin(url, config.base_url) or "pluginfile.php" not in urlsplit(url).path:
        raise ValueError("El enlace no es un anexo del Moodle configurado.")
    for attempt in range(2):
        current = url
        expired = False
        for _ in range(10):
            if not same_origin(current, config.base_url) or "/login/" in urlsplit(current).path:
                expired = True
                break
            response = page.context.request.get(current, max_redirects=0, timeout=60_000)
            try:
                status = response.status
                if status in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("El anexo devolvió una redirección sin destino.")
                    current = urljoin(current, location)
                    continue
                if status in (401, 403):
                    expired = True
                    break
                if status >= 400:
                    raise MoodleHTTPError(status, current)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                body = response.body()
                prefix = body[:1024].lstrip().lower()
                html = content_type in ("text/html", "application/xhtml+xml") or prefix.startswith((b"<!doctype html", b"<html"))
                if html:
                    expired = True
                    break
                if not body:
                    raise RuntimeError("Moodle devolvió un anexo vacío.")
                if (urlsplit(url).path.lower().endswith(".pdf") or content_type == "application/pdf") and not body.startswith(b"%PDF-"):
                    raise RuntimeError("Moodle no devolvió un PDF válido; el anexo no se guardó.")
                return body, content_type
            finally:
                response.dispose()
        if not expired:
            raise RuntimeError("Demasiadas redirecciones al descargar el anexo.")
        if attempt == 0:
            login(page, config)
    raise MoodleAuthenticationError("Moodle devolvió una página de acceso o denegó el anexo después de renovar la sesión. No se guardó como archivo.")


def download_attachment(page: Page, config: Config, url: str, directory: Path) -> dict:
    body, content_type = authenticated_content(page, config, url)
    directory.mkdir(parents=True, exist_ok=True)
    name = attachment_name(url)
    for number in range(1000):
        original = Path(name)
        candidate = directory / (name if number == 0 else f"{original.stem} ({number}){original.suffix}")
        try:
            output = candidate.open("xb")
        except FileExistsError:
            continue
        try:
            with output:
                output.write(body)
        except BaseException:
            candidate.unlink(missing_ok=True)
            raise
        return {"name": candidate.name, "path": str(candidate.resolve()), "size_bytes": len(body), "content_type": content_type}
    raise RuntimeError("Ya existen demasiados anexos con el mismo nombre en la carpeta.")
