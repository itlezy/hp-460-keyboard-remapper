# Current software-only plan

Reassessment: the [stock native-mode flag](native-mode-and-nuclear-options.md)
offers a stronger target if a live setter can be found. Its original native
insertion path passes offline function tests; live access is unresolved.
The sampled VM companion described here remains a research fallback.

## Constraints and status

- No case opening, soldering, probes or electronic equipment is required for
  this phase. The user is not doing hardware work.
- Admin experiments are permitted on the research PC. The work laptop has no
  admin access, but running a Python, PowerShell, AHK or compiled program is
  acceptable. A helper may run when the keyboard connects.
- A persistent keyboard-only fix is still desirable, but a running companion
  is now an accepted solution. It must deliver F1–F12 with normal modifiers,
  plus native Print Screen/Home/End/Page Up/Page Down without Fn.
- Media actions may be discarded. Italian physical layout with Windows US
  remains supported by leaving ordinary key usages/layout interpretation alone.
- Ordinary signed OTA rejects the firmware candidate. No flash was attempted.
- No driver was installed, no automatic startup was registered, no Fn setting
  or stored program was changed during this unattended research session.
- The PC is locked and the user is away. Interactive event recording is stopped.
  Two attempts to open the HP control interface for a read-only program query
  failed before sending the query. The reason is not established; sleep or
  disconnection is possible. No configuration backup was obtained.

## Preferred new investigation: temporary F-row mask stream

The built-in programmable-key interpreter can do more than send shortcuts.
An original ARM code path lets a program select which special-key bits its
active execution consumes, read the current special-key mask and emit a
vendor notification containing data derived from VM variables.

This offers a possible companion architecture:

```text
Fn Lock off:
  ordinary keys, modifiers and navigation -> normal keyboard reports
  F1–F12 special-key bits -> consumed by one running VM program
                          -> vendor notification of the combined F-row mask
                          -> helper emits only the changed F-key down/up events
```

Fn Lock off is the internal setup. The helper would emit F1–F12 while leaving
Windows' existing Shift/Ctrl/Alt state intact. It would not use HPAC's native
F-key macro instruction, which emits its own zero-modifier keyboard report.
This is materially different from the earlier failed self-map.

One running VM handles the combined mask. This avoids the interpreter's
single-program selection problem found in the
[consumer-only alternative](consumer-bridge.md), where a second F-key could
reach its original default shortcut while another custom program was active.
Reading the specific HP vendor interface would also avoid global media-key
bindings that affect other keyboards.

## Recovered instructions and receive path

| Address / VM item | Observed role |
| --- | --- |
| `0x1000A738`, command 2 of `0x0D00` | receives a simulated button program |
| `0x1000A97C`–`0x1000A99C` | copies the complete packet into RAM, passes descriptor at packet + 6 to initializer |
| `0x1000A6D8` / `0x100055FA` | initializes the one active program |
| VM variable 0 | current special-key mask, supplied by the main scheduling loop |
| opcode 22, blob subcommand 7 | replaces active program's consumed-key mask |
| `0x10005ADA`–`0x10005AF8` | assembles subcommand 7 bytes into context + `0xDC` |
| `0x100148DE`–`0x10014908` | active filter shifts that mask right by 7, removes selected programmable bits from default dispatch |
| opcode 25 / `0x10005BB6` | creates a vendor ButtonReply command-2 notification from a blob |
| `0x1000AA68` | queues the notification on the vendor transport and supplies a scheduling delay |

The initial consumed mask covers only the initiating button. Subcommand 7 can
replace it with `0x0007FF80`, which shifts to `0x00000FFF`: all twelve F-row
bits. This is a mask in the interpreter's own context, not a matrix flash
rewrite or arbitrary RAM write.

The simulated program descriptor has an extra byte before the descriptor
compared with command 1. The complete packet payload used by the emulator is:

```text
02 00 <button-id> <host> 00 <program-length> <program-bytes>
```

The exact command-2 handler is executed by the emulator; no live simulate
packet has been sent. HID fragmentation/reassembly on the actual device still
needs validation. The packet-handler path does not use the command-1 stored
configuration write or schedule its save-to-flash operation.

Prototype notifications, before Windows' HID report ID/padding, are:

```text
01 0D 06 00 02 <button-id> 03 A5 <mask-low> <mask-high>
```

`A5` is the prototype marker, not an HP protocol-defined constant. The helper
would validate packet type, command, size and marker, then use only the low
twelve mask bits. No letters or typed text are included.

## What is implemented and verified

`experiments/key_mask_program.py` builds a 24-byte candidate. It consumes the
F-row, copies VM variable 0 into two notification bytes and uses an iteration
counter to terminate after 1–127 notifications. The default is 16. This
bounded design is for research; a wall-clock expiry and a production stop
procedure have not been proved on hardware.

`experiments/validate_key_mask_program.py` executes the actual command-2
handler, initializer, VM and active filter in Unicorn. It checks:

- all 4,096 simultaneous F-row combinations, in bounded batches;
- all 256 physical modifier bytes with mixed press/release masks;
- notifications carry the exact sampled F-row mask;
- F-row bits are consumed while non-F-row bits remain available for dispatch;
- no keyboard or consumer-report callback is invoked;
- the physical report modifier byte remains unchanged;
- the bounded program ends and its F-row suppression ends afterward.

The independent host decoder/state machine is in
`experiments/key_mask_bridge.py`. Tests cover notification validation,
duplicate masks, overlapping presses, release-before-press transitions and
cleanup for every one of the 4,096 combinations. It currently replays files;
it does not open the keyboard or call SendInput.
The repository test suite now has 22 passing tests.

The original consumer-only path separately passed 6,144 transformer/filter/VM
runs. Its overlap limitation remains; that result is not presented as a full
keyboard fix. The AHK lab companion passed parsing without activating hotkeys.
The passive hook/Raw Input recorder was also checked briefly before the AFK
notice and exited; it has no startup or background registration.

## Remaining work before calling this a solution

1. Confirm normal vendor access, identity/version and the actual active profile
   when the keyboard is available. Obtain a private read-only configuration
   backup before any configuration experiment.
2. Validate a very short simulated program with Fn Lock left in its original
   state. Confirm real notifications, fragmentation and automatic termination.
   Native F-row routing should be kept available during initial setup; do not
   immediately switch layers and assume the program is receiving events.
3. Establish a clean start/stop procedure, including helper crashes and device
   disconnects. The current firmware initializer refuses to replace a busy
   program. Although the handler calls `0x1000F084`, its callback is initially
   null; it is not yet a proven cancellation command. Finite emulated execution
   is not proof of a usable production cancellation/recovery mechanism.
4. Measure event timing. The emulator supplies one mask per interpreter tick.
   It does not prove every short physical press/release edge survives VM
   scheduling and BLE queue delays. Notification callbacks can yield, so a
   sampled stream could miss an event. Removing an extra explicit delay helps
   the model but does not prove hardware performance.
   Cross-interface ordering also matters: if a queued F-key notification arrives
   after Windows has processed a physical Shift release, preserving the current
   Windows modifier state alone will not reconstruct the original chord. The
   offline modifier-byte checks do not prove Windows chord timing.
5. Add/test the live host reader and Windows injection backend. Test plain and
   modified F-keys, key hold/repeat, rapid taps, simultaneous keys, unchanged
   navigation/ordinary keys, second keyboard, sleep/reconnect and orderly stop.
6. Test standard-user execution on this PC before work-laptop deployment.
   SendInput cannot inject into higher-integrity applications; running elevated
   here tests a different case from standard-user operation at work. Keep the
   final deployment constraints explicit.
7. Add connection handling and packaging only after the input path works.
   A resident helper would be needed on each PC; this path is not an unsigned
   firmware flash that can be provisioned once and then used without software.

No user key-press test is being awaited during the AFK period. The scripts and
offline findings are prepared so later testing can be narrow and deliberate.

## Reproduce offline

```powershell
PYTHON.EXE experiments/key_mask_program.py
PYTHON.EXE experiments/validate_key_mask_program.py C:\path\Ash_1200.FW
PYTHON.EXE experiments/key_mask_bridge.py captures/key-mask-emulated.json
PYTHON.EXE -m unittest discover -s tests -v
```

The replay needs optional Unicorn. The ordinary utility, packet framing,
program assembler and host mask state machine use the standard library.
`captures/key-mask-emulated.json` contains eight notifications produced by
emulation, not captured from a physical keyboard. The replay prints planned
F-key transitions and injects nothing into Windows.

Relevant Windows references:

- [Raw Input and device identity](https://learn.microsoft.com/en-us/windows/win32/inputdev/about-raw-input)
- [Low-level hook suppression and timeout limits](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc)
- [SendInput and integrity levels](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
