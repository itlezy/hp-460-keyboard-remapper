# HPAC developer mode and packet log

HP Accessory Center 2.21 contains a hidden diagnostic packet logger. It is the
most useful reference when comparing a new firmware version or another HP
accessory.

## Settings helper

Close HPAC before changing its settings.

```powershell
# Read-only status.
PYTHON.EXE hpac_dev_mode.py status

# Enable developer mode and keyboard-program packet monitoring.
PYTHON.EXE hpac_dev_mode.py enable

# Disable the three flags again.
PYTHON.EXE hpac_dev_mode.py disable
```

The helper changes these keys:

```json
{
    "dev": true,
    "monitorHPACPackets": true,
    "monitorHPACPacketsKbdPrg": true
}
```

Before writing, it makes a timestamped backup beside `HPAC.settings`. HPAC's
settings file is not plain JSON: an opaque binary trailer follows the top-level
JSON object. The helper locates the closing brace with a string-aware parser
and preserves that trailer byte-for-byte.

The default settings location is:

```text
%LOCALAPPDATA%\Packages\AD2F1837.HPAccessoryCenter_v10z8vjag6ke6\
LocalCache\Roaming\HP Inc\HP Accessory Center\HPAC.settings
```

Use `--settings PATH` if a future HPAC package stores it elsewhere.

## Reveal the diagnostic UI

After enabling the flags:

1. Start HP Accessory Center.
2. Hold the **middle and right mouse buttons** over the HP logo for roughly two
   seconds.
3. Open **Settings**.
4. Open **Packet log**.
5. Connect or revisit the keyboard page to produce a fresh startup exchange.
6. Export the log to a text file.

The exact gesture and menu visibility may change in later HPAC releases.

## Useful packet-log entries

On startup, the tested version emitted:

```text
ButtonQueryPacket sze:7 seq:0 command:0 hostId:0
ButtonReplyPacket sze:9 seq:0 command:0 nbProg:24 nb:0 hostId:1
config(nbProgrammableButtons:24 supportLongPress:0
supportDoublePress:0 supportDownUpPress:0 supportSimulate:1)
```

`nbProg:24` initially suggested that HPAC's 12-key Ash UI merely hid physical
navigation-key slots. Static analysis confirmed this structurally: the Ash
matrix uses virtual codes `0x010C–0x0112` for program IDs `12–18`. A controlled
write returned those descriptors but did not change the first key test, so the
remaining problem is activation semantics rather than absent IDs. `nb:0` meant
no custom button descriptors were stored at startup.

## Privacy before publication

HPAC exports may contain:

- the Windows host name;
- Bluetooth addresses or HID instance paths;
- keyboard hardware/profile identifiers;
- application names and per-application assignments.

Replace those values with neutral placeholders before attaching a capture to
an issue or commit. The capture in this repository is sanitized.
