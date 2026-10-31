"""Verify HPAC firmware container signatures offline using its embedded public key."""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


def main() -> None:
    import pefile

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hpac", type=Path)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()
    pe_data = args.hpac.read_bytes()
    if hashlib.sha256(pe_data).hexdigest() != "9a9bbf2d871463ac411f059836e2e551a3031ceb47a212adbac8ee6a13b8e488":
        raise SystemExit("Requires the analyzed HPAC 2.21.4522.0 image")
    pe = pefile.PE(data=pe_data, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase

    def bignum(va):
        rva = va - base
        length = struct.unpack("<I", pe.get_data(rva, 4))[0]
        return int.from_bytes(pe.get_data(rva + 4, length * 4), "little")

    modulus = bignum(0x140625000)
    exponent = bignum(0x140624ED8)
    print(f"HPAC public key: modulus bits={modulus.bit_length()}, exponent={exponent}")
    for image in args.images:
        data = image.read_bytes()
        print(f"IMAGE {image.name} SHA256={hashlib.sha256(data).hexdigest()}")
        offset = 0
        while offset < len(data):
            if len(data) - offset < 9:
                raise SystemExit("Truncated record header")
            record_length, kind = struct.unpack_from("<IB", data, offset)
            payload_length = struct.unpack_from("<I", data, offset + 5)[0]
            if record_length < 9 or offset + record_length > len(data) or payload_length > record_length - 9:
                raise SystemExit("Invalid record bounds")
            payload = data[offset + 9:offset + 9 + payload_length]
            trailer = data[offset + 9 + payload_length:offset + record_length]
            print(f"record file=0x{offset:X} length=0x{record_length:X} type={kind} payload=0x{payload_length:X} trailer={len(trailer)}")
            digest = hashlib.sha256(payload).digest()
            if kind == 0 and len(payload) > 8:
                inner_length = struct.unpack_from("<I", payload)[0]
                inner_block = payload[inner_length + 8:inner_length + 264]
                marker = payload[inner_length + 4:inner_length + 8]
                print(f"inner image length=0x{inner_length:X}, opaque_block_length={len(inner_block)}, marker={marker.hex(' ')}")
                if len(inner_block) == 256:
                    recovered_inner = pow(int.from_bytes(inner_block, "big"), exponent, modulus).to_bytes(256, "big")
                    print(f"candidate_known_key_prefix={recovered_inner[:2].hex()}, candidate_digest_matches={recovered_inner[-32:] == hashlib.sha256(payload[4:4 + inner_length]).digest()}")
                    print("Inner block purpose and device-side enforcement are unproven; this failed candidate-key test does not establish a signature.")
            for block_offset in range(4, len(trailer), 256):
                signature = trailer[block_offset:block_offset + 256]
                if len(signature) != 256:
                    continue
                for endian in ("big", "little"):
                    recovered = pow(int.from_bytes(signature, endian), exponent, modulus).to_bytes(256, "big")
                    if recovered[:2] in (b"\x00\x01", b"\x00\x02"):
                        separator = recovered.find(b"\x00", 2)
                        message = recovered[separator + 1:]
                        print(f"RSA recovered endian={endian} type={recovered[1]} message_length={len(message)} SHA256_matches={message[-32:] == digest}")
                        patched_payload = bytearray(payload)
                        if image.name == "Ash_1200.FW" and kind == 0:
                            patched_payload[0x7424:0x7428] = bytes.fromhex("2D D0 2C E0")
                            print(f"candidate_patch_SHA256_matches={message[-32:] == hashlib.sha256(patched_payload).digest()}")
            offset += record_length
        footer = len(data) - 821
        magic = data[footer + 24:footer + 32]
        print(f"fwupd HPAC footer=0x{footer:X}, magic={magic.hex()}, matches={magic == bytes.fromhex('55 AA 55 AA 55 AA 55 AA')}")


if __name__ == "__main__":
    main()
