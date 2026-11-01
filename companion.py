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
import logging
import math
import os
import subprocess
import sys
import time
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from pathlib import Path

import hp460
from experiments.button_transport import frame_button_payload
from experiments.key_mask_bridge import MaskTracker, decode_mask
from experiments.key_mask_program import build_key_mask_program


F_VKS = {index + 1: 0x70 + index for index in range(12)}
KEYEVENTF_KEYUP = 0x0002
HPAC_PROCESS = "HPAccessoryCenter.exe"
INSTANCE_MUTEX_NAME = r"Local\HP460Companion"
ERROR_ALREADY_EXISTS = 183
ERROR_NO_MORE_FILES = 18
TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260
NOTIFICATION_COUNT = 127
RELOAD_SECONDS = 1.0
NOTIFICATION_TIMEOUT_SECONDS = 3.0
LOG_MAX_BYTES = 256 * 1024
LOG_BACKUPS = 2


LOGGER = logging.getLogger("hp460-companion")


ULONG_PTR = ctypes.c_size_t


class ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("default_heap_id", ULONG_PTR),
        ("module_id", wintypes.DWORD),
        ("threads", wintypes.DWORD),
        ("parent_process_id", wintypes.DWORD),
        ("base_priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
        ("executable", wintypes.WCHAR * MAX_PATH),
    ]


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


def configure_logging() -> Path | None:
    """Write bounded diagnostics for console and pythonw execution."""
    if LOGGER.handlers:
        handler = LOGGER.handlers[0]
        return Path(handler.baseFilename) if hasattr(handler, "baseFilename") else None
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    try:
        log_dir = Path(local_app_data) / "HP460Companion"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "companion.log"
        handler = RotatingFileHandler(
            log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
            encoding="utf-8", delay=True,
        )
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    return log_path


def report(message: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(message, file=stream, flush=True)
    LOGGER.log(logging.ERROR if error else logging.INFO, message)


def release_injected_keys(tracker: MaskTracker, observe: bool = False) -> None:
    """Release every synthetic F-key still held by the companion."""
    transitions = tracker.release()
    if observe:
        return
    for key, down in transitions:
        try:
            inject_key(F_VKS[int(key[1:])], down)
        except OSError as exc:
            report(f"Failed to release {key}: {exc}", error=True)


def acquire_instance_lock() -> tuple[object, int] | None:
    """Hold a session-local named mutex, or return None for a second instance."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, INSTANCE_MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return kernel32, handle


def ensure_clean_state(api: hp460.WindowsHidApi, selected: hp460.HidDevice) -> None:
    api.write(selected, hp460.build_fn_lock_report(current=False, startup=False))
    for button_id in range(12):
        api.write(selected, hp460.build_button_clear_report(button_id=button_id, host=0))


def find_process_ids(executable: str) -> list[int]:
    """Return matching process IDs without launching another program."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if ctypes.c_void_p(snapshot).value == hp460.INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    entry = ProcessEntry32()
    entry.size = ctypes.sizeof(entry)
    process_ids: list[int] = []
    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            error = ctypes.get_last_error()
            if error == ERROR_NO_MORE_FILES:
                return []
            raise ctypes.WinError(error)
        while True:
            if entry.executable.casefold() == executable.casefold():
                process_ids.append(entry.process_id)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                error = ctypes.get_last_error()
                if error == ERROR_NO_MORE_FILES:
                    break
                raise ctypes.WinError(error)
    finally:
        kernel32.CloseHandle(snapshot)
    return process_ids


def close_hpac_if_running() -> bool:
    if not find_process_ids(HPAC_PROCESS):
        return False
    result = subprocess.run(
        ["taskkill", "/F", "/IM", HPAC_PROCESS],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode not in (0, 128):
        raise RuntimeError(f"Failed to close {HPAC_PROCESS}: {result.stderr.strip()}")
    return result.returncode == 0


def load_mask_program(api: hp460.WindowsHidApi, selected: hp460.HidDevice,
                      notifications: int = NOTIFICATION_COUNT) -> None:
    code = build_key_mask_program(notifications)
    payload = bytes((2, 0, 3, 1, 0, len(code))) + code
    for frame in frame_button_payload(payload):
        api.write(selected, frame)


def read_notifications(api: hp460.WindowsHidApi, selected: hp460.HidDevice,
                       observe: bool = False, seconds: float | None = None) -> None:
    tracker = MaskTracker()
    handle = api.kernel32.CreateFileW(selected.path, hp460.GENERIC_READ,
        hp460.FILE_SHARE_READ | hp460.FILE_SHARE_WRITE, None, hp460.OPEN_EXISTING,
        hp460.FILE_FLAG_OVERLAPPED, None)
    if ctypes.c_void_p(handle).value == hp460.INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    event = api.kernel32.CreateEventW(None, True, False, None)
    if not event:
        error = ctypes.get_last_error()
        api.kernel32.CloseHandle(handle)
        raise ctypes.WinError(error)
    overlapped = hp460.Overlapped(event=event)
    buffer = ctypes.create_string_buffer(21)
    transferred = wintypes.DWORD()
    pending = False
    last_reload = time.monotonic()
    started = time.monotonic()
    last_notification = started
    count = 0
    last_heartbeat = started
    try:
        while True:
            if seconds is not None and time.monotonic() - started >= seconds:
                return
            now = time.monotonic()
            if now - last_notification >= NOTIFICATION_TIMEOUT_SECONDS:
                raise RuntimeError("Notification stream timed out")
            if now - last_reload >= RELOAD_SECONDS:
                load_mask_program(api, selected)
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
            last_notification = time.monotonic()
            count += 1
            if observe and time.monotonic() - last_heartbeat >= 1.0:
                report(f"heartbeat: {count} notifications, last mask={mask:03X}")
                last_heartbeat = time.monotonic()
            for key, down in tracker.update(mask):
                if observe:
                    report(f"{key} {'DOWN' if down else 'UP'} (mask={mask:03X})")
                else:
                    inject_key(F_VKS[int(key[1:])], down)
    finally:
        if pending:
            api.kernel32.CancelIoEx(handle, ctypes.byref(overlapped))
            api.kernel32.WaitForSingleObject(event, 1000)
        release_injected_keys(tracker, observe)
        api.kernel32.CloseHandle(event)
        api.kernel32.CloseHandle(handle)


def run(args: argparse.Namespace) -> int:
    unavailable: str | None = None
    while True:
        try:
            api, devices, selected = hp460.open_selected_device(args.device_index)
        except KeyboardInterrupt:
            return 0
        except hp460.ControlInterfaceBusyError as exc:
            message = f"Device not ready: {exc}"
            if message != unavailable:
                report(message, error=True)
                unavailable = message
            try:
                if close_hpac_if_running():
                    report("Closed HP Accessory Center; retrying the keyboard now.")
                    continue
            except Exception as hpac_exc:
                failure = f"Failed to handle HP Accessory Center: {hpac_exc}"
                if failure != unavailable:
                    report(failure, error=True)
                    unavailable = failure
            time.sleep(args.reconnect_seconds)
            continue
        except Exception as exc:
            message = f"Device not ready: {exc}"
            if message != unavailable:
                report(message, error=True)
                unavailable = message
            time.sleep(args.reconnect_seconds)
            continue
        if unavailable is not None:
            report("HP 460 keyboard is ready again.")
            unavailable = None
        try:
            ensure_clean_state(api, selected)
            load_mask_program(api, selected)
            read_notifications(api, selected, observe=args.observe, seconds=args.seconds)
            if args.seconds is not None:
                return 0
            report("Notification stream stopped; reconnecting.")
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            report(f"Runtime error; reconnecting: {exc}", error=True)
        finally:
            for device in devices:
                api.close(device)
        time.sleep(args.reconnect_seconds)


def build_parser() -> argparse.ArgumentParser:
    def nonnegative_int(value: str) -> int:
        parsed = int(value)
        if parsed < 0:
            raise argparse.ArgumentTypeError("must be zero or greater")
        return parsed

    def positive_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed) or parsed <= 0:
            raise argparse.ArgumentTypeError("must be a finite number greater than zero")
        return parsed

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-index", type=nonnegative_int, default=0)
    parser.add_argument("--reconnect-seconds", type=positive_float, default=3.0)
    parser.add_argument("--observe", action="store_true",
                        help="decode and print the mask stream without injecting keys")
    parser.add_argument("--seconds", type=positive_float, default=None,
                        help="run the notification loop for a bounded number of seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    lock = acquire_instance_lock()
    if lock is None:
        report("HP 460 companion is already running.")
        return 0
    kernel32, handle = lock
    try:
        report("HP 460 companion started.")
        return run(args)
    finally:
        report("HP 460 companion stopped.")
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
