"""Compact terminal branding with a real-image splash and safe text fallback."""
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import textwrap
import time

ACCENT_BLUE = '\033[38;2;76;144;240m'  # #4C90F0, shared with the dashboard.
RESET = '\033[0m'
IMAGE = Path(__file__).with_name('terminal-banner.png')

# A compact crop of the user's handheld-radio art for terminals without image support.
RADIO_ART = """                #%-
                %%=
                %%=
          =%%= #%%%.
  +%%%%% -%%%%-#%%%.
.#%%%%%%%%%#%%%#%%%%%%#.
.%%..======-======+..%%.
:%%..%=-----------#..%%:
-%%..%*+++++++++++#..%%-
.%%.::::::::::::::::.%%.
 +%.#              #.%*.
 -%..#%%* +%%+ *%%#..%-
 -%. :--: .::: :--: .%-
 .+%################%+"""


def paint(text, color=None):
    if color is None:
        color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    return ACCENT_BLUE + str(text) + RESET if color else str(text)


def banner(width=None, color=None, unicode=None, compact=False):
    """Text fallback. Scrolling menus keep only the wordmark to save rows."""
    width = max(1, width if width is not None else shutil.get_terminal_size((80, 24)).columns)
    heading = ['BRUTAL OP25 // TERMINAL SETUP', 'Built on boatbod/op25']
    if compact or width < 24:
        lines = heading
    elif width >= 56:
        lines = [f'{line:<24}   {heading[i]}' if i < len(heading) else line
                 for i, line in enumerate(RADIO_ART.splitlines())]
    else:
        lines = RADIO_ART.splitlines() + heading
    wrapped = [part for line in lines for part in
               (textwrap.wrap(line, width=width, replace_whitespace=False,
                              drop_whitespace=False) or [''])]
    return paint('\n'.join(wrapped), color)


def da1_supports_sixels(response):
    """DA1 parameter 4 advertises Sixel support; unrelated parameters are ignored."""
    match = re.search(rb'\x1b\[\?([0-9;]+)c', response)
    return bool(match and b'4' in match.group(1).split(b';'))


def _probe_sixels(timeout=0.3):
    """Ask the attached terminal, without assuming WSL or a particular Linux emulator."""
    if sys.platform != 'linux' or not sys.stdin.isatty():
        return False
    import termios
    import tty

    fd = sys.stdin.fileno()
    try:
        previous = termios.tcgetattr(fd)
    except (OSError, termios.error):
        return False
    response = bytearray()
    try:
        tty.setcbreak(fd)
        sys.stdout.write('\033[c')
        sys.stdout.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and len(response) < 256:
            ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            chunk = os.read(fd, 256 - len(response))
            if not chunk:
                break
            response.extend(chunk)
            if da1_supports_sixels(response) or b'c' in chunk:
                break
    except (OSError, ValueError):
        return False
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)
        except (OSError, termios.error):
            pass
    return da1_supports_sixels(response)


def _graphics_protocol():
    term = os.environ.get('TERM', '')
    if term.startswith('xterm-kitty') or os.environ.get('KITTY_WINDOW_ID'):
        return 'kitty'
    return 'sixels' if _probe_sixels() else None


def show_graphic_banner():
    """Display the image only when the attached terminal confirms a pixel protocol."""
    if (not sys.stdout.isatty() or 'NO_COLOR' in os.environ or
            os.environ.get('BRUTAL_ASCII') == '1' or os.environ.get('TERM') == 'dumb' or
            shutil.get_terminal_size((80, 24)).columns < 50 or
            shutil.get_terminal_size((80, 24)).lines < 18 or
            not IMAGE.is_file() or not shutil.which('chafa')):
        return False
    protocol = _graphics_protocol()
    if protocol is None:
        return False
    try:
        result = subprocess.run(
            ['chafa', '--format', protocol, '--size', '46x12', str(IMAGE)],
            stdout=sys.stdout.buffer, stderr=subprocess.DEVNULL,
            timeout=4, check=False)
        if result.returncode != 0:
            return False
        sys.stdout.write('\n')
        sys.stdout.flush()
        return True
    except (OSError, subprocess.TimeoutExpired, AttributeError):
        return False
