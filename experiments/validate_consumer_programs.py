"""Check consumer-only tap/hold candidates using original ARM VM instructions."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware_analysis import ASH_1200_SHA256
from experiments.consumer_programs import TARGETS, consumer_tap, consumer_held
from experiments.validate_program_vm import emulate_program


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    data = args.image.read_bytes()
    if hashlib.sha256(data).hexdigest() != ASH_1200_SHA256:
        raise SystemExit("Requires exact stock Ash 1.2.0")
    runs = 0
    for button_id, usage, name in TARGETS:
        bit = 1 << button_id
        for modifiers in range(256):
            for other_bits in (0, 0xFFFFFF ^ bit):
                masks = [bit | other_bits, bit | other_bits, other_bits, other_bits, other_bits]
                for kind, code in (("tap", consumer_tap(usage)), ("held", consumer_held(button_id, usage))):
                    times = []
                    reports, calls = emulate_program(data, code, incoming_masks=masks, emission_ticks=times,
                                                     physical_modifiers=modifiers, through_filter=True, button_id=button_id)
                    assert reports == [("consumer", usage.to_bytes(2, "little")), ("consumer", bytes(2))], (name, kind, reports)
                    assert calls == ["0x1000aaf8", "0x1000aaf8"], calls
                    assert times == ([0, 1] if kind == "tap" else [0, 2]), (name, kind, times)
                    runs += 1
        print(f"PASS {name}: tap and held reports; all modifier bytes and unrelated input bits")
    print(f"PASS {runs} original-ARM transformer/filter/VM runs; no keyboard-report callback or physical report modifier changes")
    print("Not a live Shift-shortcut result: Bluetooth, HID parser, Windows, repeat, disconnect and overlapping macros still need testing.")


if __name__ == "__main__":
    main()
