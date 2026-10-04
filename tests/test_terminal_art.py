import os
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from terminal_art import (ACCENT_BLUE, IMAGE, RADIO_ART, banner,
                          da1_supports_sixels, paint, show_graphic_banner)


class TerminalArtTests(unittest.TestCase):
    def test_compact_blue_wordmark_and_ascii_fallback(self):
        self.assertEqual(ACCENT_BLUE, '\033[38;2;76;144;240m')
        self.assertTrue(RADIO_ART.isascii())
        self.assertLessEqual(max(map(len, RADIO_ART.splitlines())), 26)
        text = banner(80, False)
        self.assertTrue(text.isascii())
        self.assertIn('BRUTAL OP25 // TERMINAL SETUP', text)
        self.assertIn('Built on boatbod/op25', text)
        self.assertIn('%%=', text)
        self.assertLessEqual(len(text.splitlines()), 14)
        compact = banner(80, False, compact=True).splitlines()
        self.assertEqual(len(compact), 2)
        self.assertNotIn('%%=', '\n'.join(compact))

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

    def test_banner_png_is_valid_and_compact(self):
        data = IMAGE.read_bytes()
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        width, height = struct.unpack('>II', data[16:24])
        self.assertLessEqual(width, 480)
        self.assertLessEqual(height, 190)
        self.assertLess(len(data), 100_000)

    def test_terminal_capability_parser_checks_complete_parameter(self):
        self.assertTrue(da1_supports_sixels(b'\x1b[?62;4;22c'))
        self.assertFalse(da1_supports_sixels(b'\x1b[?62;44;22c'))
        self.assertFalse(da1_supports_sixels(b'garbage'))

    def test_image_is_not_sent_without_capability(self):
        with patch('terminal_art.sys.stdout.isatty', return_value=False), \
                patch('terminal_art.subprocess.run') as run:
            self.assertFalse(show_graphic_banner())
            run.assert_not_called()

    def test_image_is_sent_for_capable_terminal(self):
        output = Mock()
        output.isatty.return_value = True
        output.buffer = Mock()
        with patch('terminal_art.sys.stdout', output), \
                patch('terminal_art.shutil.get_terminal_size', return_value=os.terminal_size((80, 24))), \
                patch('terminal_art.shutil.which', return_value='/usr/bin/chafa'), \
                patch('terminal_art._graphics_protocol', return_value='sixels'), \
                patch('terminal_art.subprocess.run', return_value=Mock(returncode=0)) as run, \
                patch.dict(os.environ, {'TERM': 'xterm-256color'}, clear=True):
            self.assertTrue(show_graphic_banner())
            self.assertEqual(run.call_args.args[0][:5],
                             ['chafa', '--format', 'sixels', '--size', '46x12'])
            self.assertIs(run.call_args.kwargs['stdout'], output.buffer)
            output.write.assert_called_with('\n')

    def test_image_failure_falls_back_to_text(self):
        output = Mock()
        output.isatty.return_value = True
        output.buffer = Mock()
        with patch('terminal_art.sys.stdout', output), \
                patch('terminal_art.shutil.get_terminal_size', return_value=os.terminal_size((80, 24))), \
                patch('terminal_art.shutil.which', return_value='/usr/bin/chafa'), \
                patch('terminal_art._graphics_protocol', return_value='kitty'), \
                patch('terminal_art.subprocess.run', return_value=Mock(returncode=1)), \
                patch.dict(os.environ, {'TERM': 'xterm-kitty'}, clear=True):
            self.assertFalse(show_graphic_banner())

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
