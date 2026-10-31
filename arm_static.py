"""Read-only Thumb literal and address-reference inventory for Ash 1.2.0."""

from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

from firmware_analysis import FILE_MAP_BASE


def main() -> None:
    import capstone

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--low", type=lambda v: int(v, 0), required=True)
    parser.add_argument("--high", type=lambda v: int(v, 0))
    args = parser.parse_args()
    data = args.image.read_bytes()
    high = args.low if args.high is None else args.high
    hits = {}
    for offset in range(13, len(data) - 3, 2):
        value = struct.unpack_from("<I", data, offset)[0]
        if args.low <= value <= high:
            hits[FILE_MAP_BASE + offset] = value
            print(f"word 0x{FILE_MAP_BASE + offset:08X} -> 0x{value:08X}")
    engine = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
    # Decode at each halfword independently so embedded tables cannot desynchronize
    # the scan. Hits are candidates until their surrounding control flow is checked.
    for offset in range(13, len(data) - 3, 2):
        address = FILE_MAP_BASE + offset
        instruction = next(engine.disasm(data[offset:offset + 4], address, count=1), None)
        if instruction is None or instruction.mnemonic not in ("ldr", "ldr.w"):
            continue
        ref = re.search(r"\[pc, #?(0x[0-9a-f]+|[0-9]+)\]", instruction.op_str)
        if ref:
            literal = ((address + 4) & ~3) + int(ref[1], 0)
            if literal in hits:
                print(f"LDR 0x{address:08X} {instruction.mnemonic} {instruction.op_str} ; literal=0x{literal:08X} value=0x{hits[literal]:08X}")


if __name__ == "__main__":
    main()
