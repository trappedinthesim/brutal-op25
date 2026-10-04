"""Portable saved-system backup/restore and hostile archive boundaries."""
import json
import fcntl
from pathlib import Path
import tempfile
import unittest
import zipfile

from profile_transfer import export_profiles, restore_profiles


PROFILE_ID = 'a' * 32


def profile(name='Test P25'):
    return {'id': PROFILE_ID, 'revision': 1, 'name': name,
            'settings': {'hardware': {'profile': 'rtlv4'}, 'site_id': 1},
            'system': {'name': name, 'sites': [], 'talkgroups': []}}


class ProfileTransferTests(unittest.TestCase):
    def test_round_trip_does_not_include_receiver_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            saved = source / 'saved-profiles'
            saved.mkdir(parents=True)
            (saved / (PROFILE_ID + '.json')).write_text(json.dumps(profile()))
            (source / 'receiver').mkdir()
            (source / 'receiver/active.json').write_text('private receiver cache')
            backup = root / 'backup.zip'
            self.assertEqual(export_profiles(source, backup), 1)
            with zipfile.ZipFile(backup) as archive:
                self.assertEqual(set(archive.namelist()),
                                 {'manifest.json', 'profiles/' + PROFILE_ID + '.json'})
            target = root / 'target'
            self.assertEqual(restore_profiles(target, backup), 1)
            self.assertEqual(restore_profiles(target, backup), 0)
            self.assertEqual(json.loads((target / 'saved-profiles' / (PROFILE_ID + '.json')).read_text()),
                             profile())
            self.assertFalse((target / 'receiver').exists())

    def test_conflicting_profile_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source/saved-profiles'
            source.mkdir(parents=True)
            (source / (PROFILE_ID + '.json')).write_text(json.dumps(profile()))
            backup = root / 'backup.zip'
            export_profiles(root / 'source', backup)
            target = root / 'target/saved-profiles'
            target.mkdir(parents=True)
            (target / (PROFILE_ID + '.json')).write_text(json.dumps(profile('Different')))
            with self.assertRaisesRegex(ValueError, 'different contents'):
                restore_profiles(root / 'target', backup)
            self.assertEqual(json.loads((target / (PROFILE_ID + '.json')).read_text())['name'],
                             'Different')

    def test_archive_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / 'bad.zip'
            with zipfile.ZipFile(backup, 'w') as archive:
                archive.writestr('manifest.json', json.dumps({'format': 1, 'count': 1}))
                archive.writestr('../escape.json', json.dumps(profile()))
            with self.assertRaisesRegex(ValueError, 'unexpected path'):
                restore_profiles(root / 'target', backup)
            self.assertFalse((root / 'escape.json').exists())

    def test_refuses_to_replace_existing_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved = root / 'saved-profiles'
            saved.mkdir()
            (saved / (PROFILE_ID + '.json')).write_text(json.dumps(profile()))
            backup = root / 'backup.zip'
            backup.write_text('keep')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                export_profiles(root, backup)
            self.assertEqual(backup.read_text(), 'keep')

    def test_receiver_lock_blocks_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved = root / 'saved-profiles'
            saved.mkdir()
            (saved / (PROFILE_ID + '.json')).write_text(json.dumps(profile()))
            with (root / '.receiver-session.lock').open('a+') as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, 'Stop the receiver'):
                    export_profiles(root, root / 'backup.zip')


if __name__ == '__main__':
    unittest.main()
