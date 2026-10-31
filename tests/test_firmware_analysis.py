import struct
import unittest

from firmware_analysis import (
    FILE_HEADER_SIZE,
    FILE_MAP_BASE,
    decompress_runtime_data,
    file_offset_to_va,
    parse_header,
    va_to_file_offset,
)


class FirmwareAnalysisTests(unittest.TestCase):
    def test_address_translation_uses_thirteen_byte_container_header(self) -> None:
        self.assertEqual(va_to_file_offset(0x10000000), FILE_HEADER_SIZE)
        self.assertEqual(file_offset_to_va(FILE_HEADER_SIZE), 0x10000000)
        self.assertEqual(va_to_file_offset(0x100139A6), 0x139B3)

    def test_header_parses_vector_table_after_container_header(self) -> None:
        application = struct.pack("<II", 0x20006FE8, 0x10000249) + bytes(24)
        trailer = bytes(0x100)
        data = (
            struct.pack("<I", len(application))
            + bytes([0])
            + struct.pack("<II", 0x11, 0x22)
            + application
            + trailer
        )
        header = parse_header(data)
        self.assertEqual(header.application_length, len(application))
        self.assertEqual(header.initial_stack_pointer, 0x20006FE8)
        self.assertEqual(header.reset_handler, 0x10000249)

    def test_header_rejects_inconsistent_application_length(self) -> None:
        data = struct.pack("<I", 1) + bytes(FILE_HEADER_SIZE - 4 + 8 + 0x100)
        with self.assertRaisesRegex(ValueError, "application length"):
            parse_header(data)

    def test_runtime_decompressor_handles_literals_and_back_reference(self) -> None:
        source_va = 0x10000000
        container = bytes(FILE_HEADER_SIZE) + bytes([0x04, 0x00]) + b"ABC" + bytes([0x19, 0x03])
        output, consumed = decompress_runtime_data(
            container, source_va=source_va, output_size=6
        )
        self.assertEqual(output, b"ABCABC")
        self.assertEqual(consumed, 7)


if __name__ == "__main__":
    unittest.main()
