# Firmware notes

HP publishes Ash firmware images under its HPAC firmware directory. These
files are not redistributed here.

| Version | Public URL | Length | SHA-256 |
| --- | --- | ---: | --- |
| 1.0.0 | `https://ftp.hp.com/pub/hpac/FW/Ash_1000.FW` | 92,225 | `514B88BB2DAC7FF54D818EE593732E3F07A6A48A3CB8485DE8628B90D8C590A6` |
| 1.1.0 | `https://ftp.hp.com/pub/hpac/FW/Ash_1100.FW` | 92,265 | `B749A0BB1FBA465CA96E31E865D0B0D424183461ECFA2345CB9ECD389C265A75` |
| 1.2.0 | `https://ftp.hp.com/pub/hpac/FW/Ash_1200.FW` | 90,549 | `6E490AE055B9DFC9AA9E750F8693BD563A24EC2F060A84F12D250996A0E77C2E` |

The images contain ARM Cortex-M Thumb code. The updater container has a
13-byte prefix before the Cortex vector table. The exact 1.2.0 mapping is:

```text
virtual address = 0x10000000 + file offset - 13
file offset      = virtual address - 0x10000000 + 13
```

The initial stack pointer is `0x20006FE8`, and the reset vector is
`0x10000249` (Thumb code begins at `0x10000248`). For Rizin, map the raw file
at `0x0FFFFFF3`:

```powershell
RIZIN.EXE -a arm -b 16 -m 0x0FFFFFF3 -e asm.cpu=cortexm Ash_1200.FW
```

## Startup data layout

The C runtime table at `0x100143F8` describes three initializers:

| Source | Destination | Size | Operation |
| ---: | ---: | ---: | --- |
| `0x1001442C` | `0x20000000` | `0x1564` | direct copy |
| `0x10015990` | `0x20001564` | `0x0C3C` | compact zero/back-reference decompression |
| — | `0x200021A0` | `0x4E48` | zero fill |

The decompressor is at `0x10001B7C`. `firmware_analysis.py` reproduces it and
also accounts for functions that execute from copied RAM. For example, the
runtime function at `0x200003F5` has an inspectable flash alias at
`0x10014820`.

## The 24-way custom-program engine

Immediately before the programmable-button data, Ash 1.2.0 contains a
13-by-10 little-endian physical-matrix table at `0x10013820`. Most entries are
ordinary USB keyboard usages. Nineteen entries instead use a contiguous
firmware-private range:

| Virtual code | Matrix action | Physical meaning |
| ---: | ---: | --- |
| `0x0100–0x010B` | `0–11` | F1–F12 positions |
| `0x010C` | `12` | Stamp / Print Screen |
| `0x010D` | `13` | Insert |
| `0x010E` | `14` | Delete |
| `0x010F` | `15` | Home |
| `0x0110` | `16` | End |
| `0x0111` | `17` | Page Up |
| `0x0112` | `18` | Page Down |

Each value in `0x0100–0x0112` occurs exactly once. Subtracting `0x0100`
produces the switch index used by the matrix-layer converters. It does not by
itself prove that the same number is an HPAC-programmable physical position.

The custom-program filter at runtime `0x200003F5` runs before the default
special-key dispatcher. It loops over 24 configuration entries and uses the
table at `0x100139A6` to translate each entry to a bit in the incoming special
key mask. The table is:

```text
18 00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F 10 11 12 13 14 15 16 17
```

The first byte is the count; the remaining bytes form an identity map. Thus,
if physical bit 14 reaches this path, configuration entry 14 is the program
that can consume it.

The default dispatcher at `0x1000F2D4` uses a 24-entry inline jump table. The
most relevant cases are:

| Entry | Case address | Compiled default |
| ---: | ---: | --- |
| 12 | `0x1000F3B6` | language-switch / Stamp macro |
| 13 | `0x1000F3E2` | Insert, HID usage `0x49` |
| 14 | `0x1000F3EC` | Home, HID usage `0x4A` |
| 15 | `0x1000F3F6` | Page Up, HID usage `0x4B` |
| 16 | `0x1000F400` | Delete, HID usage `0x4C` |
| 17 | `0x1000F40A` | End, HID usage `0x4D` |
| 18 | `0x1000F414` | Page Down, HID usage `0x4E` |

The command-1 packet handler at `0x1000A738` writes directly into the same
active-profile container that the runtime filter searches. A request host of
zero is replaced with `active_profile + 1`; it is not an inactive namespace.
This rules out the earlier host-field hypothesis.

The controlled live experiment that stored programs in entries `12–23` did
not alter the five target keys on either layer. Later control-flow analysis
explains the result: the matrix action IDs are transformed by separate native,
special, and direct dispatchers. The configurable 24-bit mask is not the
normal Fn-Lock-on direct navigation route. HP's product material advertises
only F1–F12 because those are the physical positions its UI supports.

## Layer-path model

The report transformation at `0x1000F4DC` reads the 24-bit special-key mask,
then calls the thunk at `0x10001CB8`. That thunk jumps directly to the custom
filter at runtime `0x200003F5`. Only the bits not consumed by a custom program
continue to the default dispatcher at `0x1000F2D4`.

This explains an important asymmetry in the observed behavior. Fn Lock does
not simply exchange HID usages after dispatch; it selects among distinct code
paths. With Fn Lock on and Fn not held, virtual navigation actions reach the
hardcoded switch at `0x100038B4`. Its relevant cases are:

| Matrix action | Physical key | Direct output |
| ---: | --- | --- |
| `14` | Delete | keyboard Delete `0x4C` |
| `15` | Home | consumer App2 `0x0192` |
| `16` | End | keyboard Esc `0x29` |
| `17` | Page Up | brightness increment `0x006F` |
| `18` | Page Down | brightness decrement `0x0070` |

The native converter at `0x10004284` maps the same matrix inputs to Delete
`0x4C`, Home `0x4A`, End `0x4D`, Page Up `0x4B`, and Page Down `0x4E`. These
are immediate constants in executable code, not a writable profile table.
The user's prior Fn-Lock-off experiment also shows why self-programming F1–F12
is not an equivalent workaround: the simulated program does not compose with a
physically held Shift, so `Shift+F4` still requires Fn.

The same direct dispatcher makes the Fn-Lock-off host-remap alternative more
complicated than six media-key remaps. The complete F-row outputs are:

| Physical key | Direct special-layer output |
| --- | --- |
| F1–F6 | Mute, Volume Down, Volume Up, Previous, Play/Pause, Next |
| F7 | Left GUI + keyboard usage `0x33` (`Win+;`) |
| F8 | keyboard F13, usage `0x68` |
| F9 | keyboard Scroll Lock, usage `0x47` |
| F10 | Left GUI + I |
| F11 | Left GUI + L |
| F12 | Left Ctrl + F |

The F7–F12 chords are assembled directly into the keyboard report. A simple
AHK remap catches F1–F6 but does not reliably suppress the synthetic modifier
sequence for the remaining keys.

## Minimal offline patch candidate

The direct-layer call site contains an existing native-conversion block at
`0x1000747E`. Redirecting only the `0x010C–0x0112` branch to this block would
leave F1–F12 on their normal direct path while making Stamp through Page Down
native. The proposed two-halfword patch is:

| Virtual address | File offset | Original | Candidate | Meaning |
| ---: | ---: | --- | --- | --- |
| `0x10007420` | `0x742D` | `09 D0` | `2D D0` | Stamp: branch to native block |
| `0x10007422` | `0x742F` | `20 46` | `2C E0` | Insert–Page Down: branch to native block |

This is a static candidate, not a flashable release. It has not passed the
container's unknown authentication checks, has not been run on hardware, and
must not be flashed without a full backup and a proven recovery route.

## Updater authentication boundary

Later HPAC analysis proved that two of these regions are outer RSA signature
blocks and identified the exact nested layout. See the
[firmware follow-up](firmware-followup.md) for the verified record offsets,
public-key operation, digest checks and function emulator results. The first
inner block remains unresolved. The historical size-based observations below
are retained as the starting point for that analysis.

The image is neither encrypted nor packed as a whole, but the 1.2.0 tail has
three distinct 256-byte high-entropy regions, at file offsets:

```text
0x15EA4..0x15FA4
0x15FA8..0x160A8
0x160B5..0x161B5
```

Two are preceded by a `04 01 00 00` length marker. Their cryptographic format
has not yet been proven, so the analyzer deliberately calls them
"authentication-sized opaque blocks," not verified RSA signatures. Their
layout is enough to make a stock OTA patch unsafe to assume: changing code is
easy, producing an image accepted by every validation stage is not.

Observed firmware strings and descriptors included:

- product text for HP 460 and HP 475;
- PixArt BLE keyboard/controller text;
- `QueryPacketResponse`, `PayloadPacket`, `AckPacket`;
- `BatteryQueryPacket`, `BTReply`, `ButtonReplyPacket`;
- keyboard report ID 1;
- consumer report ID 3;
- system-control report ID 4;
- vendor feature report ID 5;
- vendor page `FF05` report ID 6 with 20-byte input/output payloads;
- additional vendor reports 7, 8, and 9.

This confirms that the 21-byte `06 ...` Windows reports are implemented by the
keyboard firmware itself. HPAC is a user-mode client of that firmware protocol,
not a front end for a proprietary kernel driver.

The target direct-layer navigation outputs are compiled into executable code.
Capturing an HPAC-generated native-key program established the bytecode used
by exposed programmable F-row buttons, but writing that bytecode to entries
`12–23` did not connect those entries to the direct navigation path.

Do not flash a modified image to pursue this remap without first identifying
the update validation, controller debug access, full-flash backup, and a tested
recovery path. This utility does not flash or patch firmware.

## Reproduce the static findings

Download the public HP image separately, then run:

```powershell
PYTHON.EXE firmware_analysis.py C:\path\to\Ash_1200.FW
```

The command validates the container length and known SHA-256, prints the exact
memory map and vector, expands the runtime initializer, locates the opaque tail
blocks, and decodes the physical matrix, virtual-key IDs, button map, and jump
targets. It is read-only and never opens a keyboard.

## External references

- [HP 460 product page](https://www.hp.com/us-en/shop/pdp/hp-460-multi-device-bluetooth-keyboard-7n7b8aa-aba)
  (HP describes F1–F12 programming)
- [HP 460 product datasheet](https://cdn.cs.1worldsync.com/syndication/feeds/hp/inline-content/P9/5/4/C/2/0/54C20D26C405B04B31DAD63A5D5862085808C430_source.PDF)
  (HP describes 12 programmable F1–F12 buttons, not navigation-key remapping)
- [Microsoft keyboard and mouse HID client drivers](https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/keyboard-and-mouse-hid-client-drivers)
  (Microsoft's supported architecture for value-added keyboard behavior is a
  filter driver layered over the standard HID keyboard stack)
- [Microsoft HID driver samples](https://learn.microsoft.com/en-us/windows-hardware/drivers/samples/human-interface-devices--hid--driver-samples)
  (official starting points for HID filtering and virtual HID work)
- [PAR2801 reverse-engineering materials and datasheet index](https://github.com/AlexKryukoff/K530-QMK-BLE-OpenRGB/tree/sn32_master_openrgb/Redragon_K530_Keyboard)
  (useful comparison material for the PixArt Cortex-M0 BLE family; not proof
  that the HP board exposes the same recovery wiring)
- [PixArt PAR2801 comparison manual](https://fcc.report/FCC-ID/2AIPB-PAJ2801UA-40/3083972.pdf)
  (documents Cortex-M0 and two-pin SWD support for a related PixArt part; it
  does not identify the exact HP controller or prove that SWD is exposed or
  unlocked on this keyboard)
