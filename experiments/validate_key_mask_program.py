"""Replay bounded key-mask simulator programs and the active F-row filter."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import ASH_1200_SHA256
from experiments.key_mask_program import build_key_mask_program
from experiments.key_mask_bridge import decode_mask
from experiments.validate_program_vm import emulate_program


def check(data, masks, modifiers):
    times, filtered = [], []
    program = build_key_mask_program(len(masks))
    reports, calls = emulate_program(data, program, incoming_masks=masks + [0xFFF, 0xFFF],
        physical_modifiers=modifiers, emission_ticks=times, filter_masks=filtered, through_simulate=True)
    assert len(reports) == len(masks), (len(reports), len(masks))
    assert times == list(range(len(masks)))
    assert all(kind == "notify" for kind, value in reports)
    assert calls == ["0x1000aa68"] * len(masks)
    assert [decode_mask(value[4:]) for kind, value in reports] == [mask & 0xFFF for mask in masks]
    assert filtered[:len(masks)] == [mask & ~0xFFF for mask in masks[1:]] + [0]
    # On the next tick after the bounded program ends, F-row suppression ends.
    assert filtered[-1] == 0xFFF, filtered[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    data = args.image.read_bytes()
    if hashlib.sha256(data).hexdigest() != ASH_1200_SHA256:
        raise SystemExit("Requires exact stock Ash 1.2.0")
    for offset in range(0, 4096, 64):
        check(data, list(range(offset, offset + 64)), 0)
    print("PASS: all 4096 F-row masks reported through actual simulate handler and original VM")
    for modifiers in range(256):
        check(data, [0, 1, 0x41, 0x840, 0xFFF, 0, 0x1000, 0x800FFF], modifiers)
    print("PASS: all 256 modifier bytes unchanged; only selected F-row bits suppressed; bounded execution ends")
    print("Limits: sample-by-sample emulation; no physical edge timing, BLE queue, live cancellation, Windows injection or hardware execution")


if __name__ == "__main__":
    main()
