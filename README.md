# HP 460 Keyboard Remapper

Dependency-free Windows tooling for the **HP 460 Multi-Device Bluetooth
Keyboard** (`VID 03F0`, `PID 814A`). It uses the same vendor HID collection as
HP Accessory Center (HPAC) to:

- keep Fn Lock enabled, including after power-on;
- make the physical Stamp/Print Screen key send native Print Screen;
- make Home, End, Page Up, and Page Down send their native keyboard usages;
- restore those keys to their HP firmware defaults;
- enable HPAC's hidden developer packet logger without discarding its binary
  settings trailer.

The navigation fix is stored in the keyboard and was verified after turning the
keyboard off and on. It does not require AutoHotkey, a kernel filter, a custom
driver, or modified firmware.

## The problem

With Fn Lock enabled, the tested keyboard produced these surprising events:

| Physical key | HP firmware default seen by Windows |
| --- | --- |
| Stamp / Print Screen | `Win+Space` macro |
| Home | Consumer usage `0x0192` / `VK_LAUNCH_APP2` |
| End | `Esc` |
| Page Up | Consumer Brightness Up (`0x006F`) |
| Page Down | Consumer Brightness Down (`0x0070`) |

AutoHotkey cannot fix the whole set cleanly. In particular, the End key becomes
an ordinary Esc event, indistinguishable from the real Esc key, and brightness
events do not pass through the ordinary low-level keyboard hook.

HPAC reports 24 programmable slots for this keyboard but exposes only slots
`0` through `11` (F1 through F12) in its UI. This project programs the hidden
slots `12`, `14`, `15`, `17`, and `18` directly.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- An HP 460 keyboard paired over Bluetooth
- No third-party Python packages

Administrator rights were not required on the tested machine. Organization
policy or endpoint security software may impose additional restrictions.

## Quick start

Keep a second keyboard connected during the first test. Fully close HP
Accessory Center and any keyboard-remapping software before running commands.

```powershell
# Confirm that the vendor control collection is available.
PYTHON.EXE hp460.py devices

# Preview every report without opening or changing the keyboard.
PYTHON.EXE hp460.py nav plan

# Keep F1-F12 as ordinary function keys now and after power-on.
PYTHON.EXE hp460.py fn-lock on

# Program native Print Screen/Home/End/Page Up/Page Down.
PYTHON.EXE hp460.py nav apply

# Monitor only those five Windows virtual keys while testing.
PYTHON.EXE hp460.py verify
```

Power-cycle the keyboard and test again. The mappings should persist.

To clear these custom programs and return to HP's firmware behavior:

```powershell
PYTHON.EXE hp460.py nav restore
```

Operate on a single key with `--key`:

```powershell
PYTHON.EXE hp460.py nav apply --key end
PYTHON.EXE hp460.py nav restore --key end
```

If multiple HP 460 keyboards are connected, select one with
`--device-index N`.

## Optional installation

Running the scripts directly is sufficient. An editable installation adds the
`hp460` and `hpac-dev-mode` commands:

```powershell
PYTHON.EXE -m pip install -e .
hp460 nav plan
```

## Documentation

- [Work-laptop procedure](docs/work-laptop.md)
- [HPAC developer mode and packet log](docs/hpac-dev-mode.md)
- [Vendor HID protocol](docs/protocol.md)
- [Reverse-engineering notes](docs/reverse-engineering.md)
- [Firmware notes and hashes](docs/firmware.md)
- [Sanitized HPAC startup capture](captures/hpac-startup-sanitized.txt)
- [Raw reports and verification dump](captures/reports.txt)

## Safety scope

The utility opens only the HID collection matching all of the following:

- HP `VID 03F0`, `PID 814A`;
- usage page/usage `FF05:0001`;
- 21-byte input and output reports.

It does not disable, restart, remove, or reinstall any PnP device. It does not
flash firmware. HPAC must be closed because it can hold the vendor collection.

Firmware and HPAC binaries are not redistributed. The repository contains only
original code, public download metadata, technical observations, and sanitized
captures.

## Tested configuration

- HP 460 Multi-Device Bluetooth Keyboard
- HP codename: `Ash`
- USB/Bluetooth HID identity: `VID 03F0`, `PID 814A`
- reported device version: `04B0`
- firmware text version: `1.20.0` / `1200`
- HP Accessory Center: `2.21.4522.0`

Other firmware revisions may behave differently. Always run `nav plan` first.

## License

MIT
