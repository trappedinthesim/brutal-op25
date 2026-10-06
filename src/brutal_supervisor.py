"""Keep OP25 running behind a small control server so systems can be added and switched in the browser.

The dashboard talks to one address (127.0.0.1:8080). This module answers /brutal/api/* itself and
proxies everything else to OP25, which listens on a private loopback port. Switching systems restarts
OP25 for a few seconds; the control page stays available throughout. No Docker or USB control is
exposed here, and a switch is limited to the radio family the container was started with.
"""
from copy import deepcopy
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from container_receiver import prepare
from importer import DEFAULT_CRYPT_BEHAVIOR, RadioReference, application_key, normalize_categories
from library import ProfileLibrary
from test_connection import frequency_hz, clean_label

PUBLIC_PORT = 8080
INTERNAL_PORT = 18080
RR_SESSION_TTL = 1800
FAMILY = {'rtl': 'rtl', 'rtlv4': 'rtl', 'rspdxr2': 'rsp'}
LOCAL_NAMES = {'127.0.0.1', 'localhost', '[::1]'}
PLOT_FRAME = re.compile(r'/plot-[A-Za-z0-9_.-]+\.png$')
try:  # served by the supervisor itself so it shows even while OP25 is down (recovery page)
    LOGO = (Path(__file__).resolve().parent / 'brutal-logo.png').read_bytes()
except OSError:
    LOGO = b''
HOP_BY_HOP = {'connection', 'keep-alive', 'proxy-connection', 'transfer-encoding', 'upgrade',
              'te', 'trailer', 'content-length'}


RECOVERY_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brutal OP25 // Receiver not running</title><style>
:root{color-scheme:dark}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0d1013;color:#aab3be;font:14px/1.5 "Segoe UI",Arial,sans-serif}
main{width:min(560px,92vw);padding:24px;background:#14181d;border:1px solid #38404a;border-top:2px solid #4c90f0}
h1{display:flex;align-items:center;gap:12px;margin:0 0 4px;color:#f1f3f5;font-size:13px;letter-spacing:.16em;text-transform:uppercase}h1 img{display:block}h1 b{color:#4c90f0}
#state{margin:14px 0 2px;color:#4c90f0;font-weight:700;letter-spacing:.12em}#msg{min-height:22px;color:#aab3be}
button{margin:6px 6px 0 0;padding:9px 14px;background:#1a1f25;color:#f1f3f5;border:1px solid #38404a;font:600 11px/1.2 inherit;letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
button:hover{border-color:#4c90f0}button.p{border-color:#4c90f0}h2{margin:20px 0 4px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#6f7b89}
.e{color:#ef5f66}</style></head><body><main><h1><img src="/brutal/logo.png" width="34" height="34" alt=""><span>Brutal <b>OP25</b> // Receiver</span></h1><div id="state">CHECKING…</div><div id="msg"></div>
<button class="p" id="restart">Restart receiver</button><h2>Or listen to a saved system</h2><div id="list"></div></main><script>
(async()=>{const $=id=>document.getElementById(id);let token=null;
const api=async(p,b)=>{const o=b===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Brutal-Token':token||''},body:JSON.stringify(b)};
const r=await fetch('/brutal/api/'+p,{cache:'no-store',...o});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||('Request failed ('+r.status+')'));return d};
const fail=e=>{$('msg').textContent=e.message;$('msg').className='e'};
async function tick(){try{const s=await api('status');$('state').textContent=s.state.toUpperCase();
if(s.state==='running'){location.reload();return}$('msg').className='';$('msg').textContent=s.message||'The receiver is not running.'}
catch(e){$('state').textContent='UNREACHABLE';fail(e)}}
try{token=(await api('session')).token}catch(e){fail(e)}
$('restart').onclick=()=>api('receiver/restart',{}).then(tick).catch(fail);
try{const d=await api('systems');for(const s of d.systems){const b=document.createElement('button');b.textContent=s.name+(s.active?' (current)':'');b.disabled=!s.compatible;
b.onclick=()=>api('systems/activate',{id:s.id}).then(tick).catch(fail);$('list').append(b)}}catch(e){fail(e)}
tick();setInterval(tick,2000)})();
</script></body></html>"""


EMPTY_DASHBOARD = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brutal OP25 // Systems</title><link rel="stylesheet" href="/brutal/ui.css"></head>
<body><main style="max-width:900px;margin:70px auto;padding:24px;background:var(--brutal-panel);border:1px solid var(--brutal-line-hi);border-top:2px solid var(--brutal-accent)">
<img src="/brutal/logo.png" width="48" height="48" alt=""><h1 style="color:var(--text-1);font-size:22px">Brutal OP25</h1>
<p>Built on boatbod/op25 · Local receiver dashboard</p>
<div class="ops-context"><span id="brutal-ctx-dot"></span><strong id="brutal-ctx-system">NO SYSTEM</strong><span id="brutal-ctx-session">SETUP</span></div>
<h2 style="color:var(--text-1)">Your system library</h2><p>Use Systems to add one or more P25 systems from RadioReference or enter control channels manually. Nothing is listening until you select a saved system and have a connected radio.</p>
<button class="brutal-btn primary" onclick="brutalSystems.open('saved')">Open Systems</button>
<p id="radio-hint" role="status"></p></main><script src="/brutal/systems.js" defer></script>
<script>window.addEventListener('DOMContentLoaded',async()=>{try{const s=await (await fetch('/brutal/api/session',{cache:'no-store'})).json();document.getElementById('radio-hint').textContent=s.can_listen?'Radio connected: you can start a saved system here.':'Radio not connected: save systems here, then relaunch with the guided radio connection to listen.';brutalSystems.open('saved')}catch(e){document.getElementById('radio-hint').textContent='The local control service is unavailable.'}})</script>
</body></html>"""


def family_of(profile):
    return FAMILY.get(profile['settings']['hardware'].get('profile'))


def receiver_command(profile, internal_port, root, rsp_serial=None):
    """Command and environment that start OP25 for one saved profile."""
    here = Path(__file__).resolve().parent
    env = {**os.environ, 'OP25_HTTP_BIND': f'127.0.0.1:{internal_port}', 'OP25_DATA_DIR': str(root)}
    if family_of(profile) == 'rsp':
        from rsp_receiver import network_arguments, selected_arguments
        network = env.get('OP25_RSP_TCP_ADDR') or env.get('BRUTAL_RSP_TCP_ADDR')
        if network:
            network_arguments(network)
            env['OP25_RSP_TCP_ADDR'] = network
        else:
            serial = env.get('OP25_RSP_SERIAL', '') if rsp_serial is None else rsp_serial
            selected_arguments(serial)  # Fail before spawning a receiver that cannot bind the selected radio.
            env['OP25_RSP_SERIAL'] = serial
        return [sys.executable, str(here / 'rsp_receiver.py')], env
    return [sys.executable, str(here / 'container_receiver.py'), 'run'], env


class Receiver:
    """Owns the OP25 child process: start, stop, switch, and report honest state."""

    def __init__(self, root, internal_port=INTERNAL_PORT, command_for=None, prepare_fn=prepare,
                 stop_timeout=10, ready_timeout=90, release_delay=1.0, rsp_serial=None):
        self.root = Path(root)
        self.internal_port = internal_port
        self.release_delay = release_delay
        self.command_for = command_for or (lambda profile, port: receiver_command(profile, port, self.root, rsp_serial))
        self.prepare = prepare_fn
        self.stop_timeout, self.ready_timeout = stop_timeout, ready_timeout
        self.lock = threading.RLock()
        self.child = None
        self.profile = None
        self.state = 'stopped'  # starting | running | switching | stopped | error
        self.message = ''
        self.started = None
        self.restarts = 0
        self.last_exit = None

    def probe(self):
        conn = None
        try:
            conn = http.client.HTTPConnection('127.0.0.1', self.internal_port, timeout=1)
            conn.request('GET', '/')
            status = conn.getresponse().status
            return status < 500
        except (OSError, http.client.HTTPException):
            return False
        finally:
            if conn is not None:
                conn.close()

    def start(self, profile):
        with self.lock:
            if self.child is not None and self.child.poll() is None:
                raise ValueError('The receiver is already running')
            self.prepare(self.root, profile['id'])
            command, env = self.command_for(profile, self.internal_port)
            child = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL)
            self.child, self.profile = child, profile
            self.state, self.message, self.started, self.last_exit = 'starting', '', time.time(), None
        threading.Thread(target=self._watch, args=(child,), daemon=True).start()

    def _watch(self, child):
        ready, deadline = False, time.monotonic() + self.ready_timeout
        while child.poll() is None:
            if not ready and self.probe():
                ready = True
                with self.lock:
                    if self.child is child:
                        self.state, self.message = 'running', ''
            elif not ready and time.monotonic() > deadline:
                with self.lock:
                    if self.child is child:
                        self.state, self.message = 'error', 'The receiver did not start in time. Check the terminal output.'
                deadline = float('inf')
            time.sleep(0.4)
        with self.lock:
            if self.child is child:
                self.child, self.last_exit = None, child.returncode
                if child.returncode in (0, -signal.SIGTERM, -signal.SIGINT):
                    self.state, self.message = 'stopped', 'The receiver stopped.'
                else:
                    self.state = 'error'
                    self.message = f'The receiver exited unexpectedly (code {child.returncode}). Check the terminal output.'

    def stop(self):
        with self.lock:
            child, self.child = self.child, None
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(self.stop_timeout)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        with self.lock:
            if self.state != 'switching':
                self.state = 'stopped'

    def switch(self, profile):
        """Begin switching in the background. Returns immediately; poll status for the result."""
        with self.lock:
            if self.state == 'switching':
                raise ValueError('A switch is already in progress')
            self.state, self.message = 'switching', 'Switching to ' + profile['name']
        threading.Thread(target=self._switch, args=(profile,), daemon=True).start()

    def _switch(self, profile):
        try:
            self.stop()  # state stays 'switching' until the new receiver reports 'starting'
            time.sleep(self.release_delay)  # let the USB device release before re-opening it
            with self.lock:
                self.restarts += 1
            self.start(profile)
        except Exception as exc:  # report, never leave the UI waiting on 'switching'
            with self.lock:
                self.state, self.message = 'error', 'Could not start that system: ' + str(exc)

    def status(self):
        with self.lock:
            running = self.state == 'running' and self.started
            return {'state': self.state, 'message': self.message, 'restarts': self.restarts,
                    'uptime_s': int(time.time() - self.started) if running else 0,
                    'last_exit': self.last_exit}


class Control:
    """Everything the Systems panel can do. Pure logic: no HTTP in here, so it is easy to test."""

    def __init__(self, root, receiver, library, rr_factory=RadioReference, key_provider=application_key,
                 clock=time.monotonic, seed_hardware=None, can_listen=True):
        self.root, self.receiver, self.library = Path(root), receiver, library
        self.rr_factory, self.key_provider, self.clock = rr_factory, key_provider, clock
        self.rr, self.rr_used, self.pending = None, 0.0, None
        self.lock = threading.RLock()
        self.seed_hardware = deepcopy(seed_hardware) if seed_hardware else None
        self.can_listen = can_listen
        self.family = (family_of(receiver.profile) if receiver.profile else
                       FAMILY.get(seed_hardware.get('profile')) if seed_hardware else None)

    # ----- state -----
    def status(self):
        report = self.receiver.status()
        profile = self.receiver.profile
        site = None
        if profile:
            site = next((s for s in profile['system']['sites'] if s['id'] == profile['settings']['site_id']), None)
        report.update(active=None if not profile else {
            'id': profile['id'], 'name': profile['name'], 'system': profile['system']['name'],
            'site': site['name'] if site else '', 'hardware': profile['settings']['hardware'].get('profile')},
            family=self.family, rr_connected=self.rr_connected())
        return report

    def rr_connected(self):
        """Read-only check: polling status must not keep the sign-in alive."""
        with self.lock:
            if self.rr is not None and self.clock() - self.rr_used > RR_SESSION_TTL:
                self._close_rr()
            return self.rr is not None

    def session(self):
        try:
            self.key_provider()
            enabled = True
        except ValueError:
            enabled = False
        return {'family': self.family, 'rr_enabled': enabled, 'can_listen': self.can_listen,
                'hardware': self.seed_hardware['profile'] if self.seed_hardware else None}

    def systems(self):
        active = self.receiver.profile['id'] if self.receiver.profile else None
        rows = []
        for profile in self.library.list():
            site = next((s for s in profile['system']['sites'] if s['id'] == profile['settings']['site_id']), {})
            compatible_radio = family_of(profile) == self.family
            compatible = compatible_radio and self.can_listen
            rows.append({'id': profile['id'], 'name': profile['name'], 'system': profile['system']['name'],
                'site': site.get('name', 'Missing site'), 'control_channels': len(site.get('controls_hz', [])),
                'talkgroups': len(profile['system']['talkgroups']), 'source': profile['settings']['source'],
                'hardware': profile['settings']['hardware'].get('profile'), 'active': profile['id'] == active,
                'compatible': compatible,
                'reason': '' if compatible else ('Connect the selected radio through the guided launcher to listen.'
                    if compatible_radio else 'Saved for a different radio than the one connected now.')})
        return {'systems': rows, 'unreadable': list(self.library.unreadable)}

    # ----- switching -----
    def activate(self, identity):
        if not self.can_listen:
            raise ValueError('Radio is not connected. Save systems now, then relaunch through the guided USB setup to listen.')
        profile = self.library.read(identity)
        if family_of(profile) != self.family:
            raise ValueError('This system is saved for a different radio than the one connected now. '
                             'Relaunch with that radio to listen to it.')
        self.receiver.switch(profile)
        return self.status()

    def restart(self):
        if not self.receiver.profile:
            raise ValueError('No system is active')
        self.receiver.switch(self.library.read(self.receiver.profile['id']))
        return self.status()

    def remove(self, identity):
        if self.receiver.profile and identity == self.receiver.profile['id']:
            raise ValueError('Switch to another system before removing the one that is listening.')
        profile = self.library.remove(identity)
        return {'removed': profile['name']}

    # ----- listening preferences for the system that is listening -----
    def _active(self):
        if not self.receiver.profile:
            raise ValueError('No system is listening')
        return self.library.read(self.receiver.profile['id'])  # always the saved copy, never a stale one

    def talkgroups(self):
        profile = self._active()
        system, settings = profile['system'], profile['settings']
        names = {c['id']: c['name'] for c in system.get('categories', [])}
        listen_only = bool(settings.get('selected_only'))
        # A listen-only list made in the terminal is shown as Priority so the panel never hides what is active.
        priority = set(settings.get('priority_tgids', [])) | (set(settings.get('talkgroup_ids', [])) if listen_only else set())
        blocked = set(settings.get('blocked_tgids', []))
        counts, rows = {}, []
        for group in system['talkgroups']:
            try:
                category = int(group.get('category_id'))
            except (TypeError, ValueError):
                category = None
            counts[category] = counts.get(category, 0) + 1
            rows.append({'id': group['id'], 'label': group['label'], 'description': group.get('description', ''),
                         'mode': group.get('mode', ''), 'encrypted': int(group.get('encryption') or 0) > 0,
                         'category_id': category,
                         'state': 'blocked' if group['id'] in blocked else 'priority' if group['id'] in priority else 'normal'})
        categories = sorted(({'id': cid, 'count': n,
                              'name': names.get(cid) or ('Uncategorized' if cid is None else f'Category {cid}')}
                             for cid, n in counts.items()), key=lambda c: (c['name'].casefold(), c['id'] or 0))
        return {'profile': {'id': profile['id'], 'name': profile['name'], 'source': settings['source']},
                'talkgroups': rows, 'categories': categories, 'has_category_names': bool(names),
                'listen_only': listen_only, 'crypt_behavior': settings.get('crypt_behavior', DEFAULT_CRYPT_BEHAVIOR),
                'hold_time': settings.get('hold_time'), 'rid_labels': settings.get('rid_labels', {}),
                'revision': profile['revision']}

    SETTING_KEYS = {'priority_tgids', 'blocked_tgids', 'only_priority', 'rid_labels', 'crypt_behavior', 'hold_time'}

    def apply_settings(self, changes):
        """Save listening preferences as a new revision of the listening system, then restart onto it."""
        unknown = set(changes) - self.SETTING_KEYS
        if unknown:
            raise ValueError('Unknown setting: ' + ', '.join(sorted(unknown)))
        if self.receiver.status()['state'] == 'switching':
            raise ValueError('A switch is already in progress')
        profile = self._active()
        old = profile['settings']
        new = deepcopy(old)

        def ids(values):
            if not isinstance(values, list) or any(type(value) is not int for value in values):
                raise ValueError('Talkgroups must be given as a list of numbers')
            return set(values)

        if {'priority_tgids', 'blocked_tgids', 'only_priority'} & set(changes):
            derived = set(old.get('priority_tgids', [])) | (set(old.get('talkgroup_ids', [])) if old.get('selected_only') else set())
            priority = ids(changes['priority_tgids']) if 'priority_tgids' in changes else derived
            blocked = ids(changes['blocked_tgids']) if 'blocked_tgids' in changes else set(old.get('blocked_tgids', []))
            if 'only_priority' in changes and not isinstance(changes['only_priority'], bool):
                raise ValueError('Listen-only mode must be true or false')
            only = changes['only_priority'] if 'only_priority' in changes else bool(old.get('selected_only'))
            if only and not priority:
                raise ValueError('Mark at least one talkgroup as Priority first, or choose to listen to everything.')
            new.update(priority_tgids=sorted(priority), blocked_tgids=sorted(blocked), selected_only=only,
                       talkgroup_ids=sorted(priority) if only else [])
        if 'rid_labels' in changes:
            new['rid_labels'] = changes['rid_labels'] or {}
        if 'crypt_behavior' in changes:
            new['crypt_behavior'] = changes['crypt_behavior']
        if 'hold_time' in changes:
            if changes['hold_time'] is None:
                new.pop('hold_time', None)
            else:
                new['hold_time'] = changes['hold_time']
        if new == old:
            return {**self.status(), 'unchanged': True}
        saved = self.library.save(profile['system'], {**new, 'profile_id': profile['id'],
            'revision': profile['revision'], 'profile_name': profile['name'],
            'name_is_custom': profile.get('name_is_custom', False)})
        self.receiver.switch(saved)  # OP25 reads these files at startup, so a few seconds of silence
        return {**self.status(), 'saved': True}

    def refresh_categories(self):
        """Fetch category names for a system imported before categories were kept. Needs the RadioReference sign-in."""
        profile = self._active()
        if profile['settings']['source'] != 'radioreference':
            raise ValueError('Category names come from RadioReference; this system was added manually.')
        categories = normalize_categories(self._rr().categories(profile['system']['id']))
        if not categories:
            raise ValueError('RadioReference returned no category names for this system.')
        profile['system']['categories'] = categories  # names only: nothing the receiver reads changes
        self.library.write(profile)
        return {'categories': len(categories)}

    # ----- adding systems -----
    def _hardware(self):
        base = (self.receiver.profile['settings']['hardware'] if self.receiver.profile else self.seed_hardware)
        if not base:
            raise ValueError('No radio is active, so a new system cannot inherit its settings')
        return {key: base[key] for key in ('profile', 'args', 'rate', 'gains', 'ppm') if key in base}

    def _rr(self, required=True):
        with self.lock:
            if self.rr is not None and self.clock() - self.rr_used > RR_SESSION_TTL:
                self._close_rr()
            if self.rr is None:
                if required:
                    raise ValueError('Sign in to RadioReference first')
                return None
            self.rr_used = self.clock()
            return self.rr

    def _close_rr(self):
        if self.rr is not None:
            self.rr.close()
        self.rr, self.pending = None, None

    def rr_login(self, username, password):
        key = self.key_provider()  # fail before touching any credentials
        username = str(username or '').strip()
        if not username or not password:
            raise ValueError('Username and password are required')
        with self.lock:
            self._close_rr()
            try:
                self.rr = self.rr_factory(username, password, key)
            except Exception:
                # Library errors can echo request details; never relay them.
                raise ValueError('Could not connect to RadioReference. Account access, network availability '
                                 'or the app authorization may be responsible; this does not confirm your '
                                 'password is wrong.') from None
            finally:
                password = key = ''
            self.rr_used = self.clock()
        return {'connected': True}

    def rr_logout(self):
        with self.lock:
            self._close_rr()
        return {'connected': False}

    def rr_browse(self, level, identity=None):
        return self._rr().browse(level, identity)

    def rr_system(self, identity):
        system = self._rr().system(int(identity))
        with self.lock:
            self.pending = system
        return {'id': system['id'], 'name': system['name'], 'type': system['type'],
                'talkgroups': len(system['talkgroups']), 'import_warnings': system.get('import_warnings', []),
                'sites': [{'id': s['id'], 'name': s['name'], 'control_channels': len(s['controls_hz']),
                           'selectable': bool(s['controls_hz']), 'warnings': s['warnings']}
                          for s in system['sites']]}

    def save_pending(self, site_id, activate=False):
        with self.lock:
            system = self.pending
        if not system:
            raise ValueError('Choose a system first')
        site_id = int(site_id)
        site = next((s for s in system['sites'] if s['id'] == site_id), None)
        if site is None or not site['controls_hz']:
            raise ValueError('Choose a site that lists control channels')
        for existing in self.library.list():
            if existing['system']['id'] == system['id'] and existing['settings']['site_id'] == site_id:
                raise ValueError(f"'{existing['name']}' is already saved. Use Listen on the Saved tab.")
        profile = self.library.save(system, {'hardware': self._hardware(), 'site_id': site_id,
            'source': 'radioreference', 'demod': 'cqpsk', 'selected_only': False, 'talkgroup_ids': []})
        return self._saved(profile, activate)

    def save_manual(self, name, site, frequencies, tdma=False, activate=False):
        name, site = clean_label(name), clean_label(site)
        if not name or not site:
            raise ValueError('System and site names are required')
        values = list(dict.fromkeys(frequency_hz(v.strip()) for v in str(frequencies or '').split(',')))
        system = {'id': 0, 'name': name, 'type': 'P25 (user selected)', 'talkgroups': [],
                  'sites': [{'id': 1, 'name': site, 'controls_hz': values, 'nac': '0x0',
                             'tdma_cc': bool(tdma), 'warnings': []}]}
        profile = self.library.save(system, {'hardware': self._hardware(), 'site_id': 1, 'source': 'manual'})
        return self._saved(profile, activate)

    def _saved(self, profile, activate):
        result = {'saved': {'id': profile['id'], 'name': profile['name']}}
        if activate:
            self.activate(profile['id'])
        return result

    def shutdown(self):
        with self.lock:
            self._close_rr()


def make_handler(control, internal_port):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'BrutalOP25'

        def log_message(self, *_):
            pass  # No request or credential logging.

        # ----- guards -----
        def host_ok(self):
            # Rebinding attacks arrive under the attacker's hostname, so check the name, not the port:
            # the host-side published port may differ from the one this server listens on.
            host = self.headers.get('Host', '')
            name = host[:host.index(']') + 1] if host.startswith('[') and ']' in host else host.split(':')[0]
            return name in LOCAL_NAMES

        def json(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def route(self, method):
            # Reject DNS-rebinding: only the loopback names the launcher publishes are accepted.
            if not self.host_ok():
                return self.json(403, {'error': 'Invalid local host'})
            if method == 'POST' and not self.same_origin():
                return self.json(403, {'error': 'Invalid origin'})
            if method == 'GET' and self.path.split('?', 1)[0] == '/brutal/logo.png' and LOGO:
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Content-Length', str(len(LOGO)))
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                self.wfile.write(LOGO)
                return
            if method == 'GET' and self.path.split('?', 1)[0] in ('/brutal/ui.css', '/brutal/systems.js'):
                name = 'brutal-ui.css' if self.path.split('?', 1)[0].endswith('.css') else 'brutal-systems.js'
                body = (Path(__file__).resolve().parent / name).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/css; charset=utf-8' if name.endswith('.css') else 'text/javascript; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.split('?', 1)[0].startswith('/brutal/api/'):
                return self.api(method)
            if (method == 'GET' and self.path.split('?', 1)[0] in ('/', '/index.html')
                    and control.seed_hardware and control.receiver.profile is None):
                body = EMPTY_DASHBOARD.encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)
                return
            return self.proxy(method)

        def do_GET(self):
            self.route('GET')

        def do_POST(self):
            self.route('POST')

        def same_origin(self):
            # Browser form posts to the upstream OP25 proxy need the same CSRF guard
            # as control API posts. Non-browser local clients normally omit Origin.
            origin = self.headers.get('Origin')
            return (not origin or origin == 'http://' + self.headers.get('Host', '')) and \
                self.headers.get('Sec-Fetch-Site', '') != 'cross-site'

        # ----- control API -----
        def api(self, method):
            path = self.path.split('?', 1)[0][len('/brutal/api/'):]
            try:
                if method == 'GET':
                    routes = {'session': lambda: {**control.session(), 'token': self.server.token},
                              'status': control.status, 'systems': control.systems,
                              'talkgroups': control.talkgroups}
                    if path not in routes:
                        return self.json(404, {'error': 'Not found'})
                    return self.json(200, routes[path]())
                if not secrets.compare_digest(self.headers.get('X-Brutal-Token', ''), self.server.token):
                    return self.json(403, {'error': 'Invalid session token'})
                size = int(self.headers.get('Content-Length', '0'))
                if size < 0 or size > 100000:
                    raise ValueError('Request too large')
                body = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(body, dict):
                    raise ValueError('Invalid request')
                def boolean(name):
                    value = body.get(name, False)
                    if not isinstance(value, bool):
                        raise ValueError(name + ' must be true or false')
                    return value
                actions = {
                    'systems/activate': lambda: control.activate(body.get('id')),
                    'systems/remove': lambda: control.remove(body.get('id')),
                    'systems/save': lambda: control.save_pending(body.get('site_id'), boolean('activate')),
                    'systems/manual': lambda: control.save_manual(body.get('name'), body.get('site'),
                        body.get('frequencies'), boolean('tdma'), boolean('activate')),
                    'systems/settings': lambda: control.apply_settings(body),
                    'receiver/restart': control.restart,
                    'rr/login': lambda: control.rr_login(body.get('username'), body.get('password')),
                    'rr/logout': control.rr_logout,
                    'rr/browse': lambda: control.rr_browse(body.get('level'), body.get('id')),
                    'rr/system': lambda: control.rr_system(body.get('id')),
                    'rr/categories': control.refresh_categories,
                }
                if path not in actions:
                    return self.json(404, {'error': 'Not found'})
                return self.json(200, actions[path]())
            except (ValueError, KeyError, TypeError) as exc:
                return self.json(400, {'error': str(exc)})
            except Exception:
                return self.json(500, {'error': 'Unexpected error. Credentials were not logged.'})

        # ----- transparent proxy to OP25 -----
        def proxy(self, method):
            body = None
            if method == 'POST':
                try:
                    size = int(self.headers.get('Content-Length', '0') or 0)
                except ValueError:
                    return self.json(400, {'error': 'Invalid request length'})
                if size < 0 or size > 1000000:
                    return self.json(413, {'error': 'Request too large'})
                body = self.rfile.read(size)
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in HOP_BY_HOP | {'x-brutal-token'}}
            conn = None
            try:
                conn = http.client.HTTPConnection('127.0.0.1', internal_port, timeout=15)
                conn.request(method, self.path, body, headers)
                response = conn.getresponse()
                data = response.read()
            except (OSError, http.client.HTTPException):
                wants_page = (method == 'GET' and self.path.split('?', 1)[0] in ('/', '/index.html')
                              and 'text/html' in self.headers.get('Accept', ''))
                if wants_page:  # opening the dashboard while OP25 is down: give a way back, not a bare error
                    body = RECOVERY_PAGE.encode()
                    self.send_response(503)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(body)
                    return
                return self.json(502, {'error': 'The receiver is starting or restarting. Try again in a few seconds.'})
            finally:
                if conn is not None:
                    conn.close()
            # Every plot frame has a unique file name that is never requested again, so the browser
            # caching them (memory and disk) is pure waste. Everything else keeps upstream's headers.
            frame = method == 'GET' and PLOT_FRAME.search(self.path.split('?', 1)[0]) is not None
            skip = HOP_BY_HOP | ({'cache-control', 'etag', 'last-modified', 'expires'} if frame else set())
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in skip:
                    self.send_header(key, value)
            if frame:
                self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def build(root, public_port=PUBLIC_PORT, internal_port=INTERNAL_PORT, bind='0.0.0.0', receiver=None,
          rr_factory=RadioReference, key_provider=application_key, seed_hardware=None, can_listen=True):
    root = Path(root)
    library = ProfileLibrary(root / 'saved-profiles')
    receiver = receiver or Receiver(root, internal_port)
    control = Control(root, receiver, library, rr_factory, key_provider,
                      seed_hardware=seed_hardware, can_listen=can_listen)
    server = ThreadingHTTPServer((bind, public_port), make_handler(control, internal_port))
    server.token = secrets.token_urlsafe(32)
    server.daemon_threads = True
    return server, control


def serve_setup(root, hardware, can_listen=False, public_port=PUBLIC_PORT, internal_port=INTERNAL_PORT,
                rr_factory=RadioReference, key_provider=application_key, rsp_serial=None):
    """Use the regular Systems panel before a first profile exists; no receiver starts implicitly."""
    if can_listen and hardware.get('profile') == 'rspdxr2' and not os.environ.get('BRUTAL_RSP_TCP_ADDR'):
        from rsp_receiver import selected_arguments
        try:
            selected_arguments(rsp_serial or '')
        except ValueError:
            print('RSPdx-R2 serial could not be read. Systems can be saved, but listening is disabled for this session.',
                  flush=True)
            can_listen = False
    receiver = Receiver(root, internal_port, rsp_serial=rsp_serial)
    server, control = build(root, public_port, internal_port, receiver=receiver,
                            rr_factory=rr_factory, key_provider=key_provider,
                            seed_hardware=hardware, can_listen=can_listen)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'Systems dashboard: http://127.0.0.1:{public_port}/  (Ctrl+C closes it)', flush=True)
    try:
        while not stop.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        receiver.stop()
        control.shutdown()
        server.shutdown()
        server.server_close()
    return bool(control.library.list())


def serve(root, public_port=PUBLIC_PORT, internal_port=INTERNAL_PORT, rr_factory=RadioReference,
          key_provider=application_key):
    """Run until the user stops it (Ctrl+C). OP25 crashing leaves the control page up for recovery."""
    root = Path(root)
    pointer = json.loads((root / 'receiver' / 'active.json').read_text(encoding='utf-8'))
    profile = ProfileLibrary(root / 'saved-profiles').read(pointer['profile_id'])
    receiver = Receiver(root, internal_port)
    server, control = build(root, public_port, internal_port, receiver=receiver,
                            rr_factory=rr_factory, key_provider=key_provider)
    control.family = family_of(profile)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'Receiver web UI: http://127.0.0.1:{public_port}/  (Ctrl+C stops the receiver)', flush=True)
    reported = None
    try:
        receiver.start(profile)
        while not stop.is_set():
            time.sleep(0.5)
            status = receiver.status()
            if status['state'] in ('stopped', 'error') and status['message'] != reported:
                reported = status['message']
                print(status['message'] + ' Open the dashboard to restart or switch systems; '
                      'Ctrl+C quits.', flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        receiver.stop()
        control.shutdown()
        server.shutdown()
        server.server_close()
    return 0
