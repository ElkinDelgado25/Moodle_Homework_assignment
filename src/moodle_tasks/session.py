"""Navegador de Moodle con la sesión reutilizada entre herramientas.

Solo se guardan las cookies del dominio de Moodle (nunca las del proveedor de identidad),
con permisos 0600 y una vigencia máxima de 12 horas. MOODLE_SESSION_CACHE=false lo desactiva.

En la terminal cada operación abre y cierra su Chromium. El servidor MCP instala un
BrowserSession en su hilo de Moodle: el navegador y el contexto con las cookies siguen vivos
entre herramientas y cada llamada solo abre una pestaña nueva.
"""

import contextvars
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, sync_playwright

from .auth import login
from .config import Config, opted_out
from .core import open_page
from .storage import atomic_write, sessions_dir, user_config_dir


SESSION_MAX_AGE_SECONDS = 12 * 3600
# Chromium ocupa ~100–200 MB: se cierra tras este tiempo sin herramientas de Moodle y se reabre al volver a usarse.
BROWSER_IDLE_SECONDS = 10 * 60
# Moodle se lee como texto: avatares, imágenes de cursos y fondos no se descargan. Es una opción de
# Chromium y no un page.route, porque interceptar peticiones desactiva la caché HTTP y haría que CSS y
# JavaScript se descargaran en cada página. El src de las imágenes de la consigna se sigue leyendo.
LAUNCH_ARGS = ("--blink-settings=imagesEnabled=false",)


def launch_browser(playwright):
    return playwright.chromium.launch(headless=True, args=list(LAUNCH_ARGS))
VERSION = 1


def cache_enabled(config: Config | None = None) -> bool:
    """Desactivable con MOODLE_SESSION_CACHE=false en el entorno o en credentials.env.

    El entorno se vuelve a mirar aunque config ya lo tenga en cuenta: una Config creada sin
    load_config tampoco puede saltarse la opción de privacidad.
    """
    if opted_out(os.environ.get("MOODLE_SESSION_CACHE")):
        return False
    return config is None or getattr(config, "session_cache", True)


def _session_name(config: Config) -> str:
    key = hashlib.sha256(f"{config.base_url.lower()}\0{config.username.casefold()}".encode()).hexdigest()[:32]
    return f"{key}.json"


def session_file(config: Config) -> Path:
    return sessions_dir() / _session_name(config)


def _remove_legacy_session(config: Config) -> None:
    """Hasta 0.4.4 la sesión se guardaba en la carpeta de configuración (Roaming en Windows)."""
    legacy = user_config_dir() / "sessions"
    try:
        (legacy / _session_name(config)).unlink(missing_ok=True)
        legacy.rmdir()
    except OSError:
        pass


def _host(config: Config) -> str:
    return (urlsplit(config.base_url).hostname or "").lower()


def _moodle_cookie(cookie: dict, host: str) -> bool:
    domain = str(cookie.get("domain", "")).lstrip(".").lower()
    return bool(domain) and (host == domain or host.endswith("." + domain))


def load_state(config: Config) -> dict | None:
    """storage_state de Playwright o None si no hay sesión válida para esta cuenta."""
    if not cache_enabled(config):
        return None
    path = session_file(config)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(data, dict) or data.get("version") != VERSION or data.get("base_url") != config.base_url
            or not isinstance(data.get("cookies"), list)):
        return None
    saved_at = data.get("saved_at")
    if not isinstance(saved_at, (int, float)) or not 0 <= time.time() - saved_at < SESSION_MAX_AGE_SECONDS:
        return None
    host = _host(config)
    cookies = [cookie for cookie in data["cookies"] if isinstance(cookie, dict) and _moodle_cookie(cookie, host)]
    if len(cookies) != len(data["cookies"]) or not cookies:
        return None
    return {"cookies": cookies, "origins": []}


def save_state(context, config: Config) -> bool:
    if not cache_enabled(config):
        return False
    try:
        cookies = context.cookies()
    except Exception:
        return False
    if not isinstance(cookies, list):
        return False
    host = _host(config)
    cookies = [cookie for cookie in cookies if isinstance(cookie, dict) and _moodle_cookie(cookie, host)]
    if not cookies:
        return False
    path = session_file(config)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform != "win32":
        os.chmod(path.parent, 0o700)
    atomic_write(path, json.dumps({"version": VERSION, "saved_at": time.time(), "base_url": config.base_url,
                                   "cookies": cookies}), private=True)
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    _remove_legacy_session(config)
    return True


def clear_state(config: Config) -> None:
    try:
        session_file(config).unlink(missing_ok=True)
    except OSError:
        pass
    _remove_legacy_session(config)


def is_logged_in(page: Page) -> bool:
    return "/login/" not in page.url and bool(page.locator("a[href*='/login/logout.php']").count())


def ensure_login(page: Page, config: Config) -> bool:
    """Usa la sesión guardada si sigue activa; si no, inicia sesión. Devuelve True si hizo login."""
    if page.context.cookies():
        open_page(page, f"{config.base_url}/my/")
        if is_logged_in(page):
            return False
    login(page, config)
    return True


class BrowserSession:
    """Chromium y el contexto de Moodle vivos entre llamadas.

    Playwright síncrono ata sus objetos al hilo que los creó: solo se usa desde un único hilo,
    el que lo instala con install_browser_session.
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._account: tuple[str, str] | None = None

    @property
    def running(self) -> bool:
        return self._browser is not None

    def browser(self):
        if self._browser is not None and not self._browser.is_connected():
            self.close()
        if self._browser is None:
            self._playwright = sync_playwright().start()
            try:
                self._browser = launch_browser(self._playwright)
            except BaseException:
                self.close()
                raise
        return self._browser

    def context(self, config: Config):
        """Contexto de la cuenta: el mismo mientras no cambien la URL o el usuario de Moodle."""
        account = (config.base_url, config.username.casefold())
        if self._context is not None and self._account != account:
            self.drop_context()
        if self._context is None:
            state = load_state(config)
            browser = self.browser()
            self._context = browser.new_context(storage_state=state) if state else browser.new_context()
            self._account = account
        return self._context

    def drop_context(self) -> None:
        """Olvida las cookies en memoria; la próxima llamada parte de la sesión guardada o inicia sesión."""
        context, self._context, self._account = self._context, None, None
        if context is not None:
            with suppress(Exception):
                context.close()

    def close(self) -> None:
        self.drop_context()
        browser, self._browser = self._browser, None
        playwright, self._playwright = self._playwright, None
        if browser is not None:
            with suppress(Exception):
                browser.close()
        if playwright is not None:
            with suppress(Exception):
                playwright.stop()


_thread = threading.local()


def install_browser_session(session: BrowserSession | None) -> None:
    """moodle_page usa este navegador en el hilo actual (None vuelve a un Chromium por llamada)."""
    _thread.session = session


def current_browser_session() -> BrowserSession | None:
    return getattr(_thread, "session", None)


class BrowserThread:
    """Hilo único donde corren las operaciones de Moodle del servidor MCP, con su BrowserSession.

    Todas las herramientas usan el mismo hilo (Playwright síncrono no admite otro) y, por tanto,
    el mismo Chromium. Tras idle_seconds sin llamadas el navegador se cierra; close() lo cierra ya.
    """

    def __init__(self, idle_seconds: float = BROWSER_IDLE_SECONDS) -> None:
        self.session = BrowserSession()
        self.idle_seconds = idle_seconds
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._last_used = time.monotonic()

    def submit(self, function, *args) -> Future:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="moodle-browser",
                                                    initializer=install_browser_session, initargs=(self.session,))
            future = self._executor.submit(contextvars.copy_context().run, function, *args)
        future.add_done_callback(self._finished)
        return future

    def _finished(self, _future: Future) -> None:
        with self._lock:
            self._last_used = time.monotonic()
            self._arm_timer(self.idle_seconds)

    def _arm_timer(self, delay: float) -> None:
        """Programa la comprobación de inactividad; se llama con self._lock tomado."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._executor is None:
            return
        self._timer = threading.Timer(delay, self._close_if_idle)
        self._timer.daemon = True
        self._timer.start()

    def _close_if_idle(self) -> None:
        with self._lock:
            if self._executor is None:
                return
            # El cierre pasa por el mismo hilo: nunca coincide con una herramienta en curso.
            self._executor.submit(self._close_session_if_idle)

    def _close_session_if_idle(self) -> None:
        with self._lock:
            remaining = self.idle_seconds - (time.monotonic() - self._last_used)
            if remaining > 0:
                # El temporizador puede despertar unos milisegundos antes de lo que mide time.monotonic
                # (en Windows redondea a ticks del sistema): se vuelve a programar para lo que falta en
                # vez de dejar Chromium abierto hasta la siguiente herramienta.
                self._arm_timer(remaining)
                return
        self.session.close()

    def close(self) -> None:
        """Cierra Chromium y el hilo; un submit posterior los vuelve a abrir."""
        with self._lock:
            executor, self._executor = self._executor, None
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if executor is not None:
            executor.submit(self.session.close)
            executor.shutdown(wait=True)


@contextmanager
def moodle_page(config: Config, *, timeout_ms: int = 15_000, fresh: bool = False):
    """(browser, page) con la sesión guardada; al terminar sin errores guarda las cookies vigentes.

    fresh=True ignora la sesión guardada y parte sin cookies: sirve para validar las credenciales de verdad.
    """
    shared = current_browser_session()
    if shared is not None:
        yield from _shared_page(shared, config, timeout_ms, fresh)
        return
    from .errors import MoodleAuthenticationError

    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        try:
            state = None if fresh else load_state(config)
            context = browser.new_context(storage_state=state) if state else browser.new_context()
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            try:
                yield browser, page
            except MoodleAuthenticationError:
                clear_state(config)
                raise
            save_state(context, config)
        finally:
            browser.close()


def _shared_page(shared: BrowserSession, config: Config, timeout_ms: int, fresh: bool):
    """Una pestaña nueva en el navegador ya abierto.

    Con la caché activa, el contexto (y sus cookies) se conserva para la siguiente herramienta.
    Con fresh=True o MOODLE_SESSION_CACHE=false, cada llamada usa un contexto propio que se cierra
    al terminar: solo se reutiliza el proceso de Chromium, nunca la sesión.
    """
    from .errors import MoodleAuthenticationError

    reuse = not fresh and cache_enabled(config)
    browser = shared.browser()
    context = shared.context(config) if reuse else browser.new_context()
    try:
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            yield browser, page
        except MoodleAuthenticationError:
            clear_state(config)
            if reuse:
                shared.drop_context()
            raise
        save_state(context, config)
    finally:
        if reuse:
            # Las pestañas de esta llamada (también las que dejó abiertas un error) no pasan a la siguiente.
            for leftover in list(context.pages):
                with suppress(Exception):
                    leftover.close()
        else:
            with suppress(Exception):
                context.close()
        if not browser.is_connected():
            shared.close()
