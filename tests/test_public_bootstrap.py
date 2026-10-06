"""Git-free Linux bootstrap must preserve a working install on failed update."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
RELEASE = b'ghcr.io/trappedinthesim/brutal-op25-receiver:0.3.0-dev.24\n'


def archive(path, prepare_status=0, launch_status=0):
    files = {
        'Launch-Brutal-OP25.cmd': b'@echo off\n',
        'install-brutal-op25.sh': (
            '#!/bin/sh\n'
            'case "${1:-}" in\n'
            f'  --prepare-only|--update-image) exit {prepare_status};;\n'
            'esac\n'
            f'exit {launch_status}\n').encode(),
        'install/image-bootstrap.sh': b'# fixture\n',
        'build/image-release.txt': RELEASE,
    }
    with tarfile.open(path, 'w:gz') as tar:
        for filename, content in files.items():
            info = tarfile.TarInfo('brutal-op25-main/' + filename)
            info.size = len(content)
            info.mode = 0o755 if filename.endswith('.sh') else 0o644
            tar.addfile(info, io.BytesIO(content))


@unittest.skipUnless(os.name != 'nt', 'Bash bootstrap test')
class PublicBootstrapTests(unittest.TestCase):
    def test_install_and_update_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'Radio Apps' / 'Brutal OP25'
            fixture = root / 'source.tar.gz'
            archive(fixture)
            args = ['bash', str(ROOT / 'bootstrap/install-brutal-op25.sh'),
                    '--no-launch', '--install-path', str(destination), '--archive', str(fixture)]
            for extra in ([], ['--update']):
                result = subprocess.run(args + extra, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((destination / '.brutal-op25-install').read_text().strip(),
                             str(destination))

    def test_receiver_launch_error_does_not_undo_successful_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'BrutalOP25'
            fixture = root / 'source.tar.gz'
            archive(fixture, launch_status=7)
            result = subprocess.run([
                'bash', str(ROOT / 'bootstrap/install-brutal-op25.sh'),
                '--install-path', str(destination), '--archive', str(fixture),
            ], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((destination / '.brutal-op25-install').exists())
            self.assertFalse(list(root.glob('BrutalOP25.incomplete.*')))

    def test_failed_first_install_can_retry_the_same_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'BrutalOP25'
            bad = root / 'bad.tar.gz'
            good = root / 'good.tar.gz'
            archive(bad, prepare_status=7)
            archive(good)
            script = ROOT / 'bootstrap/install-brutal-op25.sh'
            args = ['bash', str(script), '--no-launch', '--install-path', str(destination)]
            failed = subprocess.run(args + ['--archive', str(bad)], capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(destination.exists())
            self.assertEqual(len(list(root.glob('BrutalOP25.incomplete.*'))), 1)
            retried = subprocess.run(args + ['--archive', str(good)], capture_output=True, text=True)
            self.assertEqual(retried.returncode, 0, retried.stderr)
            self.assertTrue((destination / 'install-brutal-op25.sh').exists())

    def test_update_refuses_an_unrelated_existing_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'OtherProject'
            destination.mkdir()
            (destination / 'notes.txt').write_text('Keep this')
            fixture = root / 'source.tar.gz'
            archive(fixture)
            result = subprocess.run([
                'bash', str(ROOT / 'bootstrap/install-brutal-op25.sh'), '--no-launch',
                '--update', '--install-path', str(destination), '--archive', str(fixture),
            ], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((destination / 'notes.txt').read_text(), 'Keep this')
            self.assertFalse(list(root.glob('OtherProject.previous.*')))

    def test_install_then_failed_update_restores_previous_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'BrutalOP25'
            first = root / 'first.tar.gz'
            bad = root / 'bad.tar.gz'
            archive(first)
            archive(bad, prepare_status=7)
            script = ROOT / 'bootstrap/install-brutal-op25.sh'
            args = ['bash', str(script), '--no-launch', '--install-path', str(destination)]
            result = subprocess.run(args + ['--archive', str(first)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((destination / 'install-brutal-op25.sh').exists())
            first_content = (destination / 'install-brutal-op25.sh').read_text()
            result = subprocess.run(args + ['--update', '--archive', str(bad)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((destination / 'install-brutal-op25.sh').read_text(),
                             first_content)
            self.assertEqual(len(list(root.glob('BrutalOP25.failed.*'))), 1)

    def test_successful_updates_keep_one_verified_previous_program(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'BrutalOP25'
            fixture = root / 'source.tar.gz'
            archive(fixture)
            script = ROOT / 'bootstrap/install-brutal-op25.sh'
            args = ['bash', str(script), '--no-launch', '--install-path', str(destination),
                    '--archive', str(fixture)]
            for extra in ([], ['--update'], ['--update']):
                result = subprocess.run(args + extra, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                time.sleep(1.1)
            backups = list(root.glob('BrutalOP25.previous.*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / '.brutal-op25-install').read_text().strip(),
                             str(destination))

    def test_modified_previous_program_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'BrutalOP25'
            fixture = root / 'source.tar.gz'
            archive(fixture)
            script = ROOT / 'bootstrap/install-brutal-op25.sh'
            args = ['bash', str(script), '--no-launch', '--install-path', str(destination),
                    '--archive', str(fixture)]
            for extra in ([], ['--update']):
                result = subprocess.run(args + extra, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            older = next(root.glob('BrutalOP25.previous.*'))
            (older / 'user-notes.txt').write_text('Keep this file')
            time.sleep(1.1)
            result = subprocess.run(args + ['--update'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((older / 'user-notes.txt').exists())
            self.assertEqual(len(list(root.glob('BrutalOP25.previous.*'))), 2)

    def test_unverified_legacy_folder_is_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'BrutalOP25'
            fixture = root / 'source.tar.gz'
            archive(fixture)
            script = ROOT / 'bootstrap/install-brutal-op25.sh'
            args = ['bash', str(script), '--no-launch', '--install-path', str(destination),
                    '--archive', str(fixture)]
            first = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            legacy = root / 'BrutalOP25.previous.20000101000000'
            legacy.mkdir()
            (legacy / 'unknown-file.txt').write_text('Preserve this')
            updated = subprocess.run(args + ['--update'], capture_output=True, text=True)
            self.assertEqual(updated.returncode, 0, updated.stderr)
            self.assertTrue((legacy / 'unknown-file.txt').exists())
            self.assertIn('Kept 1 older backup folder(s) without a cleanup inventory', updated.stderr)
            self.assertIn('This does not mean you changed them', updated.stderr)


if __name__ == '__main__':
    unittest.main()
