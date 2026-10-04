"""Bounded receiver diagnostic; uses an explicit existing config, never edits it."""
import argparse
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--seconds', type=int, default=40)
    parser.add_argument('--control-first', type=int)
    parser.add_argument('--small-usb-buffers', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error('Diagnostic duration must be 1-60 seconds')
    config = json.loads(Path(args.config).read_text())
    if args.small_usb_buffers:
        config['devices'][0]['args'] += ',buffers=4,buflen=16384'
    if args.control_first:
        for trunk in config['trunking']['chans']:
            channels = trunk['control_channel_list'].split(',')
            first = next((f for f in channels if round(float(f)*1000000) == args.control_first), None)
            if first is None:
                parser.error('Frequency must be in the imported control-channel list')
            trunk['control_channel_list'] = ','.join([first] + [f for f in channels if f != first])
        config['devices'][0]['frequency'] = args.control_first
        config['channels'][0]['frequency'] = args.control_first
    runtime = Path('/tmp/receiver-diagnostic')
    source = Path('/opt/op25/op25/gr-op25_repeater/apps')
    shutil.copytree(source, runtime / 'apps', dirs_exist_ok=True)
    shutil.copytree(source.parent / 'www', runtime / 'www', dirs_exist_ok=True)
    path = runtime / 'config.json'
    path.write_text(json.dumps(config))
    process = subprocess.Popen([sys.executable, '-u', str(runtime / 'apps/multi_rx.py'),
        '-c', str(path), '-v', '10'], cwd=runtime / 'apps', stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + args.seconds
    buffer = b''
    usb_errors = 0
    network_messages = 0
    missing_ids = 0
    try:
        while process.poll() is None and time.monotonic() < deadline:
            if not select.select([process.stdout], [], [], .2)[0]:
                continue
            data = os.read(process.stdout.fileno(), 65536)
            if not data:
                break
            buffer += data
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                text = line.decode(errors='replace')
                if 'rtlsdr_demod_write_reg failed' in text or 'r82xx_write: i2c wr failed' in text:
                    usb_errors += 1
                if 'net_sts_bcst' in text:
                    network_messages += 1
                if 'wacn/sysid not yet known' in text:
                    missing_ids += 1
                # Do not persist/echo raw voice-codeword payloads.
                markers = ('failed', 'error:', 'net_sts_bcst', 'rfss_sts_bcst', 'set control channel',
                    'control channel timeout', 'cannot tune voice', 'voice update', 'tuning to',
                    'DIAGNOSTIC', 'exception', 'Using device', 'Blog V4 Detected', 'iden_up', 'Starting OP25')
                if any(marker in text for marker in markers) and 'IMBE (' not in text and 'AMBE (' not in text:
                    print(text, flush=True)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        print('DIAGNOSTIC COMPLETE: USB register errors=%d; network status messages=%d; missing system-ID warnings=%d; exit=%s' % (usb_errors, network_messages, missing_ids, process.returncode))


if __name__ == '__main__':
    main()
