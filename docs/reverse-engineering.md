# Reverse-engineering notes

## HP Accessory Center

The examined HP Accessory Center release was `2.21.4522.0`, a native Qt 6 Store
application. Static analysis and packet logging showed that it:

- enumerates ordinary Windows HID interfaces;
- opens the `FF05:0001` vendor collection directly;
- reads battery, Bluetooth-host, timeout, and button configuration packets;
- writes Fn Lock and button-program packets;
- exposes a hidden packet logger in developer mode.

The executable imports APIs including `HidD_SetOutputReport`,
`HidD_GetPreparsedData`, `HidP_GetCaps`, and `WriteFile`. The installed keyboard
used standard Microsoft HID drivers; no HP filter was required.

HPAC contains device classes named `HPACAsh400`, `HPACAsh405`, `HPACAsh460`,
and `HPACAsh475`. The tested 460 identifies itself with codename `Ash`.

## The 24-entry engine and the hidden Ash keys

HPAC's embedded Ash QML exposes only button IDs `0–11`, corresponding to F1
through F12. The keyboard's configuration response nevertheless reports
`nbProgrammableButtons:24`, and HPAC's generic `setButtonProgram` backend can
address descriptors by `(buttonId, host, pressType)` without enforcing the 12
QML entries.

Related HP keyboard QML, particularly an Ivy layout, uses IDs `12–18` for a
top-row special key, Insert, Home, Page Up, Delete, End, and Page Down. A first
controlled Ash experiment appeared to reject the matching layout:

- Ash accepted native-key programs in IDs `12`, `14`, `15`, `17`, and `18`;
- a configuration query returned those records exactly;
- none of the five corresponding physical keys changed on either Fn layer;
- assigning F13 through F24 to every ID from `12` through `23` likewise
  produced no matching physical event.

Subsequent firmware analysis established that this is a real 24-entry engine,
not merely storage capacity. Its entry-to-special-bit table is an identity map,
and the command handler updates the same active-profile container consulted at
keypress time. The default switch contains native Insert/Home/Page
Up/Delete/End/Page Down cases at entries `13–18`.

The Ash physical-matrix table at `0x10013820` contains every virtual code from
`0x0100` through `0x0112` exactly once. Codes `0x010C–0x0112` represent Stamp,
Insert, Delete, Home, End, Page Up, and Page Down. These are matrix action
numbers, however, not proof of matching HPAC program slots. The experiment was
cleaned up by clearing IDs `12–23`; the keyboard then returned an empty custom
configuration.

The custom filter is reached through a direct thunk: `0x1000F4DC` calls
`0x10001CB8`, which transfers control to runtime `0x200003F5`, before calling
the default special dispatcher. The matrix transformer at `0x100072F8` makes a
separate Fn/Fn-Lock decision. With Fn Lock on and Fn not held, navigation
actions call the hardcoded direct dispatcher at `0x100038B4`; Home becomes
consumer `0x0192`, End becomes Esc, and Page Up/Down become brightness usages.
The native converter at `0x10004284` contains the desired HID usages.

This also retracts the proposed Fn-Lock-off self-map workaround. It uses the
same simulated HPAC program mechanism the user already tested, and that path
does not preserve a physically held Shift for `Shift+F4`.

## HID collection probe

Windows exposes nine top-level collections for the tested keyboard:

```text
0001:0002  mouse                    input 8
000C:0001  consumer control         input 3
0001:0080  system control           input 2
FF00:0001  vendor feature           feature 21
FF05:0001  HP control               input/output 21
0001:0006  keyboard                 input 12, output 2
FF00:0001  vendor input             input 21
FF01:0001  vendor feature           feature 21
FF02:0001  vendor feature           feature 21
```

A read-only capture of the `FF00:0001` input collection produced no reports
while Stamp, Home, End, Page Up, and Page Down were pressed once with Fn Lock
on. It therefore does not provide a passive pre-conversion matrix stream in
that state; it is more likely used for protocol or updater responses. This
negative result means a Windows filter would see the already-converted
keyboard/consumer usages unless another diagnostic mode is found.

## Native-key bytecode

HPAC was temporarily used to assign native F12 to visible button ID 11. Its
packet contained a four-byte program:

```text
F8 00 45 00
```

`45` is the standard USB HID Keyboard/Keypad usage for F12. This proves the
native-key bytecode and the write format for an exposed programmable button.
It does not prove that arbitrary configuration IDs are connected to physical
keys. The temporary F12 assignment was cleared through HPAC.

## Why AutoHotkey is insufficient for the complete fix

With Fn Lock on, the target keys do not all enter Windows through the same
keyboard path:

- Print Screen generates a firmware `Win+Space` macro;
- Home appears as consumer usage `0x0192` / `VK_LAUNCH_APP2`;
- End becomes ordinary Esc, indistinguishable from physical Esc to a normal
  keyboard hook;
- Page Up and Page Down generate brightness consumer usages and are absent
  from the low-level keyboard hook.

AutoHotkey can address some of these cases, but not all of them cleanly and
device-specifically. Raw Input can identify devices and usages, but it cannot
suppress the original events system-wide. A device-aware kernel filter could
intercept lower in the stack, although distinguishing End from physical Esc
depends on whether the reports remain distinct at that level.

## Why not firmware replacement yet?

Public firmware images now expose the dispatcher and runtime data layout, but
the updater tail also contains three 256-byte authentication-sized opaque
blocks. Replacing firmware therefore adds validation, bootloader,
calibration-data, and brick risks. There is not yet enough evidence that a
modified image can be accepted or recovered safely. This project does not
flash or patch firmware.

## Productive next directions

- Repeat one ID `12–18` write with a known-supported short-press program,
  drain the full reply, reconnect/power-cycle, test both layers, and clear it.
- Capture and decode reports from the additional vendor collections (report
  IDs 7, 8, and 9) while exercising both layers.
- Correlate host/press-type values with HPAC's multi-host and long-press code.
- Identify the Fn Lock/layer decision that turns virtual matrix codes into the
  configurable special-key mask.
- Identify the exact PixArt controller/package and non-destructive debug pads;
  obtain a full backup and prove recovery before attempting any flash write.
- Prototype a device-specific HID/filter interception only if the pre-HID
  reports retain enough information to distinguish the target keys.

## Tooling used during research

- HPAC's hidden packet logger
- static Qt resource extraction for embedded QML
- Rizin/Cutter with the Ghidra decompiler plugin
- Python scripts using `pefile` and Capstone for targeted inspection
- Windows low-level/async key-state verification
- read-only enumeration of every HP 460 top-level HID collection
- static analysis of the public Ash firmware images

No HP executable or firmware content is included in this repository.
