# VM interpreter call and the physical-modifier question

This records how the firmware actually invokes the programmable-key VM and
why the VM cannot itself emit modifier-correct F-keys. It is read-only static
analysis; no keyboard was written.

## Interpreter entry and caller

The VM interpreter is `0x10005656`. At runtime it is reached through an
indirect veneer at `0x10014D4C`, which tail-calls `0x10005656`. The real
caller is the scheduling block at `0x10014A92`-`0x10014AB6`.

That caller passes, per interpreter tick:

| VM variable | Runtime source |
| --- | --- |
| 0 | `0x20001F70 + 0x30` (the current special-key / F-row mask) |
| 1 | `0x20001F70 + 0x20` |
| 2 | `0x20001F70 + 0x24` |
| 3 | `0x20001F70 + 0x28` (read, then cleared) |
| 4 | `0x20001F70 + 0x2C` (read, then cleared) |

The interpreter adds each of these into its running variable registers, so
variables 1-4 are accumulators. The `0x20`-`0x2C` device-context fields are
read-then-cleared every tick, which is an event-counter pattern, not a
persistent state byte. The physical HID modifier byte is a different address,
`0x200027A5`.

## Keyboard-key opcode is modifier-capable but has no live modifier source

Opcode 24 (keyboard key) builds an 8-byte keyboard report from a blob. The
first blob byte becomes the report's modifier byte, and the following bytes
become key slots. Blob items may be literal bytes/words or variable
references, so the opcode can emit a nonzero modifier.

However, no VM variable carries the live physical Shift/Ctrl/Alt state.
Variable 0 is the F-row mask and variables 1-4 are the accumulator counters
above. There is also no indirect load opcode to fetch the modifier byte from
RAM. The modifier source therefore does not exist inside the VM.

## Why keyboard-side synthesis would fail even with a modifier source

HID keyboard reports are absolute state, not deltas. A VM-generated keyboard
report overwrites the device's modifier byte, so a zero-modifier F4 report
while Shift is physically held would clear Shift. The observed self-remap
failure is this exact effect. Windows-level SendInput injection merges with
the physically held modifiers instead of replacing them.

## Conclusion

The VM is a sandboxed observer/notifier. Modifier-correct F-key synthesis
must happen on the PC, which is the companion design: the keyboard consumes
the F-row and notifies the combined mask, and the Windows helper injects only
the changed F-key events while the user's physical modifiers remain intact.
