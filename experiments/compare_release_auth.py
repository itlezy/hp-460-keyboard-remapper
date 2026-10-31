"""Compare device-key installation in the three public Ash releases offline.

Executes original startup/key-setter instructions and checks each inner
signature independently with Python RSA. No HID, flash or downgrade operation.
Optional Unicorn is required; images are not distributed with this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import decompress_runtime_data


# SHA, compressed source, RAM destination, output size, startup caller/stop,
# OTA key-copy block/stop, enclosing state base and OTA context.
RELEASES = {
    "514b88bb2dac7ff54d818ee593732e3f07a6a48a3cb8485de8628b90d8c590a6":
        ("1.0", 0x10016030, 0, 0xBE4, 0x1001097E, 0x10010984,
         0x10011430, 0x10011456, 0x200009DC, 0x20002304),
    "b749a0bb1fba465ca96e31e865d0b0d424183461ecfa2345cb9ecd389c265a75":
        ("1.1", 0x10016054, 0, 0xBE4, 0x1001099C, 0x100109A2,
         0x10011454, 0x1001147A, 0x200009DC, 0x20002304),
    "6e490ae055b9dfc9aa9e750f8693bd563a24ec2f060a84f12d250996a0e77c2e":
        ("1.2", 0x10015990, 0x1564, 0xC3C, 0x1000F1EE, 0x1000F1F4,
         0x1000F8A6, 0x1000F8C4, 0x20001F70, 0x20003898),
}


def inspect(data: bytes) -> dict:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
    from unicorn.arm_const import UC_ARM_REG_R6, UC_ARM_REG_SP, UC_ARM_REG_PC

    sha = hashlib.sha256(data).hexdigest()
    if sha not in RELEASES:
        raise ValueError("Requires an exact known public Ash image")
    version, source, destination, size, caller, caller_stop, copy, copy_stop, state, context = RELEASES[sha]
    runtime, _ = decompress_runtime_data(data, source_va=source, output_size=size)
    machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    machine.mem_map(0x10000000, 0x20000)
    machine.mem_map(0x20000000, 0x40000)
    machine.mem_write(0x10000000, data[13:])
    machine.mem_write(0x20000000 + destination, runtime)
    machine.reg_write(UC_ARM_REG_SP, 0x2003F000)

    def run(start, stop):
        machine.emu_start(start | 1, stop, count=10000)
        if machine.reg_read(UC_ARM_REG_PC) != stop:
            raise RuntimeError("Original startup block did not reach its stop address")

    def word(address):
        return struct.unpack("<I", machine.mem_read(address, 4))[0]

    run(caller, caller_stop)  # actual literal load and call, not a supplied key
    installed = word(state + 0x4C)
    if not 0x20000000 <= installed < 0x20040000:
        raise ValueError("Startup did not install a RAM key descriptor")
    machine.reg_write(UC_ARM_REG_R6, state if version == "1.2" else 0)
    run(copy, copy_stop)
    if word(context + 0x54) != installed:
        raise ValueError("Original OTA initializer did not copy the installed key")
    bits, block_size, modulus_pointer, exponent_pointer = struct.unpack("<4I", machine.mem_read(installed, 16))

    def bignum(pointer):
        limbs = word(pointer)
        if not 1 <= limbs <= 64:
            raise ValueError("Invalid key bignum length")
        return int.from_bytes(machine.mem_read(pointer + 4, limbs * 4), "little")

    modulus, exponent = bignum(modulus_pointer), bignum(exponent_pointer)
    if (bits, block_size, exponent, modulus.bit_length()) != (2048, 256, 37, 2048):
        raise ValueError("Unexpected device RSA key parameters")
    length = struct.unpack_from("<I", data, 9)[0]
    trailer = data[13 + length:13 + length + 260]
    if len(trailer) != 260 or struct.unpack_from("<I", trailer)[0] != 260:
        raise ValueError("Invalid inner signature container")
    recovered = pow(int.from_bytes(trailer[4:], "big"), exponent, modulus).to_bytes(256, "big")
    separator = recovered.find(b"\0", 2)
    application = data[13:13 + length]
    digest = hashlib.sha256(application).digest()
    if recovered[:2] != b"\0\x02" or separator < 10 or recovered[separator + 1:] != digest:
        raise ValueError("Inner RSA block does not recover the application digest")
    edited = bytearray(application)
    edited[-1] ^= 1
    if hashlib.sha256(edited).digest() == digest:
        raise ValueError("Unexpected digest collision")
    return {"version": version, "sha256": sha, "key_descriptor": f"0x{installed:08X}",
            "ota_context": f"0x{context:08X}", "exponent": exponent}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.images:
        result = inspect(path.read_bytes())
        print(f"PASS Ash {result['version']}: original startup installs {result['key_descriptor']} "
              f"into OTA {result['ota_context']}+0x54; RSA-2048/e=37 recovers the stock digest; "
              "one-byte edit changes that digest")
    print("Limits: startup blocks and independent RSA only; no full receiver, boot ROM, anti-rollback or device execution")


if __name__ == "__main__":
    main()
