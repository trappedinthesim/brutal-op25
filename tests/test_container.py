import json
from pathlib import Path
import tempfile
import unittest
from container_receiver import prepare, active_config
from library import ProfileLibrary

ROOT = Path(__file__).resolve().parents[1]


class ContainerTests(unittest.TestCase):
    def test_launchers_provide_private_writable_gnuradio_home(self):
        for name in ('brutal-op25.sh',):
            launcher = (ROOT / name).read_text()
            self.assertIn('/home/op25:size=16m,uid=1000,gid=1000,mode=0700', launcher)
            self.assertIn('--read-only', launcher)

    def test_refresh_dockerfile_copies_the_same_app_files_as_the_main_dockerfile(self):
        def app_files(name):
            text = (ROOT / 'build' / name).read_text()
            line = next(l for l in text.splitlines() if l.startswith('COPY src/importer.py'))
            return set(line.split()[1:-1])
        self.assertEqual(app_files('Dockerfile.refresh'), app_files('Dockerfile'))
        self.assertIn('COPY --from=patched-op25 /usr/local/lib/x86_64-linux-gnu/libgnuradio-op25_repeater.so.1.0.0.0',
                      (ROOT / 'build/Dockerfile.refresh').read_text())
        self.assertIn('COPY --from=patched-op25 /usr/local/lib/x86_64-linux-gnu/libgnuradio-op25_repeater.so.1.0.0.0',
                      (ROOT / 'build/Dockerfile.sdrplay-ui').read_text())

    def test_runtime_and_private_refresh_keep_security_package_updates(self):
        base = (ROOT / 'build/Dockerfile').read_text()
        refresh = (ROOT / 'build/Dockerfile.refresh').read_text()
        self.assertIn('libssl3 usbutils', base)
        self.assertNotIn('python3-venv python3-setuptools', base)
        self.assertIn('setuptools==84.0.0', base)
        self.assertIn('apt-get install -y --only-upgrade libssl3', refresh)
        self.assertIn('setuptools==84.0.0', refresh)

    def test_launchers_check_published_ports_before_docker_run(self):
        for name, run_marker in (('brutal-op25.sh', 'exec docker run'),):
            launcher = (ROOT / name).read_text()
            self.assertIn('already in use', launcher)
            self.assertLess(launcher.index('already in use'), launcher.index(run_marker))
            for port in ('8080', '9000'):
                self.assertIn(port, launcher[:launcher.index(run_marker)])

    def test_prepare_real_capture_and_revision_switch(self):
        system = json.loads((Path(__file__).parent / "live-bexar-system.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            library = ProfileLibrary(Path(directory) / "saved-profiles")
            profile = library.save(system, {"hardware": {"profile": "rtl"}, "site_id": system["sites"][0]["id"],
                "source": "radioreference", "talkgroup_ids": []})
            destination = prepare(directory, profile["id"])
            self.assertTrue(destination.name.endswith("-v3"))
            self.assertEqual(json.loads((Path(directory) / "receiver" / "active.json").read_text())
                             ["prepared_format"], 3)
            config = json.loads(active_config(directory).read_text(encoding="utf-8"))
            self.assertEqual(config["terminal"]["terminal_type"], "http:0.0.0.0:8080")
            self.assertEqual(config["channels"][0]["destination"], "ws://0.0.0.0:9000")
            self.assertEqual(config["channels"][0]["plot"],
                             "fft,constellation,symbol,datascope,mixer,fll")
            self.assertEqual(Path(config["trunking"]["chans"][0]["tgid_tags_file"]), destination / "talkgroups.tsv")
            prepare(directory, profile["id"])
            library.apply(library.review(profile["id"], system))
            second = prepare(directory, profile["id"])
            self.assertNotEqual(destination, second)
            self.assertTrue(destination.exists())
            self.assertEqual(active_config(directory), second / "config.json")

    def test_prepared_receiver_gets_priority_blocklist_and_escaped_radio_names(self):
        system = json.loads((Path(__file__).parent / "live-bexar-system.json").read_text(encoding="utf-8"))
        ids = [g["id"] for g in system["talkgroups"]]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = ProfileLibrary(root / "saved-profiles")
            profile = library.save(system, {"hardware": {"profile": "rtl"}, "site_id": system["sites"][0]["id"],
                "source": "radioreference", "priority_tgids": [ids[0]], "blocked_tgids": [ids[3]],
                "rid_labels": {"7": "<img src=x onerror=alert(1)>", "8": "Medic & Co"}, "hold_time": 5})
            destination = prepare(root, profile["id"])
            trunk = json.loads((destination / "config.json").read_text(encoding="utf-8"))["trunking"]["chans"][0]
            for key, name in (("blacklist", "blacklist.tsv"), ("rid_tags_file", "rid_tags.tsv"),
                              ("tgid_tags_file", "talkgroups.tsv")):
                self.assertEqual(Path(trunk[key]), destination / name)   # absolute, inside this revision
            self.assertEqual(trunk["tgid_hold_time"], 5.0)
            self.assertEqual((destination / "blacklist.tsv").read_text(), f"{ids[3]}\n")
            names = (destination / "rid_tags.tsv").read_text(encoding="utf-8")
            self.assertNotIn("<img", names)                              # the dashboard renders these as HTML
            self.assertIn("&lt;img src=x onerror=alert(1)&gt;", names)
            self.assertIn("Medic &amp; Co", names)
            first = (destination / "talkgroups.tsv").read_text(encoding="utf-8").splitlines()[0].split("\t")
            self.assertEqual((first[0], first[-1], len(first)), (str(ids[0]), "1", 3))
            # Saved data stays plain; only the runtime copy is escaped.
            self.assertEqual(library.read(profile["id"])["settings"]["rid_labels"]["7"], "<img src=x onerror=alert(1)>")

    def test_interrupted_prepare_does_not_block_the_profile(self):
        system = json.loads((Path(__file__).parent / "live-bexar-system.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = ProfileLibrary(root / "saved-profiles")
            profile = library.save(system, {"hardware": {"profile": "rtl"},
                "site_id": system["sites"][0]["id"], "source": "radioreference"})
            # A crash or Ctrl+C between mkdir and rename leaves a half-written staging directory.
            stale = root / "receiver" / f"{profile['id']}-r{profile['revision']}-v3-staging"
            stale.mkdir(parents=True)
            (stale / "config.json").write_text("{truncated", encoding="utf-8")
            destination = prepare(root, profile["id"])
            self.assertEqual(active_config(root), destination / "config.json")
            self.assertIn("devices", json.loads((destination / "config.json").read_text(encoding="utf-8")))
            self.assertFalse(stale.exists())

    def test_existing_prepared_revision_is_not_reused_after_format_upgrade(self):
        system = json.loads((Path(__file__).parent / "live-bexar-system.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = ProfileLibrary(root / "saved-profiles")
            profile = library.save(system, {"hardware": {"profile": "rtl"},
                "site_id": system["sites"][0]["id"], "source": "radioreference"})
            old = root / "receiver" / f"{profile['id']}-r{profile['revision']}"
            old.mkdir(parents=True)
            (old / "config.json").write_text('{"old":true}', encoding="utf-8")
            (root / "receiver" / "active.json").write_text(json.dumps({
                "profile_id": profile["id"], "revision": profile["revision"]}), encoding="utf-8")
            self.assertEqual(active_config(root), old / "config.json")
            new = prepare(root, profile["id"])
            self.assertNotEqual(new, old)
            self.assertEqual((old / "config.json").read_text(), '{"old":true}')
            self.assertEqual(active_config(root), new / "config.json")

    def test_v2_prepared_revision_is_preserved_and_upgraded_to_v3(self):
        system = json.loads((Path(__file__).parent / "live-bexar-system.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = ProfileLibrary(root / "saved-profiles")
            profile = library.save(system, {"hardware": {"profile": "rtlv4"},
                "site_id": system["sites"][0]["id"], "source": "radioreference"})
            old = root / "receiver" / f"{profile['id']}-r{profile['revision']}-v2"
            old.mkdir(parents=True)
            (old / "config.json").write_text('{"old":2}', encoding="utf-8")
            (root / "receiver" / "active.json").write_text(json.dumps({
                "profile_id": profile["id"], "revision": profile["revision"],
                "prepared_format": 2}), encoding="utf-8")
            self.assertEqual(active_config(root), old / "config.json")
            new = prepare(root, profile["id"])
            self.assertTrue(new.name.endswith('-v3'))
            self.assertEqual((old / "config.json").read_text(), '{"old":2}')
            self.assertEqual(active_config(root), new / "config.json")

    def test_runtime_receiver_escapes_database_labels_for_upstream_html(self):
        system = json.loads((Path(__file__).parent / "live-bexar-system.json").read_text(encoding="utf-8"))
        system["name"] = "AARRS <status>"
        system["sites"][0]["name"] = "Northeast & More"
        system["talkgroups"][0]["label"] = '<img src=x onerror=alert(1)>'
        with tempfile.TemporaryDirectory() as directory:
            library = ProfileLibrary(Path(directory) / "saved-profiles")
            profile = library.save(system, {"hardware": {"profile": "rtl"},
                "site_id": system["sites"][0]["id"], "source": "radioreference"})
            destination = prepare(directory, profile["id"])
            config = json.loads((destination / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["channels"][0]["trunking_sysname"],
                             config["trunking"]["chans"][0]["sysname"])
            self.assertIn("&lt;status&gt;", config["channels"][0]["trunking_sysname"])
            self.assertIn("&amp; More", config["channels"][0]["trunking_sysname"])
            self.assertIn("&lt;img src=x onerror=alert(1)&gt;",
                          (destination / "talkgroups.tsv").read_text(encoding="utf-8"))
            self.assertIn('<img src=x onerror=alert(1)>', library.read(profile["id"])["system"]["talkgroups"][0]["label"])


if __name__ == "__main__":
    unittest.main()
