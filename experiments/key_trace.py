"""Short, passive Windows keyboard/consumer trace for the HP 460 experiments.

Records only the test keys below. Never suppresses input, injects events,
changes Fn Lock, installs a driver or enables startup. Device paths stay private.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import os
import queue
import sys
import time
from ctypes import wintypes as W
from pathlib import Path

NAMES = {**{0x70 + i: f"F{i + 1}" for i in range(24)},
         0x10: "SHIFT", 0x11: "CTRL", 0x12: "ALT",
         0xA0: "LSHIFT", 0xA1: "RSHIFT", 0xA2: "LCTRL", 0xA3: "RCTRL",
         0xA4: "LALT", 0xA5: "RALT", 0x5B: "LWIN", 0x5C: "RWIN",
         0xAD: "MUTE", 0xAE: "VOLUME_DOWN", 0xAF: "VOLUME_UP",
         0xB0: "MEDIA_NEXT", 0xB1: "MEDIA_PREVIOUS", 0xB3: "MEDIA_PLAY_PAUSE",
         0x2C: "PRINTSCREEN", 0x24: "HOME", 0x23: "END", 0x21: "PAGEUP",
         0x22: "PAGEDOWN", 0x2D: "INSERT", 0x2E: "DELETE", 0x1B: "ESC",
         0xB7: "APP2", 0x91: "SCROLLLOCK", 0x20: "SPACE",
         0xA6: "BROWSER_BACK", 0xA7: "BROWSER_FORWARD", 0xA8: "BROWSER_REFRESH",
         0xA9: "BROWSER_STOP", 0xAA: "BROWSER_SEARCH", 0xAB: "BROWSER_FAVORITES", 0xAC: "BROWSER_HOME",
         0xBA: "MACRO_SEMICOLON", 0xBE: "MACRO_PERIOD",
         0x49: "MACRO_I", 0x4C: "MACRO_L", 0x46: "MACRO_F"}
WM_INPUT, WM_TIMER, WM_CLOSE, WM_DESTROY = 0xFF, 0x113, 0x10, 2
KEY_UP_MESSAGES = (0x101, 0x105)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30, help="bounded capture duration (default 30; maximum 120)")
    parser.add_argument("--output", type=Path, help="exclusive-create JSONL file; otherwise console only")
    args = parser.parse_args()
    if not 0 < args.seconds <= 120:
        parser.error("--seconds must be greater than zero and at most 120")
    if os.name != "nt":
        parser.error("Windows only")

    user = C.WinDLL("user32", use_last_error=True)
    kernel = C.WinDLL("kernel32", use_last_error=True)
    result_type = C.c_ssize_t
    callback = C.WINFUNCTYPE(result_type, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    hook_callback = C.WINFUNCTYPE(result_type, C.c_int, W.WPARAM, W.LPARAM)

    class WindowClass(C.Structure):
        _fields_ = [("style", W.UINT), ("procedure", callback), ("class_extra", C.c_int),
                    ("window_extra", C.c_int), ("instance", W.HINSTANCE), ("icon", W.HICON),
                    ("cursor", W.HANDLE), ("brush", W.HBRUSH), ("menu", W.LPCWSTR), ("name", W.LPCWSTR)]

    class RawDevice(C.Structure):
        _fields_ = [("page", W.USHORT), ("usage", W.USHORT), ("flags", W.DWORD), ("window", W.HWND)]

    class RawHeader(C.Structure):
        _fields_ = [("kind", W.DWORD), ("size", W.DWORD), ("device", W.HANDLE), ("parameter", W.WPARAM)]

    class RawKeyboard(C.Structure):
        _fields_ = [("scan", W.USHORT), ("flags", W.USHORT), ("reserved", W.USHORT),
                    ("vk", W.USHORT), ("message", W.UINT), ("extra", W.ULONG)]

    class HookEvent(C.Structure):
        _fields_ = [("vk", W.DWORD), ("scan", W.DWORD), ("flags", W.DWORD),
                    ("timestamp", W.DWORD), ("extra", C.c_size_t)]

    user.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user.DefWindowProcW.restype = result_type
    user.RegisterClassW.argtypes = [C.POINTER(WindowClass)]
    user.RegisterClassW.restype = W.ATOM
    user.UnregisterClassW.argtypes = [W.LPCWSTR, W.HINSTANCE]
    user.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                                   C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
    user.CreateWindowExW.restype = W.HWND
    user.DestroyWindow.argtypes = [W.HWND]
    user.RegisterRawInputDevices.argtypes = [C.POINTER(RawDevice), W.UINT, W.UINT]
    user.RegisterRawInputDevices.restype = W.BOOL
    user.GetRawInputData.argtypes = [W.HANDLE, W.UINT, C.c_void_p, C.POINTER(W.UINT), W.UINT]
    user.GetRawInputData.restype = W.UINT
    user.GetRawInputDeviceInfoW.argtypes = [W.HANDLE, W.UINT, C.c_void_p, C.POINTER(W.UINT)]
    user.GetRawInputDeviceInfoW.restype = W.UINT
    user.SetWindowsHookExW.argtypes = [C.c_int, hook_callback, W.HINSTANCE, W.DWORD]
    user.SetWindowsHookExW.restype = W.HHOOK
    user.CallNextHookEx.argtypes = [W.HHOOK, C.c_int, W.WPARAM, W.LPARAM]
    user.CallNextHookEx.restype = result_type
    user.UnhookWindowsHookEx.argtypes = [W.HHOOK]
    user.GetMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
    user.GetMessageW.restype = W.BOOL
    user.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
    user.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
    user.DispatchMessageW.restype = result_type
    user.SetTimer.argtypes = [W.HWND, C.c_size_t, W.UINT, C.c_void_p]
    user.SetTimer.restype = C.c_size_t
    user.KillTimer.argtypes = [W.HWND, C.c_size_t]
    user.PostQuitMessage.argtypes = [C.c_int]
    kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]
    kernel.GetModuleHandleW.restype = W.HMODULE

    events = queue.SimpleQueue()
    aliases: dict[int, str] = {}
    started = time.perf_counter()
    deadline = started + args.seconds
    callback_failure: list[Exception] = []
    output = None
    hwnd = hook = atom = None
    instance = kernel.GetModuleHandleW(None)
    class_name = f"HP460PassiveTrace_{os.getpid()}"

    def emit(source, **values):
        events.put({"ms": round((time.perf_counter() - started) * 1000, 3), "source": source, **values})

    def device_alias(handle):
        if handle not in aliases:
            length = W.UINT()
            if user.GetRawInputDeviceInfoW(handle, 0x20000007, None, C.byref(length)) == 0xFFFFFFFF:
                raise C.WinError(C.get_last_error())
            name = C.create_unicode_buffer(length.value + 1)
            if user.GetRawInputDeviceInfoW(handle, 0x20000007, name, C.byref(length)) == 0xFFFFFFFF:
                raise C.WinError(C.get_last_error())
            path = name.value.upper()
            family = "HP460" if "03F0" in path and "814A" in path else "OTHER"
            aliases[handle] = f"{family}-{len(aliases) + 1}"
        return aliases[handle]

    def read_raw(parameter):
        length = W.UINT()
        if user.GetRawInputData(parameter, 0x10000003, None, C.byref(length), C.sizeof(RawHeader)) == 0xFFFFFFFF:
            raise C.WinError(C.get_last_error())
        buffer = C.create_string_buffer(length.value)
        if user.GetRawInputData(parameter, 0x10000003, buffer, C.byref(length), C.sizeof(RawHeader)) == 0xFFFFFFFF:
            raise C.WinError(C.get_last_error())
        header = RawHeader.from_buffer(buffer)
        offset = C.sizeof(RawHeader)
        if header.kind == 1 and length.value >= offset + C.sizeof(RawKeyboard):
            key = RawKeyboard.from_buffer(buffer, offset)
            if key.vk in NAMES:
                emit("raw-keyboard", device=device_alias(header.device), key=NAMES[key.vk],
                     vk=key.vk, scan=key.scan, flags=key.flags, down=not bool(key.flags & 1), message=key.message)
        elif header.kind == 2 and length.value >= offset + 8:
            # Only consumer-control TLC was registered, not arbitrary vendor HID.
            alias = device_alias(header.device)
            if alias.startswith("HP460"):
                emit("raw-consumer", device=alias, report=bytes(buffer)[offset:].hex())

    @callback
    def procedure(window, message, wp, lp):
        try:
            if message == WM_INPUT:
                read_raw(lp)
            elif message == WM_TIMER:
                if time.perf_counter() >= deadline or callback_failure:
                    user.DestroyWindow(window)
            elif message == WM_CLOSE:
                user.DestroyWindow(window)
                return 0
            elif message == WM_DESTROY:
                user.PostQuitMessage(0)
                return 0
        except Exception as error:
            callback_failure.append(error)
        return user.DefWindowProcW(window, message, wp, lp)

    @hook_callback
    def observe(code, message, parameter):
        try:
            if code == 0:
                key = C.cast(parameter, C.POINTER(HookEvent)).contents
                if key.vk in NAMES:
                    emit("hook", key=NAMES[key.vk], vk=key.vk, scan=key.scan, flags=key.flags,
                         down=message not in KEY_UP_MESSAGES, injected=bool(key.flags & 0x10), os_ms=key.timestamp)
        except Exception as error:
            callback_failure.append(error)
        return user.CallNextHookEx(None, code, message, parameter)

    def flush():
        while not events.empty():
            line = json.dumps(events.get(), separators=(",", ":"))
            print(line, flush=True)
            if output:
                output.write(line + "\n")

    try:
        if args.output:
            output = args.output.open("x", encoding="utf-8")
        window_class = WindowClass(procedure=procedure, instance=instance, name=class_name)
        atom = user.RegisterClassW(C.byref(window_class))
        if not atom:
            raise C.WinError(C.get_last_error())
        hwnd = user.CreateWindowExW(0, class_name, "HP460 passive trace", 0, 0, 0, 0, 0, W.HWND(-3), None, instance, None)
        if not hwnd:
            raise C.WinError(C.get_last_error())
        devices = (RawDevice * 2)(RawDevice(1, 6, 0x100, hwnd), RawDevice(0xC, 1, 0x100, hwnd))
        if not user.RegisterRawInputDevices(devices, 2, C.sizeof(RawDevice)):
            raise C.WinError(C.get_last_error())
        hook = user.SetWindowsHookExW(13, observe, instance, 0)
        if not hook or not user.SetTimer(hwnd, 1, 20, None):
            raise C.WinError(C.get_last_error())
        print(f"Passive trace active for {args.seconds:g}s; no keys blocked or generated. Ctrl+C stops.", file=sys.stderr, flush=True)
        print("Do not test F11 without a separate Win+L guard. No keyboard settings were changed.", file=sys.stderr, flush=True)
        message = W.MSG()
        while True:
            status = user.GetMessageW(C.byref(message), None, 0, 0)
            if status == -1:
                raise C.WinError(C.get_last_error())
            if status == 0:
                break
            user.TranslateMessage(C.byref(message))
            user.DispatchMessageW(C.byref(message))
            flush()
        flush()
        if callback_failure:
            raise RuntimeError(f"Trace callback failed: {callback_failure[0]}")
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        if hook:
            user.UnhookWindowsHookEx(hook)
        if hwnd:
            user.KillTimer(hwnd, 1)
            user.DestroyWindow(hwnd)
        if atom:
            user.UnregisterClassW(class_name, instance)
        if output:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
