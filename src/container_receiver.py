"""Explicit deployment CLI. Does not expose Docker control to the web manager."""
import argparse
import csv
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
from brutal_ui import apply_branding
from brutal_runtime import patch_runtime_apps
from library import ProfileLibrary
from importer import export_setup

PREPARED_FORMAT = 3


def prepare(data_root, identity):
    root = Path(data_root).resolve()
    library = ProfileLibrary(root / "saved-profiles")
    profile = library.read(identity)
    destination = root / "receiver" / f"{identity}-r{profile['revision']}-v{PREPARED_FORMAT}"
    files = export_setup(profile["system"], profile["settings"])
    config = json.loads(files["config.json"])
    # boatbod's dashboard renders these received strings with innerHTML.
    # Escape the runtime copy only; saved profiles and normal exports stay plain.
    for channel in config["channels"]:
        channel["trunking_sysname"] = html.escape(channel["trunking_sysname"])
        # Native OP25 startup creates plot sinks once. Browser reloads must not
        # toggle them, since toggle_plot would turn existing plots off.
        channel["plot"] = "fft,constellation,symbol,datascope,mixer,fll"
    for trunk in config["trunking"]["chans"]:
        trunk["sysname"] = html.escape(trunk["sysname"])
        for key in ("tgid_tags_file", "whitelist", "blacklist", "rid_tags_file"):
            if trunk.get(key):
                trunk[key] = str(destination / trunk[key])
    tags = io.StringIO(newline="")
    writer = csv.writer(tags, delimiter="\t", lineterminator="\n")
    for row in csv.reader(io.StringIO(files["talkgroups.tsv"]), delimiter="\t"):
        if len(row) < 2:
            raise ValueError("Generated talkgroup label file is malformed")
        writer.writerow([row[0], html.escape(row[1]), *row[2:]])
    files["talkgroups.tsv"] = tags.getvalue()
    if "rid_tags.tsv" in files:  # user-typed radio names reach the same innerHTML, so escape them too
        names = io.StringIO(newline="")
        name_writer = csv.writer(names, delimiter="\t", lineterminator="\n")
        for row in csv.reader(io.StringIO(files["rid_tags.tsv"]), delimiter="\t"):
            if len(row) < 2:
                raise ValueError("Generated radio name file is malformed")
            name_writer.writerow([row[0], html.escape(row[1]), *row[2:]])
        files["rid_tags.tsv"] = names.getvalue()
    config["terminal"]["terminal_type"] = "http:0.0.0.0:8080"
    for channel in config["channels"]:
        channel["destination"] = "ws://0.0.0.0:9000"
    files["config.json"] = json.dumps(config, indent=2)
    # Revision directories are immutable. A failed write never replaces active selection.
    if not destination.exists():
        stage = destination.with_name(destination.name + "-staging")
        # An interrupted earlier run leaves this behind; it is never active, so discard it.
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True, exist_ok=False)
        for name, content in files.items():
            (stage / name).write_text(content, encoding="utf-8")
        stage.rename(destination)
    pointer = root / "receiver" / "active.json"
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(json.dumps({"profile_id": identity, "revision": profile["revision"],
                                     "prepared_format": PREPARED_FORMAT}), encoding="utf-8")
    os.replace(temporary, pointer)
    return destination


def active_config(root):
    root = Path(root).resolve()
    pointer = json.loads((root / "receiver/active.json").read_text(encoding="utf-8"))
    # Validate ID through the same allowlist as stored profiles, before using in a path.
    ProfileLibrary(root / "saved-profiles").path(pointer["profile_id"])
    revision = int(pointer["revision"])
    if revision < 1:
        raise ValueError("Invalid active revision")
    prepared_format = int(pointer.get("prepared_format", 1))
    if prepared_format not in (1, 2, PREPARED_FORMAT):
        raise ValueError("Invalid prepared receiver format")
    suffix = f"-v{prepared_format}" if prepared_format > 1 else ""
    config = root / "receiver" / f"{pointer['profile_id']}-r{revision}{suffix}" / "config.json"
    if not config.is_file():
        raise ValueError("Prepared receiver configuration is missing")
    return config


def run(root):
    """Run the receiver under the browser-controllable supervisor; blocks until it exits."""
    from brutal_supervisor import serve
    return serve(root)


def exec_receiver(root):
    """Replace this process with OP25 for the active profile. Used by the supervisor, not users."""
    config = active_config(root)
    override = os.environ.get('OP25_PREPARED_CONFIG')
    if override:
        path = Path(override).resolve()
        if path != Path('/tmp/rsp-config.json'):
            raise ValueError('Invalid SDRplay runtime configuration path')
        config = path
    bind = os.environ.get('OP25_HTTP_BIND')
    if bind:
        # The supervisor owns the public port and proxies to OP25 on this loopback-only one.
        if not re.fullmatch(r'127\.0\.0\.1:[0-9]{2,5}', bind):
            raise ValueError('Invalid internal receiver address')
        data = json.loads(config.read_text(encoding="utf-8"))
        data["terminal"]["terminal_type"] = "http:" + bind
        config = Path('/tmp/brutal-active-config.json')
        config.write_text(json.dumps(data), encoding="utf-8")
    devices = json.loads(config.read_text(encoding="utf-8"))["devices"]
    if any("driver=sdrplay" in device["args"] for device in devices):
        from hardware_check import check_profile
        report = check_profile("rspdxr2")
        if report["missing"]:
            raise ValueError("SDRplay software is not installed in this receiver environment: " + "; ".join(report["missing"]))
    source = Path(os.environ.get("OP25_APPS_DIR", "/opt/op25/op25/gr-op25_repeater/apps"))
    runtime = Path(root) / "runtime"
    apps = runtime / "apps"
    shutil.copytree(source, apps, dirs_exist_ok=True)
    patch_runtime_apps(apps)
    # Refresh web assets at image upgrade while keeping a writable plot directory.
    shutil.copytree(source.parent / "www", runtime / "www", dirs_exist_ok=True)
    apply_branding(runtime / "www")
    os.chdir(apps)
    os.execv(sys.executable, [sys.executable, str(apps / "multi_rx.py"), "-c", str(config)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("profile_id", nargs="?")
    args = parser.parse_args()
    root = os.environ.get("OP25_DATA_DIR", "/data")
    try:
        if args.action == "prepare":
            if not args.profile_id:
                raise ValueError("Supply the saved profile ID")
            print(prepare(root, args.profile_id))
        else:
            exec_receiver(root)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        raise SystemExit(f"Receiver: {exc}. Prepare a saved profile before starting.")
