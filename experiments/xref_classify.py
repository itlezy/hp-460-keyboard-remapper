"""Classify firmware literal references to a RAM address as read or write.

Read-only offline analysis of a locally provided Ash_1200.FW image. Requires
Capstone. For each PC-relative LDR that loads the target literal, this prints
the following instructions so store targets can be classified. It was used to
prove that no command-driven writer exists for the F-row polarity byte.
"""

from __future__ import annotations

import sys
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm import ARM_INS_LDR, ARM_OP_MEM, ARM_REG_PC


FILE_MAP_BASE = 0x0FFFFFF3
TARGET = 0x20001BE0
LITERAL_VAS = [
    0x10002E1C, 0x10003290, 0x100033BC, 0x100035EC, 0x100039CC,
    0x100046A4, 0x100071C4, 0x10007274, 0x100072E8, 0x10007530,
    0x10007584, 0x1000F2D0, 0x1000F480, 0x1000FAEC, 0x1000FB3C,
    0x1000FBDC, 0x1000FBEC, 0x10014734,
]


def main() -> int:
    image = Path(sys.argv[1]).read_bytes()
    engine = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    engine.detail = True

    def code_at(va: int) -> bytes:
        offset = va - FILE_MAP_BASE
        return image[offset:offset + 0x120]

    for literal_va in LITERAL_VAS:
        print(f"\n== literal @ {literal_va:08X} = {TARGET:08X}")
        window_va = literal_va - 0x100
        window = code_at(window_va)
        found = False
        for insn in engine.disasm(window, window_va):
            if insn.id != ARM_INS_LDR:
                continue
            op = insn.operands[1]
            if op.type != ARM_OP_MEM or op.mem.base != ARM_REG_PC:
                continue
            target = (insn.address + 4) & ~3
            target += op.mem.disp
            if target == literal_va:
                reg = insn.reg_name(insn.operands[0].reg)
                print(f"  LDR  {insn.mnemonic} {reg}, [pc,#{op.mem.disp}] @ {insn.address:08X}")
                tail_va = insn.address + insn.size
                tail = image[tail_va - FILE_MAP_BASE:tail_va - FILE_MAP_BASE + 0x28]
                for next_insn in engine.disasm(tail, tail_va):
                    text = f"      {next_insn.address:08X} {next_insn.mnemonic:7s} {next_insn.op_str}"
                    if next_insn.mnemonic.startswith(("str", "ldr")):
                        text += "   <-- memory op"
                    print(text)
                found = True
                break
        if not found:
            print("  (no direct pc-relative LDR found in window)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
