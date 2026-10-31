import unittest

from hp460 import (
    build_parser,
    build_button_clear_report,
    build_button_set_report,
    build_fn_lock_report,
    run_capture_vendor,
    run_collections,
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

    def test_experimental_button_clear_packet(self) -> None:
        report = build_button_clear_report(button_id=12)
        self.assertEqual(
            report,
            bytes.fromhex(
                "06 00 0D 05 00 01 0C 00 00 00 02 00 00 00 00 00 00 00 00 00 00"
            ),
        )


if __name__ == "__main__":
    unittest.main()
