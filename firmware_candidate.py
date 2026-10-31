"""Build an offline native-key Ash 1.2.0 candidate; never opens hardware."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from firmware_analysis import (
    ASH_1200_SHA256,
    KEY_MATRIX_COLUMNS,
    KEY_MATRIX_VA,
    VIRTUAL_KEY_NAMES,
    parse_key_matrix,
    va_to_file_offset,
    virtual_key_positions,
)


def build_candidate(data: bytes) -> tuple[bytes, dict]:
    if hashlib.sha256(data).hexdigest() != ASH_1200_SHA256:
        raise ValueError("Requires the exact unmodified public Ash_1200.FW SHA-256")
    usages = list(range(0x3A, 0x46)) + [0x46, 0x49, 0x4C, 0x4A, 0x4D, 0x4B, 0x4E]
    candidate = bytearray(data)
    changes = []
    permitted_bytes = set()
    for action, row, column in virtual_key_positions(parse_key_matrix(data)):
        offset = va_to_file_offset(KEY_MATRIX_VA) + 2 * (row * KEY_MATRIX_COLUMNS + column)
        original = struct.unpack_from("<H", data, offset)[0]
        struct.pack_into("<H", candidate, offset, usages[action])
        permitted_bytes.update((offset, offset + 1))
        changes.append({"key": VIRTUAL_KEY_NAMES[action], "file_offset": f"0x{offset:X}", "row": row, "column": column, "before": f"0x{original:04X}", "after": f"0x{usages[action]:04X}"})
    actual_differences = {i for i, (a, b) in enumerate(zip(data, candidate)) if a != b}
    if len(changes) != 19 or actual_differences != permitted_bytes:
        raise ValueError("Unexpected patch footprint")
    manifest = {
        "status": "OFFLINE CANDIDATE; not tested on hardware",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "length": len(candidate),
        "changed_bytes": len(actual_differences),
        "other_bytes_unchanged": True,
        "outer_signature_valid_for_modified_payload": False,
        "inner_signature_bytes_preserved": True,
        "inner_signature_valid_for_modified_application": False,
        "physical_device_backup": False,
        "changes": changes,
    }
    return bytes(candidate), manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, help="write a separate candidate and .json manifest; fails if either exists")
    args = parser.parse_args()
    try:
        candidate, manifest = build_candidate(args.image.read_bytes())
        serialized = json.dumps(manifest, indent=2) + "\n"
        if args.output:
            manifest_path = args.output.with_name(args.output.name + ".json")
            if args.output.exists() or manifest_path.exists():
                raise ValueError("Output or manifest already exists; refusing to overwrite")
            # Exclusive creation also protects against races after the check.
            with args.output.open("xb") as stream:
                stream.write(candidate)
            with manifest_path.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        print(serialized, end="")
        return 0
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
