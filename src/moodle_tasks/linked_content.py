"""Lectura acotada del material web enlazado desde las instrucciones."""

import ipaddress
import re
import socket
import time
from urllib.parse import urldefrag, urljoin, urlsplit

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .auth import open_authenticated_page
from .errors import redact_credentials

MAX_LINKS = 5
MAX_CONTENT = 30_000          # total para todos los enlaces de una tarea
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 6               # redirecciones seguidas, sin contar la petición inicial
# Cualquier actividad o curso del mismo Moodle se lee con la sesión, salvo los archivos.
MOODLE_READABLE = re.compile(r"^/(?:mod/[a-z0-9_]+/|course/view\.php)")
MOODLE_FILE = re.compile(r"^/mod/(?:resource|folder)/|/pluginfile\.php/")
EXTRACT_TEXT = """(body) => {
    const root = body.querySelector('article, main, [role="main"], #region-main') || body;
    root.querySelectorAll('script, style, nav, header, footer, aside, noscript').forEach(el => el.remove());
    return root.innerText || root.textContent || '';
}"""


def _normalize_page_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()
DESCRIPTION_SELECTORS = (
    "#intro",
    ".activity-description",
    ".mod_introbox",
    "[data-region='activity-description']",
    "[data-region='activity-information'] .description",
    ".box.generalbox",
    "[data-region='activity-information']",
)
INTRO_SELECTORS = ", ".join(DESCRIPTION_SELECTORS)
DATE_FIELD = re.compile(r"\b(?:Apertura|Opened|Opens|Cierre|Due(?: date)?|Fecha de entrega)\s*:\s*", re.I)
DATE_VALUE = re.compile(
    r"(?:(?:[A-Za-zÁ-ÿ]+),?\s*)?\d{1,2}\s+(?:de\s+)?[A-Za-zÁ-ÿ]+\s+(?:de\s+)?"
    r"\d{4},?\s+\d{1,2}:\d{2}(?:\s*[ap]m)?",
    re.I,
)


# El árbol de anexos vive dentro del bloque de la descripción: se oculta para leer solo la consigna.
DESCRIPTION_TEXT = """el => {
    const hidden = Array.from(el.querySelectorAll(
        "[id^='assign_files_tree'], .fileuploadsubmission, .fileuploadsubmissiontime"));
    const previous = hidden.map(node => node.style.display);
    hidden.forEach(node => { node.style.display = 'none'; });
    try { return el.innerText || ''; } finally { hidden.forEach((node, i) => { node.style.display = previous[i]; }); }
}"""
DESCRIPTION_IMAGES = """images => images.filter(image => !image.closest("[id^='assign_files_tree']")
        && !/\\bicon\\b/.test(image.className || '') && image.src)
    .map(image => ({name: (image.alt || image.title || '').trim(), url: image.src}))"""


def clean_block_text(value: str | None) -> str:
    """Normaliza espacios sin perder los párrafos y listas de la consigna."""
    lines = [re.sub(r"[\t\f\v ]+", " ", line).strip() for line in (value or "").replace("\xa0", " ").splitlines()]
    cleaned = []
    blank = False
    for line in lines:
        if line:
            cleaned.append(line)
            blank = False
        elif cleaned and not blank:
            cleaned.append("")
            blank = True
    return "\n".join(cleaned).strip()


def is_date_summary(value: str) -> bool:
    """Evita presentar el resumen de apertura y cierre como si fuera la consigna."""
    fields = list(DATE_FIELD.finditer(value))
    if not fields or value[:fields[0].start()].strip(" ,;:-\n"):
        return False
    for index, field in enumerate(fields):
        end = fields[index + 1].start() if index + 1 < len(fields) else len(value)
        date_value = value[field.end():end].strip(" ,;:-\n")
        if not DATE_VALUE.fullmatch(date_value):
            return False
    return True


def assignment_description(page: Page) -> str:
    """Lee el bloque de descripción de Moodle, sin confundirlo con sus fechas."""
    for selector in DESCRIPTION_SELECTORS:
        matches = page.locator(selector)
        texts = []
        for index in range(matches.count()):
            try:
                text = clean_block_text(matches.nth(index).evaluate(DESCRIPTION_TEXT))
            except PlaywrightTimeoutError:
                continue
            if text and not is_date_summary(text) and text not in texts:
                texts.append(text)
        if texts:
            return "\n\n".join(texts)
    return ""


def assignment_images(page: Page) -> list[dict[str, str]]:
    """Imágenes incrustadas en la consigna: una captura puede ser la instrucción completa."""
    found = page.locator(INTRO_SELECTORS).locator("img[src]").evaluate_all(DESCRIPTION_IMAGES)
    images, seen = [], set()
    for item in found if isinstance(found, list) else []:
        url = urldefrag(str(item.get("url", "")))[0]
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            images.append({"name": str(item.get("name", "")), "url": url})
    return images[:20]


def assignment_links(page: Page, content: str, attachments: list[dict]) -> list[dict[str, str]]:
    candidates = page.locator(INTRO_SELECTORS).locator("a[href]").evaluate_all(
        "aa => aa.map(a => ({name: (a.innerText || a.title || '').trim(), url: a.href}))"
    )
    candidates.extend({"name": "", "url": match.rstrip(".,;!?)")}
                      for match in re.findall(r"https?://[^\s<>\"']+", content, re.IGNORECASE))
    seen = {urldefrag(item["url"])[0] for item in attachments}
    seen.add(urldefrag(page.url)[0])
    links = []
    for item in candidates:
        url = urldefrag(item["url"])[0]
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        if "pluginfile.php" in parsed.path or url in seen:
            continue
        seen.add(url)
        links.append({"name": item["name"], "url": url})
    return links


def validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError("El enlace no es una URL web pública compatible.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError("El enlace apunta a una dirección local o privada.")


def _slice(result: dict, text: str, offset: int, max_chars: int) -> None:
    """Tramo del texto desde offset; next_offset permite pedir el resto con otra llamada."""
    end = offset + max_chars
    result.update(content=text[offset:end], truncated=len(text) > end, total_chars=len(text))
    if offset:
        result["offset"] = offset
    if len(text) > end:
        result["next_offset"] = end


def read_link(browser, link: dict[str, str], max_chars: int = MAX_CONTENT, offset: int = 0) -> dict:
    result = dict(link, kind="page", content="", truncated=False)
    validate_public_url(link["url"])
    # Sin cookies de Moodle ni ejecución de scripts de los sitios enlazados.
    context = browser.new_context(java_script_enabled=False, service_workers="block")
    try:
        page = context.new_page()
        blocked = []
        redirects = 0
        resolved_url = link["url"]
        deadline = time.monotonic() + 15

        def route_document(route):
            nonlocal redirects, resolved_url
            request = route.request
            if request.resource_type != "document" or request.frame != page.main_frame:
                route.abort()
                return
            try:
                current = request.url
                while True:
                    validate_public_url(current)
                    timeout = max(1, int((deadline - time.monotonic()) * 1000))
                    response = route.fetch(url=current, max_redirects=0, timeout=timeout)
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("El enlace devolvió una redirección sin destino.")
                        redirects += 1
                        if redirects > MAX_REDIRECTS:
                            raise ValueError("El enlace excedió el límite de redirecciones.")
                        current = urljoin(current, location)
                        continue
                    resolved_url = current
                    if len(response.body()) > MAX_BODY_BYTES:
                        raise ValueError("La página enlazada es demasiado grande para leerla (más de 2 MB).")
                    route.fulfill(response=response)
                    return
            except Exception as error:
                blocked.append(str(error))
                route.abort()
                return

        context.route("**/*", route_document)
        try:
            response = page.goto(link["url"], wait_until="domcontentloaded", timeout=15_000)
        except Exception as error:
            if blocked:
                raise ValueError(blocked[0]) from None
            if "Download is starting" in str(error):
                raise ValueError("El enlace descarga un archivo, no es una página; ábrelo o descárgalo aparte.") from None
            raise
        if response is None or response.status >= 400:
            raise ValueError(f"No se pudo leer el enlace (HTTP {response.status if response else 'sin respuesta'}).")
        if response.headers.get("content-type", "").split(";", 1)[0] not in ("text/html", "application/xhtml+xml", "text/plain"):
            raise ValueError("El enlace no contiene una página de texto compatible; puede requerir descargar un archivo.")
        if page.locator("input[type='password']").count() or "/login/" in urlsplit(resolved_url).path:
            raise ValueError("El enlace requiere iniciar sesión; no se pudieron leer las instrucciones.")
        text = _normalize_page_text(page.locator("body").evaluate(EXTRACT_TEXT))
        if not text:
            raise ValueError("La página no contiene instrucciones legibles sin ejecutar JavaScript.")
        result.update(resolved_url=resolved_url, title=page.title())
        _slice(result, text, offset, max_chars)
        return result
    finally:
        context.close()


def read_moodle_link(session_page, config, link: dict[str, str], max_chars: int = MAX_CONTENT, offset: int = 0) -> dict:
    """Página del mismo Moodle leída con la sesión iniciada (las anónimas piden login)."""
    result = dict(link, kind="page", content="", truncated=False)
    page = session_page.context.new_page()
    try:
        page.set_default_timeout(15_000)
        open_authenticated_page(page, link["url"], config)
        text = _normalize_page_text(page.locator("body").evaluate(EXTRACT_TEXT))
        if not text:
            raise ValueError("La página de Moodle no tiene texto legible.")
        result.update(resolved_url=page.url, title=page.title())
        _slice(result, text, offset, max_chars)
        return result
    finally:
        page.close()


def read_linked_resources(browser, links: list[dict[str, str]], credentials: tuple[str, ...] = (), *,
                          session_page=None, config=None, only_url: str | None = None, offset: int = 0) -> dict:
    """Texto de los enlaces de la consigna. only_url y offset continúan un enlace que quedó truncado."""
    from .urls import moodle_path

    if only_url is not None:
        wanted = urldefrag(only_url)[0]
        links = [link for link in links if link["url"] == wanted]
        if not links:
            raise ValueError("resource_url debe ser uno de los enlaces de linked_resources de esta tarea.")
    else:
        offset = 0
    resources = []
    remaining = MAX_CONTENT
    for link in links[:MAX_LINKS]:
        if remaining <= 0:
            resources.append(dict(link, error="Se alcanzó el límite total de texto de los enlaces.", truncated=True))
            continue
        path = moodle_path(link["url"], config.base_url) if config is not None else None
        try:
            if path is not None and MOODLE_FILE.search(path):
                downloadable = path.startswith("/mod/resource/") or "/pluginfile.php/" in path
                resources.append(dict(link, kind="file", error=(
                    "Es un archivo de Moodle; descárgalo con download_assignment_attachments." if downloadable
                    else "Es una carpeta de Moodle; ábrela en Moodle para ver sus archivos.")))
                continue
            if path is not None and session_page is not None and MOODLE_READABLE.match(path):
                resource = read_moodle_link(session_page, config, link, remaining, offset)
            else:
                resource = read_link(browser, link, remaining, offset)
            remaining -= len(resource.get("content", ""))
            resources.append(resource)
        except PlaywrightTimeoutError:
            resources.append(dict(link, error="Se agotó el tiempo de lectura del enlace."))
        except Exception as error:
            resources.append(dict(link, error=redact_credentials(error, credentials)))
    return {"linked_resources": resources, "links_omitted": max(0, len(links) - MAX_LINKS),
            "linked_content_incomplete": len(links) > MAX_LINKS or any(
                item.get("error") or item.get("truncated") for item in resources)}
