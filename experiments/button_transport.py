"""Read current stored button programs over the known vendor HID interface.

Only the command-0 query is sent. This module does not expose a write/apply
command. Optional backups may contain personal macros: keep them outside Git.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def frame_button_payload(payload: bytes) -> list[bytes]:
    """Prepare command packets offline; this function never opens a device."""
    if not 1 <= len(payload) <= 1023:
        raise ValueError("Button payload must have 1..1023 bytes")
    frames = []
    for sequence, offset in enumerate(range(0, len(payload), 16)):
        chunk = payload[offset:offset + 16]
        padding = (b"\x02" + bytes(15 - len(chunk))) if len(chunk) < 16 else b""
        frames.append(bytes((6, 0, 0x0D, len(payload) & 0xFF, (sequence << 2) | (len(payload) >> 8))) + chunk + padding)
    return frames


class ButtonReply:
    def __init__(self):
        self.length = None
        self.next_sequence = 0
        self.payload = bytearray()

    def add(self, frame: bytes) -> bytes | None:
        if len(frame) != 21:
            raise ValueError("Expected a 21-byte vendor report")
        if frame[:3] != b"\x06\x01\x0D":
            return None
        length = frame[3] | ((frame[4] & 3) << 8)
        sequence = frame[4] >> 2
        if not length or sequence != self.next_sequence:
            raise ValueError("Invalid or out-of-order button reply")
        if self.length is None:
            self.length = length
        if length != self.length:
            raise ValueError("Reply length changed between fragments")
        self.payload.extend(frame[5:5 + min(16, length - len(self.payload))])
        self.next_sequence += 1
        return bytes(self.payload) if len(self.payload) == length else None


def decode_button_reply(payload: bytes) -> dict:
    if len(payload) < 5 or payload[0] != 0:
        raise ValueError("Not a command-0 button reply")
    command, capacity, count, host, flags = payload[:5]
    records = []
    offset = 5
    for _ in range(count):
        if offset + 4 > len(payload):
            raise ValueError("Truncated button descriptor")
        button, record_host, press_type, length = payload[offset:offset + 4]
        offset += 4
        if length & 0x80:
            if offset >= len(payload):
                raise ValueError("Truncated extended program length")
            length = (length & 0x7F) | (payload[offset] << 7)
            offset += 1
        if offset + length > len(payload):
            raise ValueError("Truncated program")
        code = payload[offset:offset + length]
        records.append({"button_id": button, "host": record_host, "press_type": press_type,
                        "length": length, "program_hex": code.hex(), "sha256": hashlib.sha256(code).hexdigest()})
        offset += length
    if offset != len(payload):
        raise ValueError("Unexplained trailing button reply bytes")
    return {"capacity": capacity, "host": host, "flags": flags, "records": records,
            "raw_reply_hex": payload.hex()}


def query_programs(timeout: float = 3) -> dict:
    import hp460
    from ctypes import wintypes

    api, devices, selected = hp460.open_selected_device(0)
    read_handle = event = None
    pending = False
    overlapped = None
    try:
        if len(devices) != 1:
            raise RuntimeError("Read-only experiment requires exactly one connected HP 460")
        read_handle = api.kernel32.CreateFileW(selected.path, hp460.GENERIC_READ,
            hp460.FILE_SHARE_READ | hp460.FILE_SHARE_WRITE, None, hp460.OPEN_EXISTING,
            hp460.FILE_FLAG_OVERLAPPED, None)
        if ctypes.c_void_p(read_handle).value == hp460.INVALID_HANDLE_VALUE:
            read_handle = None
            raise ctypes.WinError(ctypes.get_last_error())
        event = api.kernel32.CreateEventW(None, True, False, None)
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())
        overlapped = hp460.Overlapped(event=event)
        buffer = ctypes.create_string_buffer(21)
        transferred = wintypes.DWORD()
        response = ButtonReply()
        sent = False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not pending:
                if not api.kernel32.ResetEvent(event):
                    raise ctypes.WinError(ctypes.get_last_error())
                transferred.value = 0
                immediate = api.kernel32.ReadFile(read_handle, buffer, 21, ctypes.byref(transferred), ctypes.byref(overlapped))
                if not immediate:
                    if ctypes.get_last_error() != hp460.ERROR_IO_PENDING:
                        raise ctypes.WinError(ctypes.get_last_error())
                    pending = True
                if not sent:
                    # 7-byte decoded packet = 4-byte framing + 3-byte query.
                    api.write(selected, frame_button_payload(bytes((0, 0, 0)))[0])
                    sent = True
            else:
                status = api.kernel32.WaitForSingleObject(event, 100)
                if status == hp460.WAIT_TIMEOUT:
                    continue
                if status != hp460.WAIT_OBJECT_0:
                    raise ctypes.WinError(ctypes.get_last_error())
                if not api.kernel32.GetOverlappedResult(read_handle, ctypes.byref(overlapped), ctypes.byref(transferred), False):
                    raise ctypes.WinError(ctypes.get_last_error())
                pending = False
            if pending:
                continue
            payload = response.add(bytes(buffer[:transferred.value]))
            if payload is not None:
                return decode_button_reply(payload)
        raise RuntimeError("Timed out waiting for complete command-0 reply; no settings changed")
    finally:
        if pending and read_handle:
            api.kernel32.CancelIoEx(read_handle, ctypes.byref(overlapped))
            api.kernel32.WaitForSingleObject(event, 1000)
        if event:
            api.kernel32.CloseHandle(event)
        if read_handle:
            api.kernel32.CloseHandle(read_handle)
        for device in devices:
            api.close(device)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="exclusive-create private backup; may contain personal key programs")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Backup already exists; refusing to overwrite")
    try:
        result = query_programs()
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    public = {**result, "records": [{k: v for k, v in record.items() if k != "program_hex"} for record in result["records"]]}
    del public["raw_reply_hex"]
    print(json.dumps(public, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
