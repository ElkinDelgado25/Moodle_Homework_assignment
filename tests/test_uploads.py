import html
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from moodle_tasks.main import Config
from moodle_tasks.uploads import forbids_upload, moodle_name, upload_files

from helpers import make_docx, make_pdf


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
        self.state = {"existing_files": [], "saved_files": None, "closed": False, "description": "Subir los archivos finales.",
                      "has_filemanager": True, "reject_names": set(), "requests": [], "posts": [],
                      "require_login": False, "authenticated": False, "login_count": 0,
                      "drafts": True, "status_extra": "", "banner": False, "delayed_files": [], "hide_in_form": False,
                      "statement": False, "form_error": False, "form_cancel": False, "reject_without_cancel": False,
                      "sanitize": False, "maxfiles_js": None, "maxfiles_attr": "2"}
        self.page.route("**/*", self.respond)

    def tearDown(self):
        self.page.close()

    def respond(self, route):
        request = route.request
        parts = urlsplit(request.url)
        self.state["requests"].append((request.method, parts.path))
        html_response = lambda body: route.fulfill(content_type="text/html; charset=utf-8", body=body)
        if self.state["require_login"] and parts.path in ("/login/index.php", "/my/", "/mod/assign/view.php"):
            if parts.path == "/my/" and request.method == "POST":
                self.state["authenticated"] = True
                self.state["login_count"] += 1
                return html_response('<a href="/login/logout.php">Salir</a>')
            if not self.state["authenticated"]:
                return html_response(self.login_html())
        if parts.path == "/save" and request.method == "POST":
            values = parse_qs(request.post_data or "")
            self.state["posts"].append(values)
            if "cancel" in values:
                return html_response(self.view_html())
            if self.state["form_error"]:
                return html_response(self.edit_html(error=True))
            self.state["saved_files"] = values.get("filename", [])
            return html_response(self.view_html())
        if parts.path == "/mod/assign/view.php":
            if parse_qs(parts.query).get("action") == ["editsubmission"]:
                return html_response(self.edit_html())
            return html_response(self.view_html())
        return route.fulfill(status=404, body="Not found")

    def login_html(self):
        return '''<!doctype html><html><body><form id="login" action="/my/" method="post">
          <input name="username"><input name="password"><button type="submit">Acceder</button>
        </form></body></html>'''

    def view_html(self):
        files = self.state["saved_files"]
        if files is None:
            files = self.state["existing_files"]
        links = "".join(f'<a href="/pluginfile.php/1/assignsubmission_file/submission_files/9/{html.escape(name)}">{html.escape(name)}</a>' for name in files)
        if self.state["saved_files"]:
            status = "Borrador (no enviado)" if self.state["drafts"] else "Enviado para calificar"
        else:
            status = "No se ha enviado nada en esta tarea"
        grade = '<button type="button" id="grade">Enviar tarea</button>' if self.state["saved_files"] and self.state["drafts"] else ""
        closed_text = "<p>Esta tarea está cerrada</p>" if self.state["closed"] else ""
        banner = '<div class="alert alert-danger">Mantenimiento programado el sábado</div>' if self.state["banner"] else ""
        return f'''<!doctype html><html><body>{banner}<main id="region-main">
          <h1>Tarea de ejemplo</h1><div id="intro">{self.state["description"]}</div>{closed_text}
          <table class="submissionstatustable"><tr><th>Estado de la entrega</th><td>{status}{self.state["status_extra"]}</td></tr>
          <tr><th>Archivos enviados</th><td class="files">{links}</td></tr></table>{grade}
        </main></body></html>'''

    def edit_html(self, error=False):
        current_files = self.state["saved_files"]
        if current_files is None:
            current_files = [] if self.state["hide_in_form"] else self.state["existing_files"]
        existing = "".join(f'<div class="fp-file"><input type="checkbox" data-togglegroup="files" data-toggle="slave" data-fullname="{name}"><div class="fp-filename">{name}</div></div>' for name in current_files)
        add_control = '<div class="fp-btn-add"><a role="button" id="add-link">Agregar</a></div>' if self.state.get("inner_add") else '<button type="button" class="fp-btn-add">Agregar</button>'
        save_control = self.state.get("save_control") or '<button type="submit">Guardar cambios</button>'
        cancel_control = '<button type="submit" name="cancel" value="1">Cancelar</button>' if self.state["form_cancel"] else ""
        initial = "fm-loading" if self.state["delayed_files"] else "fm-updating"
        maxfiles = f' data-maxfiles="{self.state["maxfiles_attr"]}"' if self.state["maxfiles_attr"] is not None else ""
        manager = f'''<div class="filemanager {initial}"{maxfiles} data-maxbytes="1000000">
          <button type="button" class="fp-vb-details">Detalles</button>{add_control}<button type="button" class="fp-btn-delete">Eliminar</button>
          <div class="fp-content">{existing}</div></div>''' if self.state["has_filemanager"] else ""
        statement = '<input type="checkbox" name="submissionstatement" id="id_submissionstatement"><label for="id_submissionstatement">Declaro que este trabajo es original.</label>' if self.state["statement"] else ""
        feedback = '<div class="invalid-feedback" style="display:block">Debe aceptar la declaración.</div>' if error else ""
        init = f'<script>M = {{form_filemanager: {{init: function(){{}}}}}}; M.form_filemanager.init(Y, {{"maxfiles":{self.state["maxfiles_js"]},"maxbytes":1000000}});</script>' if self.state["maxfiles_js"] is not None else ""
        reject_dialog = ('<p class="alert-danger">Tipo de archivo rechazado</p>' if self.state["reject_without_cancel"]
                         else '<p class="alert-danger">Tipo de archivo rechazado</p><button type="button" id="cancel">Cancelar</button>')
        banner = '<div class="alert alert-danger">Mantenimiento programado el sábado</div>' if self.state["banner"] else ""
        return f'''<!doctype html><html><body>{banner}<main id="region-main"><h1>Tarea de ejemplo</h1>{init}{feedback}
          <form id="editform" method="post" action="/save">{manager}{statement}
          {save_control}{cancel_control}<button type="button" id="grade" onclick="fetch('/grade')">Enviar tarea</button></form>
          <script>
          const sanitize = {str(self.state["sanitize"]).lower()};
          const form = document.querySelector('#editform');
          form.addEventListener('submit', (event) => {{
            if (event.submitter && event.submitter.name === 'cancel') return;
            document.querySelectorAll('.fp-filename').forEach((el) => {{
              const input = document.createElement('input'); input.type = 'hidden'; input.name = 'filename'; input.value = el.textContent;
              form.appendChild(input);
            }});
          }});
          const fm = document.querySelector('.filemanager');
          if (fm) {{
            const delayed = {list(self.state["delayed_files"])!r};
            setTimeout(() => {{
              delayed.forEach((name) => {{
                const item = document.createElement('div'); item.className = 'fp-file';
                item.innerHTML = '<div class="fp-filename"></div>'; item.firstChild.textContent = name;
                fm.querySelector('.fp-content').appendChild(item);
              }});
              fm.classList.remove('fm-updating', 'fm-loading');
              fm.classList.add('fm-loaded');
              if (!fm.querySelector('.fp-file')) fm.classList.add('fm-nofiles', 'fm-noitems');
            }}, delayed.length ? 600 : 50);
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
                    dialog.innerHTML = {reject_dialog!r};
                    const cancel = dialog.querySelector('#cancel'); if (cancel) cancel.onclick = () => dialog.remove();
                    document.addEventListener('keydown', (e) => {{ if (e.key === 'Escape') dialog.remove(); }}, {{once: true}});
                    return;
                  }}
                  let label = file.name;
                  if (sanitize) label = label.replace(/[&<>"`|':\\\\/]/g, '').replace(/\\s+/g, ' ').trim();
                  const item = document.createElement('div'); item.className = 'fp-file';
                  const name = document.createElement('div'); name.className = 'fp-filename'; name.textContent = label;
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

    def make_files(self, directory, docx_name="entrega.docx", pdf_name="entrega.pdf"):
        docx = Path(directory) / docx_name
        pdf = Path(directory) / pdf_name
        make_docx(docx)
        make_pdf(pdf)
        return docx, pdf

    def upload(self, names=("entrega.docx", "entrega.pdf"), **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            docx, pdf = self.make_files(directory, *names)
            return upload_files(self.page, self.config, 1, [str(docx), str(pdf)], **kwargs)

    # Comportamiento básico

    def test_missing_local_file_does_not_open_moodle(self):
        result = upload_files(self.page, self.config, 1, ["/tmp/no-existe-entrega.pdf"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["uploaded_files"], [])
        self.assertEqual(self.state["requests"], [])

    def test_closed_activity_is_not_modified(self):
        self.state["closed"] = True
        result = self.upload()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.state["requests"], [("GET", "/mod/assign/view.php")])

    def test_docx_and_pdf_are_saved_as_draft_without_submitting_for_grading(self):
        result = self.upload()
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["uploaded_files"], ["entrega.docx", "entrega.pdf"])
        self.assertEqual(self.state["saved_files"], ["entrega.docx", "entrega.pdf"])
        self.assertTrue(result["complete"])
        submission = result["submission"]
        self.assertEqual(submission["state"], "draft")
        self.assertTrue(submission["requires_submit_for_grading"])
        self.assertFalse(submission["submitted_by_tool"])
        self.assertIn("Enviar tarea", submission["note"])
        self.assertNotIn(("GET", "/grade"), self.state["requests"])

    def test_drafts_disabled_reports_submitted_state(self):
        self.state["drafts"] = False
        result = self.upload()
        self.assertEqual(result["submission"]["state"], "submitted")
        self.assertFalse(result["submission"]["requires_submit_for_grading"])

    def test_upload_authenticates_before_opening_submission(self):
        self.state["require_login"] = True
        with tempfile.TemporaryDirectory() as directory:
            docx, _ = self.make_files(directory)
            result = upload_files(self.page, self.config, 1, [str(docx)])
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(self.state["login_count"], 1)

    def test_inner_add_control_and_submitbutton(self):
        self.state["inner_add"] = True
        self.state["save_control"] = '<input type="submit" id="id_submitbutton" name="submitbutton" value="Guardar cambios&nbsp;">'
        result = self.upload()
        self.assertEqual(result["status"], "uploaded")
        self.assertNotIn(("GET", "/grade"), self.state["requests"])

    def test_activity_without_file_manager_is_blocked(self):
        self.state["has_filemanager"] = False
        result = self.upload()
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(self.state["saved_files"])

    # Archivos existentes y reintentos

    def test_existing_files_are_preserved_without_explicit_replacement(self):
        self.state["existing_files"] = ["anterior.pdf"]
        result = self.upload()
        self.assertEqual(result["status"], "blocked_existing_files")
        self.assertEqual(result["existing_files"], ["anterior.pdf"])
        self.assertIsNone(self.state["saved_files"])

    def test_files_that_load_late_in_the_form_still_block(self):
        self.state["delayed_files"] = ["previo.pdf"]
        result = self.upload()
        self.assertEqual(result["status"], "blocked_existing_files")
        self.assertEqual(result["existing_files"], ["previo.pdf"])
        self.assertIsNone(self.state["saved_files"])

    def test_files_shown_on_the_view_page_block_even_if_the_form_hides_them(self):
        self.state["existing_files"] = ["visto.pdf"]
        self.state["hide_in_form"] = True
        result = self.upload()
        self.assertEqual(result["status"], "blocked_existing_files")
        self.assertEqual(result["existing_files"], ["visto.pdf"])

    def test_retry_with_the_same_files_reports_already_uploaded(self):
        self.state["existing_files"] = ["entrega.docx", "entrega.pdf"]
        result = self.upload()
        self.assertEqual(result["status"], "already_uploaded")
        self.assertTrue(result["complete"])
        self.assertEqual(self.state["posts"], [])

    def test_explicit_replacement_removes_old_files_and_saves_new_ones(self):
        self.state["existing_files"] = ["anterior.pdf"]
        result = self.upload(replace_existing=True)
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["replaced_files"], ["anterior.pdf"])
        self.assertEqual(self.state["saved_files"], ["entrega.docx", "entrega.pdf"])

    def test_failed_replacement_preserves_the_previous_submission(self):
        self.state["existing_files"] = ["anterior.pdf"]
        self.state["reject_names"] = {"entrega.pdf"}
        result = self.upload(replace_existing=True)
        self.assertEqual(result["status"], "replacement_cancelled")
        self.assertEqual(result["replaced_files"], [])
        self.assertIsNone(self.state["saved_files"])
        self.assertEqual(result["failed_files"], ["entrega.pdf"])

    # Todo o nada y diálogos

    def test_partial_rejection_saves_nothing(self):
        self.state["reject_names"] = {"entrega.pdf"}
        result = self.upload()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_files"], ["entrega.pdf"])
        self.assertEqual([item["status"] for item in result["files"]], ["not_saved", "failed"])
        self.assertIsNone(self.state["saved_files"])
        self.assertFalse(result["complete"])

    def test_dismissing_a_dialog_never_clicks_the_form_cancel_button(self):
        self.state["reject_names"] = {"entrega.pdf"}
        self.state["form_cancel"] = True
        self.state["reject_without_cancel"] = True
        result = self.upload()
        self.assertEqual(result["status"], "failed")
        self.assertFalse(any("cancel" in post for post in self.state["posts"]))

    def test_a_page_banner_is_not_mistaken_for_an_upload_error(self):
        self.state["banner"] = True
        result = self.upload()
        self.assertEqual(result["status"], "uploaded")

    def test_form_error_after_save_is_reported(self):
        self.state["form_error"] = True
        result = self.upload()
        self.assertEqual(result["status"], "failed")
        self.assertIn("Debe aceptar", " ".join(result["errors"]))
        self.assertIsNone(self.state["saved_files"])

    def test_required_statement_is_never_ticked(self):
        self.state["statement"] = True
        result = self.upload()
        self.assertEqual(result["status"], "requires_statement")
        self.assertIn("original", " ".join(result["errors"]))
        self.assertEqual(self.state["posts"], [])

    # Nombres y límites

    def test_names_sanitized_by_moodle_are_confirmed(self):
        self.state["sanitize"] = True
        result = self.upload(names=("Informe & anexo  final.docx", "Ana's   trabajo.pdf"))
        self.assertEqual(result["status"], "uploaded", result)
        self.assertEqual(self.state["saved_files"], ["Informe anexo final.docx", "Anas trabajo.pdf"])

    def test_maxfiles_from_the_javascript_configuration(self):
        self.state["maxfiles_attr"] = None
        self.state["maxfiles_js"] = 1
        started = time.monotonic()
        result = self.upload()
        self.assertEqual(result["status"], "blocked")
        self.assertIn("máximo 1", result["errors"][0])
        self.assertLess(time.monotonic() - started, 5)

    # Instrucciones y cierre

    def test_explicit_no_upload_instruction_blocks_changes(self):
        self.state["description"] = "No se deben subir documentos."
        result = self.upload()
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(self.state["saved_files"])

    def test_qualified_restriction_does_not_block_the_upload(self):
        self.state["description"] = "No se deben subir archivos comprimidos (ZIP); suba un PDF."
        self.assertEqual(self.upload()["status"], "uploaded")

    def test_closed_wording_in_the_description_does_not_block(self):
        self.state["description"] = "Si la tarea está cerrada, contacte al docente."
        self.assertEqual(self.upload()["status"], "uploaded")

    def test_closed_status_is_detected(self):
        self.state["status_extra"] = " — Envíos cerrados"
        self.assertEqual(self.upload()["status"], "blocked")


class UploadRuleTests(unittest.TestCase):
    def test_forbids_upload(self):
        blocking = ["No se deben subir documentos.", "Do not upload files for this activity.",
                    "No es necesario entregar nada en esta actividad"]
        allowed = ["No se deben subir archivos comprimidos (ZIP); suba un PDF.", "No se debe entregar tarde.",
                   "Do not submit late work.", "Do not upload screenshots, upload the PDF.",
                   "No se requiere subir el código fuente, solo el informe.", "Suba el informe en PDF.", ""]
        for text in blocking:
            self.assertTrue(forbids_upload(text), text)
        for text in allowed:
            self.assertFalse(forbids_upload(text), text)

    def test_moodle_name(self):
        self.assertEqual(moodle_name("Informe & anexo  final.PDF"), "informe anexo final.pdf")
        self.assertEqual(moodle_name("a:b|c\"d.pdf"), "abcd.pdf")
        self.assertEqual(moodle_name("Práctica.pdf"), moodle_name("Práctica.pdf"))


if __name__ == "__main__":
    unittest.main()
