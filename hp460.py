#!/usr/bin/env python3
"""Control Fn Lock and inspect key-layer behavior on an HP 460 keyboard."""

from __future__ import annotations

import argparse
import ctypes
import math
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass


VENDOR_ID = 0x03F0
PRODUCT_ID = 0x814A
TARGET_USAGE_PAGE = 0xFF05
TARGET_USAGE = 0x0001
REPORT_LENGTH = 21

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
ERROR_NO_MORE_ITEMS = 259
ERROR_IO_PENDING = 997
ERROR_NOT_FOUND = 1168
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
WRITE_TIMEOUT_SECONDS = 2.0
WRITE_CANCEL_WAIT_MS = 1000


TARGET_VKS = {
    0x70: "F1",
    0x71: "F2",
    0x72: "F3",
    0x73: "F4",
    0x74: "F5",
    0x75: "F6",
    0x76: "F7",
    0x77: "F8",
    0x78: "F9",
    0x79: "F10",
    0x7A: "F11",
    0x7B: "F12",
    0xA0: "LEFT_SHIFT",
    0xA1: "RIGHT_SHIFT",
    0xAD: "VOLUME_MUTE",
    0xAE: "VOLUME_DOWN",
    0xAF: "VOLUME_UP",
    0xB0: "MEDIA_NEXT",
    0xB1: "MEDIA_PREVIOUS",
    0xB3: "MEDIA_PLAY_PAUSE",
    0x2C: "PRINTSCREEN",
    0x24: "HOME",
    0x23: "END",
    0x21: "PAGEUP",
    0x22: "PAGEDOWN",
    0x5B: "LWIN",
    0x20: "SPACE",
    0x1B: "ESC",
    0xB7: "LAUNCH_APP2",
}

FN_LOCK_PREFIX = bytes.fromhex(
    "06 10 0D 0C 00 80 0B 00 01 00 00 00 00 00 00 00"
)
FN_LOCK_SUFFIX = bytes.fromhex("E0 16 0A F3")


def build_fn_lock_report(*, current: bool, startup: bool) -> bytes:
    state = 0x02
    if current:
        state |= 0x04
    if startup:
        state |= 0x01
    report = FN_LOCK_PREFIX + bytes([state]) + FN_LOCK_SUFFIX
    if len(report) != REPORT_LENGTH:
        raise AssertionError(f"Unexpected report length: {len(report)}")
    return report


def build_button_set_report(*, button_id: int, usage: int, host: int = 0) -> bytes:
    """Build an experimental HPAC command-1 button-program report."""
    report = (
        bytes.fromhex("06 00 0D 09 00 01")
        + bytes([button_id, host])
        + bytes.fromhex("00 04 F8 00")
        + bytes([usage])
        + bytes.fromhex("00 02 00 00 00 00 00 00")
    )
    if len(report) != REPORT_LENGTH:
        raise AssertionError(f"Unexpected report length: {len(report)}")
    return report


def build_button_clear_report(*, button_id: int, host: int = 0) -> bytes:
    """Build HPAC command 1 with an empty experimental button program."""
    report = (
        bytes.fromhex("06 00 0D 05 00 01")
        + bytes([button_id, host])
        + bytes.fromhex("00 00 02 00 00 00 00 00 00 00 00 00 00")
    )
    if len(report) != REPORT_LENGTH:
        raise AssertionError(f"Unexpected report length: {len(report)}")
    return report


class Guid(ctypes.Structure):
    _fields_ = [
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", ctypes.c_ubyte * 8),
    ]


class SpDeviceInterfaceData(ctypes.Structure):
    _fields_ = [
        ("cb_size", wintypes.DWORD),
        ("interface_class_guid", Guid),
        ("flags", wintypes.DWORD),
        ("reserved", ctypes.c_void_p),
    ]


class HiddAttributes(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.ULONG),
        ("vendor_id", wintypes.USHORT),
        ("product_id", wintypes.USHORT),
        ("version_number", wintypes.USHORT),
    ]


class HidpCaps(ctypes.Structure):
    _fields_ = [
        ("usage", wintypes.USHORT),
        ("usage_page", wintypes.USHORT),
        ("input_report_byte_length", wintypes.USHORT),
        ("output_report_byte_length", wintypes.USHORT),
        ("feature_report_byte_length", wintypes.USHORT),
        ("reserved", wintypes.USHORT * 17),
        ("number_link_collection_nodes", wintypes.USHORT),
        ("number_input_button_caps", wintypes.USHORT),
        ("number_input_value_caps", wintypes.USHORT),
        ("number_input_data_indices", wintypes.USHORT),
        ("number_output_button_caps", wintypes.USHORT),
        ("number_output_value_caps", wintypes.USHORT),
        ("number_output_data_indices", wintypes.USHORT),
        ("number_feature_button_caps", wintypes.USHORT),
        ("number_feature_value_caps", wintypes.USHORT),
        ("number_feature_data_indices", wintypes.USHORT),
    ]


class Overlapped(ctypes.Structure):
    _fields_ = [
        ("internal", ctypes.c_size_t),
        ("internal_high", ctypes.c_size_t),
        ("offset", wintypes.DWORD),
        ("offset_high", wintypes.DWORD),
        ("event", wintypes.HANDLE),
    ]


# A timed-out operation normally completes immediately after CancelIoEx. If a
# broken driver does not acknowledge cancellation within the grace period, its
# ctypes buffers must remain alive until Windows eventually completes it.
_ORPHANED_WRITES: list[tuple[object, object, Overlapped, int]] = []


def _reap_orphaned_writes() -> None:
    remaining: list[tuple[object, object, Overlapped, int]] = []
    for kernel32, buffer, overlapped, event in _ORPHANED_WRITES:
        if kernel32.WaitForSingleObject(event, 0) == WAIT_OBJECT_0:
            kernel32.CloseHandle(event)
        else:
            remaining.append((kernel32, buffer, overlapped, event))
    _ORPHANED_WRITES[:] = remaining


@dataclass(frozen=True)
class HidDevice:
    path: str
    handle: int
    version: int


@dataclass(frozen=True)
class HidCollection:
    path: str
    usage_page: int
    usage: int
    input_length: int
    output_length: int
    feature_length: int
    version: int


class ControlInterfaceBusyError(RuntimeError):
    """The HP 460 control collection exists but another process owns it."""


class WindowsHidApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("HP 460 HID control is only available on Windows.")
        self.setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
        self.hid = ctypes.WinDLL("hid", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self.setupapi.SetupDiGetClassDevsW.argtypes = [
            ctypes.POINTER(Guid),
            wintypes.LPCWSTR,
            wintypes.HWND,
            wintypes.DWORD,
        ]
        self.setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
        self.setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(Guid),
            wintypes.DWORD,
            ctypes.POINTER(SpDeviceInterfaceData),
        ]
        self.setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(SpDeviceInterfaceData),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        self.setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

        self.hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(Guid)]
        self.hid.HidD_GetAttributes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(HiddAttributes),
        ]
        self.hid.HidD_GetPreparsedData.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
        self.hid.HidP_GetCaps.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(HidpCaps),
        ]
        self.hid.HidP_GetCaps.restype = ctypes.c_long

        self.kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.kernel32.CreateFileW.restype = wintypes.HANDLE
        self.kernel32.WriteFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        self.kernel32.ReadFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(Overlapped),
        ]
        self.kernel32.CreateEventW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self.kernel32.CreateEventW.restype = wintypes.HANDLE
        self.kernel32.WaitForSingleObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        self.kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
        self.kernel32.GetOverlappedResult.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Overlapped),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.BOOL,
        ]
        self.kernel32.CancelIoEx.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Overlapped),
        ]
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    def interface_paths(self) -> list[str]:
        hid_guid = Guid()
        self.hid.HidD_GetHidGuid(ctypes.byref(hid_guid))
        device_info = self.setupapi.SetupDiGetClassDevsW(
            ctypes.byref(hid_guid),
            None,
            None,
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
        )
        if ctypes.c_void_p(device_info).value == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())

        paths: list[str] = []
        try:
            index = 0
            while True:
                interface_data = SpDeviceInterfaceData()
                interface_data.cb_size = ctypes.sizeof(interface_data)
                found = self.setupapi.SetupDiEnumDeviceInterfaces(
                    device_info,
                    None,
                    ctypes.byref(hid_guid),
                    index,
                    ctypes.byref(interface_data),
                )
                if not found:
                    error = ctypes.get_last_error()
                    if error == ERROR_NO_MORE_ITEMS:
                        break
                    raise ctypes.WinError(error)

                required_size = wintypes.DWORD()
                self.setupapi.SetupDiGetDeviceInterfaceDetailW(
                    device_info,
                    ctypes.byref(interface_data),
                    None,
                    0,
                    ctypes.byref(required_size),
                    None,
                )
                detail = ctypes.create_string_buffer(required_size.value)
                ctypes.cast(detail, ctypes.POINTER(wintypes.DWORD))[0] = (
                    8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                )
                if not self.setupapi.SetupDiGetDeviceInterfaceDetailW(
                    device_info,
                    ctypes.byref(interface_data),
                    detail,
                    required_size,
                    None,
                    None,
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                paths.append(ctypes.wstring_at(ctypes.addressof(detail) + 4))
                index += 1
        finally:
            self.setupapi.SetupDiDestroyDeviceInfoList(device_info)
        return paths

    def open_matching_devices(self) -> tuple[list[HidDevice], list[tuple[str, int]]]:
        devices: list[HidDevice] = []
        blocked: list[tuple[str, int]] = []
        identity = "_dev_vid&0203f0_pid&814a_"

        for path in self.interface_paths():
            if identity not in path.lower():
                continue
            handle = self.kernel32.CreateFileW(
                path,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                FILE_FLAG_OVERLAPPED,
                None,
            )
            if ctypes.c_void_p(handle).value == INVALID_HANDLE_VALUE:
                blocked.append((path, ctypes.get_last_error()))
                continue

            attributes = HiddAttributes()
            attributes.size = ctypes.sizeof(attributes)
            preparsed_data = ctypes.c_void_p()
            try:
                if not self.hid.HidD_GetAttributes(handle, ctypes.byref(attributes)):
                    continue
                if (attributes.vendor_id, attributes.product_id) != (
                    VENDOR_ID,
                    PRODUCT_ID,
                ):
                    continue
                if not self.hid.HidD_GetPreparsedData(
                    handle, ctypes.byref(preparsed_data)
                ):
                    continue
                caps = HidpCaps()
                status = self.hid.HidP_GetCaps(preparsed_data, ctypes.byref(caps))
                if status < 0:
                    continue
                if (
                    caps.usage_page,
                    caps.usage,
                    caps.input_report_byte_length,
                    caps.output_report_byte_length,
                ) == (TARGET_USAGE_PAGE, TARGET_USAGE, REPORT_LENGTH, REPORT_LENGTH):
                    devices.append(HidDevice(path, handle, attributes.version_number))
                    handle = None
            finally:
                if preparsed_data.value:
                    self.hid.HidD_FreePreparsedData(preparsed_data)
                if handle is not None:
                    self.kernel32.CloseHandle(handle)
        return devices, blocked

    def matching_collections(self) -> tuple[list[HidCollection], int]:
        """Inspect HP 460 top-level HID collections without write access."""
        collections: list[HidCollection] = []
        blocked = 0
        identity = "_dev_vid&0203f0_pid&814a_"

        for path in self.interface_paths():
            if identity not in path.lower():
                continue
            handle = self.kernel32.CreateFileW(
                path,
                0,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None,
            )
            if ctypes.c_void_p(handle).value == INVALID_HANDLE_VALUE:
                blocked += 1
                continue

            attributes = HiddAttributes()
            attributes.size = ctypes.sizeof(attributes)
            preparsed_data = ctypes.c_void_p()
            try:
                if not self.hid.HidD_GetAttributes(handle, ctypes.byref(attributes)):
                    continue
                if (attributes.vendor_id, attributes.product_id) != (
                    VENDOR_ID,
                    PRODUCT_ID,
                ):
                    continue
                if not self.hid.HidD_GetPreparsedData(
                    handle, ctypes.byref(preparsed_data)
                ):
                    continue
                caps = HidpCaps()
                status = self.hid.HidP_GetCaps(preparsed_data, ctypes.byref(caps))
                if status < 0:
                    continue
                collections.append(
                    HidCollection(
                        path=path,
                        usage_page=caps.usage_page,
                        usage=caps.usage,
                        input_length=caps.input_report_byte_length,
                        output_length=caps.output_report_byte_length,
                        feature_length=caps.feature_report_byte_length,
                        version=attributes.version_number,
                    )
                )
            finally:
                if preparsed_data.value:
                    self.hid.HidD_FreePreparsedData(preparsed_data)
                self.kernel32.CloseHandle(handle)
        return collections, blocked

    def capture_input(
        self, collection: HidCollection, duration_seconds: float | None = None
    ) -> None:
        """Print reports from one input collection without writing to it."""
        if collection.input_length <= 0:
            raise RuntimeError("The selected collection has no input reports.")
        handle = self.kernel32.CreateFileW(
            collection.path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            None,
        )
        if ctypes.c_void_p(handle).value == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        event = self.kernel32.CreateEventW(None, True, False, None)
        if not event:
            self.kernel32.CloseHandle(handle)
            raise ctypes.WinError(ctypes.get_last_error())

        overlapped = Overlapped(event=event)
        buffer = ctypes.create_string_buffer(collection.input_length)
        transferred = wintypes.DWORD()
        pending = False
        deadline = (
            None
            if duration_seconds is None
            else time.monotonic() + duration_seconds
        )
        try:
            while deadline is None or time.monotonic() < deadline:
                if not pending:
                    if not self.kernel32.ResetEvent(event):
                        raise ctypes.WinError(ctypes.get_last_error())
                    transferred.value = 0
                    if self.kernel32.ReadFile(
                        handle,
                        buffer,
                        collection.input_length,
                        ctypes.byref(transferred),
                        ctypes.byref(overlapped),
                    ):
                        print(bytes(buffer[: transferred.value]).hex(" ").upper())
                        continue
                    error = ctypes.get_last_error()
                    if error != ERROR_IO_PENDING:
                        raise ctypes.WinError(error)
                    pending = True

                wait = self.kernel32.WaitForSingleObject(event, 100)
                if wait == WAIT_TIMEOUT:
                    continue
                if wait != WAIT_OBJECT_0:
                    raise ctypes.WinError(ctypes.get_last_error())
                if not self.kernel32.GetOverlappedResult(
                    handle,
                    ctypes.byref(overlapped),
                    ctypes.byref(transferred),
                    False,
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                print(bytes(buffer[: transferred.value]).hex(" ").upper(), flush=True)
                pending = False
        except KeyboardInterrupt:
            pass
        finally:
            if pending:
                self.kernel32.CancelIoEx(handle, ctypes.byref(overlapped))
                self.kernel32.WaitForSingleObject(event, 1000)
            self.kernel32.CloseHandle(event)
            self.kernel32.CloseHandle(handle)

    def close(self, device: HidDevice) -> None:
        self.kernel32.CloseHandle(device.handle)

    def write(
        self,
        device: HidDevice,
        report: bytes,
        timeout_seconds: float = WRITE_TIMEOUT_SECONDS,
    ) -> None:
        """Write one report without allowing a stalled HID driver to hang."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        _reap_orphaned_writes()
        buffer = ctypes.create_string_buffer(report)
        event = self.kernel32.CreateEventW(None, True, False, None)
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())
        overlapped = Overlapped(event=event)
        written = wintypes.DWORD()
        preserve_operation = False
        try:
            immediate = self.kernel32.WriteFile(
                device.handle,
                buffer,
                len(report),
                ctypes.byref(written),
                ctypes.byref(overlapped),
            )
            if not immediate:
                error = ctypes.get_last_error()
                if error != ERROR_IO_PENDING:
                    raise ctypes.WinError(error)

                timeout_ms = max(1, math.ceil(timeout_seconds * 1000))
                status = self.kernel32.WaitForSingleObject(event, timeout_ms)
                if status == WAIT_TIMEOUT:
                    cancelled = self.kernel32.CancelIoEx(
                        device.handle, ctypes.byref(overlapped)
                    )
                    cancel_error = 0 if cancelled else ctypes.get_last_error()
                    cancel_status = self.kernel32.WaitForSingleObject(
                        event, WRITE_CANCEL_WAIT_MS
                    )
                    if cancel_status != WAIT_OBJECT_0:
                        _ORPHANED_WRITES.append(
                            (self.kernel32, buffer, overlapped, event)
                        )
                        preserve_operation = True
                    detail = ""
                    if cancel_error not in (0, ERROR_NOT_FOUND):
                        detail = f"; cancellation failed with WinError {cancel_error}"
                    raise TimeoutError(
                        f"HID write timed out after {timeout_seconds:g} seconds{detail}"
                    )
                if status != WAIT_OBJECT_0:
                    raise ctypes.WinError(ctypes.get_last_error())
                if not self.kernel32.GetOverlappedResult(
                    device.handle,
                    ctypes.byref(overlapped),
                    ctypes.byref(written),
                    False,
                ):
                    raise ctypes.WinError(ctypes.get_last_error())

            if written.value != len(report):
                raise RuntimeError(
                    f"Short HID write: wrote {written.value} of {len(report)} bytes."
                )
        finally:
            if not preserve_operation:
                self.kernel32.CloseHandle(event)


def open_selected_device(index: int) -> tuple[WindowsHidApi, list[HidDevice], HidDevice]:
    api = WindowsHidApi()
    devices, blocked = api.open_matching_devices()
    if not devices:
        hp_control_blocked = any("&col06#" in path.lower() for path, _ in blocked)
        if hp_control_blocked:
            raise ControlInterfaceBusyError(
                "HP 460 control interface is busy. Close HP Accessory Center and retry."
            )
        raise RuntimeError("No connected HP 460 control interface was found.")
    if not 0 <= index < len(devices):
        for device in devices:
            api.close(device)
        raise RuntimeError(
            f"Device index {index} is invalid; found {len(devices)} device(s)."
        )
    return api, devices, devices[index]


def run_fn_lock(args: argparse.Namespace) -> int:
    current = args.state == "on"
    startup = current if args.startup is None else args.startup == "on"
    report = build_fn_lock_report(current=current, startup=startup)
    print(report.hex(" ").upper())
    if args.dry_run:
        return 0
    api, devices, selected = open_selected_device(args.device_index)
    try:
        api.write(selected, report)
    finally:
        for device in devices:
            api.close(device)
    print(
        "HP 460 Fn Lock set: "
        f"current={'on' if current else 'off'}, "
        f"startup={'on' if startup else 'off'}, "
        f"firmware=0x{selected.version:04X}"
    )
    return 0


def run_devices(_: argparse.Namespace) -> int:
    api = WindowsHidApi()
    devices, blocked = api.open_matching_devices()
    try:
        for index, device in enumerate(devices):
            print(
                f"[{index}] HP 460 control collection, firmware=0x{device.version:04X}, "
                f"usage={TARGET_USAGE_PAGE:04X}:{TARGET_USAGE:04X}"
            )
        if not devices:
            print("No available HP 460 control collection was found.")
        busy = sum(1 for path, _ in blocked if "&col06#" in path.lower())
        if busy:
            print(f"Busy HP 460 control collections: {busy}", file=sys.stderr)
    finally:
        for device in devices:
            api.close(device)
    return 0 if devices else 2


def run_collections(_: argparse.Namespace) -> int:
    api = WindowsHidApi()
    collections, blocked = api.matching_collections()
    for index, collection in enumerate(collections):
        print(
            f"[{index}] usage={collection.usage_page:04X}:{collection.usage:04X} "
            f"input={collection.input_length} output={collection.output_length} "
            f"feature={collection.feature_length} "
            f"firmware=0x{collection.version:04X}"
        )
    if blocked:
        print(
            f"Collections unavailable for read-only inspection: {blocked}",
            file=sys.stderr,
        )
    if not collections:
        print("No inspectable HP 460 HID collections were found.")
    return 0 if collections else 2


def run_capture_vendor(args: argparse.Namespace) -> int:
    if args.seconds is not None and args.seconds <= 0:
        raise RuntimeError("Capture duration must be greater than zero.")
    api = WindowsHidApi()
    collections, _ = api.matching_collections()
    candidates = [
        collection
        for collection in collections
        if (collection.usage_page, collection.usage, collection.input_length)
        == (0xFF00, 0x0001, REPORT_LENGTH)
    ]
    if not candidates:
        raise RuntimeError("No HP 460 FF00:0001 input collection was found.")
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one HP 460 FF00:0001 input collection; found {len(candidates)}."
        )
    print("Capturing read-only FF00:0001 reports. Press Ctrl+C to stop.")
    api.capture_input(candidates[0], args.seconds)
    return 0


def run_verify(_: argparse.Namespace) -> int:
    if os.name != "nt":
        raise RuntimeError("Key verification is only available on Windows.")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    names = TARGET_VKS
    previous = {vk: False for vk in names}
    print("Monitoring F-row, modifiers, native keys, and HP default events.")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            for vk, name in names.items():
                down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                if down != previous[vk]:
                    print(f"{name} {'DOWN' if down else 'UP'}", flush=True)
                previous[vk] = down
            time.sleep(0.005)
    except KeyboardInterrupt:
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Control HP 460 Fn Lock and inspect key-layer behavior."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    devices = subparsers.add_parser("devices", help="list matching control devices")
    devices.set_defaults(func=run_devices)

    collections = subparsers.add_parser(
        "collections", help="inspect all matching HID collections read-only"
    )
    collections.set_defaults(func=run_collections)

    capture_vendor = subparsers.add_parser(
        "capture-vendor",
        help="capture the input-only FF00:0001 vendor reports read-only",
    )
    capture_vendor.add_argument(
        "--seconds",
        type=float,
        help="stop automatically after this many seconds",
    )
    capture_vendor.set_defaults(func=run_capture_vendor)

    fn_lock = subparsers.add_parser("fn-lock", help="set current/startup Fn Lock")
    fn_lock.add_argument("state", choices=("on", "off"))
    fn_lock.add_argument("--startup", choices=("on", "off"))
    fn_lock.add_argument("--device-index", type=int, default=0)
    fn_lock.add_argument("--dry-run", action="store_true")
    fn_lock.set_defaults(func=run_fn_lock)

    verify = subparsers.add_parser(
        "verify", help="monitor target keys and hook-visible default events"
    )
    verify.set_defaults(func=run_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
