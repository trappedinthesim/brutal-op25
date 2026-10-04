"""Supervise SDRplay's API and OP25 in the same private receiver container."""
import ctypes
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from container_receiver import active_config


def selected_arguments(serial):
    if not re.fullmatch(r'[A-Za-z0-9]+', serial):
        raise ValueError('A validated RSP serial number is required')
    return 'soapy=0,driver=sdrplay,serial=' + serial


def wait_for_api(service, api, shared_memory=Path('/dev/shm/Glbl\\sdrSrvComShMem'), timeout=10):
    """Wait for the vendor service's shared memory before probing its API.

    Calling sdrplay_api_Open immediately after spawning the service prints a
    misleading one-time `shm_open: No such file or directory` on a cold start.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service.poll() is not None:
            raise RuntimeError('SDRplay API service exited; check USB permissions and container logs')
        if shared_memory.exists() and api.sdrplay_api_Open() == 0:
            try:
                version = ctypes.c_float()
                if api.sdrplay_api_ApiVersion(ctypes.byref(version)) != 0 or version.value < 3.149:
                    raise RuntimeError('SDRplay API 3.15 is required for RSPdx-R2')
            finally:
                api.sdrplay_api_Close()
            return
        time.sleep(0.25)
    raise RuntimeError('SDRplay API service did not become ready')


def stop_receiver_then_service(receiver, service):
    """Keep the vendor API alive until OP25 has released its Soapy device."""
    for process in (receiver, service):
        if process is None:
            continue
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    root = os.environ.get('OP25_DATA_DIR', '/data')
    config = json.loads(active_config(root).read_text())
    serial = os.environ.get('OP25_RSP_SERIAL', '')
    arguments = selected_arguments(serial)
    if len(config['devices']) != 1 or 'driver=sdrplay' not in config['devices'][0]['args']:
        raise ValueError('Select an RSPdx-R2 saved profile, not an RTL-SDR export')
    service = subprocess.Popen(['/opt/sdrplay_api/sdrplay_apiService'], stdin=subprocess.DEVNULL)
    receiver = None
    cancelled = False
    def terminate(*_):
        nonlocal cancelled
        cancelled = True
        # OP25 must release the RSP before the vendor API service stops.
        if receiver and receiver.poll() is None:
            receiver.terminate()
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        api = ctypes.CDLL('libsdrplay_api.so.3')
        wait_for_api(service, api)
        if cancelled:
            return 130
        found = subprocess.run(['SoapySDRUtil', '--find=driver=sdrplay,serial=' + serial],
                               capture_output=True, text=True, timeout=20)
        if cancelled:
            return 130
        output = found.stdout + found.stderr
        if found.returncode or 'RSPdx-R2' not in output or serial not in output:
            raise RuntimeError('The selected RSPdx-R2 is not visible to SoapySDR; check USB forwarding')
        config['devices'][0]['args'] = arguments
        temporary = Path('/tmp/rsp-config.json')
        temporary.write_text(json.dumps(config))
        print('RSPdx-R2 identified; starting OP25. Signal lock and audio still need validation.', flush=True)
        receiver = subprocess.Popen([sys.executable, 'container_receiver.py', 'run'],
            env={**os.environ, 'OP25_PREPARED_CONFIG': str(temporary)})
        while receiver.poll() is None:
            if service.poll() is not None:
                raise RuntimeError('SDRplay API service stopped while receiving')
            time.sleep(0.25)
        return 130 if cancelled else receiver.returncode
    finally:
        stop_receiver_then_service(receiver, service)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        sys.exit('RSPdx-R2 receiver: ' + str(exc))
