"""Install only the pinned official package, after explicit user consent.

Used inside a local addon image build, never to accept a license on a user's behalf.
"""
import argparse
import hashlib
import io
from pathlib import Path
import tarfile

SHA256 = '3a97ca764263bbe76fb0f2220e6408942357e8864c19e1408a6d6987af382fe3'
PAYLOAD_SIZE = 498671


def inspect_package(path):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('SDRplay installer checksum mismatch; refusing this package')
    payload = data[len(data) - PAYLOAD_SIZE:]
    if not payload.startswith(b'\x1f\x8b'):
        raise ValueError('Invalid official package format')
    return tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz')


def install(path, consent, root='/'):
    if consent != 'yes':
        raise ValueError('The user must review and accept SDRplay-EULA.txt before installation')
    root = Path(root).resolve()
    with inspect_package(path) as package:
        def copy(member, destination, executable=False):
            info = package.getmember(member)
            if not info.isfile():
                raise ValueError('Unexpected installer member type')
            target = root / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.extractfile(info).read())
            target.chmod(0o755 if executable else 0o644)
        copy('./amd64/libsdrplay_api.so.3.15', 'usr/local/lib/libsdrplay_api.so.3.15')
        copy('./amd64/sdrplay_apiService', 'opt/sdrplay_api/sdrplay_apiService', True)
        copy('./sdrplay_license.txt', 'opt/sdrplay_api/sdrplay_license.txt')
        for member in package.getmembers():
            if member.isfile() and member.name.startswith('./inc/') and member.name.endswith('.h'):
                copy(member.name, 'usr/local/include/' + Path(member.name).name)
    library = root / 'usr/local/lib'
    for name, target in [('libsdrplay_api.so.3', 'libsdrplay_api.so.3.15'),
                         ('libsdrplay_api.so', 'libsdrplay_api.so.3')]:
        (library / name).symlink_to(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer')
    parser.add_argument('--consent', required=True, choices=['yes', 'no'])
    args = parser.parse_args()
    install(args.installer, args.consent)
