# Firmware and HPAC follow-up

## Required behavior

F1–F12, Print Screen, Home, End, Page Up and Page Down must emit their native
keyboard usages with no Fn press. Shift, Ctrl and Alt must retain normal
behavior. Media actions, emoji, brightness and every other special action may
be removed. A resident AHK remapper is not the target solution.

## Evidence and acquisition status

- Public HP images Ash 1.0.0, 1.1.0 and 1.2.0 have been downloaded and hashed.
- The Ash 1.2.0 matrix, layer transformer and native converter were disassembled.
- HPAC 2.21.4522.0 was examined through PE strings, references, import names and
  x64 function disassembly. Pseudocode below is analyst reconstruction, not
  recovered original C++ source.
- A physical full-flash dump of the keyboard has **not** been obtained.
- No hardware flash, erase, bootloader-entry or unknown diagnostic command was
  sent during this follow-up. Only the existing read-only HID collection scan
  accessed the device.

Generated local reports are in `../local-research/`, ignored by Git. They
include six HPAC functions, three Ash disassembly windows, signature verification
and emulator results. They are static code reports, not a physical flash dump.

## Two candidate changes tested in emulation

The existing four-byte branch candidate redirects virtual navigation actions
to the native insertion block. F1–F12 keep their existing native path with Fn
Lock on. It passes the single-key function test for all 256 modifier masks.

The user's revised requirement allows a simpler alternative: change the 19
special matrix entries at `0x10013822` to ordinary USB keyboard usages.

```text
0100..010B -> 003A..0045  F1..F12
010C       -> 0046        Print Screen
010D       -> 0049        Insert
010E       -> 004C        Delete
010F       -> 004A        Home
0110       -> 004D        End
0111       -> 004B        Page Up
0112       -> 004E        Page Down
```

This candidate replaces 19 two-byte matrix entries, at their actual row/column
positions. It removes their special-action identity before layer processing.
Fn Lock can remain on, but these inputs no longer depend on its setting.

`experiments/validate_native_branch.py` applies both candidates only to memory
and executes the original ARM key-transformer instructions using Unicorn.
The matrix test reads its input keycodes back from the modified matrix.

Result: **29,184 successful function runs**: stock baseline and branch candidate
with Fn Lock on/Fn released, plus the matrix candidate in all four Fn Lock/Fn
states. Each scenario tests 19 keys against all 256 modifier masks.

The checks require the expected native usage, exactly one inserted key, no
special-key mask, no direct-dispatch call and an unchanged modifier byte. The
function must return normally. Stock special dispatch is stubbed, so its
specific consumer/macro output is not modeled by this harness.

Limits: default OS mode, one key at a time, no physical scanner, Bluetooth,
bootloader, rollover, sleep or hardware execution. This establishes that the
code change is plausible; it does not establish flashability or full operation.
The matrix candidate is now preferred because retaining any media layer is
unnecessary.

## HPAC signature verification is now identified

The examined HPAC executable has SHA-256:

```text
9a9bbf2d871463ac411f059836e2e551a3031ceb47a212adbac8ee6a13b8e488
```

Relevant preferred-image virtual addresses:

| Address | Observed role |
| --- | --- |
| `0x1400F4390` | parses firmware file and selects payload record |
| `0x1400E1F00` | enumerates length/type records |
| `0x1400E1D00` | validates payload and signed trailer |
| `0x1400E55A0` | big-integer exponentiation wrapper and RSA padding decode |
| `0x1400E57F0` | SHA-256 implementation (initial constants and digest verified) |
| `0x140623AD0` | embedded public-key descriptor |
| `0x140625000` | 2048-bit public modulus in little-endian limbs |
| `0x140624ED8` | public exponent, decimal 37 |
| `0x1400FE330` | packet receiver, including remote update errors |

The outer file format is:

```text
record_length:u32le, record_type:u8, payload_length:u32le,
payload[payload_length], signature_container_length:u32le,
signature[256]
```

Analyst reconstruction of the signature check:

```text
digest = SHA256(payload)
decoded = RSA_public_operation(signature, modulus, exponent=37)
message = decode_HP_RSA_padding(decoded)
accept only when the recovered digest agrees with digest
```

All three public Ash releases pass independent Python verification. Their
recovered outer RSA blocks begin `00 02`, with a 32-byte recovered message
equal to SHA-256(payload). This is an observed custom use of RSA padding;
do not label it conventional RSASSA-PKCS1-v1_5 without qualification.

Ash 1.2.0 contains:

| Region | File location | Meaning |
| --- | --- | --- |
| record 0 | `0x00000`, length `0x160A8` | signed firmware payload |
| payload | `0x00009`, length `0x15F9B` | nested image package |
| nested image | `0x0000D`, length `0x15E93` | ARM application and data |
| inner 256-byte block | `0x15EA4` | separate validation data; meaning unresolved |
| outer signature | `0x15FA8` | verifies using the embedded HPAC key |
| record 1 | `0x160A8`, length `0x10D` | empty metadata payload with its own signature |
| record 1 signature | `0x160B5` | also verifies using the embedded HPAC key |

Changing the four branch bytes makes the outer payload digest disagree with
the existing signature. The inner block does not decode using that same key.
Its format/key and the device's validation behavior remain unresolved.

The packet receiver also handles distinct remote Protocol, Flash, Security,
Format and FWData errors. This shows that the host supports a device-side
security rejection; it does not prove which of those checks Ash performs.

## Online updater reference: useful, with a format mismatch

The upstream fwupd PixArt plugin includes an HPAC variant and uses vendor
usage pages `FF00` (notifications), `FF01` (retransmission) and `FF02` (OTA).
These correspond to the otherwise unexplained collections on this keyboard.

The reviewed implementation has version/checksum queries and upload commands,
but no full-flash readback operation. Its expected HPAC footer magic is absent
at the documented position in all three downloaded Ash images. It therefore
cannot be assumed to accept these files. No fwupd commands were sent to the
keyboard.

Primary references:

- [PixArt BLE updater source](https://chromium.googlesource.com/chromiumos/third_party/fwupd/+/refs/heads/stabilize-16267.43.B/plugins/pixart-rf/fu-pxi-ble-device.c)
- [PixArt firmware container parser](https://chromium.googlesource.com/chromiumos/third_party/fwupd/+/refs/heads/stabilize-16267.43.B/plugins/pixart-rf/fu-pxi-firmware.c)
- [Command enum](https://chromium.googlesource.com/chromiumos/third_party/fwupd/+/refs/heads/stabilize-16267.43.B/plugins/pixart-rf/fu-pxi.rs)

## Concrete next plan

1. Scanner lookup is now confirmed: it reads a fixed 16-by-8 flash table directly.
   No RAM table indirection is present in that lookup. See the later
   [scanner and development-loader report](scan-and-dev-loader.md).
2. Trace Ash's OTA dispatch and inner-block validator. Determine whether those
   routines execute in the application, copied RAM, or controller ROM. Compare
   them with the documented PixArt command values; inspect any readback command
   before using it.
3. The local `.FW2` development loader is now traced: its inclusion flag disables
   the outer signature check when loading a local file. An x64 emulator replay
   confirms the isolated checker accepts the edited payload in this mode.
   Device validation remains separate. See the later report for addresses.
4. If a bounded memory-read command is found, read a small known application
   range twice, compare it against public Ash bytes, then expand to a full dump.
   Save device-specific pairing/configuration data privately, outside Git.
5. If software readback is unavailable, identify the board/controller and SWD
   pads using clear board photographs or physical inspection. Read flash with a
   compatible probe if debug access is open. Do not use an unlock procedure
   that requires mass erase: it would destroy the backup we need.
6. Validate the preferred matrix candidate against the actual dump, including
   multiple simultaneous keys and every relevant state, then establish the
   applicable upload/debug recovery procedure before a hardware write.

A native firmware change remains the first choice. A Windows HID filter is a
fallback if installation of modified firmware cannot be made practical. More
AHK hotkey variations are not part of this plan.

## Reproduction

Research-only dependencies: `pefile`, `capstone`, `unicorn`. They are optional;
the ordinary Fn Lock utility still uses only the Python standard library.
The follow-up used pefile 2024.8.26, Capstone 5.0.9 and Unicorn 2.1.4.

```powershell
PYTHON.EXE experiments/inspect_signed_container.py C:\path\HPAccessoryCenter.exe C:\path\Ash_1200.FW
PYTHON.EXE experiments/validate_native_branch.py C:\path\Ash_1200.FW
PYTHON.EXE experiments/export_static_research.py C:\path\HPAccessoryCenter.exe C:\path\Ash_1200.FW --rizin C:\path\rizin.exe
```

All three commands operate on local files and never open a HID device.
