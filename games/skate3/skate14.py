"""SKATE14 map container: iterate texture payloads and rewrite them.

Layout (engine tools/asset_pipeline/map_writer.py, refresh_textures.py):
  header, materials, textures [name, w, h, space, method, size, payload],
  then vertices/indices/rails/extensions (RWCM collision, WMET json) = "tail".
Textures are RGBA8 stored bottom-up (cube maps top-down), method 0 raw / 1 zlib.
Everything except texture payloads is copied byte for byte.
"""
import os
import struct
import subprocess
import tempfile
import zlib

import numpy as np


class _R:
    def __init__(self, f):
        self.f = f

    def read(self, n):
        b = self.f.read(n)
        if len(b) != n:
            raise ValueError("truncated SKATE14")
        return b

    def u(self):
        return struct.unpack("<I", self.read(4))[0]

    def s(self):
        return self.read(self.u()).decode("utf-8")


def _skip_prefix(r):
    if r.read(8) != b"SKATE14\0" or r.u() != 0x12345678:
        raise ValueError("not SKATE14")
    r.s()
    r.read(49 * 4)
    counts = [r.u() for _ in range(9)]
    for _ in range(counts[0]):
        r.s()
        r.read(4 + 7 * 4 + 8 + 4 + 16 + 4 + 16)
        if r.u():
            r.read(16); r.s(); r.read(8)
            for _ in range(r.u()):
                r.s(); r.read(16)
            for _ in range(r.u()):
                r.s()
                for _ in range(r.u()):
                    r.s()
            r.s()
    return counts


# Newer containers (SKATE15: transformed storage, texture references) are read
# through the engine's own parser, examples/dump_textures.rs.
DUMP_EXE = os.environ.get(
    "SKATE_DUMP_TEXTURES",
    r"D:\n64work\skate3\target\debug\examples\dump_textures.exe")


def _dumped(path):
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "t.bin")
        subprocess.run([DUMP_EXE, path, out], check=True, capture_output=True)
        with open(out, "rb") as f:
            r = _R(f)
            if r.read(4) != b"SKTX":
                raise ValueError("bad texture dump")
            for _ in range(r.u()):
                name = r.s()
                w, h, _space = r.u(), r.u(), r.u()
                px = r.read(w * h * 4)
                a = np.frombuffer(px, np.uint8).reshape(-1, w, 4)
                yield name, w, h, a[::-1], False


def textures(path):
    """Yield (name, w, h, rgba top-down HxWx4 uint8, cube)."""
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic != b"SKATE14\0":
        yield from _dumped(path)
        return
    with open(path, "rb") as f:
        r = _R(f)
        counts = _skip_prefix(r)
        for _ in range(counts[1]):
            name = r.s()
            w, h, _space = r.u(), r.u(), r.u()
            method, size = r.u(), r.u()
            raw = r.read(size)
            if method not in (0, 1):
                raise ValueError(f"texture method {method}")
            px = zlib.decompress(raw) if method else raw
            cube = len(px) == w * h * 4 * 6
            a = np.frombuffer(px, np.uint8).reshape(-1, w, 4)
            yield name, w, h, (a if cube or a.shape[0] != h else a[::-1]), cube


def rewrite(src, dst, fn):
    """fn(name, w, h, rgba_topdown, cube) -> new rgba (same shape). Returns texture count."""
    n = 0
    with open(src, "rb") as f, open(dst, "wb") as o:
        r = _R(f)
        counts = _skip_prefix(r)
        end = f.tell(); f.seek(0); o.write(f.read(end))
        for _ in range(counts[1]):
            start = f.tell()
            name = r.s()
            w, h, _space = r.u(), r.u(), r.u()
            head_end = f.tell()
            method, size = r.u(), r.u()
            raw = r.read(size)
            px = zlib.decompress(raw) if method else raw
            cube = len(px) == w * h * 4 * 6
            a = np.frombuffer(px, np.uint8).reshape(-1, w, 4)
            flip = not cube and a.shape[0] == h
            new = np.ascontiguousarray(fn(name, w, h, a[::-1] if flip else a, cube), np.uint8)
            if new.shape != a.shape:
                raise ValueError(f"shape changed: {name}")
            out = (new[::-1] if flip else new).tobytes()
            f.seek(start); o.write(f.read(head_end - start)); f.seek(head_end + 8 + size)
            z = zlib.compress(out, 6)
            o.write(struct.pack("<II", 1, len(z))); o.write(z)
            n += 1
        while chunk := f.read(1 << 20):
            o.write(chunk)
    return n


def tail_sections(path):
    """Return {'wmet': dict or None, 'tail_bytes': int} for inspection."""
    import json
    with open(path, "rb") as f:
        r = _R(f)
        counts = _skip_prefix(r)
        for _ in range(counts[1]):
            r.s(); r.read(12); r.u(); f.seek(r.u(), 1)
        pos = f.tell(); f.seek(0, 2); size = f.tell()
        f.seek(pos)
        blob = f.read()
    i = blob.rfind(b"WMET")
    wmet = None
    if i >= 0:
        try:
            # tag, u32 1, u32 len, then stored(method, size, data)
            _one, ln, method, sz = struct.unpack("<IIII", blob[i + 4:i + 20])
            d = blob[i + 20:i + 20 + sz]
            wmet = json.loads(zlib.decompress(d) if method == 1 else d)
        except Exception:
            wmet = "unparsed"
    return {"wmet": wmet, "tail_bytes": size - pos}
