# Reassessment: native mode before host remapping

The sampled VM companion is a research fallback, not a production-quality fix.
Original-ARM emulation establishes its instructions, not reliable physical
event capture or correct Windows modifier ordering. A stronger target is to
make the keyboard generate native reports itself.

## New finding: a separate F-row polarity flag

Stock Ash 1.2.0 has a one-byte RAM flag at `0x20001BE0`. At
`0x100073D6`–`0x100073DE`, the layer transformer reads it. Its branches at
`0x100073EE`–`0x10007412` and `0x10007464`–`0x1000746A` use that value to
select native F-key insertion versus special-key dispatch. Navigation follows
the separate Fn/Fn-Lock decision.

With physical Fn released, the original transformer produces:

| RAM flag | Fn Lock | F1–F12 | Navigation |
| --- | --- | --- | --- |
| 0 | off | special actions | native |
| 0 | on | native | alternate actions |
| 1 | off | **native** | **native** |
| 1 | on | special actions | alternate actions |

The flag-1/Fn-Lock-off case meets the desired no-Fn behavior in the function
test, including normal Shift/Ctrl/Alt modifier bytes. The internal Fn Lock
state would be off, but F1–F12 and the navigation cluster would be native.
The former HPAC self-map does not use this path: it emits separate synthetic
zero-modifier reports. Here the stock transformer inserts native usages into
the normal physical report.

`experiments/validate_layer_flag.py` runs all four rows against all 19 target
virtual actions and all 256 modifier bytes: **19,456 original-ARM runs**.
The desired row inserts each expected usage, preserves the modifier byte,
sets no special mask and never invokes the direct alternate dispatcher.
No flash bytes are patched, and no VM program runs in this experiment.

This is an isolated function test, not a live fix. It does not prove scanner,
rollover, transport, power-management or full-device behavior. In particular,
**there is no demonstrated HID command for writing this RAM flag**. Changing
emulated RAM is not evidence that live RAM is writable through HPAC.

## Where the flag comes from

The decompressed initializer starts this byte at 1. Startup code reads logical
GPIO input `0x21` through `0x1000E8D8`, at call `0x1000464E`. The result controls
the store of 1 or 0 at `0x1000466E` / `0x10004672`. The GPIO helper selects a
bank and reads its input register. This is consistent with a board mode strap;
the exact board net, physical package pin, resistor and intended product-mode
name are not established. Logical GPIO `0x21` must not be interpreted as
physical IC pin 33.

The observed keyboard behavior matches flag 0, but that is an inference from
behavior; the actual byte has not been read from this keyboard. The located
startup writer is not a software command to toggle the flag, and the static
reference inventory is not an exhaustive proof that no other writer exists.

## Stronger routes and their actual boundaries

1. **Set the stock native-mode flag.** Prioritize the vendor feature/diagnostic
   handlers and RAM access paths. A legitimate setter or a controlled device
   memory-write mechanism could allow a connection-time helper to set one byte
   and select Fn Lock off. That would avoid polling and host input injection.
   The mechanism has not been found. A RAM change would need reapplying after
   startup; whether sleep or host switching also resets it needs measurement.
2. **Modify the hardware mode input, if confirmed.** Mapping logical GPIO
   `0x21` to an actual board strap could reveal a permanent hardware mode change
   that avoids firmware authentication entirely. This is a hypothesis, not a
   located jumper or a validated modification. It would require someone with
   hardware skills/equipment; no case opening or wiring is requested of the
   user in the current software investigation.
3. **Patch the firmware's native matrix.** The existing 38-byte candidate
   eliminates special actions before layer processing. This remains the most
   direct firmware change. Installation requires a genuine device-side bypass,
   alternate loader, or usable physical programming access. Normal OTA rejects
   its signature. SWD access, read protection and boot-time authentication are
   unresolved, so even a programmer is not a guaranteed solution. Replacing
   the controller and porting firmware is a much larger hardware project.
4. **Use a device-specific Windows driver only with enough source information.**
   A filter can suppress reports before Windows executes shortcuts, but cannot
   recover physical distinctions the firmware did not transmit. With Fn Lock
   on, End is converted to Esc; device identity alone cannot distinguish it
   from the same keyboard's Esc. With Fn Lock off, generated shortcuts and
   physical modifiers need exact report traces before claiming reversible
   translation. Signing and installation rights are needed on each PC, which
   conflicts with the current work-laptop constraint. This is not yet a proven
   complete fallback.

An external Bluetooth/USB proxy has the same information limit if it only sees
the existing converted reports. Administrator access on Windows cannot by
itself expose an untransmitted physical key or disable device RSA validation.
Accepting brick risk permits a justified experiment; it does not supply a
missing programming or authentication bypass.

## Additional checks and next investigation

The older signed-image route was reconsidered. Ash 1.0 and 1.1 also install
device RSA keys into their OTA contexts; their stock inner signatures recover
their application digests. See [cross-release authentication](firmware-release-auth.md).
No unsigned downgrade route was established and no downgrade was attempted.

Fresh online searches found discussion of the same HP 460 layer conflict, but
no demonstrated HP 460 native-mode setter or compatible QMK/ZMK replacement.
Related PixArt/Sonix keyboard projects do not establish a loader or debug
unlock for this controller. The immediate research target is the stock RAM
flag's accessibility; the VM stream remains an independent fallback requiring
live timing tests. No device command, setting change or firmware upload was
sent during this reassessment.

Reproduce the new result with optional Unicorn:

```powershell
PYTHON.EXE experiments/validate_layer_flag.py C:\images\Ash_1200.FW
```

Sources:

- [HP 460 users describing the same function/navigation conflict](https://h30434.www3.hp.com/t5/Gaming-Accessories/HP-460-Multi-Device-Use-function-keys-F1-F2-F12-and-START/td-p/9464608)
- [Microsoft HID architecture and filter-driver guidance](https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/keyboard-and-mouse-hid-client-drivers)
- [Related keyboard reverse engineering, different controller/board](https://github.com/IslamAlam/blitzwolf-bw-kb-1)
