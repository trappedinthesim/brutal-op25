from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import stat
from types import SimpleNamespace
from receiver_readiness import environment, usb_inventory, assess


class ReceiverReadinessTests(unittest.TestCase):
    def env(self, container=False, kernel='generic', hint='auto', platform='linux'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'proc/sys/kernel/osrelease'
            path.parent.mkdir(parents=True)
            path.write_text(kernel)
            if container:
                (root / '.dockerenv').touch()
            return environment(root, platform, hint)

    def test_native_linux_is_first_class(self):
        env = self.env()
        self.assertEqual(env['kind'], 'linux_native')
        report = assess(env, [], 'rspdxr2', {'missing': []})
        self.assertNotIn('Windows', ' '.join(report['blockers']))
        self.assertNotIn('helper', ' '.join(report['blockers']))

    def test_container_and_wsl_detection(self):
        self.assertEqual(self.env(True)['kind'], 'linux_container')
        self.assertEqual(self.env(True, '6.18-microsoft-standard-WSL2')['kind'], 'wsl_container')
        self.assertEqual(self.env(False, '6.18-microsoft-standard-WSL2')['kind'], 'wsl')
        self.assertEqual(self.env(True, hint='windows-wsl')['kind'], 'wsl_container')
        self.assertEqual(self.env(True, 'microsoft', hint='linux')['kind'], 'linux_container')
        self.assertEqual(self.env(platform='win32')['kind'], 'windows_host')
        with self.assertRaises(ValueError):
            self.env(hint='browser-said-windows')

    def test_passthrough_guidance_depends_on_environment(self):
        linux = assess(self.env(True), [], 'rtl', {'missing': []})
        wsl = assess(self.env(True, hint='windows-wsl'), [], 'rtl', {'missing': []})
        self.assertIn('Pass the selected USB device', linux['blockers'][0])
        self.assertIn('Forward the selected USB radio', wsl['blockers'][0])

    def test_sysfs_without_device_node_reports_passthrough_not_selection(self):
        report = assess(self.env(True), [self.device(present=False)], 'rspdxr2', {'missing': []})
        self.assertFalse(report['prerequisites_ready'])
        self.assertIn('USB device node was not passed', report['blockers'][0])
        self.assertNotIn('Select the visible radio', report['blockers'][0])

    def device(self, present=True, access=True):
        return {'node': '/dev/bus/usb/001/002', 'compatible_profiles': ['rspdxr2'],
                'device_node_present': present, 'read_write_access': access}

    def test_ready_native_linux_has_no_windows_gate_but_not_hardware_verified(self):
        d = self.device()
        report = assess(self.env(), [d], 'rspdxr2', {'missing': []}, d['node'])
        self.assertTrue(report['prerequisites_ready'])
        self.assertFalse(report['hardware_verified'])
        self.assertEqual(report['blockers'], [])
        # An already-forwarded WSL device does not require a helper connection either.
        self.assertTrue(assess(self.env(True, hint='windows-wsl'), [d], 'rspdxr2',
                               {'missing': []}, d['node'])['prerequisites_ready'])

    def test_explicit_selection_permissions_and_driver_are_separate(self):
        env = self.env(True)
        d = self.device()
        self.assertIn('Select the visible radio', assess(env, [d], 'rspdxr2', {'missing': []})['blockers'][0])
        d = self.device(present=False)
        self.assertIn('device node', assess(env, [d], 'rspdxr2', {'missing': []}, d['node'])['blockers'][0])
        d = self.device(access=False)
        result = assess(env, [d], 'rspdxr2', {'missing': ['sdrplay_api']}, d['node'])
        self.assertEqual(len(result['blockers']), 2)
        self.assertFalse(result['prerequisites_ready'])
        self.assertIsNone(assess(env, [d], 'rtlv4', {'missing': []}, d['node'])['selected_device'])

    def test_sysfs_listing_does_not_claim_node_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            usb = root / 'sys/bus/usb/devices/1-2'
            usb.mkdir(parents=True)
            for name, value in {'idVendor': '1df7', 'idProduct': '3060', 'busnum': '1', 'devnum': '2'}.items():
                (usb / name).write_text(value)
            devices = usb_inventory(root)
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]['node'], '/dev/bus/usb/001/002')
            self.assertFalse(devices[0]['device_node_present'])
            self.assertFalse(devices[0]['read_write_access'])
            # Unit-only OS metadata mocks; no fictional device data is exposed in the UI.
            original = Path.stat
            def mock_stat(path, *args, **kwargs):
                if path.as_posix().endswith('/dev/bus/usb/001/002'):
                    return SimpleNamespace(st_mode=stat.S_IFCHR)
                return original(path, *args, **kwargs)
            with patch.object(Path, 'stat', mock_stat):
                self.assertTrue(usb_inventory(root, lambda *_: True)[0]['read_write_access'])
                self.assertFalse(usb_inventory(root, lambda *_: False)[0]['read_write_access'])


if __name__ == '__main__':
    unittest.main()
