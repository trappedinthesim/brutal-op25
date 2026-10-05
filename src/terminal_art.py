"""Compact ASCII branding for terminal setup."""
import os
import shutil
import sys
import textwrap

ACCENT_BLUE = '\033[38;2;76;144;240m'  # #4C90F0, shared with the dashboard.
RESET = '\033[0m'

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
    else:
        lines = TOWER.splitlines() + heading
    wrapped = [part for line in lines for part in
               (textwrap.wrap(line, width=width, replace_whitespace=False,
                              drop_whitespace=False) or [''])]
    return paint('\n'.join(wrapped), color)
