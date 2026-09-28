"""Tiny big-endian reader/writer used by the format codecs."""
import struct


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def _u(self, fmt):
        v = struct.unpack_from(">" + fmt, self.data, self.pos)
        self.pos += struct.calcsize(">" + fmt)
        return v[0] if len(v) == 1 else v

    def u8(self): return self._u("B")
    def s8(self): return self._u("b")
    def u16(self): return self._u("H")
    def s16(self): return self._u("h")
    def u32(self): return self._u("I")
    def s32(self): return self._u("i")
    def f32(self): return self._u("f")

    def f32s(self, n):
        v = struct.unpack_from(">%df" % n, self.data, self.pos)
        self.pos += 4 * n
        return list(v)

    def bytes(self, n):
        b = self.data[self.pos:self.pos + n]
        if len(b) != n:
            raise ValueError("read past end")
        self.pos += n
        return bytes(b)

    def remaining(self):
        return len(self.data) - self.pos

    def done(self):
        return self.pos >= len(self.data)


class Writer:
    def __init__(self):
        self.buf = bytearray()

    def _p(self, fmt, *v):
        self.buf += struct.pack(">" + fmt, *v)

    def u8(self, v): self._p("B", v & 0xFF)
    def s8(self, v): self._p("b", v)
    def u16(self, v): self._p("H", v & 0xFFFF)
    def s16(self, v): self._p("h", v)
    def u32(self, v): self._p("I", v & 0xFFFFFFFF)
    def s32(self, v): self._p("i", v)
    def f32(self, v): self._p("f", v)

    def f32s(self, vs):
        for v in vs:
            self.f32(v)

    def bytes(self, b):
        self.buf += b

    def getvalue(self):
        return bytes(self.buf)


def f32_bits(v: float) -> int:
    return struct.unpack(">I", struct.pack(">f", v))[0]


# N64 Vtx (gbi.h Vtx_t): s16 ob[3], u16 flag, s16 tc[2], u8 cn[4]
VTX_SIZE = 16


def parse_vtx(data: bytes):
    out = []
    for i in range(0, len(data), VTX_SIZE):
        x, y, z, flag, s, t, r, g, b, a = struct.unpack_from(">hhhHhhBBBB", data, i)
        out.append([x, y, z, flag, s, t, r, g, b, a])
    return out


def build_vtx(vtx) -> bytes:
    return b"".join(struct.pack(">hhhHhhBBBB", *v) for v in vtx)
