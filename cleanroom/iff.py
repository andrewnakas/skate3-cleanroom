"""IFF-style FORM containers as used by Paradigm's UltraVision engine (and
others): "FORM" u32 len, 4-char type, then chunks of 4-char tag + u32 size +
data. A chunk tagged GZIP wraps a MIO0 stream: its data is the real tag,
u32 decompressed size, then the MIO0 stream.
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional

from .codec import mio0


@dataclass
class Chunk:
    tag: str
    data: bytes
    compressed: bool = False          # stored inside a GZIP/MIO0 wrapper
    raw: Optional[bytes] = None       # original wrapped payload (round-trip only)


@dataclass
class Form:
    type: str
    chunks: List[Chunk] = field(default_factory=list)

    def find(self, tag):
        return [c for c in self.chunks if c.tag == tag]

    def first(self, tag):
        for c in self.chunks:
            if c.tag == tag:
                return c
        return None


def _tag(b: bytes) -> str:
    return b.decode("latin-1")


def parse_form(buf: bytes, offset: int = 0, keep_raw: bool = False) -> Form:
    if buf[offset:offset + 4] != b"FORM":
        raise ValueError(f"no FORM at {offset:#x}")
    length = struct.unpack_from(">I", buf, offset + 4)[0]
    end = offset + 8 + length
    form = Form(_tag(buf[offset + 8:offset + 12]))
    p = offset + 12
    while p < end:
        tag = buf[p:p + 4]
        size = struct.unpack_from(">I", buf, p + 4)[0]
        data = buf[p + 8:p + 8 + size]
        if tag == b"GZIP":
            inner = _tag(data[0:4])
            dsize = struct.unpack_from(">I", data, 4)[0]
            dec = mio0.decompress(data, 8)
            if len(dec) != dsize:
                raise ValueError("GZIP size mismatch")
            form.chunks.append(Chunk(inner, dec, True, bytes(data) if keep_raw else None))
        else:
            form.chunks.append(Chunk(_tag(tag), bytes(data)))
        p += 8 + size
    if p != end:
        raise ValueError(f"FORM {form.type} chunk overrun ({p:#x} != {end:#x})")
    return form


def form_length(buf: bytes, offset: int = 0) -> int:
    return 8 + struct.unpack_from(">I", buf, offset + 4)[0]


def build_chunk(c: Chunk, reuse_raw: bool = False) -> bytes:
    if c.compressed:
        if reuse_raw and c.raw is not None:
            payload = c.raw
        else:
            stream = mio0.compress(c.data)
            payload = c.tag.encode("latin-1") + struct.pack(">I", len(c.data)) + stream
            payload += b"\0" * (-len(payload) % 8)
        return b"GZIP" + struct.pack(">I", len(payload)) + payload
    return c.tag.encode("latin-1") + struct.pack(">I", len(c.data)) + c.data


def build_form(form: Form, reuse_raw: bool = False) -> bytes:
    body = form.type.encode("latin-1") + b"".join(build_chunk(c, reuse_raw) for c in form.chunks)
    return b"FORM" + struct.pack(">I", len(body)) + body
