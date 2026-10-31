# Decision record and next plan

## Results established on hardware

All live tests used the HP 460 with firmware 1.20.0. The test processes were
stopped afterward, and the keyboard was restored to current and startup Fn
Lock on.

1. With Fn Lock on, Stamp/Home/End/Page Up/Page Down become a language macro,
   App2, Esc, Brightness Up, and Brightness Down. Holding Fn produces their
   native usages.
2. Programs written to HPAC entries `12–23` were accepted and read back but
   did not change this direct layer.
3. The input-only `FF00:0001` vendor collection produced no reports while the
   five target keys were pressed. It is not a passive raw-matrix stream.
4. With Fn Lock off, Stamp, Home, End, Page Up, and Page Down all produced the
   desired native usages without Fn.
5. With Fn Lock off, an isolated AHK `Media_Prev::F4` rule converted physical
   F4 to F4. The recorded modified sequence was exactly `Shift down`, `F4
   down`, `F4 up`, `Shift up`. This differs from HPAC's simulated F4 and proves
   that host-side translation can preserve `Shift+F4`.
6. The same simple AHK strategy worked for F1–F6 but not for the whole row.
   F7–F12 are firmware-generated keyboard chords. Emoji and other Windows
   actions leaked through two prototype variants. F11 was intentionally not
   tested because its source chord is `Win+L`.

The retained AHK experiment is in
`../experiments/fn-off-ahk-prototype.ahk`. It documents a partial success and
a reproducible limitation; it is not the finished solution.

## What the firmware proves

The Fn-Lock-on direct navigation behavior is compiled code, not an HPAC data
table. The layer transformer at `0x100072F8` sends matrix actions `0x010C`
through `0x0112` to the direct dispatcher at `0x100038B4`. The firmware also
contains a native converter and insertion block at `0x1000747E`.

A two-halfword offline candidate can redirect only Stamp through Page Down to
that existing native block:

```text
VA 0x10007420 / file 0x742D: 09 D0 -> 2D D0
VA 0x10007422 / file 0x742F: 20 46 -> 2C E0
```

F1–F12 take an earlier branch and are not affected by these instructions. The
candidate therefore matches the original requirement: retain Fn Lock on and
make the navigation cluster native. It is statically compelling but has not
been flashed or executed.

## Options

### 1. Firmware patch: best final behavior, highest recovery requirement

This is the preferred research direction because it produces a self-contained
keyboard that can be moved to the work laptop without resident software or a
driver. The code change is now small and precisely located.

It is not ready to flash. The public updater image has three 256-byte
authentication-sized regions, and neither the validation algorithm nor a
recovery procedure has been proved. A rejected image is the mild failure; an
accepted but unbootable image could brick the keyboard.

Required gates before a live attempt:

1. Build an offline patcher locked to the exact Ash 1.2.0 SHA-256. It should
   emit a byte-level manifest and a patched copy, never modify the source.
2. Trace HPAC's updater and firmware bootloader validation to determine which
   bytes are authenticated and whether a development or recovery command
   exists.
3. Identify the actual controller marking and board test pads. A related
   PixArt PAR2801-family manual documents two-pin SWD, but that does not prove
   this board exposes unlocked SWD.
4. Read and verify a complete flash backup before writing anything.
5. Prove recovery by restoring an unchanged dump. Only then test the two
   halfword patch on one keyboard.

### 2. Windows HID filter: robust software fallback

Use Fn Lock off, where the navigation cluster is already correct. A device-
specific filter would rewrite the HP keyboard's F-row reports while preserving
the modifier state that existed before each firmware-generated shortcut.

This can solve the synthetic `Win`/`Ctrl` problem that defeated simple AHK,
but it requires driver development, signing/test-signing during development,
and installation rights on every computer. The keyboard and consumer controls
are separate HID collections, so a complete implementation likely needs a
filter plus a virtual HID keyboard or a small companion service. Microsoft
documents a filter driver as the supported architecture for value-added
keyboard behavior.

### 3. Advanced AHK/Raw Input: lowest deployment cost, less robust

The proven F1–F6 remaps and `Shift+F4` result make a more sophisticated AHK
state machine plausible. It would need exact low-level traces, device identity
from Raw Input, suppression of complete synthetic chords, and careful handling
of real Win/Ctrl combinations. Ordinary AHK keyboard hooks are not device-
specific, while Raw Input cannot suppress the original events by itself.

This route remains useful as a temporary prototype, but the two leak tests
show that it should not be called complete without all F1–F12 modifier cases,
F11 safety, multiple-key rollover, reconnect, sleep, and second-keyboard tests.

## Recommended sequence

1. Continue offline firmware work: make the exact-SHA patcher and analyze the
   updater authentication path. This is safe and directly serves the portable
   work-laptop goal.
2. In parallel, add a read-only low-level/Raw Input trace command for exact
   F7–F12 report timing. It supports either software fallback without changing
   the keyboard.
3. Choose the live route only after the recovery and deployment constraints
   are known:
   - proven SWD backup/restore: test the firmware candidate;
   - driver installation allowed: build the HID filter;
   - neither available: pursue the advanced AHK state machine with explicit
     limitations.

Do not send more hidden HPAC button records: the direct navigation branch has
now been located, and those records do not control it.
