import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from moodle_tasks.main import Config
from moodle_tasks.uploads import upload_files


class AssignmentUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.set_default_timeout(3000)
        self.config = Config("https://moodle.test", "test", "private-password", True)
        self.state = {"existing_files": [], "saved_files": None, "closed": False,
                      "has_filemanager": True, "reject_names": set(), "requests": [],
                      "require_login": False, "authenticated": False, "login_count": 0}
        self.page.route("**/*", self.respond)

    def tearDown(self):
        self.page.close()

    def respond(self, route):
        request = route.request
        parts = urlsplit(request.url)
        self.state["requests"].append((request.method, parts.path))
        if self.state["require_login"] and parts.path in ("/login/index.php", "/my/", "/mod/assign/view.php"):
            if parts.path == "/my/" and request.method == "POST":
                self.state["authenticated"] = True
                self.state["login_count"] += 1
                return route.fulfill(content_type="text/html; charset=utf-8",
                                     body='<a href="/login/logout.php">Salir</a>')
            if not self.state["authenticated"] and parts.path != "/login/index.php":
                return route.fulfill(content_type="text/html; charset=utf-8", body=self.login_html())
            if not self.state["authenticated"] and parts.path == "/login/index.php":
                return route.fulfill(content_type="text/html; charset=utf-8", body=self.login_html())
        if parts.path == "/save" and request.method == "POST":
            values = parse_qs(request.post_data or "")
            self.state["saved_files"] = values.get("filename", [])
            return route.fulfill(content_type="text/html; charset=utf-8", body=self.view_html())
        if parts.path == "/mod/assign/view.php":
            if parse_qs(parts.query).get("action") == ["editsubmission"]:
                return route.fulfill(content_type="text/html; charset=utf-8", body=self.edit_html())
            return route.fulfill(content_type="text/html; charset=utf-8", body=self.view_html())
        return route.fulfill(status=404, body="Not found")

    def login_html(self):
        return '''<!doctype html><html><body><form id="login" action="/my/" method="post">
          <input name="username"><input name="password"><button type="submit">Acceder</button>
        </form></body></html>'''

    def view_html(self):
        files = self.state["saved_files"]
        if files is None:
            files = self.state["existing_files"]
        links = "".join(f'<a href="/pluginfile.php/assignsubmission_file/{name}">{name}</a>' for name in files)
        action = "Editar entrega" if files else "Agregar entrega"
        closed_text = "<p>Esta tarea está cerrada</p>" if self.state["closed"] else ""
        return f'''<!doctype html><html><body><main id="region-main">
          <h1>Tarea de ejemplo</h1><div id="intro">Subir los archivos finales.</div>{closed_text}
          <table class="submissionstatustable"><tr><th>Estado de la entrega</th><td>Sin entrega</td></tr>
          <tr><th>Archivos enviados</th><td class="files">{links}</td></tr></table>
          <a href="/mod/assign/view.php?id=1&amp;action=editsubmission">{action}</a>
        </main></body></html>'''

    def edit_html(self):
        current_files = self.state["saved_files"]
        if current_files is None:
            current_files = self.state["existing_files"]
        existing = "".join(f'<div class="fp-file"><input type="checkbox" data-togglegroup="files" data-toggle="slave" data-fullname="{name}"><div class="fp-filename">{name}</div></div>' for name in current_files)
        add_control = '<div class="fp-btn-add"><a role="button" id="add-link">Agregar</a></div>' if self.state.get("inner_add") else '<button type="button" class="fp-btn-add">Agregar</button>'
        save_control = self.state.get("save_control") or '<button type="submit">Guardar cambios</button>'
        manager = f'''<div class="filemanager fm-updating" data-maxfiles="2" data-maxbytes="1000000">
          <button type="button" class="fp-vb-details">Detalles</button>{add_control}<button type="button" class="fp-btn-delete">Eliminar</button>
          <div class="fp-content">{existing}</div></div>''' if self.state["has_filemanager"] else ""
        return f'''<!doctype html><html><body><main id="region-main"><h1>Tarea de ejemplo</h1>
          <form id="editform" method="post" action="/save">{manager}
          {save_control}<button type="button" id="grade" onclick="fetch('/grade')">Enviar tarea</button></form>
          <script>
          const form = document.querySelector('#editform');
          form.addEventListener('submit', () => {{
            document.querySelectorAll('.fp-filename').forEach((el) => {{
              const input = document.createElement('input'); input.type = 'hidden'; input.name = 'filename'; input.value = el.textContent;
              form.appendChild(input);
            }});
          }});
          const fm = document.querySelector('.filemanager');
          if (fm) {{
            setTimeout(() => {{
              fm.classList.remove('fm-updating');
              if (!fm.querySelector('.fp-file')) fm.classList.add('fm-nofiles', 'fm-noitems');
            }}, 50);
            fm.querySelector('.fp-vb-details').onclick = (event) => event.currentTarget.classList.add('checked');
            const add = fm.querySelector('.fp-btn-add a, .fp-btn-add');
            add.onclick = () => {{
              const dialog = document.createElement('div'); dialog.id = 'file-dialog'; dialog.setAttribute('role', 'dialog');
              dialog.innerHTML = '<button type="button" id="repo">Subir un archivo</button>'; document.body.appendChild(dialog);
              dialog.querySelector('#repo').onclick = () => {{
                dialog.innerHTML = '<div class="fp-file"><input type="file" id="fileupload"></div><button type="button" class="fp-upload-btn">Subir este archivo</button><button type="button" id="cancel">Cancelar</button>';
                dialog.querySelector('.fp-upload-btn').onclick = () => {{
                  const file = dialog.querySelector('#fileupload').files[0];
                  if ({str(bool(self.state['reject_names'])).lower()} && file && file.name.endsWith('.pdf')) {{
                    dialog.innerHTML = '<p class="alert-danger">Tipo de archivo rechazado</p><button type="button" id="cancel">Cancelar</button>';
                    dialog.querySelector('#cancel').onclick = () => dialog.remove(); return;
                  }}
                  const item = document.createElement('div'); item.className = 'fp-file';
                  const name = document.createElement('div'); name.className = 'fp-filename'; name.textContent = file.name;
                  item.appendChild(name); fm.querySelector('.fp-content').appendChild(item);
                  dialog.remove();
                }};
              }};
            }};
            fm.querySelector('.fp-btn-delete').onclick = () => {{
              const dialog = document.createElement('div'); dialog.setAttribute('role', 'dialog');
              dialog.innerHTML = '<button type="button" id="delete">Sí</button>'; document.body.appendChild(dialog);
              dialog.querySelector('#delete').onclick = () => {{ fm.querySelectorAll('.fp-file input:checked').forEach((input) => input.closest('.fp-file').remove()); dialog.remove(); }};
            }};
          }}
          </script></main></body></html>'''

    def make_files(self, directory):
        docx = Path(directory) / "entrega.docx"
        pdf = Path(directory) / "entrega.pdf"
        docx.write_bytes(b"docx")
        pdf.write_bytes(b"pdf")
        return docx, pdf

    def test_missing_local_file_does_not_open_moodle(self):
        result = upload_files(self.page, self.config, 1, ["/tmp/no-existe-entrega.pdf"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["uploaded_files"], [])
        self.assertEqual(self.state["requests"], [])

    def test_closed_activity_is_not_modified(self):
        self.state["closed"] = True
        with tempfile.TemporaryDirectory() as directory:
            docx, pdf = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx), str(pdf)])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.state["requests"], [("GET", "/mod/assign/view.php")])

    def test_existing_files_are_preserved_without_explicit_replacement(self):
        self.state["existing_files"] = ["anterior.pdf"]
        with tempfile.TemporaryDirectory() as directory:
            docx, pdf = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx), str(pdf)])
        self.assertEqual(result["status"], "blocked_existing_files")
        self.assertEqual(result["existing_files"], ["anterior.pdf"])
        self.assertFalse(self.state["saved_files"])

    def test_docx_and_pdf_are_saved_without_submitting_for_grading(self):
        with tempfile.TemporaryDirectory() as directory:
            docx, pdf = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx), str(pdf)])
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["uploaded_files"], ["entrega.docx", "entrega.pdf"])
        self.assertEqual(self.state["saved_files"], ["entrega.docx", "entrega.pdf"])
        self.assertFalse(result["sent_for_grading"])
        self.assertTrue(result["complete"])

    def test_upload_authenticates_before_opening_submission(self):
        self.state["require_login"] = True
        with tempfile.TemporaryDirectory() as directory:
            docx, _ = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx)])
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(self.state["login_count"], 1)
        self.assertTrue(self.state["authenticated"])

    def test_partial_moodle_rejection_saves_only_confirmed_file(self):
        self.state["reject_names"] = {"entrega.pdf"}
        with tempfile.TemporaryDirectory() as directory:
            docx, pdf = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx), str(pdf)])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["uploaded_files"], ["entrega.docx"])
        self.assertEqual(result["failed_files"], ["entrega.pdf"])
        self.assertEqual(self.state["saved_files"], ["entrega.docx"])
        self.assertFalse(result["complete"])
        self.assertFalse(result["sent_for_grading"])

    def test_explicit_replacement_removes_old_files_and_saves_new_ones(self):
        self.state["existing_files"] = ["anterior.pdf"]
        with tempfile.TemporaryDirectory() as directory:
            docx, pdf = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx), str(pdf)], replace_existing=True)
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["replaced_files"], ["anterior.pdf"])
        self.assertEqual(self.state["saved_files"], ["entrega.docx", "entrega.pdf"])

    def test_failed_replacement_preserves_the_previous_submission(self):
        self.state["existing_files"] = ["anterior.pdf"]
        self.state["reject_names"] = {"entrega.pdf"}
        with tempfile.TemporaryDirectory() as directory:
            docx, pdf = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx), str(pdf)], replace_existing=True)
        self.assertEqual(result["status"], "replacement_cancelled")
        self.assertEqual(result["replaced_files"], [])
        self.assertIsNone(self.state["saved_files"])
        self.assertEqual(result["failed_files"], ["entrega.pdf"])

    def test_activity_without_file_manager_is_blocked(self):
        self.state["has_filemanager"] = False
        with tempfile.TemporaryDirectory() as directory:
            docx, _ = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx)])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.state["saved_files"], None)

    def test_inner_add_control_and_submitbutton_save_without_sending_for_grading(self):
        self.state["inner_add"] = True
        self.state["save_control"] = '<input type="submit" id="id_submitbutton" name="submitbutton" value="Guardar cambios&nbsp;">'
        with tempfile.TemporaryDirectory() as directory:
            docx, pdf = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx), str(pdf)])
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["uploaded_files"], ["entrega.docx", "entrega.pdf"])
        self.assertNotIn(("GET", "/grade"), self.state["requests"])
        self.assertFalse(result["sent_for_grading"])

    def test_explicit_no_upload_instruction_blocks_changes(self):
        original_view_html = self.view_html

        def view_with_no_upload():
            return original_view_html().replace("Subir los archivos finales.", "No se deben subir documentos.")

        self.view_html = view_with_no_upload
        with tempfile.TemporaryDirectory() as directory:
            docx, _ = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx)])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.state["saved_files"], None)


if __name__ == "__main__":
    unittest.main()
