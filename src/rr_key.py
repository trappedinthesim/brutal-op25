"""Load the release image's embedded RadioReference application key, if any."""
import ctypes
from pathlib import Path


LIBRARY = Path('/opt/manager/librrkey.so')


def embedded_key(path=LIBRARY):
    try:
        library = ctypes.CDLL(str(path))
        library.brutal_rr_app_key.restype = ctypes.c_char_p
        value = library.brutal_rr_app_key()
        return value.decode('utf-8').strip() if value else ''
    except (OSError, AttributeError, UnicodeError):
        return ''
