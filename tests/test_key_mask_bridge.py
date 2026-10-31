import unittest

from experiments.key_mask_bridge import MaskTracker, decode_mask


class KeyMaskBridgeTests(unittest.TestCase):
    def test_notification_marker_size_and_non_frow_bits(self):
        self.assertEqual(decode_mask(bytes.fromhex("02 00 03 A5 41 08")), 0x841)
        self.assertEqual(decode_mask(bytes.fromhex("02 00 03 A5 00 F0")), 0)
        for value in ("00 18 00 01 18", "02 00 03 A6 41 08", "02 00 03 A5 41 08 00"):
            with self.assertRaises(ValueError):
                decode_mask(bytes.fromhex(value))

    def test_chords_transition_without_repeating_held_keys(self):
        tracker = MaskTracker()
        self.assertEqual(tracker.update(0x9), [("F1", True), ("F4", True)])
        self.assertEqual(tracker.update(0x9), [])
        self.assertEqual(tracker.update(0x48), [("F1", False), ("F7", True)])
        self.assertEqual(tracker.release(), [("F4", False), ("F7", False)])
        self.assertEqual(tracker.release(), [])

    def test_every_simultaneous_frow_combination_and_cleanup(self):
        for mask in range(4096):
            tracker = MaskTracker()
            down = tracker.update(mask)
            up = tracker.release()
            self.assertEqual([key for key, state in down], [key for key, state in up])
            self.assertTrue(all(state for key, state in down))
            self.assertTrue(all(not state for key, state in up))
            self.assertEqual(len(down), mask.bit_count())


if __name__ == "__main__":
    unittest.main()
