"""Inicio de sesión en Moodle (formulario propio o Microsoft 365) y renovación de una sesión vencida."""

import re

from playwright.sync_api import Page

from .config import Config
from .core import clean_text, open_page
from .errors import MoodleAuthenticationError, MoodleHTTPError


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
    selected_again = False
    retried_empty_field = False
    for _ in range(120):
        if page.url.startswith(config.base_url + "/") and page.locator("a[href*='/login/logout.php']").count():
            return
        for selector in ("#passwordError", "#usernameError", "#errorText"):
            error = page.locator(selector).first
            if error.count() and error.is_visible() and clean_text(error.inner_text()):
                message = clean_text(error.inner_text())
                if re.search(r"please enter your password|(?:escriba|introduzca|ingresa|ingrese) (?:su |tu |la )?contraseña", message, re.I):
                    if not retried_empty_field:
                        retried_empty_field = True
                        submit_microsoft_password(page, config.password)
                        break
                    raise RuntimeError("Microsoft sigue detectando el campo de contraseña vacío. Falló el envío del formulario; no se confirmó el acceso.")
                raise MoodleAuthenticationError("Microsoft no aceptó el acceso: " + message)
        alternate = page.get_by_role("link", name=re.compile(
            r"Use a different account|Usar una cuenta diferente|Utilizar otra cuenta", re.I))
        if not selected_again and alternate.count() and alternate.first.is_visible():
            alternate.first.click()
            profile = page.get_by_text(config.username, exact=True).first
            profile.wait_for(state="visible", timeout=20_000)
            profile.click()
            selected_again = True
        stay = page.get_by_role("button", name="No", exact=True)
        if stay.count() and stay.first.is_visible() and page.get_by_text(re.compile(
            r"Stay signed in|mantener la sesión iniciada", re.I)).count():
            stay.first.click()
        page.wait_for_timeout(500)
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
