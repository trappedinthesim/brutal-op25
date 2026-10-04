import os
import sys
import unittest
from terminal_menu import MenuState, clean, read_key, menu_layout
from unittest.mock import patch
from brutal_cli import choose


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.items = [{'name': 'Afghanistan'}, {'name': 'United States'}, {'name': 'Zimbabwe'}]

    def test_default_country_and_scroll_limits(self):
        state = MenuState(self.items, lambda c: c['name'], 1)
        self.assertEqual(state.selected()['name'], 'United States')
        state.move(1)
        self.assertEqual(state.selected()['name'], 'Zimbabwe')
        state.move(100)
        self.assertEqual(state.cursor, 2)
        state.move(-100)
        self.assertEqual(state.cursor, 0)

    def test_search_filters_and_recovers(self):
        state = MenuState(self.items, lambda c: c['name'])
        state.filter('UNITED')
        self.assertEqual(state.selected()['name'], 'United States')
        state.filter('nothing')
        self.assertIsNone(state.selected())
        state.filter('')
        self.assertEqual(len(state.matches), 3)

    def test_fallback_enter_accepts_default(self):
        chosen = choose('Country', self.items, lambda c: c['name'], lambda _: '', lambda _: None, 1)
        self.assertEqual(chosen['name'], 'United States')

    def test_labels_cannot_inject_terminal_controls(self):
        self.assertNotIn('\033', clean('Name\033[2J'))
        self.assertNotIn('\n', clean('Name\nNext'))

    def test_compact_brand_stays_above_scrolling_choices(self):
        state = MenuState(list(range(50)), str)
        with patch.dict(os.environ, {'TERM': 'xterm', 'BRUTAL_ASCII': '0'}), \
                patch('terminal_art.sys.stdout') as output:
            output.encoding = 'utf-8'
            lines, rows = menu_layout(state, 'Country', 80, 24)
            self.assertEqual(lines[0], 'BRUTAL OP25 // TERMINAL SETUP')
            self.assertIn('Built on boatbod/op25', lines)
            self.assertIn('> 0', lines)
            state.move(rows)
            moved, _ = menu_layout(state, 'Country', 80, 24)
            self.assertEqual(lines[:6], moved[:6])
            self.assertIn('> ' + str(rows), moved)
            self.assertLessEqual(len(moved), 23)

    def test_small_windows_keep_selection_without_overflow(self):
        state = MenuState(['Example'], str)
        for width, height in ((80, 24), (40, 20), (20, 12), (10, 4), (80, 2)):
            lines, _ = menu_layout(state, 'Receiver site', width, height)
            self.assertLessEqual(len(lines), max(2, height-1))
            self.assertTrue(all(len(line) <= width-1 for line in lines))
            self.assertTrue(any(line.startswith('> ') for line in lines))

    def test_empty_search_keeps_header_and_hint(self):
        state = MenuState(['Example'], str)
        state.filter('not here')
        lines, _ = menu_layout(state, 'Country', 80, 24)
        self.assertIn('BRUTAL OP25 // TERMINAL SETUP', lines)
        self.assertEqual(lines[-1], '0 of 0')
        self.assertTrue(any(line.startswith('No matches') for line in lines))

    def test_radio_failure_stays_visible_with_choices(self):
        state = MenuState(['Check again', 'Continue without listening', 'Exit'], str)
        reason = 'USB device not passed into this container. This session has no Windows-helper connection.'
        lines, _ = menu_layout(state, 'Your radio is not ready yet', 80, 24, [reason])
        self.assertIn('USB device not passed', '\n'.join(lines))
        self.assertIn('Windows-helper', '\n'.join(lines))
        self.assertIn('> Check again', lines)
        self.assertLessEqual(len(lines), 23)
        state.move(1)
        moved, _ = menu_layout(state, 'Your radio is not ready yet', 80, 24, [reason])
        self.assertIn('USB device not passed', '\n'.join(moved))

    @unittest.skipUnless(sys.platform == 'linux', 'POSIX keyboard descriptor regression')
    def test_arrow_page_and_unicode_reads(self):
        for key in ('\033[A', '\033[B', '\033[5~', '\033[6~', 'é', '\r'):
            read, write = os.pipe()
            try:
                os.write(write, key.encode('utf-8'))
                with os.fdopen(read, 'rb', buffering=0) as stream:
                    self.assertEqual(read_key(stream), key)
                read = None
            finally:
                if read is not None:
                    os.close(read)
                os.close(write)


if __name__ == '__main__':
    unittest.main()
