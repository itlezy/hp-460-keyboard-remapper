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

## Hidden slots

HPAC's embedded Ash QML defines only these visible assignments:

```text
buttonId 0 through 11 = F1 through F12
```

The device's config reply says `nbProgrammableButtons:24`. HPAC's generic
`setButtonProgram` backend searches descriptors by `(buttonId, host,
pressType)` and is not restricted to the 12 QML entries.

Related HP keyboard QML, particularly the Ivy layout, uses this sequence:

```text
12: top-row special key
13: Insert
14: Home
15: Page Up
16: Delete
17: End
18: Page Down
```

On Ash, the top-row special key after F12 is Stamp/Print Screen. Programming
slot 12 changed only that physical key, experimentally confirming the sequence.
Slots 14, 17, 15, and 18 then produced native Home, End, Page Up, and Page Down
respectively.

## Native-key bytecode

HPAC was temporarily used to assign native F12 to visible slot 11. Its packet
contained a four-byte program:

```text
F8 00 45 00
```

`45` is the standard USB HID Keyboard/Keypad usage for F12. Replacing it with
the standard usages for Print Screen and the navigation keys produced the
expected native events. The temporary F12 assignment was then cleared through
HPAC.

## Why not AutoHotkey?

With Fn Lock on, the target keys did not all enter Windows through the same
keyboard path:

- Print Screen generated a firmware `Win+Space` macro;
- Home appeared as consumer usage `0x0192` / `VK_LAUNCH_APP2`;
- End became ordinary Esc, indistinguishable from the physical Esc key;
- Page Up and Page Down generated brightness consumer usages and were absent
  from the low-level keyboard hook.

Raw Input can observe more devices/usages but cannot suppress the original
events system-wide. A kernel interception/filter driver would be invasive and
would still struggle to distinguish End from real Esc after firmware has
already collapsed both into the same event.

Programming the keyboard's own hidden slots fixes the events at their source.

## Why not firmware replacement?

The public firmware images helped confirm protocol structure but were not
needed for the fix. Replacing firmware would add signing, bootloader,
calibration-data, and brick risks without improving the result. This project
does not flash or patch firmware.

## Tooling used during research

- HPAC's hidden packet logger
- static Qt resource extraction for embedded QML
- Rizin/Cutter with the Ghidra decompiler plugin
- Python scripts using `pefile` and Capstone for targeted inspection
- Windows low-level/async key-state verification
- static analysis of the public Ash firmware images

No HP executable or firmware content is included in this repository.
