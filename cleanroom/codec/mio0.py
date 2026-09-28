"""MIO0 compression (Nintendo LZ variant used by many N64 titles).

Layout: "MIO0", u32 decompressed size, u32 offset of back-reference stream,
u32 offset of literal stream, then a bitstream of u32 words (MSB first):
1 = copy one literal byte, 0 = back-reference u16 (len = (v >> 12) + 3,
distance = (v & 0xFFF) + 1).

The compressor is our own greedy/lazy LZ; it need not match Nintendo's
encoder byte-for-byte, only decode to the same data.
"""
import struct

MAGIC = b"MIO0"
MIN_MATCH = 3
MAX_MATCH = 18
WINDOW = 0x1000


def decompress(src: bytes, offset: int = 0) -> bytes:
    if src[offset:offset + 4] != MAGIC:
        raise ValueError("not MIO0 data")
    size, comp_off, raw_off = struct.unpack_from(">III", src, offset + 4)
    comp = offset + comp_off
    raw = offset + raw_off
    bits = offset + 16
    out = bytearray()
    word = 0
    nbits = 0
    while len(out) < size:
        if nbits == 0:
            word = struct.unpack_from(">I", src, bits)[0]
            bits += 4
            nbits = 32
        nbits -= 1
        if (word >> nbits) & 1:
            out.append(src[raw])
            raw += 1
        else:
            v = (src[comp] << 8) | src[comp + 1]
            comp += 2
            length = (v >> 12) + 3
            dist = (v & 0xFFF) + 1
            start = len(out) - dist
            if start < 0:
                raise ValueError("MIO0 back-reference before start of output")
            for i in range(length):
                out.append(out[start + i])
    return bytes(out[:size])


def compressed_size(src: bytes, offset: int = 0) -> int:
    """Byte length of a MIO0 stream (header + all three streams, unpadded)."""
    size, comp_off, raw_off = struct.unpack_from(">III", src, offset + 4)
    # Walk the bitstream to count literals and references.
    bits = offset + 16
    produced = lits = refs = 0
    word = nbits = 0
    comp = offset + comp_off
    while produced < size:
        if nbits == 0:
            word = struct.unpack_from(">I", src, bits)[0]
            bits += 4
            nbits = 32
        nbits -= 1
        if (word >> nbits) & 1:
            produced += 1
            lits += 1
        else:
            v = (src[comp + refs * 2] << 8) | src[comp + refs * 2 + 1]
            refs += 1
            produced += (v >> 12) + 3
    return max(comp_off + refs * 2, raw_off + lits)


def _find_match(data, pos, chains, n):
    best_len = 0
    best_dist = 0
    if pos + MIN_MATCH > n:
        return 0, 0
    key = data[pos:pos + MIN_MATCH]
    cand = chains.get(key)
    if not cand:
        return 0, 0
    limit = min(MAX_MATCH, n - pos)
    lo = pos - WINDOW
    # Newest candidates first; cap the search to keep Python fast enough.
    tried = 0
    for c in reversed(cand):
        if c < lo:
            break
        length = MIN_MATCH
        while length < limit and data[c + length] == data[pos + length]:
            length += 1
        if length > best_len:
            best_len = length
            best_dist = pos - c
            if length == limit:
                break
        tried += 1
        if tried >= 256:
            break
    return best_len, best_dist


def compress(data: bytes) -> bytes:
    data = bytes(data)
    n = len(data)
    chains: dict = {}
    flags = []
    comp = bytearray()
    raw = bytearray()

    def insert(p):
        if p + MIN_MATCH <= n:
            k = data[p:p + MIN_MATCH]
            lst = chains.get(k)
            if lst is None:
                chains[k] = [p]
            else:
                lst.append(p)
                if len(lst) > 1024:
                    del lst[:512]

    pos = 0
    while pos < n:
        length, dist = _find_match(data, pos, chains, n)
        if length >= MIN_MATCH:
            # Lazy evaluation: prefer a longer match starting one byte later.
            insert(pos)
            nlen, _ = _find_match(data, pos + 1, chains, n)
            if nlen > length + 1:
                flags.append(1)
                raw.append(data[pos])
                pos += 1
                continue
            flags.append(0)
            v = ((length - 3) << 12) | (dist - 1)
            comp += bytes(((v >> 8) & 0xFF, v & 0xFF))
            for p in range(pos + 1, pos + length):
                insert(p)
            pos += length
        else:
            insert(pos)
            flags.append(1)
            raw.append(data[pos])
            pos += 1

    words = bytearray()
    for i in range(0, len(flags), 32):
        chunk = flags[i:i + 32]
        w = 0
        for j, f in enumerate(chunk):
            if f:
                w |= 1 << (31 - j)
        words += struct.pack(">I", w)
    comp_off = 16 + len(words)
    raw_off = comp_off + len(comp)
    out = MAGIC + struct.pack(">III", n, comp_off, raw_off) + words + comp + raw
    return bytes(out)
