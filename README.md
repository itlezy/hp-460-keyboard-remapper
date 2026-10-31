# HP 460 Keyboard Protocol Research

Dependency-free Windows tooling and reverse-engineering notes for the **HP 460
Multi-Device Bluetooth Keyboard** (`VID 03F0`, `PID 814A`).

## Current status

Newest reassessment: [goal, evidence, and current plan](docs/current-plan.md).
The selected path is a two-halfword firmware patch that makes the navigation
cluster native while preserving F1-F12 modifiers; it requires a confirmed
safe flash and recovery procedure before anything is written.

Newest finding: [stock native-mode flag and stronger options](docs/native-mode-and-nuclear-options.md).
A separate RAM flag plus Fn Lock off makes the unmodified transformer emit
native F1–F12 and navigation usages in 19,456 offline ARM runs. No live setter
for that flag is known yet. Access to this native path is the preferred new
research target; the sampled companion below remains a fallback.
The [access audit](docs/native-mode-access-audit.md) confirms its GPIO source;
32,768 known-settings callback cases do not alter it. Live access remains open.

[Live vendor transport](docs/live-vendor-transport.md): a direct Bluetooth
auxiliary enable/read/reset handshake now works on hardware. The protocol is
disabled again afterward; no native-mode RAM write has been established.

Current direction: [software-only companion and temporary F-row mask program](docs/software-only-plan.md).
A running helper is acceptable; hardware tools and opening the keyboard are
outside the current plan. A bounded program passes original-ARM emulation for
all F-row combinations, but live timing, lifecycle and Windows input delivery
are not established. No live simulator program has been sent.

Latest analysis: [device signature proof and next hardware experiment](docs/device-validation-and-next-test.md).
Two offline patch candidates pass ARM function emulation; the preferred one
replaces the special matrix keycodes with native usages and discards the media
layer. HPAC's outer firmware signatures are now independently verified, and a
modified image fails that check. A physical keyboard flash dump and a usable
installation/recovery path are still pending.

The later [scanner and local-loader analysis](docs/scan-and-dev-loader.md)
confirms the fixed flash lookup and an HPAC development flag that can skip
the outer signature check for local `.FW2` loading. The subsequent device
analysis identifies a different RSA-2048 key and verifies the inner application
signature using original ARM instructions. The native matrix candidate fails
that check. Hardware debug/recovery access and flash readback remain unresolved;
ordinary `.FW2` upload is not a demonstrated installation route.

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

HPAC's Ash UI exposes only F1–F12. Ash 1.2.0 nevertheless contains a 16-by-8
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

A controlled alternative test did establish that Fn Lock off makes the full
navigation cluster native and that a host-side `Media_Prev` to F4 remap
preserves physical Shift. The trace was `Shift down`, `F4 down/up`, `Shift up`.
A simple AHK prototype handled F1–F6 but did not reliably suppress the
firmware-generated shortcut chords used by F7–F12, so it is not a finished
solution.

## What works

- Enumerating every HP 460 top-level HID collection read-only
- Capturing the input-only vendor collection without writing to the keyboard
- Enabling/disabling current and startup Fn Lock
- Monitoring native target keys and hook-visible HP default events
- Safely enabling HPAC's hidden developer packet logger
- Building and decoding HPAC button-program packets for research
- Preserving HPAC's non-JSON settings trailer
- Reproducing the Ash 1.2.0 image map, runtime-data decompression, 16-by-8
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

# Capture protocol/update responses from the input-only vendor collection.
PYTHON.EXE hp460.py capture-vendor --seconds 15

# Preview the persistent Fn Lock report without opening the keyboard.
PYTHON.EXE hp460.py fn-lock on --dry-run

# Enable Fn Lock now and at keyboard startup.
PYTHON.EXE hp460.py fn-lock on

# Observe native keys and hook-visible default events.
PYTHON.EXE hp460.py verify

# Analyze a separately downloaded public firmware image without flashing it.
PYTHON.EXE firmware_analysis.py C:\path\to\Ash_1200.FW

# Print the exact-hash native matrix candidate manifest, without writing a file.
PYTHON.EXE firmware_candidate.py C:\path\to\Ash_1200.FW
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

- [Goal, evidence, and current plan](docs/current-plan.md)
- [VM interpreter call and the physical-modifier question](docs/vm-interpreter-call.md)
- [Work-laptop Fn Lock procedure](docs/work-laptop.md)
- [HPAC developer mode and packet log](docs/hpac-dev-mode.md)
- [Vendor HID protocol and slot experiment](docs/protocol.md)
- [Reverse-engineering notes](docs/reverse-engineering.md)
- [Firmware notes and hashes](docs/firmware.md)
- [Firmware follow-up, signature analysis and readout plan](docs/firmware-followup.md)
- [Device signature verification, Italian/US layout and next hardware test](docs/device-validation-and-next-test.md)
- [Current software-only plan and combined-mask prototype](docs/software-only-plan.md)
- [Consumer-only programs and their overlap limitation](docs/consumer-bridge.md)
- [Decision record and next plan](docs/decision-plan.md)
- [Known-incomplete AHK experiment](experiments/fn-off-ahk-prototype.ahk)
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
