"""Replay Ash's bytecode branch and bit-reader bounds checks offline.

No HID/Bluetooth access. The test supplies synthetic RAM preceding a program;
an out-of-buffer fetch is not an established live memory-read/write command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import ASH_1200_SHA256


def encoded_displacement(delta: int, *, extended: bool = False) -> bytes:
    if not extended and -256 <= delta <= 255:
        return struct.pack("<I", delta & 0x1FF)
    if not -131072 <= delta <= 131071:
        raise ValueError("Extended displacement is signed 18-bit")
    # First field: nine low bits + extension indicator. Second: upper bits.
    value = (delta & 0x1FF) | 0x200 | (((delta >> 9) & 0x3FF) << 10)
    return struct.pack("<I", value)


def audit(data: bytes) -> dict:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

    if hashlib.sha256(data).hexdigest() != ASH_1200_SHA256:
        raise ValueError("Requires exact stock Ash 1.2.0")
    engine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    engine.mem_map(0x10000000, 0x20000)
    engine.mem_map(0x20000000, 0x40000)
    engine.mem_write(0x10000000, data[13:])
    state, code, output, stop = 0x20008000, 0x20020000, 0x20008100, 0x1001FFF0
    reads, writes, frees = [], [], []

    def observe_read(machine, access, address, size, value, user):
        reads.append((address, size))

    def observe_write(machine, access, address, size, value, user):
        writes.append((address, size))

    def intercept_free(machine, address, size, user):
        frees.append(machine.reg_read(UC_ARM_REG_R0))
        machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))

    engine.hook_add(UC_HOOK_MEM_READ, observe_read, begin=0x20000000, end=0x2003FFFF)
    engine.hook_add(UC_HOOK_MEM_WRITE, observe_write, begin=0x20000000, end=0x2003FFFF)
    engine.hook_add(UC_HOOK_CODE, intercept_free, begin=0x10000EA6, end=0x10000EA6)

    def initialize(bits=64, cursor=0):
        engine.mem_write(state, struct.pack("<5I", bits, code, cursor & 0xFFFFFFFF, 0, 0))
        engine.mem_write(output, bytes(4))
        reads.clear()
        writes.clear()
        frees.clear()

    def run(address, *arguments):
        engine.reg_write(UC_ARM_REG_SP, 0x2003F000)
        engine.reg_write(UC_ARM_REG_LR, stop | 1)
        for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), arguments):
            engine.reg_write(register, value)
        engine.emu_start(address | 1, stop, count=2000)
        assert engine.reg_read(UC_ARM_REG_PC) == stop
        return engine.reg_read(UC_ARM_REG_R0)

    def cursor():
        return struct.unpack("<i", engine.mem_read(state + 8, 4))[0]

    cases = 0
    negative_targets = 0
    for extended, displacements in (
        (False, range(-256, 256)),
        (True, (-131072, -65536, -1024, -512, -276, -1, 0, 1, 64, 512, 65535, 131071)),
    ):
        consumed = 20 if extended else 10
        for delta in displacements:
            engine.mem_write(code, encoded_displacement(delta, extended=extended))
            initialize()
            result = run(0x1000A104, state, 1)
            target = consumed + delta
            if delta == 0:
                assert result == 0 and cursor() == consumed
            elif target <= 64:
                assert result == 1 and cursor() == target, (extended, delta, result, cursor())
                negative_targets += target < 0
            else:
                assert result == 0 and bytes(engine.mem_read(state, 20)) == bytes(20)
            assert not frees
            cases += 1

    # A real branch, not a direct cursor edit, selects a byte before the buffer.
    engine.mem_write(code, encoded_displacement(-276, extended=True))
    engine.mem_write(code - 32, b"\xA5\x5A\xC3\x3C")
    initialize()
    assert run(0x1000A104, state, 1) == 1 and cursor() == -256
    reads.clear()
    writes.clear()
    assert run(0x10005E12, state, 8, output) == 1
    observed = struct.unpack("<I", engine.mem_read(output, 4))[0]
    assert observed == 0xA5 and cursor() == -248
    assert any(address == code - 32 for address, _ in reads)
    # The fetch is a read. It does not itself modify the preceding buffer.
    assert all(not (address < code and address + size > code - 32) for address, size in writes)
    assert bytes(engine.mem_read(0x20001BE0, 1)) == b"\0"

    # Upper-bound rejection remains effective for a positive cursor.
    initialize(bits=8, cursor=8)
    assert run(0x10005E12, state, 1, output) == 0
    assert bytes(engine.mem_read(state, 20)) == bytes(20)

    return {
        "image_sha256": ASH_1200_SHA256,
        "branch_cases": cases,
        "accepted_negative_targets": negative_targets,
        "out_of_buffer_fetch": {"cursor_bits": -256, "bytes_before_buffer": 32,
                                "synthetic_marker": "A5", "observed_value": f"{observed:02X}"},
        "positive_read_past_end_rejected": True,
        "native_mode_flag_written": False,
        "hardware_access": False,
        "limitations": "Original branch/reader only; synthetic preceding RAM; no live dump, RAM setter or code execution established",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.image.read_bytes()), indent=2))


if __name__ == "__main__":
    main()
