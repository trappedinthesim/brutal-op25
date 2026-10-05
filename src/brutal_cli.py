"""Linux-first terminal onboarding. No browser, Docker socket, or saved secrets."""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import sys
from importer import PROFILES, RadioReference, application_key
from library import ProfileLibrary
from hardware_check import check_profile
from receiver_readiness import environment, usb_inventory, assess
from container_receiver import prepare, run
from brutal_supervisor import serve_setup
from terminal_art import banner, paint
from terminal_menu import can_scroll, scrolling_menu, MenuCancelled


class Cancelled(Exception):
    pass


class WindowsHandoff(BaseException):
    """Explicit process handoff, not a setup failure. Caught only at the entrypoint."""
    pass


def acquire_session_lock(root):
    """Keep one setup/receiver session per data volume, including across execv."""
    import fcntl

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / '.receiver-session.lock').open('a+')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.set_inheritable(handle.fileno(), True)
    except BlockingIOError:
        handle.close()
        raise ValueError('Another Brutal OP25 session is using this system library. '
                         'Close the other receiver window before starting this one.') from None
    except Exception:
        handle.close()
        raise
    return handle


def request_windows_connection(root, preset, resume_profile=None):
    nonce = os.environ.get('BRUTAL_HANDOFF_NONCE', '')
    if len(nonce) != 32 or any(c not in '0123456789abcdef' for c in nonce):
        raise ValueError('Windows launcher session is unavailable')
    if preset not in ('rtl', 'rtlv4', 'rspdxr2'):
        raise ValueError('Automatic USB connection supports RTL-SDR and RSPdx-R2 only')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / 'host-handoff.tmp'
    request = {'version': 1, 'action': 'connect_usb', 'preset': preset, 'nonce': nonce}
    if resume_profile:
        saved = ProfileLibrary(root / 'saved-profiles').read(resume_profile)
        if saved['settings']['hardware']['profile'] != preset:
            raise ValueError('Saved system SDR does not match the USB request')
        request['resume_listen'] = resume_profile
    temporary.write_text(json.dumps(request), encoding='utf-8')
    os.replace(temporary, root / 'host-handoff.json')
    raise WindowsHandoff()


def choose(title, items, label, prompt=input, output=print, default_index=None):
    """Paged number menus work with ordinary terminals, SSH and container TTYs."""
    if not items:
        raise ValueError('No entries available for ' + title)
    page = (default_index or 0) // 15
    while True:
        output('\n' + title)
        start = page * 15
        for index, item in enumerate(items[start:start + 15], start + 1):
            output(f'  {index:>3}. {label(item)}')
        hint = f'Choose 1-{len(items)} (q to cancel): ' if len(items) <= 15 else \
            f'Choose a number (1-{len(items)}) | n/p page | /search | q back: '
        if default_index is not None:
            hint += f'[Enter: {label(items[default_index])}] '
        value = prompt(hint).strip()
        if not value and default_index is not None:
            return items[default_index]
        if value.lower() == 'q':
            raise Cancelled()
        if value == 'n':
            page = min(page + 1, (len(items) - 1) // 15)
        elif value == 'p':
            page = max(0, page - 1)
        elif value.startswith('/'):
            match = next((i for i, item in enumerate(items)
                          if value[1:].casefold() in label(item).casefold()), None)
            if match is not None:
                page = match // 15
            else:
                output('No matching entry.')
        elif value.isdigit() and 1 <= int(value) <= len(items):
            return items[int(value) - 1]
        else:
            output('Choose a listed number.')


def profile_label(profile):
    site = next((s for s in profile['system']['sites']
                 if s['id'] == profile['settings']['site_id']), {})
    return (f"{profile['system']['name']} / {site.get('name', 'Missing site')} / "
            f"{profile['settings']['hardware']['profile']} · {profile['id'][:8]}")


def talkgroup_ids(text, system):
    available = {g['id'] for g in system['talkgroups']}
    try:
        values = sorted({int(value.strip()) for value in text.split(',')})
    except ValueError:
        raise ValueError('Enter comma-separated decimal talkgroup IDs') from None
    if not values or not set(values) <= available:
        raise ValueError('Select only IDs listed in this system')
    return values


class Terminal:
    def __init__(self, root, prompt=input, output=print, secret=getpass, rr_factory=RadioReference):
        self.root = Path(root).resolve()
        self.library = ProfileLibrary(self.root / 'saved-profiles')
        self.prompt = lambda message: prompt(paint(message))
        self.output = lambda message: output(paint(message))
        self.secret = lambda message: secret(paint(message))
        self.rr_factory, self.rr = rr_factory, None
        self.interactive_menus = prompt is input and output is print

    def pick(self, title, items, label=lambda x: x['name'], default_index=None, context=()):
        if self.interactive_menus and can_scroll():
            try:
                selected = scrolling_menu(title, items, label, default_index or 0, context=context)
            except MenuCancelled:
                raise Cancelled() from None
            self.output(title + ': ' + label(selected))
            return selected
        for message in context:
            self.output(message)
        return choose(title, items, label, self.prompt, self.output, default_index)

    def confirm(self, message):
        self.output(message)
        return self.prompt('Confirm [y/N]: ').strip().lower() == 'y'

    def login(self):
        if self.rr is None:
            key = application_key()  # Fail before collecting any personal credentials.
            self.output('RadioReference credentials are held in memory for this session only.')
            username = self.prompt('RadioReference username (q back): ').strip()
            if username.lower() == 'q':
                raise Cancelled()
            password = self.secret('RadioReference password: ')
            try:
                if not username or not password:
                    raise ValueError('Username and password are required')
                self.rr = self.rr_factory(username, password, key)
            except Exception:
                # Constructor/library errors must not accidentally print secrets.
                raise ValueError('Could not connect to RadioReference. Account access, network '
                                 'availability or the app authorization may be responsible; '
                                 'this does not confirm your password is wrong.') from None
            finally:
                password = key = ''
        return self.rr

    def hardware(self, honor_launcher_selection=True):
        presets = [{'id': key, **value} for key, value in PROFILES.items()
                   if value.get('selectable', True)]
        selected = os.environ.get('BRUTAL_SELECTED_PROFILE') if honor_launcher_selection else None
        preset = next((p for p in presets if p['id'] == selected and p['id'] != 'custom'), None)
        if preset:
            self.output('Using the radio selected by the USB launcher: ' + preset['name'])
        else:
            preset = self.pick('Choose your SDR', presets)
        hardware = {key: preset[key] for key in ('args', 'rate', 'gains')}
        hardware.update(profile=preset['id'], ppm=0)
        if preset['id'] != 'custom':
            self.output('Using recommended starting settings for ' + preset['name'] +
                        '. Actual reception still needs testing.')
            return hardware
        self.output('Custom setup is for experienced users. Enter driver-specific settings.')
        if preset['id'] == 'custom':
            hardware['args'] = self.prompt('gr-osmosdr device arguments: ').strip()
        for key, name in [('rate', 'Sample rate (Hz)'), ('gains', 'Named integer gains'), ('ppm', 'PPM correction')]:
            value = self.prompt(f"{name} [{preset.get(key, 0)}]: ").strip()
            if value:
                hardware[key] = value
        return hardware

    def report_import_warnings(self, system, limit=8):
        """Database rows we had to skip or reconcile are shown, never hidden."""
        warnings = system.get('import_warnings', [])
        if warnings:
            self.output(f"{len(warnings)} database entr{'y needs' if len(warnings) == 1 else 'ies need'} "
                        'attention; the rest of the system was imported:')
            for warning in warnings[:limit]:
                self.output('  - ' + warning)
            if len(warnings) > limit:
                self.output(f'  ...and {len(warnings) - limit} more.')

    def import_system(self, hardware=None, onboarding=False):
        if self.rr is None:
            application_key()
        hardware = hardware if hardware is not None else self.hardware()
        rr = self.login()
        countries = rr.browse('countries')['countries']
        us_index = next((i for i, c in enumerate(countries)
                         if c.get('code') == 'US' or c['name'].casefold() == 'united states'), None)
        country = self.pick('Country', countries, default_index=us_index)
        state = self.pick('State / province', rr.browse('states', country['id'])['states'])
        county = self.pick('County / area', rr.browse('counties', state['id'])['counties'])
        systems = {s['id']: s for s in rr.browse('counties', state['id']).get('systems', [])}
        systems.update({s['id']: s for s in rr.browse('systems', county['id'])['systems']})
        choice = self.pick('P25 systems (database coverage does not guarantee reception)',
                           sorted(systems.values(), key=lambda s: s['name'].casefold()))
        self.output('Fetching sites and talkgroups…')
        system = rr.system(choice['id'])
        self.report_import_warnings(system)
        site = self.pick('Receiver site', [s for s in system['sites'] if s['controls_hz']],
                         lambda s: f"{s['name']} ({len(s['controls_hz'])} control channels)")
        if onboarding:
            self.output('\n[3/4] Import talkgroups')
        self.output(f"{len(system['talkgroups'])} talkgroups imported. Encrypted voice cannot be decoded.")
        ids = []
        filtered = False
        self.output('Listening to all talkgroups by default. You can filter them later in Manage saved systems.')
        demod = 'cqpsk'  # Default is appropriate for simulcast; no jargon question in normal setup.
        if onboarding:
            self.output('\n[4/4] Review your setup')
        self.output(f"\nConfirm: {system['name']} / {site['name']} / {hardware['profile']}")
        if not self.confirm('Save this new profile?'):
            raise Cancelled()
        profile = self.library.save(system, {'hardware': hardware, 'site_id': site['id'],
            'source': 'radioreference', 'demod': demod, 'selected_only': filtered, 'talkgroup_ids': ids})
        self.output('Saved: ' + profile_label(profile) + '. Use Listen from the main menu.')
        return profile

    def manual(self, hardware=None, onboarding=False):
        from test_connection import frequency_hz, clean_label
        hardware = hardware if hardware is not None else self.hardware()
        name = clean_label(self.prompt('System name: '))
        if onboarding:
            self.output('\n[3/4] Choose your receiver site')
        site = clean_label(self.prompt('Site name: '))
        # A repeated frequency would produce a duplicate control channel in the receiver config.
        frequencies = list(dict.fromkeys(
            frequency_hz(v.strip()) for v in self.prompt('Control channels (MHz, comma separated): ').split(',')))
        tdma = self.confirm('Does the database list this control channel as TDMA / Phase 2? '
                            'Leave as No if unsure')
        system = {'id': 0, 'name': name, 'type': 'P25 (user selected)', 'talkgroups': [],
            'sites': [{'id': 1, 'name': site, 'controls_hz': frequencies, 'nac': '0x0', 'tdma_cc': tdma, 'warnings': []}]}
        if not name or not site:
            raise ValueError('System and site names are required')
        if onboarding:
            self.output('\n[4/4] Review your setup')
        self.output(f"Confirm: {name} / {site} / {hardware['profile']} / {len(frequencies)} control channels")
        if not self.confirm('Save manual P25 profile?'):
            raise Cancelled()
        profile = self.library.save(system, {'hardware': hardware, 'site_id': 1, 'source': 'manual'})
        self.output('Saved. No RadioReference login was needed.')
        return profile

    def readiness(self, profile, resume_profile=None):
        hardware = profile['settings']['hardware']['profile']
        env, devices = environment(), usb_inventory()
        software = check_profile(hardware)
        candidates = [d for d in devices if d['device_node_present'] and
                      (hardware == 'custom' or hardware in d['compatible_profiles'])]
        if len(candidates) == 1:
            # Nothing to choose between: don't make the user confirm the only radio every launch.
            selected = candidates[0]
            self.output('Using the radio Linux can see: ' + selected['name'] + ' ' + selected['node'])
        else:
            selected = self.pick('Select Linux-visible USB radio', candidates,
                lambda d: d['name'] + ' ' + d['node']) if candidates else None
        report = assess(env, devices, hardware, software, selected['node'] if selected else None)
        if env['wsl'] and hardware != 'custom' and os.environ.get('BRUTAL_HANDOFF_NONCE') and (
                not candidates or software.get('missing')):
            choice = self.pick('Connect your radio to Linux', [
                'Connect my radio now (approve Windows prompts when asked)',
                'Not now - continue without listening'], str)
            if choice.startswith('Connect'):
                self.output('Connecting your radio. Setup will continue automatically in this window.')
                request_windows_connection(self.root, hardware, resume_profile)
        report['requires_windows_launcher'] = bool(env['wsl'] and not candidates and
            hardware != 'custom' and os.environ.get('BRUTAL_WINDOWS_LAUNCHER') != '1' and
            not os.environ.get('BRUTAL_HANDOFF_NONCE'))
        if report['requires_windows_launcher']:
            report['blockers'] = ['USB device not passed into this container. '
                'This standalone session has no Windows-helper connection; retrying here cannot attach the radio. '
                'You can save your system without listening. Automatic USB setup requires the guided launcher.']
            self.output('\nRadio connection is unavailable in this standalone container.\n'
                        'You can continue choosing and saving your system without listening.\n'
                        'The Windows USB bridge is not connected to this session. '
                        'Automatic connection is available in the guided Windows launch.\n'
                        'No USB access or reception has been verified.')
            return report
        self.output('Receiver: ' + env['label'])
        for blocker in report['blockers']:
            if os.environ.get('BRUTAL_HANDOFF_NONCE') and blocker.startswith('Forward the selected USB'):
                blocker = 'USB connection was deferred. You can save a system now; connect the radio before listening.'
            self.output('NEEDS ACTION: ' + blocker)
        if os.environ.get('BRUTAL_DIAGNOSTICS') == '1':
            self.output(report['note'])
        return report

    def listen(self, profile=None):
        # No account interaction: all metadata is read from the chosen saved profile.
        profile = profile if profile is not None else self.pick('Saved systems', self.library.list(), profile_label)
        report = self.readiness(profile, resume_profile=profile['id'])
        if not report['prerequisites_ready']:
            return
        if profile['settings']['hardware']['profile'] == 'custom':
            raise ValueError('Custom driver operation needs device-specific validation before launch')
        if profile['settings']['hardware']['profile'] in ('rtl', 'rtlv4'):
            accessible = [d for d in usb_inventory() if d['read_write_access'] and
                          'rtl' in d['compatible_profiles']]
            if len(accessible) != 1:
                raise ValueError('Pass only the selected RTL device into this container before launch; '
                                 'multiple accessible radios need explicit serial binding')
        self.output('Selected system: ' + profile_label(profile))
        self.output('Press Ctrl+C to stop the receiver.')
        if not self.confirm('Start listening now?'):
            return
        prepare(self.root, profile['id'])
        self.output('Starting OP25. Actual control-channel lock and audio still need verification.')
        self.output('Receiver web UI: http://127.0.0.1:8080/')
        self.output('Open this link in your computer\'s browser after startup; Ctrl+click in supported terminals.')
        self.output('Browser audio starts automatically when allowed. If the dashboard shows ENABLE AUDIO, click it once; the headphone button mutes or unmutes. Port 9000 is audio transport, not a webpage.')
        self.output('Use the Systems button in the web UI to add, switch or remove systems while listening.')
        if profile['settings']['hardware']['profile'] == 'rspdxr2':
            serial = report['selected_device'].get('serial', '')
            if not serial:
                raise ValueError('The selected RSP serial is unavailable; cannot bind the correct radio')
            os.environ['OP25_DATA_DIR'] = str(self.root)
            os.environ['OP25_RSP_SERIAL'] = serial
        run(self.root)

    def manage(self):
        profile = self.pick('Saved systems', self.library.list(), profile_label)
        action = self.pick('Manage profile', ['View', 'Edit site / talkgroups', 'Check RadioReference updates'], str)
        if action == 'View':
            self.output(json.dumps(profile, indent=2))
        elif action == 'Edit site / talkgroups':
            settings = dict(profile['settings'])
            site = self.pick('Receiver site', [s for s in profile['system']['sites'] if s['controls_hz']])
            settings['site_id'] = site['id']
            value = self.prompt('Talkgroup IDs, comma separated; blank means all: ').strip()
            settings['selected_only'] = bool(value)
            settings['talkgroup_ids'] = talkgroup_ids(value, profile['system']) if value else []
            if self.confirm('Save the changed site / listening filter?'):
                self.library.save(profile['system'], {**settings, 'profile_id': profile['id'],
                    'revision': profile['revision'], 'profile_name': profile['name'],
                    'name_is_custom': profile.get('name_is_custom', False)})
        else:
            if profile['settings']['source'] != 'radioreference':
                raise ValueError('This manual profile has no RadioReference update source')
            fresh = self.login().system(profile['system']['id'])
            review = self.library.review(profile['id'], fresh)
            self.output(json.dumps(review['changes'], indent=2))
            if review['blockers']:
                self.output('Cannot apply: ' + '; '.join(review['blockers']))
            elif self.confirm('Apply these changes? SDR settings and filters are preserved'):
                self.library.apply(review)

    def add_radio(self):
        self.output('First select an existing system to copy. You will choose the new SDR afterward; '
                    'the listed radios are only your saved starting points.')
        original = self.pick('Existing system to copy', self.library.list(), profile_label)
        self.output('Your site, talkgroups, and listening preferences stay intact. '
                    'Only one radio listens at a time.')
        hardware = self.hardware(honor_launcher_selection=False)
        if hardware['profile'] == original['settings']['hardware']['profile']:
            raise ValueError('That saved system already uses this SDR. To retry its driver or USB setup, '
                             'choose Listen using a saved system from the main menu; do not add it again.')
        saved = self.library.find_hardware_clone(original['id'], hardware)
        if saved:
            self.output('This SDR setup is already saved: ' + profile_label(saved) +
                        '. Reusing it; no duplicate or RadioReference import was created.')
        else:
            self.output('New setup: ' + profile_label(original) + ' → ' + hardware['profile'])
            if not self.confirm('Save this additional SDR profile?'):
                return None
            saved = self.library.clone_for_hardware(original['id'], hardware)
            self.output('Saved radio settings: ' + profile_label(saved) +
                        '. Driver installation and reception are not yet verified; no re-import was needed.')
        self.output('To switch SDRs later, stop the receiver and choose the matching saved profile. '
                    'The dashboard cannot swap physical radios during a running session.')
        if self.confirm('Connect this radio and test it now?'):
            self.listen(saved)
        return saved

    def first_run(self):
        """An empty store is a new installation, never a returning-user menu."""
        profile = None
        self.output('\nWELCOME TO BRUTAL OP25\nLet\'s set up your first radio system. '
                    'Your setup stays local; nothing is imported from another installation.')
        try:
            self.output('\n[1/4] Connect and choose your radio')
            hardware = self.hardware()
            while True:
                report = self.readiness({'settings': {'hardware': hardware}})
                if report['prerequisites_ready']:
                    break
                choices = [
                    'Check again after connecting / fixing the radio',
                    'Choose my system now; finish radio connection later', 'Exit setup']
                if report.get('requires_windows_launcher'):
                    choices = choices[1:]  # This container cannot acquire a USB node by retrying.
                choice = self.pick('Your radio is not ready yet', choices, str,
                    context=report.get('blockers', []))
                if choice.startswith('Exit'):
                    return False
                if choice.startswith('Choose'):
                    self.output('We can save your system now, but cannot start listening until the radio is ready.')
                    break
            while True:
                self.output('\n[2/4] Choose how to find your P25 system')
                source = self.pick('Import source', [
                    'RadioReference - browse systems near you',
                    'Manual - I already know my control-channel frequencies',
                    'Skip for now - add systems in the dashboard'], str)
                try:
                    if source.startswith('Skip'):
                        self.output('Opening the Systems dashboard. Your selected radio settings will be used '
                                    'for any systems you save there. Nothing starts listening automatically.')
                        return serve_setup(self.root, hardware,
                            can_listen=report['prerequisites_ready'] and hardware['profile'] != 'custom')
                    profile = (self.import_system(hardware, onboarding=True) if source.startswith('RadioReference')
                               else self.manual(hardware, onboarding=True))
                    break
                except ValueError as error:
                    self.output('Setup needs attention: ' + str(error))
                    self.output('Choose another source or press q to exit. No profile was saved.')
            self.output('\nSetup saved. Radio reception and audio are not verified yet.')
            if self.confirm('Check the radio and start listening now?'):
                try:
                    self.listen(profile)
                except ValueError as error:
                    self.output('Receiver needs attention: ' + str(error))
            return True
        except Cancelled:
            if profile is not None:
                self.output('Receiver start cancelled. Your completed setup is saved.')
                return True
            self.output('Setup cancelled. No completed profile was saved. Setup opens again next launch.')
            return False
        except ValueError as error:
            self.output('Setup needs attention: ' + str(error) + '. Run setup again when ready.')
            return False
        except Exception:
            self.output('Setup could not finish. Check storage, network and receiver dependencies. '
                        'No credential-bearing traceback was printed.')
            return profile is not None

    def setup_only_reason(self):
        if os.environ.get('BRUTAL_SETUP_ONLY') == '1':
            return 'This session was launched for system setup only (--no-usb).'
        env = environment()
        if (env.get('container') and not os.environ.get('BRUTAL_HANDOFF_NONCE') and
                os.environ.get('BRUTAL_WINDOWS_LAUNCHER') != '1' and
                not any(d['device_node_present'] for d in usb_inventory())):
            return 'No USB radio was passed into this standalone container, and no host USB helper is connected.'
        return ''

    def loop(self):
        self.output(banner(color=False))
        self.output('Profile store: ' + str(self.library.root))
        self.output('One system/site active at a time. No browser onboarding or ZIP required.')
        setup_only = self.setup_only_reason()
        if setup_only:
            self.output('\nSYSTEM SETUP ONLY — listening is unavailable in this session.\n' + setup_only +
                        '\nImports and saved systems still work. For listening, use the guided launcher: '
                        'Launch-Brutal-OP25.cmd on Windows, or brutal-op25.sh on Linux/WSL. '
                        'Do not use a bare docker run. Your saved systems remain available there.')
        try:
            resume = os.environ.pop('BRUTAL_RESUME_LISTEN', '')
            if resume:
                try:
                    if os.environ.get('BRUTAL_WINDOWS_LAUNCHER') != '1':
                        raise ValueError('Listening continuation requires the connected USB launcher')
                    profile = self.library.read(resume)
                    if profile['settings']['hardware']['profile'] != os.environ.get('BRUTAL_SELECTED_PROFILE'):
                        raise ValueError('Saved system SDR no longer matches the connected radio')
                    self.output('USB connected. Resuming listening setup for ' + profile_label(profile))
                    self.listen(profile)
                except Cancelled:
                    self.output('Receiver start cancelled. Your saved system is unchanged.')
                except (ValueError, FileNotFoundError) as error:
                    self.output('Could not resume listening: ' + str(error))
            saved = self.library.list()
            if self.library.unreadable:
                self.output('Warning: ' + str(len(self.library.unreadable)) + ' saved-system file(s) could not be read '
                            'and were skipped: ' + ', '.join(self.library.unreadable))
            if not saved and not self.first_run():
                return
            while True:
                listen_label = 'Listen unavailable — system setup only' if setup_only else 'Listen using a saved system'
                self.output('\n1. ' + listen_label + '\n2. Add another system from RadioReference\n'
                            '3. Manage / update saved systems\n4. Check radio setup\n'
                            '5. Manual P25 setup\n6. Add another SDR to a saved system\n0. Exit')
                action = self.prompt('Choose: ').strip()
                try:
                    if action == '0':
                        return
                    if action == '1':
                        if setup_only:
                            self.output('Listening is disabled here: ' + setup_only +
                                        ' Use the guided launcher; no re-import is needed.')
                        else:
                            self.listen()
                    elif action == '2':
                        self.import_system()
                    elif action == '3':
                        self.manage()
                    elif action == '4':
                        self.output(json.dumps({'environment': environment(), 'usb': usb_inventory()}, indent=2))
                        preset = self.pick('Driver check', [{'id': k, **v} for k, v in PROFILES.items()
                                           if v.get('selectable', True)])
                        self.output(json.dumps(check_profile(preset['id']), indent=2))
                    elif action == '5':
                        self.manual()
                    elif action == '6':
                        self.add_radio()
                    else:
                        self.output('Choose a listed action.')
                except Cancelled:
                    self.output('Cancelled. Back to main menu.')
                except ValueError as error:
                    self.output('Setup: ' + str(error))
                except Exception:
                    self.output('Operation failed. Check network, storage and receiver dependencies. '
                                'No credential-bearing traceback was printed.')
        finally:
            if self.rr:
                self.rr.close()
                self.rr = None


def main():
    parser = argparse.ArgumentParser(description='Brutal OP25 terminal setup - built on boatbod/op25')
    parser.add_argument('--data-dir', default=os.environ.get('OP25_DATA_DIR') or
        str(Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'brutal-op25'))
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error('An interactive terminal is required. Use Launch-Brutal-OP25.cmd '
                     'on Windows or brutal-op25.sh on Linux.')
    task_session_lock = acquire_session_lock(args.data_dir)
    try:
        Terminal(args.data_dir).loop()
    except WindowsHandoff:
        raise SystemExit(88)
    except (KeyboardInterrupt, EOFError):
        print(paint('\nBrutal OP25 stopped.'))
    finally:
        task_session_lock.close()


if __name__ == '__main__':
    main()
