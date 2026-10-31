# Work-laptop procedure

This is the conservative procedure for programming a second HP 460 keyboard.

## Preparation

1. Check that running local Python utilities is permitted by the laptop's
   security policy.
2. Install Python 3.10 or newer if it is not already available.
3. Pair and connect the HP 460 keyboard over Bluetooth.
4. Keep the laptop's built-in keyboard or another USB keyboard available.
5. Copy this repository to a local directory.
6. Exit HP Accessory Center completely, including its tray process.
7. Exit AutoHotkey and other keyboard-remapping or screenshot utilities during
   verification.

The HP software is not required for the programmer. It is useful only for
comparison, firmware updates, or its packet logger.

## Identify the control collection

```powershell
PYTHON.EXE hp460.py devices
```

Expected output resembles:

```text
[0] HP 460 control collection, firmware=0x04B0, usage=FF05:0001
```

If the tool reports that the interface is busy, close HPAC and retry. Do not
disable or remove the keyboard in Device Manager.

## Preview and apply

```powershell
PYTHON.EXE hp460.py nav plan
PYTHON.EXE hp460.py fn-lock on
PYTHON.EXE hp460.py nav apply
```

`nav plan` is non-mutating. It prints the five reports that `nav apply` will
send.

## Verify

```powershell
PYTHON.EXE hp460.py verify
```

Without holding Fn, press:

1. Stamp / Print Screen
2. Home
3. End
4. Page Up
5. Page Down

The verifier should print one DOWN and one UP event for each native key. Stop
it with Ctrl+C. Then turn the HP keyboard off, wait five seconds, turn it on,
and repeat the test to confirm persistence.

## Restore HP defaults

```powershell
PYTHON.EXE hp460.py nav restore
```

Restore sends an empty button program to each hidden slot, which is the same
mechanism HPAC uses to return an exposed function key to its firmware default.

To restore only one slot:

```powershell
PYTHON.EXE hp460.py nav restore --key page-up
```

## Troubleshooting

- **No device found:** confirm that Bluetooth reports the keyboard as connected
  and run `devices` again.
- **Interface busy:** fully exit HPAC. Logging tools that open the vendor HID
  collection may also need to be closed.
- **Fn layer is reversed:** run `PYTHON.EXE hp460.py fn-lock on`.
- **Unexpected result on another firmware:** stop, run `nav restore`, and save
  an HPAC packet capture before experimenting further.
- **Endpoint protection blocks HID access:** do not work around corporate
  policy; request approval or run the tool on an authorized machine.
