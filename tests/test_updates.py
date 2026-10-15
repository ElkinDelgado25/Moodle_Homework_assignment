import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
