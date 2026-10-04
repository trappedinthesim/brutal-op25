"""Compact, static ASCII branding for the terminal setup."""
import os
import shutil
import sys
import textwrap

ACCENT_BLUE = '\033[38;2;76;144;240m'  # Exact #4C90F0 on true-color terminals; matches the dashboard accent.
RESET = '\033[0m'


def paint(text, color=None):
    if color is None:
        color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    return ACCENT_BLUE + str(text) + RESET if color else str(text)


# Terminal-sized rendition of the user-supplied satellite dish art.
DISH = r"""            .      *
        .:-=+*###*.
     .-+#@@@@@@@@@#.
   .-+%@@@@@@@@@@@#'
  /#@@@@@@@@@@#-'       o ))
 /#@@@@@@#-'-----------'
/#@@@#-'
`----'-----\
           \\
            ||
           [__]"""


def banner(width=None, color=None, unicode=None):
    width = max(1, width if width is not None else shutil.get_terminal_size((80, 24)).columns)
    if color is None:
        color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    # unicode is retained for callers of the previous banner API; this art is ASCII everywhere.
    dish = DISH.splitlines() if width >= max(map(len, DISH.splitlines())) else []
    # Keep a stable left alignment. Never emit a row wider than the terminal.
    text = '\n'.join(dish + ['BRUTAL OP25 // TERMINAL SETUP', 'Built on boatbod/op25'])
    lines = []
    for line in text.splitlines():
        lines.extend(textwrap.wrap(line, width=width, replace_whitespace=False,
                                   drop_whitespace=False) or [''])
    result = '\n'.join(lines)
    return paint(result, color)
