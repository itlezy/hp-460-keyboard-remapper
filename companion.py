"""Windows companion for the HP 460 native F-row key-mask stream.

Every run starts from a clean, deterministic keyboard state:

1. Fn Lock off (current and startup), so navigation is native even after a
   power cycle.
2. Stored F1-F12 programs cleared, so no HPAC macro can shadow the temporary
   mask program.
3. A bounded temporary VM program is loaded. It consumes all twelve F-row
   bits and emits the combined mask as a vendor notification.

The helper then reads those notifications and injects only the changed F-key
down/up events through SendInput. It never injects modifiers; Shift/Ctrl/Alt
come from the physical keys, so Shift+F4 stays Shift+F4.

The mask program is bounded to a small number of notifications, so the helper
reloads it periodically. If the helper stops, the current program expires on
its own and the F-row returns to the stock Fn-Lock-off behavior.
"""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hp460
from experiments.button_transport import frame_button_payload
from experiments.key_mask_bridge import MaskTracker, decode_mask
from experiments.key_mask_program import build_key_mask_program


F_VKS = {index + 1: 0x70 + index for index in range(12)}
KEYEVENTF_KEYUP = 0x0002
HPAC_PROCESS = "HPAccessoryCenter.exe"


ULONG_PTR = ctypes.c_size_t


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KeybdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeybdInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]


def inject_key(vk: int, down: bool) -> None:
    entry = Input()
    entry.type = 1  # INPUT_KEYBOARD
    entry.union.ki = KeybdInput(vk, 0, 0 if down else KEYEVENTF_KEYUP, 0, 0)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if user32.SendInput(1, ctypes.byref(entry), ctypes.sizeof(Input)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def ensure_clean_state(api: hp460.WindowsHidApi, selected: hp460.HidDevice) -> None:
    api.write(selected, hp460.build_fn_lock_report(current=False, startup=False))
    for button_id in range(12):
        api.write(selected, hp460.build_button_clear_report(button_id=button_id, host=0))


def ensure_hpac_closed() -> None:
    result = subprocess.run(
        ["taskkill", "/F", "/IM", HPAC_PROCESS],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode not in (0, 128):
        raise RuntimeError(f"Failed to close {HPAC_PROCESS}: {result.stderr.strip()}")


def load_mask_program(api: hp460.WindowsHidApi, selected: hp460.HidDevice,
                      notifications: int = 127) -> None:
    code = build_key_mask_program(notifications)
    payload = bytes((2, 0, 3, 1, 0, len(code))) + code
    for frame in frame_button_payload(payload):
        api.write(selected, frame)


def read_notifications(api: hp460.WindowsHidApi, selected: hp460.HidDevice,
                       reload_seconds: float, notifications: int,
                       observe: bool = False, seconds: float | None = None) -> None:
    tracker = MaskTracker()
    handle = api.kernel32.CreateFileW(selected.path, hp460.GENERIC_READ,
        hp460.FILE_SHARE_READ | hp460.FILE_SHARE_WRITE, None, hp460.OPEN_EXISTING,
        hp460.FILE_FLAG_OVERLAPPED, None)
    if ctypes.c_void_p(handle).value == hp460.INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    event = api.kernel32.CreateEventW(None, True, False, None)
    overlapped = hp460.Overlapped(event=event)
    buffer = ctypes.create_string_buffer(21)
    transferred = wintypes.DWORD()
    pending = False
    last_reload = time.monotonic()
    started = time.monotonic()
    count = 0
    last_heartbeat = started
    try:
        while True:
            if seconds is not None and time.monotonic() - started >= seconds:
                return
            if time.monotonic() - last_reload >= reload_seconds:
                load_mask_program(api, selected, notifications)
                last_reload = time.monotonic()
            if not pending:
                if not api.kernel32.ResetEvent(event):
                    raise ctypes.WinError(ctypes.get_last_error())
                transferred.value = 0
                immediate = api.kernel32.ReadFile(handle, buffer, 21,
                    ctypes.byref(transferred), ctypes.byref(overlapped))
                if not immediate:
                    if ctypes.get_last_error() != hp460.ERROR_IO_PENDING:
                        raise ctypes.WinError(ctypes.get_last_error())
                    pending = True
            if pending:
                status = api.kernel32.WaitForSingleObject(event, 100)
                if status == hp460.WAIT_TIMEOUT:
                    continue
                if status != hp460.WAIT_OBJECT_0:
                    raise ctypes.WinError(ctypes.get_last_error())
                if not api.kernel32.GetOverlappedResult(handle, ctypes.byref(overlapped),
                                                        ctypes.byref(transferred), False):
                    raise ctypes.WinError(ctypes.get_last_error())
                pending = False
            frame = bytes(buffer[:transferred.value])
            if len(frame) != 21 or frame[0:3] != b"\x06\x01\x0D":
                continue
            payload = frame[5:5 + frame[3]]
            try:
                mask = decode_mask(payload)
            except ValueError:
                continue
            count += 1
            if observe and time.monotonic() - last_heartbeat >= 1.0:
                print(f"heartbeat: {count} notifications, last mask={mask:03X}", flush=True)
                last_heartbeat = time.monotonic()
            for key, down in tracker.update(mask):
                if observe:
                    print(f"{key} {'DOWN' if down else 'UP'} (mask={mask:03X})", flush=True)
                else:
                    inject_key(F_VKS[int(key[1:])], down)
    finally:
        if pending:
            api.kernel32.CancelIoEx(handle, ctypes.byref(overlapped))
            api.kernel32.WaitForSingleObject(event, 1000)
        api.kernel32.CloseHandle(event)
        api.kernel32.CloseHandle(handle)


def run(args: argparse.Namespace) -> int:
    if not args.no_kill_hpac:
        ensure_hpac_closed()
    api, devices, selected = hp460.open_selected_device(args.device_index)
    try:
        ensure_clean_state(api, selected)
        load_mask_program(api, selected, args.notifications)
        if args.dry_run:
            print("Clean state applied and bounded mask program loaded.")
            return 0
        read_notifications(api, selected, args.reload_seconds, args.notifications,
                           observe=args.observe, seconds=args.seconds)
        return 0
    finally:
        for device in devices:
            api.close(device)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--notifications", type=int, default=127)
    parser.add_argument("--reload-seconds", type=float, default=1.0)
    parser.add_argument("--observe", action="store_true",
                        help="decode and print the mask stream without injecting keys")
    parser.add_argument("--seconds", type=float, default=None,
                        help="run the notification loop for a bounded number of seconds")
    parser.add_argument("--dry-run", action="store_true",
                        help="apply clean state and load one program, then exit without the loop")
    parser.add_argument("--no-kill-hpac", action="store_true",
                        help="do not terminate HP Accessory Center before opening the device")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
