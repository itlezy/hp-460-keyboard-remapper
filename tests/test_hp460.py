import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import hp460

from hp460 import (
    ControlInterfaceBusyError,
    build_parser,
    build_button_clear_report,
    build_button_set_report,
    build_fn_lock_report,
    run_capture_vendor,
    run_collections,
    open_selected_device,
)


class ProtocolTests(unittest.TestCase):
    def test_collections_command_is_available(self) -> None:
        args = build_parser().parse_args(["collections"])
        self.assertIs(args.func, run_collections)

    def test_vendor_capture_command_is_available(self) -> None:
        args = build_parser().parse_args(["capture-vendor", "--seconds", "5"])
        self.assertIs(args.func, run_capture_vendor)
        self.assertEqual(args.seconds, 5)

    def test_fn_lock_states(self) -> None:
        expected = {
            (False, False): 0x02,
            (False, True): 0x03,
            (True, False): 0x06,
            (True, True): 0x07,
        }
        for state, value in expected.items():
            report = build_fn_lock_report(current=state[0], startup=state[1])
            self.assertEqual(len(report), 21)
            self.assertEqual(report[0], 0x06)
            self.assertEqual(report[16], value)
            self.assertEqual(report[-4:], bytes.fromhex("E0 16 0A F3"))

    def test_experimental_button_packet_matches_captured_layout(self) -> None:
        report = build_button_set_report(button_id=11, usage=0x45)
        self.assertEqual(
            report,
            bytes.fromhex(
                "06 00 0D 09 00 01 0B 00 00 04 F8 00 45 00 "
                "02 00 00 00 00 00 00"
            ),
        )

    def test_open_selected_device_reports_busy_control_interface(self) -> None:
        api = Mock()
        api.open_matching_devices.return_value = (
            [],
            [(r"\\?\hid#example&col06#blocked", 5)],
        )
        with (
            patch("hp460.WindowsHidApi", return_value=api),
            self.assertRaises(ControlInterfaceBusyError),
        ):
            open_selected_device(0)

    def test_experimental_button_clear_packet(self) -> None:
        report = build_button_clear_report(button_id=12)
        self.assertEqual(
            report,
            bytes.fromhex(
                "06 00 0D 05 00 01 0C 00 00 00 02 00 00 00 00 00 00 00 00 00 00"
            ),
        )

    def test_overlapped_write_completes_after_pending_io(self) -> None:
        api = hp460.WindowsHidApi.__new__(hp460.WindowsHidApi)
        api.kernel32 = Mock()
        api.kernel32.CreateEventW.return_value = 101
        api.kernel32.WriteFile.return_value = False
        api.kernel32.WaitForSingleObject.return_value = hp460.WAIT_OBJECT_0

        def complete(_handle, _overlapped, written, _wait):
            written._obj.value = hp460.REPORT_LENGTH
            return True

        api.kernel32.GetOverlappedResult.side_effect = complete
        device = SimpleNamespace(handle=202)

        with patch.object(ctypes, "get_last_error", return_value=hp460.ERROR_IO_PENDING):
            api.write(device, bytes(hp460.REPORT_LENGTH))

        self.assertIsNotNone(api.kernel32.WriteFile.call_args.args[4])
        api.kernel32.CancelIoEx.assert_not_called()
        api.kernel32.CloseHandle.assert_called_once_with(101)

    def test_overlapped_write_timeout_is_cancelled(self) -> None:
        api = hp460.WindowsHidApi.__new__(hp460.WindowsHidApi)
        api.kernel32 = Mock()
        api.kernel32.CreateEventW.return_value = 303
        api.kernel32.WriteFile.return_value = False
        api.kernel32.WaitForSingleObject.side_effect = [
            hp460.WAIT_TIMEOUT,
            hp460.WAIT_OBJECT_0,
        ]
        api.kernel32.CancelIoEx.return_value = True
        device = SimpleNamespace(handle=404)

        with (
            patch.object(ctypes, "get_last_error", return_value=hp460.ERROR_IO_PENDING),
            self.assertRaisesRegex(TimeoutError, "HID write timed out after 0.01 seconds"),
        ):
            api.write(device, bytes(hp460.REPORT_LENGTH), timeout_seconds=0.01)

        api.kernel32.CancelIoEx.assert_called_once()
        api.kernel32.CloseHandle.assert_called_once_with(303)


if __name__ == "__main__":
    unittest.main()
