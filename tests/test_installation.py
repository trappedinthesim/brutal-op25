"""Read-only installer checks plus a disposable, fake SDRplay download."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name != 'nt' and shutil.which('bash'),
                     'Bash installer checks need a native Linux/WSL shell')
class LinuxInstallerTests(unittest.TestCase):
    def test_scripts_parse(self):
        scripts = ('install-brutal-op25.sh', 'install/user-launcher.sh', 'brutal-op25.sh',
                   'install/brutal-wsl.sh',
                   'install/prepare-sdrplay.sh', 'install/build-sdrplay.sh',
                   'install/sdrplay-license.sh')
        result = subprocess.run(['bash', '-n', *scripts], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_mode_makes_no_changes(self):
        result = subprocess.run(['bash', 'install-brutal-op25.sh', '--check'],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No packages, services, USB permissions, or images were changed.',
                      result.stdout)

    @unittest.skipIf(getattr(os, 'geteuid', lambda: 1)() == 0,
                     'A personal launcher is deliberately not installed for root')
    def test_personal_command_is_created_and_preserves_an_unrelated_command(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'home with spaces'
            home.mkdir()
            env = dict(os.environ, HOME=str(home), BRUTAL_TEST_ROOT=str(ROOT))
            command = ['bash', '-c',
                       '. ./install/user-launcher.sh; brutal_install_user_command "$BRUTAL_TEST_ROOT"']
            result = subprocess.run(command, cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            launcher = home / '.local/bin/brutal-op25'
            self.assertTrue(launcher.exists())
            check = subprocess.run([str(launcher), '--check'], cwd=ROOT, env=env,
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertIn('No packages, services, USB permissions, or images were changed.',
                          check.stdout)
            launcher.write_text('user-owned command\n')
            result = subprocess.run(command, cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(launcher.read_text(), 'user-owned command\n')

    def test_changed_vendor_payload_is_rejected_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            curl = Path(directory) / 'curl'
            curl.write_text('#!/usr/bin/env python3\n'
                            'import pathlib, sys\n'
                            'args = sys.argv[1:]\n'
                            'if "--output" in args:\n'
                            '    pathlib.Path(args[args.index("--output") + 1]).write_bytes(b"unverified payload")\n'
                            'else:\n'
                            '    print(\'<a data-downloadurl="https://sdrplay.com/download/hardware-api-linux/?test=1">\')\n')
            curl.chmod(0o755)
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', 'install/prepare-sdrplay.sh'], cwd=ROOT,
                                    env=env, capture_output=True, text=True,
                                    timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertNotIn('Review the SDRplay license', result.stdout)

    def test_sdrplay_license_choice_is_explicit_and_retryable(self):
        # A synthetic fixture tests the UI; no real vendor license is accepted here.
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'fixture-license.txt'
            fixture.write_text('TEST LICENSE TEXT ONLY\n')
            command = ['bash', '-c',
                       '. ./install/sdrplay-license.sh; brutal_request_sdrplay_license "$1"',
                       'bash', str(fixture)]
            accepted = subprocess.run(command, cwd=ROOT, input='mistake\n\nr\ny\n',
                                      capture_output=True, text=True, timeout=10)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(accepted.stdout.count('TEST LICENSE TEXT ONLY'), 2)
            self.assertIn('Choose y to accept', accepted.stdout)
            self.assertIn('License accepted.', accepted.stdout)
            cancelled = subprocess.run(command, cwd=ROOT, input='n\n',
                                       capture_output=True, text=True, timeout=10)
            self.assertNotEqual(cancelled.returncode, 0)
            self.assertIn('Your saved profile is unchanged', cancelled.stdout)
            no_input = subprocess.run(command, cwd=ROOT, input='',
                                      capture_output=True, text=True, timeout=10)
            self.assertNotEqual(no_input.returncode, 0)
            self.assertIn('No license decision was received', no_input.stderr)

    @unittest.skipUnless(shutil.which('less'), 'Interactive license test needs less')
    def test_sdrplay_pager_explains_how_to_return_to_setup(self):
        import fcntl
        import pty
        import select
        import struct
        import termios
        import time

        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'fixture-license.txt'
            fixture.write_text('TEST LICENSE TEXT ONLY\n' * 100)
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, 0, 0))
            command = ['bash', '-c',
                       '. ./install/sdrplay-license.sh; brutal_request_sdrplay_license "$1"',
                       'bash', str(fixture)]
            process = subprocess.Popen(command, cwd=ROOT, stdin=slave, stdout=slave,
                                       stderr=slave, env={**os.environ, 'TERM': 'xterm'})
            os.close(slave)
            seen = bytearray()

            def wait_for(marker):
                deadline = time.monotonic() + 8
                while marker not in seen and time.monotonic() < deadline:
                    if not select.select([master], [], [], 0.2)[0]:
                        continue
                    try:
                        seen.extend(os.read(master, 4096))
                    except OSError:
                        break
                self.assertIn(marker, seen, bytes(seen[-1000:]))

            try:
                wait_for(b'press q to return')
                os.write(master, b'q')
                wait_for(b'Accept SDRplay')
                os.write(master, b'y\n')
                self.assertEqual(process.wait(timeout=8), 0, bytes(seen[-1000:]))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                os.close(master)


class WindowsInstallerSourceTests(unittest.TestCase):
    def test_wsl_installer_uses_official_ubuntu_not_desktop(self):
        source = (ROOT / 'install/install-brutal-wsl.ps1').read_text()
        linux = (ROOT / 'install-brutal-op25.sh').read_text()
        self.assertIn("$taskDistribution = 'Ubuntu-24.04'", source)
        self.assertIn("'--web-download','--no-launch'", source)
        self.assertIn('No sign-in is needed; close it and return here.', source)
        self.assertLess(source.index('No sign-in is needed; close it and return here.'),
                        source.index("Start-Process -FilePath 'wsl.exe'"))
        self.assertIn("Read-Host 'Install these components and continue? [y/N]'", source)
        self.assertLess(source.index('Read-Host'), source.index('Install-BrutalWslDistribution }'))
        self.assertIn('https://download.docker.com/linux/$ID', linux)
        self.assertNotIn('Docker.DockerDesktop', source)
        self.assertIn('if ($CheckOnly)', source)

    def test_vendor_checksum_is_shared_across_install_paths(self):
        expected = '3a97ca764263bbe76fb0f2220e6408942357e8864c19e1408a6d6987af382fe3'
        for path in ('prepare-sdrplay.sh', 'build-sdrplay.sh'):
            self.assertIn(expected, (ROOT / 'install' / path).read_text(), path)

    def test_sdrplay_addon_is_checked_before_use(self):
        linux = (ROOT / 'install/build-sdrplay.sh').read_text()
        launcher = (ROOT / 'brutal-op25.sh').read_text()
        wsl = (ROOT / 'install/brutal-wsl.sh').read_text()
        self.assertIn('check_profile("rspdxr2")', linux)
        self.assertIn('check_profile("rspdxr2")', launcher)
        self.assertIn('check_profile("rspdxr2")', wsl)
        self.assertIn('install/prepare-sdrplay.sh', wsl)

    def test_usb_bridge_is_pinned_and_releases_only_its_own_attach(self):
        source = (ROOT / 'install/wsl-usb.ps1').read_text()
        wsl = (ROOT / 'install/brutal-wsl.sh').read_text()
        self.assertIn('1c984914aec944de19b64eff232421439629699f8138e3ddc29301175bc6d938', source)
        self.assertIn('Get-AuthenticodeSignature', source)
        self.assertIn('if ($taskAttachedHere', source)
        self.assertIn('task_attached == 1', wsl)
        self.assertIn('BRUTAL_USB=', source)


if __name__ == '__main__':
    unittest.main()
