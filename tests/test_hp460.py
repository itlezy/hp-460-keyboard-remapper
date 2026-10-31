import unittest

from hp460 import (
    NAV_ASSIGNMENTS,
    build_parser,
    build_fn_lock_report,
    build_nav_restore_report,
    build_nav_set_report,
    selected_assignments,
)


class ProtocolTests(unittest.TestCase):
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

    def test_navigation_packets_match_captured_layout(self) -> None:
        expected = {
            "print-screen": (12, 0x46),
            "home": (14, 0x4A),
            "end": (17, 0x4D),
            "page-up": (15, 0x4B),
            "page-down": (18, 0x4E),
        }
        for assignment in NAV_ASSIGNMENTS:
            slot, usage = expected[assignment.name]
            report = build_nav_set_report(assignment)
            self.assertEqual(len(report), 21)
            self.assertEqual(report[:6], bytes.fromhex("06 00 0D 09 00 01"))
            self.assertEqual(report[6], slot)
            self.assertEqual(report[7:12], bytes.fromhex("00 00 04 F8 00"))
            self.assertEqual(report[12], usage)
            self.assertEqual(report[13:15], bytes.fromhex("00 02"))

    def test_restore_packets_clear_program(self) -> None:
        for assignment in NAV_ASSIGNMENTS:
            report = build_nav_restore_report(assignment)
            self.assertEqual(len(report), 21)
            self.assertEqual(report[:6], bytes.fromhex("06 00 0D 05 00 01"))
            self.assertEqual(report[6], assignment.slot)
            self.assertEqual(report[7:11], bytes.fromhex("00 00 00 02"))

    def test_key_filter_preserves_protocol_order(self) -> None:
        selected = selected_assignments(["end", "home"])
        self.assertEqual([item.name for item in selected], ["home", "end"])

    def test_setup_defaults_to_live_canonical_configuration(self) -> None:
        args = build_parser().parse_args(["setup"])
        self.assertFalse(args.dry_run)
        self.assertEqual(args.device_index, 0)
        self.assertEqual(args.delay, 0.3)


if __name__ == "__main__":
    unittest.main()
