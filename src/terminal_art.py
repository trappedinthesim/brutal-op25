"""Compact ASCII branding for terminal setup."""
import os
import shutil
import sys
import textwrap

ACCENT_BLUE = '\033[38;2;76;144;240m'  # #4C90F0, shared with the dashboard.
RESET = '\033[0m'

WORDMARK = """░█▀▄░█▀▄░█░█░▀█▀░█▀█░█░░░░░█▀█░█▀█░▀▀▄░█▀▀
░█▀▄░█▀▄░█░█░░█░░█▀█░█░░░░░█░█░█▀▀░▄▀░░▀▀▄
░▀▀░░▀░▀░▀▀▀░░▀░░▀░▀░▀▀▀░░░▀▀▀░▀░░░▀▀▀░▀▀░"""

TOWER = r"""   /  /          \  \
  |  |            |  |
   \  \    /\    /  /
          /||\
         / || \
        /--||--\
       /   ||   \
      /----||----\
     /     ||     \
    /______||______\
""".rstrip('\n')


def paint(text, color=None):
    if color is None:
        color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    return ACCENT_BLUE + str(text) + RESET if color else str(text)


def banner(width=None, color=None, unicode=None, compact=False):
    """Show the tower at startup; scrolling menus keep only the wordmark."""
    width = max(1, width if width is not None else shutil.get_terminal_size((80, 24)).columns)
    heading = ['BRUTAL OP25 // TERMINAL SETUP', 'Built on boatbod/op25']
    if compact or width < 24:
        lines = heading
    elif width >= max(map(len, WORDMARK.splitlines())) + 2 and _supports_wordmark(unicode):
        logo_width = max(map(len, WORDMARK.splitlines()))
        tower_width = max(map(len, TOWER.splitlines()))
        tower_indent = ' ' * ((logo_width - tower_width) // 2)
        lines = (WORDMARK.splitlines() + [''] +
                 [tower_indent + line for line in TOWER.splitlines()] + [''] +
                 ['TERMINAL SETUP'.center(logo_width).rstrip(),
                  'BUILT ON BOATBOD / OP25'.center(logo_width).rstrip()])
    else:
        lines = TOWER.splitlines() + heading
    wrapped = [part for line in lines for part in
               (textwrap.wrap(line, width=width, replace_whitespace=False,
                              drop_whitespace=False) or [''])]
    return paint('\n'.join(wrapped), color)


def _supports_wordmark(unicode):
    if unicode is not None:
        return bool(unicode)
    try:
        WORDMARK.encode(sys.stdout.encoding or 'utf-8')
        return True
    except (UnicodeEncodeError, LookupError):
        return False
