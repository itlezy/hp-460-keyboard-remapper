# Live auxiliary vendor transport

## What is now established

The paired HP 460 exposes its auxiliary protocol directly through a Bluetooth
vendor service. A live enable/read/reset test succeeded, matching the original
ARM handler. This is transport access, **not a native-mode flag setter**.
The flag at `0x20001BE0` has still not been read or written on hardware.

No native-key remap, Fn Lock change, stored program write, firmware upload,
Windows driver change, adapter reset or pairing change was performed in this
test. The auxiliary protocol state was temporarily enabled and then reset.

## Connection and backup

While the physical keyboard was unavailable, Windows still showed its paired
Bluetooth entry and parent HID service, but no HP child HID collections. A
standard uncached Device Information service query returned `Unreachable`,
with connection status `Disconnected`. This was not an access-denied HID handle.

After the user woke the keyboard on the correct host channel, the HP control
interface returned. A command-0 program backup succeeded:

```json
{"capacity": 24, "host": 1, "flags": 24, "records": []}
```

A backup after the live GATT handshake returned the same values. Raw backups
and Bluetooth query reports stay in ignored `local-research/`; public files
contain no device addresses, serials, host names or HID paths. Physical input
from the HP keyboard is distinct from typing through RDP; RDP input does not
exercise the HP matrix.

## HID feature reads and a rejected write

Standard `HidD_GetFeature` calls succeeded for all three feature collections:

| Usage page | Report ID | Report length | Result |
| --- | --- | --- | --- |
| `FF00` | 5 | 21 | ID plus 20 zero bytes |
| `FF01` | 8 | 21 | ID plus 20 zero bytes |
| `FF02` | 9 | 21 | ID plus 20 zero bytes |

A fixed auxiliary enable/reset attempt through `HidD_SetFeature`, report 9,
was rejected with Windows error 122 (`ERROR_INSUFFICIENT_BUFFER`). It did not
produce a confirmed handshake. That error does not prove the vendor protocol
is unavailable through other transports; direct GATT subsequently worked.
No arbitrary command/address probing was used to obtain that result.

`experiments/vendor_feature_probe.py` defaults to reads. Each operation runs
in a bounded child process. Its optional experimental HID handshake exposes
only the fixed auxiliary enable/reset pair; direct GATT is the demonstrated
working route on this PC.

## Direct Bluetooth GATT access

Windows native WinRT APIs found service
`0000FF00-0000-1000-8000-00805F9B34FB` with these characteristics:

| UUID suffix | Properties observed | Windows AttributeHandle observed |
| --- | --- | ---: |
| `FF01` | Read, WriteWithoutResponse, Write, Notify | 89 |
| `FF02` | Read, WriteWithoutResponse, Write | 92 |
| `FF04` | Read, Write, Indicate | 94 |

These are Bluetooth UUIDs, not identically numbered HID usage pages. The tools
select UUIDs rather than hardcoding these handles. No write was made to FF02
or FF04. The firmware's vendor characteristic declarations and handlers near
`0x10008690`–`0x10008704` agree with the FF01/FF02 protocol routing.

Python launches a hidden Windows PowerShell helper for the built-in WinRT
projection; no Python WinRT package or driver installation is needed. This
was tested in the current research-PC session. Standard-user permissions on
the work laptop remain untested.

## Verified temporary handshake

The original command dispatcher at `0x1001054C` accepts `10` to enable the
auxiliary protocol, calling `0x100031BC`. Its reply builder at `0x10006CF8`
produces `0E 02 10 00`. Command `28` calls `0x10003070`, clearing auxiliary
transfer bookkeeping and disabling that protocol. It is not a hardware reset.

Before sending either command, isolated execution of the original handlers
confirmed the expected auxiliary-state transitions and no writes to the
native-mode/Fn-Lock byte range. No transfer-start or transfer-data command was
executed in that replay or sent during the live handshake.

The complete live exchange on FF01 was:

```text
read                  -> 21 zero bytes
write with response   -> 10
read                  -> 0E 02 10 00
write with response   -> 28
read                  -> 21 zero bytes
```

Both writes returned `Success`. The full enable acknowledgement matched the
emulator, and the final read confirmed the inactive protocol response.
The sanitized exchange is in
[`captures/auxiliary-handshake-sanitized.json`](../captures/auxiliary-handshake-sanitized.json).

`experiments/ble_auxiliary_handshake.py` requires an initially zero-filled reply
before a normal test. It resets auxiliary state in a `finally` block and
checks the resulting read. `--reset-only` is a separate recovery operation.
An optional fixed information-query mode is provided for commands `23` and
`2C`; neither is an arbitrary address read/write interface. Protocol or host
process failure must not be mistaken for successful cleanup.

## Verified information queries

A subsequent `--query-info` run succeeded on the same FF01 characteristic:

```text
enable 10 -> 0E 02 10 00
query  23 -> 0E 09 23 00 00 00 00 04 B0 EB FE
query  2C -> 0E 03 2C 00 00
reset  28 -> 21 zero bytes
```

Every write returned `Success`, and the final inactive read confirmed cleanup.
The information response contains firmware value `0x04B0` (1200), consistent
with Ash 1.2. The remaining fields are not all decoded. The original `2C`
callback at `0x10003B6C` returns the auxiliary mode byte; its live value is 0.
This is **not** a read of native-mode byte `0x20001BE0` or Fn Lock.

The sanitized exchange is in
[`captures/auxiliary-information-sanitized.json`](../captures/auxiliary-information-sanitized.json).

## WinRT buffer interoperability detail

The returned buffer is a COM object. PowerShell's generic `.Length` fallback
can report 1 without reading the actual WinRT buffer length. That produced
an initially truncated host-side display. The corrected reader queries the
native `IBuffer` length before copying bytes. The real inactive value has 21
bytes and the real enabled acknowledgement has four.

The two interfaces have different identifiers and vtables:

- `IBuffer`: `905A0FE0-BC53-11DF-8C49-001E4FC686DA`, IInspectable interface.
- `IBufferByteAccess`: `905A0FEF-BC53-11DF-8C49-001E4FC686DA`, IUnknown interface.

The implementation reads length through the former and buffer storage through
the latter, with a 512-byte bound. Confusing those interfaces caused a host
helper crash during development; it was corrected before the successful live
handshake. That crash was a host-side read-helper failure, not a device flash.

## Reproduce

Keep the keyboard awake on this host channel. These commands operate in
isolation and do not register startup tasks or keyboard hooks:

```powershell
# Standard read-only feature/metadata probes.
PYTHON.EXE experiments/vendor_feature_probe.py
PYTHON.EXE experiments/ble_vendor_read.py --read-values

# Changes only temporary auxiliary protocol state, then verifies reset.
PYTHON.EXE experiments/ble_auxiliary_handshake.py --output local-research\auxiliary-test.json

# Fixed information queries, followed by the same verified auxiliary reset.
PYTHON.EXE experiments/ble_auxiliary_handshake.py --query-info

# Explicit auxiliary reset if a prior test ended without confirmed cleanup.
PYTHON.EXE experiments/ble_auxiliary_handshake.py --reset-only
```

The native-mode investigation still needs an actual flag-access mechanism.
Additional diagnostic queries and any proposed memory operation must be traced
and validated separately; successful transport access does not supply them.
