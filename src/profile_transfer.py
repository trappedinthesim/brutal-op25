"""Portable, credential-free saved-system backup; never exports receiver caches."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import zipfile

from library import ProfileLibrary


PROFILE_NAME = re.compile(r"profiles/([0-9a-f]{32})\.json\Z")
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_PROFILES = 1000


def _lock(root):
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / '.receiver-session.lock').open('a+')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise ValueError('Stop the receiver before backing up or restoring saved systems.') from None
    return handle


def export_profiles(root, destination):
    root, destination = Path(root), Path(destination)
    with _lock(root):
        library = ProfileLibrary(root / 'saved-profiles')
        profiles = library.list()
        if library.unreadable:
            raise ValueError('A damaged saved-system file must be repaired before backup.')
        if not profiles:
            raise ValueError('No saved systems to back up.')
        if len(profiles) > MAX_PROFILES:
            raise ValueError('Too many saved systems for one backup.')
        if destination.exists():
            raise ValueError('Backup file already exists; choose a new name.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + '.partial')
        if temporary.exists():
            raise ValueError('An unfinished backup with this name already exists.')
        try:
            with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps({'format': 1, 'count': len(profiles)}))
                for profile in profiles:
                    archive.writestr('profiles/' + profile['id'] + '.json',
                                     json.dumps(profile, ensure_ascii=False))
            if temporary.stat().st_size > MAX_ARCHIVE_BYTES:
                raise ValueError('Backup exceeds the 50 MiB safety limit.')
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return len(profiles)


def restore_profiles(root, source):
    root, source = Path(root), Path(source)
    if not source.is_file() or source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('Backup is missing or exceeds the 50 MiB safety limit.')
    with _lock(root), zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or 'manifest.json' not in names:
            raise ValueError('Invalid backup manifest or duplicate files.')
        if len(entries) > MAX_PROFILES + 1 or sum(e.file_size for e in entries) > MAX_ARCHIVE_BYTES:
            raise ValueError('Backup has too many or oversized records.')
        if any(name != 'manifest.json' and not PROFILE_NAME.fullmatch(name) for name in names):
            raise ValueError('Backup contains an unexpected path.')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest != {'format': 1, 'count': len(entries) - 1}:
            raise ValueError('Backup manifest does not match its records.')
        profiles = []
        for name in names:
            if name == 'manifest.json':
                continue
            identity = PROFILE_NAME.fullmatch(name).group(1)
            profile = ProfileLibrary.validate(json.loads(archive.read(name)), identity)
            profiles.append(profile)
        library = ProfileLibrary(root / 'saved-profiles')
        root_owner = root.stat()
        for profile in profiles:
            target = library.path(profile['id'])
            if target.exists() and library.read(profile['id']) != profile:
                raise ValueError('A saved system with the same ID has different contents; nothing restored.')
        added = 0
        for profile in profiles:
            if not library.path(profile['id']).exists():
                library.write(profile)
                os.chown(library.path(profile['id']), root_owner.st_uid, root_owner.st_gid)
                added += 1
        if added:
            os.chown(library.root, root_owner.st_uid, root_owner.st_gid)
        return added


def main():
    parser = argparse.ArgumentParser(description='Back up or restore saved Brutal OP25 systems')
    parser.add_argument('action', choices=('export', 'restore'))
    parser.add_argument('path')
    parser.add_argument('--data', default='/data')
    args = parser.parse_args()
    try:
        count = (export_profiles(args.data, args.path) if args.action == 'export'
                 else restore_profiles(args.data, args.path))
    except (ValueError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        parser.exit(1, f'Backup needs attention: {exc}\n')
    print(f'{args.action}: {count} saved system(s); receiver cache and credentials were not included.')


if __name__ == '__main__':
    main()
