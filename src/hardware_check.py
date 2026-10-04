"""Receiver-environment checks only; never tune hardware or claim reception."""
import ctypes
import ctypes.util
import json
from pathlib import Path
import re
import subprocess
import sys
from importer import PROFILES


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=12)
        return result.returncode, result.stdout + result.stderr
    except (OSError, subprocess.TimeoutExpired) as error:
        return -1, str(error)


def runtime_inventory():
    # File backend avoids opening a physical radio or changing its configuration.
    code, output = command([sys.executable, "-c", "import osmosdr; osmosdr.source('file=/dev/null,rate=1000000')"])
    match = re.search(r"built-in source types:\s*([^\r\n]+)", output)
    backends = match.group(1).split() if match and code == 0 else []
    libraries = {}
    for name in {lib for profile in PROFILES.values() for lib in profile.get("libraries", [])}:
        library = ctypes.util.find_library(name)
        loaded = False
        if library:
            try:
                ctypes.CDLL(library)
                loaded = True
            except OSError:
                pass
        libraries[name] = {"library": library, "loadable": loaded}
    _, info = command(["SoapySDRUtil", "--info"])
    match = re.search(r"Available factories\.*\s*([^\r\n]+)", info)
    factories = [value.strip() for value in match.group(1).split(",")
                 if re.fullmatch(r"[A-Za-z0-9_]+", value.strip())] if match else []
    # Confirm the runtime loader uses our installed driver, not the older apt copy.
    maps = Path("/proc/self/maps")
    rtl_paths = sorted({line.split()[-1] for line in maps.read_text().splitlines()
                        if "/librtlsdr.so" in line}) if maps.exists() else []
    return {"backends": backends, "libraries": libraries, "soapy_factories": factories,
            "rtl_library_paths": rtl_paths, "rtl_blog_source_present": Path("/opt/rtl-sdr-blog/src/librtlsdr.c").exists()}


def check_profile(identity, inventory=None):
    if identity not in PROFILES:
        raise ValueError("Unknown hardware profile")
    profile = PROFILES[identity]
    inventory = inventory if inventory is not None else runtime_inventory()
    missing = []
    backend = profile.get("backend")
    if not backend:
        missing.append("Custom arguments require a device-specific driver check")
    elif backend not in inventory["backends"]:
        missing.append(f"gr-osmosdr {backend} backend")
    for library in profile.get("libraries", []):
        if not inventory["libraries"].get(library, {}).get("loadable"):
            missing.append(f"{library} runtime library")
    if profile.get("factory") and profile["factory"] not in inventory["soapy_factories"]:
        missing.append(f"SoapySDR {profile['factory']} plugin (RSPdx-R2-capable build required)")
    if identity == "rtlv4" and not (inventory["rtl_blog_source_present"] and
            any(p.startswith("/usr/local/") for p in inventory["rtl_library_paths"])):
        missing.append("Verified RTL-SDR Blog V4 driver provenance; an external driver must be checked separately")
    return {"profile": identity, "name": profile["name"], "backend": backend,
            "software_dependencies_present": not missing, "missing": missing,
            "hardware_verified": False, "inventory": inventory,
            "note": "Software check only: USB visibility, device model, rates/gains, signal lock and audio are not tested."}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PROFILES, nargs="?")
    args = parser.parse_args()
    inventory = runtime_inventory()
    print(json.dumps(check_profile(args.profile, inventory) if args.profile else
                     [check_profile(p, inventory) for p in PROFILES], indent=2))
