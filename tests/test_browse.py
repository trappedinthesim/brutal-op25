import unittest
from unittest.mock import Mock
from importer import RadioReference, is_p25
from test_connection import records


class BrowseTests(unittest.TestCase):
    def adapter(self):
        rr = RadioReference.__new__(RadioReference)
        rr.browse_cache = {}
        rr.type_names = {}
        return rr

    def test_filter_uses_type_not_system_name(self):
        rr = self.adapter()
        rr.call = Mock(side_effect=lambda method, value: [{"sType": value,
            "sTypeDescr": {1: "Project 25", 2: "Motorola", 3: "DMR"}[value]}])
        result = rr.p25_systems([
            {"sid": 1, "sType": 1, "sName": "Regional"},
            {"sid": 2, "sType": 2, "sName": "P25 sounding name"},
            {"sid": 3, "sType": 3, "sName": "Other"},
            {"sid": 1, "sType": 1, "sName": "Regional"}])
        self.assertEqual([row["id"] for row in result], [1])
        self.assertEqual(rr.call.call_count, 3)

    def test_session_cache_and_array_wrapper(self):
        rr = self.adapter()
        rr.call = Mock(return_value={"stateList": {"_value_1": [
            {"stid": 48, "stateName": "Texas", "stateCode": "TX"}], "arrayType": None}})
        self.assertEqual(rr.browse("states", 1)["states"][0]["name"], "Texas")
        self.assertEqual(rr.browse("states", 1)["states"][0]["id"], 48)
        rr.call.assert_called_once_with("getCountryInfo", 1)

    def test_zip_exact_rpc_method_and_leading_zero(self):
        rr = self.adapter()
        rr.call = Mock(return_value={"stid": 1, "ctid": 2, "city": "Town"})
        self.assertEqual(rr.browse("zip", "00501")["county_id"], 2)
        rr.call.assert_called_once_with("getZipcodeInfo", 501)
        for value in ("1234", "12e34", "0000x"):
            with self.assertRaises(ValueError):
                rr.browse("zip", value)

    def test_unknown_type_fails_closed(self):
        rr = self.adapter()
        rr.call = Mock(return_value=[])
        self.assertEqual(rr.p25_systems([{"sid": 1, "sType": 99, "sName": "P25"}]), [])
        self.assertFalse(is_p25("Motorola"))
        self.assertTrue(is_p25("Project 25 Phase II"))


if __name__ == "__main__":
    unittest.main()
