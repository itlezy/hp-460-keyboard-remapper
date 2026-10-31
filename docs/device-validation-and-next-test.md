# Device validation and the next hardware experiment

## Decision

One HP keyboard is now an acceptable experimental target even if recovery
fails. That changes the acceptable risk; it does not make a known signature
failure a useful flash experiment. No upload, erase, reset or firmware write
was performed in this investigation.

The normal OTA receiver in public Ash 1.2.0 installs a non-null RSA key and
checks a signature over the application. The native matrix candidate fails
that check. HPAC's local `.FW2` option bypasses only its outer host signature
check. It does not disable this device check.

The next useful experiment is to identify the physical controller and its
debug/recovery access. Unsigned firmware installation remains unproven.

## Inner signature: new evidence

Earlier reports correctly left the inner 256-byte block unidentified. It can
now be identified using the device's own key, rather than HPAC's different
outer-container key.

| Ash 1.2.0 address | Observed role |
| --- | --- |
| `0x1000F1EE` | loads configuration base `0x20001DEC` before the setter call |
| `0x1000FAAC` | setter installs base + `0x10C` at global `0x20001FBC` |
| `0x20001EF8` | initialized runtime RSA key descriptor: 2048 bits, 256-byte block |
| `0x20001DF4` | device modulus, 64 little-endian 32-bit limbs |
| `0x20001DEC` | public exponent bignum, value 37 |
| `0x1000F8A6`–`0x1000F8C2` | copies the key into OTA context `0x20003898` + `0x54` |
| `0x1000F778` | packet wrapper calls the receiver with that context |
| `0x100064CC` | OTA packet receiver |
| `0x100065C0` | selects signed versus unsigned handling using context + `0x54` |
| `0x100067F4` | calls RSA decoder `0x10009EA4` with the installed key |
| `0x1000682A`–`0x1000683C` | type-2 block must decode to 32 bytes matching application SHA-256 |
| `0x10006816` | verification failure path calls storage callback with offset -3 |
| `0x10006860` | successful validation path calls storage callback with offset -2 |

The initial decompressed value at `0x20001FBC` is zero. That is **not** the
final initialized state: the setter and context initialization above install
the key before normal receiver use. Inferring unsigned operation from that
initial zero would have been incorrect.

`experiments/validate_device_signature.py` executes the original setter,
context initialization block and RSA decoder, including the firmware's actual
modular exponentiation and padding parser. Only heap allocation and release
are substituted. Independent Python big-integer arithmetic agrees.

For the exact stock Ash 1.2.0 file:

```text
application length: 0x15E93
inner signature container: file 0x15EA0, length 260 (u32 length + signature)
signature: file 0x15EA4, length 256
recovered padding: 00 02 ... 00 <32-byte digest>
recovered digest:
e5ff134cee16fcf128f6bfa7644263183d053f19e2a7defb43003313a9eda773
```

That digest equals SHA-256 of the application bytes starting at file `0xD`.
It differs from SHA-256 of the patched application. Replaying the receiver's
actual digest-comparison instructions reaches success `0x10006860` for stock
and rejection `0x10006816` for the matrix candidate.

This is static analysis plus isolated function emulation, not a live device
rejection, a full boot/transfer simulation or a controller ROM dump. It is
strong evidence that the normal update path rejects this candidate. It does
not prove secure boot, permanently locked debug, or the absence of other
bootloader/diagnostic routes.

## Flash activity happens before the final signature result

The receiver's storage callback is `0x1000ABB8`. Its offset parameter selects:

| Offset | Observed handling |
| --- | --- |
| -1 | checks transfer length, initializes storage state and calls a page-operation wrapper at offset zero |
| nonnegative | buffers the first `0x200` bytes; submits later data through the write wrapper |
| -2 | recomputes application SHA-256 from buffered first bytes and mapped storage; compares, writes buffered first bytes, then calls the finalization wrapper |
| -3 | marks failure and calls the page-operation wrapper over the declared image range in `0x1000` steps |
| -4 | calls the activation/reset wrapper and then spins |

The receiver invokes the write callback while computing SHA-256, before its
RSA/digest comparison. The page-operation wrapper `0x1000F07A` reaches
`0x10011BBC`, which dispatches through the ROM table pointer at `0x780`.
The write wrapper `0x1000F594` reaches `0x10011BE4`, then the ROM table pointer
at `0x78C`. Finalization reaches the pointer at `0x79C`; activation/reset reaches
the pointer at `0x9B0`.

The page operations are consistent with erasure and the transfer writes are
consistent with firmware staging, but the underlying ROM and physical flash
layout are not in the downloaded application. Dual-bank rollback, bootability
after rejection and recovery are not established. A rejected upload cannot
be treated as a harmless validation-only query.

## Offline candidate and Italian keyboard / Windows US

`firmware_candidate.py` accepts only the exact public Ash 1.2.0 source hash.
It changes 19 two-byte entries: F1–F12, Print Screen, Insert, Delete, Home,
End, Page Up and Page Down. All other file bytes and matrix entries are
preserved. It never opens a device, overwrites its source, or overwrites
existing candidate/manifest files.

Real-image checks confirmed the exact patch footprint, unchanged non-target
entries/source, rejection of altered or truncated inputs, and refusal to
overwrite either output. All 14 repository tests passed. The research exporter
also reran the 29,184 transformer cases, all 256 scanner cases, the HPAC local
flag replay and the device-signature replay successfully.

```text
candidate size: 90549 bytes
changed bytes: 38
candidate SHA-256:
800bc35e25a92b3382cb1f8805cf45e54ce30d9189273c5dfcf0e24d5bb0bda9
```

The candidate passes the previously documented scanner and modifier tests.
It invalidates both the outer and inner signatures. It is an offline research
artifact, not an installable release.

Italian legends and Windows US layout do not change the desired HID usages
for these keys. Windows keeps interpreting ordinary letter/punctuation keys
using the selected US layout. The extra ISO key and other ordinary matrix
entries are untouched by the patch. That preservation is relative to the
public image, not proof that the entire public image matches every byte of
this particular keyboard's installed firmware or stored regional settings.

HP's [device list](https://ftp.hp.com/pub/hpac/deviceList.txt) lists one Ash
1.2.0 image for the 460/475 family, with no regional variant in that entry.
Physical board identification and private configuration backup still matter
before constructing a programmer image. The OTA file includes containers
and signatures; do not write that whole file directly to flash.

## Next steps

Update: [manufacturer board photos and opening status](board-and-opening.md)
are now available for regulatory model TPA-S001K. Use those for the initial
controller/debug investigation; opening the user's unit is not required just
to obtain an initial board view. A full screw/clip removal procedure is not
yet verified.

1. With batteries removed, inspect the experimental keyboard's underside model
   and regulatory identifiers, then both sides of the PCB. Obtain readable
   controller and flash chip markings, board revision and test-pad labels.
   Keep serial numbers, Bluetooth addresses and other unique labels private.
2. Identify the exact chip's pinout, voltage, SWD/debug protection and boot-mode
   options. A related PixArt part supports SWD; that does not establish access
   on this board. Select a compatible probe only after identification.
3. If debug access is available, read flash/configuration twice and compare the
   dumps. Locate the active application, bootloader and device-specific data.
   A debug unlock requiring erase would be a separate destructive experiment,
   not a backup procedure. Accepted brick risk permits considering it once
   the exact behavior and required replacement image are known.
4. Determine whether direct application programming is also subject to a boot
   signature check. If it is writable and can boot modified code, patch the
   actual application's matrix and preserve configuration/pairing regions.
   If debug is locked, investigate the identified controller's recovery loader
   or a specific diagnostic bypass. No such bypass is currently established.
5. Program one experimental keyboard through the demonstrated route. Verify
   all target keys with modifiers, ISO/ordinary keys under Windows US,
   simultaneous keys, reconnect, power cycle and operation on a second PC
   with HPAC/AHK absent.

There is no extra requirement to preserve media actions. There is also no
promise that buying another keyboard will overcome a locked debug port or
boot-time signature enforcement.

## Reproduce without accessing hardware

```powershell
# Standard library only; omitting --output prints the patch manifest.
PYTHON.EXE firmware_candidate.py C:\path\Ash_1200.FW
PYTHON.EXE firmware_candidate.py C:\path\Ash_1200.FW --output local-research\Ash_1200.FW2

# Optional Unicorn dependency; uses the exact stock public image.
PYTHON.EXE experiments/validate_device_signature.py C:\path\Ash_1200.FW
```

Generated firmware and proprietary disassembly remain in Git-ignored
`local-research/`. The repository contains reproduction scripts and sanitized
findings, not proprietary binaries or personal/device-specific dumps.
