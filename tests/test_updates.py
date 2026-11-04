import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

from moodle_tasks import updates


class UpdateTests(unittest.TestCase):
    release = updates.Release("v0.3.0", "0.3.0", f"{updates.RELEASE_PAGE}/v0.3.0")

    def test_setup_installs_latest_without_prompt_even_outside_a_terminal(self):
        with patch.object(updates, "fetch_latest_release", return_value=self.release), patch.object(
            updates, "installed_version", return_value="0.2.0"
        ), patch.object(updates, "_apply_release") as apply, patch.object(
            updates.sys.stdin, "isatty", return_value=False
        ), patch.object(updates.Confirm, "ask") as ask:
            self.assertTrue(updates.update_from_setup(Console(file=io.StringIO())))
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[0], self.release)
        ask.assert_not_called()

    def test_setup_can_continue_if_github_fails_or_local_checkout_cannot_update(self):
        for failure in ("GitHub sin conexión", "El clon tiene cambios locales"):
            output = io.StringIO()
            with self.subTest(failure=failure), patch.object(
                updates, "update_latest", side_effect=updates.UpdateError(failure)
            ):
                self.assertFalse(updates.update_from_setup(Console(file=output)))
            self.assertIn(failure, output.getvalue())
            self.assertIn("configuración continuará", output.getvalue())

    def test_continuation_uses_installed_python_and_preserves_options_on_each_platform(self):
        for platform, relative in (("linux", "bin/python"), ("win32", "Scripts/python.exe")):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "tools with spaces"
                python = root / updates.PROJECT_NAME / relative
                python.parent.mkdir(parents=True)
                python.touch()
                arguments = ["--agent", "cursor", "--config-dir", str(Path(directory) / "my account")]
                with patch.object(updates.sys, "platform", platform), patch.object(
                    updates.subprocess, "run", side_effect=[
                        subprocess.CompletedProcess([], 0, str(root) + "\n"),
                        subprocess.CompletedProcess([], 0),
                    ]
                ) as run:
                    updates.continue_with_updated_setup(arguments)
                self.assertEqual(run.call_args_list[1].args[0], [
                    str(python), "-m", "moodle_tasks.setup", "--skip-update", "--sync-after-update", *arguments
                ])
                self.assertNotIn("shell", run.call_args_list[1].kwargs)

    def test_continuation_propagates_sync_failure_exit_code(self):
        with patch.object(updates.Path, "is_file", return_value=True), patch.object(
            updates.subprocess, "run", side_effect=[
                subprocess.CompletedProcess([], 0, "/tmp/tools\n"),
                subprocess.CompletedProcess([], 1),
            ]
        ), self.assertRaises(SystemExit) as caught:
            updates.continue_with_updated_setup(["--sync-only"])
        self.assertEqual(caught.exception.code, 1)

    def test_manual_update_synchronizes_when_already_current(self):
        with patch.object(updates, "fetch_latest_release", return_value=self.release), patch.object(
            updates, "installed_version", return_value=self.release.version
        ), patch("moodle_tasks.setup.main") as setup:
            updates.main([])
        setup.assert_called_once_with(["--skip-update", "--sync-only"])

    def test_manual_update_continues_with_new_code_only_after_success(self):
        for updated in (True, False):
            with self.subTest(updated=updated), patch.object(
                updates, "fetch_latest_release", return_value=self.release
            ), patch.object(updates, "installed_version", return_value="0.2.0"), patch.object(
                updates, "update_latest", return_value=updated
            ), patch.object(updates, "continue_with_updated_setup") as continuation, patch(
                "moodle_tasks.setup.main"
            ) as setup:
                updates.main([])
            setup.assert_not_called()
            if updated:
                continuation.assert_called_once_with(["--sync-only"])
            else:
                continuation.assert_not_called()

    def test_update_failure_is_printed_to_stderr_without_crashing(self):
        stderr = io.StringIO()
        with patch.object(updates, "fetch_latest_release", side_effect=updates.UpdateError("sin red")), patch(
            "sys.stderr", stderr
        ), self.assertRaises(SystemExit) as exit_:
            updates.main([])
        self.assertEqual(exit_.exception.code, 1)
        self.assertIn("sin red", stderr.getvalue())

    def test_checkout_root_explains_why_each_candidate_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "borrado"
            not_git = Path(directory)
            with patch.object(updates, "_source_candidates", return_value=[missing, not_git]), patch.object(
                updates, "_run_git", side_effect=updates.UpdateError("no es un repositorio")
            ):
                with self.assertRaises(updates.UpdateError) as error:
                    updates.checkout_root()
        message = str(error.exception)
        self.assertIn("ya no existe", message)
        self.assertIn("no es un repositorio", message)

    def test_checkout_root_reports_missing_git_and_untrusted_clone_directly(self):
        with tempfile.TemporaryDirectory() as directory:
            for failure in (updates.GitMissingError("No se encontró Git."),
                            updates.UntrustedCheckoutError("safe.directory")):
                with self.subTest(failure=type(failure).__name__), patch.object(
                    updates, "_source_candidates", return_value=[Path(directory)]
                ), patch.object(updates, "_run_git", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        updates.checkout_root()

    def test_checkout_root_reports_unreadable_candidate_without_crashing(self):
        unreadable = MagicMock(spec=Path)
        unreadable.exists.side_effect = PermissionError(13, "Permiso denegado")
        unreadable.__str__.return_value = "/srv/clon"
        with patch.object(updates, "_source_candidates", return_value=[unreadable]):
            with self.assertRaises(updates.UpdateError) as error:
                updates.checkout_root()
        self.assertIn("/srv/clon: Permiso denegado", str(error.exception))

    def test_checkout_root_distinguishes_files_and_tries_next_candidate_after_untrusted_clone(self):
        with tempfile.TemporaryDirectory() as directory:
            a_file = Path(directory) / "archivo"
            a_file.write_text("x")
            untrusted, trusted = Path(directory) / "ajeno", Path(directory) / "propio"
            untrusted.mkdir()
            trusted.mkdir()
            (trusted / "pyproject.toml").write_text('[project]\nname = "moodle-homework-assignment"\nversion = "1.0.0"\n')

            def git(root, *arguments, check=True):
                if root == untrusted:
                    raise updates.UntrustedCheckoutError("safe.directory")
                return subprocess.CompletedProcess([], 0, str(trusted), "")

            with patch.object(updates, "_source_candidates", return_value=[a_file, untrusted, trusted]), patch.object(
                updates, "_run_git", side_effect=git
            ):
                self.assertEqual(updates.checkout_root(), trusted.resolve())
            with patch.object(updates, "_source_candidates", return_value=[a_file]):
                with self.assertRaises(updates.UpdateError) as error:
                    updates.checkout_root()
        message = str(error.exception)
        self.assertIn("no es una carpeta", message)
        self.assertNotIn("..", message)
        self.assertIn("vuelve a clonar", message)

    def test_git_failure_includes_git_reason(self):
        result = subprocess.CompletedProcess(
            [], 128, "", "fatal: unable to access 'https://user:abc@github.com/x.git/': timeout.\n"
        )
        with patch.object(updates.subprocess, "run", return_value=result):
            with self.assertRaises(updates.UpdateError) as error:
                updates._run_git(Path("/tmp/clon"), "fetch")
        message = str(error.exception)
        self.assertIn("git fetch", message)
        self.assertIn("unable to access 'https://github.com/x.git/'", message)
        self.assertNotIn("abc@", message)

    def test_dubious_ownership_suggests_safe_directory_for_repository_root(self):
        stderr = ("fatal: detected dubious ownership in repository at '/srv/Moodle_Homework_assignment'\n"
                  "To add an exception for this directory, call:\n")
        result = subprocess.CompletedProcess([], 128, "", stderr)
        with patch.object(updates.subprocess, "run", return_value=result):
            with self.assertRaises(updates.UntrustedCheckoutError) as error:
                updates._run_git(Path("/srv/Moodle_Homework_assignment/lib/python3.11"), "status")
        message = str(error.exception)
        self.assertIn('git config --global --add safe.directory "/srv/Moodle_Homework_assignment"', message)
        self.assertNotIn("Windows", message)

    def test_dirty_checkout_is_not_changed_by_automatic_update(self):
        def git(_root, *arguments, **_options):
            output = {
                ("remote", "get-url", "origin"): f"https://github.com/{updates.REPOSITORY}.git\n",
                ("status", "--porcelain=v1", "--untracked-files=all"): " M local-file\n",
            }[arguments]
            return subprocess.CompletedProcess([], 0, output)

        with patch.object(updates, "checkout_root", return_value=Path("/tmp/source")), patch.object(
            updates, "_run_git", side_effect=git
        ) as run, patch.object(updates, "_run_step") as step:
            with self.assertRaisesRegex(updates.UpdateError, "cambios locales"):
                updates._apply_release(self.release, Console(file=io.StringIO()))
        self.assertEqual(run.call_count, 2)
        step.assert_not_called()

    def test_release_install_uses_exact_tag_and_forces_reinstall_with_locked_dependencies(self):
        def git(_root, *arguments, **_options):
            output = {
                ("remote", "get-url", "origin"): f"https://github.com/{updates.REPOSITORY}.git\n",
                ("status", "--porcelain=v1", "--untracked-files=all"): "",
                ("rev-parse", "--abbrev-ref", "HEAD"): "main\n",
                ("rev-parse", "HEAD"): "previous-commit\n",
                ("rev-parse", "refs/tags/v0.3.0^{commit}"): "release-commit\n",
            }.get(arguments, "")
            return subprocess.CompletedProcess([], 0, output)

        with patch.object(updates, "checkout_root", return_value=Path("/tmp/source")), patch.object(
            updates, "_run_git", side_effect=git
        ) as run, patch.object(updates, "_project_version", return_value="0.2.0"), patch.object(
            updates, "_version_at_tag", return_value=self.release.version
        ), patch.object(updates, "_ancestor", return_value=True), patch.object(updates, "_run_step") as step:
            updates._apply_release(self.release, Console(file=io.StringIO()))
        self.assertIn((Path("/tmp/source"), "checkout", "--detach", "refs/tags/v0.3.0"),
                      [call.args for call in run.call_args_list])
        commands = [call.args[0] for call in step.call_args_list]
        self.assertEqual(commands[0], ["uv", "sync", "--locked"])
        self.assertIn("--locked", commands[1])
        install = commands[2]
        self.assertIn("--force", install)
        self.assertEqual(install[install.index("--reinstall-package") + 1], updates.PROJECT_NAME)
        self.assertEqual(install[install.index("--constraints") + 1], commands[1][-1])
