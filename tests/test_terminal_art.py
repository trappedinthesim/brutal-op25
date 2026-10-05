import os
import tempfile
import unittest
from unittest.mock import patch

from terminal_art import ACCENT_BLUE, TOWER, WORDMARK, banner, paint


class TerminalArtTests(unittest.TestCase):
    def test_tower_is_compact_ascii_and_keeps_upstream_credit(self):
        self.assertTrue(TOWER.isascii())
        self.assertEqual(len(TOWER.splitlines()), 10)
        self.assertLessEqual(max(map(len, TOWER.splitlines())), 24)
        self.assertIn(r'   \  \    /\    /  /', TOWER)
        self.assertIn('    /______||______\\', TOWER)
        text = banner(80, False, unicode=True)
        self.assertEqual(text.splitlines()[:3], WORDMARK.splitlines())
        self.assertEqual(text.splitlines()[4:14],
                         [' ' * 10 + line for line in TOWER.splitlines()])
        self.assertIn('BUILT ON BOATBOD / OP25', text)
        self.assertEqual(len(text.splitlines()), 17)
        compact = banner(80, False, compact=True).splitlines()
        self.assertEqual(len(compact), 2)
        self.assertNotIn('/______||______', '\n'.join(compact))

    def test_small_or_non_unicode_terminals_use_plain_header(self):
        self.assertNotIn(WORDMARK.splitlines()[0], banner(40, False))
        self.assertIn(TOWER, banner(40, False))
        self.assertNotIn(TOWER, banner(20, False))
        self.assertNotIn(WORDMARK.splitlines()[0], banner(80, False, unicode=False))
        with patch('terminal_art.sys.stdout') as output:
            output.encoding = 'ascii'
            self.assertTrue(banner(80, False).isascii())

    def test_narrow_terminal_has_no_overflow(self):
        for width in (1, 12, 24, 31, 40, 56, 80):
            with self.subTest(width=width):
                self.assertTrue(all(len(line) <= width for line in banner(width, False).splitlines()))

    def test_color_is_optional_and_always_reset(self):
        self.assertNotIn('\033', banner(80, False))
        self.assertTrue(banner(80, True).endswith('\033[0m'))
        self.assertEqual(paint('Menu', True), '\033[38;2;76;144;240mMenu\033[0m')
        with patch('terminal_art.sys.stdout.isatty', return_value=True), \
                patch.dict(os.environ, {'NO_COLOR': ''}):
            self.assertNotIn('\033', banner(80))

    def test_terminal_styles_output_prompts_and_secret_prompts(self):
        from brutal_cli import Terminal
        with tempfile.TemporaryDirectory() as root, \
                patch('terminal_art.sys.stdout.isatty', return_value=True), \
                patch.dict(os.environ, {'TERM': 'xterm-256color'}, clear=True):
            output, prompt, secret = [], [], []
            terminal = Terminal(root, lambda s: prompt.append(s), output.append,
                                lambda s: secret.append(s))
            terminal.output('Ready')
            terminal.prompt('Choose: ')
            terminal.secret('Password: ')
            for text in output + prompt + secret:
                self.assertTrue(text.startswith(ACCENT_BLUE))
                self.assertTrue(text.endswith('\033[0m'))


if __name__ == '__main__':
    unittest.main()
