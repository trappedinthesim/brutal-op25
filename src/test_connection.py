"""Interactive, read-only RadioReference check. Credentials never leave memory."""
from decimal import Decimal
from getpass import getpass
import json
from pathlib import Path
import sys

NAMESPACE = "http://api.radioreference.com/soap2"
ENDPOINT = "https://api.radioreference.com/soap2/index.php"
# Match the explicit RPC contract used by the existing importer.
WSDL = "https://api.radioreference.com/soap2/?wsdl&v=15&s=rpc"


def frequency_hz(mhz):
    try:
        value = Decimal(str(mhz).strip()) * 1000000
    except ArithmeticError:  # InvalidOperation and Overflow both land here
        raise ValueError("Enter each control channel in MHz, for example 851.0125") from None
    if not value.is_finite() or value <= 0 or value != value.to_integral_value():
        raise ValueError("Frequency must represent a positive whole number of Hz")
    return int(value)


def frequency_mhz(hz):
    return format(Decimal(hz) / 1000000, ".6f")


def records(value, item_key=None):
    """Accept Zeep's usual array and an explicit serialized array wrapper."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        if "_value_1" in value:
            return records(value["_value_1"])
        if item_key in value:
            return records(value[item_key])
        if len(value) == 1:
            inner = next(iter(value.values()))
            if isinstance(inner, (list, tuple)):
                return list(inner)
        return [value]
    raise ValueError("Unexpected response array shape: " + type(value).__name__)


def controls(site):
    primary, alternate = [], []
    for row in records(site.get("siteFreqs"), "TrsSiteFreq"):
        role = str(row.get("use") or "").lower().strip()
        if role not in ("d", "a"):
            continue
        hz = frequency_hz(row["freq"])
        target = primary if role == "d" else alternate
        if hz not in target:
            target.append(hz)
    return list(dict.fromkeys(primary + alternate))


def clean_label(value):
    return " ".join(str(value or "").split())


def main():
    from requests import Session
    from zeep import Client, Settings
    from zeep.cache import InMemoryCache
    from zeep.helpers import serialize_object
    from zeep.transports import Transport

    print("RadioReference LIVE read-only test")
    print("Use your own approved application key and Premium account.")
    print("Passwords/key are hidden. No credentials or raw responses are saved.\n")
    username = input("RadioReference username: ").strip()
    password = getpass("RadioReference password: ")
    app_key = getpass("Approved application key: ").strip()
    system_id = int(input("RadioReference system database ID (sid in its URL): ").strip())
    if not username or not password or not app_key or system_id <= 0:
        raise ValueError("Username, password, application key, and positive system ID are required")

    report = {"mode": "live-read-only", "system_database_id": system_id,
              "key_source": "user-supplied",
              "zeep_version": __import__("zeep").__version__, "checks": []}
    secrets = (password, app_key, username)

    def redact(message):
        for secret in secrets:
            if secret:
                message = message.replace(secret, "[redacted]")
        return message

    stage = "WSDL initialization"
    session = Session()
    try:
        client = Client(WSDL, transport=Transport(session=session, cache=InMemoryCache(),
                        timeout=20, operation_timeout=30), settings=Settings(strict=True))
        # Override the HTTP address advertised by the WSDL. TLS verification stays enabled.
        service = client.create_service("{" + NAMESPACE + "}RRWsdlBinding", ENDPOINT)
        auth = client.get_type("{" + NAMESPACE + "}authInfo")(
            username=username, password=password, appKey=app_key, version="15", style="rpc")
        report["checks"].append({"stage": stage, "passed": True})

        def call(name, *args):
            nonlocal stage
            stage = name
            print("Checking " + name + "...", flush=True)
            result = serialize_object(getattr(service, name)(*args, auth), target_cls=dict)
            report["checks"].append({"stage": name, "passed": True})
            return result

        # No separate login token: each API operation carries the user's authInfo.
        details = call("getTrsDetails", system_id)
        if not isinstance(details, dict) or not details.get("sName"):
            raise ValueError("System details response has no system name")
        report["system_name"] = details["sName"]
        report["system_type_id"] = details.get("sType")
        print("System: " + str(details["sName"]))
        sites = records(call("getTrsSites", system_id), "TrsSite")
        report["site_count"] = len(sites)
        if not sites:
            raise ValueError("No sites returned for this system")
        for site in sites:
            print(f"  {site['siteId']}: {site.get('siteDescr') or '(unnamed)'}")
        site_id = int(input("Choose the exact site database ID above: ").strip())
        matches = [s for s in sites if int(s["siteId"]) == site_id]
        if len(matches) != 1:
            raise ValueError("Site ID did not match exactly one returned site")
        site = matches[0]
        stage = "frequency normalization"
        hz_list = controls(site)
        if not hz_list:
            raise ValueError("Site has no marked primary/alternate controls; manual selection is required")
        cc_list = ",".join(frequency_mhz(hz) for hz in hz_list)
        report.update(site_database_id=site_id, site_name=site.get("siteDescr"),
                      control_channels_hz=hz_list, control_channel_list=cc_list,
                      site_nac=site.get("nac"), tdma_cc=site.get("tdma_cc"))
        report["checks"].append({"stage": stage, "passed": True})
        print("Control channels (MHz): " + cc_list)

        talkgroups = records(call("getTrsTalkgroups", system_id, 0, 0, 0), "Talkgroup")
        stage = "talkgroup normalization"
        tags = {}
        encrypted = 0
        for row in talkgroups:
            tgid = int(row["tgDec"])
            if tgid <= 0:
                raise ValueError("Non-positive decimal talkgroup ID")
            label = clean_label(row.get("tgAlpha") or row.get("tgDescr") or str(tgid))
            if tgid in tags and tags[tgid] != label:
                raise ValueError(f"Conflicting labels returned for talkgroup {tgid}")
            tags[tgid] = label
            if int(row.get("enc") or 0) != 0:
                encrypted += 1
        report.update(talkgroup_count=len(talkgroups), unique_talkgroup_count=len(tags),
                      encryption_flagged_count=encrypted)
        report["checks"].append({"stage": stage, "passed": True})
        print(f"Talkgroups: {len(tags)} unique; {encrypted} entries have an encryption flag")
        print("TSV preview (first five; all encryption modes retained for later selection):")
        for tgid in sorted(tags)[:5]:
            print(f"  {tgid}\t{tags[tgid]}")
        report["passed"] = True
        print("\nLIVE CHECK PASSED. No OP25 files were changed.")
    except Exception as exc:
        report["passed"] = False
        report["checks"].append({"stage": stage, "passed": False,
            "error_type": type(exc).__name__, "message": redact(str(exc))})
        print("\nFAILED at " + stage + ": " + type(exc).__name__ + ": " + redact(str(exc)))
    finally:
        session.close()
        output = Path(__file__).with_name("connection-report.json")
        # Use a separate report per attempt; never overwrite a prior diagnostic.
        import datetime
        output = output.with_name("connection-report-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
        output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print("Sanitized report: " + str(output))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(130)
    except Exception as exc:
        print("Unable to start: " + type(exc).__name__)
        sys.exit(1)
