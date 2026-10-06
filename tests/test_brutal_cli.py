import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from brutal_cli import Terminal, choose, Cancelled, talkgroup_ids, WindowsHandoff, request_windows_connection, acquire_session_lock, profile_label

ROOT = Path(__file__).resolve().parents[1]


class TerminalTests(unittest.TestCase):
    def test_confirmation_keeps_answer_prompt_short_and_separate(self):
        with tempfile.TemporaryDirectory() as root:
            messages, prompts = [], []
            def answer(message):
                prompts.append(message)
                return 'y'
            terminal = Terminal(root, answer, messages.append)
            question = 'Start ' + ('A very long system and site name / ' * 5) + '?'
            self.assertTrue(terminal.confirm(question))
            self.assertEqual(messages, [question])
            self.assertEqual(prompts, ['Confirm [y/N]: '])

    def test_saved_profile_label_distinguishes_equivalent_radio_copies(self):
        profile = {'id': 'f19b4fe362bb4ad6a5fb1c8bc29b1a19',
                   'system': {'name': 'AARRS', 'sites': [{'id': 1, 'name': 'Northeast Simulcast'}]},
                   'settings': {'site_id': 1, 'hardware': {'profile': 'rspdxr2'}}}
        self.assertEqual(profile_label(profile), 'AARRS / Northeast Simulcast / rspdxr2 · f19b4fe3')

    @unittest.skipUnless(__import__('sys').platform == 'linux', 'Linux file lock')
    def test_one_receiver_session_per_library(self):
        with tempfile.TemporaryDirectory() as root:
            first = acquire_session_lock(root)
            try:
                with self.assertRaisesRegex(ValueError, 'Another Brutal OP25 session'):
                    acquire_session_lock(root)
                self.assertTrue(__import__('os').get_inheritable(first.fileno()))
            finally:
                first.close()
            second = acquire_session_lock(root)
            second.close()

    def test_listening_shows_receiver_web_link_and_audio_guidance(self):
        with tempfile.TemporaryDirectory() as root:
            output, prompts = [], []
            def answer(message):
                prompts.append(message)
                return 'y'
            terminal = Terminal(root, answer, output.append)
            profile = {'id': 'a'*32, 'name': 'Receiver',
                       'settings': {'hardware': {'profile': 'rtlv4'}}}
            terminal.readiness = Mock(return_value={'prerequisites_ready': True})
            with patch('brutal_cli.profile_label', return_value='Receiver'), \
                    patch('brutal_cli.usb_inventory', return_value=[{
                        'read_write_access': True, 'compatible_profiles': ['rtl']}]), \
                    patch('brutal_cli.prepare'), patch('brutal_cli.run') as start:
                terminal.listen(profile)
            start.assert_called_once()
            text = '\n'.join(output)
            self.assertIn('Receiver web UI: http://127.0.0.1:8080/', text)
            self.assertIn('starts automatically when allowed', text)
            self.assertIn('ENABLE AUDIO', text)
            self.assertIn('MUTE or UNMUTE beside the volume slider', text)
            self.assertIn('not a webpage', text)
            self.assertIn('Selected system: Receiver', text)
            self.assertIn('Start listening now?', text)
            self.assertEqual(prompts, ['Confirm [y/N]: '])

    def test_paged_search_and_cancel(self):
        answers = iter(['/Site 19', '19'])
        self.assertEqual(choose('Sites', list(range(30)), lambda n: f'Site {n}',
                               lambda _: next(answers), lambda _: None), 18)
        with self.assertRaises(Cancelled):
            choose('Sites', [1], str, lambda _: 'q', lambda _: None)

    def test_fresh_store_empty_and_saved_list_does_not_log_in(self):
        with tempfile.TemporaryDirectory() as root:
            prompts = iter(['q'])
            login = Mock(side_effect=AssertionError('Must not ask for account'))
            terminal = Terminal(root, lambda _: next(prompts), lambda _: None, rr_factory=login)
            terminal.loop()
            self.assertEqual(terminal.library.list(), [])
            self.assertFalse(terminal.library.root.exists())
            login.assert_not_called()

    def test_real_captured_p25_import_saves_only_profile_data(self):
        system = json.loads((Path(__file__).parent / 'live-bexar-system.json').read_text())
        rr = Mock()
        rr.browse.side_effect = lambda level, *_: {
            'countries': {'countries': [{'id': 1, 'name': 'United States'}]},
            'states': {'states': [{'id': 48, 'name': 'Texas'}]},
            'counties': {'counties': [{'id': 2549, 'name': 'Bexar'}], 'systems': []},
            'systems': {'systems': [{'id': system['id'], 'name': system['name']}]},
        }[level]
        rr.system.return_value = system
        factory = Mock(return_value=rr)
        prompts = iter(['3', 'unit-test-user', '1', '1', '1', '1', '1', 'y'])
        secrets = iter(['unit-test-password'])
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'BRUTAL_RR_APP_KEY': 'unit-test-key'}):
            terminal = Terminal(root, lambda _: next(prompts), lambda _: None,
                                lambda _: next(secrets), factory)
            terminal.import_system(onboarding=True)
            saved = terminal.library.list()
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]['system']['id'], system['id'])
            self.assertEqual(saved[0]['settings']['hardware']['profile'], 'rspdxr2')
            self.assertEqual(len(saved[0]['system']['talkgroups']), 1009)
            self.assertFalse(saved[0]['settings']['selected_only'])
            self.assertEqual(saved[0]['settings']['talkgroup_ids'], [])
            serialized = json.dumps(saved)
            for secret in ['unit-test-password', 'unit-test-key', 'unit-test-user']:
                self.assertNotIn(secret, serialized)

    def test_supported_sdr_uses_defaults_without_technical_questions(self):
        from importer import PROFILES
        for number, identity in [('1', 'rtl'), ('2', 'rtlv4'), ('3', 'rspdxr2')]:
            with tempfile.TemporaryDirectory() as root:
                prompt = Mock(return_value=number)
                output = []
                terminal = Terminal(root, prompt, output.append)
                hardware = terminal.hardware()
                prompt.assert_called_once()
                self.assertEqual(hardware['profile'], identity)
                self.assertEqual(hardware['rate'], PROFILES[identity]['rate'])
                self.assertEqual(hardware['gains'], PROFILES[identity]['gains'])
                self.assertEqual(hardware['ppm'], 0)
                if identity == 'rtl':
                    self.assertIn('Blog V1-V3 / other non-V4', '\n'.join(output))

    def test_windows_launcher_selection_is_reused_without_second_question(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'BRUTAL_SELECTED_PROFILE': 'rtlv4'}):
            prompt = Mock(side_effect=AssertionError('Radio already chosen'))
            terminal = Terminal(root, prompt, lambda _: None)
            self.assertEqual(terminal.hardware()['profile'], 'rtlv4')
            prompt.assert_not_called()

    def test_additional_radio_choice_ignores_previous_launcher_selection(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'BRUTAL_SELECTED_PROFILE': 'rtlv4'}):
            terminal = Terminal(root, Mock(return_value='3'), lambda _: None)
            self.assertEqual(terminal.hardware(honor_launcher_selection=False)['profile'], 'rspdxr2')

    def test_additional_radio_uses_saved_system_without_account_or_existing_profile_changes(self):
        system = json.loads((Path(__file__).parent / 'live-bexar-system.json').read_text())
        hardware = {'profile': 'rspdxr2', 'args': 'soapy=0,driver=sdrplay', 'rate': 2000000,
                    'gains': 'IFGR:40,RFGR:0', 'ppm': 0}
        with tempfile.TemporaryDirectory() as root:
            output = []
            prompts = iter(['y', 'y'])
            factory = Mock(side_effect=AssertionError('No RadioReference request expected'))
            terminal = Terminal(root, lambda _: next(prompts), output.append, rr_factory=factory)
            original = terminal.library.save(system, {'hardware': {'profile': 'rtlv4', 'args': 'rtl',
                'rate': 1000000, 'gains': 'LNA:39', 'ppm': 0}, 'site_id': system['sites'][0]['id'],
                'source': 'radioreference', 'priority_tgids': [system['talkgroups'][0]['id']]})
            terminal.pick = Mock(return_value=original)
            terminal.hardware = Mock(return_value=hardware)
            terminal.listen = Mock()
            before = terminal.library.read(original['id'])
            second = terminal.add_radio()
            terminal.hardware.assert_called_once_with(honor_launcher_selection=False)
            self.assertEqual(len(terminal.library.list()), 2)
            self.assertEqual(terminal.library.read(original['id']), before)
            self.assertEqual(second['settings']['hardware'], hardware)
            self.assertEqual(second['settings']['priority_tgids'], before['settings']['priority_tgids'])
            terminal.listen.assert_called_once_with(second)
            self.assertIn('no re-import was needed', '\n'.join(output))
            factory.assert_not_called()

    def test_retrying_additional_sdr_reuses_existing_profile(self):
        system = json.loads((Path(__file__).parent / 'live-bexar-system.json').read_text())
        rtl = {'profile': 'rtlv4', 'args': 'rtl', 'rate': 1000000, 'gains': 'LNA:39', 'ppm': 0}
        rsp = {'profile': 'rspdxr2', 'args': 'soapy=0,driver=sdrplay', 'rate': 2000000,
               'gains': 'IFGR:40,RFGR:0', 'ppm': 0}
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, lambda _: 'y', output.append)
            original = terminal.library.save(system, {'hardware': rtl,
                'site_id': system['sites'][0]['id'], 'source': 'radioreference'})
            existing = terminal.library.clone_for_hardware(original['id'], rsp)
            terminal.pick = Mock(return_value=original)
            terminal.hardware = Mock(return_value=rsp)
            terminal.listen = Mock()
            result = terminal.add_radio()
            self.assertEqual(result['id'], existing['id'])
            self.assertEqual(len(terminal.library.list()), 2)
            self.assertIn('Reusing it; no duplicate', '\n'.join(output))
            terminal.listen.assert_called_once_with(existing)

    def test_returning_user_menu_offers_additional_sdr(self):
        with tempfile.TemporaryDirectory() as root:
            replies = iter(['6', '0'])
            output = []
            terminal = Terminal(root, lambda _: next(replies), output.append)
            terminal.library.list = Mock(return_value=[{'id': 'a' * 32}])
            terminal.add_radio = Mock()
            terminal.loop()
            terminal.add_radio.assert_called_once()
            self.assertIn('6. Add another SDR to a saved system', '\n'.join(output))

    def test_wsl_launcher_keeps_usb_handoff_scoped_and_container_locked_down(self):
        script = (ROOT / 'install/brutal-wsl.sh').read_text()
        runner = (ROOT / 'brutal-op25.sh').read_text()
        usb = (ROOT / 'install/wsl-usb.ps1').read_text()
        self.assertIn('brutal-op25-data:/data', script)
        self.assertIn('--device "$task_device"', script)
        self.assertIn('--cap-drop ALL', runner)
        self.assertNotIn('--privileged', runner)
        self.assertNotIn('Using separate data volume:', runner)
        self.assertNotIn('BRUTAL OP25 // WINDOWS + WSL', script)
        self.assertNotIn('Dashboard link:', script)
        self.assertNotIn('--force', usb)
        self.assertNotIn('Downloads', usb)
        self.assertIn('task_attached', script)
        launcher = (ROOT / 'Launch-Brutal-OP25.cmd').read_text()
        self.assertIn('powershell.exe -NoProfile -ExecutionPolicy Bypass', launcher)
        self.assertNotIn('Set-ExecutionPolicy', launcher)
        self.assertIn('BRUTAL_HANDOFF_NONCE', script)
        self.assertEqual(script.count('BRUTAL_WSL_HANDOFF=1 BRUTAL_HANDOFF_NONCE=$task_nonce'), 2)
        self.assertIn('--env BRUTAL_WINDOWS_LAUNCHER=1', runner)
        self.assertIn('More than one Linux USB node matched', script)

    def test_missing_app_key_never_requests_username_password_or_radio(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {}, clear=True), \
                patch('brutal_cli.application_key',
                      side_effect=ValueError('This is an app setup issue, not your password')):
            prompt, secret, factory = Mock(), Mock(), Mock()
            terminal = Terminal(root, prompt, lambda _: None, secret, factory)
            for action in (terminal.login, terminal.import_system):
                with self.assertRaisesRegex(ValueError, 'app setup issue, not your password'):
                    action()
            prompt.assert_not_called()
            secret.assert_not_called()
            factory.assert_not_called()

    def test_login_requests_only_username_and_password_and_reuses_session(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'BRUTAL_RR_APP_KEY': 'unit-test-key'}):
            prompt, secret, factory = Mock(return_value='unit-test-user'), Mock(return_value='unit-test-password'), Mock()
            terminal = Terminal(root, prompt, lambda _: None, secret, factory)
            self.assertIs(terminal.login(), terminal.login())
            prompt.assert_called_once()
            secret.assert_called_once()
            factory.assert_called_once_with('unit-test-user', 'unit-test-password', 'unit-test-key')

    def test_runtime_key_file_is_used_without_an_application_key_prompt(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {}, clear=True), \
                patch('brutal_cli.Path.read_text', return_value='unit-test-runtime-key\n') as read:
            prompt = Mock(return_value='unit-test-user')
            secret = Mock(return_value='unit-test-password')
            factory = Mock()
            terminal = Terminal(root, prompt, lambda _: None, secret, factory)
            terminal.login()
            factory.assert_called_once_with('unit-test-user', 'unit-test-password', 'unit-test-runtime-key')
            secret.assert_called_once()
            read.assert_called_once_with(encoding='utf-8')

    def test_saved_listen_does_not_ask_radio_reference_and_cannot_bypass_checks(self):
        with tempfile.TemporaryDirectory() as root:
            terminal = Terminal(root, lambda _: '1', lambda _: None, rr_factory=Mock())
            terminal.library.list = Mock(return_value=[{'id': 'd'*32, 'system': {'name': 'Unit fixture', 'sites': []},
                'settings': {'hardware': {'profile': 'rtlv4'}, 'site_id': 1}}])
            terminal.readiness = Mock(return_value={'prerequisites_ready': False})
            with patch('brutal_cli.prepare') as prepare, patch('brutal_cli.run') as run:
                terminal.listen()
            terminal.rr_factory.assert_not_called()
            prepare.assert_not_called()
            run.assert_not_called()

    def test_talkgroup_filter_rejects_unknown_ids(self):
        system = {'talkgroups': [{'id': 123}, {'id': 456}]}
        self.assertEqual(talkgroup_ids('456,123,123', system), [123, 456])
        for text in ('999', 'abc', ''):
            with self.assertRaises(ValueError):
                talkgroup_ids(text, system)

    def test_account_session_closed_on_exit(self):
        with tempfile.TemporaryDirectory() as root:
            terminal = Terminal(root, lambda _: '0', lambda _: None)
            terminal.library.list = Mock(return_value=[{}])
            rr = terminal.rr = Mock()
            terminal.loop()
            rr.close.assert_called_once()
            self.assertIsNone(terminal.rr)

    def test_empty_store_opens_wizard_not_returning_user_menu(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, lambda _: 'q', output.append)
            terminal.loop()
            text = '\n'.join(output)
            self.assertIn('WELCOME TO BRUTAL OP25', text)
            self.assertIn('[1/4]', text)
            self.assertNotIn('Manage / update saved systems', text)
            self.assertFalse(terminal.library.root.exists())

    def test_fresh_manual_onboarding_saves_before_main_menu_and_never_logs_in(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            prompts = iter(['2', 'Test manual system', 'Test site', '851.0125', 'n', 'y', 'n', '0'])
            terminal = Terminal(root, lambda _: next(prompts), output.append, rr_factory=Mock())
            terminal.hardware = Mock(return_value={'profile': 'rtlv4'})
            terminal.readiness = Mock(return_value={'prerequisites_ready': True})
            terminal.loop()
            self.assertEqual(len(terminal.library.list()), 1)
            terminal.hardware.assert_called_once()
            terminal.rr_factory.assert_not_called()
            text = '\n'.join(output)
            for phase in ('[1/4]', '[2/4]', '[3/4]', '[4/4]'):
                self.assertIn(phase, text)
            self.assertLess(text.index('Setup saved.'), text.index('Manage / update saved systems'))

    def test_first_run_can_skip_import_and_open_systems_dashboard(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, lambda _: 'unused', output.append, rr_factory=Mock())
            terminal.hardware = Mock(return_value={'profile': 'rtlv4', 'args': 'rtl',
                'rate': 1000000, 'gains': 'LNA:39', 'ppm': 0})
            terminal.readiness = Mock(return_value={'prerequisites_ready': True})
            terminal.pick = Mock(return_value='Skip for now - add systems in the dashboard')
            with patch('brutal_cli.serve_setup', return_value=False) as dashboard:
                self.assertFalse(terminal.first_run())
            dashboard.assert_called_once_with(terminal.root, terminal.hardware.return_value, can_listen=True)
            terminal.rr_factory.assert_not_called()
            self.assertEqual(terminal.library.list(), [])
            self.assertIn('Nothing starts listening automatically', '\n'.join(output))

    def test_first_run_passes_connected_rsp_serial_to_systems_dashboard(self):
        with tempfile.TemporaryDirectory() as root:
            terminal = Terminal(root, lambda _: 'unused', lambda _: None, rr_factory=Mock())
            hardware = {'profile': 'rspdxr2', 'args': 'soapy=0,driver=sdrplay',
                        'rate': 2000000, 'gains': 'IFGR:40,RFGR:0', 'ppm': 0}
            terminal.hardware = Mock(return_value=hardware)
            terminal.readiness = Mock(return_value={'prerequisites_ready': True,
                'selected_device': {'serial': '24052A9770'}})
            terminal.pick = Mock(return_value='Skip for now - add systems in the dashboard')
            with patch('brutal_cli.serve_setup', return_value=True) as dashboard:
                self.assertTrue(terminal.first_run())
            dashboard.assert_called_once_with(terminal.root, hardware, can_listen=True,
                                              rsp_serial='24052A9770')

    def test_returning_install_skips_first_run_and_login(self):
        with tempfile.TemporaryDirectory() as root:
            terminal = Terminal(root, lambda _: '0', lambda _: None, rr_factory=Mock())
            terminal.library.list = Mock(return_value=[{}])
            terminal.first_run = Mock(side_effect=AssertionError('Should not onboard again'))
            terminal.loop()
            terminal.first_run.assert_not_called()
            terminal.rr_factory.assert_not_called()

    def test_missing_radio_can_exit_without_saved_state_or_account(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, lambda _: '3', output.append, rr_factory=Mock())
            terminal.hardware = Mock(return_value={'profile': 'rtlv4'})
            terminal.readiness = Mock(return_value={'prerequisites_ready': False})
            terminal.loop()
            self.assertEqual(terminal.library.list(), [])
            terminal.rr_factory.assert_not_called()
            self.assertNotIn('Manage / update saved systems', '\n'.join(output))

    def test_standalone_container_does_not_force_user_out_of_setup(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, lambda _: '2', output.append, rr_factory=Mock())
            terminal.hardware = Mock(return_value={'profile': 'rtlv4'})
            with patch('brutal_cli.environment', return_value={
                    'wsl': True, 'kind': 'wsl_container', 'container': True, 'linux_receiver': True}), \
                    patch('brutal_cli.usb_inventory', return_value=[]), \
                    patch('brutal_cli.check_profile', return_value={'missing': []}), \
                    patch.dict('os.environ', {}, clear=True):
                terminal.loop()
            text = '\n'.join(output)
            self.assertIn('continue choosing and saving', text)
            self.assertIn('Choose my system now', text)
            self.assertNotIn('Check again after', text)
            self.assertNotIn('WINDOWS USB SETUP REQUIRED', text)
            self.assertNotIn('Exit this session', text)
            self.assertNotIn('exclusive access', text)
            self.assertEqual(terminal.library.list(), [])
            terminal.rr_factory.assert_not_called()

    def test_short_menu_prompt_is_plain_language(self):
        prompt = Mock(return_value='2')
        self.assertEqual(choose('Options', ['First', 'Second'], str, prompt, lambda _: None), 'Second')
        prompt.assert_called_once_with('Choose 1-2 (q to cancel): ')

    def test_bare_container_disables_listen_before_profile_picker(self):
        with tempfile.TemporaryDirectory() as root, \
                patch.dict('os.environ', {}, clear=True), \
                patch('brutal_cli.environment', return_value={'container': True, 'wsl': True}), \
                patch('brutal_cli.usb_inventory', return_value=[]):
            output = []
            replies = iter(['1','0'])
            terminal = Terminal(root, lambda _: next(replies), output.append)
            terminal.library.list = Mock(return_value=[{}])
            terminal.listen = Mock()
            terminal.loop()
            terminal.listen.assert_not_called()
            self.assertIn('SYSTEM SETUP ONLY', '\n'.join(output))
            self.assertIn('Listen unavailable', '\n'.join(output))

    def test_usb_sessions_and_native_linux_keep_listen_enabled(self):
        with tempfile.TemporaryDirectory() as root:
            terminal = Terminal(root, lambda _: '0', lambda _: None)
            with patch.dict('os.environ', {}, clear=True), \
                    patch('brutal_cli.environment', return_value={'container': False}):
                self.assertEqual(terminal.setup_only_reason(), '')
            with patch.dict('os.environ', {'BRUTAL_HANDOFF_NONCE': 'f'*32}, clear=True), \
                    patch('brutal_cli.environment', return_value={'container': True}):
                self.assertEqual(terminal.setup_only_reason(), '')
            with patch.dict('os.environ', {}, clear=True), \
                    patch('brutal_cli.environment', return_value={'container': True}), \
                    patch('brutal_cli.usb_inventory', return_value=[{'device_node_present': True}]):
                self.assertEqual(terminal.setup_only_reason(), '')
            with patch.dict('os.environ', {'BRUTAL_SETUP_ONLY': '1'}, clear=True):
                self.assertIn('--no-usb', terminal.setup_only_reason())

    def test_windows_handoff_is_fixed_action_with_session_nonce_and_no_secrets(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'BRUTAL_HANDOFF_NONCE': 'a'*32}):
            with self.assertRaises(WindowsHandoff):
                request_windows_connection(root, 'rtlv4')
            request = json.loads((Path(root) / 'host-handoff.json').read_text())
            self.assertEqual(request, {'version': 1, 'action': 'connect_usb', 'preset': 'rtlv4', 'nonce': 'a'*32})
            self.assertFalse((Path(root) / 'host-handoff.tmp').exists())
            with self.assertRaises(ValueError):
                request_windows_connection(root, 'custom')
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(ValueError):
                request_windows_connection(root, 'rtl')
            self.assertFalse((Path(root) / 'host-handoff.json').exists())

    def test_connect_action_requests_host_work_without_launching_windows_from_linux(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'BRUTAL_HANDOFF_NONCE': 'b'*32}), \
                patch('brutal_cli.environment', return_value={
                    'wsl': True, 'kind': 'wsl_container', 'container': True, 'linux_receiver': True}), \
                patch('brutal_cli.usb_inventory', return_value=[]), \
                patch('brutal_cli.check_profile', return_value={'missing': []}):
            output = []
            terminal = Terminal(root, lambda _: '1', output.append)
            with self.assertRaises(WindowsHandoff):
                terminal.readiness({'settings': {'hardware': {'profile': 'rtlv4'}}})
            self.assertIn('continue automatically in this window', '\n'.join(output))
            self.assertEqual(json.loads((Path(root) / 'host-handoff.json').read_text())['preset'], 'rtlv4')

    def test_fresh_v4_selection_is_preserved_through_windows_handoff(self):
        replies = iter(['2', '1'])  # V4, then Connect my radio now.
        with tempfile.TemporaryDirectory() as root, \
                patch.dict('os.environ', {'BRUTAL_HANDOFF_NONCE': 'c'*32}, clear=True), \
                patch('brutal_cli.environment', return_value={
                    'wsl': True, 'kind': 'wsl_container', 'container': True, 'linux_receiver': True}), \
                patch('brutal_cli.usb_inventory', return_value=[]), \
                patch('brutal_cli.check_profile', return_value={'missing': []}):
            output = []
            terminal = Terminal(root, lambda _: next(replies), output.append)
            with self.assertRaises(WindowsHandoff):
                terminal.first_run()
            request = json.loads((Path(root) / 'host-handoff.json').read_text())
            self.assertEqual(request['preset'], 'rtlv4')
            self.assertIn('Using recommended starting settings for RTL-SDR Blog V4', '\n'.join(output))

    def test_saved_listening_continues_after_usb_handoff_without_selecting_again(self):
        system = json.loads((Path(__file__).parent / 'live-bexar-system.json').read_text())
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, lambda _: '0', output.append, rr_factory=Mock())
            profile = terminal.library.save(system, {'hardware': {'profile': 'rtlv4'},
                'site_id': system['sites'][0]['id'], 'source': 'radioreference'})
            with patch.dict('os.environ', {'BRUTAL_HANDOFF_NONCE': 'd'*32}):
                with self.assertRaises(WindowsHandoff):
                    request_windows_connection(root, 'rtlv4', profile['id'])
            request = json.loads((Path(root) / 'host-handoff.json').read_text())
            self.assertEqual(request['resume_listen'], profile['id'])
            terminal.listen = Mock()
            with patch.dict('os.environ', {'BRUTAL_RESUME_LISTEN': request['resume_listen'],
                    'BRUTAL_WINDOWS_LAUNCHER': '1', 'BRUTAL_SELECTED_PROFILE': 'rtlv4'}):
                terminal.loop()
                import os
                self.assertNotIn('BRUTAL_RESUME_LISTEN', os.environ)
            terminal.listen.assert_called_once_with(terminal.library.read(profile['id']))
            terminal.rr_factory.assert_not_called()
            self.assertIn('USB connected. Resuming listening setup', '\n'.join(output))
            self.assertNotIn('Project: https://github.com/trappedinthesim/brutal-op25', '\n'.join(output))

    def test_usb_continuation_rejects_profile_mismatch_and_path_injection(self):
        system = json.loads((Path(__file__).parent / 'live-bexar-system.json').read_text())
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'BRUTAL_HANDOFF_NONCE': 'e'*32}):
            terminal = Terminal(root, lambda _: '0', lambda _: None)
            profile = terminal.library.save(system, {'hardware': {'profile': 'rtlv4'},
                'site_id': system['sites'][0]['id'], 'source': 'radioreference'})
            for preset, identity in [('rspdxr2',profile['id']), ('rtlv4','../../anything')]:
                with self.assertRaises(ValueError):
                    request_windows_connection(root, preset, identity)
                self.assertFalse((Path(root) / 'host-handoff.json').exists())
            terminal.listen = Mock()
            with patch.dict('os.environ', {'BRUTAL_RESUME_LISTEN': profile['id'],
                    'BRUTAL_WINDOWS_LAUNCHER': '1', 'BRUTAL_SELECTED_PROFILE': 'rspdxr2'}):
                terminal.loop()
            terminal.listen.assert_not_called()

    def test_deferred_connection_does_not_tell_launcher_user_to_exit(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'BRUTAL_HANDOFF_NONCE': 'b'*32}), \
                patch('brutal_cli.environment', return_value={
                    'wsl': True, 'kind': 'wsl_container', 'container': True,
                    'linux_receiver': True, 'label': 'Linux container on WSL'}), \
                patch('brutal_cli.usb_inventory', return_value=[]), \
                patch('brutal_cli.check_profile', return_value={'missing': []}):
            output = []
            terminal = Terminal(root, lambda _: '2', output.append)
            report = terminal.readiness({'settings': {'hardware': {'profile': 'rtlv4'}}})
            self.assertFalse(report['requires_windows_launcher'])
            self.assertNotIn('Double-click', '\n'.join(output))
            self.assertFalse((Path(root) / 'host-handoff.json').exists())

    def _linux_radio(self, node):
        return {'node': node, 'name': 'RTL2832 family', 'compatible_profiles': ['rtl', 'rtlv4'],
                'serial': '1', 'device_node_present': True, 'read_write_access': True}

    def _ready_env(self):
        return patch('brutal_cli.environment', return_value={
            'wsl': False, 'kind': 'linux_native', 'container': False,
            'linux_receiver': True, 'label': 'Native Linux'})

    def test_single_matching_radio_is_selected_without_a_menu(self):
        radio = self._linux_radio('/dev/bus/usb/001/005')
        with tempfile.TemporaryDirectory() as root, self._ready_env(), \
                patch('brutal_cli.usb_inventory', return_value=[radio]), \
                patch('brutal_cli.check_profile', return_value={'missing': []}):
            output = []
            terminal = Terminal(root, Mock(side_effect=AssertionError('no prompt expected')), output.append)
            terminal.pick = Mock(side_effect=AssertionError('no menu expected'))
            report = terminal.readiness({'settings': {'hardware': {'profile': 'rtlv4'}}})
            self.assertEqual(report['selected_device']['node'], radio['node'])
            self.assertTrue(report['prerequisites_ready'])
            self.assertIn('/dev/bus/usb/001/005', '\n'.join(output))

    def test_several_matching_radios_still_ask_which_one(self):
        radios = [self._linux_radio('/dev/bus/usb/001/005'), self._linux_radio('/dev/bus/usb/001/006')]
        with tempfile.TemporaryDirectory() as root, self._ready_env(), \
                patch('brutal_cli.usb_inventory', return_value=radios), \
                patch('brutal_cli.check_profile', return_value={'missing': []}):
            terminal = Terminal(root, lambda _: '', lambda _: None)
            terminal.pick = Mock(return_value=radios[1])
            report = terminal.readiness({'settings': {'hardware': {'profile': 'rtlv4'}}})
            terminal.pick.assert_called_once()
            self.assertEqual(report['selected_device']['node'], radios[1]['node'])

    def test_manual_setup_removes_duplicate_frequencies_and_records_tdma(self):
        prompts = iter(['Dup system', 'Dup site', '851.0125, 851.0125, 852.5', 'y', 'y'])
        with tempfile.TemporaryDirectory() as root:
            terminal = Terminal(root, lambda _: next(prompts), lambda _: None)
            profile = terminal.manual({'profile': 'rtl', 'args': 'rtl', 'rate': 1000000, 'gains': 'LNA:39', 'ppm': 0})
            site = profile['system']['sites'][0]
            self.assertEqual(site['controls_hz'], [851012500, 852500000])
            self.assertTrue(site['tdma_cc'])

    def test_import_warnings_are_shown_and_capped(self):
        output = []
        terminal = Terminal(tempfile.gettempdir(), lambda _: '', output.append)
        terminal.report_import_warnings({'import_warnings': [f'note {i}' for i in range(11)]}, limit=3)
        text = '\n'.join(output)
        self.assertIn('11 database entries need attention', text)
        self.assertIn('note 2', text)
        self.assertNotIn('note 3', text)
        self.assertIn('...and 8 more.', text)
        output.clear()
        terminal.report_import_warnings({})
        self.assertEqual(output, [])

    def test_unreadable_saved_profile_is_reported_in_menu(self):
        with tempfile.TemporaryDirectory() as root:
            store = Path(root) / 'saved-profiles'
            store.mkdir()
            (store / ('c' * 32 + '.json')).write_text('{broken', encoding='utf-8')
            output = []
            terminal = Terminal(root, lambda _: 'q', output.append)
            terminal.loop()
            self.assertIn('could not be read', '\n'.join(output))
            self.assertIn('c' * 32 + '.json', '\n'.join(output))

    def test_handoff_exit_code_is_only_the_explicit_entrypoint_signal(self):
        from brutal_cli import main
        with patch('brutal_cli.sys.argv', ['brutal_cli.py']), \
                patch('brutal_cli.sys.stdin.isatty', return_value=True), \
                patch('brutal_cli.acquire_session_lock'), \
                patch('brutal_cli.Terminal.loop', side_effect=WindowsHandoff):
            with self.assertRaises(SystemExit) as exit:
                main()
            self.assertEqual(exit.exception.code, 88)


if __name__ == '__main__':
    unittest.main()
