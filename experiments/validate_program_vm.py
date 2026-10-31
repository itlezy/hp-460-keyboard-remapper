"""Emulate stored HP key programs, capturing report callbacks instead of HID.

Only heap allocation/reallocation/free and outbound callbacks are substituted.
Uses the unmodified public image. No device is opened or programmed.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import ASH_1200_SHA256


def emulate_program(data: bytes, code: bytes, *, ticks: int = 4, incoming_mask: int = 0,
                    incoming_masks: list[int] | None = None, emission_ticks: list[int] | None = None,
                    physical_modifiers: int = 0, through_filter: bool = False, button_id: int = 3,
                    filter_masks: list[int] | None = None, through_simulate: bool = False,
                    record_host: int = 1, record_press_type: int = 0):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(0x10000000, 0x20000)
    uc.mem_map(0x20000000, 0x40000)
    uc.mem_write(0x10000000, data[13:])
    uc.mem_write(0x200027A5, bytes((physical_modifiers,)))
    context, descriptor, stack = 0x20002AEC, 0x20009000, 0x2003F000
    uc.mem_write(descriptor, bytes((button_id, record_host, record_press_type, len(code))) + code + bytes(16))
    heap = 0x20010000
    allocations = {}
    reports = []
    calls = []
    current_tick = -1

    def intercept(engine, address, size, user):
        nonlocal heap
        if address in (0x10000E44, 0x10000EF2):
            length = engine.reg_read(UC_ARM_REG_R0 if address == 0x10000E44 else UC_ARM_REG_R1)
            pointer = heap
            heap += (length + 7) & ~7
            if not 0 < length <= 4096 or heap >= 0x20030000:
                raise RuntimeError("Unexpected emulator allocation")
            engine.mem_write(pointer, bytes(length))
            if address == 0x10000EF2:
                old = engine.reg_read(UC_ARM_REG_R0)
                engine.mem_write(pointer, bytes(engine.mem_read(old, min(length, allocations[old]))))
            allocations[pointer] = length
            engine.reg_write(UC_ARM_REG_R0, pointer)
        elif address == 0x10000EA6:
            pass
        elif address in (0x1000AB2C, 0x1000AB04, 0x1000ABAC, 0x1000AAF8, 0x1000AA68):
            pointer = engine.reg_read(UC_ARM_REG_R1)
            calls.append(hex(address))
            if address in (0x1000ABAC, 0x1000AAF8):
                kind = "keyboard" if address == 0x1000ABAC else "consumer"
                reports.append((kind, bytes(engine.mem_read(pointer, 8 if kind == "keyboard" else 2))))
                if emission_ticks is not None:
                    emission_ticks.append(current_tick)
            elif address == 0x1000AA68:
                header = bytes(engine.mem_read(pointer, 4))
                packet_length = 4 + header[2] + ((header[3] & 3) << 8)
                reports.append(("notify", bytes(engine.mem_read(pointer, packet_length))))
                if emission_ticks is not None:
                    emission_ticks.append(current_tick)
            # The real transport callbacks return a delay of 20 ms.
            engine.reg_write(UC_ARM_REG_R0, 20)
        else:
            raise RuntimeError(f"Unexpected intercepted address {address:X}")
        engine.reg_write(UC_ARM_REG_PC, engine.reg_read(UC_ARM_REG_LR))

    for address in (0x10000E44, 0x10000EF2, 0x10000EA6, 0x1000AB2C, 0x1000AB04, 0x1000ABAC, 0x1000AAF8, 0x1000AA68):
        uc.hook_add(UC_HOOK_CODE, intercept, begin=address, end=address)

    def run(address, args, stack_args):
        uc.reg_write(UC_ARM_REG_SP, stack)
        uc.reg_write(UC_ARM_REG_LR, 0x1001FFF1)
        for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            uc.reg_write(register, value)
        uc.mem_write(stack, struct.pack(f"<{len(stack_args)}I", *stack_args))
        uc.emu_start(address | 1, 0x1001FFF0, count=200000)
        assert uc.reg_read(UC_ARM_REG_PC) == 0x1001FFF0
        return uc.reg_read(UC_ARM_REG_R0)

    if through_simulate:
        payload = bytes((2, 0, button_id, record_host, record_press_type, len(code))) + code
        packet = bytes((0, 0x0D, len(payload), 0)) + payload
        uc.mem_write(descriptor, packet + bytes(16))
        run(0x1000A738, (0, descriptor, len(packet), 0), (0,))
        assert int.from_bytes(uc.mem_read(context + 0xE4, 4), "little") == len(code) * 8
    elif through_filter:
        payload = bytes((0, 24, 1, 1, 0x18, button_id, 1, 0, len(code))) + code
        packet = bytes((1, 0x0D, len(payload), 0)) + payload
        uc.mem_write(0x20002C1F, packet + bytes(16))
        # Active profile is zero; device/model and Fn Lock remain their default
        # zero values, selecting the Fn-Lock-off F-row special-key path.
        run(0x100072F8, (0x100 + button_id, 0x20008000, 0x20008100, 0), (0,))
        mask = int.from_bytes(uc.mem_read(0x200027BC, 4), "little")
        assert mask == 1 << button_id, (button_id, mask)
        remaining = run(0x10014820, (mask, 0, 0, 0), (0,))
        assert remaining == 0, (button_id, remaining)
        assert int.from_bytes(uc.mem_read(context + 0xE4, 4), "little") == len(code) * 8
        assert uc.mem_read(0x200027A5, 1)[0] == physical_modifiers
        assert not reports and not calls
    else:
        run(0x100055FA, (context, 1, descriptor, 6), (0x1000AB2D, 0x1000AB05, 0x1000ABAD, 0x1000AAF9, 0x1000AA69))
    for current_tick, mask in enumerate(incoming_masks if incoming_masks is not None else [incoming_mask] * ticks):
        if filter_masks is not None and current_tick > 0:
            filter_masks.append(run(0x10014820, (mask, 0, 0, 0), (0,)))
        result = run(0x10005656, (context, mask, 0, 0), (0, 0))
        assert uc.mem_read(0x200027A5, 1)[0] == physical_modifiers
        if not result:
            if filter_masks is not None:
                filter_masks.append(run(0x10014820, (mask, 0, 0, 0), (0,)))
            break
    return reports, calls


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    data = args.image.read_bytes()
    if hashlib.sha256(data).hexdigest() != ASH_1200_SHA256:
        raise SystemExit("Requires exact stock Ash 1.2.0")
    for usage in (0x3D, 0x45, 0x68, 0x73):
        code = bytes((0xF8, 0, usage, 0))
        reports, calls = emulate_program(data, code)
        print(f"program={code.hex(' ')} reports={[(kind, value.hex(' ')) for kind, value in reports]} callbacks={calls}")
        assert reports == [("keyboard", bytes((0, 0, usage, 0, 0, 0, 0, 0))), ("keyboard", bytes(8))]
    print("PASS native F4/F12 and marker F13/F24 programs emit zero-modifier press then all-zero release")
    print("Limits: interpreter callbacks only; no physical modifier merge, Bluetooth or Windows execution")


if __name__ == "__main__":
    main()
