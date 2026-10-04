"""Persistent, credential-free profiles and review-before-apply refreshes."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import threading
import uuid
from importer import export_setup, zip_files


def now():
    return datetime.now(timezone.utc).isoformat()


class ProfileLibrary:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.unreadable = []  # File names skipped by the most recent list() call.

    def path(self, identity):
        if not re.fullmatch(r"[0-9a-f]{32}", str(identity)):
            raise ValueError("Invalid profile ID")
        return self.root / (identity + ".json")

    @staticmethod
    def validate(profile, identity):
        """Reject damaged profile metadata before it can become a filesystem path."""
        if not isinstance(profile, dict) or profile.get("id") != identity:
            raise ValueError("Saved profile is damaged: ID mismatch")
        revision = profile.get("revision")
        if type(revision) is not int or revision < 1:
            raise ValueError("Saved profile is damaged: invalid revision")
        if (not isinstance(profile.get("name"), str) or not profile["name"]
                or not isinstance(profile.get("settings"), dict)
                or not isinstance(profile.get("system"), dict)):
            raise ValueError("Saved profile is damaged: invalid contents")
        settings, system = profile["settings"], profile["system"]
        if (not isinstance(settings.get("hardware"), dict)
                or not isinstance(settings.get("site_id"), int)
                or not isinstance(system.get("name"), str)
                or not isinstance(system.get("sites"), list)
                or not isinstance(system.get("talkgroups"), list)):
            raise ValueError("Saved profile is damaged: incomplete system or radio settings")
        return profile

    def read(self, identity):
        with self.lock:
            try:
                return self.validate(json.loads(self.path(identity).read_text(encoding="utf-8")), identity)
            except FileNotFoundError:
                raise ValueError("Saved profile not found") from None
            except json.JSONDecodeError:
                raise ValueError("Saved profile is damaged: invalid JSON") from None

    def list(self):
        """Readable profiles only. A damaged file is skipped and named in self.unreadable
        so one bad profile cannot hide every other saved system."""
        with self.lock:
            self.unreadable = []
            if not self.root.exists():
                return []
            profiles = []
            for path in sorted(self.root.glob("*.json")):
                if not re.fullmatch(r"[0-9a-f]{32}\.json", path.name):
                    continue
                try:
                    profile = self.validate(json.loads(path.read_text(encoding="utf-8")), path.stem)
                except (OSError, ValueError):
                    self.unreadable.append(path.name)
                    continue
                profiles.append(profile)
            return sorted(profiles, key=lambda p: str(p["name"]).casefold())

    def write(self, profile):
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.path(profile["id"])
            if path.exists():
                previous = self.read(profile["id"])
                history = self.root / "history"
                history.mkdir(exist_ok=True)
                backup = history / f"{profile['id']}-r{previous['revision']}.json"
                if not backup.exists():
                    backup.write_text(json.dumps(previous, indent=2), encoding="utf-8")
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(profile, indent=2), encoding="utf-8")
            os.replace(temp, path)
        return profile

    def remove(self, identity):
        """Take a system out of the list. The file is archived, never deleted, so it is recoverable."""
        with self.lock:
            profile = self.read(identity)
            archive = self.root / "history" / "removed"
            archive.mkdir(parents=True, exist_ok=True)
            os.replace(self.path(identity), archive / f"{identity}-r{profile['revision']}.json")
            return profile

    @staticmethod
    def tuning_settings(request):
        """Listening preferences kept with a system. Only keys present in the request are carried, so
        older saved systems and plain saves stay exactly as they were; export_setup validates the values."""
        settings = {}
        try:
            for key in ("blocked_tgids", "priority_tgids"):
                if key in request:
                    settings[key] = sorted({int(v) for v in request[key] or []})
            if "rid_labels" in request:
                settings["rid_labels"] = {str(int(k)): str(v) for k, v in dict(request["rid_labels"] or {}).items()}
            if request.get("crypt_behavior") is not None:
                settings["crypt_behavior"] = int(request["crypt_behavior"])
            if request.get("hold_time") is not None:
                settings["hold_time"] = float(request["hold_time"])
        except (TypeError, ValueError):
            raise ValueError("Listening preferences contain a value that is not a number") from None
        return settings

    def save(self, system, request):
        hardware = {key: request["hardware"][key] for key in
                    ("profile", "args", "rate", "gains", "ppm") if key in request["hardware"]}
        settings = {"hardware": hardware, "site_id": int(request["site_id"]),
            "talkgroup_ids": sorted({int(v) for v in request.get("talkgroup_ids", [])}),
            "selected_only": bool(request.get("selected_only")),
            "demod": request.get("demod", "cqpsk"), "source": request["source"]}
        settings.update(self.tuning_settings(request))
        export_setup(system, settings)  # Validate before persisting anything.
        site = next(s for s in system["sites"] if s["id"] == settings["site_id"])
        default_name = f"{system['name']} / {site['name']}"
        with self.lock:
            old = self.read(request["profile_id"]) if request.get("profile_id") else None
            if old and (old["system"]["id"] != system["id"] or old["revision"] != request.get("revision")):
                raise ValueError("Profile changed or belongs to another system; reopen it first")
            requested_name = str(request.get("profile_name") or "").strip()
            if "name_is_custom" in request:
                if not isinstance(request["name_is_custom"], bool):
                    raise ValueError("Invalid profile name mode")
                custom = request["name_is_custom"]
            elif old and (not requested_name or requested_name == old["name"]):
                # Legacy profiles may have kept another site's generated name.
                defaults = {f"{old['system']['name']} / {s['name']}" for s in old["system"]["sites"]}
                custom = old.get("name_is_custom", old["name"] not in defaults)
            else:
                custom = bool(requested_name and requested_name != default_name)
            name = (requested_name or (old["name"] if old else "")) if custom else default_name
            if not name or len(name) > 200:
                raise ValueError("Profile name must be 1–200 characters")
            return self.write({"id": old["id"] if old else uuid.uuid4().hex,
                "revision": old["revision"] + 1 if old else 1, "name": name, "name_is_custom": custom,
                "created_at": old["created_at"] if old else now(), "updated_at": now(),
                "settings": settings, "system": deepcopy(system)})

    def clone_for_hardware(self, identity, hardware):
        """Create a separate receiver profile without re-importing or changing the original."""
        with self.lock:
            original = self.read(identity)
            if hardware.get("profile") == original["settings"]["hardware"].get("profile"):
                raise ValueError("That saved system already uses this SDR type. Choose a different radio.")
            existing = self.find_hardware_clone(identity, hardware)
            if existing:
                return existing
            request = deepcopy(original["settings"])
            request["hardware"] = deepcopy(hardware)
            request["profile_name"] = original["name"]
            request["name_is_custom"] = original.get("name_is_custom", False)
            return self.save(original["system"], request)

    def find_hardware_clone(self, identity, hardware):
        """Reuse an equivalent radio setup instead of accumulating failed-attempt copies."""
        with self.lock:
            original = self.read(identity)
            expected = deepcopy(original["settings"])
            expected["hardware"] = deepcopy(hardware)
            matches = [profile for profile in self.list()
                       if profile["id"] != identity
                       and profile["system"] == original["system"]
                       and profile["settings"] == expected]
            return max(matches, key=lambda p: (p.get("updated_at", ""), p["id"])) if matches else None

    def review(self, identity, fresh):
        profile = self.read(identity)
        if profile["system"]["id"] != fresh["id"]:
            raise ValueError("Update belongs to a different system")
        old = {g["id"]: g for g in profile["system"]["talkgroups"]}
        new = {g["id"]: g for g in fresh["talkgroups"]}
        added = [new[i] for i in sorted(new.keys() - old.keys())]
        removed = [old[i] for i in sorted(old.keys() - new.keys())]
        changed = [{"id": i, "before": old[i], "after": new[i]}
                   for i in sorted(old.keys() & new.keys()) if old[i] != new[i]]
        settings = deepcopy(profile["settings"])
        missing = sorted(set(settings["talkgroup_ids"]) - new.keys())
        settings["talkgroup_ids"] = sorted(set(settings["talkgroup_ids"]) & new.keys())
        for key in ("priority_tgids", "blocked_tgids"):  # a talkgroup RadioReference dropped cannot stay marked
            if key in settings:
                settings[key] = sorted(set(settings[key]) & new.keys())
        blockers = []
        try:
            export_setup(fresh, settings)
        except ValueError as exc:
            blockers.append(str(exc))
        return {"profile_id": identity, "revision": profile["revision"], "checked_at": now(),
            "system": deepcopy(fresh), "settings": settings,
            "changes": {"added": added, "removed": removed, "changed": changed,
                "sites_changed": profile["system"]["sites"] != fresh["sites"],
                "system_name_changed": profile["system"]["name"] != fresh["name"],
                "removed_selections": missing}, "blockers": blockers}

    def apply(self, review):
        with self.lock:
            profile = self.read(review["profile_id"])
            if profile["revision"] != review["revision"]:
                raise ValueError("Profile changed since this preview. Check updates again.")
            if review["blockers"]:
                raise ValueError("Update cannot be applied: " + "; ".join(review["blockers"]))
            export_setup(review["system"], review["settings"])
            profile.update(system=review["system"], settings=review["settings"],
                           updated_at=now(), revision=profile["revision"] + 1)
            return self.write(profile)

    def export(self, identities):
        if not identities:
            raise ValueError("Select at least one saved profile")
        files = {}
        with self.lock:
            for identity in dict.fromkeys(identities):
                profile = self.read(identity)
                bundle = export_setup(profile["system"], profile["settings"])
                bundle["saved-profile.json"] = json.dumps(profile, indent=2)
                for name, content in bundle.items():
                    files[f"{identity}/{name}"] = content
        files["README.txt"] = ("Saved OP25 profile library. Each folder is a separate system/site setup.\n"
            "Talkgroup IDs and file names are isolated by profile; nothing is merged across systems.\n"
            "Select ONE folder and follow its README to deploy it into boatbod apps/.\n"
            "This ZIP does not configure simultaneous monitoring or cross-system scanning.\n"
            "Using multiple receivers simultaneously needs a separate hardware/channel plan.\n"
            "Keep the local manager to check database updates after installation.\n"
            "Applying updates here does not overwrite files on a running receiver.\n")
        return zip_files(files)
