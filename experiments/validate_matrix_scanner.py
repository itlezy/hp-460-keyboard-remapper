"""Emulate the actual Ash 16x8 scanner loop with one asserted matrix bit.

Executes cached-scan processing, not electrical scanning. List manipulation and
report dispatch are stubbed; captured keycodes feed the separate transformer test.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import ASH_1200_SHA256, KEY_MATRIX_VA, KEY_MATRIX_COLUMNS, parse_key_matrix, va_to_file_offset, virtual_key_positions


def main() -> None:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    original = args.image.read_bytes()
    if hashlib.sha256(original).hexdigest() != ASH_1200_SHA256:
        raise SystemExit("Requires unmodified Ash 1.2.0")
    expected = list(range(0x3A, 0x46)) + [0x46, 0x49, 0x4C, 0x4A, 0x4D, 0x4B, 0x4E]
    patched = bytearray(original)
    for action, row, column in virtual_key_positions(parse_key_matrix(original)):
        offset = va_to_file_offset(KEY_MATRIX_VA) + 2 * (row * KEY_MATRIX_COLUMNS + column)
        struct.pack_into("<H", patched, offset, expected[action])
    for name, data in (("stock", original), ("matrix", patched)):
        engine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        engine.mem_map(0x10000000, 0x20000)
        engine.mem_map(0x20000000, 0x10000)
        engine.mem_write(0x10000000, bytes(data[13:]))
        observed = []

        def instruction(uc, address, size, _):
            if address == 0x1001FFF0:
                uc.emu_stop()
            elif address == 0x10001BD4:  # list contains: false
                uc.reg_write(UC_ARM_REG_R0, 0)
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            elif address == 0x10001BEC:  # insert keycode into list
                observed.append(uc.reg_read(UC_ARM_REG_R0))
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            elif address in (0x10001BE0, 0x10001BF8, 0x10001C04, 0x10003380):
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            elif address not in range(0x10002D5C, 0x10002E1C):
                raise RuntimeError(f"Unexpected execution 0x{address:08X}")

        engine.hook_add(UC_HOOK_CODE, instruction)
        values = [value for row in parse_key_matrix(bytes(data)) for value in row]
        for slot, value in enumerate(values):
            engine.mem_write(0x20000000, bytes(0x10000))
            scan = bytearray(16)
            scan[slot // 8] |= 1 << (slot % 8)
            engine.mem_write(0x20002833, bytes(scan))
            observed.clear()
            for register, val in ((UC_ARM_REG_R0, 1), (UC_ARM_REG_SP, 0x2000F000), (UC_ARM_REG_LR, 0x1001FFF1)):
                engine.reg_write(register, val)
            engine.emu_start(0x10002D5D, 0x1001FFF0, count=10000)
            assert engine.reg_read(UC_ARM_REG_PC) == 0x1001FFF0
            assert observed == ([value] if value else []), (name, slot, value, observed)
        print(f"PASS {name}: all 128 cached scan bits map to the exact flash table keycodes")
    print("PASS: scanner confirms base=0x10013822, 16 scan bytes x 8 bits; no RAM table indirection")


if __name__ == "__main__":
    main()
