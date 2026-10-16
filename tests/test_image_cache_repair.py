"""Exercise bounded cache replacement and its ownership/in-use guards."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'ghcr.io/trappedinthesim/brutal-op25-receiver:0.3.0-dev.24'
LOCAL = 'brutal-op25:0.3.0-dev.24'
IMAGE_ID = 'sha256:' + 'a' * 64

MOCK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['REPAIR_STATE'])
s = json.loads(p.read_text())
a = sys.argv[1:]
with open(os.environ['REPAIR_LOG'], 'a') as f:
    f.write(json.dumps(a) + '\n')
def done(code=0, output=''):
    p.write_text(json.dumps(s))
    if output: print(output)
    sys.exit(code)
if a[0] == 'run':
    if s.get('runtime_error'): done(125, 'Docker daemon unavailable')
    if s['broken']: done(1, '/usr/bin/id: cannot find name for user ID 1000')
    done(0, 'op25')
if a[:2] == ['image', 'inspect']:
    if not s['present']: done(1)
    if '--format' not in a: done()
    fmt = a[a.index('--format') + 1]
    if fmt == '{{.Id}}':
        if s.get('retagged') and a[2] == s['tags'][0]: done(0, 'sha256:' + 'b' * 64)
        done(0, s['id'])
    if '.Config.Labels' in fmt: done(0, s['source'])
    if '.RepoDigests' in fmt: done(0, s.get('digest', ''))
    if '.RepoTags' in fmt: done(0, '\n'.join(s['tags']))
if a[0] == 'ps':
    if s.get('ps_failed'): done(1)
    done(0, s.get('containers', ''))
if a[:2] == ['image', 'rm']:
    if s.get('remove_failed'): done(1)
    assert a[2] == '--no-prune' and a[3:] == s['tags'], a
    s['present'] = False
    done()
if a[0] == 'pull':
    if s.get('pull_failed'): done(1)
    s['present'] = True
    s['broken'] = s.get('still_broken', False)
    done()
done(2, 'Unexpected mock command: ' + repr(a))
'''


@unittest.skipUnless(os.name != 'nt' and shutil.which('bash'), 'Needs native Bash')
class ImageCacheRepairTests(unittest.TestCase):
    def run_repair(self, **overrides):
        state = dict(present=True, broken=True, id=IMAGE_ID,
                     tags=[LOCAL, LOCAL + '-previous', RELEASE],
                     source='https://github.com/trappedinthesim/brutal-op25')
        state.update(overrides)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state').write_text(json.dumps(state))
            (root / 'docker').write_text(MOCK)
            (root / 'docker').chmod(0o755)
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ['PATH'],
                       REPAIR_STATE=str(root / 'state'), REPAIR_LOG=str(root / 'log'))
            result = subprocess.run(['bash', '-c',
                                     '. ./install/image-bootstrap.sh; brutal_verify_release_image "$1"',
                                     '_', RELEASE], cwd=ROOT, env=env, capture_output=True,
                                    text=True, timeout=10)
            calls = [json.loads(line) for line in (root / 'log').read_text().splitlines()]
        return result, calls

    def test_missing_account_replaces_only_the_validated_image_once(self):
        result, calls = self.run_repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        removals = [a for a in calls if a[:2] == ['image', 'rm']]
        self.assertEqual(removals, [['image', 'rm', '--no-prune', LOCAL, LOCAL + '-previous', RELEASE]])
        self.assertEqual([a for a in calls if a[0] == 'pull'], [['pull', RELEASE]])
        self.assertEqual(calls[-1][0], 'run')
        self.assertFalse(any('--volume' in a or '--force' in a or 'prune' in a for a in calls))

    def test_healthy_image_needs_no_repair(self):
        result, calls = self.run_repair(broken=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)

    def test_guards_stop_before_any_removal(self):
        scenarios = [dict(runtime_error=True), dict(containers='abc123'),
                     dict(source='https://example.com/another-project'),
                     dict(tags=[LOCAL, RELEASE, 'another-app:latest']),
                     dict(digest='another-registry/app@' + IMAGE_ID),
                     dict(retagged=True), dict(ps_failed=True)]
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                result, calls = self.run_repair(**scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(a[:2] == ['image', 'rm'] or a[0] == 'pull' for a in calls))

    def test_removal_failure_is_not_forced(self):
        result, calls = self.run_repair(remove_failed=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(a[0] == 'pull' or '--force' in a for a in calls))

    def test_failed_download_gives_retry_instruction(self):
        result, calls = self.run_repair(pull_failed=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Run Update again', result.stderr)
        self.assertEqual(sum(a[0] == 'pull' for a in calls), 1)

    def test_still_broken_after_replacement_does_not_loop(self):
        result, calls = self.run_repair(still_broken=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('after one cache replacement', result.stderr)
        self.assertEqual(sum(a[:2] == ['image', 'rm'] for a in calls), 1)
        self.assertEqual(sum(a[0] == 'pull' for a in calls), 1)
