"""Replay Ash's startup key installation and inner RSA decoder offline.

Runs original ARM instructions, including modular exponentiation. Only heap
allocation/free are substituted. No HID, ROM, bootloader or flash execution.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import ASH_1200_SHA256, decompress_runtime_data
from firmware_candidate import build_candidate


def main() -> None:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    data = args.image.read_bytes()
    if hashlib.sha256(data).hexdigest() != ASH_1200_SHA256:
        raise SystemExit("Requires the exact stock Ash 1.2.0")
    candidate, _ = build_candidate(data)
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(0x10000000, 0x20000)
    uc.mem_map(0x20000000, 0x40000)
    uc.mem_write(0x10000000, data[13:])
    runtime, _ = decompress_runtime_data(data)
    uc.mem_write(0x20001564, runtime)
    heap = 0x20010000

    def allocate(engine, address, size, user):
        nonlocal heap
        length = engine.reg_read(UC_ARM_REG_R0)
        allocation = heap
        heap += (length + 7) & ~7
        if heap >= 0x20030000:
            raise RuntimeError("Emulator heap exhausted")
        engine.mem_write(allocation, bytes(length))
        engine.reg_write(UC_ARM_REG_R0, allocation)
        engine.reg_write(UC_ARM_REG_PC, engine.reg_read(UC_ARM_REG_LR))

    def release(engine, address, size, user):
        engine.reg_write(UC_ARM_REG_PC, engine.reg_read(UC_ARM_REG_LR))

    uc.hook_add(UC_HOOK_CODE, allocate, begin=0x10000E44, end=0x10000E44)
    uc.hook_add(UC_HOOK_CODE, release, begin=0x10000EA6, end=0x10000EA6)

    def run(start, stop=0x1001FFF0, **registers):
        for register, value in ((UC_ARM_REG_SP, 0x2003F000), (UC_ARM_REG_LR, 0x1001FFF1)):
            uc.reg_write(register, value)
        for name, value in registers.items():
            uc.reg_write({"r0": UC_ARM_REG_R0, "r1": UC_ARM_REG_R1, "r2": UC_ARM_REG_R2, "r4": UC_ARM_REG_R4, "r5": UC_ARM_REG_R5, "r6": UC_ARM_REG_R6}[name], value)
        uc.emu_start(start | 1, stop, count=100_000_000)
        assert uc.reg_read(UC_ARM_REG_PC) == stop, f"Did not return: {uc.reg_read(UC_ARM_REG_PC):08X}"

    # The actual caller supplies this non-null configuration base at 0x1000F1EE.
    run(0x1000FAAC, r0=0x20001DEC)
    assert struct.unpack("<I", uc.mem_read(0x20001FBC, 4))[0] == 0x20001EF8
    run(0x1000F8A6, stop=0x1000F8C4, r6=0x20001F70)
    key = struct.unpack("<I", uc.mem_read(0x200038EC, 4))[0]
    assert key == 0x20001EF8
    bits, block_size, modulus_pointer, exponent_pointer = struct.unpack("<4I", uc.mem_read(key, 16))

    def bignum(pointer):
        limbs = struct.unpack("<I", uc.mem_read(pointer, 4))[0]
        return int.from_bytes(uc.mem_read(pointer + 4, limbs * 4), "little")

    modulus, exponent = bignum(modulus_pointer), bignum(exponent_pointer)
    assert bits == 2048 and block_size == 256 and exponent == 37
    print(f"PASS startup installs key 0x{key:08X} into OTA context +0x54; RSA-{bits}, exponent {exponent}")
    image_length = struct.unpack_from("<I", data, 9)[0]
    signed_container = data[13 + image_length:13 + image_length + 260]
    assert struct.unpack_from("<I", signed_container)[0] == 260
    uc.mem_write(0x20006000, signed_container)
    uc.mem_write(0x20007000, struct.pack("<I", 260))
    run(0x10009EA4, r0=0x20006000, r1=0x20007000, r2=key)
    padding = uc.reg_read(UC_ARM_REG_R0)
    length = struct.unpack("<I", uc.mem_read(0x20007000, 4))[0]
    message = bytes(uc.mem_read(0x20006000, length))
    assert padding == 2 and length == 32
    recovered = pow(int.from_bytes(signed_container[4:], "big"), exponent, modulus).to_bytes(256, "big")
    assert recovered[0:2] == b"\x00\x02" and recovered[-32:] == message
    stock_digest = hashlib.sha256(data[13:13 + image_length]).digest()
    candidate_digest = hashlib.sha256(candidate[13:13 + image_length]).digest()
    assert message == stock_digest and message != candidate_digest
    print("PASS original ARM RSA/padding decoder recovers the exact stock application SHA-256")
    print("PASS independent Python RSA agrees; native matrix candidate digest disagrees with the unchanged inner signature")
    # Run the receiver's real type-2 comparison, stopping before callbacks.
    context = 0x20003898
    uc.mem_write(context + 0xC0, message)
    for name, digest, destination in (("stock", stock_digest, 0x10006860), ("matrix", candidate_digest, 0x10006816)):
        uc.mem_write(context + 0xA0, digest)
        uc.mem_write(0x2003F008, struct.pack("<I", context + 0xA0))
        uc.mem_write(0x2003F00C, struct.pack("<I", 32))
        run(0x1000682A, stop=destination, r4=context, r5=context + 0xC0)
        print(f"PASS original receiver digest comparison: {name} -> 0x{destination:08X} ({'success' if name == 'stock' else 'reject'})")
    print("Limits: isolated startup and RSA functions; no full boot, receiver transfer, ROM, bootloader or hardware emulation.")


if __name__ == "__main__":
    main()
