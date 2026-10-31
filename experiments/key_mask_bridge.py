"""Decode/replay the experimental key-mask stream; no hardware or SendInput.

This is the host-side state machine for a future live companion, not an
installed remapper. Input files are JSON arrays of notification payload hex.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def decode_mask(payload: bytes) -> int:
    if len(payload) != 6 or payload[0] != 2 or payload[2:4] != b"\x03\xA5":
        raise ValueError("Not a key-mask notification")
    return int.from_bytes(payload[4:6], "little") & 0xFFF


class MaskTracker:
    def __init__(self):
        self.held = 0

    def update(self, mask: int) -> list[tuple[str, bool]]:
        if not 0 <= mask <= 0xFFF:
            raise ValueError("Expected a twelve-bit F-row mask")
        releases = self.held & ~mask
        presses = mask & ~self.held
        result = [(f"F{bit + 1}", False) for bit in range(12) if releases & (1 << bit)]
        result += [(f"F{bit + 1}", True) for bit in range(12) if presses & (1 << bit)]
        self.held = mask
        return result

    def release(self):
        return self.update(0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payloads", type=Path)
    args = parser.parse_args()
    tracker = MaskTracker()
    for entry in json.loads(args.payloads.read_text(encoding="utf-8")):
        for key, down in tracker.update(decode_mask(bytes.fromhex(entry))):
            print(f"{key} {'DOWN' if down else 'UP'}")
    for key, down in tracker.release():
        print(f"{key} UP (cleanup)")


if __name__ == "__main__":
    main()
