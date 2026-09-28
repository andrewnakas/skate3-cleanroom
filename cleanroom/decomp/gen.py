"""CLEAN ROOM: spec -> asset files, in the formats the decomp's build reads.

Textures: colour grid + our own detail noise + the kept 2-bit alpha outline.
Samples:  resynthesised from the coarse outline (or a supplied waveform such
          as a voice take), same length/rate/loop points, dither, and a
          per-sample 2-predictor VADPCM book (retail banks use 2; larger books
          grow sound banks past fixed audio pools and the audio dies).

Game code calls these helpers; `write_all` covers the common case:

    python -m cleanroom.decomp.gen <spec dir> <clean tree> [tex|snd]
"""
import hashlib
import json
import os
import struct
import sys
import wave

import numpy as np

from cleanroom.gfx import png
from cleanroom.audio import descriptor, vadpcm


def h32(*parts):
    return int.from_bytes(hashlib.sha1("/".join(map(str, parts)).encode()).digest()[:4], "little")


# ----------------------------------------------------------------- textures

def upsample_grid(grid, n, w, h):
    g = np.asarray(grid, np.float32).reshape(n, n, 4)
    ys = (np.arange(h, dtype=np.float32) + 0.5) / max(1, h) * n - 0.5
    xs = (np.arange(w, dtype=np.float32) + 0.5) / max(1, w) * n - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, n - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, n - 1)
    y1, x1 = np.clip(y0 + 1, 0, n - 1), np.clip(x0 + 1, 0, n - 1)
    fy = np.clip(ys - np.floor(ys), 0, 1)[:, None, None]
    fx = np.clip(xs - np.floor(xs), 0, 1)[None, :, None]
    top = g[y0][:, x0] * (1 - fx) + g[y0][:, x1] * fx
    bot = g[y1][:, x0] * (1 - fx) + g[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def detail(seed, w, h, amount=0.06, cell=4.0):
    rng = np.random.default_rng(seed)
    lat = rng.standard_normal((int(h / cell) + 3, int(w / cell) + 3)).astype(np.float32)
    ys, xs = np.arange(h, dtype=np.float32) / cell, np.arange(w, dtype=np.float32) / cell
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
    fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
    v = (lat[y0][:, x0] * (1 - fx) + lat[y0][:, x0 + 1] * fx) * (1 - fy) + \
        (lat[y0 + 1][:, x0] * (1 - fx) + lat[y0 + 1][:, x0 + 1] * fx) * fy
    return 1.0 + amount * v


def unpack_alpha2(hexstr, w, h):
    b = np.frombuffer(bytes.fromhex(hexstr), np.uint8)
    a = np.empty(len(b) * 4, np.uint8)
    a[0::4], a[1::4], a[2::4], a[3::4] = b >> 6, (b >> 4) & 3, (b >> 2) & 3, b & 3
    return a[:w * h].reshape(h, w).astype(np.float32) * 85.0


def from_digest(path, d):
    w, h = d["w"], d["h"]
    n = int(round(len(d["grid"]) ** 0.5))
    rgba = upsample_grid(d["grid"], n, w, h)
    rgba[..., :3] *= detail(h32("detail", path), w, h, 0.03 if n > 4 else 0.07, 4.0 if n == 4 else 8.0)[..., None]
    rgba[..., 3] = unpack_alpha2(d["alpha2"], w, h) if "alpha2" in d else 255
    return np.clip(rgba, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ samples

def two_predictors(x):
    fits = []
    for s in range(2, len(x) - 16, 16):
        y, p1, p2 = x[s:s + 16], x[s - 1:s + 15], x[s - 2:s + 14]
        if (y ** 2).sum() < 1e3:
            continue
        a, *_ = np.linalg.lstsq(np.stack([p1, p2], 1), y, rcond=None)
        fits.append(a)
    if len(fits) < 2:
        return [(1.0, 0.0), (1.8, -0.82)]
    f = np.clip(np.asarray(fits), [-1.95, -0.98], [1.95, 0.98])
    c = f[[np.argmin(f[:, 0]), np.argmax(f[:, 0])]].copy()
    for _ in range(12):
        lab = np.argmin(((f[:, None, :] - c[None]) ** 2).sum(-1), 1)
        for k in range(2):
            if (lab == k).any():
                c[k] = f[lab == k].mean(0)
    out = []
    for a1, a2 in c:
        a2 = float(np.clip(a2, -0.98, 0.98))
        out.append((float(np.clip(a1, -(1 - a2) + 0.02, (1 - a2) - 0.02)), a2))
    return out


def _chunk(tag, data):
    return tag + struct.pack(">I", len(data)) + data + (b"\0" if len(data) & 1 else b"")


def _markers(mark_hex):
    b = bytes.fromhex(mark_hex)
    n = struct.unpack(">H", b[:2])[0]
    o, out = 2, {}
    for _ in range(n):
        mid, pos = struct.unpack(">HI", b[o:o + 6])
        out[mid] = pos
        ln = b[o + 6]
        o += 6 + 1 + ln + ((1 + ln) & 1)
    return out


def loop_points(d):
    if "MARK" in d and "INST" in d:
        play, beg, end = struct.unpack(">hHH", bytes.fromhex(d["INST"])[8:14])
        mk = _markers(d["MARK"])
        if play and beg in mk and end in mk and mk[end] > mk[beg]:
            return mk[beg], mk[end]
    return None


def waveform(path, d, supplied=None):
    """Float waveform for a slot: a supplied take, else resynthesis."""
    n, rate = d["nframes"], d["rate"]
    x = supplied if supplied is not None else descriptor.synthesize(d["desc"], n, rate, seed=h32("smp", path))
    x = np.asarray(x, np.float32)[:n]
    x = np.pad(x, (0, n - len(x)))
    lp = loop_points(d)
    if lp and supplied is None:
        x = descriptor.make_loop_seamless(x, *lp)
    dither = np.random.default_rng(h32("dither", path)).integers(-1, 2, n)   # breaks coincidental ramps
    return np.clip(np.round(np.clip(x, -1, 1) * 32000) + dither, -32768, 32767).astype(np.int16)


def codes_chunk(book):
    return b"stoc" + b"\x0bVADPCMCODES" + struct.pack(">hhh", 1, book["order"], book["npred"]) + \
        struct.pack(">%dh" % len(book["book"]), *book["book"])


def aiff_bytes(d, pcm):
    """Uncompressed AIFF with our codebook (the decomp's tools encode it)."""
    book = vadpcm.make_book(two_predictors(pcm.astype(np.float64)))
    body = b"AIFF" + _chunk(b"COMM", bytes.fromhex(d["comm"])[:18])
    for tag in ("MARK", "INST"):
        if tag in d:
            body += _chunk(tag.encode(), bytes.fromhex(d[tag]))
    body += _chunk(b"APPL", codes_chunk(book)) + _chunk(b"SSND", struct.pack(">II", 0, 0) + pcm.astype(">i2").tobytes())
    return b"FORM" + struct.pack(">I", len(body)) + body


def aifc_bytes(d, pcm):
    """VADPCM-compressed AIFC (for decomps that consume .aifc directly)."""
    book = vadpcm.make_book(two_predictors(pcm.astype(np.float64)))
    data, _, dec = vadpcm.encode(pcm, book)
    comm = bytes.fromhex(d["comm"])
    body = b"AIFC" + _chunk(b"FVER", struct.pack(">I", 0xA2805140)) + _chunk(b"COMM", comm)
    for tag in ("MARK", "INST"):
        if tag in d:
            body += _chunk(tag.encode(), bytes.fromhex(d[tag]))
    body += _chunk(b"APPL", codes_chunk(book))
    lp = loop_points(d)
    if lp:
        st = vadpcm.loop_state(dec, lp[0])
        body += _chunk(b"APPL", b"stoc" + b"\x0bVADPCMLOOPS" + struct.pack(">hh", 1, 1) +
                       struct.pack(">IIi", lp[0], lp[1], -1) + struct.pack(">16h", *st))
    body += _chunk(b"SSND", struct.pack(">II", 0, 0) + data)
    return b"FORM" + struct.pack(">I", len(body)) + body


def wav_bytes(d, pcm, path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(round(d["rate"])))
        w.writeframes(pcm.astype("<i2").tobytes())


def write_sample(path, d, supplied=None):
    pcm = waveform(path, d, supplied)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if d.get("container") == "wav":
        wav_bytes(d, pcm, path)
    else:
        with open(path, "wb") as f:
            f.write(aifc_bytes(d, pcm) if d.get("container") == "aifc" else aiff_bytes(d, pcm))


# --------------------------------------------------------------------- main

def write_all(spec_dir, tree, only=None, texture_hook=None, sample_hook=None):
    """texture_hook(path, d) -> RGBA or None (glyphs, labels, faces...);
    sample_hook(path, d) -> float waveform or None (voice takes...)."""
    A = json.load(open(os.path.join(spec_dir, "assets.json")))
    T = json.load(open(os.path.join(spec_dir, "textures.json")))
    S = json.load(open(os.path.join(spec_dir, "samples.json")))
    n = {"digest": 0, "hooked": 0, "sample": 0, "kept": 0}
    for a, d in T.items():
        if only not in (None, "tex"):
            break
        img = texture_hook(a, d) if texture_hook else None
        n["hooked" if img is not None else "digest"] += 1
        img = from_digest(a, d) if img is None else np.clip(img, 0, 255).astype(np.uint8)
        dst = os.path.join(tree, a)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        png.write(dst, img)
    for a, d in S.items():
        if only not in (None, "snd"):
            break
        write_sample(os.path.join(tree, a), d, sample_hook(a, d) if sample_hook else None)
        n["sample"] += 1
    if only is None:
        for a in A.get("kept", []):
            dst = os.path.join(tree, a)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(os.path.join(spec_dir, "kept", a), "rb") as f, open(dst, "wb") as g:
                g.write(f.read())
            n["kept"] += 1
    return n


if __name__ == "__main__":
    only = sys.argv[3] if len(sys.argv) > 3 else None
    print("generated:", write_all(sys.argv[1], sys.argv[2], only))
