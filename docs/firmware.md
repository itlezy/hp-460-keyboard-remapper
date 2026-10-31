# Firmware notes

HP publishes Ash firmware images under its HPAC firmware directory. These
files are not redistributed here.

| Version | Public URL | Length | SHA-256 |
| --- | --- | ---: | --- |
| 1.0.0 | `https://ftp.hp.com/pub/hpac/FW/Ash_1000.FW` | 92,225 | `514B88BB2DAC7FF54D818EE593732E3F07A6A48A3CB8485DE8628B90D8C590A6` |
| 1.1.0 | `https://ftp.hp.com/pub/hpac/FW/Ash_1100.FW` | 92,265 | `B749A0BB1FBA465CA96E31E865D0B0D424183461ECFA2345CB9ECD389C265A75` |
| 1.2.0 | `https://ftp.hp.com/pub/hpac/FW/Ash_1200.FW` | 90,549 | `6E490AE055B9DFC9AA9E750F8693BD563A24EC2F060A84F12D250996A0E77C2E` |

The images contain ARM Cortex-M Thumb code. For static analysis of 1.2.0, a
useful approximate mapping was:

```text
virtual address = 0x10000000 + file offset - 1
```

Observed firmware strings and descriptors included:

- product text for HP 460 and HP 475;
- PixArt BLE keyboard/controller text;
- `QueryPacketResponse`, `PayloadPacket`, `AckPacket`;
- `BatteryQueryPacket`, `BTReply`, `ButtonReplyPacket`;
- keyboard report ID 1;
- consumer report ID 3;
- system-control report ID 4;
- vendor feature report ID 5;
- vendor page `FF05` report ID 6 with 20-byte input/output payloads;
- additional vendor reports 7, 8, and 9.

This confirms that the 21-byte `06 ...` Windows reports are implemented by the
keyboard firmware itself. HPAC is a user-mode client of that firmware protocol,
not a front end for a proprietary kernel driver.

The native button programs were not present as a simple plaintext default
table in the updater image. They are likely generated or stored in writable
device configuration. The safer route was to capture one HPAC-generated native
key program and use the keyboard's documented-by-behavior configuration path.

Do not flash a downloaded image merely to apply this remap. The utility only
writes supported runtime/configuration reports.
