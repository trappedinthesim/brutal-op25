"""Prebuilt-image selection must never turn private runtime data into build inputs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'ghcr.io/trappedinthesim/brutal-op25-receiver:0.3.0-dev.5'
LOCAL = 'brutal-op25:0.3.0-dev.5'


class ImageReleaseTests(unittest.TestCase):
    def test_versioned_image_is_consistent(self):
        self.assertEqual((ROOT / 'build/image-release.txt').read_text().strip(), RELEASE)
        self.assertIn(f'BRUTAL_LOCAL_IMAGE={LOCAL}', (ROOT / 'install/image-bootstrap.sh').read_text())
        dockerfile = (ROOT / 'build/Dockerfile').read_text()
        self.assertIn('org.opencontainers.image.version="0.3.0-dev.5"', dockerfile)
        self.assertIn('ARG SOURCE_REVISION=unknown', dockerfile)
        self.assertIn('ARG RR_EMBED_REVISION=local', dockerfile)

    def test_release_workflow_embeds_only_the_app_key_through_buildkit(self):
        workflow = (ROOT / '.github/workflows/image.yml').read_text()
        self.assertIn('packages: write', workflow)
        self.assertIn("tags:\n      - 'image-v*'", workflow)
        self.assertIn('docker run --rm --network none', workflow)
        self.assertIn('docker push "$IMAGE_REF"', workflow)
        self.assertIn('Verify bundled RTL receiver driver loads', workflow)
        self.assertIn('Verify license, notices, and corresponding upstream source', workflow)
        self.assertIn('check_profile("rtlv4")', workflow)
        self.assertIn('secrets.BRUTAL_RR_APP_KEY', workflow)
        self.assertIn('--secret id=rr_key,env=BRUTAL_RR_APP_KEY', workflow)
        self.assertIn('--build-arg REQUIRE_RR_EMBED=1', workflow)
        self.assertNotIn('--build-arg BRUTAL_RR_APP_KEY', workflow)
        self.assertNotIn('echo "$BRUTAL_RR_APP_KEY"', workflow)
        self.assertNotIn('SDRPLAY_LICENSE_ACCEPTED=yes', workflow)
        ignore = (ROOT / '.dockerignore').read_text()
        self.assertNotIn('!build/image-release.txt', ignore)
        self.assertNotIn('!install/image-bootstrap.sh', ignore)


@unittest.skipUnless(os.name != 'nt' and shutil.which('bash'), 'Needs native Bash')
class LinuxPullTests(unittest.TestCase):
    def run_bootstrap(self, *, local_present=False, pull_succeeds=True, crlf_release=False,
                      operation='ensure', expected_success=True):
        with tempfile.TemporaryDirectory() as directory:
            mock = Path(directory) / 'docker'
            log = Path(directory) / 'calls'
            mock.write_text('#!/bin/sh\n'
                            'printf "%s\\n" "$*" >> "$BRUTAL_TEST_LOG"\n'
                            'case "$1 $2" in\n'
                            '  "image inspect")\n'
                            '    if [ "$3" = "brutal-op25:0.3.0-dev.5" ]; then\n'
                            '      [ "$BRUTAL_TEST_LOCAL" = 0 ] || exit 1\n'
                            '      [ "$4" = "--format" ] && printf "%s\\n" old-id\n'
                            '    else\n'
                            '      [ "$4" = "--format" ] && printf "%s\\n" new-id\n'
                            '    fi\n'
                            '    exit 0;;\n'
                            '  "pull "*) exit "$BRUTAL_TEST_PULL";;\n'
                            'esac\n'
                            'exit 0\n')
            mock.chmod(0o755)
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ['PATH'],
                       BRUTAL_TEST_LOG=str(log),
                       BRUTAL_TEST_LOCAL='0' if local_present else '1',
                       BRUTAL_TEST_PULL='0' if pull_succeeds else '1')
            release_root = ROOT
            if crlf_release:
                release_root = Path(directory)
                (release_root / 'build').mkdir()
                (release_root / 'build/image-release.txt').write_bytes((RELEASE + '\r\n').encode())
            action = {'ensure': 'brutal_ensure_base_image "$BRUTAL_TEST_RELEASE_ROOT"',
                      'update': 'brutal_update_base_image "$BRUTAL_TEST_RELEASE_ROOT"',
                      'rollback': 'brutal_rollback_base_image'}[operation]
            script = '. ./install/image-bootstrap.sh; ' + action
            env['BRUTAL_TEST_RELEASE_ROOT'] = str(release_root)
            result = subprocess.run(['bash', '-c', script], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=10)
            calls = log.read_text().splitlines() if log.exists() else []
        self.assertEqual(result.returncode == 0, expected_success, result.stderr)
        return calls

    def test_existing_local_image_does_not_pull_or_build(self):
        self.assertEqual(self.run_bootstrap(local_present=True),
                         [f'image inspect {LOCAL}'])

    def test_pull_success_is_tagged_locally_without_build(self):
        calls = self.run_bootstrap()
        self.assertEqual(calls, [f'image inspect {LOCAL}', f'pull {RELEASE}',
                                 f'tag {RELEASE} {LOCAL}'])

    def test_windows_checkout_line_endings_are_accepted(self):
        calls = self.run_bootstrap(crlf_release=True)
        self.assertEqual(calls, [f'image inspect {LOCAL}', f'pull {RELEASE}',
                                 f'tag {RELEASE} {LOCAL}'])

    def test_private_registry_failure_falls_back_to_local_build(self):
        calls = self.run_bootstrap(pull_succeeds=False)
        self.assertEqual(calls[:2], [f'image inspect {LOCAL}', f'pull {RELEASE}'])
        self.assertEqual(calls[2], f'build --file {ROOT}/build/Dockerfile --tag {LOCAL} {ROOT}')

    def test_explicit_update_keeps_last_image_for_rollback(self):
        calls = self.run_bootstrap(local_present=True, operation='update')
        self.assertEqual(calls, [f'pull {RELEASE}',
                                 f'image inspect {LOCAL} --format {{{{.Id}}}}',
                                 f'image inspect {RELEASE} --format {{{{.Id}}}}',
                                 f'tag {LOCAL} {LOCAL}-previous',
                                 f'tag {RELEASE} {LOCAL}'])

    def test_failed_update_does_not_retag_current_image(self):
        calls = self.run_bootstrap(local_present=True, pull_succeeds=False,
                                   operation='update', expected_success=False)
        self.assertEqual(calls, [f'pull {RELEASE}'])

    def test_image_rollback_keeps_failed_version_for_diagnosis(self):
        calls = self.run_bootstrap(local_present=True, operation='rollback')
        self.assertEqual(calls, [f'image inspect {LOCAL}-previous',
                                 f'tag {LOCAL} {LOCAL}-failed',
                                 f'tag {LOCAL}-previous {LOCAL}'])

    def test_sdrplay_addon_is_rebuilt_when_base_image_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            mock = Path(directory) / 'docker'
            mock.write_text('#!/bin/sh\n'
                            'if [ "$3" = "brutal-op25:0.3.0-dev.5" ]; then echo base-id; '
                            'else echo "$BRUTAL_TEST_ADDON_BASE"; fi\n')
            mock.chmod(0o755)
            script = '. ./install/image-bootstrap.sh; brutal_sdrplay_addon_current addon'
            for addon_base, expected in [('base-id', 0), ('old-base-id', 1)]:
                env = dict(os.environ, PATH=directory + os.pathsep + os.environ['PATH'],
                           BRUTAL_TEST_ADDON_BASE=addon_base)
                result = subprocess.run(['bash', '-c', script], cwd=ROOT, env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)


if __name__ == '__main__':
    unittest.main()
