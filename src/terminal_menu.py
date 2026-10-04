"""Keyboard-scrolling menus for Linux TTYs, with no extra dependencies."""
import os
import re
import select
import shutil
import sys
import textwrap
from terminal_art import banner, paint


class MenuCancelled(Exception):
    pass


def clean(text):
    return re.sub(r'[\x00-\x1f\x7f]', '', str(text))


class MenuState:
    def __init__(self, items, label, default_index=0):
        self.items = items
        self.labels = [clean(label(item)) for item in items]
        self.query = ''
        self.matches = list(range(len(items)))
        self.cursor = min(max(0, default_index), max(0, len(items)-1))

    def filter(self, query):
        self.query = query
        self.matches = [i for i, label in enumerate(self.labels) if query.casefold() in label.casefold()]
        self.cursor = 0

    def move(self, amount):
        self.cursor = min(max(0, self.cursor + amount), max(0, len(self.matches)-1))

    def selected(self):
        return self.items[self.matches[self.cursor]] if self.matches else None


def read_key(stream):
    # Read from the descriptor: TextIOWrapper buffering can otherwise hide
    # the rest of an arrow-key sequence from select().
    data = os.read(stream.fileno(), 1)
    if not data:
        raise MenuCancelled()
    first = data[0]
    length = 2 if 0xc0 <= first < 0xe0 else 3 if 0xe0 <= first < 0xf0 else 4 if first >= 0xf0 else 1
    while len(data) < length:
        piece = os.read(stream.fileno(), length-len(data))
        if not piece:
            break
        data += piece
    key = data.decode('utf-8', errors='replace')
    if key != '\033':
        return key
    if not select.select([stream], [], [], .08)[0]:
        return '\033'
    key += os.read(stream.fileno(), 1).decode('ascii', errors='replace')
    # CSI and SS3 sequences, including arrows, Home/End and Page Up/Down.
    if key[-1] in ('[', 'O'):
        while select.select([stream], [], [], .08)[0] and len(key) < 10:
            key += os.read(stream.fileno(), 1).decode('ascii', errors='replace')
            if key[-1].isalpha() or key[-1] == '~':
                break
    return key


def menu_layout(state, title, width, height, context=()):
    """Reserve a fixed branded header; only the choices page scrolls."""
    width, height = max(1, width - 1), max(2, height - 1)
    header = banner(width=width, color=False).splitlines()
    controls = [clean(title), 'Arrows: scroll | Enter: select | Esc: back',
                'Type to search | Backspace: edit | PgUp/PgDn: page',
                'Search: ' + clean(state.query)]
    details = [line for message in context for line in textwrap.wrap(clean(message), width=width)]
    controls[1:1] = details
    if len(header) + len(controls) + 2 > height:
        # Tiny windows cannot fit the full skull plus a usable selection.
        header = ['BRUTAL OP25'] if height >= 7 else []
    if len(header) + len(controls) + 2 > height:
        controls = ([clean(title)] + details)[:max(0,height-len(header)-2)]
    rows = max(1, height - len(header) - len(controls) - 1)
    start = (state.cursor // rows) * rows
    lines = header + controls
    for position in range(start, min(start + rows, len(state.matches))):
        index = state.matches[position]
        lines.append(('> ' if position == state.cursor else '  ') + state.labels[index])
    if not state.matches:
        lines.append('No matches. Backspace to change your search.')
    lines.append(f'{state.cursor+1 if state.matches else 0} of {len(state.matches)}')
    return [line[:width] for line in lines], rows


def scrolling_menu(title, items, label, default_index=0, context=()):
    import termios
    import tty
    if not items:
        raise ValueError('No entries available for ' + title)
    state = MenuState(items, label, default_index)
    stream, output = sys.stdin, sys.stdout
    previous = termios.tcgetattr(stream.fileno())
    try:
        tty.setcbreak(stream.fileno())
        output.write('\033[?1049h\033[?25l')
        while True:
            width, height = shutil.get_terminal_size((80, 24))
            lines, rows = menu_layout(state, title, width, height, context)
            output.write('\033[H\033[2J' + paint('\n'.join(lines)))
            output.flush()
            key = read_key(stream)
            if key in ('\r', '\n'):
                selected = state.selected()
                if selected is not None:
                    return selected
            elif key in ('\033', '\x04'):
                raise MenuCancelled()
            elif key == '\x03':
                raise KeyboardInterrupt()
            elif key in ('\033[A', '\033OA'):
                state.move(-1)
            elif key in ('\033[B', '\033OB'):
                state.move(1)
            elif key == '\033[5~':
                state.move(-rows)
            elif key == '\033[6~':
                state.move(rows)
            elif key in ('\033[H', '\033OH', '\033[1~'):
                state.cursor = 0
            elif key in ('\033[F', '\033OF', '\033[4~'):
                state.cursor = max(0, len(state.matches)-1)
            elif key in ('\x7f', '\b'):
                state.filter(state.query[:-1])
            elif len(key) == 1 and key.isprintable():
                state.filter(state.query + key)
    finally:
        termios.tcsetattr(stream.fileno(), termios.TCSADRAIN, previous)
        output.write('\033[?25h\033[?1049l')
        output.flush()


def can_scroll():
    return (sys.platform == 'linux' and sys.stdin.isatty() and sys.stdout.isatty() and
            os.environ.get('TERM') != 'dumb' and os.environ.get('BRUTAL_NUMBERED_MENUS') != '1')
