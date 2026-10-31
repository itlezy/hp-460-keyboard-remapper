# Scanner and local development-loader results

Subsequent result: [device signature proof and next hardware test](device-validation-and-next-test.md).
That report identifies the inner signature check and replaces the former
requirement for proven recovery, following acceptance of losing one keyboard.

## Fixed flash matrix confirmed

The cached matrix processing routine at `0x10002D5C` iterates 16 scan bytes,
each with eight bits. At `0x10002D88` it loads the constant `0x10013822`, then
reads a halfword at `base + 2 * (byte_index * 8 + bit_index)`. The validity
counter at `0x100031D8` independently uses the same base and 16-by-8 indexing.
Neither lookup uses a writable RAM table pointer.

The earlier 13-by-10 interpretation at `0x10013820` was incorrect: that first
halfword is the end of the preceding `KB2861` board-name string. This corrects
the table dimensions and physical row/column coordinates. It does **not** change
the absolute addresses of the 19 proposed virtual-key substitutions, which were
located by their unique code values.

The new `experiments/validate_matrix_scanner.py` executes the actual scanner
instructions with each cached scan bit individually asserted. It verifies all
128 positions against the flash table, both stock and patched: 256 successful
scanner runs. The 29,184 key-transformer runs also still pass after correcting
the parser and removing the experiment's hardcoded column count.

Scanner-test limits: electrical scanning, list internals and report dispatch
are stubbed. It proves the actual lookup reads the modified keycode; it does
not prove complete keyboard operation. A live RAM override would require an
additional mechanism to change executable code or its fixed literal, rather
than merely updating an existing RAM keymap.

## HPAC supports disabling outer verification for local FW2 files

The local directory scanner at `0x1400FB190` uses a Boolean inclusion argument.
When enabled and a filename ends in `.FW2`, it sets `r12b=1`. Immediately before
calling the file parser at `0x1400FB6C8`, it inverts that value and passes it as
the parser's verification flag (`r8b=0`).

The parser at `0x1400F4390` forwards the flag through record enumeration at
`0x1400E1F00` to the section checker at `0x1400E1D00`. With verification false,
the checker still validates lengths, but returns the payload length before
allocating a signature buffer or running RSA/SHA verification.

Analyst reconstruction:

```text
local_development_file = include_local && filename.endsWith(".FW2")
verify_outer_signature = !local_development_file
parse_file(bytes, verify_outer_signature)
```

`experiments/validate_hpac_local_flag.py` executes the original x64 section
checker on the stock and edited Ash record with this flag disabled. Both return
payload length `0x15F9B`; neither calls the cryptographic routines. The test
does not open HPAC, invoke its updater or touch a HID device.

This narrows the earlier signature obstacle: the stock download path rejects
an edited outer signature, while HPAC already has a development path that can
skip that outer check. A patched HPAC executable may therefore be unnecessary.
The full Qt local-loader path has not been exercised, and device acceptance is
not established.

The directory-opening routine at `0x1400F8FC0` constructs the same
`QStandardPaths::writableLocation(10) + "/HPAC/FWUpdates"` directory used by the
scanner, creates it if necessary and opens it. Its UI labels include "Load
local FW2s" and "open local FW2s directory". These are local firmware-loading
features, not a flash-backup feature. Merely renaming a file leaves its opaque
inner trailer unchanged; whether the keyboard checks that trailer is unknown.

## Firmware readout status and next action

No flash readout command has been identified. There is no physical keyboard
dump yet, and no unknown diagnostic, update-start or erase command was sent.

The application also calls low-address function-pointer tables: for example,
`0x10011390` calls through the pointer at `0x7AC` to read stored data. Such an
internal read primitive is not evidence of a remotely callable read command.
The destination pointers and underlying controller routines are outside the
downloaded application image. The inner block was unidentified at this stage;
the later report now identifies its separate device key, RSA decoder and
application-digest comparison.

The next analysis should follow the actual HID feature callbacks into the OTA
implementation, identifying any device-side validation and any address-based
readback operation. If the required code/data live in controller ROM or
protected debug space, board inspection and a debug probe may be needed to
obtain them.

The later analysis confirms storage operations precede final validation, and
the candidate fails the ordinary device check. Even with accepted brick risk,
a known-failing upload is a poor experiment. Board debug/recovery identification
is the next useful step.

## Reproduce

Use the same optional dependencies as the firmware follow-up (`pefile`,
`capstone`, `unicorn`):

```powershell
PYTHON.EXE experiments/validate_matrix_scanner.py C:\path\Ash_1200.FW
PYTHON.EXE experiments/validate_hpac_local_flag.py C:\path\HPAccessoryCenter.exe C:\path\Ash_1200.FW
PYTHON.EXE arm_static.py C:\path\Ash_1200.FW --low 0x10013822
```

The local report exporter now saves these additional emulator outputs and the
two local-loader disassemblies in the Git-ignored `local-research` directory.
