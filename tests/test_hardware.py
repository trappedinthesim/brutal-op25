import json
from pathlib import Path
import unittest
from hardware_check import check_profile
from importer import PROFILES, export_setup


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.system = json.loads((Path(__file__).parent / 'live-bexar-system.json').read_text(encoding='utf-8'))

    def export(self, hardware):
        return export_setup(self.system, {'hardware': hardware, 'site_id': self.system['sites'][0]['id'],
                                         'talkgroup_ids': [], 'source': 'radioreference'})

    def test_all_named_presets_export_real_system_with_parseable_gains(self):
        for identity, preset in PROFILES.items():
            if identity == 'custom':
                continue
            with self.subTest(profile=identity):
                files = self.export({'profile': identity})
                cfg = json.loads(files['config.json'])
                device = cfg['devices'][0]
                self.assertEqual(device['rate'], preset['rate'])
                self.assertEqual(device['args'], preset['args'])
                for gain in device['gains'].split(','):
                    name, value = gain.split(':')  # Same upstream parser contract.
                    self.assertTrue(name)
                    int(value)
                self.assertFalse(device['gain_mode'])
                self.assertFalse(json.loads(files['import-info.json'])['hardware_verified'])

    def test_airspy_models_have_distinct_rates(self):
        self.assertEqual(PROFILES['airspy']['rate'], 2500000)
        self.assertEqual(PROFILES['airspymini']['rate'], 3000000)

    def test_only_owned_radio_families_and_custom_are_selectable(self):
        self.assertEqual({key for key, profile in PROFILES.items() if profile.get('selectable', True)},
                         {'rtl', 'rtlv4', 'rspdxr2', 'custom'})

    def test_blank_fractional_malformed_and_duplicate_gains_rejected(self):
        for gain in ('', 'LNA:38.6', 'LNA', 'LNA:39,', 'LNA:39,LNA:20'):
            with self.subTest(gain=gain), self.assertRaises(ValueError):
                self.export({'profile': 'rtl', 'gains': gain})

    def test_sdrplay_missing_api_and_plugin_are_not_hardware_success(self):
        report = check_profile('rspdxr2', {'backends': ['soapy'], 'libraries': {
            'SoapySDR': {'loadable': True}, 'sdrplay_api': {'loadable': False}},
            'soapy_factories': [], 'rtl_blog_source_present': False, 'rtl_library_paths': []})
        self.assertFalse(report['software_dependencies_present'])
        self.assertEqual(len(report['missing']), 2)
        self.assertFalse(report['hardware_verified'])

    def test_v4_requires_loaded_vendor_driver_not_just_generic_rtl_backend(self):
        inventory = {'backends': ['rtl'], 'libraries': {'rtlsdr': {'loadable': True}},
            'soapy_factories': [], 'rtl_blog_source_present': False, 'rtl_library_paths': []}
        self.assertTrue(check_profile('rtl', inventory)['software_dependencies_present'])
        self.assertFalse(check_profile('rtlv4', inventory)['software_dependencies_present'])
        inventory.update(rtl_blog_source_present=True, rtl_library_paths=['/usr/local/lib/librtlsdr.so.0.6git'])
        report = check_profile('rtlv4', inventory)
        self.assertTrue(report['software_dependencies_present'])
        self.assertFalse(report['hardware_verified'])


if __name__ == '__main__':
    unittest.main()
