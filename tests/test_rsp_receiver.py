import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from rsp_receiver import selected_arguments, stop_receiver_then_service, wait_for_api


class RspReceiverTests(unittest.TestCase):
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
