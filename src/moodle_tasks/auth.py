"""Inicio de sesión en Moodle (formulario propio o Microsoft 365) y renovación de una sesión vencida."""

import re
import time

from playwright.sync_api import Page

from .config import Config
from .core import clean_text, open_page
from .errors import MoodleAuthenticationError, MoodleHTTPError

MICROSOFT_LOGIN_SECONDS = 60
MICROSOFT_POLL_MS = 100
MICROSOFT_ERRORS = ("#passwordError", "#usernameError", "#errorText")
EMPTY_PASSWORD = re.compile(r"please enter your password|(?:escriba|introduzca|ingresa|ingrese) (?:su |tu |la )?contraseña",
                            re.I)
OTHER_ACCOUNT = re.compile(r"Use a different account|Usar una cuenta diferente|Utilizar otra cuenta", re.I)
STAY_SIGNED_IN = re.compile(r"Stay signed in|mantener la sesión iniciada", re.I)


def login(page: Page, config: Config) -> None:
    open_page(page, f"{config.base_url}/login/index.php")
    microsoft = page.get_by_role("link", name="Microsoft 365 Uleam", exact=True)
    if microsoft.count() and config.username.lower().endswith(("@live.uleam.edu.ec", "@uleam.edu.ec")):
        login_microsoft(page, config)
        return
    login_form = page.locator("form#login, form[action*='login']")
    if login_form.count() == 0:
        if page.locator("a[href*='/login/logout.php']").count():
            return
        raise RuntimeError("No se encontró el formulario de acceso ni una sesión iniciada en Moodle.")

    page.locator("input[name='username']").fill(config.username)
    page.locator("input[name='password']").fill(config.password)
    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
        page.locator("button[type='submit'], input[type='submit']").first.click()
    response = navigation.value
    if response is not None and response.status >= 400:
        raise MoodleHTTPError(response.status, page.url)

    if "/login/" in page.url:
        if page.locator("input[name='username'], input[name='password']").count():
            raise MoodleAuthenticationError("Moodle no aceptó el usuario o la contraseña.")
        raise RuntimeError("No se pudo confirmar el inicio de sesión en Moodle.")

    if not page.locator("a[href*='/login/logout.php']").count():
        raise RuntimeError("No se pudo confirmar una sesión iniciada en Moodle.")


def submit_microsoft_password(page: Page, password_value: str) -> None:
    """Espera la etapa de contraseña y actualiza el formulario con teclado."""
    password = page.locator('input[name="passwd"]')
    submit = page.get_by_role("button", name=re.compile(r"^(Sign in|Iniciar sesión|Acceder)$", re.I))
    try:
        password.wait_for(state="visible", timeout=30_000)
        submit.wait_for(state="visible", timeout=30_000)
        for _ in range(2):
            password.fill("")
            password.press_sequentially(password_value, delay=40)
            password.press("Tab")
            if password.input_value() == password_value:
                submit.click()
                return
    except Exception:
        # Los errores de escritura de Playwright pueden incluir el argumento.
        raise RuntimeError("No se pudo completar el campo de contraseña de Microsoft. El formulario no terminó de estar disponible.") from None
    raise RuntimeError("Microsoft vació el campo de contraseña antes de enviarlo. No se pudo completar el formulario.")


def login_microsoft(page: Page, config: Config) -> None:
    """Acceso institucional observado en ULEAM; no resuelve códigos ni MFA."""
    page.get_by_role("link", name="Microsoft 365 Uleam", exact=True).click()
    email = page.locator('input[name="loginfmt"]')
    email.wait_for(state="visible", timeout=30_000)
    email.fill(config.username)
    page.locator("#idSIButton9").click()
    submit_microsoft_password(page, config.password)
    logged_in = page.locator("a[href*='/login/logout.php']")
    errors = [page.locator(selector).first for selector in MICROSOFT_ERRORS]
    alternate = page.get_by_role("link", name=OTHER_ACCOUNT).first
    stay = page.get_by_role("button", name="No", exact=True).first
    stay_prompt = page.get_by_text(STAY_SIGNED_IN)
    selected_again = False
    retried_empty_field = False
    stay_answered_at = None
    # Plazo total con reloj y sondeo corto: cada paso del acceso se detecta en ~0,1 s, no tras 0,5 s fijos.
    deadline = time.monotonic() + MICROSOFT_LOGIN_SECONDS
    while time.monotonic() < deadline:
        if page.url.startswith(config.base_url + "/") and logged_in.count():
            return
        for error in errors:
            if error.count() and error.is_visible() and clean_text(error.inner_text()):
                message = clean_text(error.inner_text())
                if EMPTY_PASSWORD.search(message):
                    if not retried_empty_field:
                        retried_empty_field = True
                        submit_microsoft_password(page, config.password)
                        break
                    raise RuntimeError("Microsoft sigue detectando el campo de contraseña vacío. Falló el envío del formulario; no se confirmó el acceso.")
                raise MoodleAuthenticationError("Microsoft no aceptó el acceso: " + message)
        if not selected_again and alternate.count() and alternate.is_visible():
            alternate.click()
            profile = page.get_by_text(config.username, exact=True).first
            profile.wait_for(state="visible", timeout=20_000)
            profile.click()
            selected_again = True
        # «¿Mantener la sesión iniciada?» se responde una vez por página: el sondeo es más rápido que la navegación.
        if stay_answered_at != page.url and stay.count() and stay.is_visible() and stay_prompt.count():
            stay_answered_at = page.url
            stay.click()
        page.wait_for_timeout(MICROSOFT_POLL_MS)
    raise RuntimeError("Microsoft requiere completar el acceso o una verificación adicional. No se confirmó una sesión de Moodle.")


def open_authenticated_page(page: Page, url: str, config: Config) -> None:
    """Renueva una sesión vencida una vez, sin leer el formulario como una tarea."""
    for attempt in range(2):
        open_page(page, url)
        if not ("/login/" in page.url or page.locator("input[name='username'], input[name='password'], input[name='loginfmt']").count()):
            return
        if attempt == 0:
            login(page, config)
    raise MoodleAuthenticationError("La sesión de Moodle sigue vencida después de volver a iniciar sesión.")
