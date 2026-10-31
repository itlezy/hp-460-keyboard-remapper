"""Offline prototype: run a VM program that consumes F-row bits and reports them.

Requires an active companion on the PC. No live simulate command is exposed.
Stopping/recovery and timing must be established before hardware execution.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.consumer_programs import Bits


def build_key_mask_program(notifications: int = 16) -> bytes:
    if not 1 <= notifications <= 127:
        raise ValueError("A bounded prototype must emit 1..127 notifications")
    stream = Bits()
    stream.put(22, 5)
    # Hardware subcommand 7 replaces the active macro's consumed-key mask.
    # Its bit 7 is programmable-button bit 0, hence 0xFFF << 7.
    stream.blob((("word", 0x8007), ("word", 0x07FF), ("byte", 0)))
    stream.arithmetic(1, 15, notifications)
    loop = len(stream.bits)
    stream.arithmetic(4, 5, 0)
    stream.arithmetic(1, 5, variable=0)
    stream.arithmetic(5, 5, 64)
    stream.arithmetic(5, 5, 4)
    stream.put(25, 5)
    stream.blob((("byte", 0xA5), ("variable", 0), ("variable", 5)))
    # The notification callback already yields. Do not add a second delay.
    stream.put(20, 5)  # decrement variable[15]; jump while nonzero
    stream.put(15, 4)
    jump = len(stream.bits)
    stream.put(0, 10)
    stream.patch_jump(jump, loop)
    stream.put(0, 5)
    return stream.finish()


if __name__ == "__main__":
    code = build_key_mask_program()
    print("OFFLINE ONLY; stop/recovery and physical timing not yet established")
    print(f"length={len(code)} bytes: {code.hex(' ')}")
