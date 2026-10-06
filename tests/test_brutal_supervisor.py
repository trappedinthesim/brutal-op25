import json
from pathlib import Path
import http.client
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import brutal_supervisor as sup
from library import ProfileLibrary

SYSTEM = json.loads((Path(__file__).parent / 'live-bexar-system.json').read_text(encoding='utf-8'))
HARDWARE = {'profile': 'rtl', 'args': 'rtl', 'rate': 1000000, 'gains': 'LNA:39', 'ppm': 0}
CHILD = ("import http.server, os\n"
         "class H(http.server.BaseHTTPRequestHandler):\n"
         "    def do_GET(self):\n"
         "        b = os.environ['NAME'].encode(); self.send_response(200); self.send_header('Content-Length', str(len(b)))\n"
         "        self.end_headers(); self.wfile.write(b)\n"
         "    def log_message(self, *a): pass\n"
         "http.server.HTTPServer(('127.0.0.1', int(os.environ['PORT'])), H).serve_forever()\n")


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_for(predicate, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def saved(library, site_index=0, hardware=HARDWARE):
    return library.save(SYSTEM, {'hardware': hardware, 'site_id': SYSTEM['sites'][site_index]['id'],
                                 'source': 'radioreference'})


class ReceiverTests(unittest.TestCase):
    def make(self, script=CHILD):
        port = free_port()
        receiver = sup.Receiver('/unused', port, prepare_fn=lambda *_: None, release_delay=0.05,
            stop_timeout=5, ready_timeout=20,
            command_for=lambda profile, p: ([sys.executable, '-c', script],
                                            {'PORT': str(p), 'NAME': profile['id'], 'PATH': ''}))
        self.addCleanup(receiver.stop)
        return receiver, port

    def test_lifecycle_start_ready_stop(self):
        receiver, _ = self.make()
        receiver.start({'id': 'a', 'name': 'A'})
        self.assertEqual(receiver.state, 'starting')
        self.assertTrue(wait_for(lambda: receiver.state == 'running'))
        self.assertGreaterEqual(receiver.status()['uptime_s'], 0)
        with self.assertRaisesRegex(ValueError, 'already running'):
            receiver.start({'id': 'b', 'name': 'B'})
        receiver.stop()
        self.assertEqual(receiver.state, 'stopped')

    def test_switch_replaces_the_running_receiver_and_reports_switching(self):
        receiver, port = self.make()
        receiver.start({'id': 'first', 'name': 'First'})
        self.assertTrue(wait_for(lambda: receiver.state == 'running'))
        receiver.switch({'id': 'second', 'name': 'Second'})
        self.assertEqual(receiver.state, 'switching')
        with self.assertRaisesRegex(ValueError, 'already in progress'):
            receiver.switch({'id': 'third', 'name': 'Third'})
        self.assertTrue(wait_for(lambda: receiver.state == 'running' and receiver.profile['id'] == 'second'))
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        conn.request('GET', '/')
        self.assertEqual(conn.getresponse().read(), b'second')
        conn.close()
        self.assertEqual(receiver.restarts, 1)

    def test_unexpected_exit_is_an_error_and_clean_exit_is_stopped(self):
        receiver, _ = self.make('import sys; sys.exit(3)')
        receiver.start({'id': 'x', 'name': 'X'})
        self.assertTrue(wait_for(lambda: receiver.state == 'error'))
        self.assertIn('code 3', receiver.message)
        self.assertEqual(receiver.last_exit, 3)
        receiver, _ = self.make('import sys; sys.exit(0)')
        receiver.start({'id': 'y', 'name': 'Y'})
        self.assertTrue(wait_for(lambda: receiver.state == 'stopped'))

    def test_failed_switch_reports_error_instead_of_hanging(self):
        receiver, _ = self.make()
        receiver.prepare = Mock(side_effect=ValueError('bad profile'))
        receiver.switch({'id': 'bad', 'name': 'Bad'})
        self.assertTrue(wait_for(lambda: receiver.state == 'error'))
        self.assertIn('bad profile', receiver.message)


class FakeReceiver:
    def __init__(self, profile):
        self.profile, self.switched, self.state = profile, [], 'running'

    def switch(self, profile):
        self.switched.append(profile['id'])
        self.profile = profile

    def status(self):
        return {'state': self.state, 'message': '', 'restarts': 0, 'uptime_s': 5, 'last_exit': None}


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = ProfileLibrary(Path(self.temp.name) / 'saved-profiles')
        self.active = saved(self.library, 0)
        self.receiver = FakeReceiver(self.active)
        self.rr = Mock()
        self.rr.system.return_value = SYSTEM
        self.factory = Mock(return_value=self.rr)
        self.clock = [1000.0]
        self.control = sup.Control(self.temp.name, self.receiver, self.library, self.factory,
                                   lambda: 'unit-key', clock=lambda: self.clock[0])

    def test_systems_lists_active_and_flags_other_radio_families(self):
        other = saved(self.library, 1)
        rsp = saved(self.library, 2, {'profile': 'rspdxr2', 'args': 'soapy=0,driver=sdrplay',
                                      'rate': 2000000, 'gains': 'IFGR:40,RFGR:0', 'ppm': 0})
        rows = {r['id']: r for r in self.control.systems()['systems']}
        self.assertTrue(rows[self.active['id']]['active'])
        self.assertTrue(rows[other['id']]['compatible'])
        self.assertFalse(rows[rsp['id']]['compatible'])
        self.assertIn('different radio', rows[rsp['id']]['reason'])

    def test_empty_dashboard_saves_systems_with_selected_radio_and_never_listens_without_usb(self):
        receiver = FakeReceiver(None)
        receiver.state = 'stopped'
        hardware = {**HARDWARE, 'profile': 'rtlv4'}
        control = sup.Control(self.temp.name, receiver, self.library, self.factory,
                              lambda: 'unit-key', seed_hardware=hardware, can_listen=False)
        self.assertFalse(control.session()['can_listen'])
        result = control.save_manual('Test', 'Site', '851.0125', activate=False)
        profile = self.library.read(result['saved']['id'])
        self.assertEqual(profile['settings']['hardware'], hardware)
        self.assertEqual(len(control.systems()['systems']), 2)
        self.assertFalse({r['id']: r for r in control.systems()['systems']}[profile['id']]['compatible'])
        with self.assertRaisesRegex(ValueError, 'Radio is not connected'):
            control.activate(profile['id'])
        self.assertEqual(receiver.switched, [])
        control.can_listen = True
        control.activate(profile['id'])
        self.assertEqual(receiver.switched, [profile['id']])

    def test_empty_dashboard_can_import_multiple_sites_without_activating(self):
        receiver = FakeReceiver(None)
        hardware = {**HARDWARE, 'profile': 'rtlv4'}
        control = sup.Control(self.temp.name, receiver, self.library, self.factory,
                              lambda: 'unit-key', seed_hardware=hardware, can_listen=False)
        control.rr_login('user', 'secret')
        control.rr_system(SYSTEM['id'])
        site_ids = [site['id'] for site in SYSTEM['sites'] if site['controls_hz']
                    and site['id'] != self.active['settings']['site_id']][:2]
        self.assertEqual(len(site_ids), 2)
        for site_id in site_ids:
            result = control.save_pending(site_id, activate=False)
            self.assertEqual(self.library.read(result['saved']['id'])['settings']['hardware'], hardware)
        self.assertEqual(len(self.library.list()), 3)
        self.assertEqual(receiver.switched, [])

    def test_activate_switches_only_to_a_compatible_system(self):
        other = saved(self.library, 1)
        rsp = saved(self.library, 2, {'profile': 'rspdxr2', 'args': 'soapy=0,driver=sdrplay',
                                      'rate': 2000000, 'gains': 'IFGR:40,RFGR:0', 'ppm': 0})
        self.control.activate(other['id'])
        self.assertEqual(self.receiver.switched, [other['id']])
        with self.assertRaisesRegex(ValueError, 'different radio'):
            self.control.activate(rsp['id'])
        with self.assertRaises(ValueError):
            self.control.activate('f' * 32)
        self.assertEqual(self.receiver.switched, [other['id']])

    def test_rtl_and_rtlv4_are_the_same_radio_family(self):
        v4 = saved(self.library, 1, {**HARDWARE, 'profile': 'rtlv4'})
        self.assertTrue({r['id']: r for r in self.control.systems()['systems']}[v4['id']]['compatible'])

    def test_remove_refuses_the_active_system_and_archives_others(self):
        other = saved(self.library, 1)
        with self.assertRaisesRegex(ValueError, 'Switch to another system'):
            self.control.remove(self.active['id'])
        self.assertEqual(self.control.remove(other['id']), {'removed': other['name']})
        self.assertEqual([r['id'] for r in self.control.systems()['systems']], [self.active['id']])

    def test_unreadable_files_are_reported(self):
        (Path(self.temp.name) / 'saved-profiles' / ('d' * 32 + '.json')).write_text('{bad', encoding='utf-8')
        self.assertEqual(self.control.systems()['unreadable'], ['d' * 32 + '.json'])

    def test_radioreference_flow_saves_with_the_current_radio_settings(self):
        self.control.rr_login(' user ', 'secret')
        self.factory.assert_called_once_with('user', 'secret', 'unit-key')
        self.assertTrue(self.control.status()['rr_connected'])
        summary = self.control.rr_system(SYSTEM['id'])
        self.assertEqual(summary['talkgroups'], len(SYSTEM['talkgroups']))
        site = next(s for s in summary['sites'] if s['selectable'] and s['id'] != self.active['settings']['site_id'])
        result = self.control.save_pending(site['id'], activate=True)
        profile = self.library.read(result['saved']['id'])
        self.assertEqual(profile['settings']['hardware'], HARDWARE)
        self.assertEqual(profile['settings']['source'], 'radioreference')
        self.assertFalse(profile['settings']['selected_only'])
        self.assertEqual(self.receiver.switched, [profile['id']])
        self.assertNotIn('secret', json.dumps(profile))

    def test_saving_the_same_system_and_site_twice_is_refused(self):
        self.control.rr_login('user', 'secret')
        self.control.rr_system(SYSTEM['id'])
        with self.assertRaisesRegex(ValueError, 'already saved'):
            self.control.save_pending(self.active['settings']['site_id'])
        self.assertEqual(len(self.library.list()), 1)

    def test_site_without_control_channels_cannot_be_saved(self):
        broken = json.loads(json.dumps(SYSTEM))
        broken['sites'][1]['controls_hz'] = []
        self.rr.system.return_value = broken
        self.control.rr_login('user', 'secret')
        summary = self.control.rr_system(broken['id'])
        self.assertFalse(next(s for s in summary['sites'] if s['id'] == broken['sites'][1]['id'])['selectable'])
        with self.assertRaisesRegex(ValueError, 'control channels'):
            self.control.save_pending(broken['sites'][1]['id'])

    def test_login_errors_never_echo_credentials_and_missing_key_is_clear(self):
        self.factory.side_effect = RuntimeError('boom password=secret')
        with self.assertRaises(ValueError) as caught:
            self.control.rr_login('user', 'secret')
        self.assertNotIn('secret', str(caught.exception))
        self.assertFalse(self.control.status()['rr_connected'])
        control = sup.Control(self.temp.name, self.receiver, self.library, self.factory,
                              Mock(side_effect=ValueError('no key')))
        with self.assertRaisesRegex(ValueError, 'no key'):
            control.rr_login('user', 'secret')
        self.assertFalse(control.session()['rr_enabled'])
        with self.assertRaisesRegex(ValueError, 'Username and password'):
            self.control.rr_login('', '')
        with self.assertRaisesRegex(ValueError, 'Sign in'):
            self.control.rr_system(1)

    def test_radioreference_session_expires_and_status_polling_does_not_extend_it(self):
        self.control.rr_login('user', 'secret')
        self.clock[0] += sup.RR_SESSION_TTL - 5
        self.assertTrue(self.control.status()['rr_connected'])  # a poll near expiry...
        self.clock[0] += 10
        self.assertFalse(self.control.status()['rr_connected'])  # ...must not have renewed it
        with self.assertRaisesRegex(ValueError, 'Sign in'):
            self.control.rr_browse('countries')
        self.rr.close.assert_called()

    def test_logout_closes_the_session_and_forgets_the_selected_system(self):
        self.control.rr_login('user', 'secret')
        self.control.rr_system(SYSTEM['id'])
        self.control.rr_logout()
        self.rr.close.assert_called_once()
        with self.assertRaisesRegex(ValueError, 'Choose a system'):
            self.control.save_pending(SYSTEM['sites'][0]['id'])

    def test_manual_system_removes_duplicates_records_tdma_and_inherits_radio(self):
        result = self.control.save_manual('Home P25', 'Roof', '851.0125, 851.0125, 852.5', True)
        site = self.library.read(result['saved']['id'])['system']['sites'][0]
        self.assertEqual(site['controls_hz'], [851012500, 852500000])
        self.assertTrue(site['tdma_cc'])
        self.assertEqual(self.library.read(result['saved']['id'])['settings']['hardware'], HARDWARE)
        for bad in (('', 'Roof', '851.0'), ('Home', '', '851.0'), ('Home', 'Roof', 'abc'), ('Home', 'Roof', '')):
            with self.assertRaises(ValueError):
                self.control.save_manual(*bad)

    # ----- listening preferences -----
    def tg_ids(self, count=6):
        return [g['id'] for g in SYSTEM['talkgroups'][:count]]

    def test_talkgroups_lists_states_and_falls_back_when_category_names_are_missing(self):
        a, b, c = self.tg_ids(3)
        self.active = self.library.save(SYSTEM, {**self.active['settings'], 'priority_tgids': [a], 'blocked_tgids': [b],
            'profile_id': self.active['id'], 'revision': 1, 'profile_name': self.active['name']})
        self.receiver.profile = self.active
        data = self.control.talkgroups()
        states = {t['id']: t['state'] for t in data['talkgroups']}
        self.assertEqual((states[a], states[b], states[c]), ('priority', 'blocked', 'normal'))
        self.assertEqual(len(data['talkgroups']), len(SYSTEM['talkgroups']))
        self.assertFalse(data['has_category_names'])
        self.assertTrue(all(cat['name'].startswith(('Category ', 'Uncategorized')) for cat in data['categories']))
        self.assertEqual(sum(cat['count'] for cat in data['categories']), len(SYSTEM['talkgroups']))
        self.assertEqual((data['crypt_behavior'], data['hold_time'], data['rid_labels']), (2, None, {}))

    def test_talkgroups_uses_category_names_and_shows_a_terminal_listen_only_list_as_priority(self):
        a, b = self.tg_ids(2)
        categorized = json.loads(json.dumps(SYSTEM))
        wanted = categorized['talkgroups'][0]['category_id']
        categorized['categories'] = [{'id': int(wanted), 'name': 'Fire'}]
        self.library.write({**self.active, 'system': categorized, 'settings': {**self.active['settings'],
                            'selected_only': True, 'talkgroup_ids': [a, b]}})
        data = self.control.talkgroups()
        self.assertTrue(data['has_category_names'])
        self.assertIn('Fire', [cat['name'] for cat in data['categories']])
        self.assertTrue(data['listen_only'])
        self.assertEqual({t['id'] for t in data['talkgroups'] if t['state'] == 'priority'}, {a, b})

    def test_apply_settings_saves_a_new_revision_and_restarts_onto_it(self):
        a, b, c = self.tg_ids(3)
        result = self.control.apply_settings({'priority_tgids': [a, b], 'blocked_tgids': [c], 'only_priority': False})
        self.assertTrue(result['saved'])
        saved = self.library.read(self.active['id'])
        self.assertEqual(saved['revision'], 2)
        self.assertEqual((saved['settings']['priority_tgids'], saved['settings']['blocked_tgids']), (sorted([a, b]), [c]))
        self.assertFalse(saved['settings']['selected_only'])
        self.assertEqual(self.receiver.switched, [self.active['id']])
        self.assertEqual(self.receiver.profile['revision'], 2)
        # The earlier revision is kept in history.
        self.assertTrue((Path(self.temp.name) / 'saved-profiles' / 'history' / (self.active['id'] + '-r1.json')).exists())

    def test_only_priority_becomes_a_listen_only_list_and_needs_at_least_one_priority(self):
        a, b = self.tg_ids(2)
        with self.assertRaisesRegex(ValueError, 'at least one talkgroup as Priority'):
            self.control.apply_settings({'only_priority': True, 'priority_tgids': []})
        self.assertEqual(self.library.read(self.active['id'])['revision'], 1)
        self.control.apply_settings({'only_priority': True, 'priority_tgids': [a, b]})
        settings = self.library.read(self.active['id'])['settings']
        self.assertTrue(settings['selected_only'])
        self.assertEqual(settings['talkgroup_ids'], sorted([a, b]))
        self.control.apply_settings({'only_priority': False, 'priority_tgids': [a, b]})
        settings = self.library.read(self.active['id'])['settings']
        self.assertEqual((settings['selected_only'], settings['talkgroup_ids']), (False, []))

    def test_unchanged_settings_do_not_restart_the_receiver(self):
        a = self.tg_ids(1)[0]
        self.control.apply_settings({'priority_tgids': [a]})
        switched = list(self.receiver.switched)
        result = self.control.apply_settings({'priority_tgids': [a]})
        self.assertTrue(result['unchanged'])
        self.assertEqual(self.receiver.switched, switched)
        self.assertEqual(self.library.read(self.active['id'])['revision'], 2)

    def test_bad_settings_are_rejected_before_anything_is_saved_or_restarted(self):
        a, b = self.tg_ids(2)
        bad = [{'nonsense': 1}, {'priority_tgids': ['x']}, {'priority_tgids': [a], 'blocked_tgids': [a]},
               {'priority_tgids': [999999999]}, {'crypt_behavior': 7}, {'hold_time': 99},
               {'rid_labels': {'0': 'zero'}}, {'rid_labels': {'abc': 'x'}},
               {'only_priority': 'false'}, {'priority_tgids': str(a)}]
        for changes in bad:
            with self.assertRaises(ValueError, msg=str(changes)):
                self.control.apply_settings(changes)
        self.assertEqual(self.library.read(self.active['id'])['revision'], 1)
        self.assertEqual(self.receiver.switched, [])

    def test_radio_names_encrypted_behavior_and_hold_time_round_trip_and_hold_time_can_be_reset(self):
        self.control.apply_settings({'rid_labels': {'6002013': 'Engine 5', '7': ' Chief '}, 'crypt_behavior': 1, 'hold_time': 6})
        s = self.library.read(self.active['id'])['settings']
        self.assertEqual((s['rid_labels'], s['crypt_behavior'], s['hold_time']), ({'6002013': 'Engine 5', '7': ' Chief '}, 1, 6.0))
        data = self.control.talkgroups()
        self.assertEqual((data['crypt_behavior'], data['hold_time']), (1, 6.0))
        self.control.apply_settings({'hold_time': None, 'rid_labels': {}})
        s = self.library.read(self.active['id'])['settings']
        self.assertNotIn('hold_time', s)
        self.assertEqual(s['rid_labels'], {})

    def test_a_switch_already_in_progress_blocks_a_second_change(self):
        self.receiver.state = 'switching'
        with self.assertRaisesRegex(ValueError, 'already in progress'):
            self.control.apply_settings({'hold_time': 3})
        self.assertEqual(self.library.read(self.active['id'])['revision'], 1)

    def test_category_names_can_be_added_to_an_older_system_without_a_new_revision(self):
        with self.assertRaisesRegex(ValueError, 'Sign in'):
            self.control.refresh_categories()
        self.control.rr_login('user', 'secret')
        self.rr.categories.return_value = []
        with self.assertRaisesRegex(ValueError, 'no category names'):
            self.control.refresh_categories()
        wanted = int(SYSTEM['talkgroups'][0]['category_id'])
        self.rr.categories.return_value = [{'tgCid': wanted, 'tgCname': 'Fire'}]
        self.assertEqual(self.control.refresh_categories(), {'categories': 1})
        profile = self.library.read(self.active['id'])
        self.assertEqual(profile['system']['categories'], [{'id': wanted, 'name': 'Fire'}])
        self.assertEqual(profile['revision'], 1)  # names only: nothing the receiver reads changed
        self.assertEqual(self.receiver.switched, [])
        manual = self.control.save_manual('Home', 'Roof', '851.0125')
        self.receiver.profile = self.library.read(manual['saved']['id'])
        with self.assertRaisesRegex(ValueError, 'added manually'):
            self.control.refresh_categories()

    def test_status_reports_active_system_and_site(self):
        status = self.control.status()
        self.assertEqual(status['active']['id'], self.active['id'])
        self.assertEqual(status['active']['hardware'], 'rtl')
        self.assertEqual(status['family'], 'rtl')
        self.assertIn(status['active']['site'], [s['name'] for s in SYSTEM['sites']])


class FakeOp25(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        body = b'<html>op25 dashboard</html>' if self.path == '/' else b'png-bytes'
        self.send_response(200)
        if self.path != '/':
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.send_header('ETag', '"upstream-tag"')
        self.send_header('Content-Type', 'text/html' if self.path == '/' else 'image/png')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = self.rfile.read(int(self.headers['Content-Length']))
        FakeOp25.seen.append((self.path, data, self.headers.get('Content-Type'),
                              self.headers.get('Host'), self.headers.get('X-Brutal-Token')))
        body = json.dumps({'echo': json.loads(data)}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        library = ProfileLibrary(Path(self.temp.name) / 'saved-profiles')
        self.active = saved(library)
        self.other = saved(library, 1)
        self.receiver = FakeReceiver(self.active)
        self.upstream_port = free_port()
        self.upstream = ThreadingHTTPServer(('127.0.0.1', self.upstream_port), FakeOp25)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)
        self.port = free_port()
        self.server, self.control = sup.build(self.temp.name, self.port, self.upstream_port,
            bind='127.0.0.1', receiver=self.receiver, key_provider=lambda: 'k', rr_factory=Mock())
        self.control.family = 'rtl'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        FakeOp25.seen = []

    def call(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        merged = {'Host': host if host is not None else f'127.0.0.1:{self.port}', **(headers or {})}
        conn.request(method, path, json.dumps(body) if body is not None else None, merged)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data, response

    def token(self):
        return json.loads(self.call('GET', '/brutal/api/session')[1])['token']

    def post(self, path, body, token=True, headers=None):
        merged = {'X-Brutal-Token': self.token() if token is True else (token or ''), **(headers or {})}
        status, data, _ = self.call('POST', '/brutal/api/' + path, body, merged)
        return status, json.loads(data)

    def test_dashboard_and_commands_pass_through_unchanged(self):
        status, data, response = self.call('GET', '/')
        self.assertEqual((status, data), (200, b'<html>op25 dashboard</html>'))
        self.assertEqual(response.getheader('Content-Type'), 'text/html')
        self.assertEqual(self.call('GET', '/images/x.png')[1], b'png-bytes')
        status, data, _ = self.call('POST', '/', [{'command': 'update', 'arg1': 0, 'arg2': 0}],
                                    {'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)['echo'][0]['command'], 'update')
        self.assertEqual(FakeOp25.seen[0][0:1] + FakeOp25.seen[0][2:3], ('/', 'application/json'))
        self.call('POST', '/', [{'command': 'update'}], {'X-Brutal-Token': 'sensitive'})
        self.assertIsNone(FakeOp25.seen[-1][4])

    def test_empty_dashboard_serves_systems_panel_without_upstream(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        self.control.seed_hardware = {**HARDWARE, 'profile': 'rtlv4'}
        self.control.can_listen = False
        self.receiver.profile = None
        self.receiver.state = 'stopped'
        status, page, response = self.call('GET', '/', headers={'Accept': 'text/html'})
        self.assertEqual(status, 200)
        self.assertIn(b'Your system library', page)
        self.assertIn(b'/brutal/systems.js', page)
        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
        self.assertIn(b'function', self.call('GET', '/brutal/systems.js')[1])
        self.assertIn(b'--brutal-panel', self.call('GET', '/brutal/ui.css')[1])
        self.assertFalse(json.loads(self.call('GET', '/brutal/api/session')[1])['can_listen'])

    def test_plot_frames_are_never_cached_but_other_files_keep_their_headers(self):
        for path in ('/images/plot-0-fft-207.png', '/plot-1-symbol-3.png?x=1'):
            _, data, response = self.call('GET', path)
            self.assertEqual(data, b'png-bytes')
            self.assertEqual(response.getheader('Cache-Control'), 'no-store', path)
            self.assertIsNone(response.getheader('ETag'), path)
        for path in ('/main.css', '/images/1x1.png', '/images/plot-notes.txt', '/images/plot-0-fft.png.bak'):
            _, _, response = self.call('GET', path)
            self.assertEqual(response.getheader('Cache-Control'), 'public, max-age=3600', path)
            self.assertEqual(response.getheader('ETag'), '"upstream-tag"', path)
        self.assertEqual(self.call('GET', '/images/plot-0-fft-207.png')[2].getheader('Content-Length'), '9')

    def test_receiver_down_is_a_clear_502_not_a_hang(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        status, data, _ = self.call('GET', '/')
        self.assertEqual(status, 502)
        self.assertIn('restarting', json.loads(data)['error'])
        self.assertEqual(self.call('GET', '/brutal/api/status')[0], 200)  # control stays up

    def test_opening_the_dashboard_while_down_gives_a_recovery_page(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        status, data, response = self.call('GET', '/', headers={'Accept': 'text/html,application/xhtml+xml'})
        self.assertEqual(status, 503)
        self.assertIn('text/html', response.getheader('Content-Type'))
        self.assertIn(b'Restart receiver', data)
        self.assertIn(b'/brutal/api/', data)
        self.assertNotIn(b'innerHTML', data)  # names are inserted as text, never parsed as markup
        # API-style requests still get machine-readable errors, never HTML.
        self.assertEqual(self.call('GET', '/images/plot.png', headers={'Accept': 'image/png'})[0], 502)
        self.assertEqual(self.call('POST', '/', [{'command': 'update'}], {'Accept': 'text/html'})[0], 502)
        self.assertEqual(self.call('GET', '/main.js', headers={'Accept': 'text/html'})[0], 502)

    def test_logo_is_served_by_the_supervisor_even_while_the_receiver_is_down(self):
        status, data, response = self.call('GET', '/brutal/logo.png')
        self.assertEqual((status, response.getheader('Content-Type')), (200, 'image/png'))
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        self.assertGreater(len(data), 1000)
        self.upstream.shutdown()
        self.upstream.server_close()
        self.assertEqual(self.call('GET', '/brutal/logo.png')[0], 200)
        self.assertEqual(self.call('GET', '/brutal/logo.png', host='evil.example')[0], 403)
        page = self.call('GET', '/', headers={'Accept': 'text/html'})[1]
        self.assertIn(b'src="/brutal/logo.png"', page)

    def test_foreign_host_names_are_rejected_for_everything(self):
        for path in ('/', '/brutal/api/status', '/brutal/api/session'):
            self.assertEqual(self.call('GET', path, host='evil.example:80')[0], 403)
        for tricky in ('127.0.0.1.evil.example:80', 'localhost.evil.example', '', 'evil.example:127.0.0.1'):
            self.assertEqual(self.call('GET', '/brutal/api/status', host=tricky)[0], 403, tricky)
        self.assertEqual(self.call('GET', '/', host=f'localhost:{self.port}')[0], 200)
        # The host-side published port may differ from the listening port; the name is what matters.
        self.assertEqual(self.call('GET', '/brutal/api/status', host='127.0.0.1:18080')[0], 200)
        self.assertEqual(self.call('GET', '/brutal/api/status', host='[::1]:8080')[0], 200)
        self.assertEqual(FakeOp25.seen, [])

    def test_changes_need_the_session_token_and_a_local_origin(self):
        self.assertEqual(self.post('systems/activate', {'id': self.other['id']}, token='')[0], 403)
        self.assertEqual(self.post('systems/activate', {'id': self.other['id']}, token='wrong')[0], 403)
        status, body = self.post('systems/activate', {'id': self.other['id']},
                                 headers={'Origin': 'http://evil.example'})
        self.assertEqual(status, 403)
        self.assertEqual(self.receiver.switched, [])
        # Another local page (different port) is a different origin even though the host name is loopback.
        status, body = self.post('systems/activate', {'id': self.other['id']},
                                 headers={'Origin': f'http://127.0.0.1:{self.port + 1}'})
        self.assertEqual(status, 403)
        status, body = self.post('systems/activate', {'id': self.other['id']},
                                 headers={'Origin': f'http://127.0.0.1:{self.port}'})
        self.assertEqual((status, self.receiver.switched), (200, [self.other['id']]))

    def test_upstream_commands_reject_cross_site_posts(self):
        for headers in ({'Origin': 'http://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            status, _, _ = self.call('POST', '/', [{'command': 'update'}], headers)
            self.assertEqual(status, 403)
        self.assertEqual(FakeOp25.seen, [])
        self.assertEqual(self.call('POST', '/', [{'command': 'update'}],
                                   {'Origin': f'http://127.0.0.1:{self.port}'})[0], 200)

    def test_malformed_proxy_length_gets_a_client_error(self):
        with socket.create_connection(('127.0.0.1', self.port), timeout=5) as conn:
            conn.sendall((f'POST / HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                          'Content-Length: invalid\r\n\r\n').encode())
            response = conn.recv(1024)
        self.assertIn(b'400', response.split(b'\r\n', 1)[0])
        self.assertEqual(FakeOp25.seen, [])

    def test_api_round_trip_and_errors_are_json(self):
        listing = json.loads(self.call('GET', '/brutal/api/systems')[1])
        self.assertEqual(len(listing['systems']), 2)
        self.assertEqual(self.call('GET', '/brutal/api/nothing')[0], 404)
        self.assertEqual(self.post('systems/nothing', {})[0], 404)
        status, body = self.post('systems/remove', {'id': self.active['id']})
        self.assertEqual(status, 400)
        self.assertIn('Switch to another system', body['error'])
        status, body = self.post('systems/manual', {'name': 'M', 'site': 'S', 'frequencies': '851.0'})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(self.call('GET', '/brutal/api/systems')[1])['systems']), 3)

    def test_api_does_not_treat_text_as_true_for_radio_actions(self):
        baseline = len(json.loads(self.call('GET', '/brutal/api/systems')[1])['systems'])
        for body in ({'name': 'M', 'site': 'S', 'frequencies': '851.0', 'tdma': 'false'},
                     {'name': 'M', 'site': 'S', 'frequencies': '851.0', 'activate': 'false'}):
            self.assertEqual(self.post('systems/manual', body)[0], 400)
        self.assertEqual(len(json.loads(self.call('GET', '/brutal/api/systems')[1])['systems']), baseline)

    def test_talkgroups_and_settings_endpoints(self):
        data = json.loads(self.call('GET', '/brutal/api/talkgroups')[1])
        self.assertEqual(data['profile']['id'], self.active['id'])
        self.assertGreater(len(data['talkgroups']), 100)
        target = data['talkgroups'][0]['id']
        self.assertEqual(self.post('systems/settings', {'priority_tgids': [target]}, token='')[0], 403)
        self.assertEqual(self.receiver.switched, [])
        status, body = self.post('systems/settings', {'priority_tgids': [target]})
        self.assertEqual(status, 200)
        self.assertTrue(body['saved'])
        self.assertEqual(self.receiver.switched, [self.active['id']])
        status, body = self.post('systems/settings', {'hold_time': 500})
        self.assertEqual(status, 400)
        self.assertIn('Hold time', body['error'])
        status, body = self.post('systems/settings', {'priority_tgids': [target], 'blocked_tgids': [target]})
        self.assertEqual(status, 400)
        self.assertEqual(self.post('rr/categories', {})[0], 400)  # not signed in

    def test_oversized_and_malformed_requests_are_rejected(self):
        token = self.token()
        for payload in ('[1,2]', 'x' * 200000):
            conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
            conn.request('POST', '/brutal/api/systems/activate', payload,
                         {'Host': f'127.0.0.1:{self.port}', 'X-Brutal-Token': token})
            response = conn.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            conn.close()


class CommandTests(unittest.TestCase):
    def test_rtl_and_rsp_profiles_use_the_right_entrypoints_and_private_port(self):
        rtl = {'settings': {'hardware': {'profile': 'rtlv4'}}}
        rsp = {'settings': {'hardware': {'profile': 'rspdxr2'}}}
        cmd, env = sup.receiver_command(rtl, 18080, '/data')
        self.assertTrue(cmd[1].endswith('container_receiver.py') and cmd[2] == 'run')
        self.assertEqual(env['OP25_HTTP_BIND'], '127.0.0.1:18080')
        cmd, env = sup.receiver_command(rsp, 18080, '/data', rsp_serial='24052A9770')
        self.assertTrue(cmd[1].endswith('rsp_receiver.py'))
        self.assertEqual(env['OP25_DATA_DIR'], '/data')
        self.assertEqual(env['OP25_RSP_SERIAL'], '24052A9770')
        with self.assertRaisesRegex(ValueError, 'validated RSP serial'):
            sup.receiver_command(rsp, 18080, '/data', rsp_serial='')

    def test_receiver_binds_selected_rsp_serial_for_dashboard_starts(self):
        rsp = {'settings': {'hardware': {'profile': 'rspdxr2'}}}
        receiver = sup.Receiver('/tmp/brutal-test', rsp_serial='24052A9770')
        command, env = receiver.command_for(rsp, 18080)
        self.assertTrue(command[1].endswith('rsp_receiver.py'))
        self.assertEqual(env['OP25_RSP_SERIAL'], '24052A9770')

    def test_windows_rsp_stream_needs_no_linux_sdrplay_serial(self):
        rsp = {'settings': {'hardware': {'profile': 'rspdxr2'}}}
        with patch.dict('os.environ', {'BRUTAL_RSP_TCP_ADDR': '172.20.208.1:1234'}, clear=True):
            command, env = sup.receiver_command(rsp, 18080, '/data', rsp_serial='')
        self.assertTrue(command[1].endswith('rsp_receiver.py'))
        self.assertEqual(env['OP25_RSP_TCP_ADDR'], '172.20.208.1:1234')
        with patch.dict('os.environ', {'BRUTAL_RSP_TCP_ADDR': '8.8.8.8:1234'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'private address'):
                sup.receiver_command(rsp, 18080, '/data', rsp_serial='')


if __name__ == '__main__':
    unittest.main()
