import unittest

from experiments.button_transport import ButtonReply, decode_button_reply, frame_button_payload


class ButtonTransportTests(unittest.TestCase):
    def test_native_f12_framing_matches_actual_hpac_capture(self):
        expected = bytes.fromhex("06 00 0D 09 00 01 0B 00 00 04 F8 00 45 00 02 00 00 00 00 00 00")
        self.assertEqual(frame_button_payload(bytes.fromhex("01 0B 00 00 04 F8 00 45 00")), [expected])

    def test_decode_actual_three_fragment_button_reply(self):
        decoder = ButtonReply()
        frames = [bytes.fromhex(value) for value in (
            "06 01 0D 2D 00 00 18 05 01 18 0C 01 00 04 F8 00 46 00 0E 01 00",
            "06 01 0D 2D 04 04 F8 00 4A 00 11 01 00 04 F8 00 4D 00 0F 01 00",
            "06 01 0D 2D 08 04 F8 00 4B 00 12 01 00 04 F8 00 4E 00 00 00 00",
        )]
        self.assertIsNone(decoder.add(frames[0]))
        self.assertIsNone(decoder.add(frames[1]))
        result = decode_button_reply(decoder.add(frames[2]))
        self.assertEqual(result["capacity"], 24)
        self.assertEqual([(entry["button_id"], entry["program_hex"]) for entry in result["records"]],
                         [(12, "f8004600"), (14, "f8004a00"), (17, "f8004d00"), (15, "f8004b00"), (18, "f8004e00")])

    def test_missing_or_changed_fragment_is_rejected(self):
        first = bytes.fromhex("06 01 0D 2D 00") + bytes(16)
        for header in ("06 01 0D 2D 08", "06 01 0D 2E 04"):
            decoder = ButtonReply()
            decoder.add(first)
            with self.assertRaises(ValueError):
                decoder.add(bytes.fromhex(header) + bytes(16))

    def test_extended_program_length_and_truncation(self):
        payload = bytes((0, 24, 1, 1, 0x18, 6, 1, 0, 0x80, 1)) + bytes(128)
        self.assertEqual(decode_button_reply(payload)["records"][0]["length"], 128)
        with self.assertRaisesRegex(ValueError, "Truncated program"):
            decode_button_reply(payload[:-1])
        with self.assertRaisesRegex(ValueError, "trailing"):
            decode_button_reply(payload + b"\0")

    def test_framing_bounds_and_six_bit_sequence_limit(self):
        for length in (0, 1024):
            with self.assertRaises(ValueError):
                frame_button_payload(bytes(length))
        frames = frame_button_payload(bytes(1023))
        self.assertEqual(len(frames), 64)
        self.assertEqual(frames[-1][4], 255)
        self.assertTrue(all(len(frame) == 21 for frame in frames))


if __name__ == "__main__":
    unittest.main()
