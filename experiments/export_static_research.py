"""Create local, ignored firmware/HPAC disassembly reports from installed binaries."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hpac", type=Path)
    parser.add_argument("firmware", type=Path)
    parser.add_argument("--rizin", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = project / "local-research"
    output.mkdir(exist_ok=True)

    def save(name, command):
        result = subprocess.run([str(part) for part in command], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        with (output / name).open("w", encoding="utf-8") as stream:
            # Generated reports contain no input filesystem paths.
            stream.write(result.stdout)
        print(name)

    for address, length in ((0x1400E1D00, 0x200), (0x1400E1F00, 0x19D), (0x1400F4390, 0x52B), (0x1400E55A0, 0x250), (0x1400E57F0, 0x2EA), (0x1400FE330, 0x7B0), (0x1400FB190, 0x640), (0x1400F8FC0, 0x108)):
        save(f"hpac-{address:X}.asm.txt", [sys.executable, project / "hpac_static.py", args.hpac, "--function", hex(address), "--bytes", hex(length)])
    for address, count in ((0x100072F8, 260), (0x10004284, 70), (0x100038B4, 150), (0x10002D5C, 96), (0x100031D8, 95), (0x100064CC, 610), (0x10009EA4, 140), (0x1000ABB8, 145), (0x1000FAAC, 16), (0x1000F89C, 85), (0x1000F198, 85), (0x100055FA, 1000), (0x10014820, 120), (0x1000A916, 75)):
        save(f"ash-{address:X}.asm.txt", [args.rizin, "-q", "-a", "arm", "-b", "16", "-m", "0x0FFFFFF3", "-e", "asm.cpu=cortexm", "-e", "scr.color=0", "-c", f"pd {count} @ {address}", args.firmware])
    save("native-branch-emulation.txt", [sys.executable, project / "experiments/validate_native_branch.py", args.firmware])
    save("signed-container-verification.txt", [sys.executable, project / "experiments/inspect_signed_container.py", args.hpac, args.firmware])
    save("matrix-scanner-emulation.txt", [sys.executable, project / "experiments/validate_matrix_scanner.py", args.firmware])
    save("hpac-local-flag-emulation.txt", [sys.executable, project / "experiments/validate_hpac_local_flag.py", args.hpac, args.firmware])
    save("device-signature-emulation.txt", [sys.executable, project / "experiments/validate_device_signature.py", args.firmware])
    save("program-vm-emulation.txt", [sys.executable, project / "experiments/validate_program_vm.py", args.firmware])
    save("consumer-pipeline-emulation.txt", [sys.executable, project / "experiments/validate_consumer_programs.py", args.firmware])
    save("key-mask-emulation.txt", [sys.executable, project / "experiments/validate_key_mask_program.py", args.firmware])
    save("layer-flag-emulation.txt", [sys.executable, project / "experiments/validate_layer_flag.py", args.firmware])
    save("native-mode-access-audit.txt", [sys.executable, project / "experiments/audit_native_mode_access.py", args.firmware])
    for address, count in ((0x1000464C, 48), (0x1000E8D8, 29), (0x10012B68, 35),
                           (0x1000DB90, 24), (0x1000FB34, 4), (0x1001054C, 110),
                           (0x1001070C, 36), (0x10010668, 40), (0x1000F098, 80),
                           (0x1000270C, 98)):
        save(f"ash-{address:X}.asm.txt", [args.rizin, "-q", "-a", "arm", "-b", "16", "-m", "0x0FFFFFF3", "-e", "asm.cpu=cortexm", "-e", "scr.color=0", "-c", f"pd {count} @ {address}", args.firmware])
    print("Local reports exported; proprietary disassembly remains ignored by Git.")


if __name__ == "__main__":
    main()
