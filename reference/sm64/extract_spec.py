"""DIRTY ROOM: read the decomp's extracted retail assets and write the spec.

Input is a sm64-port tree after `extract_assets.py us` (the only place retail
bytes exist). For every extracted file we keep
  * slot metadata - path, texture format and size, sample count, rate,
                    loop points (the engine and build depend on these),
  * facts         - what the user chose to keep: a coarse colour grid and a
                    2-bit alpha outline per texture, a coarse audio outline
                    per sample, the music note events (m64 sequences) and the
                    attract-mode demo inputs,
and drops texels, glyph shapes and sample data.

Usage: python -m games.sm64.extract_spec <dirty sm64 tree> [spec_dir]
"""
import json
import os
import struct
import sys

import numpy as np

from cleanroom.gfx import png
from cleanroom.audio import descriptor
from cleanroom.audio.pitch import median_f0

HERE = os.path.dirname(os.path.abspath(__file__))


def _grid(rgba, n):
    h, w = rgba.shape[:2]
    out = []
    for gy in range(n):
        for gx in range(n):
            y0, y1 = gy * h // n, max(gy * h // n + 1, (gy + 1) * h // n)
            x0, x1 = gx * w // n, max(gx * w // n + 1, (gx + 1) * w // n)
            out.append([int(round(v)) for v in rgba[y0:y1, x0:x1].reshape(-1, 4).mean(0)])
    return out


def _alpha2(a):
    a = (a.astype(np.uint8) >> 6).ravel()
    a = np.concatenate([a, np.zeros((-len(a)) % 4, np.uint8)])
    return ((a[0::4] << 6) | (a[1::4] << 4) | (a[2::4] << 2) | a[3::4]).astype(np.uint8).tobytes().hex()


def texture_fact(path, rgba):
    name = os.path.basename(path)
    parts = name.split(".")
    fmt = parts[-2] if len(parts) >= 3 else "rgba"      # skyboxes / cake: plain .png
    h, w = rgba.shape[:2]
    n = 16 if "skyboxes" in path or fmt == "rgba" else 4
    d = {"fmt": fmt, "w": w, "h": h, "grid": _grid(rgba, n)}
    if (rgba[..., 3] < 250).any():
        d["alpha2"] = _alpha2(rgba[..., 3])
    if fmt.startswith("i") and not fmt.startswith("ia"):
        pass
    return d


def _chunks(buf):
    assert buf[:4] == b"FORM" and buf[8:12] in (b"AIFF", b"AIFC")
    pos, out = 12, []
    while pos + 8 <= len(buf):
        tag, n = buf[pos:pos + 4], struct.unpack(">I", buf[pos + 4:pos + 8])[0]
        out.append((tag.decode("latin1"), buf[pos + 8:pos + 8 + n]))
        pos += 8 + n + (n & 1)
    return out


def sample_fact(buf):
    ch = dict(_chunks(buf))
    comm = ch["COMM"]
    nch, nframes, bits = struct.unpack(">hIh", comm[:8])
    assert nch == 1 and bits == 16, (nch, bits)
    ssnd = ch["SSND"][8:]
    pcm = np.frombuffer(ssnd[:nframes * 2], ">i2").astype(np.float64)
    # sample rate: 80-bit extended float
    e, m = struct.unpack(">HQ", comm[8:18])
    rate = m * 2.0 ** ((e & 0x7FFF) - 16383 - 63)
    d = {"nframes": nframes, "comm": comm.hex(), "rate": rate,
         "desc": descriptor.describe(pcm, rate)}
    f0 = median_f0((pcm / 32768).astype(np.float32), rate)     # one number: the line's pitch level
    if f0:
        d["f0"] = round(f0, 1)
    for tag in ("MARK", "INST"):         # loop points (slot)
        if tag in ch:
            d[tag] = ch[tag].hex()
    return d


def main(argv):
    src = argv[1]
    out = argv[2] if len(argv) > 2 else os.path.join(HERE, "spec")
    os.makedirs(os.path.join(out, "kept"), exist_ok=True)
    lines = open(os.path.join(src, ".assets-local.txt")).read().split("\n")
    header = lines[:2]
    listed = [l for l in lines[2:] if l.strip()]
    assets = [l for l in listed if os.path.exists(os.path.join(src, l))]
    print(f"listed {len(listed)}, present {len(assets)} (others are other-version only)")
    tex, smp, kept = {}, {}, []
    for i, a in enumerate(assets):
        p = os.path.join(src, a)
        if a.endswith(".png"):
            tex[a] = texture_fact(a, png.read(p))
        elif a.endswith(".aiff"):
            smp[a] = sample_fact(open(p, "rb").read())
        elif a.endswith(".m64") or a.endswith(".bin"):
            dst = os.path.join(out, "kept", a)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(p, "rb") as f, open(dst, "wb") as g:
                g.write(f.read())
            kept.append(a)
        else:
            raise SystemExit(f"unknown asset type: {a}")
        if i % 400 == 0:
            print(f"  {i}/{len(assets)}", flush=True)
    json.dump({"header": header, "assets": assets}, open(os.path.join(out, "assets.json"), "w"), indent=0)
    json.dump(tex, open(os.path.join(out, "textures.json"), "w"), separators=(",", ":"))
    json.dump(smp, open(os.path.join(out, "samples.json"), "w"), separators=(",", ":"))
    print(f"spec: {len(tex)} textures, {len(smp)} samples, {len(kept)} kept facts (m64/demos) -> {out}")


if __name__ == "__main__":
    main(sys.argv)
