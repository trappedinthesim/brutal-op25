"""Regression checks for local build inputs; never reads personal directories."""
from pathlib import Path
import tempfile
import unittest

from install_sdrplay_payload import install, inspect_package

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    '.dockerignore', 'LICENSE', 'THIRD-PARTY-NOTICES.md', 'build/', 'src/',
    'build/Dockerfile', 'build/Dockerfile.refresh', 'build/Dockerfile.sdrplay',
    'build/Dockerfile.sdrplay-ui', 'build/rtl-usb-retry.patch', 'build/op25-audio-origin.patch',
    'build/requirements.txt', 'build/build_rr_key_helper.py', 'build/install_sdrplay_payload.py',
    'src/importer.py', 'src/rr_key.py', 'src/library.py', 'src/profile_transfer.py', 'src/test_connection.py',
    'src/container_receiver.py', 'src/brutal_ui.py', 'src/brutal_runtime.py',
    'src/brutal_supervisor.py', 'src/brutal-ui.css', 'src/brutal-systems.js',
    'src/brutal-tuning.js', 'src/brutal-logo.png', 'src/hardware_check.py',
    'src/receiver_readiness.py', 'src/brutal_cli.py', 'src/terminal_art.py',
    'src/terminal_menu.py', 'src/rsp_receiver.py',
}


class ImagePrivacyTests(unittest.TestCase):
    def test_retired_browser_onboarding_is_not_a_build_or_launch_path(self):
        retired = ('server.py', 'index.html', 'browse.js', 'manage.html', 'install.html',
                   'compose.yaml', 'compose.receiver.yaml', 'compose.rspdxr2.yaml',
                   'start-container.ps1', 'start-onboarding.ps1', 'setup-rspdxr2.ps1')
        self.assertFalse([name for name in retired if (ROOT / name).exists()])
        dockerfile = (ROOT / 'build/Dockerfile').read_text()
        self.assertIn('CMD ["python", "brutal_cli.py"]', dockerfile)
        self.assertNotIn('8765', dockerfile)
        self.assertIn('brutal-systems.js', dockerfile)

    def test_context_is_exact_source_allowlist(self):
        lines = [line.strip() for line in (ROOT / '.dockerignore').read_text().splitlines()
                 if line.strip() and not line.startswith('#')]
        self.assertEqual(lines[0], '*')
        self.assertEqual(set(lines[1:]), {'!' + name for name in ALLOWED})
        self.assertEqual(len(lines), len(ALLOWED) + 1)

    def test_license_and_upstream_notices_ship_with_image(self):
        license_text = (ROOT / 'LICENSE').read_text()
        notices = (ROOT / 'THIRD-PARTY-NOTICES.md').read_text()
        dockerfile = (ROOT / 'build/Dockerfile').read_text()
        self.assertIn('GNU GENERAL PUBLIC LICENSE', license_text)
        self.assertIn('Version 3, 29 June 2007', license_text)
        self.assertIn('boatbod/op25', notices)
        self.assertIn('rtlsdrblog/rtl-sdr-blog', notices)
        self.assertIn('COPY LICENSE THIRD-PARTY-NOTICES.md ./', dockerfile)
        self.assertIn('COPY --from=builder /opt/op25/ /opt/op25/', dockerfile)
        self.assertIn('COPY --from=rtl-builder /opt/rtl-sdr-blog/ /opt/rtl-sdr-blog/', dockerfile)

    def test_no_bulk_local_copies_or_host_home_mounts(self):
        for filename in ('Dockerfile', 'Dockerfile.sdrplay', 'Dockerfile.sdrplay-ui'):
            for line in (ROOT / 'build' / filename).read_text().splitlines():
                if line.startswith(('COPY ', 'ADD ')):
                    self.assertFalse(line.startswith('ADD '), line)
                    self.assertNotIn(' . ', ' ' + line + ' ')
                    self.assertNotIn('*', line)
        for filename in ('install/brutal-wsl.sh', 'brutal-op25.sh'):
            text = (ROOT / filename).read_text().lower()
            for forbidden in ('/mnt/c', 'c:/users', 'c:\\users', '${home}',
                              '${userprofile}'):
                self.assertNotIn(forbidden, text)
            # Mentioning or selecting the host daemon is safe; passing its socket
            # into the receiver container would give that container root-level
            # control of the host and is the boundary this test must protect.
            self.assertNotRegex(text, r'--(?:volume|mount)\s+[^\n]*docker\.sock')

    def test_license_gate_precedes_proprietary_copy(self):
        text = (ROOT / 'build/Dockerfile.sdrplay').read_text()
        self.assertIn('ARG SDRPLAY_LICENSE_ACCEPTED=no', text)
        self.assertLess(text.index('RUN test "${SDRPLAY_LICENSE_ACCEPTED}" = yes'),
                        text.index('COPY --from=sdrplay-api'))
        with self.assertRaisesRegex(ValueError, 'review and accept'):
            install('does-not-exist', 'no')

    def test_sdrplay_build_includes_make_toolchain(self):
        text = (ROOT / 'build/Dockerfile.sdrplay').read_text()
        self.assertIn('cmake build-essential', text)

    def test_usb_recovery_is_bounded_and_checked_against_pinned_source(self):
        dockerfile = (ROOT / 'build/Dockerfile').read_text()
        self.assertIn('git -C /opt/rtl-sdr-blog apply --check', dockerfile)
        patch = (ROOT / 'build/rtl-usb-retry.patch').read_text()
        additions = '\n'.join(line[1:] for line in patch.splitlines()
                              if line.startswith('+') and not line.startswith('+++'))
        self.assertIn('if (r == LIBUSB_ERROR_PIPE)', additions)
        self.assertLess(additions.index('rtlsdr_demod_read_reg('),
                        additions.index('libusb_control_transfer('))
        self.assertEqual(additions.count('libusb_control_transfer('), 1)
        self.assertNotIn('return 0', additions)
        self.assertNotIn('while', additions)

    def test_audio_websocket_origin_guard_is_applied_to_pinned_upstream(self):
        dockerfile = (ROOT / 'build/Dockerfile').read_text()
        patch = (ROOT / 'build/op25-audio-origin.patch').read_text()
        self.assertIn('git -C /opt/op25 apply --check /tmp/op25-audio-origin.patch', dockerfile)
        self.assertIn('set_validate_handler', patch)
        self.assertIn('con->get_origin()', patch)
        self.assertIn('http://127.0.0.1:8080', patch)
        self.assertIn('http://localhost:8080', patch)

    def test_unrecognized_vendor_package_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'package'
            path.touch()
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                inspect_package(path)


if __name__ == '__main__':
    unittest.main()
