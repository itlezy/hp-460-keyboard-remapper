# Native-mode access investigation

Later live result: [vendor GATT handshake](live-vendor-transport.md) succeeds
after the keyboard is awake. This resolves transport availability for that
auxiliary route; it does not establish a native-mode flag setter.

## Result

The [native-mode behavior](native-mode-and-nuclear-options.md) remains supported
by original-ARM function tests. This follow-up narrows how it is selected but
does not provide a live setter. No keyboard command, GPIO operation, setting
change or firmware transfer was sent during this investigation.

Read-only Windows enumeration found zero paths containing the HP 460 product
identifier, zero matching collections and zero blocked matching collections.
This rules out merely mistaking an access-denied handle for a usable control
interface in that enumeration. It does not establish why the keyboard is
unavailable. No device paths or unique identifiers are saved in public reports.

## GPIO source confirmed with original instructions

The initialization path includes call `0x100039D6` to `0x100045F0`. The latter
configures and reads logical GPIO inputs `0x21`, `0x22` and `0x23`.
The audited sub-block starts at `0x1000464C`, calls the original GPIO helper
`0x1000E8D8` three times, and stores the first result into `0x20001BE0`.

The initialized GPIO-bank table is:

| RAM pointer | Register-bank base |
| --- | --- |
| `0x20001AC8` | `0x50000000` |
| `0x20001ACC` | `0x50000080` |

The helper reads input at bank base + `0x50`. Logical GPIO `0x21` selects
bank 1, bit 1, so the relevant input is bit `0x02` of `0x500000D0`.
This identifies a register bit, not a physical package pin or board pad.

`experiments/audit_native_mode_access.py` supplies all eight combinations of
the three GPIO input bits in an emulated peripheral register. Original code
always copies the `0x21` input to the flag. A write hook verifies that the store
occurs at `0x1000466E` for 1 or `0x10004672` for 0. No GPIO helper is stubbed.
Other initialization effects outside that sub-block are not tested.

## Ordinary settings are a separate path

The known DeviceSpecific application handler calls `0x10012B68`. Its recognized
setting IDs are 0, 2, 3 and 8; the function does not implement a generic
address/value write operation. ID 0 extracts bit 2 of its supplied value and
calls `0x1000DB90`, which updates the LED state and invokes `0x1000FB34`.
That final setter writes `0x20001BE9`, the Fn Lock byte, rather than
`0x20001BE0`, the F-row polarity flag.

The audit executes the actual settings callback with IDs 0–63, byte values
0–255 and both initial native-mode flag values: **32,768 cases**. None writes
the native-mode byte; all ID-0 cases produce the expected separate Fn Lock
value. Only LED calls at `0x10003E40` and `0x1000400C` are stubbed. A memory
write hook covers overlapping stores, not merely changes in the final value.

This is a negative result for this callback. It is not an exhaustive test of
the complete DeviceSpecific parser, every profile/host state, malformed
packets, every HID interface or every ROM routine.

## Additional vendor transfer family

The firmware contains another command dispatcher at `0x1001054C`, reached
through a wrapper at `0x1000270C` and through BLE characteristic handling near
`0x10008690`–`0x10008704`. The latter compares characteristic UUIDs `FF01` and
`FF02`. Those UUIDs must not be confused with identically numbered HID usage
pages; the mapping to each Windows collection has not been established.

Recovered dispatcher branches include:

| Command | Handler / observed role |
| --- | --- |
| `10` | `100031BC`, enables protocol state and replies |
| `18`, `22`, `25` | queued via `10010838` to `100027F4`, transfer/data control |
| `23` | `1000319C`, query through an installed callback |
| `27` | `10003688`, transfer initialization and metadata reply |
| `28` | `10003070`, resets transfer bookkeeping |
| `29` | invokes an installed callback with a byte argument |
| `2A` | `10003B1C`, callback result reply |
| `2B` | `1000335C`, callback query with a 32-bit argument |
| `2C` | `10003894`, another callback result reply |

All command values and addresses in that table are hexadecimal. Labels are
analyst descriptions, not recovered original function names.

The 32-bit argument in command `2B` initially looked interesting for memory
access. The traced callback at `0x10003A74` uses it as a zero/nonzero selection
for device information; it does not dereference it as an arbitrary address.
Mode 0 instead selects `0x10003CE0`, which ignores the argument and calls the
fixed device-information routine at `0x10003BC0`. No read/write primitive was
established from that argument.

Executing initializer `0x1001070C`, then all three modes of `0x10010668`, leaves
the payload callback at context `0x20001B6C + 0x54` pointing to `0x1000F099`.
Its function entry is `0x1000F098`. Original adapter execution with an intercepted
transport sink emits HP `0xCF5` transfer-start and `0xCF7` payload packets.
These are the command classes used by the already-analyzed HP OTA receiver.
The initializers and adapter do not write the native-mode flag.

This is not proof of the full end-to-end transfer or authentication behavior
of every alternate path. It means a second protocol name/characteristic alone
is not evidence of a separate unsigned flasher. No transfer initialization or
payload was sent to hardware.

## Next concrete work

1. Trace the remaining vendor feature wrappers and their indirect callbacks,
   including packet-length checks and the addresses/ranges accepted by any
   storage or diagnostic operations. Identify a real memory-access mechanism
   before constructing a live address/value packet. The ROM implementations
   behind low-address call tables are not contained in the public application.
2. If a candidate is found, reproduce its read/write behavior in emulation.
   First establish a read of `0x20001BE0`; then establish a one-byte RAM write
   without flash/GPIO side effects. Finding a setter for another byte or an
   internal storage-read function does not meet this requirement.
3. Once a live route is established and the control interface is available,
   back up settings, read the current flag, and perform a temporary native-mode
   test with a demonstrated restoration procedure. Actual key tests come then:
   plain/modified F-keys, navigation, ordinary/ISO keys, overlapping presses,
   sleep, reconnect and power cycle.
4. If software access remains unavailable, identify the GPIO net from exact
   controller/board information before proposing a hardware strap modification.
   No pad or resistor has been identified, and no electronics work is requested
   of the user at this stage.

## Reproduce

With optional Unicorn installed and the exact public Ash 1.2 image:

```powershell
PYTHON.EXE experiments/audit_native_mode_access.py C:\images\Ash_1200.FW
```

The generated audit and proprietary disassembly are kept under ignored
`local-research/`. The script opens no HID device and modifies no input file.
