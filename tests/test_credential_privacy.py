import unittest
from unittest.mock import patch
from urllib.parse import quote

from moodle_tasks.errors import redact_credentials
from moodle_tasks.main import Config, main
from moodle_tasks.setup import ask_account


class CredentialPrivacyTests(unittest.TestCase):
    def test_config_repr_hides_password(self):
        settings = Config('https://moodle.test', 'student', 'private-test-password', True)
        self.assertNotIn(settings.password, repr(settings))

    def test_terminal_hides_credentials_in_partial_and_fatal_errors(self):
        settings = Config('https://moodle.test', 'private-test-user', 'test/pass+word', True)
        failure = f'{settings.username} {settings.password} {quote(settings.password, safe="")}'
        for fatal in (False, True):
            with self.subTest(fatal=fatal):
                with patch('moodle_tasks.main.load_config', return_value=settings), patch(
                    'moodle_tasks.main.collect_assignments',
                    side_effect=RuntimeError(failure) if fatal else None,
                    return_value=([], [failure]),
                ), patch('moodle_tasks.main.print_tasks'), patch('builtins.print') as output:
                    if fatal:
                        with self.assertRaises(SystemExit):
                            main([])
                    else:
                        main([])
                    text = ' '.join(str(call.args[0]) for call in output.call_args_list)
                self.assertNotIn(settings.username, text)
                self.assertNotIn(settings.password, text)
                self.assertNotIn(quote(settings.password, safe=''), text)
                self.assertIn('[oculto]', text)

    def test_unexpected_login_error_hides_new_unsaved_password(self):
        with patch('builtins.input', return_value='student@example.test'), patch(
            'moodle_tasks.setup.getpass.getpass', return_value='unsaved-test-secret'
        ), patch('moodle_tasks.setup.verify_credentials', side_effect=RuntimeError('Unexpected unsaved-test-secret')):
            with self.assertRaises(RuntimeError) as caught:
                ask_account('https://moodle.test')
        self.assertNotIn('unsaved-test-secret', str(caught.exception))
        self.assertIn('[oculto]', str(caught.exception))

    def test_redaction_preserves_errors_without_credentials(self):
        self.assertEqual(redact_credentials('HTTP 502', (None, '')), 'HTTP 502')
