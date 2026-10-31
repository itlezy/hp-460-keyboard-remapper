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

HPAC reports 24 programmable button entries, but experimental programs written
to entries `12–23` did not control these physical keys on the Ash/460 firmware.
The records were accepted, returned in multipart configuration replies, and
then cleared. The project deliberately does not expose a misleading
`nav apply` command.

An earlier apparent success was disproved by controlled layer tests. The
corrected negative result and raw evidence are preserved here because they
substantially narrow the next phase of research.

## What works

- Enumerating only the HP `FF05:0001` vendor HID collection
- Enabling/disabling current and startup Fn Lock
- Monitoring native target keys and hook-visible HP default events
- Safely enabling HPAC's hidden developer packet logger
- Building and decoding HPAC button-program packets for research
- Preserving HPAC's non-JSON settings trailer

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

# Preview the persistent Fn Lock report without opening the keyboard.
PYTHON.EXE hp460.py fn-lock on --dry-run

# Enable Fn Lock now and at keyboard startup.
PYTHON.EXE hp460.py fn-lock on

# Observe native keys and hook-visible default events.
PYTHON.EXE hp460.py verify
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

The next research phase should inspect the other vendor collections and/or a
device-aware HID/filter path before considering firmware changes.

## Documentation

- [Work-laptop Fn Lock procedure](docs/work-laptop.md)
- [HPAC developer mode and packet log](docs/hpac-dev-mode.md)
- [Vendor HID protocol and negative slot experiment](docs/protocol.md)
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
