"""Emulate the key transformer with Unicorn; never opens hardware or writes firmware.

External direct-dispatch calls are recorded and stubbed. Native conversion and
report insertion execute actual firmware instructions. This is a function test,
not full-device/bootloader emulation.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import ASH_1200_SHA256, KEY_MATRIX_VA, parse_key_matrix, va_to_file_offset, virtual_key_positions


def main() -> None:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    original = args.image.read_bytes()
    if hashlib.sha256(original).hexdigest() != ASH_1200_SHA256:
        raise SystemExit("Requires unmodified Ash 1.2.0 SHA256")
    patched = bytearray(original)
    assert patched[0x742D:0x7431] == bytes.fromhex("09 D0 20 46")
    patched[0x742D:0x7431] = bytes.fromhex("2D D0 2C E0")
    expected = list(range(0x3A, 0x46)) + [0x46, 0x49, 0x4C, 0x4A, 0x4D, 0x4B, 0x4E]
    matrix_image = bytearray(original)
    matrix_inputs = []
    for action, row, column in virtual_key_positions(parse_key_matrix(original)):
        offset = va_to_file_offset(KEY_MATRIX_VA) + (row * 10 + column) * 2
        struct.pack_into("<H", matrix_image, offset, expected[action])
        matrix_inputs.append(struct.unpack_from("<H", matrix_image, offset)[0])
    results = []
    runs = 0
    scenarios = [("stock", original, 1, 0), ("branch", patched, 1, 0)]
    scenarios += [("matrix", matrix_image, lock, fn) for lock, fn in itertools.product(range(2), repeat=2)]
    for variant, image, lock, fn in scenarios:
        engine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        engine.mem_map(0x10000000, 0x20000)
        engine.mem_map(0x20000000, 0x10000)
        engine.mem_write(0x10000000, bytes(image[13:]))
        calls = []

        def on_instruction(uc, address, size, _):
            if address == 0x1001FFF0:
                uc.emu_stop()
            elif address == 0x100038B4:
                calls.append("direct")
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            elif address not in range(0x100072F8, 0x10007530) and address not in range(0x10004284, 0x10004370) and address not in range(0x1000AFF2, 0x1000B020):
                raise RuntimeError(f"Unexpected firmware execution 0x{address:08X}")

        engine.hook_add(UC_HOOK_CODE, on_instruction)
        for key, modifiers in itertools.product(range(19), range(256)):
            engine.mem_write(0x20000000, bytes(0x10000))
            engine.mem_write(0x20001BE9, bytes([lock]))
            engine.mem_write(0x20001BE6, bytes([fn]))
            engine.mem_write(0x200027A5, bytes([modifiers]))
            calls.clear()
            key_input = matrix_inputs[key] if variant == "matrix" else 0x100 + key
            for reg, value in ((UC_ARM_REG_R0, key_input), (UC_ARM_REG_R1, 0x20008000), (UC_ARM_REG_R2, 0x20008100), (UC_ARM_REG_R3, 0), (UC_ARM_REG_SP, 0x2000F000), (UC_ARM_REG_LR, 0x1001FFF1)):
                engine.reg_write(reg, value)
            engine.emu_start(0x100072F9, 0x1001FFF0, count=2000)
            assert engine.reg_read(UC_ARM_REG_PC) == 0x1001FFF0, "Execution did not return"
            count = engine.mem_read(0x20008100, 1)[0]
            usage = engine.mem_read(0x200027A6, 1)[0]
            special = int.from_bytes(engine.mem_read(0x200027BC, 4), "little")
            runs += 1
            if variant != "stock" or key < 12:
                assert count == 1 and usage == expected[key] and not special and not calls, (variant, key, modifiers, count, usage, special, calls)
                assert engine.mem_read(0x200027A5, 1)[0] == modifiers
            if modifiers == 0:
                results.append(f"{variant:7} lock={lock} fn={fn} action {key:2}: count={count} usage=0x{usage:02X} special=0x{special:08X} calls={calls}")
    print("\n".join(results))
    print(f"PASS: {runs:,} function runs; all 19 candidate keys preserve all 256 modifier masks.")
    print("Matrix candidate passes all four Fn Lock / Fn states.")
    print("Limit: one key, default mode; scanner and Bluetooth are not emulated, external direct dispatcher is stubbed.")


if __name__ == "__main__":
    main()
