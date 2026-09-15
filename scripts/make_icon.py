"""Create the project-owned Windows icon from the Book-OCR green-book motif."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "book-ocr.ico"


def png(size: int) -> bytes:
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            edge = min(x, y, size - 1 - x, size - 1 - y)
            green = (23, 114, 69, 255) if edge >= size // 12 else (18, 91, 55, 255)
            # Two white book pages with a centre spine and green text strokes.
            left = size * 0.20 <= x <= size * 0.48 and size * 0.24 <= y <= size * 0.76
            right = size * 0.52 <= x <= size * 0.80 and size * 0.24 <= y <= size * 0.76
            color = green
            if left or right:
                color = (247, 251, 248, 255)
                line_y = y in (int(size * .39), int(size * .50))
                if line_y and ((left and x < size * .42) or (right and x > size * .58)):
                    color = (23, 114, 69, 255)
            pixels.extend(color)
    raw = zlib.compress(bytes(pixels), 9)
    def chunk(kind: bytes, value: bytes) -> bytes:
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def main() -> None:
    images = [png(size) for size in (16, 32, 48, 64, 128, 256)]
    offset = 6 + 16 * len(images)
    entries = []
    for size, image in zip((16, 32, 48, 64, 128, 256), images):
        entries.append(struct.pack("<BBBBHHII", 0 if size == 256 else size, 0 if size == 256 else size, 0, 0, 1, 32, len(image), offset))
        offset += len(image)
    OUT.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(images))


if __name__ == "__main__":
    main()
