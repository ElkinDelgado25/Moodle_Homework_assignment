"""Lectura acotada del material web enlazado desde las instrucciones."""

import ipaddress
import re
import socket
import time
from urllib.parse import urldefrag, urljoin, urlsplit

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .errors import redact_credentials

MAX_LINKS = 5
MAX_CONTENT = 30_000
INTRO_SELECTORS = ".activity-description, .mod_introbox, #intro"


def assignment_links(page: Page, content: str, attachments: list[dict]) -> list[dict[str, str]]:
    candidates = page.locator(INTRO_SELECTORS).locator("a[href]").evaluate_all(
        "aa => aa.map(a => ({name: (a.innerText || a.title || '').trim(), url: a.href}))"
    )
    candidates.extend({"name": "", "url": match.rstrip(".,;!?)")}
                      for match in re.findall(r"https?://[^\s<>\"']+", content))
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


def read_link(browser, link: dict[str, str]) -> dict:
    result = dict(link, content="", truncated=False)
    validate_public_url(link["url"])
    # Sin cookies de Moodle ni ejecución de scripts de los sitios enlazados.
    context = browser.new_context(java_script_enabled=False, service_workers="block")
    try:
        page = context.new_page()
        blocked = []
        navigations = 0
        resolved_url = link["url"]
        deadline = time.monotonic() + 15

        def route_document(route):
            nonlocal navigations, resolved_url
            request = route.request
            if request.resource_type != "document" or request.frame != page.main_frame:
                route.abort()
                return
            try:
                current = request.url
                while True:
                    navigations += 1
                    if navigations > 6:
                        raise ValueError("El enlace excedió el límite de redirecciones.")
                    validate_public_url(current)
                    timeout = max(1, int((deadline - time.monotonic()) * 1000))
                    response = route.fetch(url=current, max_redirects=0, timeout=timeout)
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("El enlace devolvió una redirección sin destino.")
                        current = urljoin(current, location)
                        continue
                    resolved_url = current
                    route.fulfill(response=response)
                    return
            except Exception as error:
                blocked.append(str(error))
                route.abort()
                return

        context.route("**/*", route_document)
        try:
            response = page.goto(link["url"], wait_until="domcontentloaded", timeout=15_000)
        except Exception:
            if blocked:
                raise ValueError(blocked[0]) from None
            raise
        if response is None or response.status >= 400:
            raise ValueError(f"No se pudo leer el enlace (HTTP {response.status if response else 'sin respuesta'}).")
        if response.headers.get("content-type", "").split(";", 1)[0] not in ("text/html", "application/xhtml+xml", "text/plain"):
            raise ValueError("El enlace no contiene una página de texto compatible; puede requerir descargar un archivo.")
        if page.locator("input[type='password']").count() or "/login/" in urlsplit(resolved_url).path:
            raise ValueError("El enlace requiere iniciar sesión; no se pudieron leer las instrucciones.")
        text = page.locator("body").evaluate("""(body) => {
            const root = body.querySelector('article, main, [role="main"]') || body;
            root.querySelectorAll('script, style, nav, header, footer, aside, noscript').forEach(el => el.remove());
            return root.innerText || root.textContent || '';
        }""")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        if not text:
            raise ValueError("La página no contiene instrucciones legibles sin ejecutar JavaScript.")
        result.update(resolved_url=resolved_url, title=page.title(), content=text[:MAX_CONTENT],
                      truncated=len(text) > MAX_CONTENT)
        return result
    finally:
        context.close()


def read_linked_resources(browser, links: list[dict[str, str]], credentials: tuple[str, ...] = ()) -> dict:
    resources = []
    for link in links[:MAX_LINKS]:
        try:
            resources.append(read_link(browser, link))
        except PlaywrightTimeoutError:
            resources.append(dict(link, error="Se agotó el tiempo de lectura del enlace."))
        except Exception as error:
            resources.append(dict(link, error=redact_credentials(error, credentials)))
    return {"linked_resources": resources, "links_omitted": max(0, len(links) - MAX_LINKS),
            "linked_content_incomplete": len(links) > MAX_LINKS or any(
                item.get("error") or item.get("truncated") for item in resources)}
