import unittest
from unittest.mock import patch
from terminal_art import SKULL, banner, paint


class TerminalArtTests(unittest.TestCase):
    def test_compact_splash_leaves_room_for_menu(self):
        text = banner(80, False, True)
        self.assertLessEqual(max(map(len, SKULL.splitlines())), 32)
        self.assertLessEqual(len(text.splitlines()), 14)
        self.assertIn('BRUTAL OP25', text)
        self.assertIn('Built on boatbod/op25', text)
        self.assertIn(SKULL, text)
        self.assertEqual(len(SKULL.splitlines()), 11)

    def test_ascii_fallback_and_override(self):
        self.assertTrue(banner(80, False, False).isascii())
        with patch.dict('os.environ', {'BRUTAL_ASCII': '1'}):
            self.assertTrue(banner(80, False).isascii())
        with patch('terminal_art.sys.stdout') as output:
            output.encoding = 'ascii'
            output.isatty.return_value = False
            self.assertTrue(banner(80, False).isascii())

    def test_narrow_terminal_has_no_overflow(self):
        for width in (1, 12, 24, 31, 32, 40, 80):
            with self.subTest(width=width):
                self.assertTrue(all(len(line) <= width for line in banner(width, False).splitlines()))
        self.assertNotIn('.------------.', banner(24, False))

    def test_color_is_optional_and_always_reset(self):
        self.assertNotIn('\033', banner(80, False))
        self.assertTrue(banner(80, True).endswith('\033[0m'))
        with patch('terminal_art.sys.stdout.isatty', return_value=True), \
                patch.dict('os.environ', {'NO_COLOR': ''}):
            self.assertNotIn('\033', banner(80))

    def test_exact_accent_color(self):
        self.assertEqual(paint('Menu', True), '\033[38;2;76;144;240mMenu\033[0m')
        self.assertTrue(banner(80, True).startswith('\033[38;2;76;144;240m'))

    def test_terminal_styles_output_prompts_and_secret_prompts(self):
        from brutal_cli import Terminal
        import tempfile
        with tempfile.TemporaryDirectory() as root, \
                patch('terminal_art.sys.stdout.isatty', return_value=True), \
                patch.dict('os.environ', {'TERM': 'xterm-256color'}, clear=True):
            output, prompt, secret = [], [], []
            terminal = Terminal(root, lambda s: prompt.append(s), output.append,
                                lambda s: secret.append(s))
            terminal.output('Ready')
            terminal.prompt('Choose: ')
            terminal.secret('Password: ')
            for text in output + prompt + secret:
                self.assertTrue(text.startswith('\033[38;2;76;144;240m'))
                self.assertTrue(text.endswith('\033[0m'))


if __name__ == '__main__':
    unittest.main()
