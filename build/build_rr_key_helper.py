"""Build the client key helper from a BuildKit secret."""
import argparse
from pathlib import Path
import secrets
import subprocess
import tempfile


def c_array(data):
    return ', '.join(f'0x{byte:02x}' for byte in data)


def build(key_file, output, required=False):
    source = Path(key_file)
    key = source.read_bytes().strip() if source.is_file() else b''
    if required and not key:
        raise ValueError('The release build requires the RadioReference application-key build secret.')
    if b'\x00' in key or b'\n' in key or b'\r' in key:
        raise ValueError('The application key must be a single line of text without NUL bytes.')
    try:
        key.decode('utf-8')
    except UnicodeError as exc:
        raise ValueError('The application key must be UTF-8 text.') from exc
    mask = secrets.token_bytes(len(key))
    masked = bytes(left ^ right for left, right in zip(key, mask))
    count = len(key)
    # Use one dummy byte for a source build with no embedded key.
    encoded_array = c_array(masked or b'\x00')
    mask_array = c_array(mask or b'\x00')
    program = f'''#include <stddef.h>
static const unsigned char encoded[] = {{{encoded_array}}};
static const unsigned char mask[] = {{{mask_array}}};
__attribute__((visibility("default")))
const char *brutal_rr_app_key(void) {{
    static unsigned char decoded[{count + 1}];
    static int ready = 0;
    if (!ready) {{
        for (size_t i = 0; i < {count}; ++i) decoded[i] = encoded[i] ^ mask[i];
        decoded[{count}] = 0;
        ready = 1;
    }}
    return (const char *)decoded;
}}
'''
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='brutal-rr-key-') as directory:
        c_file = Path(directory) / 'helper.c'
        c_file.write_text(program, encoding='ascii')
        subprocess.run(['cc', '-shared', '-fPIC', '-Os', '-fvisibility=hidden',
                        '-Wl,-s', '-o', str(destination), str(c_file)],
                       check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--key-file', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--required', action='store_true')
    args = parser.parse_args()
    build(args.key_file, args.output, args.required)
