# Work-laptop procedure

The current project can reproduce the proven persistent Fn Lock configuration
on another HP 460. Primary-layer navigation remapping remains unresolved.

## Preparation

1. Confirm that local Python utilities are allowed by the laptop's policy.
2. Install Python 3.10 or newer if needed.
3. Pair and connect the HP 460 over Bluetooth.
4. Keep the built-in or a USB keyboard available.
5. Copy this repository locally.
6. Fully exit HP Accessory Center before running the HID tool.

## Identify and configure

```powershell
PYTHON.EXE hp460.py devices
PYTHON.EXE hp460.py fn-lock on --dry-run
PYTHON.EXE hp460.py fn-lock on
```

Expected device output resembles:

```text
[0] HP 460 control collection, firmware=0x04B0, usage=FF05:0001
```

The Fn Lock command sets both current and startup state to on. It does not
program Stamp, Home, End, Page Up, or Page Down.

## Verify the layer behavior

```powershell
PYTHON.EXE hp460.py verify
```

With Fn Lock on, press the five keys without Fn and then with Fn held. On the
tested 1.20.0 firmware, only the Fn-held path emits the native navigation keys.

## Troubleshooting

- **No device found:** verify that Bluetooth reports the keyboard connected.
- **Interface busy:** fully exit HPAC and retry.
- **Fn Lock does not persist:** rerun `fn-lock on` and power-cycle the keyboard.
- **Endpoint protection blocks HID access:** follow organizational policy; do
  not bypass it.

Do not use the experimental slot packets as a navigation-key solution. The
normal Fn-Lock-on navigation actions are hardcoded in a separate firmware
dispatcher, and accepted records in IDs `12–23` did not alter that path.
