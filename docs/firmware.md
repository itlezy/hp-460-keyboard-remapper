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

The important limitation is earlier in the pipeline. On the tested Ash/460,
programs stored in entries `12–23` did not intercept the five physical keys on
either layer. Therefore the generic 24-way engine and its navigation defaults
exist, but the Ash/460 scan path does not present those tested keypresses as
the corresponding configurable mask bits. HP's own product material likewise
advertises only F1–F12 as programmable.

## Updater authentication boundary

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

The target navigation behavior is compiled into code, not held in a simple
plaintext user keymap. Capturing an HPAC-generated native-key program
established the bytecode used by exposed programmable buttons, but writing
that bytecode to other accepted configuration IDs did not alter the five
target physical keys.

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
blocks, and decodes the button map and jump targets. It is read-only and never
opens a keyboard.

## External references

- [HP 460 product page](https://www.hp.com/us-en/shop/pdp/hp-460-multi-device-bluetooth-keyboard-7n7b8aa-aba)
  (HP describes F1–F12 programming)
- [PAR2801 reverse-engineering materials and datasheet index](https://github.com/AlexKryukoff/K530-QMK-BLE-OpenRGB/tree/sn32_master_openrgb/Redragon_K530_Keyboard)
  (useful comparison material for the PixArt Cortex-M0 BLE family; not proof
  that the HP board exposes the same recovery wiring)
