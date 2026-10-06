from copy import deepcopy
from pathlib import Path
import io
import json
import tempfile
import unittest
import zipfile
from library import ProfileLibrary


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = ProfileLibrary(self.temp.name)
        self.system = json.loads((Path(__file__).parent / "live-bexar-system.json").read_text(encoding="utf-8"))
        self.request = {"hardware": {"profile": "rtl", "ppm": 2.5, "password": "not-persisted"},
            "site_id": self.system["sites"][0]["id"], "source": "radioreference",
            "selected_only": True, "talkgroup_ids": [self.system["talkgroups"][0]["id"]]}

    def tearDown(self):
        self.temp.cleanup()

    def test_persistent_profiles_export_separately(self):
        first = self.library.save(self.system, self.request)
        second_request = {**self.request, "site_id": self.system["sites"][1]["id"]}
        second = self.library.save(self.system, second_request)
        self.assertEqual(len(ProfileLibrary(self.temp.name).list()), 2)
        with zipfile.ZipFile(io.BytesIO(self.library.export([first["id"], second["id"]]))) as archive:
            for profile in (first, second):
                self.assertIn(profile["id"] + "/talkgroup-info.json", archive.namelist())
                self.assertNotIn(b'"password"', archive.read(profile["id"] + "/saved-profile.json"))

    def test_additional_sdr_copies_saved_system_without_reimport_or_mutating_original(self):
        original = self.library.save(self.system, {**self.request, "profile_name": "My AARRS",
            "priority_tgids": [self.system["talkgroups"][0]["id"]], "hold_time": 3})
        before = deepcopy(self.library.read(original["id"]))
        hardware = {"profile": "rspdxr2", "args": "soapy=0,driver=sdrplay", "rate": 2000000,
            "gains": "IFGR:40,RFGR:0", "ppm": 0}
        second = self.library.clone_for_hardware(original["id"], hardware)
        self.assertNotEqual(second["id"], original["id"])
        self.assertEqual(second["revision"], 1)
        self.assertEqual(second["name"], "My AARRS")
        self.assertEqual(second["system"], before["system"])
        self.assertEqual(second["settings"], {**before["settings"], "hardware": hardware})
        self.assertEqual(self.library.read(original["id"]), before)
        self.assertEqual(len(self.library.list()), 2)
        retried = self.library.clone_for_hardware(original["id"], hardware)
        self.assertEqual(retried["id"], second["id"])
        self.assertEqual(len(self.library.list()), 2)
        with self.assertRaisesRegex(ValueError, "already uses this SDR type"):
            self.library.clone_for_hardware(original["id"], before["settings"]["hardware"])
        self.assertEqual(len(self.library.list()), 2)

    def test_corrupt_profile_is_skipped_and_reported_not_fatal(self):
        good = self.library.save(self.system, self.request)
        root = Path(self.temp.name)
        broken, wrong_shape = "a" * 32, "b" * 32
        (root / (broken + ".json")).write_text("{truncated", encoding="utf-8")
        (root / (wrong_shape + ".json")).write_text('{"id": "x"}', encoding="utf-8")
        profiles = self.library.list()
        self.assertEqual([p["id"] for p in profiles], [good["id"]])
        self.assertEqual(sorted(self.library.unreadable), [broken + ".json", wrong_shape + ".json"])
        # A later clean listing clears the report.
        (root / (broken + ".json")).unlink()
        (root / (wrong_shape + ".json")).unlink()
        self.library.list()
        self.assertEqual(self.library.unreadable, [])

    def test_damaged_profile_metadata_is_rejected_before_use(self):
        good = self.library.save(self.system, self.request)
        path = self.library.path(good["id"])
        for bad in ({**good, "revision": "x/../../outside"},
                    {**good, "revision": True}, {**good, "id": "f" * 32},
                    {**good, "settings": []}):
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Saved profile is damaged"):
                self.library.read(good["id"])
            self.assertEqual(self.library.list(), [])
            self.assertEqual(self.library.unreadable, [path.name])

    def test_damaged_nested_record_cannot_break_the_whole_library(self):
        good = self.library.save(self.system, self.request)
        other = self.library.save(self.system, self.request)
        path = self.library.path(good["id"])
        bad_versions = [
            {**good, "system": {**good["system"], "sites": [None]}},
            {**good, "system": {**good["system"], "talkgroups": [None]}},
            {**good, "system": {**good["system"], "categories": [None]}},
            {**good, "settings": {**good["settings"], "site_id": 999999}},
            {**good, "settings": {**good["settings"], "source": None}},
            {**good, "settings": {**good["settings"], "talkgroup_ids": [False]}},
            {**good, "system": {**good["system"], "id": None}},
            {**good, "settings": {**good["settings"], "priority_tgids": None}},
            {**good, "settings": {**good["settings"], "blocked_tgids": [999999]}},
            {**good, "settings": {**good["settings"], "rid_labels": []}},
            {**good, "settings": {**good["settings"], "selected_only": True, "talkgroup_ids": []}},
        ]
        for bad in bad_versions:
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Saved profile is damaged"):
                self.library.read(good["id"])
            self.assertEqual([p["id"] for p in self.library.list()], [other["id"]])
            self.assertEqual(self.library.unreadable, [path.name])

    def test_listening_preferences_persist_and_plain_saves_stay_clean(self):
        plain = self.library.save(self.system, self.request)
        for key in ("priority_tgids", "blocked_tgids", "rid_labels", "crypt_behavior", "hold_time"):
            self.assertNotIn(key, plain["settings"])  # older and plain profiles are untouched
        ids = [g["id"] for g in self.system["talkgroups"]]
        request = {**plain["settings"], "selected_only": False, "talkgroup_ids": [],
                   "priority_tgids": [ids[1], ids[0]], "blocked_tgids": [ids[5]],
                   "rid_labels": {6002013: "Engine 5"}, "crypt_behavior": 1, "hold_time": 3,
                   "profile_id": plain["id"], "revision": plain["revision"]}
        saved = self.library.save(self.system, request)
        self.assertEqual(saved["revision"], 2)
        reread = self.library.read(saved["id"])["settings"]
        self.assertEqual(reread["priority_tgids"], sorted([ids[0], ids[1]]))
        self.assertEqual(reread["blocked_tgids"], [ids[5]])
        self.assertEqual(reread["rid_labels"], {"6002013": "Engine 5"})
        self.assertEqual((reread["crypt_behavior"], reread["hold_time"]), (1, 3.0))
        # A later edit that does not mention them cannot silently drop them via the terminal path.
        again = self.library.save(self.system, {**reread, "profile_id": saved["id"], "revision": 2})
        self.assertEqual(again["settings"]["blocked_tgids"], [ids[5]])
        for bad in ({"priority_tgids": ["x"]}, {"rid_labels": {"x": "y"}}, {"hold_time": "soon"},
                    {"priority_tgids": [ids[0]], "blocked_tgids": [ids[0]]}):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.library.save(self.system, {**reread, **bad, "profile_id": saved["id"], "revision": 3})
        self.assertEqual(self.library.read(saved["id"])["revision"], 3)  # failed saves wrote nothing

    def test_review_prunes_marks_on_talkgroups_that_radioreference_dropped(self):
        ids = [g["id"] for g in self.system["talkgroups"]]
        profile = self.library.save(self.system, {**self.request, "selected_only": False, "talkgroup_ids": [],
                                                  "priority_tgids": [ids[0], ids[1]], "blocked_tgids": [ids[2]]})
        fresh = deepcopy(self.system)
        fresh["talkgroups"] = [g for g in fresh["talkgroups"] if g["id"] not in (ids[1], ids[2])]
        review = self.library.review(profile["id"], fresh)
        self.assertEqual(review["blockers"], [])
        self.assertEqual(review["settings"]["priority_tgids"], [ids[0]])
        self.assertEqual(review["settings"]["blocked_tgids"], [])
        updated = self.library.apply(review)
        self.assertEqual(updated["settings"]["priority_tgids"], [ids[0]])

    def test_remove_archives_instead_of_deleting(self):
        keep = self.library.save(self.system, self.request)
        gone = self.library.save(self.system, {**self.request, "site_id": self.system["sites"][1]["id"]})
        self.library.remove(gone["id"])
        self.assertEqual([p["id"] for p in self.library.list()], [keep["id"]])
        archived = Path(self.temp.name) / "history" / "removed" / (gone["id"] + "-r1.json")
        self.assertEqual(json.loads(archived.read_text(encoding="utf-8"))["id"], gone["id"])
        with self.assertRaises(ValueError):
            self.library.read(gone["id"])
        with self.assertRaises(ValueError):
            self.library.remove(gone["id"])
        with self.assertRaises(ValueError):
            self.library.remove("../escape")

    def test_review_does_not_write_and_apply_preserves_settings(self):
        profile = self.library.save(self.system, self.request)
        fresh = deepcopy(self.system)
        fresh["talkgroups"][1]["label"] += " changed"
        review = self.library.review(profile["id"], fresh)
        self.assertEqual(len(review["changes"]["changed"]), 1)
        self.assertEqual(self.library.read(profile["id"])["revision"], 1)
        updated = self.library.apply(review)
        self.assertEqual(updated["settings"], profile["settings"])
        self.assertEqual(updated["revision"], 2)
        self.assertTrue((Path(self.temp.name) / "history" / (profile["id"] + "-r1.json")).exists())
        with self.assertRaises(ValueError):
            self.library.apply(review)

    def test_removed_last_selected_group_blocks_update(self):
        profile = self.library.save(self.system, self.request)
        fresh = deepcopy(self.system)
        fresh["talkgroups"] = fresh["talkgroups"][1:]
        review = self.library.review(profile["id"], fresh)
        self.assertEqual(review["changes"]["removed_selections"], self.request["talkgroup_ids"])
        self.assertTrue(review["blockers"])
        with self.assertRaises(ValueError):
            self.library.apply(review)

    def test_profile_edit_revision_and_path_validation(self):
        profile = self.library.save(self.system, self.request)
        request = {**self.request, "profile_id": profile["id"], "revision": 1, "profile_name": "My AARRS"}
        edited = self.library.save(self.system, request)
        self.assertEqual(edited["revision"], 2)
        self.assertEqual(len(self.library.list()), 1)
        with self.assertRaises(ValueError):
            self.library.save(self.system, request)
        with self.assertRaises(ValueError):
            self.library.read("../other")

    def test_generated_name_follows_site_and_custom_name_is_preserved(self):
        profile = self.library.save(self.system, self.request)
        northeast = next(s for s in self.system['sites'] if s['name'] == 'Northeast Simulcast')
        request = {**self.request, 'site_id': northeast['id'], 'profile_id': profile['id'],
                   'revision': profile['revision'], 'profile_name': profile['name']}
        changed = self.library.save(self.system, request)
        self.assertEqual(changed['name'], self.system['name'] + ' / Northeast Simulcast')
        self.assertFalse(changed['name_is_custom'])
        request.update(revision=changed['revision'], profile_name='My receiver')
        custom = self.library.save(self.system, request)
        request.update(revision=custom['revision'], site_id=self.request['site_id'])
        self.assertEqual(self.library.save(self.system, request)['name'], 'My receiver')

    def test_legacy_stale_default_name_is_repaired_on_save(self):
        profile = self.library.save(self.system, self.request)
        profile.pop('name_is_custom')
        northeast = next(s for s in self.system['sites'] if s['name'] == 'Northeast Simulcast')
        profile['settings']['site_id'] = northeast['id']
        self.library.write(profile)
        request = {**self.request, 'site_id': northeast['id'], 'profile_id': profile['id'],
                   'revision': profile['revision'], 'profile_name': profile['name']}
        repaired = self.library.save(self.system, request)
        self.assertEqual(repaired['name'], self.system['name'] + ' / Northeast Simulcast')
        self.assertFalse(repaired['name_is_custom'])


if __name__ == "__main__":
    unittest.main()
