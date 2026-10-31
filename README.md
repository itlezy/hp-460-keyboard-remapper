# HP 460 Keyboard Protocol Research

Dependency-free Windows tooling and reverse-engineering notes for the **HP 460
Multi-Device Bluetooth Keyboard** (`VID 03F0`, `PID 814A`).

## Current status

The Fn Lock control is proven and works both immediately and at keyboard
startup:

```powershell
PYTHON.EXE hp460.py fn-lock on
```

The desired primary-layer remap is **not solved yet**. With Fn Lock on, the
tested keyboard behaves as follows:

| Physical key | No Fn | Fn held |
| --- | --- | --- |
| Stamp / Print Screen | firmware `Win+Space` macro | native Print Screen |
| Home | Consumer `0x0192` / `VK_LAUNCH_APP2` | native Home |
| End | Esc | native End |
| Page Up | Brightness Up (`0x006F`) | native Page Up |
| Page Down | Brightness Down (`0x0070`) | native Page Down |

HPAC's Ash UI exposes only F1–F12. Ash 1.2.0 nevertheless contains a 13-by-10
physical-matrix table with virtual keycodes `0x0100–0x0112`: F1–F12 followed by
Stamp, Insert, Delete, Home, End, Page Up, and Page Down. Deeper disassembly
shows that these virtual codes are layer inputs, not automatically equivalent
to HPAC program IDs.

An earlier live experiment wrote and read back programs in IDs `12–18`, but
the five tested keys did not change on either layer. That negative observation
is preserved, but the later matrix disassembly disproves its former
interpretation that the stored records necessarily control those matrix
positions. The normal Fn-Lock-on navigation path is a separate hardcoded
dispatcher, and the user's earlier Fn-Lock-off self-remap also established
that HPAC-simulated F keys do not preserve `Shift+F4` as required. The project
therefore does not expose a premature `nav apply` command.

## What works

- Enumerating only the HP `FF05:0001` vendor HID collection
- Enabling/disabling current and startup Fn Lock
- Monitoring native target keys and hook-visible HP default events
- Safely enabling HPAC's hidden developer packet logger
- Building and decoding HPAC button-program packets for research
- Preserving HPAC's non-JSON settings trailer
- Reproducing the Ash 1.2.0 image map, runtime-data decompression, 13-by-10
  physical keymap, and 24-way special-key dispatcher offline

The tool does not disable/restart PnP devices and does not modify firmware.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- An HP 460 keyboard paired over Bluetooth
- No third-party Python packages

## Usage

Fully close HP Accessory Center before accessing the vendor collection.

```powershell
# Confirm the control interface and firmware version.
PYTHON.EXE hp460.py devices

# Inspect every HP 460 top-level HID collection without write access.
PYTHON.EXE hp460.py collections

# Preview the persistent Fn Lock report without opening the keyboard.
PYTHON.EXE hp460.py fn-lock on --dry-run

# Enable Fn Lock now and at keyboard startup.
PYTHON.EXE hp460.py fn-lock on

# Observe native keys and hook-visible default events.
PYTHON.EXE hp460.py verify

# Analyze a separately downloaded public firmware image without flashing it.
PYTHON.EXE firmware_analysis.py C:\path\to\Ash_1200.FW
```

Optional editable installation:

```powershell
PYTHON.EXE -m pip install -e .
hp460 fn-lock on
```

## Why AutoHotkey is insufficient for the complete fix

Home and the firmware macro can be intercepted in user mode, but:

- End becomes an ordinary Esc event, indistinguishable from the physical Esc
  key on the same keyboard;
- brightness usages do not traverse the ordinary low-level keyboard hook;
- Raw Input can identify devices/usages but cannot suppress the original event
  system-wide.

The keyboard-side decision is now identified. With Fn Lock on and Fn not held,
the firmware sends the navigation cluster through a hardcoded dispatcher at
`0x100038B4`; its cases produce App2, Esc, and brightness usages. The native
converter at `0x10004284` contains the desired Home/End/Page Up/Page Down
usages. A firmware patch is mechanically small, but the public updater
container ends in three 256-byte authentication-sized blocks, so an ordinary
edited image is not expected to pass the stock updater.

## Documentation

- [Work-laptop Fn Lock procedure](docs/work-laptop.md)
- [HPAC developer mode and packet log](docs/hpac-dev-mode.md)
- [Vendor HID protocol and slot experiment](docs/protocol.md)
- [Reverse-engineering notes](docs/reverse-engineering.md)
- [Firmware notes and hashes](docs/firmware.md)
- [Sanitized HPAC startup capture](captures/hpac-startup-sanitized.txt)
- [Raw reports and corrected experiment log](captures/reports.txt)

## Tested configuration

- HP codename: `Ash`
- `VID 03F0`, `PID 814A`
- reported device version: `04B0`
- firmware text version: `1.20.0` / `1200`
- HP Accessory Center: `2.21.4522.0`

Firmware and HPAC binaries are not redistributed. Captures in this repository
are sanitized.

## License

MIT
