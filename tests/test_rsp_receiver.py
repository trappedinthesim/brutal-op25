import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from rsp_receiver import network_arguments, network_main, selected_arguments, stop_receiver_then_service, wait_for_api


class RspReceiverTests(unittest.TestCase):
    def test_local_network_address_is_validated(self):
        self.assertEqual(network_arguments('172.20.208.1:1234'), 'rtl_tcp=172.20.208.1:1234')
        for address in ('8.8.8.8:1234', '0.0.0.0:1234', '172.20.208.1:22',
                        'localhost:1234', '172.20.208.1:bad'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                network_arguments(address)

    def test_windows_stream_uses_transient_config_without_linux_sdrplay_driver(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root) / 'active.json'
            config.write_text('{"devices":[{"args":"soapy=0,driver=sdrplay","rate":2000000,"gains":"IFGR:40,RFGR:0"}]}')
            with patch('rsp_receiver.active_config', return_value=config), \
                 patch('rsp_receiver.Path', return_value=config), \
                 patch('rsp_receiver.os.execvpe', side_effect=RuntimeError('exec intercepted')) as execute:
                with self.assertRaisesRegex(RuntimeError, 'exec intercepted'):
                    network_main('172.20.208.1:1234')
                self.assertEqual(execute.call_args.args[2]['OP25_PREPARED_CONFIG'], str(config))
                data = json.loads(config.read_text())
                self.assertEqual(data['devices'][0]['args'], 'rtl_tcp=172.20.208.1:1234')
                self.assertEqual(data['devices'][0]['rate'], 1000000)
                self.assertEqual(data['devices'][0]['gains'], 'LNA:20')

    def test_serial_is_bound_to_selected_radio(self):
        self.assertEqual(selected_arguments('EXAMPLE123'),
                         'soapy=0,driver=sdrplay,serial=EXAMPLE123')
        with self.assertRaises(ValueError):
            selected_arguments('../other-radio')

    def test_api_probe_waits_for_service_shared_memory(self):
        service = Mock()
        service.poll.return_value = None
        api = Mock()
        api.sdrplay_api_Open.return_value = 0
        def provide_version(version):
            version._obj.value = 3.15
            return 0
        api.sdrplay_api_ApiVersion.side_effect = provide_version
        with tempfile.TemporaryDirectory() as root:
            shared = Path(root) / 'service-ready'
            with patch('rsp_receiver.time.sleep', side_effect=lambda _: shared.touch()):
                wait_for_api(service, api, shared, timeout=5)
        api.sdrplay_api_Open.assert_called_once()
        api.sdrplay_api_Close.assert_called_once()

    def test_api_service_exit_is_reported_without_probe(self):
        service = Mock()
        service.poll.return_value = 1
        api = Mock()
        with self.assertRaisesRegex(RuntimeError, 'service exited'):
            wait_for_api(service, api, Path('/no/such/shared-memory'))
        api.sdrplay_api_Open.assert_not_called()

    def test_shutdown_releases_receiver_before_api_service(self):
        order = Mock()
        receiver = Mock()
        service = Mock()
        receiver.poll.return_value = None
        service.poll.return_value = None
        receiver.terminate.side_effect = order.receiver_terminate
        receiver.wait.side_effect = order.receiver_wait
        service.terminate.side_effect = order.service_terminate
        service.wait.side_effect = order.service_wait

        stop_receiver_then_service(receiver, service)

        self.assertEqual(order.mock_calls, [
            call.receiver_terminate(), call.receiver_wait(timeout=5),
            call.service_terminate(), call.service_wait(timeout=5),
        ])


if __name__ == '__main__':
    unittest.main()
