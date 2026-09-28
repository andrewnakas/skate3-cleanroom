"""Minimal PNG read/write (8-bit greyscale, grey+alpha, RGB, RGBA, palette)
with numpy only, so the harness needs no imaging library."""
import struct
import zlib

import numpy as np


def write(path, rgba):
    rgba = np.ascontiguousarray(rgba, np.uint8)
    h, w = rgba.shape[:2]
    ch = rgba.shape[2] if rgba.ndim == 3 else 1
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[ch]
    raw = b"".join(b"\0" + rgba[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def _unfilter(data, h, stride, bpp):
    out = np.zeros((h, stride), np.uint8)
    prev = np.zeros(stride, np.int32)
    pos = 0
    for y in range(h):
        ft = data[pos]; pos += 1
        line = np.frombuffer(data, np.uint8, stride, pos).astype(np.int32); pos += stride
        if ft == 0:
            cur = line
        elif ft == 2:
            cur = (line + prev) & 0xFF
        else:
            cur = np.zeros(stride, np.int32)
            for x in range(stride):
                a = cur[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                if ft == 1:
                    p = a
                elif ft == 3:
                    p = (a + b) >> 1
                else:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    p = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[x] = (line[x] + p) & 0xFF
        out[y] = cur
        prev = cur
    return out


def read(path) -> np.ndarray:
    """Return an (h, w, 4) uint8 RGBA array."""
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    pos, idat, plte, trns = 8, b"", None, None
    while pos < len(buf):
        n, tag = struct.unpack(">I4s", buf[pos:pos + 8])
        data = buf[pos + 8:pos + 8 + n]
        pos += 12 + n
        if tag == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", data)
        elif tag == b"PLTE":
            plte = np.frombuffer(data, np.uint8).reshape(-1, 3)
        elif tag == b"tRNS":
            trns = np.frombuffer(data, np.uint8)
        elif tag == b"IDAT":
            idat += data
    if depth != 8 or interlace:
        raise ValueError(f"{path}: only 8-bit non-interlaced PNGs are supported")
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    px = _unfilter(zlib.decompress(idat), h, w * ch, ch).reshape(h, w, ch)
    if ctype == 3:
        rgb = plte[px[..., 0]]
        a = np.full((h, w), 255, np.uint8)
        if trns is not None:
            lut = np.full(256, 255, np.uint8)
            lut[:len(trns)] = trns
            a = lut[px[..., 0]]
        return np.dstack([rgb, a])
    if ch == 1:
        return np.dstack([px[..., 0]] * 3 + [np.full((h, w), 255, np.uint8)])
    if ch == 2:
        return np.dstack([px[..., 0]] * 3 + [px[..., 1]])
    if ch == 3:
        return np.dstack([px, np.full((h, w), 255, np.uint8)])
    return px
