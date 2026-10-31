import struct
import unittest

from firmware_analysis import (
    FILE_HEADER_SIZE,
    FILE_MAP_BASE,
    KEY_MATRIX_COLUMNS,
    KEY_MATRIX_ROWS,
    KEY_MATRIX_VA,
    decompress_runtime_data,
    file_offset_to_va,
    parse_key_matrix,
    parse_direct_dispatch_targets,
    parse_header,
    va_to_file_offset,
    virtual_key_positions,
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

    def test_matrix_parser_decodes_rows_and_virtual_key_positions(self) -> None:
        offset = va_to_file_offset(KEY_MATRIX_VA)
        count = KEY_MATRIX_ROWS * KEY_MATRIX_COLUMNS
        values = [0] * count
        expected_positions = []
        for button_id in range(19):
            index = button_id * 3
            values[index] = 0x0100 + button_id
            expected_positions.append(
                (button_id, index // KEY_MATRIX_COLUMNS, index % KEY_MATRIX_COLUMNS)
            )
        data = bytearray(offset + count * 2)
        struct.pack_into(f"<{count}H", data, offset, *values)

        matrix = parse_key_matrix(bytes(data))

        self.assertEqual(len(matrix), KEY_MATRIX_ROWS)
        self.assertTrue(all(len(row) == KEY_MATRIX_COLUMNS for row in matrix))
        self.assertEqual(virtual_key_positions(matrix), tuple(expected_positions))

    def test_virtual_key_positions_rejects_missing_code(self) -> None:
        matrix = tuple(
            tuple(0 for _ in range(KEY_MATRIX_COLUMNS))
            for _ in range(KEY_MATRIX_ROWS)
        )
        with self.assertRaisesRegex(ValueError, "0x0100 occurs 0 times"):
            virtual_key_positions(matrix)

    def test_direct_dispatch_parser_decodes_inline_relative_targets(self) -> None:
        table_va = 0x100038D8
        offset = va_to_file_offset(table_va)
        data = bytearray(offset + 4)
        data[offset : offset + 4] = bytes([3, 1, 2, 3])
        self.assertEqual(
            parse_direct_dispatch_targets(bytes(data)),
            (table_va + 2, table_va + 4, table_va + 6),
        )


if __name__ == "__main__":
    unittest.main()
