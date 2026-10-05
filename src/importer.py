"""RadioReference adapter and boatbod export. No GNU Radio runtime required."""
from decimal import Decimal
from pathlib import Path
import csv
import io
import json
import math
import os
import re
import zipfile
from test_connection import records, controls, frequency_hz, frequency_mhz, clean_label
from rr_key import embedded_key

API_VERSION = "18"
NAMESPACE = "http://api.radioreference.com/soap2"
ENDPOINT = "https://api.radioreference.com/soap2/index.php"
PROFILES = {
    "rtl": {"name": "RTL-SDR (Blog V1-V3 / other non-V4)", "args": "rtl", "rate": 1000000, "gains": "LNA:39",
        "backend": "rtl", "libraries": ["rtlsdr"], "note": "For Blog V1-V3 and other non-V4 RTL-SDRs. The bundled driver is documented as backward-compatible, but these radios have not been hardware-tested here. Choose the separate V4 preset for Blog V4."},
    "rtlv4": {"name": "RTL-SDR Blog V4", "args": "rtl", "rate": 1000000, "gains": "LNA:39",
        "backend": "rtl", "libraries": ["rtlsdr"], "note": "Uses the V4-capable RTL-SDR Blog driver in our image. USB access and reception still need testing."},
    "airspy": {"name": "Airspy R2", "args": "airspy", "rate": 2500000, "gains": "LNA:8,MIX:8,IF:8",
        "selectable": False,
        "backend": "airspy", "libraries": ["airspy"], "note": "R2 preset: 2.5 MSPS. Driver check available; hardware untested."},
    "airspymini": {"name": "Airspy Mini", "args": "airspy", "rate": 3000000, "gains": "LNA:8,MIX:8,IF:8",
        "selectable": False,
        "backend": "airspy", "libraries": ["airspy"], "note": "Mini preset: 3 MSPS. Driver check available; hardware untested."},
    "hackrf": {"name": "HackRF", "args": "hackrf", "rate": 8000000, "gains": "RF:0,IF:16,BB:20",
        "selectable": False,
        "backend": "hackrf", "libraries": ["hackrf"], "note": "Receive only; RF amplifier off. 8 MSPS starting point. Hardware untested."},
    "rspdxr2": {"name": "SDRplay RSPdx-R2", "args": "soapy=0,driver=sdrplay", "rate": 2000000,
        "gains": "IFGR:40,RFGR:0", "backend": "soapy", "libraries": ["SoapySDR", "sdrplay_api"],
        "factory": "sdrplay", "note": "Requires SDRplay API 3.15 and an RSPdx-R2-capable SoapySDRPlay3 plugin in the receiver environment. Not included in the base image; reception untested."},
    "custom": {"name": "Other / custom", "args": "", "rate": 2000000, "gains": "",
        "note": "Enter gr-osmosdr arguments and named integer gains. Compatibility depends on the chosen driver."},
}


def application_key():
    """Deployment configuration, not an end-user question. Shared by the terminal and web importers."""
    key = os.environ.get('BRUTAL_RR_APP_KEY', '').strip()
    if not key:
        try:
            key = Path('/run/secrets/radioreference_app_key').read_text(encoding='utf-8').strip()
        except OSError:
            pass
    if not key:
        key = embedded_key()
    if not key:
        raise ValueError('RadioReference import is not enabled: this installation has no '
                         'configured application key. This is an app setup issue, not your '
                         'password. Saved-system listening and manual setup still work.')
    return key


class RadioReference:
    def __init__(self, username, password, key):
        from requests import Session
        from zeep import Client, Settings
        from zeep.cache import InMemoryCache
        from zeep.transports import Transport
        self.secrets = (username, password, key)
        self.session = Session()
        self.browse_cache = {}
        self.type_names = {}
        try:
            self.client = Client(f"{NAMESPACE.replace('http:', 'https:')}/?wsdl&v={API_VERSION}&s=rpc",
                transport=Transport(session=self.session, cache=InMemoryCache(), timeout=20,
                                    operation_timeout=30), settings=Settings(strict=True))
            self.service = self.client.create_service("{" + NAMESPACE + "}RRWsdlBinding", ENDPOINT)
            self.auth = self.client.get_type("{" + NAMESPACE + "}authInfo")(
                username=username, password=password, appKey=key, version=API_VERSION, style="rpc")
            self.call("getUserData")
        except Exception:
            self.close()
            raise

    def call(self, method, *args):
        from zeep.helpers import serialize_object
        try:
            # getCountryList is the one browsing operation with no authInfo parameter.
            parameters = args if method == "getCountryList" else (*args, self.auth)
            return serialize_object(getattr(self.service, method)(*parameters), target_cls=dict)
        except Exception as exc:
            message = str(exc)
            for secret in self.secrets:
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise ValueError(f"RadioReference {method}: {message}") from None

    def type_name(self, type_id):
        type_id = int(type_id)
        if type_id not in self.type_names:
            rows = records(self.call("getTrsType", type_id), "trsTypeDef")
            self.type_names[type_id] = next((r["sTypeDescr"] for r in rows
                if int(r["sType"]) == type_id), "Unknown")
        return self.type_names[type_id]

    def p25_systems(self, value):
        systems = {}
        for row in records(value, "TrsListDef"):
            type_name = self.type_name(row["sType"])
            if is_p25(type_name):
                sid = int(row["sid"])
                systems[sid] = {"id": sid, "name": clean_label(row["sName"]),
                                "type": type_name, "city": clean_label(row.get("sCity"))}
        return sorted(systems.values(), key=lambda row: (row["name"].casefold(), row["id"]))

    def browse(self, level, value=None):
        if level not in ("countries", "states", "counties", "systems", "zip"):
            raise ValueError("Unknown browsing level")
        if level == "zip":
            text = str(value).strip()
            if not re.fullmatch(r"[0-9]{5}", text):
                raise ValueError("Enter a five-digit US ZIP code")
            value = int(text)
        elif level != "countries":
            value = int(value)
            if value <= 0:
                raise ValueError("Choose a valid location")
        key = (level, value)
        if key in self.browse_cache:
            return self.browse_cache[key]
        if level == "countries":
            rows = records(self.call("getCountryList"), "Country")
            result = {"countries": location_options(rows, "coid", "countryName", "countryCode")}
        elif level == "states":
            info = self.call("getCountryInfo", value)
            result = {"states": location_options(records(info.get("stateList"), "State"),
                                                 "stid", "stateName", "stateCode")}
        elif level == "counties":
            info = self.call("getStateInfo", value)
            result = {"counties": location_options(records(info.get("countyList"), "County"),
                                                    "ctid", "countyName"),
                      "systems": self.p25_systems(info.get("trsList"))}
        elif level == "systems":
            info = self.call("getCountyInfo", value)
            result = {"systems": self.p25_systems(info.get("trsList"))}
        else:
            info = self.call("getZipcodeInfo", value)
            result = {"state_id": int(info["stid"]), "county_id": int(info["ctid"]),
                      "city": clean_label(info.get("city"))}
        # Small, per-login, in-memory cache only. No background database crawling.
        self.browse_cache[key] = result
        return result

    def system(self, system_id):
        detail = self.call("getTrsDetails", system_id)
        if not isinstance(detail, dict) or not detail.get("sName"):
            raise ValueError("RadioReference returned no system details")
        # Type IDs belong to RadioReference; resolve through its catalog rather than guessing.
        type_name = self.type_name(detail["sType"])
        if not is_p25(type_name):
            raise ValueError(f"This first importer supports P25 only. System type: {type_name}")
        sites = records(self.call("getTrsSites", system_id), "TrsSite")
        talkgroups = records(self.call("getTrsTalkgroups", system_id, 0, 0, 0), "Talkgroup")
        return normalize_system(system_id, detail, sites, talkgroups, type_name, self.categories(system_id))

    def categories(self, system_id):
        """Category names (Fire, Police, ...). Optional: a failure here must never block an import."""
        try:
            rows = records(self.call("getTrsTalkgroupCats", int(system_id)), "TalkgroupCat")
        except ValueError:
            return []
        return rows

    def close(self):
        self.session.close()
        self.auth = None
        self.secrets = ()
        self.browse_cache.clear()
        self.type_names.clear()


def is_p25(type_name):
    return bool(re.search(r"\b(?:project\s*25|p25)\b", type_name, re.IGNORECASE))


def location_options(rows, id_key, name_key, code_key=None):
    options = [{"id": int(row[id_key]), "name": clean_label(row[name_key]),
                "code": str(row.get(code_key) or "") if code_key else ""} for row in rows]
    return sorted(options, key=lambda row: (row["name"].casefold(), row["id"]))


def system_id(value):
    value = str(value).strip()
    if value.isdigit() and int(value) > 0:
        return int(value)
    from urllib.parse import urlparse, parse_qs
    url = urlparse(value)
    if url.hostname in ("radioreference.com", "www.radioreference.com"):
        sid = parse_qs(url.query).get("sid", [""])[0]
        path_match = re.fullmatch(r"/db/sid/(\d+)/?", url.path)
        if not sid and path_match:
            sid = path_match.group(1)
        if sid.isdigit() and int(sid) > 0:
            return int(sid)
    raise ValueError("Enter a positive system database ID or a RadioReference system URL")


def nac_value(value):
    text = str(value or "").strip()
    if not text or text.lower() in ("unknown", "n/a"):
        return "0x0"
    try:
        number = int(text.removeprefix("0x").removeprefix("0X"), 16)
    except ValueError:
        raise ValueError("Site NAC is not a valid hexadecimal value") from None
    if not 0 <= number <= 0xFFF:
        raise ValueError("Site NAC must fit 12 bits")
    return hex(number)


def normalize_categories(rows):
    seen = {}
    for row in rows or []:
        try:
            seen[int(row["tgCid"])] = clean_label(row["tgCname"]) or f"Category {int(row['tgCid'])}"
        except (KeyError, TypeError, ValueError):
            continue
    return [{"id": cid, "name": seen[cid]} for cid in sorted(seen, key=lambda c: (seen[c].casefold(), c))]


def normalize_system(sid, details, sites, groups, type_name="P25", categories=None):
    normalized_sites = []
    import_warnings = []
    for site in sites:
        if not isinstance(site, dict):
            import_warnings.append("Skipped a malformed site record.")
            continue
        warnings = []
        try:
            nac = nac_value(site.get("nac"))
        except ValueError:
            nac = "0x0"
            warnings.append("Unrecognized site NAC; OP25 will discover it from the control channel.")
        try:
            site_id = int(site["siteId"])
            frequencies = controls(site)
            if site_id < 1:
                raise ValueError("Invalid site ID")
        except (AttributeError, KeyError, TypeError, ValueError):
            import_warnings.append("Skipped a site with an invalid ID or control-channel frequency.")
            continue
        normalized_sites.append({"id": site_id, "name": clean_label(site.get("siteDescr")) or "Unnamed site",
            "rfss": site.get("rfss"), "site_number": site.get("siteNumber"), "nac": nac,
            "tdma_cc": str(site.get("tdma_cc") or "0") == "1",
            "controls_hz": frequencies, "warnings": warnings})
    seen = {}
    for row in groups:
        # One malformed database row must not discard the whole system. Skip it and say so.
        name = clean_label(row.get("tgAlpha") or row.get("tgDescr") or "") or "(unnamed)"
        try:
            tgid = int(row["tgDec"])
            if not 1 <= tgid <= 65535:
                import_warnings.append(f"Skipped '{name}': P25 talkgroup ID {tgid} is outside 1-65535.")
                continue
            group = {"id": tgid, "label": clean_label(row.get("tgAlpha") or row.get("tgDescr") or str(tgid)),
                "description": clean_label(row.get("tgDescr")), "mode": str(row.get("tgMode") or ""),
                "encryption": int(row.get("enc") or 0), "category_id": row.get("tgCid")}
        except (KeyError, TypeError, ValueError):
            import_warnings.append(f"Skipped '{name}': it has no valid decimal talkgroup ID.")
            continue
        if tgid in seen:
            if seen[tgid] != group:
                # Never silently pick a winner: keep the first (deterministic) and report both.
                import_warnings.append(f"Talkgroup {tgid} appears twice with different details; kept "
                                       f"'{seen[tgid]['label']}' and ignored '{group['label']}'.")
            continue
        seen[tgid] = group
    result = {"id": int(sid), "name": clean_label(details["sName"]), "type": type_name,
              "sites": normalized_sites, "talkgroups": [seen[k] for k in sorted(seen)]}
    cats = normalize_categories(categories)
    if cats:
        result["categories"] = cats
    if import_warnings:
        result["import_warnings"] = import_warnings
    return result


MAX_RID = 0xFFFFFF  # P25 unit IDs are 24-bit
PRIORITY_HIGH = 1   # OP25 prefers the lower number; unlisted talkgroups default to 3
DEFAULT_CRYPT_BEHAVIOR = 2  # 2 = skip encrypted talkgroups entirely; 1 = OP25's own default (do not skip)


def tuning_options(system, request):
    """Validate the listening preferences saved with a system: priority, blocked, radio names, ..."""
    known = {g["id"] for g in system["talkgroups"]}

    def talkgroups(key):
        try:
            values = {int(v) for v in request.get(key) or []}
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a list of talkgroup numbers") from None
        if not values <= known:
            raise ValueError(f"{key}: some talkgroups do not belong to this system")
        return values

    priority, blocked = talkgroups("priority_tgids"), talkgroups("blocked_tgids")
    if priority & blocked:
        raise ValueError("A talkgroup cannot be both Priority and Blocked")
    selected = {int(i) for i in request.get("talkgroup_ids", [])}
    if request.get("selected_only") and blocked & selected:
        raise ValueError("A blocked talkgroup cannot also be in the listen-only list")
    labels = request.get("rid_labels") or {}
    if not isinstance(labels, dict) or len(labels) > 5000:
        raise ValueError("Radio names must be a list of at most 5000 entries")
    rid_labels = {}
    for raw_id, raw_label in labels.items():
        try:
            rid = int(raw_id)
        except (TypeError, ValueError):
            raise ValueError(f"Radio ID {raw_id!r} is not a number") from None
        if not 1 <= rid <= MAX_RID:
            raise ValueError(f"Radio ID {rid} is outside 1-{MAX_RID}")
        label = clean_label(raw_label)
        if len(label) > 40:
            raise ValueError("Radio names can be at most 40 characters")
        if label:
            rid_labels[rid] = label
    try:
        crypt = int(request.get("crypt_behavior", DEFAULT_CRYPT_BEHAVIOR))
    except (TypeError, ValueError):
        raise ValueError("Encrypted-call behavior must be 1 or 2") from None
    if crypt not in (1, 2):
        raise ValueError("Encrypted-call behavior must be 1 or 2")
    hold = request.get("hold_time")
    if hold is not None:
        try:
            hold = float(hold)
        except (TypeError, ValueError):
            raise ValueError("Hold time must be a number of seconds") from None
        if not math.isfinite(hold) or not 0 <= hold <= 30:
            raise ValueError("Hold time must be between 0 and 30 seconds")
    return {"priority": priority, "blocked": blocked, "rid_labels": rid_labels,
            "crypt_behavior": crypt, "hold_time": hold}


def export_setup(system, request):
    hardware = request["hardware"]
    profile = PROFILES.get(hardware.get("profile"))
    if not profile:
        raise ValueError("Select a supported hardware profile")
    args = str(hardware.get("args") or profile["args"]).strip()
    if not args or any(c in args for c in "\r\n\x00"):
        raise ValueError("Provide valid gr-osmosdr device arguments")
    rate = int(hardware.get("rate", profile["rate"]))
    ppm = float(hardware.get("ppm", 0))
    gain = str(hardware.get("gains", profile["gains"]))
    if not gain.strip():
        raise ValueError("Enter named integer gains (for example LNA:39). Blank gains crash this upstream OP25 receiver path.")
    stages = [part.strip() for part in gain.split(",")]
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*:-?[0-9]+", part) for part in stages):
        raise ValueError("Gains must be comma-separated NAME:integer entries supported by the selected driver")
    if len({part.split(":")[0] for part in stages}) != len(stages):
        raise ValueError("Duplicate gain stages")
    gain = ",".join(stages)
    if not 24000 <= rate <= 20000000 or not math.isfinite(ppm) or abs(ppm) > 1000:
        raise ValueError("Invalid sample rate or PPM correction")
    site = next((s for s in system["sites"] if s["id"] == int(request["site_id"])), None)
    if site is None or not site["controls_hz"]:
        raise ValueError("Select a site with marked control channels")
    selected = {int(i) for i in request.get("talkgroup_ids", [])}
    known = {g["id"] for g in system["talkgroups"]}
    if not selected <= known:
        raise ValueError("Selected talkgroups do not belong to this system")
    if request.get("selected_only", False) and not selected:
        raise ValueError("Select at least one talkgroup or allow all talkgroups")
    tuning = tuning_options(system, request)
    name = clean_label(system["name"] + " / " + site["name"])
    cfg = {
        "devices": [{"name": "sdr0", "args": args, "rate": rate, "frequency": site["controls_hz"][0],
                     "gains": gain, "gain_mode": not bool(gain), "ppm": ppm,
                     "offset": 0, "usable_bw_pct": 0.85, "tunable": True}],
        "channels": [{"name": "Receiver 1", "device": "sdr0", "trunking_sysname": name,
                      "frequency": site["controls_hz"][0], "demod_type": request.get("demod", "cqpsk"),
                      "cqpsk_tracking": True, "excess_bw": 0.2, "filter_type": "rc", "if_rate": 24000,
                      "symbol_rate": 4800, "destination": "ws://127.0.0.1:9000",
                      "crypt_behavior": tuning["crypt_behavior"]}],
        "trunking": {"module": "tk_p25.py", "chans": [{"sysname": name, "nac": site["nac"],
                    "control_channel_list": ",".join(frequency_mhz(f) for f in site["controls_hz"]),
                    "tdma_cc": site["tdma_cc"], "tgid_tags_file": "talkgroups.tsv",
                    "whitelist": "whitelist.tsv" if request.get("selected_only") else "",
                    "blacklist": "blacklist.tsv" if tuning["blocked"] else "",
                    "crypt_behavior": tuning["crypt_behavior"]}]},
        "terminal": {"module": "terminal.py", "terminal_type": "http:127.0.0.1:8080",
                     "http_plot_interval": 1.0, "http_plot_directory": "../www/images"}}
    if cfg["channels"][0]["demod_type"] not in ("cqpsk", "fsk4"):
        raise ValueError("Unsupported demodulator")
    trunk_chan = cfg["trunking"]["chans"][0]
    if tuning["hold_time"] is not None:
        trunk_chan["tgid_hold_time"] = tuning["hold_time"]
    if tuning["rid_labels"]:
        trunk_chan["rid_tags_file"] = "rid_tags.tsv"
    tags = io.StringIO(newline="")
    writer = csv.writer(tags, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    for group in system["talkgroups"]:
        # A third column is OP25's priority; rows without one stay at its default.
        writer.writerow([group["id"], group["label"]] + ([PRIORITY_HIGH] if group["id"] in tuning["priority"] else []))
    readme = ("Generated for boatbod OP25 multi_rx.py (GNU Radio 3.10).\n"
        "Extract these files together into op25/gr-op25_repeater/apps/.\n"
        "From that directory run: python3 multi_rx.py -c config.json\n"
        "Open http://127.0.0.1:8080 and enable browser audio (WebSocket port 9000).\n"
        "Hardware profiles are presets, not proof of detected hardware or working drivers.\n"
        "Verify sample rate/gains on your receiver host before use.\n"
        + profile.get("note", "") + "\n"
        +
        "Unknown NAC is 0x0 (automatic discovery). Encrypted audio is silenced.\n")
    if request.get("source") == "fictional-demo":
        readme = "FICTIONAL DEMO ONLY: not a real listening configuration.\n\n" + readme
    manifest = {"source": request.get("source", "radioreference"), "system_id": system["id"],
                "site_id": site["id"], "name": name, "controls_hz": site["controls_hz"],
                "selected_talkgroups": sorted(selected), "hardware_verified": False,
                "priority_talkgroups": sorted(tuning["priority"]), "blocked_talkgroups": sorted(tuning["blocked"]),
                "radio_names": len(tuning["rid_labels"]),
                "warnings": site["warnings"], "api_version": API_VERSION}
    files = {"config.json": json.dumps(cfg, indent=2), "talkgroups.tsv": tags.getvalue(),
             "whitelist.tsv": "".join(f"{i}\n" for i in sorted(selected)),
             "import-info.json": json.dumps(manifest, indent=2), "README.txt": readme}
    if tuning["blocked"]:
        files["blacklist.tsv"] = "".join(f"{i}\n" for i in sorted(tuning["blocked"]))
    if tuning["rid_labels"]:
        rid_rows = io.StringIO(newline="")
        rid_writer = csv.writer(rid_rows, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        for rid in sorted(tuning["rid_labels"]):
            rid_writer.writerow([rid, tuning["rid_labels"][rid]])
        files["rid_tags.tsv"] = rid_rows.getvalue()
    files["talkgroup-info.json"] = json.dumps({"system_id": system["id"],
        "talkgroups": system["talkgroups"]}, indent=2)
    legacy = io.StringIO(newline="")
    writer = csv.writer(legacy, delimiter="\t", quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(["Sysname", "Control Channel List", "Offset", "NAC", "Modulation",
                     "TGID Tags File", "Whitelist", "Blacklist", "Center Frequency"])
    writer.writerow([name, cfg["trunking"]["chans"][0]["control_channel_list"], "0", site["nac"],
                     cfg["channels"][0]["demod_type"], "talkgroups.tsv",
                     "whitelist.tsv" if request.get("selected_only") else "",
                     "blacklist.tsv" if tuning["blocked"] else "", ""])
    files["trunk.tsv"] = legacy.getvalue()
    return files


def zip_files(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def demo_system():
    return normalize_system(0, {"sName": "Demo County P25 (fictional)"}, [
        {"siteId": 1, "siteDescr": "Central simulcast", "nac": "293", "rfss": 1, "siteNumber": 1,
         "siteFreqs": [{"freq": "773.84375", "use": "d"}, {"freq": "774.19375", "use": "a"}]},
        {"siteId": 2, "siteDescr": "North tower", "nac": "294", "rfss": 1, "siteNumber": 2,
         "siteFreqs": [{"freq": "851.0125", "use": "d"}]}], [
        {"tgDec": 101, "tgAlpha": "Fire Dispatch", "tgDescr": "County fire dispatch", "enc": 0, "tgMode": "D"},
        {"tgDec": 102, "tgAlpha": "EMS Dispatch", "tgDescr": "Emergency medical services", "enc": 0, "tgMode": "T"},
        {"tgDec": 201, "tgAlpha": "Police Dispatch", "tgDescr": "Mixed encryption", "enc": 1, "tgMode": "T"},
        {"tgDec": 202, "tgAlpha": "Police Tactical", "tgDescr": "Fully encrypted", "enc": 2, "tgMode": "T"},
        {"tgDec": 301, "tgAlpha": "Public Works", "tgDescr": "Road maintenance", "enc": 0, "tgMode": "D"}])
