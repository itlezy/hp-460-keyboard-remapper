# Vendor HID protocol

## Device and collection

The tested keyboard exposes several standard and vendor HID collections. HPAC
uses the vendor collection with:

| Property | Value |
| --- | --- |
| Vendor ID | `03F0` |
| Product ID | `814A` |
| Usage page | `FF05` |
| Usage | `0001` |
| Input report length | 21 bytes |
| Output report length | 21 bytes |
| Report ID | `06` |

The Windows device normally appears as `COL06`. The tool verifies the HID
capabilities rather than relying on that collection number.

HPAC imports the ordinary Windows HID APIs and opens this collection directly
from user mode. No HP keyboard filter driver is involved.

## HP update packet framing

After the HID report ID, HPAC's packet printer derives a packet-class key from
the first two protocol bytes:

```text
class = ((byte[2] & 0x0F) << 8) | byte[1]
size  = ((byte[4] & 0x03) << 8) + byte[3] + 4
```

Indexes above are indexes in the complete 21-byte HID report. Relevant class
keys include:

| Key | HPAC name |
| --- | --- |
| `0xCF8` | `BatteryQueryPacket` |
| `0xCF9` | `BatteryReplyPacket` |
| `0xCFA` | `BTQueryPacket` |
| `0xCFB` | `BTReplyPacket` |
| `0xD00` | `ButtonQueryPacket` |
| `0xD01` | `ButtonReplyPacket` |
| `0xD10` | `DeviceSpecificPacket` |
| `0xD11` | `DeviceSpecificReplyPacket` |

For Button packets, observed commands were:

| Command | Direction | Meaning |
| --- | --- | --- |
| `0` | host to keyboard | request button configuration |
| `1` | host to keyboard | set or clear a button program |
| `2` | keyboard to host | button notification path |

The startup config reply reported 24 programmable slots and no custom
descriptors. The decoded startup exchange is preserved in
`captures/hpac-startup-sanitized.txt`.

## Button descriptor

The command-1 packet layout used by this project is:

| Report index | Meaning |
| ---: | --- |
| `0` | HID report ID `06` |
| `1..4` | ButtonQuery framing (`00 0D 09 00`) |
| `5` | command `01` |
| `6` | button slot |
| `7` | host (`00`) |
| `8` | press type (`00`, normal press) |
| `9` | program length (`04`) |
| `10..13` | program bytes |
| `14..20` | observed transport trailer/padding, preserved verbatim |

A captured HPAC assignment of native F12 to visible slot 11 produced:

```text
06 00 0D 09 00 01 0B 00 00 04 F8 00 45 00 02 00 00 00 00 00 00
```

The four-byte native-key program is:

```text
F8 00 <USB keyboard usage> 00
```

The HID usages needed here are contiguous standard Keyboard/Keypad Page
usages:

| Key | Hidden slot | Usage | Program |
| --- | ---: | ---: | --- |
| Print Screen | 12 | `46` | `F8 00 46 00` |
| Home | 14 | `4A` | `F8 00 4A 00` |
| Page Up | 15 | `4B` | `F8 00 4B 00` |
| End | 17 | `4D` | `F8 00 4D 00` |
| Page Down | 18 | `4E` | `F8 00 4E 00` |

Slots 13 and 16 correspond to Insert and Delete and are intentionally left
untouched.

An empty program restores a slot's firmware default. The packet uses size 5,
program length 0, and the same observed trailer:

```text
06 00 0D 05 00 01 <slot> 00 00 00 02 00 00 00 00 00 00 00 00 00 00
```

## Fn Lock

Fn Lock uses a DeviceSpecific packet. State byte 16 is a bit field:

| Current | Startup | State byte |
| --- | --- | ---: |
| Off | Off | `02` |
| Off | On | `03` |
| On | Off | `06` |
| On | On | `07` |

The On/On report is:

```text
06 10 0D 0C 00 80 0B 00 01 00 00 00 00 00 00 00 07 E0 16 0A F3
```

HPAC describes the startup operation as `saveToFlash:1`. It changes a stored
device setting; it is not a firmware rewrite.

## Live verification

The five command-1 reports were sent individually and Windows produced native
Print Screen, Home, End, Page Up, and Page Down DOWN/UP events. After the
keyboard was turned off and back on, all five events remained native. See
`captures/reports.txt`.
