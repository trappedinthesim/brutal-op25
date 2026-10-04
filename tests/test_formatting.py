import unittest
from decimal import Decimal
from test_connection import controls, frequency_hz, frequency_mhz, clean_label


class FormattingTests(unittest.TestCase):
    def test_decimal_conversion(self):
        self.assertEqual(frequency_hz(Decimal("773.84375")), 773843750)
        self.assertEqual(frequency_mhz(773843750), "773.843750")

    def test_controls_do_not_disappear_after_voice_channel(self):
        site = {"siteFreqs": [
            {"freq": "774.19375", "use": "a"},
            {"freq": "773.84375", "use": "d"},
            {"freq": "775.10000", "use": ""},
            {"freq": "773.843750", "use": "a"}]}
        self.assertEqual(controls(site), [773843750, 774193750])

    def test_invalid_frequency(self):
        for value in ("NaN", "Infinity", "0", "-1", "773.1234567"):
            with self.assertRaises(ValueError):
                frequency_hz(value)

    def test_non_numeric_frequency_is_a_clear_value_error_not_a_decimal_error(self):
        for value in ("abc", "", "  ", "851,0125", "1e999999999", "85 1"):
            with self.assertRaisesRegex(ValueError, "MHz"):
                frequency_hz(value)

    def test_tsv_labels(self):
        self.assertEqual(clean_label("Fire\tDispatch\r\nNorth"), "Fire Dispatch North")


if __name__ == "__main__":
    unittest.main()
