"""Read HP vendor features; optionally test the temporary auxiliary handshake.

Default: GET_FEATURE only. --handshake sends fixed 10/28 auxiliary protocol
commands on report 9, reads the response and resets that temporary protocol.
No arbitrary command, address/value write, firmware transfer or remap is exposed.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPORT_PAGES = {5: 0xFF00, 8: 0xFF01, 9: 0xFF02}


def worker(report_id: int, operation: str) -> dict:
    import hp460

    api = hp460.WindowsHidApi()
    collections, _ = api.matching_collections()
    selected = [c for c in collections if c.usage_page == REPORT_PAGES[report_id]
                and c.usage == 1 and c.feature_length == 21]
    if len(selected) != 1:
        return {"status": "requires_one_collection", "matches": len(selected)}
    access = 0 if operation == "get" else hp460.GENERIC_READ | hp460.GENERIC_WRITE
    handle = api.kernel32.CreateFileW(selected[0].path, access,
        hp460.FILE_SHARE_READ | hp460.FILE_SHARE_WRITE, None, hp460.OPEN_EXISTING, 0, None)
    if ctypes.c_void_p(handle).value == hp460.INVALID_HANDLE_VALUE:
        return {"status": "open_failed", "error": ctypes.get_last_error()}
    for name in ("HidD_GetFeature", "HidD_SetFeature"):
        function = getattr(api.hid, name)
        function.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        function.restype = ctypes.c_ubyte

    def get():
        buffer = ctypes.create_string_buffer(21)
        buffer[0] = bytes((report_id,))
        if not api.hid.HidD_GetFeature(handle, buffer, 21):
            raise ctypes.WinError(ctypes.get_last_error())
        return bytes(buffer).hex()

    def send(command):
        buffer = ctypes.create_string_buffer(bytes((9, command)) + bytes(19), 21)
        if not api.hid.HidD_SetFeature(handle, buffer, 21):
            raise ctypes.WinError(ctypes.get_last_error())

    result = {"status": "success"}
    stage = "initial_read"
    try:
        if operation == "get":
            result["report_hex"] = get()
        elif operation == "reset":
            stage = "reset_write"
            send(0x28)
            stage = "reset_read"
            result["reset_report_hex"] = get()
        else:
            result["before_hex"] = get()
            if any(bytes.fromhex(result["before_hex"])[1:]):
                return {"status": "nonempty_initial_reply", "before_hex": result["before_hex"]}
            try:
                stage = "enable_write"
                send(0x10)
                result["enable_sent"] = True
                stage = "enabled_read"
                result["enabled_hex"] = get()
            finally:
                # Reset even if sending/reading the enable command fails.
                try:
                    send(0x28)
                    result["reset_sent"] = True
                    result["reset_report_hex"] = get()
                except OSError as reset_error:
                    result["reset_error"] = reset_error.winerror
            enabled = bytes.fromhex(result["enabled_hex"])
            result["expected_enable_reply"] = enabled.startswith(bytes.fromhex("09 00 0E 02 10 00"))
            result["reset_empty"] = "reset_report_hex" in result and not any(bytes.fromhex(result["reset_report_hex"])[1:])
    except OSError as error:
        result.update(status="io_failed", error=error.winerror, error_stage=stage)
    finally:
        api.kernel32.CloseHandle(handle)
    return result


def run_worker(report_id, operation, timeout):
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", operation, "--report", str(report_id)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    if completed.returncode or not completed.stdout.strip():
        return {"status": "worker_failed", "exit_code": completed.returncode}
    try:
        return json.loads(completed.stdout)
    except ValueError:
        return {"status": "invalid_worker_response"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handshake", action="store_true")
    parser.add_argument("--output", type=Path, help="exclusive-create private report; raw responses are omitted from stdout")
    parser.add_argument("--timeout", type=float, default=8)
    parser.add_argument("--worker", choices=("get", "handshake", "reset"), help=argparse.SUPPRESS)
    parser.add_argument("--report", type=int, choices=REPORT_PAGES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 15:
        parser.error("Timeout must be 1..15 seconds per worker")
    if args.worker:
        if args.report is None or (args.worker != "get" and args.report != 9):
            parser.error("A valid report is required; only report 9 supports the handshake")
        print(json.dumps(worker(args.report, args.worker)))
        return
    if args.output and args.output.exists():
        parser.error("Output already exists; refusing to overwrite")
    records = []
    for report_id in ((9,) if args.handshake else REPORT_PAGES):
        result = run_worker(report_id, "handshake" if args.handshake else "get", args.timeout)
        if args.handshake and result["status"] in ("timeout", "worker_failed", "invalid_worker_response"):
            # The bounded child may have ended before its finally block ran.
            result["fallback_reset"] = run_worker(9, "reset", args.timeout)
        result.update(report_id=report_id, usage_page=f"{REPORT_PAGES[report_id]:04X}")
        records.append(result)
        public = {k: v for k, v in result.items() if not k.endswith("_hex") and k != "fallback_reset"}
        if "report_hex" in result:
            raw = bytes.fromhex(result["report_hex"])
            public.update(payload_nonzero=any(raw[1:]), sha256=hashlib.sha256(raw).hexdigest())
        if "fallback_reset" in result:
            public["fallback_reset_status"] = result["fallback_reset"]["status"]
        print(json.dumps(public))
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(records, stream, indent=2)
            stream.write("\n")


if __name__ == "__main__":
    main()
