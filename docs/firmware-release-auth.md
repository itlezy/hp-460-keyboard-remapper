# Older releases are not an obvious unsigned-update route

The public Ash 1.0, 1.1 and 1.2 application images all contain a device RSA key.
`experiments/compare_release_auth.py` now executes each image's actual startup
literal load, key-setter call and OTA-context initialization block in Unicorn.
It does not supply a replacement key or stub those instructions.

| Image | Startup call | Key setter | Key descriptor | OTA context | Key copy |
| --- | --- | --- | --- | --- | --- |
| 1.0 | `10010980` | `10011854` | `20000964` | `20002304` | `10011452` |
| 1.1 | `1001099E` | `10011878` | `20000964` | `20002304` | `10011476` |
| 1.2 | `1000F1F0` | `1000FAAC` | `20001EF8` | `20003898` | `1000F8C2` |

All addresses are hexadecimal. Each context receives the key at offset `54`.
The keys are RSA-2048, exponent 37. Independent Python modular exponentiation
on each image's inner signature recovers a type-2 block containing exactly
the SHA-256 of that image's application. A one-byte application edit changes
that digest.

Additional static receiver traces in the older releases:

| Image | Receiver | Non-null key branch | RSA call | 32-byte digest comparison |
| --- | --- | --- | --- | --- |
| 1.0 | `10008714` | `10008852` | `10008A8E` -> `1000B734` | `10008ACC`–`10008ADE` |
| 1.1 | `10008734` | `10008872` | `10008AAE` -> `1000B754` | `10008AEC`–`10008AFE` |

The complete older receiver/transfer paths and original older RSA decoders
have not been emulated. The existing 1.2 signature experiment does execute
the original RSA decoder and digest comparison. These findings rule out
assuming the older public images simply omit device authentication; they do
not rule out bugs, alternate loaders or a diagnostic bypass.

No downgrade was attempted. Whether the keyboard accepts a signed downgrade,
enforces rollback restrictions, or checks an application signature at boot
is not established. Windows administrator privileges and HPAC's `.FW2` mode
do not by themselves remove device authentication.

## Reproduce

Install the optional Unicorn dependency, then supply the three public files:

```powershell
PYTHON.EXE experiments/compare_release_auth.py C:\images\Ash_1000.FW C:\images\Ash_1100.FW C:\images\Ash_1200.FW
```

The script accepts only the exact known SHA-256 hashes and never opens HID or
modifies its inputs. Images and proprietary disassembly are not distributed.
