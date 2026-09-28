"""ROM image helpers: byte-order normalisation, loading, header and CRC.

`load_retail` is dirty-room only: generators must never import it
(tests/test_cleanroom_rules.py enforces this).
"""
import os
import struct
import zipfile

Z64_MAGIC = b"\x80\x37\x12\x40"
V64_MAGIC = b"\x37\x80\x40\x12"
N64_MAGIC = b"\x40\x12\x37\x80"


def to_z64(data: bytes) -> bytes:
    head = data[:4]
    if head == Z64_MAGIC:
        return bytes(data)
    b = bytearray(data)
    if head == V64_MAGIC:
        b[0::2], b[1::2] = data[1::2], data[0::2]
        return bytes(b)
    if head == N64_MAGIC:
        for i in range(0, len(b) - 3, 4):
            b[i:i + 4] = data[i:i + 4][::-1]
        return bytes(b)
    raise ValueError("not an N64 ROM image")


def load_retail(path: str) -> bytes:
    """Read a .z64/.v64/.n64 or a zip holding one, returned big-endian."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist()
                     if os.path.splitext(n)[1].lower() in (".z64", ".n64", ".v64")]
            if not names:
                raise ValueError(f"no ROM inside {path}")
            data = z.read(names[0])
    else:
        with open(path, "rb") as f:
            data = f.read()
    return to_z64(data)


# --- CIC-6102 checksum --------------------------------------------------------

_CRC_START = 0x1000
_CRC_LEN = 0x100000
_SEED_6102 = 0xF8CA4DDC


def _rol(v, n):
    v &= 0xFFFFFFFF
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF if n else v


def cic6102_crc(rom: bytes):
    """Return (crc1, crc2) as computed by the 6102 IPL3 over 0x1000..0x101000."""
    rom = bytes(rom).ljust(_CRC_START + _CRC_LEN, b"\0")
    t1 = t2 = t3 = t4 = t5 = t6 = _SEED_6102
    words = struct.unpack_from(">%dI" % (_CRC_LEN // 4), rom, _CRC_START)
    M = 0xFFFFFFFF
    for d in words:
        if ((t6 + d) & M) < t6:
            t4 = (t4 + 1) & M
        t6 = (t6 + d) & M
        t3 ^= d
        r = _rol(d, d & 0x1F)
        t5 = (t5 + r) & M
        if t2 > d:
            t2 ^= r
        else:
            t2 ^= t6 ^ d
        t1 = (t1 + (t5 ^ d)) & M
    return (t6 ^ t4 ^ t3) & M, (t5 ^ t2 ^ t1) & M


def build_header(title: str, game_id: bytes, entry: int, crc=(0, 0),
                 region: bytes = b"E", version: int = 0) -> bytes:
    """A 0x40-byte z64 header written from scratch (no retail bytes)."""
    h = bytearray(0x40)
    h[0:4] = Z64_MAGIC
    struct.pack_into(">I", h, 0x04, 0x0000000F)   # clock rate word
    struct.pack_into(">I", h, 0x08, entry)
    struct.pack_into(">I", h, 0x0C, 0x00001444)   # libultra release
    struct.pack_into(">II", h, 0x10, *crc)
    t = title.encode("ascii")[:20].ljust(20, b" ")
    h[0x20:0x34] = t
    h[0x3B] = ord("N")
    h[0x3C:0x3E] = game_id[:2]
    h[0x3E:0x3F] = region[:1]
    h[0x3F] = version
    return bytes(h)


def finalize_crc(image: bytearray) -> None:
    crc = cic6102_crc(image)
    struct.pack_into(">II", image, 0x10, *crc)
