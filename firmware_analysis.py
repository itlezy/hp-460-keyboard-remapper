#!/usr/bin/env python3
"""Offline structural analysis for public HP Ash keyboard firmware images.

The script never opens a HID device and never modifies its input file.  HP
firmware is intentionally not distributed with this project; pass a locally
downloaded Ash_1200.FW image on the command line.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path


FILE_HEADER_SIZE = 13
FLASH_BASE = 0x10000000
FILE_MAP_BASE = FLASH_BASE - FILE_HEADER_SIZE
ASH_1200_SHA256 = "6e490ae055b9dfc9aa9e750f8693bd563a24ec2f060a84f12d250996a0e77c2e"

RUNTIME_DATA_SOURCE_VA = 0x10015990
RUNTIME_DATA_DESTINATION = 0x20001564
RUNTIME_DATA_SIZE = 0x0C3C
BUTTON_MAP_VA = 0x100139A6
BUTTON_DISPATCH_TABLE_VA = 0x1000F2F0
DIRECT_DISPATCH_TABLE_VA = 0x100038D8
KEY_MATRIX_VA = 0x10013820
KEY_MATRIX_ROWS = 13
KEY_MATRIX_COLUMNS = 10


BUTTON_ACTIONS = (
    "consumer mute",
    "consumer volume down",
    "consumer volume up",
    "consumer previous track",
    "consumer play/pause",
    "consumer next track",
    "keyboard Left GUI + ; (emoji shortcut)",
    "keyboard F13 / microphone-mute shortcut",
    "keyboard Scroll Lock (usage 0x47)",
    "keyboard Left GUI + I (settings shortcut)",
    "keyboard Left GUI + L (lock shortcut)",
    "keyboard Left Ctrl + F (search shortcut)",
    "language-switch / Stamp macro",
    "keyboard Insert (usage 0x49)",
    "keyboard Home (usage 0x4A)",
    "keyboard Page Up (usage 0x4B)",
    "keyboard Delete (usage 0x4C)",
    "keyboard End (usage 0x4D)",
    "keyboard Page Down (usage 0x4E)",
    "host/device function 19",
    "keyboard usage 0x47",
    "modifier + keyboard usage 0x07",
    "modifier + keyboard usage 0x04",
    "modifier + keyboard usage 0x0F",
)

VIRTUAL_KEY_NAMES = (
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
    "F8",
    "F9",
    "F10",
    "F11",
    "F12",
    "Stamp / Print Screen",
    "Insert",
    "Delete",
    "Home",
    "End",
    "Page Up",
    "Page Down",
)

DIRECT_ACTIONS = (
    "consumer mute",
    "consumer volume down",
    "consumer volume up",
    "consumer previous track",
    "consumer play/pause",
    "consumer next track",
    "keyboard Left GUI + ; (emoji shortcut)",
    "keyboard F13 / microphone-mute shortcut",
    "keyboard Scroll Lock (usage 0x47)",
    "keyboard Left GUI + I (settings shortcut)",
    "keyboard Left GUI + L (lock shortcut)",
    "keyboard Left Ctrl + F (search shortcut)",
    "no action in this dispatcher",
    "keyboard Insert (usage 0x49)",
    "keyboard Delete (usage 0x4C)",
    "consumer AL Local Machine Browser (usage 0x0192)",
    "keyboard Esc (usage 0x29; OS-dependent alternative 0x06)",
    "consumer Brightness Increment (usage 0x006F)",
    "consumer Brightness Decrement (usage 0x0070)",
    "host/device function 19",
    "host/device function 20",
    "host/device function 21",
    "host/device function 22",
    "default / no action",
)


@dataclass(frozen=True)
class FirmwareHeader:
    application_length: int
    flags: int
    trailer_field_1: int
    trailer_field_2: int
    initial_stack_pointer: int
    reset_handler: int


def va_to_file_offset(address: int) -> int:
    """Translate a flash virtual address to an updater-file offset."""
    return address - FILE_MAP_BASE


def file_offset_to_va(offset: int) -> int:
    """Translate an updater-file offset to a flash virtual address."""
    return FILE_MAP_BASE + offset


def parse_header(data: bytes) -> FirmwareHeader:
    if len(data) < FILE_HEADER_SIZE + 8:
        raise ValueError("file is too short to contain an Ash header and vector table")

    application_length = struct.unpack_from("<I", data, 0)[0]
    expected_length = len(data) - FILE_HEADER_SIZE - 0x100
    if application_length != expected_length:
        raise ValueError(
            "header application length does not match file size: "
            f"0x{application_length:X} != 0x{expected_length:X}"
        )

    initial_stack_pointer, reset_handler = struct.unpack_from("<II", data, FILE_HEADER_SIZE)
    return FirmwareHeader(
        application_length=application_length,
        flags=data[4],
        trailer_field_1=struct.unpack_from("<I", data, 5)[0],
        trailer_field_2=struct.unpack_from("<I", data, 9)[0],
        initial_stack_pointer=initial_stack_pointer,
        reset_handler=reset_handler,
    )


def decompress_runtime_data(
    data: bytes,
    *,
    source_va: int = RUNTIME_DATA_SOURCE_VA,
    output_size: int = RUNTIME_DATA_SIZE,
) -> tuple[bytes, int]:
    """Reproduce the compact initializer implemented at flash 0x10001B7C."""
    source_offset = va_to_file_offset(source_va)
    source = memoryview(data)[source_offset:]
    output = bytearray()
    cursor = 0

    def take() -> int:
        nonlocal cursor
        if cursor >= len(source):
            raise ValueError("compressed runtime-data stream ended unexpectedly")
        value = source[cursor]
        cursor += 1
        return value

    while len(output) < output_size:
        token = take()
        literal_code = token & 0x07
        if literal_code == 0:
            literal_code = take()
        run_code = token >> 4
        if run_code == 0:
            run_code = take()

        literal_count = max(0, literal_code - 1)
        for _ in range(literal_count):
            output.append(take())

        if token & 0x08:
            distance = take()
            if distance == 0 or distance > len(output):
                raise ValueError(f"invalid back-reference distance {distance}")
            for _ in range(run_code + 2):
                output.append(output[-distance])
        else:
            output.extend(bytes(run_code))

        if len(output) > output_size:
            raise ValueError("runtime-data stream expanded past its declared size")

    return bytes(output), cursor


def parse_button_map(data: bytes) -> tuple[int, ...]:
    offset = va_to_file_offset(BUTTON_MAP_VA)
    count = data[offset]
    mapping = tuple(data[offset + 1 : offset + 1 + count])
    if len(mapping) != count:
        raise ValueError("truncated programmable-button mapping table")
    return mapping


def parse_key_matrix(data: bytes) -> tuple[tuple[int, ...], ...]:
    """Decode the Ash 13-by-10 physical-matrix usage table."""
    offset = va_to_file_offset(KEY_MATRIX_VA)
    count = KEY_MATRIX_ROWS * KEY_MATRIX_COLUMNS
    byte_count = count * 2
    raw = data[offset : offset + byte_count]
    if len(raw) != byte_count:
        raise ValueError("truncated keyboard matrix table")
    values = struct.unpack(f"<{count}H", raw)
    return tuple(
        tuple(values[index : index + KEY_MATRIX_COLUMNS])
        for index in range(0, count, KEY_MATRIX_COLUMNS)
    )


def virtual_key_positions(
    matrix: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, int, int], ...]:
    """Return ``(button_id, row, column)`` for virtual codes 0x100..0x112."""
    positions: list[tuple[int, int, int]] = []
    for button_id in range(len(VIRTUAL_KEY_NAMES)):
        code = 0x0100 + button_id
        matches = [
            (row, column)
            for row, values in enumerate(matrix)
            for column, value in enumerate(values)
            if value == code
        ]
        if len(matches) != 1:
            raise ValueError(
                f"virtual key 0x{code:04X} occurs {len(matches)} times in matrix"
            )
        row, column = matches[0]
        positions.append((button_id, row, column))
    return tuple(positions)


def parse_dispatch_targets(data: bytes) -> tuple[int, ...]:
    offset = va_to_file_offset(BUTTON_DISPATCH_TABLE_VA)
    count = data[offset]
    relative_halfwords = data[offset + 1 : offset + 1 + count]
    if len(relative_halfwords) != count:
        raise ValueError("truncated programmable-button jump table")
    table_base = BUTTON_DISPATCH_TABLE_VA
    return tuple(table_base + value * 2 for value in relative_halfwords)


def parse_direct_dispatch_targets(data: bytes) -> tuple[int, ...]:
    """Decode the direct-layer inline switch used with Fn Lock on."""
    offset = va_to_file_offset(DIRECT_DISPATCH_TABLE_VA)
    count = data[offset]
    relative_halfwords = data[offset + 1 : offset + 1 + count]
    if len(relative_halfwords) != count:
        raise ValueError("truncated direct-layer jump table")
    table_base = DIRECT_DISPATCH_TABLE_VA + 1
    return tuple((table_base + value * 2) & ~1 for value in relative_halfwords)


def authentication_sized_blocks(data: bytes) -> tuple[tuple[int, int], ...]:
    """Locate signature-sized opaque tail regions without claiming their format."""
    candidates: list[tuple[int, int]] = []
    search_start = max(0, len(data) - 0x800)
    marker = bytes.fromhex("04 01 00 00")
    cursor = search_start
    while True:
        marker_offset = data.find(marker, cursor, len(data) - 0x100)
        if marker_offset < 0:
            break
        payload_offset = marker_offset + len(marker)
        if payload_offset + 0x100 <= len(data):
            candidates.append((payload_offset, 0x100))
        cursor = marker_offset + 1

    final_block = (len(data) - 0x100, 0x100)
    if final_block not in candidates:
        candidates.append(final_block)
    return tuple(sorted(set(candidates)))


def report(path: Path) -> str:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    header = parse_header(data)
    runtime_data, compressed_length = decompress_runtime_data(data)
    key_matrix = parse_key_matrix(data)
    key_positions = virtual_key_positions(key_matrix)
    button_map = parse_button_map(data)
    dispatch_targets = parse_dispatch_targets(data)
    direct_dispatch_targets = parse_direct_dispatch_targets(data)

    lines = [
        f"file: {path}",
        f"length: {len(data)} (0x{len(data):X})",
        f"sha256: {digest}",
        f"known Ash 1.2.0: {'yes' if digest == ASH_1200_SHA256 else 'no'}",
        "",
        "header and memory map:",
        f"  application length: 0x{header.application_length:X}",
        f"  flags: 0x{header.flags:02X}",
        f"  trailer fields: 0x{header.trailer_field_1:X}, 0x{header.trailer_field_2:X}",
        f"  initial SP: 0x{header.initial_stack_pointer:08X}",
        f"  reset handler: 0x{header.reset_handler:08X}",
        f"  file mapping base: 0x{FILE_MAP_BASE:08X}",
        "",
        "runtime initializer:",
        f"  source: 0x{RUNTIME_DATA_SOURCE_VA:08X}",
        f"  destination: 0x{RUNTIME_DATA_DESTINATION:08X}",
        f"  compressed bytes consumed: 0x{compressed_length:X}",
        f"  expanded bytes: 0x{len(runtime_data):X}",
        "",
        f"keyboard matrix ({KEY_MATRIX_ROWS} rows x {KEY_MATRIX_COLUMNS} columns):",
    ]
    for row, values in enumerate(key_matrix):
        lines.append(f"  row {row:2d}: " + " ".join(f"{value:04X}" for value in values))

    lines.extend(
        [
            "",
            "matrix virtual keys and action indices:",
        ]
    )
    for button_id, row, column in key_positions:
        lines.append(
            f"  0x{0x100 + button_id:04X} -> ID {button_id:2d} "
            f"at row {row:2d}, column {column}: {VIRTUAL_KEY_NAMES[button_id]}"
        )

    lines.extend(
        [
            "",
            "authentication-sized opaque tail blocks:",
        ]
    )
    for offset, length in authentication_sized_blocks(data):
        lines.append(f"  file 0x{offset:X}..0x{offset + length:X} ({length} bytes)")

    lines.extend(
        [
            "",
            f"programmable-button bit map ({len(button_map)} entries):",
            "  " + " ".join(f"{value:02X}" for value in button_map),
            f"  identity: {'yes' if button_map == tuple(range(len(button_map))) else 'no'}",
            "",
            "default special-key dispatcher:",
        ]
    )
    for index, (target, action) in enumerate(zip(dispatch_targets, BUTTON_ACTIONS)):
        lines.append(f"  {index:2d}: 0x{target:08X}  {action}")

    lines.extend(["", "Fn-Lock-on direct-layer dispatcher:"])
    for index, (target, action) in enumerate(
        zip(direct_dispatch_targets, DIRECT_ACTIONS)
    ):
        lines.append(f"  {index:2d}: 0x{target:08X}  {action}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", type=Path, help="path to a local Ash_1200.FW image")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(report(args.firmware))
    except (OSError, ValueError) as error:
        raise SystemExit(f"error: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
