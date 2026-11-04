"""Moodle mínimo en 127.0.0.1 para probar el flujo completo sin red externa."""

import html
import secrets
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from helpers import make_pdf  # noqa: F401 - reutiliza el generador de PDF

MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre")


def moodle_date(moment: datetime) -> str:
    return f"{moment.day} de {MONTHS[moment.month - 1]} de {moment.year}, {moment:%H:%M}"


class FakeMoodle:
    USERNAME = "estudiante"
    PASSWORD = "clave-secreta-123"
    ASSIGNMENT_ID = 11

    def __init__(self, pdf_bytes: bytes):
        self.pdf_bytes = pdf_bytes
        self.tokens: set[str] = set()
        self.logins = 0
        self.saved_files: list[str] = []
        self.requests: list[tuple[str, str]] = []
        self.due = datetime.now().replace(second=0, microsecond=0) + timedelta(days=3)
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_html(self, body: str, status: int = 200, headers: dict | None = None):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def redirect(self, location: str, headers: dict | None = None):
                self.send_response(303)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()

            def authenticated(self) -> bool:
                cookie = self.headers.get("Cookie", "")
                return any(f"MoodleSession={token}" in cookie for token in server.tokens)

            def do_GET(self):
                parts = urlsplit(self.path)
                query = parse_qs(parts.query)
                server.requests.append(("GET", self.path))
                if parts.path == "/login/index.php":
                    return self.send_html(server.login_page())
                if not self.authenticated():
                    return self.redirect("/login/index.php")
                if parts.path == "/my/":
                    return self.send_html(server.dashboard())
                if parts.path == "/mod/assign/view.php":
                    if query.get("action") == ["editsubmission"]:
                        return self.send_html(server.edit_page())
                    return self.send_html(server.view_page())
                if parts.path == "/mod/page/view.php":
                    return self.send_html(server.linked_page())
                if parts.path.startswith("/pluginfile.php/") and parts.path.endswith("guia.pdf"):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Length", str(len(server.pdf_bytes)))
                    self.end_headers()
                    self.wfile.write(server.pdf_bytes)
                    return
                self.send_html("<h1>No encontrado</h1>", status=404)

            def do_POST(self):
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                values = parse_qs(self.rfile.read(length).decode("utf-8"))
                server.requests.append(("POST", self.path))
                if parts.path == "/login/index.php":
                    if values.get("username") == [server.USERNAME] and values.get("password") == [server.PASSWORD]:
                        token = secrets.token_hex(8)
                        server.tokens.add(token)
                        server.logins += 1
                        return self.redirect("/my/", {"Set-Cookie": f"MoodleSession={token}; Path=/; HttpOnly"})
                    return self.send_html(server.login_page(error=True))
                if not self.authenticated():
                    return self.redirect("/login/index.php")
                if parts.path == "/mod/assign/view.php":
                    server.saved_files = values.get("filename", [])
                    return self.redirect(f"/mod/assign/view.php?id={server.ASSIGNMENT_ID}")
                if parts.path.endswith("/grade"):
                    raise AssertionError("La herramienta nunca debe enviar para calificar.")
                self.send_html("<h1>No encontrado</h1>", status=404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    # ---------------------------------------------------------------- páginas

    def shell(self, body: str) -> str:
        return (f'<!doctype html><html><head><title>Moodle</title></head><body>'
                f'<nav class="usermenu"><span class="usertext">Carlos Mendoza</span>'
                f'<a href="/login/logout.php">Salir</a></nav>{body}</body></html>')

    def login_page(self, error: bool = False) -> str:
        message = '<div class="alert alert-danger">Datos erróneos</div>' if error else ""
        return (f'<!doctype html><html><body>{message}<form id="login" action="/login/index.php" method="post">'
                '<input name="username"><input name="password" type="password">'
                '<button type="submit">Acceder</button></form></body></html>')

    def dashboard(self) -> str:
        identifier = self.ASSIGNMENT_ID
        action = "" if self.saved_files else f'<a href="/mod/assign/view.php?id={identifier}&action=editsubmission">Agregar entrega</a>'
        return self.shell(
            '<section class="block_timeline"><button>Próximos 30 días</button>'
            f'<div data-region="event-list-item"><div class="event-name-container">'
            f'<a aria-label="Pendiente para {moodle_date(self.due)}" href="/mod/assign/view.php?id={identifier}">Práctica 3: App con Compose</a>'
            f'<small>Vencimiento de Tarea · Desarrollo Móvil</small></div>{action}</div></section>')

    def view_page(self) -> str:
        opened = self.due - timedelta(days=7)
        links = "".join(f'<a href="/pluginfile.php/1/assignsubmission_file/submission_files/9/{html.escape(name)}">{html.escape(name)}</a>'
                        for name in self.saved_files)
        status = "Borrador (no enviado)" if self.saved_files else "No se ha enviado nada en esta tarea"
        grade = '<button type="button">Enviar tarea</button>' if self.saved_files else ""
        return self.shell(
            '<div class="breadcrumb"><a href="/course/view.php?id=7">Desarrollo Móvil</a></div>'
            '<main id="region-main"><h1>Práctica 3: App con Compose</h1>'
            f'<div class="activity-dates"><div>Apertura: {moodle_date(opened)}</div><div>Cierre: {moodle_date(self.due)}</div></div>'
            '<div id="intro"><p>Desarrolle la aplicación siguiendo la guía y entregue un informe en PDF y DOCX.</p>'
            '<p>Requisitos en <a href="/mod/page/view.php?id=5">la página de la práctica</a>.</p>'
            '<p><a href="/pluginfile.php/1/mod_assign/introattachment/0/guia.pdf">guia.pdf</a></p></div>'
            f'<table class="submissionstatustable"><tr><th>Estado de la entrega</th><td>{status}</td></tr>'
            f'<tr><th>Archivos enviados</th><td>{links}</td></tr></table>{grade}</main>')

    def linked_page(self) -> str:
        return self.shell('<main id="region-main"><h1>Requisitos</h1><p>Requisitos: pantalla principal con Compose, '
                          'lista de elementos y repositorio público en GitHub.</p></main>')

    def edit_page(self) -> str:
        current = "".join(f'<div class="fp-file"><div class="fp-filename">{html.escape(name)}</div></div>' for name in self.saved_files)
        return self.shell(f'''<main id="region-main"><h1>Práctica 3: App con Compose</h1>
          <form id="editform" method="post" action="/mod/assign/view.php">
            <div class="filemanager fm-loading" data-maxfiles="5" data-maxbytes="10485760">
              <button type="button" class="fp-btn-add">Agregar</button><div class="fp-content">{current}</div></div>
            <input type="submit" id="id_submitbutton" name="submitbutton" value="Guardar cambios">
            <input type="submit" name="cancel" value="Cancelar">
          </form>
          <script>
          const form = document.querySelector('#editform');
          form.addEventListener('submit', (event) => {{
            if (event.submitter && event.submitter.name === 'cancel') return;
            document.querySelectorAll('.fp-filename').forEach((el) => {{
              const input = document.createElement('input'); input.type = 'hidden'; input.name = 'filename'; input.value = el.textContent;
              form.appendChild(input);
            }});
          }});
          const fm = document.querySelector('.filemanager');
          setTimeout(() => {{
            fm.classList.remove('fm-loading'); fm.classList.add('fm-loaded');
            if (!fm.querySelector('.fp-file')) fm.classList.add('fm-nofiles');
          }}, 150);
          fm.querySelector('.fp-btn-add').onclick = () => {{
            const dialog = document.createElement('div'); dialog.className = 'moodle-dialogue'; dialog.setAttribute('role', 'dialog');
            dialog.innerHTML = '<button type="button" id="repo">Subir un archivo</button>'; document.body.appendChild(dialog);
            dialog.querySelector('#repo').onclick = () => {{
              dialog.innerHTML = '<div class="fp-file"><input type="file" id="up"></div><button type="button" class="fp-upload-btn">Subir este archivo</button>';
              dialog.querySelector('.fp-upload-btn').onclick = () => {{
                const file = dialog.querySelector('#up').files[0];
                const item = document.createElement('div'); item.className = 'fp-file';
                const name = document.createElement('div'); name.className = 'fp-filename';
                name.textContent = file.name.replace(/[&<>"`|':\\\\/]/g, '').replace(/\\s+/g, ' ').trim();
                item.appendChild(name); fm.querySelector('.fp-content').appendChild(item);
                fm.classList.remove('fm-nofiles'); dialog.remove();
              }};
            }};
          }};
          </script></main>''')
