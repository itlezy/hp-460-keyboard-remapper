"""Fixed temporary VM notification test; no keyboard/media report or saved remap.

Defaults to an offline packet preview. --run sends one bounded simulator program
to one Ash 1.2 keyboard after a read-only program backup. Not a native-mode fix.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.button_transport import frame_button_payload, query_programs
from experiments.consumer_programs import Bits

MARKER = b"HP46"


def marker_payload(prefix_fetch: bool = False) -> bytes:
    if prefix_fetch:
        # Fetches at negative non-byte-aligned positions use division truncated
        # toward zero, so these descriptor bytes encode notify(A5), end under
        # the original reader's behavior. A 64-byte declared length makes the
        # final prefix fetch decode opcode zero. Only two program bytes run.
        bits = Bits()
        bits.put(26, 5)
        displacement = len(bits.bits)
        bits.put(0, 10)
        bits.patch_jump(displacement, -32)
        code = bits.finish().ljust(64, b"\0")
        return bytes((2, 0, 0x19, 0xD2, 0x52, len(code))) + code
    bits = Bits()
    bits.put(25, 5)  # one vendor notification
    bits.blob([("byte", value) for value in MARKER])
    bits.put(0, 5)   # terminate, no loop or keyboard/consumer callback
    code = bits.finish()
    return bytes((2, 0, 3, 1, 0, len(code))) + code


def expected_notification(prefix_fetch: bool = False) -> bytes:
    payload = b"\x02\0\x19\xA5" if prefix_fetch else b"\x02\0\x03" + MARKER
    return b"\x01\x0D" + bytes((len(payload), 0)) + payload


def run_marker(prefix_fetch: bool = False) -> dict:
    import hp460
    from ctypes import wintypes

    before = query_programs()
    if before["records"]:
        raise RuntimeError("Fixed experiment requires an empty stored-program table")
    api, devices, selected = hp460.open_selected_device(0)
    readers = []
    result = {"status": "marker_not_observed", "program_sent": False, "matching_marker": False,
              "test": "prefix_fetch" if prefix_fetch else "in_bounds_marker"}
    try:
        if len(devices) != 1 or selected.version != 0x04B0:
            raise RuntimeError("Requires exactly one connected Ash 1.2 (0x04B0) keyboard")
        collections, _ = api.matching_collections()
        candidates = [item for item in collections if item.input_length == 21 and
                      (item.usage_page, item.usage) in ((0xFF00, 1), (0xFF05, 1))]
        if len(candidates) != 2:
            raise RuntimeError("Requires the FF00 and FF05 vendor input collections")
        for item in candidates:
            handle = api.kernel32.CreateFileW(item.path, hp460.GENERIC_READ,
                hp460.FILE_SHARE_READ | hp460.FILE_SHARE_WRITE, None, hp460.OPEN_EXISTING,
                hp460.FILE_FLAG_OVERLAPPED, None)
            if ctypes.c_void_p(handle).value == hp460.INVALID_HANDLE_VALUE:
                raise ctypes.WinError(ctypes.get_last_error())
            event = api.kernel32.CreateEventW(None, True, False, None)
            if not event:
                api.kernel32.CloseHandle(handle)
                raise ctypes.WinError(ctypes.get_last_error())
            readers.append({"handle": handle, "event": event, "overlap": hp460.Overlapped(event=event),
                "buffer": ctypes.create_string_buffer(21), "transferred": wintypes.DWORD(),
                "pending": False, "page": item.usage_page})

        def consume(reader):
            frame = bytes(reader["buffer"][:reader["transferred"].value])
            # Only retain the fixed notification, never arbitrary vendor data.
            expected = expected_notification(prefix_fetch)
            if len(frame) == 21 and frame[1:1 + len(expected)] == expected:
                result.update(status="success", matching_marker=True,
                              reply_hex=frame[:1 + len(expected)].hex(" "), padding_omitted=True,
                              reply_usage_page=f"{reader['page']:04X}")

        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and not result["matching_marker"]:
            for reader in readers:
                if not reader["pending"]:
                    if not api.kernel32.ResetEvent(reader["event"]):
                        raise ctypes.WinError(ctypes.get_last_error())
                    reader["transferred"].value = 0
                    immediate = api.kernel32.ReadFile(reader["handle"], reader["buffer"], 21,
                        ctypes.byref(reader["transferred"]), ctypes.byref(reader["overlap"]))
                    if immediate:
                        consume(reader)
                    elif ctypes.get_last_error() == hp460.ERROR_IO_PENDING:
                        reader["pending"] = True
                    else:
                        raise ctypes.WinError(ctypes.get_last_error())
                elif api.kernel32.WaitForSingleObject(reader["event"], 0) == hp460.WAIT_OBJECT_0:
                    if not api.kernel32.GetOverlappedResult(reader["handle"], ctypes.byref(reader["overlap"]),
                                                           ctypes.byref(reader["transferred"]), False):
                        raise ctypes.WinError(ctypes.get_last_error())
                    reader["pending"] = False
                    consume(reader)
            if not result["program_sent"]:
                for frame in frame_button_payload(marker_payload(prefix_fetch)):
                    api.write(selected, frame)
                    time.sleep(0.01)
                result["program_sent"] = True
            time.sleep(0.005)
    finally:
        for reader in readers:
            if reader["pending"]:
                api.kernel32.CancelIoEx(reader["handle"], ctypes.byref(reader["overlap"]))
                # Complete cancellation before releasing OVERLAPPED/buffer storage.
                api.kernel32.GetOverlappedResult(reader["handle"], ctypes.byref(reader["overlap"]),
                                                ctypes.byref(reader["transferred"]), True)
            api.kernel32.CloseHandle(reader["event"])
            api.kernel32.CloseHandle(reader["handle"])
        for device in devices:
            api.close(device)
    after = query_programs()
    result["stored_programs_unchanged"] = before == after
    if before != after:
        result["status"] = "unexpected_program_table_change"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="send the fixed temporary marker program")
    parser.add_argument("--prefix-fetch", action="store_true", help="fixed bounded descriptor-prefix fetch test")
    parser.add_argument("--emulate", type=Path, help="validate the fixed program using original ARM instructions")
    parser.add_argument("--output", type=Path, help="exclusive-create sanitized result")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output already exists")
    if args.run and args.emulate:
        parser.error("Choose either hardware or offline emulation")
    if args.emulate:
        import hashlib
        from firmware_analysis import ASH_1200_SHA256
        from experiments.validate_program_vm import emulate_program
        data = args.emulate.read_bytes()
        if hashlib.sha256(data).hexdigest() != ASH_1200_SHA256:
            parser.error("Requires exact stock Ash 1.2")
        payload = marker_payload(args.prefix_fetch)
        reports, calls = emulate_program(data, payload[6:], through_simulate=True,
                                         button_id=payload[2], record_host=payload[3], record_press_type=payload[4])
        assert reports == [("notify", expected_notification(args.prefix_fetch))]
        assert calls == ["0x1000aa68"]
        report = {"status": "offline_pass", "notifications": 1, "keyboard_or_media_callbacks": 0}
    elif args.run:
        if os.name != "nt":
            parser.error("Hardware access requires Windows")
        report = run_marker(args.prefix_fetch)
    else:
        report = {"status": "offline_preview", "reports_hex": [frame.hex(" ") for frame in
                  frame_button_payload(marker_payload(args.prefix_fetch))]}
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] in ("offline_pass", "offline_preview", "success") else 2


if __name__ == "__main__":
    raise SystemExit(main())
