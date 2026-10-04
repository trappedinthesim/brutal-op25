"""Compact, static Unicode branding with an ASCII fallback."""
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

# User-provided design, preserved exactly. Braille cells have single-column width.
SKULL = """⠀⠀⠀⠀⢀⣀⣤⣤⣤⣤⣄⡀⠀⠀⠀⠀
⠀⢀⣤⣾⣿⣾⣿⣿⣿⣿⣿⣿⣷⣄⠀⠀
⢠⣾⣿⢛⣼⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⡀
⣾⣯⣷⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣧
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⡿⠻⢿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠻⢿⡵
⢸⡇⠀⠀⠉⠛⠛⣿⣿⠛⠛⠉⠀⠀⣿⡇
⢸⣿⣀⠀⢀⣠⣴⡇⠹⣦⣄⡀⠀⣠⣿⡇
⠈⠻⠿⠿⣟⣿⣿⣦⣤⣼⣿⣿⠿⠿⠟⠀
⠀⠀⠀⠀⠸⡿⣿⣿⢿⡿⢿⠇⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠈⠁⠈⠁⠀⠀⠀⠀⠀⠀"""

ASCII_SKULL = r"""         .------------.
       .' .  .  .  .  .'.
      / .  .  .  .  .  . \
     | . .BRUTAL  BRUTAL. |
     |   :BRUTAL  BRUTAL: |
     | .  '---' /\ '---' .|
      \ . .   /BR\  . . /
       | .  BRUTAL  . |
       |BR .  --  . AL|
       |. |B|R|U|T| .|
        \ '--------' /
         'BRUTALOP25'"""


def banner(width=None, color=None, unicode=None):
    width = max(1, width if width is not None else shutil.get_terminal_size((80, 24)).columns)
    if color is None:
        color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    if unicode is None:
        unicode = os.environ.get('BRUTAL_ASCII') != '1' and os.environ.get('TERM') != 'dumb'
        try:
            SKULL.encode(sys.stdout.encoding or 'ascii')
        except (UnicodeEncodeError, LookupError):
            unicode = False
    skull = (SKULL if unicode else ASCII_SKULL).splitlines() if width >= 32 else []
    # Keep a stable left alignment. Never emit a row wider than the terminal.
    text = '\n'.join(skull + ['BRUTAL OP25 // TERMINAL SETUP', 'Built on boatbod/op25'])
    lines = []
    for line in text.splitlines():
        lines.extend(textwrap.wrap(line, width=width, replace_whitespace=False,
                                   drop_whitespace=False) or [''])
    result = '\n'.join(lines)
    return paint(result, color)
