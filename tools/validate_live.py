"""Interactive live validation. Run from the repo root with `python -m tools.validate_live`.

Never saves credentials or SOAP envelopes.
"""
from getpass import getpass
from pathlib import Path
import json
from importer import RadioReference, export_setup, zip_files


def main():
    username = input("RadioReference username: ")
    password = getpass("RadioReference password: ")
    key = getpass("Approved application key: ").strip()
    rr = None
    try:
        rr = RadioReference(username, password, key)
        key = ""
        password = ""
        print("Authenticated against live API v18", flush=True)
        countries = rr.browse("countries")["countries"]
        us = next(row for row in countries if row["code"].upper() == "US")
        states = rr.browse("states", us["id"])["states"]
        texas = next(row for row in states if row["name"].lower() == "texas")
        state = rr.browse("counties", texas["id"])
        county = next(row for row in state["counties"] if row["name"].lower() in ("bexar", "bexar county"))
        local = rr.browse("systems", county["id"])["systems"]
        print(f"LIVE Texas / {county['name']} P25 systems:", flush=True)
        for row in local:
            print(f"  {row['id']}: {row['name']} [{row['type']}]", flush=True)
        sid = int(input("System ID to validate from this list: "))
        if sid not in {row["id"] for row in local}:
            raise ValueError("Choose a system from the live Bexar list")
        system = rr.system(sid)
        print(f"LIVE {system['name']}: {len(system['sites'])} sites; {len(system['talkgroups'])} talkgroups", flush=True)
        for site in system["sites"]:
            print(f"  Site {site['id']}: {site['name']} / {site['controls_hz']} Hz / NAC {site['nac']}", flush=True)
        site = next(site for site in system["sites"] if site["controls_hz"])
        files = export_setup(system, {"source": "radioreference", "hardware": {"profile": "rtl"},
            "site_id": site["id"], "selected_only": False, "talkgroup_ids": [], "demod": "cqpsk"})
        report = {"live": True, "api_version": "18", "location": "Texas / Bexar County",
            "country_id": us["id"], "state_id": texas["id"], "county_id": county["id"],
            "available_p25_systems": local, "system_id": sid, "system_name": system["name"],
            "site_count": len(system["sites"]), "talkgroup_count": len(system["talkgroups"]),
            "formatting_test_site": site, "hardware_verified": False,
            "note": "First importable site used for export-format validation only, not a recommended receiver site."}
        root = Path(__file__).resolve().parents[1]
        (root / "live-bexar-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (root / "tests/live-bexar-system.json").write_text(json.dumps(system, indent=2), encoding="utf-8")
        (root / "live-bexar-format-check.zip").write_bytes(zip_files(files))
        print("Live import and formatting export succeeded. Hardware/reception not tested.", flush=True)
    finally:
        password = ""
        if rr:
            rr.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # No traceback, request body, authentication values, or diagnostic HTTP logging.
        print(f"Validation failed: {exc}")
        raise SystemExit(1)
