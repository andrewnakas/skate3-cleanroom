"""libultra ALBankFile (.ctl) reader/writer and ALSeqFile container.

Layouts follow PR/libaudio.h; all pointers in the file are offsets that
alBnkfNew patches (ctl-relative, and tbl-relative for wavetable bases).

IR (plain dicts, JSON-able):
bankfile = {"revision": 0x4231, "banks": [bank|None]}
bank = {"flags", "pad", "rate", "percussion": inst|None, "insts": [inst|None]}
inst = {"volume","pan","priority","flags","trem":[4],"vib":[4],"bend",
        "sounds": [sound]}
sound = {"env": {...}, "keymap": {...}, "wave": {...}, "pan","volume","flags"}
wave = {"base","len","type","flags","loop": {...}|None,"book": {...}|None}
Objects shared between several parents are shared in the IR by "ref" ids so
round-trips can preserve sharing: every object dict gets "_id".
"""
import struct

AL_BANK_VERSION = 0x4231  # 'B1'
AL_SEQBANK_VERSION = 0x5331  # 'S1'
ADPCM, RAW16 = 0, 1


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def parse_bankfile(ctl: bytes) -> dict:
    cache = {}

    def once(kind, off, fn):
        key = (kind, off)
        if key not in cache:
            cache[key] = fn(off)
            cache[key]["_id"] = f"{kind}@{off:x}"
        return cache[key]

    def env(o):
        a, d, r, av, dv = struct.unpack_from(">iiiBB", ctl, o)
        return {"attack": a, "decay": d, "release": r, "attack_vol": av, "decay_vol": dv}

    def keymap(o):
        vmin, vmax, kmin, kmax, kbase, det = struct.unpack_from(">BBBBBb", ctl, o)
        return {"vel_min": vmin, "vel_max": vmax, "key_min": kmin, "key_max": kmax,
                "key_base": kbase, "detune": det}

    def loop_adpcm(o):
        s, e, c = struct.unpack_from(">III", ctl, o)
        st = list(struct.unpack_from(">16h", ctl, o + 12))
        return {"start": s, "end": e, "count": c, "state": st}

    def loop_raw(o):
        s, e, c = struct.unpack_from(">III", ctl, o)
        return {"start": s, "end": e, "count": c}

    def book(o):
        order, npred = struct.unpack_from(">ii", ctl, o)
        n = order * npred * 8
        return {"order": order, "npred": npred, "book": list(struct.unpack_from(">%dh" % n, ctl, o + 8))}

    def wave(o):
        base, ln, typ, fl, lp, bk = struct.unpack_from(">IiBBxxII", ctl, o)
        w = {"base": base, "len": ln, "type": typ, "flags": fl, "loop": None, "book": None}
        if typ == ADPCM:
            if lp:
                w["loop"] = once("aloop", lp, loop_adpcm)
            if bk:
                w["book"] = once("book", bk, book)
        elif lp:
            w["loop"] = once("rloop", lp, loop_raw)
        return w

    def sound(o):
        e, k, wt, pan, vol, fl = struct.unpack_from(">IIIBBB", ctl, o)
        return {"env": once("env", e, env), "keymap": once("key", k, keymap),
                "wave": once("wave", wt, wave), "pan": pan, "volume": vol, "flags": fl}

    def inst(o):
        f = struct.unpack_from(">12Bhh", ctl, o)
        n = f[13]
        offs = struct.unpack_from(">%dI" % n, ctl, o + 16)
        return {"volume": f[0], "pan": f[1], "priority": f[2], "flags": f[3],
                "trem": list(f[4:8]), "vib": list(f[8:12]), "bend": f[12],
                "sounds": [once("sound", so, sound) for so in offs]}

    def bank(o):
        n, fl, pad, rate, perc = struct.unpack_from(">hBBiI", ctl, o)
        offs = struct.unpack_from(">%dI" % n, ctl, o + 12)
        return {"flags": fl, "pad": pad, "rate": rate,
                "percussion": once("inst", perc, inst) if perc else None,
                "insts": [once("inst", io, inst) if io else None for io in offs]}

    rev, n = struct.unpack_from(">hh", ctl, 0)
    offs = struct.unpack_from(">%dI" % n, ctl, 4)
    return {"revision": rev & 0xFFFF,
            "banks": [once("bank", bo, bank) if bo else None for bo in offs]}


def build_bankfile(bf: dict) -> bytes:
    """Serialise a bank file IR. Shared objects (same `_id` or same dict
    object) are written once. Flags are written as in the IR (0 on disk)."""
    out = bytearray()
    placed = {}

    def align(n):
        while len(out) % n:
            out.append(0)

    def key(obj):
        return obj.get("_id") or id(obj)

    # Header first; patch offsets afterwards.
    nb = len(bf["banks"])
    out += struct.pack(">HH", bf.get("revision", AL_BANK_VERSION), nb)
    bank_slots = len(out)
    out += bytes(4 * nb)

    def put_env(e):
        k = ("env", key(e))
        if k not in placed:
            align(8)
            placed[k] = len(out)
            out.extend(struct.pack(">iiiBBxx", e["attack"], e["decay"], e["release"],
                                   e["attack_vol"], e["decay_vol"]))
        return placed[k]

    def put_key(m):
        k = ("key", key(m))
        if k not in placed:
            align(8)
            placed[k] = len(out)
            out.extend(struct.pack(">BBBBBbxx", m["vel_min"], m["vel_max"], m["key_min"],
                                   m["key_max"], m["key_base"], m["detune"]))
        return placed[k]

    def put_loop(lp, typ):
        k = ("loop", key(lp))
        if k not in placed:
            align(8)
            placed[k] = len(out)
            out.extend(struct.pack(">III", lp["start"], lp["end"], lp["count"]))
            if typ == ADPCM:
                out.extend(struct.pack(">16h", *lp["state"]))
        return placed[k]

    def put_book(b):
        k = ("book", key(b))
        if k not in placed:
            align(8)
            placed[k] = len(out)
            out.extend(struct.pack(">ii", b["order"], b["npred"]))
            out.extend(struct.pack(">%dh" % len(b["book"]), *b["book"]))
        return placed[k]

    def put_wave(w):
        k = ("wave", key(w))
        if k not in placed:
            lp = put_loop(w["loop"], w["type"]) if w.get("loop") else 0
            bk = put_book(w["book"]) if w.get("book") else 0
            align(8)
            placed[k] = len(out)
            out.extend(struct.pack(">IiBBxxII", w["base"], w["len"], w["type"], w.get("flags", 0), lp, bk))
        return placed[k]

    def put_sound(s):
        k = ("sound", key(s))
        if k not in placed:
            e = put_env(s["env"])
            m = put_key(s["keymap"])
            w = put_wave(s["wave"])
            align(8)
            placed[k] = len(out)
            out.extend(struct.pack(">IIIBBBx", e, m, w, s["pan"], s["volume"], s.get("flags", 0)))
        return placed[k]

    def put_inst(i):
        k = ("inst", key(i))
        if k not in placed:
            offs = [put_sound(s) for s in i["sounds"]]
            align(8)
            placed[k] = len(out)
            out.extend(struct.pack(">12Bhh", i["volume"], i["pan"], i["priority"], i.get("flags", 0),
                                   *i["trem"], *i["vib"], i["bend"], len(offs)))
            out.extend(struct.pack(">%dI" % len(offs), *offs))
        return placed[k]

    def put_bank(b):
        perc = put_inst(b["percussion"]) if b.get("percussion") else 0
        offs = [put_inst(i) if i else 0 for i in b["insts"]]
        align(8)
        o = len(out)
        out.extend(struct.pack(">hBBiI", len(offs), b.get("flags", 0), b.get("pad", 0), b["rate"], perc))
        out.extend(struct.pack(">%dI" % len(offs), *offs))
        return o

    for i, b in enumerate(bf["banks"]):
        o = put_bank(b) if b else 0
        struct.pack_into(">I", out, bank_slots + 4 * i, o)
    align(16)
    return bytes(out)


# ------------------------------------------------------------ sequence files

def parse_seqfile(data: bytes):
    rev, n = struct.unpack_from(">hh", data, 0)
    seqs = []
    for i in range(n):
        off, ln = struct.unpack_from(">Ii", data, 4 + 8 * i)
        seqs.append(bytes(data[off:off + ln]))
    return rev & 0xFFFF, seqs


def build_seqfile(seqs, revision=AL_SEQBANK_VERSION, align=16) -> bytes:
    hdr = 4 + 8 * len(seqs)
    pos = (hdr + align - 1) // align * align
    table = bytearray(struct.pack(">HH", revision, len(seqs)))
    body = bytearray()
    for s in seqs:
        table += struct.pack(">Ii", pos + len(body), len(s))
        body += s
        while len(body) % align:
            body.append(0)
    return bytes(table.ljust(pos, b"\0") + body)
