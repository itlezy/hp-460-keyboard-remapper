"""Execute HPAC's section checker with its local-FW2 validation flag disabled.

Tests the isolated x64 checker only; no Qt UI, updater or HID access.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


def main() -> None:
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_RSP, UC_X86_REG_RIP, UC_X86_REG_RAX

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hpac", type=Path)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    hpac = args.hpac.read_bytes()
    firmware = args.image.read_bytes()
    if hashlib.sha256(hpac).hexdigest() != "9a9bbf2d871463ac411f059836e2e551a3031ceb47a212adbac8ee6a13b8e488":
        raise SystemExit("Requires analyzed HPAC executable")
    if hashlib.sha256(firmware).hexdigest() != "6e490ae055b9dfc9aa9e750f8693bd563a24ec2f060a84f12d250996a0e77c2e":
        raise SystemExit("Requires unmodified Ash 1.2.0")
    pe = pefile.PE(data=hpac, fast_load=True)
    mapped = pe.get_memory_mapped_image()
    record_length = struct.unpack_from("<I", firmware)[0]
    payload_length = struct.unpack_from("<I", firmware, 5)[0]
    modified = bytearray(firmware)
    modified[0x742D:0x7431] = bytes.fromhex("2D D0 2C E0")
    for name, data in (("stock", firmware), ("modified", modified)):
        engine = Uc(UC_ARCH_X86, UC_MODE_64)
        engine.mem_map(0x140000000, (len(mapped) + 4095) & ~4095)
        engine.mem_write(0x140000000, mapped)
        engine.mem_map(0x200000000, 0x20000)
        engine.mem_write(0x200000000, bytes(data[5:record_length]))
        engine.mem_map(0x210000000, 0x10000)
        engine.mem_map(0x150000000, 0x1000)
        stack = 0x21000F008
        engine.mem_write(stack, struct.pack("<Q", 0x150000000))
        for register, value in ((UC_X86_REG_RCX, 0x200000000), (UC_X86_REG_RDX, record_length - 5), (UC_X86_REG_R8, 0x140623AD0), (UC_X86_REG_R9, 0), (UC_X86_REG_RSP, stack)):
            engine.reg_write(register, value)

        def instruction(uc, address, size, _):
            if address == 0x150000000:
                uc.emu_stop()
            elif address not in range(0x1400E1D00, 0x1400E1F00):
                raise RuntimeError(f"Unexpected call 0x{address:X}")

        engine.hook_add(UC_HOOK_CODE, instruction)
        engine.emu_start(0x1400E1D00, 0x150000000, count=10000)
        assert engine.reg_read(UC_X86_REG_RIP) == 0x150000000
        result = engine.reg_read(UC_X86_REG_RAX)
        assert result == payload_length, (name, result, payload_length)
        print(f"PASS {name}: verification=false returns payload length 0x{result:X} without RSA/SHA calls")
    print("Scope: isolated host checker only; device acceptance and full Qt loader not tested")


if __name__ == "__main__":
    main()
