"""Flujo completo contra un Moodle local: listar, leer, descargar, generar el entregable y subirlo."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client

from helpers import make_pdf
from fake_moodle import FakeMoodle
from moodle_tasks.server import create_server


class EndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        pdf = make_pdf(self.root / "guia.pdf")
        self.moodle = FakeMoodle(pdf.read_bytes()).__enter__()
        self.env_file = self.root / "credentials.env"
        self.env_file.write_text(f"MOODLE_URL={self.moodle.base_url}\nMOODLE_USERNAME={FakeMoodle.USERNAME}\n"
                                 f"MOODLE_PASSWORD={FakeMoodle.PASSWORD}\n")
        self.config_dir = self.root / "config"
        self.deliveries = self.root / "Entregas"
        self.opened = []
        environment = {key: value for key, value in os.environ.items() if not key.startswith("MOODLE_")}
        environment["MOODLE_SESSION_CACHE"] = "true"
        self.patchers = [
            patch.dict(os.environ, environment, clear=True),
            *(patch(target, return_value=self.config_dir) for target in (
                "moodle_tasks.server.user_config_dir", "moodle_tasks.session.user_config_dir",
                "moodle_tasks.paths.user_config_dir")),
            *(patch(target, return_value=self.root / "cache") for target in (
                "moodle_tasks.paths.user_cache_dir", "moodle_tasks.delivery.user_cache_dir")),
            patch("moodle_tasks.paths.default_env_file", return_value=self.env_file),
            patch("moodle_tasks.document.find_soffice", return_value=None),
            patch("moodle_tasks.server.open_file", side_effect=lambda path: self.opened.append(path) or True),
        ]
        for patcher in self.patchers:
            patcher.start()

    async def asyncTearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.moodle.__exit__(None, None, None)
        self.temporary.cleanup()

    async def test_full_flow_with_one_login(self):
        async with Client(create_server(self.env_file)) as client:
            listing = await client.call_tool("list_assignments")
            self.assertFalse(listing.is_error, listing)
            data = listing.structured_content
            self.assertEqual(data["returned_count"], 1)
            row = data["assignments"][0]
            self.assertEqual(row["assignment_id"], FakeMoodle.ASSIGNMENT_ID)
            self.assertIn("Práctica 3", data["response_markdown"])

            detail = await client.call_tool("get_assignment", {"assignment_id": row["assignment_id"]})
            self.assertFalse(detail.is_error, detail)
            task = detail.structured_content
            self.assertIn("Desarrolle la aplicación", task["description"])
            self.assertEqual(task["course"], "Desarrollo Móvil")
            pages = [item for item in task["linked_resources"] if item.get("content")]
            self.assertEqual(len(pages), 1, task["linked_resources"])
            self.assertIn("repositorio público en GitHub", pages[0]["content"])

            download = await client.call_tool("download_assignment_attachments", {
                "assignment_id": row["assignment_id"], "destination_directory": str(self.root / "Material")})
            files = download.structured_content["files"]
            self.assertEqual([item["name"] for item in files], ["guia.pdf"])
            self.assertTrue(Path(files[0]["path"]).read_bytes().startswith(b"%PDF-"))

            build = await client.call_tool("build_delivery_document", {
                "document": {"title": "Práctica 3: App con Compose",
                             "blocks": [{"type": "heading", "level": 1, "text": "Desarrollo"},
                                        {"type": "paragraph", "text": "Se implementó la pantalla principal. Repositorio: https://github.com/estudiante/practica-3"}]},
                "cover": {"materia": "Desarrollo Móvil", "nombre_docente": "Ing. Ana Pérez", "estudiantes": ["Carlos Mendoza"],
                          "carrera": "Software", "curso": "Quinto A", "anio": "2026"},
                "destination_directory": str(self.deliveries)})
            self.assertFalse(build.is_error, build)
            built = build.structured_content
            self.assertEqual(built["status"], "ok")
            self.assertIn("https://github.com/estudiante/practica-3", built["hyperlinks"])
            self.assertEqual(self.opened, [Path(built["pdf_path"])])

            upload = await client.call_tool("upload_assignment_files", {
                "assignment_id": row["assignment_id"], "file_paths": [built["docx_path"], built["pdf_path"]]})
            self.assertFalse(upload.is_error, upload)
            result = upload.structured_content
            self.assertEqual(result["status"], "uploaded", result)
            self.assertEqual(sorted(self.moodle.saved_files), ["Práctica 3 App con Compose.docx", "Práctica 3 App con Compose.pdf"])
            self.assertEqual(result["submission"]["state"], "draft")
            self.assertTrue(result["submission"]["requires_submit_for_grading"])

            retry = await client.call_tool("upload_assignment_files", {
                "assignment_id": row["assignment_id"], "file_paths": [built["docx_path"], built["pdf_path"]]})
            self.assertEqual(retry.structured_content["status"], "already_uploaded")

            secret_leak = await client.call_tool("upload_assignment_files", {
                "assignment_id": row["assignment_id"], "file_paths": [str(self.env_file)]})
            self.assertEqual(secret_leak.structured_content["status"], "blocked")

        # Una sola sesión para todo el flujo y ninguna credencial en las respuestas.
        self.assertEqual(self.moodle.logins, 1)
        for result in (listing, detail, download, build, upload, retry, secret_leak):
            self.assertNotIn(FakeMoodle.PASSWORD, json.dumps(result.structured_content, ensure_ascii=False))
        self.assertFalse(any(path.endswith("/grade") for _, path in self.moodle.requests))

    async def test_wrong_password_reports_an_error_and_keeps_no_session(self):
        self.env_file.write_text(f"MOODLE_URL={self.moodle.base_url}\nMOODLE_USERNAME={FakeMoodle.USERNAME}\nMOODLE_PASSWORD=incorrecta\n")
        async with Client(create_server(self.env_file)) as client:
            result = await client.call_tool("get_assignment", {"assignment_id": FakeMoodle.ASSIGNMENT_ID})
        self.assertTrue(result.is_error)
        self.assertNotIn("incorrecta", str(result))
        self.assertFalse((self.config_dir / "sessions").exists() and any((self.config_dir / "sessions").iterdir()))


if __name__ == "__main__":
    unittest.main()
