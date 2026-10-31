#!/usr/bin/env python3
"""Inspect or enable HP Accessory Center's hidden packet-log settings."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


PACKAGE = "AD2F1837.HPAccessoryCenter_v10z8vjag6ke6"
SETTINGS_RELATIVE = Path(
    "Packages",
    PACKAGE,
    "LocalCache",
    "Roaming",
    "HP Inc",
    "HP Accessory Center",
    "HPAC.settings",
)
DEV_KEYS = (
    "dev",
    "monitorHPACPackets",
    "monitorHPACPacketsKbdPrg",
)


def default_settings_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not defined.")
    return Path(local_app_data, SETTINGS_RELATIVE)


def split_json_trailer(data: bytes) -> tuple[bytes, bytes]:
    """Split the top-level JSON object from HPAC's opaque binary trailer."""
    start = 0
    while start < len(data) and data[start] in b" \t\r\n":
        start += 1
    if start >= len(data) or data[start] != ord("{"):
        raise ValueError("HPAC settings do not start with a JSON object.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(data)):
        value = data[index]
        if in_string:
            if escaped:
                escaped = False
            elif value == ord("\\"):
                escaped = True
            elif value == ord('"'):
                in_string = False
            continue
        if value == ord('"'):
            in_string = True
        elif value == ord("{"):
            depth += 1
        elif value == ord("}"):
            depth -= 1
            if depth == 0:
                end = index + 1
                return data[:end], data[end:]
            if depth < 0:
                break
    raise ValueError("Could not find the end of the HPAC JSON object.")


def read_settings(path: Path) -> tuple[dict[str, object], bytes]:
    json_bytes, trailer = split_json_trailer(path.read_bytes())
    settings = json.loads(json_bytes.decode("utf-8"))
    if not isinstance(settings, dict):
        raise ValueError("HPAC settings root is not an object.")
    return settings, trailer


def write_settings(
    path: Path, settings: dict[str, object], trailer: bytes
) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.backup-{stamp}")
    shutil.copy2(path, backup)

    encoded = json.dumps(settings, ensure_ascii=False, indent=4).encode("utf-8")
    handle, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encoded)
            stream.write(trailer)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return backup


def print_status(path: Path, settings: dict[str, object], trailer: bytes) -> None:
    print(f"settings={path}")
    for key in DEV_KEYS:
        print(f"{key}={settings.get(key)!r}")
    print(f"binary_trailer_bytes={len(trailer)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or toggle HPAC's hidden packet-log settings."
    )
    parser.add_argument("action", choices=("status", "enable", "disable"))
    parser.add_argument("--settings", type=Path, help="override HPAC.settings path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = args.settings or default_settings_path()
    try:
        settings, trailer = read_settings(path)
        print_status(path, settings, trailer)
        if args.action == "status":
            return 0
        enabled = args.action == "enable"
        for key in DEV_KEYS:
            settings[key] = enabled
        backup = write_settings(path, settings, trailer)
        print(f"updated={args.action}")
        print(f"backup={backup}")
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
