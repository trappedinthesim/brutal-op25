import csv
import io
import json
import unittest
from importer import demo_system, export_setup, normalize_system, system_id, zip_files


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.system = demo_system()
        self.request = {"hardware": {"profile": "rtl"}, "site_id": 1,
                        "talkgroup_ids": [101, 201], "selected_only": True}

    def test_export_matches_boatbod_units_and_links(self):
        files = export_setup(self.system, self.request)
        cfg = json.loads(files["config.json"])
        self.assertEqual(cfg["devices"][0]["frequency"], 773843750)
        trunk = cfg["trunking"]["chans"][0]
        self.assertEqual(trunk["control_channel_list"], "773.843750,774.193750")
        self.assertEqual(cfg["channels"][0]["trunking_sysname"], trunk["sysname"])
        self.assertEqual(trunk["nac"], "0x293")
        self.assertEqual(files["whitelist.tsv"], "101\n201\n")
        for field in ("tgid_tags_file", "whitelist"):
            self.assertIn(trunk[field], files)
        rows = list(csv.reader(io.StringIO(files["trunk.tsv"]), delimiter="\t"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[1]), 9)
        self.assertEqual(rows[1][1], trunk["control_channel_list"])

    def test_separate_sites(self):
        self.request["site_id"] = 2
        files = export_setup(self.system, self.request)
        cfg = json.loads(files["config.json"])
        self.assertEqual(cfg["trunking"]["chans"][0]["control_channel_list"], "851.012500")

    def test_empty_whitelist_rejected(self):
        self.request["talkgroup_ids"] = []
        with self.assertRaises(ValueError):
            export_setup(self.system, self.request)

    def test_unknown_talkgroup_rejected(self):
        self.request["talkgroup_ids"] = [999]
        with self.assertRaises(ValueError):
            export_setup(self.system, self.request)

    def test_conflicting_duplicate_keeps_first_and_is_reported(self):
        system = normalize_system(1, {"sName": "Test"}, [],
            [{"tgDec": 1, "tgAlpha": "One"}, {"tgDec": 1, "tgAlpha": "Other"}, {"tgDec": 2, "tgAlpha": "Two"}])
        self.assertEqual([(g["id"], g["label"]) for g in system["talkgroups"]], [(1, "One"), (2, "Two")])
        self.assertEqual(len(system["import_warnings"]), 1)
        self.assertIn("Talkgroup 1", system["import_warnings"][0])
        self.assertIn("One", system["import_warnings"][0])
        self.assertIn("Other", system["import_warnings"][0])

    def test_identical_duplicate_is_silent(self):
        system = normalize_system(1, {"sName": "Test"}, [],
            [{"tgDec": 5, "tgAlpha": "Same"}, {"tgDec": 5, "tgAlpha": "Same"}])
        self.assertEqual(len(system["talkgroups"]), 1)
        self.assertNotIn("import_warnings", system)

    def test_invalid_talkgroup_ids_are_skipped_not_fatal(self):
        system = normalize_system(1, {"sName": "Test"}, [], [
            {"tgDec": 0, "tgAlpha": "Zero"}, {"tgDec": 70000, "tgAlpha": "Huge"},
            {"tgDec": "abc", "tgAlpha": "Text"}, {"tgAlpha": "Missing"}, {"tgDec": 7, "tgAlpha": "Good"}])
        self.assertEqual([g["id"] for g in system["talkgroups"]], [7])
        self.assertEqual(len(system["import_warnings"]), 4)
        self.assertIn("Zero", " ".join(system["import_warnings"]))

    def test_non_object_talkgroup_is_skipped_not_fatal(self):
        system = normalize_system(1, {"sName": "Test"}, [], [
            None, "bad row", {"tgDec": 7, "tgAlpha": "Good"}])
        self.assertEqual([g["id"] for g in system["talkgroups"]], [7])
        self.assertEqual(system["import_warnings"], [
            "Skipped a malformed talkgroup record.",
            "Skipped a malformed talkgroup record.",
        ])

    def test_one_malformed_site_does_not_hide_other_valid_sites(self):
        sites = [{"siteId": "bad", "siteDescr": "Broken"},
                 {"siteId": 9, "siteDescr": "Good", "siteFreqs": [
                     {"use": "d", "freq": "851.0125"}]}]
        system = normalize_system(1, {"sName": "Test"}, sites, [])
        self.assertEqual([(s["id"], s["controls_hz"]) for s in system["sites"]],
                         [(9, [851012500])])
        self.assertEqual(len(system["import_warnings"]), 1)

    def test_clean_import_has_no_warning_key(self):
        self.assertNotIn("import_warnings", self.system)

    def test_defaults_are_unchanged_when_no_listening_preferences_are_set(self):
        files = export_setup(self.system, self.request)
        trunk = json.loads(files["config.json"])["trunking"]["chans"][0]
        self.assertEqual(trunk["crypt_behavior"], 2)
        self.assertEqual(trunk["blacklist"], "")
        for key in ("tgid_hold_time", "rid_tags_file"):
            self.assertNotIn(key, trunk)
        self.assertNotIn("blacklist.tsv", files)
        self.assertNotIn("rid_tags.tsv", files)
        for row in csv.reader(io.StringIO(files["talkgroups.tsv"]), delimiter="\t"):
            self.assertEqual(len(row), 2)  # no priority column unless asked for

    def test_priority_blocked_names_hold_time_and_encryption_reach_the_receiver_files(self):
        request = {**self.request, "selected_only": False, "talkgroup_ids": [],
                   "priority_tgids": [102, 101], "blocked_tgids": [301],
                   "rid_labels": {"6002013": "Engine 5", 42: "  Chief\tCar "}, "crypt_behavior": 1, "hold_time": 4.5}
        files = export_setup(self.system, request)
        cfg = json.loads(files["config.json"])
        trunk, channel = cfg["trunking"]["chans"][0], cfg["channels"][0]
        self.assertEqual((trunk["crypt_behavior"], channel["crypt_behavior"]), (1, 1))
        self.assertEqual(trunk["tgid_hold_time"], 4.5)
        self.assertEqual(trunk["blacklist"], "blacklist.tsv")
        self.assertEqual(trunk["rid_tags_file"], "rid_tags.tsv")
        self.assertEqual(files["blacklist.tsv"], "301\n")
        self.assertEqual(files["rid_tags.tsv"], "42\tChief Car\n6002013\tEngine 5\n")
        rows = {r[0]: r for r in csv.reader(io.StringIO(files["talkgroups.tsv"]), delimiter="\t")}
        self.assertEqual(rows["101"][2], "1")
        self.assertEqual(rows["102"][2], "1")
        self.assertEqual(len(rows["201"]), 2)   # untouched talkgroups keep OP25's default priority
        legacy = list(csv.reader(io.StringIO(files["trunk.tsv"]), delimiter="\t"))
        self.assertEqual(legacy[1][7], "blacklist.tsv")
        manifest = json.loads(files["import-info.json"])
        self.assertEqual((manifest["priority_talkgroups"], manifest["blocked_talkgroups"], manifest["radio_names"]),
                         ([101, 102], [301], 2))

    def test_listening_preferences_are_validated(self):
        bad = [
            {"priority_tgids": [999]},                       # not in this system
            {"blocked_tgids": ["abc"]},
            {"priority_tgids": [101], "blocked_tgids": [101]},  # cannot be both
            {"blocked_tgids": [101], "selected_only": True, "talkgroup_ids": [101]},
            {"rid_labels": {"0": "x"}}, {"rid_labels": {"16777216": "x"}}, {"rid_labels": {"abc": "x"}},
            {"rid_labels": {"5": "x" * 41}}, {"rid_labels": ["not", "a", "dict"]},
            {"crypt_behavior": 3}, {"crypt_behavior": 0}, {"crypt_behavior": "x"},
            {"hold_time": -1}, {"hold_time": 31}, {"hold_time": "soon"}, {"hold_time": float("nan")},
        ]
        for extra in bad:
            with self.assertRaises(ValueError, msg=str(extra)):
                export_setup(self.system, {**self.request, **extra})
        # The edges are accepted.
        export_setup(self.system, {**self.request, "hold_time": 0, "rid_labels": {"1": "a", "16777215": "b"}})
        export_setup(self.system, {**self.request, "hold_time": 30, "crypt_behavior": 1})

    def test_empty_radio_names_are_dropped_not_written(self):
        files = export_setup(self.system, {**self.request, "rid_labels": {"7": "   ", "8": ""}})
        self.assertNotIn("rid_tags.tsv", files)

    def test_categories_are_named_sorted_and_optional(self):
        groups = [{"tgDec": 1, "tgAlpha": "One", "tgCid": 10}]
        cats = [{"tgCid": 11, "tgCname": "Police"}, {"tgCid": 10, "tgCname": "Fire"},
                {"tgCid": "bad", "tgCname": "Broken"}, {"tgCname": "No id"}, {"tgCid": 12, "tgCname": "  "}]
        system = normalize_system(1, {"sName": "T"}, [], groups, categories=cats)
        self.assertEqual(system["categories"], [{"id": 12, "name": "Category 12"}, {"id": 10, "name": "Fire"},
                                                {"id": 11, "name": "Police"}])
        self.assertNotIn("categories", normalize_system(1, {"sName": "T"}, [], groups))
        self.assertNotIn("categories", normalize_system(1, {"sName": "T"}, [], groups, categories=[]))

    def test_a_category_lookup_failure_never_blocks_an_import(self):
        from importer import RadioReference
        rr = object.__new__(RadioReference)
        rr.call = lambda *a: (_ for _ in ()).throw(ValueError("RadioReference getTrsTalkgroupCats: boom"))
        self.assertEqual(rr.categories(1), [])
        rr.call = lambda *a: {"TalkgroupCat": [{"tgCid": 1, "tgCname": "Fire"}]}
        self.assertEqual(rr.categories(1), [{"tgCid": 1, "tgCname": "Fire"}])

    def test_exact_id_parsing(self):
        self.assertEqual(system_id("https://www.radioreference.com/apps/db/?sid=2324"), 2324)
        self.assertEqual(system_id("2324"), 2324)
        self.assertEqual(system_id("https://www.radioreference.com/db/sid/2324"), 2324)
        with self.assertRaises(ValueError):
            system_id("https://example.com/?sid=2324")

    def test_demo_is_marked_in_download(self):
        self.request["source"] = "fictional-demo"
        files = export_setup(self.system, self.request)
        self.assertIn("FICTIONAL DEMO ONLY", files["README.txt"])

    def test_zip_has_no_credentials(self):
        import zipfile
        files = export_setup(self.system, self.request)
        with zipfile.ZipFile(io.BytesIO(zip_files(files))) as archive:
            self.assertEqual(set(archive.namelist()), set(files))
            for name in archive.namelist():
                self.assertNotIn('"password"', archive.read(name).decode())
                self.assertNotIn('"appKey"', archive.read(name).decode())


if __name__ == "__main__":
    unittest.main()
