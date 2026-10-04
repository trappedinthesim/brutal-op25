"""Read-only receiver-side discovery. Never infers the host from the browser."""
import os
from pathlib import Path
import stat
import sys

USB_MODELS = {
    ('1df7', '3060'): ('SDRplay RSPdx-R2', ['rspdxr2']),
    ('0bda', '2832'): ('RTL2832 family (exact model unverified)', ['rtl', 'rtlv4']),
    ('0bda', '2838'): ('RTL2838 family (exact model unverified)', ['rtl', 'rtlv4']),
}


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ''


def environment(root=Path('/'), platform=None, host_hint=None):
    root = Path(root)
    platform = platform or sys.platform
    hint = os.environ.get('OP25_HOST_PLATFORM', 'auto') if host_hint is None else host_hint
    if hint not in ('auto', 'linux', 'windows-wsl'):
        raise ValueError('OP25_HOST_PLATFORM must be auto, linux, or windows-wsl')
    container = (root / '.dockerenv').exists() or (root / 'run/.containerenv').exists()
    kernel = read(root / 'proc/sys/kernel/osrelease').lower()
    wsl = platform == 'linux' and (hint == 'windows-wsl' or
                                  (hint == 'auto' and ('microsoft' in kernel or 'wsl' in kernel)))
    kind = ('windows_host' if platform == 'win32' else
            'wsl_container' if wsl and container else
            'wsl' if wsl else 'linux_container' if platform == 'linux' and container else
            'linux_native' if platform == 'linux' else 'unsupported')
    labels = {'windows_host': 'Windows host', 'wsl_container': 'Linux container on WSL',
              'wsl': 'Linux on WSL', 'linux_container': 'Linux container (outer host unconfirmed)',
              'linux_native': 'Native Linux', 'unsupported': 'Unsupported receiver environment'}
    return {'kind': kind, 'label': labels[kind], 'container': container, 'wsl': wsl,
            'linux_receiver': platform == 'linux', 'host_hint': hint,
            'note': 'Detected on the receiver, not from the browser. An opaque container kernel '
                    'may require an explicit OP25_HOST_PLATFORM deployment setting.'}


def usb_inventory(root=Path('/'), access=os.access):
    root = Path(root)
    devices = []
    sysfs = root / 'sys/bus/usb/devices'
    for device in sorted(sysfs.glob('*')):
        identity = (read(device / 'idVendor').lower(), read(device / 'idProduct').lower())
        if identity not in USB_MODELS:
            continue
        bus, number = read(device / 'busnum'), read(device / 'devnum')
        if not bus.isdigit() or not number.isdigit():
            continue
        node = f'/dev/bus/usb/{int(bus):03d}/{int(number):03d}'
        path = root / node.lstrip('/')
        try:
            present = stat.S_ISCHR(path.stat().st_mode)
        except OSError:
            present = False
        name, profiles = USB_MODELS[identity]
        devices.append({'node': node, 'name': name, 'compatible_profiles': profiles,
                        'serial': read(device / 'serial'),
                        'device_node_present': present,
                        'read_write_access': present and access(path, os.R_OK | os.W_OK)})
    return devices


def assess(env, devices, profile, software, selected_node=None):
    candidates = [d for d in devices if profile == 'custom' or profile in d['compatible_profiles']]
    selected = next((d for d in candidates if d['node'] == selected_node), None)
    blockers = []
    if not env['linux_receiver']:
        blockers.append('Run the receiver on Linux, directly or in a Linux container/WSL.')
    if not candidates:
        if env['wsl'] or env['kind'] == 'windows_host':
            blockers.append('Forward the selected USB radio from Windows to WSL. Start Brutal OP25 '
                            'through Launch-Brutal-OP25.cmd so its Windows USB setup handles this; '
                            'a bare docker run cannot prepare Windows USB. Approve Windows prompts '
                            'when asked; no USB commands need to be typed.')
        elif env['container']:
            blockers.append('Pass the selected USB device into this Linux container. If the outer '
                            'host is Windows, it must first be forwarded to WSL.')
        else:
            blockers.append('Connect the radio to this Linux receiver. Custom/other USB IDs need '
                            'a device-specific check; this list recognizes RTL-SDR and RSPdx-R2 only.')
    elif not any(d['device_node_present'] for d in candidates):
        blockers.append('Linux detects the radio, but its USB device node was not passed into this container. '
                        'The container must be started with the selected radio device.' if env['container']
                        else 'Linux detects the radio, but its USB device node is missing. Check USB device creation.')
    elif not selected:
        blockers.append('Select the visible radio to confirm which USB device to use.')
    elif not selected['device_node_present']:
        blockers.append('The radio appears in Linux USB information but its device node is not '
                        'available to this process. Check container device passthrough.' if env['container']
                        else 'The USB device node is unavailable. Check Linux device creation.')
    elif not selected['read_write_access']:
        blockers.append('Give the receiver user read/write access to this selected USB node using '
                        'a targeted udev/group rule. Do not run the web app as root.')
    missing = software.get('missing', [])
    if missing:
        blockers.append('Install receiver-side dependencies: ' + '; '.join(missing) + '.')
    return {'environment': env, 'devices': candidates, 'selected_device': selected,
            'prerequisites_ready': not blockers, 'blockers': blockers,
            'hardware_verified': False,
            'note': 'USB identity and permissions do not prove exclusive access, driver operation, '
                    'sample-rate/gain support, reception, or audio.'}
