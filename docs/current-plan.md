# Goal, evidence, and current plan

This is the single entry point for where the HP 460 keyboard work stands. It
states the goal, what has been proven, the remaining paths, the tooling, and
the next steps. It contains no personal details, device addresses, serials,
host names, or machine paths.

## Goal

Make the HP 460 behave like a normal keyboard:

- F1-F12 send native F1-F12, including Shift/Ctrl/Alt combinations, with no
  Fn key involved.
- Stamp, Insert, Delete, Home, End, Page Up, and Page Down send their native
  usages with no Fn key involved.
- Fn is needed only for the alternate media/brightness actions.

The user does not care about the Fn Lock state itself; the requirement is
standard keyboard behavior with working modifier combinations.

## What has been established

### Firmware structure

- Public Ash 1.2.0 image is mapped offline: 16-by-8 physical matrix, 24-entry
  special-key dispatcher, and the layer transformer at `0x100072F8`.
- The transformer reads the F-row polarity byte at `0x20001BE0` to choose
  native F-key insertion versus alternate dispatch.
- A native converter and insertion block exists at `0x1000747E` (with the
  converter at `0x10004284`).
- With Fn Lock on, the navigation cluster is handled by a hardcoded direct
  dispatcher at `0x100038B4`; it is not reachable through configurable
  programs or commands.

The polarity byte and Fn Lock select the following unmodified behavior:

| `0x20001BE0` | Fn Lock | F1-F12 | Navigation |
| --- | --- | --- | --- |
| 0 | off | alternate actions | native |
| 0 | on | native | alternate actions |
| 1 | off | native | native |
| 1 | on | alternate actions | alternate actions |

The desired row is `flag=1` plus Fn Lock off. Emulation covers all 19 target
keys and all 256 modifier bytes in that row, confirming native usages are
inserted into the normal physical report with the modifier byte preserved.

### Live results

- Fn Lock on/off control works both immediately and at startup.
- With Fn Lock on, the inverted navigation cluster is: Stamp -> language
  macro, Home -> consumer App2, End -> Esc, Page Up -> brightness up,
  Page Down -> brightness down.
- With Fn Lock off, the navigation cluster is native, but F1-F12 become
  alternate actions or generated shortcut chords.
- Stored programs for entries 12-23 are accepted and read back but do not
  change the hardcoded Fn-Lock-on navigation path.

### The polarity flag has no software setter

- The only writer of byte `0x20001BE0` is the startup GPIO sampler, which
  copies logical GPIO `0x21` (register `0x500000D0`, bit 1) into the flag.
- A settings-callback audit over 32,768 cases writes only the Fn Lock byte at
  offset `+9`, never the polarity byte.
- A complete classification of all 18 literal references to `0x20001BE0`
  confirms no command-driven writer to byte `+0`. Writes exist only at
  offsets `+1`, `+5`, `+9`, `+0xA`, `+0xD`, `+0xE`, and `+0x28`.

### The VM read bug is not a memory-access primitive

- The program-VM bit reader checks the upper bound but not the lower bound,
  allowing a negative cursor to read before the program buffer.
- A live temporary notification test confirmed the negative fetch works and
  leaves the stored program table unchanged.
- However, VM execution follows the cursor, and the instruction set has no
  indirect load or store opcode. All writes are to the VM register file or
  fixed context offsets. This is therefore a read-only input-buffer bug, not
  arbitrary RAM read/write, and it does not reach the polarity flag.

### Rejected approaches

- HPAC-style "Function Lock off + remap F1-F12 to themselves" is rejected:
  the remap emits a synthetic zero-modifier F-key, so Shift+F4 cannot carry
  the Shift. This is structural to the custom-program path.
- Host-side remapping is incomplete: with Fn Lock on, End is indistinguishable
  from Esc, and F7-F12 generate firmware shortcut chords.

## Paths

### A. Firmware patch (selected)

Redirect Stamp through Page Down to the existing native insertion block while
leaving F1-F12 on their current native path. The candidate is two halfwords:

```text
VA 0x10007420 / file 0x742D: 09 D0 -> 2D D0
VA 0x10007422 / file 0x742F: 20 46 -> 2C E0
```

This preserves modifiers and makes the navigation cluster native with Fn Lock
still on. The open work is making the flash itself safe: the public updater
container is signed, and a recovery route must be established before writing.

### B. Hardware strap

Set the logical GPIO `0x21` strap so the firmware boots with `0x20001BE0 = 1`,
then set Fn Lock off. This gives the same normal behavior without flashing,
but requires board identification and physical modification.

### Dead ends

- No command-driven setter for `0x20001BE0`.
- No arbitrary RAM read/write through the VM.
- No host-only filter that recovers the lost distinctions.

## Tools

- Repository: `hp460.py`, `firmware_analysis.py`, `firmware_candidate.py`,
  and the `experiments/` emulators, audits, and the xref classifier.
- Disassembly: Rizin (ARM Thumb), Capstone, and Unicorn emulation.
- Reference binaries and data: public Ash 1.0/1.1/1.2 firmware images, the
  HP Accessory Center application as a protocol reference, the PAR2801-Q32P
  module datasheet, and FCC filing photographs.
- Firmware and application binaries are not redistributed; captures are
  sanitized.

## Next steps

1. Trace the exact OTA authentication for the two-halfword patch and determine
   whether the inner digest can be recomputed for a candidate image.
2. Identify a recovery path: SWD pins from the PAR2801 datasheet and FCC
   photographs, plus bootloader behavior.
3. Produce a safe, reversible flash procedure with a recovery plan and present
   it for confirmation before any write is attempted.
4. After confirmation: build the candidate, verify it in emulation, back up
   what can be backed up, and flash with recovery prepared.

No flash, erase, reset, or firmware write is attempted until the user confirms
the exact procedure and recovery plan.
