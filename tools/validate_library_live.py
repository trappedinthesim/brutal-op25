"""Read-only live RR validation plus temporary library operations.

Run from the repo root with `python -m tools.validate_library_live`.
No user profiles are altered.
"""
from getpass import getpass
from pathlib import Path
from datetime import datetime, timezone
import io
import json
import tempfile
import zipfile
from importer import RadioReference
from library import ProfileLibrary


def main():
    rr = RadioReference(input("RadioReference username: "), getpass("RadioReference password: "),
                        getpass("Approved application key: ").strip())
    try:
        systems = [rr.system(7017), rr.system(10441)]
        with tempfile.TemporaryDirectory() as directory:
            library = ProfileLibrary(directory)
            profiles = []
            for system in systems:
                site = next(s for s in system["sites"] if s["controls_hz"])
                profiles.append(library.save(system, {"hardware": {"profile": "rtl"},
                    "source": "radioreference", "site_id": site["id"], "talkgroup_ids": [], "selected_only": False}))
                print(f"Live import: {system['name']} / {len(system['talkgroups'])} talkgroups", flush=True)
            archive = library.export([p["id"] for p in profiles])
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                for profile in profiles:
                    saved = json.loads(bundle.read(profile["id"] + "/talkgroup-info.json"))
                    assert saved["system_id"] == profile["system"]["id"]
                    assert len(saved["talkgroups"]) == len(profile["system"]["talkgroups"])
            fresh = rr.system(7017)
            review = library.review(profiles[0]["id"], fresh)
            updated = library.apply(review)
            assert updated["settings"] == profiles[0]["settings"]
            report = {"validated_at": datetime.now(timezone.utc).isoformat(), "live": True,
                "systems": [{"id": s["id"], "name": s["name"], "sites": len(s["sites"]),
                    "talkgroups": len(s["talkgroups"])} for s in systems],
                "separate_profile_export": True, "live_refresh_review_and_apply": True,
                "changes": {k: len(v) if isinstance(v, list) else v for k, v in review["changes"].items()},
                "settings_preserved": True, "user_profiles_modified": False,
                "receiver_deployment_tested": False, "hardware_verified": False}
            (Path(__file__).resolve().parents[1] / "live-library-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print("Separate multi-system export and real refresh succeeded in temporary library.", flush=True)
    finally:
        rr.close()


if __name__ == "__main__":
    main()
