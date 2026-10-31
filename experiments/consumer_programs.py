"""Build research consumer-only key programs offline. Never accesses hardware."""

from __future__ import annotations

import json

# button ID, consumer usage, Windows event name
TARGETS = (
    (6, 0x0224, "Browser_Back"),
    (7, 0x0225, "Browser_Forward"),
    (8, 0x0227, "Browser_Refresh"),
    (9, 0x0226, "Browser_Stop"),
    (10, 0x0221, "Browser_Search"),
    (11, 0x022A, "Browser_Favorites"),
)


class Bits:
    def __init__(self):
        self.bits = []

    def put(self, value, width):
        self.bits.extend((value >> bit) & 1 for bit in range(width))

    def scalar(self, value=None, *, variable=None):
        self.put(variable is None, 1)
        self.put(value if variable is None else variable, 8 if variable is None else 4)

    def consumer(self, usage, *, auto_release):
        self.put(27, 5)
        self.put(auto_release, 1)
        self.put(3, 2)  # a literal 16-bit blob item
        self.put(usage, 16)
        self.put(0, 2)  # end of blob

    def blob(self, items):
        for kind, value in items:
            self.put({"variable": 1, "byte": 2, "word": 3}[kind], 2)
            self.put(value, {"variable": 4, "byte": 8, "word": 16}[kind])
        self.put(0, 2)

    def arithmetic(self, opcode, register, value=None, *, variable=None):
        self.put(opcode, 5)
        self.put(register, 4)
        self.scalar(value, variable=variable)

    def patch_jump(self, position, destination):
        delta = destination - (position + 10)
        if not -256 <= delta <= 255:
            raise ValueError("Short VM branch out of range")
        # Bit 9 clear selects signed 9-bit displacement; bit 8 is its sign.
        self.bits[position:position + 10] = [(delta >> bit) & 1 for bit in range(9)] + [0]

    def finish(self):
        result = bytearray((len(self.bits) + 7) // 8)
        for index, value in enumerate(self.bits):
            result[index // 8] |= value << (index % 8)
        return bytes(result)


def consumer_tap(usage: int) -> bytes:
    if not 0 < usage <= 0xFFFF:
        raise ValueError("Invalid consumer usage")
    stream = Bits()
    stream.consumer(usage, auto_release=True)
    stream.put(0, 5)
    return stream.finish()


def consumer_held(button_id: int, usage: int) -> bytes:
    """Hold consumer usage until the selected incoming special-key bit clears.

    Research candidate: one interpreter instance/one consumer usage at a time.
    Registers 0 and 5 are VM variables, not arbitrary memory addresses.
    """
    if not 6 <= button_id <= 11 or not 0 < usage <= 0xFFFF:
        raise ValueError("Held candidate supports F7-F12 only")
    stream = Bits()
    stream.consumer(usage, auto_release=False)
    loop = len(stream.bits)
    stream.arithmetic(4, 5, 0)                 # variable[5] *= 0
    stream.arithmetic(1, 5, variable=0)        # variable[5] += current special-key mask
    stream.arithmetic(5, 5, 64)               # divide off low six key bits
    stream.arithmetic(5, 5, 1 << (button_id - 6))
    stream.arithmetic(7, 5, 1)                # isolate selected bit
    stream.put(19, 5)                         # if variable[5] != 0, branch to wait
    stream.put(5, 4)
    stream.scalar(0)
    branch_to_wait = len(stream.bits)
    stream.put(0, 10)
    stream.consumer(0, auto_release=False)    # explicit key release
    stream.put(0, 5)                          # end
    wait = len(stream.bits)
    stream.put(21, 5)                         # yield 20 ms (unsigned immediate expression)
    stream.put(1, 1)
    stream.put(0, 1)
    stream.put(20, 8)
    stream.put(26, 5)                         # unconditional relative branch
    branch_to_loop = len(stream.bits)
    stream.put(0, 10)
    stream.patch_jump(branch_to_wait, wait)
    stream.patch_jump(branch_to_loop, loop)
    return stream.finish()


if __name__ == "__main__":
    print(json.dumps({"status": "OFFLINE CANDIDATES; physical tests pending", "targets": [
        {"key": f"F{button_id + 1}", "button_id": button_id, "usage": f"0x{usage:04X}",
         "event": name, "tap_program": consumer_tap(usage).hex(" "),
         "held_program": consumer_held(button_id, usage).hex(" ")}
        for button_id, usage, name in TARGETS]}, indent=2))
