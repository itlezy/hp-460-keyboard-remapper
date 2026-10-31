"""REJECTED prototype: Fn Lock off + remap each F-key to itself.

This reproduces HP Accessory Center's "Function Lock off + remap each F-key
to itself" recipe without HPAC, but it does NOT meet the goal and is kept
only as a documented dead end. The stored programs emit a synthetic
zero-modifier F-key, so Shift+F4 (and other modifier combinations) still
require Fn. It turns Fn Lock off (so Home/End/Page Up/Page Down stay native)
and stores a 4-byte keyboard program for F1-F12 that emits the matching F-key.

Reversible: run again with --undo, or use HPAC. No firmware bytes are
modified; this only changes stored button programs and the Fn Lock state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hp460
from experiments.button_transport import query_programs


F_KEYS = tuple(range(0x3A, 0x46))  # HID usages F1..F12


def reports(*, fn_lock_on: bool) -> list[bytes]:
    fn_lock = hp460.build_fn_lock_report(current=fn_lock_on, startup=fn_lock_on)
    remaps = [hp460.build_button_set_report(button_id=index, usage=usage, host=0)
              for index, usage in enumerate(F_KEYS)]
    return [fn_lock] + remaps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--undo", action="store_true",
                        help="restore Fn Lock on and clear the 12 stored F-key programs")
    parser.add_argument("--backup", type=Path,
                        help="exclusive-create private backup of the current programs")
    args = parser.parse_args()

    fn_lock_on = args.undo
    if not args.undo and args.backup:
        if args.backup.exists():
            parser.error("Backup already exists; refusing to overwrite")

    api, devices, selected = hp460.open_selected_device(0)
    try:
        before = query_programs()
        if not args.undo and args.backup:
            with args.backup.open("x", encoding="utf-8") as stream:
                json.dump(before, stream, indent=2)
                stream.write("\n")

        if args.undo:
            writes = [hp460.build_fn_lock_report(current=True, startup=True)]
            writes += [hp460.build_button_clear_report(button_id=index, host=0)
                       for index in range(len(F_KEYS))]
        else:
            writes = reports(fn_lock_on=False)

        for report in writes:
            api.write(selected, report)
    finally:
        for device in devices:
            api.close(device)

    after = query_programs()
    print(json.dumps({
        "mode": "undo" if args.undo else "apply",
        "fn_lock": "on" if fn_lock_on else "off",
        "programs_before": len(before["records"]),
        "programs_after": len(after["records"]),
        "stored_buttons": [record["button_id"] for record in after["records"]],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
