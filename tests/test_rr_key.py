"""Use synthetic test keys only; never load the developer's real key here."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from build_rr_key_helper import build
from importer import application_key
from rr_key import embedded_key


class ApplicationKeySelectionTests(unittest.TestCase):
    def test_embedded_key_is_fallback_after_runtime_sources(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch('importer.Path') as fake_path, \
                mock.patch('importer.embedded_key', return_value='synthetic-embedded'):
            fake_path.return_value.read_text.side_effect = OSError('no mounted key')
            self.assertEqual(application_key(), 'synthetic-embedded')
            os.environ['BRUTAL_RR_APP_KEY'] = 'synthetic-runtime'
            self.assertEqual(application_key(), 'synthetic-runtime')
            del os.environ['BRUTAL_RR_APP_KEY']
            fake_path.return_value.read_text.side_effect = None
            fake_path.return_value.read_text.return_value = 'synthetic-mounted'
            self.assertEqual(application_key(), 'synthetic-mounted')

    def test_no_key_still_fails_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch('importer.Path') as fake_path, \
                mock.patch('importer.embedded_key', return_value=''):
            fake_path.return_value.read_text.side_effect = OSError('no mounted key')
            with self.assertRaisesRegex(ValueError, 'no configured application key'):
                application_key()


@unittest.skipUnless(shutil.which('cc'), 'A C compiler is needed to test the release helper')
class CompiledHelperTests(unittest.TestCase):
    def test_synthetic_key_is_obscured_but_available_at_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / 'key'
            library = Path(directory) / 'librrkey.so'
            synthetic = 'SYNTHETIC_TEST_APP_KEY_ONLY'
            key_file.write_text(synthetic, encoding='ascii')
            build(key_file, library, required=True)
            self.assertEqual(embedded_key(library), synthetic)
            self.assertNotIn(synthetic.encode('ascii'), library.read_bytes())

    def test_source_build_has_no_embedded_key(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / 'librrkey.so'
            build(Path(directory) / 'missing', library)
            self.assertEqual(embedded_key(library), '')
            with self.assertRaisesRegex(ValueError, 'requires.*build secret'):
                build(Path(directory) / 'missing', library, required=True)


if __name__ == '__main__':
    unittest.main()
