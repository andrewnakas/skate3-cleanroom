"""libultra compressed MIDI sequences (ALCSeq), as read by cseq.c.

Header: s32 trackOffset[16] (0 = unused), s32 division. Each track is a
stream of (varlen delta, event). Differences from SMF: note-on carries a
varlen duration after velocity (no note-offs), 0xFE starts a back-reference
(u16 distance, u8 length) unless doubled (0xFE 0xFE = literal 0xFE), and
meta 0x2E/0x2D are loop start/end.

`decode` expands back-references and returns per-track event lists;
`encode` writes tracks without back-references (always valid).
"""
import struct

BLOCK = 0xFE
META = 0xFF
META_TEMPO = 0x51
META_EOT = 0x2F
LOOPSTART = 0x2E
LOOPEND = 0x2D


class _Track:
    def __init__(self, data, pos):
        self.d = data
        self.p = pos
        self.bu = None
        self.bulen = 0

    def byte(self):
        if self.bulen:
            b = self.d[self.bu]
            self.bu += 1
            self.bulen -= 1
            return b
        b = self.d[self.p]
        self.p += 1
        if b == BLOCK:
            nb = self.d[self.p]
            self.p += 1
            if nb != BLOCK:
                back = (nb << 8) | self.d[self.p]
                self.p += 1
                ln = self.d[self.p]
                self.p += 1
                self.bu = self.p - (back + 4)
                self.bulen = ln
                b = self.d[self.bu]
                self.bu += 1
                self.bulen -= 1
        return b

    def varlen(self):
        v = self.byte()
        if v & 0x80:
            v &= 0x7F
            while True:
                c = self.byte()
                v = (v << 7) + (c & 0x7F)
                if not c & 0x80:
                    break
        return v


def decode(data: bytes, max_events=200000):
    offs = struct.unpack_from(">16i", data, 0)
    division = struct.unpack_from(">i", data, 64)[0]
    tracks = {}
    for t, off in enumerate(offs):
        if not off:
            continue
        tr = _Track(data, off)
        ev = []
        time = 0
        last = 0
        delta = tr.varlen()
        for _ in range(max_events):
            time += delta
            st = tr.byte()
            if st == META:
                typ = tr.byte()
                if typ == META_TEMPO:
                    b = [tr.byte() for _ in range(3)]
                    ev.append((time, "tempo", (b[0] << 16) | (b[1] << 8) | b[2]))
                    last = 0
                elif typ == META_EOT:
                    ev.append((time, "end"))
                    break
                elif typ == LOOPSTART:
                    tr.byte(); tr.byte()
                    ev.append((time, "loopstart"))
                    last = 0
                elif typ == LOOPEND:
                    cnt = tr.byte(); cur = tr.byte()
                    for _ in range(4):
                        tr.byte()
                    ev.append((time, "loopend", cnt))
                    last = 0
                else:
                    ev.append((time, "meta?", typ))
                    break
            else:
                if st & 0x80:
                    status = st
                    b1 = tr.byte()
                    last = st
                else:
                    status = last
                    b1 = st
                kind = status & 0xF0
                if kind in (0xC0, 0xD0):
                    ev.append((time, "midi", status, b1))
                else:
                    b2 = tr.byte()
                    if kind == 0x90:
                        dur = tr.varlen()
                        ev.append((time, "note", status & 0xF, b1, b2, dur))
                    else:
                        ev.append((time, "midi", status, b1, b2))
            delta = tr.varlen()
        tracks[t] = ev
    return division, tracks


def _varlen(v):
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def _escape(b: bytes) -> bytes:
    return b.replace(b"\xFE", b"\xFE\xFE")


def encode(tracks, division=96) -> bytes:
    """tracks: {track_index: [(time, kind, ...)]} with kinds
    note(ch, key, vel, dur) / midi(status, b1[, b2]) / tempo(usec_per_qn) /
    loopstart / loopend(count, 0xFF=forever). An 'end' is appended."""
    bodies = {}
    for t, events in tracks.items():
        out = bytearray()
        now = 0
        loop_positions = []
        for e in sorted(events, key=lambda e: (e[0], 0 if e[1] != "loopend" else 1)):
            time, kind = e[0], e[1]
            out += _escape(_varlen(time - now))
            now = time
            if kind == "note":
                ch, key, vel, dur = e[2:6]
                out += _escape(bytes([0x90 | ch, key & 0x7F, max(1, vel & 0x7F)]) + _varlen(dur))
            elif kind == "midi":
                out += _escape(bytes(e[2:]))
            elif kind == "tempo":
                u = e[2]
                out += _escape(bytes([META, META_TEMPO, (u >> 16) & 0xFF, (u >> 8) & 0xFF, u & 0xFF]))
            elif kind == "loopstart":
                out += bytes([META, LOOPSTART, 0, 0])
                loop_positions.append(len(out))
            elif kind == "loopend":
                count = e[2]
                start = loop_positions.pop()
                out += bytes([META, LOOPEND, count, count])
                # Offset is measured back from the end of this event.
                end_of_event = len(out) + 4
                out += struct.pack(">I", end_of_event - start)
        out += _varlen(0) + bytes([META, META_EOT])
        bodies[t] = bytes(out)
    hdr = bytearray(struct.pack(">16i", *([0] * 16)) + struct.pack(">i", division))
    data = bytearray(hdr)
    for t in sorted(bodies):
        struct.pack_into(">i", data, 4 * t, len(data))
        data += bodies[t]
    while len(data) % 8:
        data.append(0)
    return bytes(data)
