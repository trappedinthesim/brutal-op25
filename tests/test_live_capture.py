"""Regression checks against the real AARRS capture, without more API requests."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from importer import export_setup


class LiveCaptureTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).parent / "live-bexar-system.json").exists(), "Run live validation first")
    def test_real_sites_with_boatbod_parser(self):
        root = Path(__file__).resolve().parent
        system = json.loads((root / "live-bexar-system.json").read_text(encoding="utf-8"))
        app_path = Path(os.environ["OP25_APPS_DIR"]) if os.environ.get("OP25_APPS_DIR") else root.parents[2] / "work/op25-audit/op25/gr-op25_repeater/apps"
        if not app_path.exists():
            self.skipTest("Local boatbod checkout missing")
        sys.path.insert(0, str(app_path))
        try:
            from helper_funcs import read_tsv_file, get_frequency
            for site in system["sites"]:
                if not site["controls_hz"]:
                    continue
                files = export_setup(system, {"hardware": {"profile": "rtl"}, "site_id": site["id"],
                    "source": "radioreference", "talkgroup_ids": [], "selected_only": False})
                with tempfile.TemporaryDirectory() as directory:
                    trunk_path = Path(directory) / "trunk.tsv"
                    trunk_path.write_text(files["trunk.tsv"], encoding="utf-8")
                    parsed = read_tsv_file(str(trunk_path), "nac")
                trunk = parsed[int(site["nac"], 16)]
                self.assertEqual([get_frequency(f) for f in trunk["control_channel_list"].split(',')], site["controls_hz"])
            self.assertEqual(len(system["talkgroups"]), 1009)
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
