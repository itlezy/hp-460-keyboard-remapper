# Consumer-only programs: useful finding, incomplete standalone approach

The user accepts a running Python, PowerShell, AHK or compiled helper. Admin
experiments are acceptable on the research PC; the work laptop has no admin
access. No electronics or case opening is part of this software investigation.

## Why the old native-key program loses modifiers

The program `F8 00 3D 00` is a bit-packed VM instruction, not an ordinary native
keymap entry. Its low five opcode bits select instruction 24. Original ARM
interpreter execution produces these callback arguments:

```text
keyboard: 00 00 3D 00 00 00 00 00
keyboard: 00 00 00 00 00 00 00 00
```

The first byte is the modifier byte, zero here. The report callback at
`0x1000ABAC` forwards a keyboard report through the transport; it does not
merge the physically held modifier byte. This explains why an HPAC simulated
F4 is different from native F4. Changing that program to F13/F24 still emits
the same zero-modifier keyboard reports.

## A separate consumer-only instruction

Opcode 27, encoded as `FB` with the auto-release and literal-blob flags, emits
a two-byte consumer report through `0x1000AAF8`. For example:

```text
FB 24 02 00 -> consumer 0224 (Browser Back), then consumer 0000 (release)
```

It emits no keyboard-report callback. The physical keyboard modifier byte is
unchanged in the original transformer/filter/interpreter replay. The firmware
consumer descriptors at `0x100134A4` and `0x10013772` advertise a 16-bit array
with usage maximum `0x029C`, covering all the proposed markers.

With Fn Lock off, the navigation keys are already native. F1–F6 already emit
six distinct consumer events. A possible bridge would change only F7–F12:

| F-key | Consumer usage | Windows event / proposed bridge source |
| --- | --- | --- |
| F7 | `0224` AC Back | Browser_Back |
| F8 | `0225` AC Forward | Browser_Forward |
| F9 | `0227` AC Refresh | Browser_Refresh |
| F10 | `0226` AC Stop | Browser_Stop |
| F11 | `0221` AC Search | Browser_Search |
| F12 | `022A` AC Bookmarks | Browser_Favorites |

A helper could map the twelve consumer events to F1–F12 while preserving
Windows' current modifiers. This avoids the earlier Win/Ctrl shortcut macros
for single-key operation. It requires a helper on each PC; it is not a
standalone firmware fix or a modified firmware installation.

Primary references for these usage names and Windows input mappings:

- [USB-IF HID Usage Tables](https://www.usb.org/sites/default/files/hut1_21_0.pdf)
- [Microsoft keyboard input overview and HID mapping table](https://learn.microsoft.com/en-us/windows/win32/inputdev/about-keyboard-input)
- [Microsoft SendInput integrity restrictions](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)

## Held-key prototype and a real overlap limitation

`experiments/consumer_programs.py` builds four-byte tap programs and 26-byte
held programs. The latter use VM variable 0 (current special-key mask),
arithmetic/conditional branches and a 20 ms yield to emit release only after
the corresponding physical bit clears. They need multi-report configuration
packets. The packet framer is offline-tested, not live-validated for these new
programs.

The original transformer at `0x100072F8` and custom filter at `0x10014820`
successfully select all six programs in Fn-Lock-off mode. The VM initializer
is `0x100055FA`, interpreter `0x10005656`, bit reader `0x10005E12` and blob
reader `0x10005D7E`. The filter invokes the ordinary program initializer at
`0x1000A6D8`; this is not a flash-patching path.

The 6,144-case replay covers six keys, two program variants, all 256 physical
modifier bytes, and no/all unrelated special-key bits. It checks the selected
consumer usage, release timing in emulator ticks, absence of keyboard-report
callbacks and preservation of the physical report modifier byte.

However, only one custom program runs at once. At `0x10014862`–`0x10014870`,
the filter skips selecting another program while the current one is active.
A separate overlap replay confirms that holding F7 then pressing F11 leaves
bit `0x0400` for the old default dispatcher. That could invoke the original
shortcut. The 6,144 single-program cases do not establish reliable rollover.

**This consumer-only bridge is therefore not the finished solution.** The
AHK companion is retained as an isolated lab prototype, with global bindings
and no startup registration. It was parsed with `--check`; no hotkeys were
activated. Do not test the old F11 action without first establishing the
configuration/guard. Changing `.ahk` syntax alone does not fix this firmware
serialization limit.

The subsequent [software-only plan](software-only-plan.md) investigates a
temporary program that consumes all F-row bits and reports their combined
mask to a device-specific helper, avoiding the second-program selection path.

## Reproduce

```powershell
# Offline manifest and emulation; optional Unicorn dependency for replay.
PYTHON.EXE experiments/consumer_programs.py
PYTHON.EXE experiments/validate_program_vm.py C:\path\Ash_1200.FW
PYTHON.EXE experiments/validate_consumer_programs.py C:\path\Ash_1200.FW

# Parse only. Does not register hotkeys or modify keyboard configuration.
AutoHotkey64.EXE /ErrorStdOut experiments/consumer-bridge.ahk --check

# Query only; backup may contain personal macros, so keep it Git-ignored.
PYTHON.EXE experiments/button_transport.py --output local-research\button-backup.json
```

The query could not open the control interface during the unattended locked-PC
session. No backup or configuration write was made. Physical modifier, repeat,
reconnect and Windows behaviour remain untested for these new candidates.
