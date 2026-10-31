"""Test stock Ash's F-row polarity flag offline; no live RAM write mechanism.

Only emulated RAM is changed. Native conversion executes original ARM code;
the alternate direct dispatcher is recorded and stubbed for baseline checks.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import ASH_1200_SHA256


def main():
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    data = args.image.read_bytes()
    if hashlib.sha256(data).hexdigest() != ASH_1200_SHA256:
        raise SystemExit("Requires exact stock Ash 1.2.0")
    engine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    engine.mem_map(0x10000000, 0x20000)
    engine.mem_map(0x20000000, 0x10000)
    engine.mem_write(0x10000000, data[13:])
    direct = []

    def intercept(machine, address, size, user):
        direct.append(machine.reg_read(UC_ARM_REG_R0))
        machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))

    engine.hook_add(UC_HOOK_CODE, intercept, begin=0x100038B4, end=0x100038B4)
    expected = list(range(0x3A, 0x46)) + [0x46, 0x49, 0x4C, 0x4A, 0x4D, 0x4B, 0x4E]
    runs = 0
    for flag, lock, key, modifiers in itertools.product(range(2), range(2), range(19), range(256)):
        engine.mem_write(0x20000000, bytes(0x10000))
        engine.mem_write(0x20001BE0, bytes((flag,)))
        engine.mem_write(0x20001BE9, bytes((lock,)))
        engine.mem_write(0x200027A5, bytes((modifiers,)))
        direct.clear()
        for register, value in ((UC_ARM_REG_R0, 0x100 + key), (UC_ARM_REG_R1, 0x20008000),
                                (UC_ARM_REG_R2, 0x20008100), (UC_ARM_REG_R3, 0),
                                (UC_ARM_REG_SP, 0x2000F000), (UC_ARM_REG_LR, 0x1001FFF1)):
            engine.reg_write(register, value)
        engine.emu_start(0x100072F9, 0x1001FFF0, count=2000)
        if engine.reg_read(UC_ARM_REG_PC) != 0x1001FFF0:
            raise RuntimeError("Transformer did not return")
        count = engine.mem_read(0x20008100, 1)[0]
        usage = engine.mem_read(0x200027A6, 1)[0]
        special = int.from_bytes(engine.mem_read(0x200027BC, 4), "little")
        native = (flag != lock) if key < 12 else not lock
        if native:
            assert (count, usage, special, direct) == (1, expected[key], 0, []), (flag, lock, key, modifiers)
        elif key <= 12:
            assert count == 0 and special == 1 << key and not direct
        else:
            assert count == special == 0 and direct == [0x100 + key]
        assert engine.mem_read(0x200027A5, 1)[0] == modifiers
        runs += 1
    print(f"PASS {runs:,} original-transformer runs: both flag values, both Fn Lock values, 19 keys, all 256 modifier bytes")
    print("PASS flag 0x20001BE0=1 + Fn Lock OFF + Fn released: all 19 keys native, no special mask or direct dispatcher")
    print("Limits: only emulated RAM; no HID-accessible setter, persistence, full scanner/transport, rollover or hardware execution proved")


if __name__ == "__main__":
    main()
