"""Navegador por llamada con la sesión de Moodle reutilizada entre herramientas.

Solo se guardan las cookies del dominio de Moodle (nunca las del proveedor de identidad),
con permisos 0600 y una vigencia máxima de 12 horas. MOODLE_SESSION_CACHE=false lo desactiva.
"""

import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, sync_playwright

from .main import Config, login, open_page
from .storage import atomic_write, user_config_dir


SESSION_MAX_AGE_SECONDS = 12 * 3600
VERSION = 1


def cache_enabled(config: Config | None = None) -> bool:
    """Desactivable con MOODLE_SESSION_CACHE=false en el entorno o en credentials.env."""
    from .main import OPT_OUT

    if (os.environ.get("MOODLE_SESSION_CACHE") or "true").strip().lower() in OPT_OUT:
        return False
    return config is None or getattr(config, "session_cache", True)


def session_file(config: Config) -> Path:
    key = hashlib.sha256(f"{config.base_url.lower()}\0{config.username.casefold()}".encode()).hexdigest()[:32]
    return user_config_dir() / "sessions" / f"{key}.json"


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
                                   "cookies": cookies}))
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    return True


def clear_state(config: Config) -> None:
    try:
        session_file(config).unlink(missing_ok=True)
    except OSError:
        pass


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


@contextmanager
def moodle_page(config: Config, *, timeout_ms: int = 15_000):
    """(browser, page) con la sesión guardada; al terminar sin errores guarda las cookies vigentes."""
    from .errors import MoodleAuthenticationError

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            state = load_state(config)
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
