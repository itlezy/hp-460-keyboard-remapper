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

The Windows device normally appears as `COL06`. The tool checks the HID
capabilities instead of relying on that collection number. HPAC opens this
collection directly with the ordinary Windows HID APIs; no HP keyboard filter
driver is involved.

## HP update packet framing

After the HID report ID, HPAC's packet printer derives a packet-class key from
the first two protocol bytes:

```text
class = ((byte[2] & 0x0F) << 8) | byte[1]
size  = ((byte[4] & 0x03) << 8) + byte[3] + 4
```

Indexes above refer to the complete 21-byte HID report. Relevant class keys
include:

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

The startup config reply reported `nbProgrammableButtons:24` and no custom
descriptors. Static analysis later confirmed a 24-entry identity map inside
the generic custom-program engine. It still is not evidence that every
physical Ash/460 key is routed into those 24 special bits. The decoded startup
exchange is in `../captures/hpac-startup-sanitized.txt`.

## Query and multipart replies

The bootstrap query captured from HPAC was:

```text
06 F3 0C 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

Its `QueryPacketResponse` arrived in multiple input reports, beginning:

```text
06 F4 0C 1A 00 ...
06 F4 0C 1A 04 ...
```

Button writes also produce multipart `ButtonReplyPacket` responses. One
observed response had decoded size 49 and three fragments. A client that sends
several writes must drain every response fragment before issuing the next
write. The current command-line interface deliberately exposes only the
independent, proven Fn Lock operation; its packet builders for button programs
are research helpers, not an apply command.

## Button descriptor

The command-1 packet layout observed from HPAC is:

| Report index | Meaning |
| ---: | --- |
| `0` | HID report ID `06` |
| `1..4` | ButtonQuery framing (`00 0D 09 00`) |
| `5` | command `01` |
| `6` | button ID / configuration entry |
| `7` | host (`00` in the capture) |
| `8` | press type (`00`, normal press) |
| `9` | program length (`04`) |
| `10..13` | program bytes |
| `14..20` | observed transport trailer/padding, preserved verbatim |

A captured HPAC assignment of native F12 to visible button ID 11 produced:

```text
06 00 0D 09 00 01 0B 00 00 04 F8 00 45 00 02 00 00 00 00 00 00
```

The four-byte native-key program is:

```text
F8 00 <USB keyboard usage> 00
```

For example, usage `45` is F12. An empty program clears a custom entry. The
packet uses size 5 and program length 0:

```text
06 00 0D 05 00 01 <id> <host> 00 00 02 00 00 00 00 00 00 00 00 00 00
```

## Negative Ash/460 entry experiment

A related HP keyboard layout suggested the hypothesis that IDs `12`, `14`,
`15`, `17`, and `18` might represent Print Screen, Home, Page Up, End, and Page
Down. Controlled testing disproved that hypothesis on the tested Ash/460:

1. Native-key programs for those usages were written to the five entries.
2. The keyboard acknowledged the writes and returned all five records in a
   multipart configuration reply (`nb=5`).
3. The same physical keys were tested with and without Fn. Their behavior did
   not change.
4. IDs `12–23` were then assigned unique F13–F24 usages. None of the target
   physical keys emitted the corresponding event on either layer.
5. Every experimental entry was cleared. The reply collapsed to the empty
   configuration (`nb=0`).

The stable physical behavior with Fn Lock enabled was:

| Physical key | No Fn | Fn held |
| --- | --- | --- |
| Stamp / Print Screen | `Win+Space` firmware macro | Print Screen |
| Home | Consumer `0x0192` / `VK_LAUNCH_APP2` | Home |
| End | Esc | End |
| Page Up | Consumer Brightness Up `0x006F` | Page Up |
| Page Down | Consumer Brightness Down `0x0070` | Page Down |

The accepted entries are stored in the active configuration container, but the
five physical Ash keys do not reach that container through the hypothesized
special bits. They are therefore not an exposed navigation-key map for this
hardware path. Raw observations are recorded in `../captures/reports.txt`.

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

The On/On report was applied and the current layer was verified. This is the
only persistent keyboard configuration operation exposed by the utility.
