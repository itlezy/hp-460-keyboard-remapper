"""Read-only HPAC string/address inventory. Optional dependency: pefile."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--pattern", default=r"firmware|bootloader|flash|OTA|DFU|readMemory|signature|PAR28|KB28")
    parser.add_argument("--xrefs", action="store_true", help="find RIP-relative references (requires capstone)")
    parser.add_argument("--function", type=lambda s: int(s, 0), help="disassemble containing x64 unwind function")
    parser.add_argument("--bytes", type=lambda s: int(s, 0), help="override disassembly span for chained unwind fragments")
    args = parser.parse_args()
    import pefile

    data = args.image.read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    if args.function is not None:
        import capstone

        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXCEPTION"], pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        imports = {item.address: item.name.decode(errors="replace") for library in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) for item in library.imports if item.name}
        rva = args.function - pe.OPTIONAL_HEADER.ImageBase
        for entry in getattr(pe, "DIRECTORY_ENTRY_EXCEPTION", []):
            start, end = entry.struct.BeginAddress, entry.struct.EndAddress
            if start <= rva < end:
                if args.bytes is not None:
                    end = start + args.bytes
                print(f"unwind function 0x{pe.OPTIONAL_HEADER.ImageBase + start:X}..0x{pe.OPTIONAL_HEADER.ImageBase + end:X}")
                engine = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
                for address, size, mnemonic, operands in engine.disasm_lite(pe.get_data(start, end - start), pe.OPTIONAL_HEADER.ImageBase + start):
                    comment = ""
                    ref = re.search(r"\[rip ([+-]) (0x[0-9a-f]+)\]", operands)
                    if ref:
                        target = address + size + int(ref[2], 16) * (1 if ref[1] == "+" else -1)
                        if target in imports:
                            comment = " ; " + imports[target]
                    print(f"0x{address:X}: {mnemonic:8} {operands}{comment}")
                return
        raise SystemExit("No containing unwind function found")
    pattern = re.compile(args.pattern, re.IGNORECASE)
    print(f"SHA256 {hashlib.sha256(data).hexdigest()}")
    targets = {}
    for encoding, regex in (("ascii", rb"[\x20-\x7e]{5,}"), ("utf16", rb"(?:[\x20-\x7e]\x00){5,}")):
        for match in re.finditer(regex, data):
            value = match.group().decode("ascii" if encoding == "ascii" else "utf-16-le")
            if not pattern.search(value):
                continue
            try:
                address = pe.OPTIONAL_HEADER.ImageBase + pe.get_rva_from_offset(match.start())
            except pefile.PEFormatError:
                continue
            # Avoid embedding large compressed resources or Qt-generated blobs.
            if len(value) <= 350:
                print(f"file=0x{match.start():08X} VA=0x{address:X} {encoding} {value}")
                targets[address] = value
    if args.xrefs:
        import capstone

        engine = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        engine.skipdata = True
        for section in pe.sections:
            if not section.Characteristics & 0x20000000:
                continue
            for address, size, mnemonic, operands in engine.disasm_lite(section.get_data(), pe.OPTIONAL_HEADER.ImageBase + section.VirtualAddress):
                match = re.search(r"\[rip ([+-]) (0x[0-9a-f]+)\]", operands)
                if match:
                    displacement = int(match[2], 16) * (1 if match[1] == "+" else -1)
                    target = address + size + displacement
                    if target in targets:
                        print(f"XREF 0x{address:X} -> 0x{target:X}: {mnemonic} {operands}: {targets[target]}")


if __name__ == "__main__":
    main()
