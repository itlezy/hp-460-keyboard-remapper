"""Offline native-mode access audit: GPIO sampling, settings and transfer adapter.

Uses original Ash 1.2 instructions. LED calls and a transport sink are stubbed;
peripheral input values are supplied by the emulator. Never opens a device.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import ASH_1200_SHA256, decompress_runtime_data


def main():
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    data = args.image.read_bytes()
    if hashlib.sha256(data).hexdigest() != ASH_1200_SHA256:
        raise SystemExit("Requires exact stock Ash 1.2.0")
    runtime, _ = decompress_runtime_data(data)
    initial = data[13 + 0x1442C:13 + 0x15990] + runtime
    machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    machine.mem_map(0x10000000, 0x20000)
    machine.mem_map(0x20000000, 0x10000)
    machine.mem_map(0x50000000, 0x2000)
    machine.mem_write(0x10000000, data[13:])
    flag, flags_written, packets = 0x20001BE0, [], []
    sink = 0x1001FFE0

    def intercept(engine, address, size, user):
        if address == sink:
            pointer, length = engine.reg_read(UC_ARM_REG_R0), engine.reg_read(UC_ARM_REG_R1)
            packets.append(bytes(engine.mem_read(pointer, length)))
            engine.reg_write(UC_ARM_REG_R0, 1)
        engine.reg_write(UC_ARM_REG_PC, engine.reg_read(UC_ARM_REG_LR))

    for address in (0x10003E40, 0x1000400C, sink):
        machine.hook_add(UC_HOOK_CODE, intercept, begin=address, end=address)

    def watch(engine, access, address, size, value, user):
        if address <= flag < address + size:
            flags_written.append(engine.reg_read(UC_ARM_REG_PC))

    machine.hook_add(UC_HOOK_MEM_WRITE, watch, begin=0x20000000, end=0x2000FFFF)

    def reset():
        machine.mem_write(0x20000000, bytes(0x10000))
        machine.mem_write(0x20000000, initial)
        flags_written.clear()
        packets.clear()

    def run(address, values=(), stop=0x1001FFF0):
        machine.reg_write(UC_ARM_REG_SP, 0x2000F000)
        machine.reg_write(UC_ARM_REG_LR, 0x1001FFF1)
        for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), values):
            machine.reg_write(register, value)
        machine.emu_start(address | 1, stop, count=10000)
        if machine.reg_read(UC_ARM_REG_PC) != stop:
            raise RuntimeError("Original code did not reach its return/stop address")

    def word(address):
        return struct.unpack("<I", machine.mem_read(address, 4))[0]

    for levels in range(8):
        reset()
        # Initialized bank-1 base is 0x50000080; GPIO helper reads +0x50.
        assert word(0x20001ACC) == 0x50000080
        machine.mem_write(0x500000D0, struct.pack("<I", levels << 1))
        run(0x1000464C, stop=0x10004674)
        expected = levels & 1
        assert machine.mem_read(flag, 1)[0] == expected
        assert flags_written == [0x1000466E if expected else 0x10004672]
    print("PASS eight GPIO input combinations: original sampler/helper assigns flag from logical GPIO 0x21 (bank 1 bit 1)")

    count = 0
    for original_flag, setting, value in itertools.product(range(2), range(64), range(256)):
        reset()
        machine.mem_write(flag, bytes((original_flag,)))
        machine.mem_write(flag + 9, b"\0")
        run(0x10012B68, (setting, 0, 0, value))
        assert not flags_written and machine.mem_read(flag, 1)[0] == original_flag
        expected_lock = (value >> 2) & 1 if setting == 0 else 0
        assert machine.mem_read(flag + 9, 1)[0] == expected_lock
        count += 1
    print(f"PASS {count:,} settings-callback cases: IDs 0..63, values 0..255, both native-mode flags; none writes native-mode byte")

    reset()
    run(0x1001070C, (0,))
    legacy = 0x20001B6C
    assert word(legacy + 0x54) == 0x1000F099
    for mode in range(3):
        run(0x10010668, (mode,))
        assert word(legacy + 0x54) == 0x1000F099
    print("PASS original legacy initializers retain HP packet adapter 0x1000F099 in all three transport modes")

    # Capture adapter output; no real receiver, transport, storage or ROM runs.
    machine.mem_write(0x20001D8C + 0x18, struct.pack("<I", sink | 1))
    machine.mem_write(0x20009000, b"\x10\0\0\0ABCD")
    run(0x1000F098, (0, 8, 0x20009000))
    assert [packet[:2] for packet in packets] == [b"\xF5\x0C", b"\xF7\x0C"]
    packets.clear()
    run(0x1000F098, (8, 8, 0x20009000))
    assert [packet[:2] for packet in packets] == [b"\xF7\x0C"]
    assert not flags_written
    print("PASS legacy payload adapter emits HP 0xCF5 transfer-start / 0xCF7 data packets; no native-mode write")
    print("Limits: specific blocks/callbacks only, LED/transport stubs and simulated GPIO inputs; no exhaustive access proof, full transfer, ROM, HID or hardware execution")


if __name__ == "__main__":
    main()
