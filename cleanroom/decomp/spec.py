"""DIRTY ROOM: extracted decomp assets -> clean-room spec (coarse facts only).

For each file in the census:
  texture (.png)   format (from the name), size, a colour grid (4x4, 16x16 for
                   >= 128 px or skyboxes), 2-bit alpha outline if alpha varies
  sample           frame count, rate, raw COMM/MARK/INST (loop points), a coarse
                   spectral outline (descriptor) and a median pitch
  keep patterns    copied verbatim into spec/kept/ (user-approved facts such as
                   note sequences or demo inputs), listed separately
  everything else  listed as "unhandled" so the session decides explicitly

    python -m cleanroom.decomp.spec <dirty tree> <census assets.json> <spec dir> [--keep .m64,demos/]
"""
import json
import os
import shutil
import struct
import sys

import numpy as np

from cleanroom.gfx import png
from cleanroom.audio import descriptor, vadpcm
from cleanroom.audio.pitch import median_f0


def grid(rgba, n):
    h, w = rgba.shape[:2]
    out = []
    for gy in range(n):
        for gx in range(n):
            y0, y1 = gy * h // n, max(gy * h // n + 1, (gy + 1) * h // n)
            x0, x1 = gx * w // n, max(gx * w // n + 1, (gx + 1) * w // n)
            out.append([int(round(v)) for v in rgba[y0:y1, x0:x1].reshape(-1, 4).mean(0)])
    return out


def alpha2(a):
    a = (a.astype(np.uint8) >> 6).ravel()
    a = np.concatenate([a, np.zeros((-len(a)) % 4, np.uint8)])
    return ((a[0::4] << 6) | (a[1::4] << 4) | (a[2::4] << 2) | a[3::4]).astype(np.uint8).tobytes().hex()


def texture_fact(path, rgba):
    parts = os.path.basename(path).split(".")
    fmt = parts[-2] if len(parts) >= 3 else "rgba"
    h, w = rgba.shape[:2]
    n = 16 if ("sky" in path.lower() or max(w, h) >= 128) else 4
    d = {"fmt": fmt, "w": w, "h": h, "grid": grid(rgba, n)}
    if (rgba[..., 3] < 250).any():
        d["alpha2"] = alpha2(rgba[..., 3])
    return d


def chunks(buf):
    assert buf[:4] == b"FORM" and buf[8:12] in (b"AIFF", b"AIFC"), "not AIFF/AIFC"
    pos, out = 12, []
    while pos + 8 <= len(buf):
        tag, n = buf[pos:pos + 4], struct.unpack(">I", buf[pos + 4:pos + 8])[0]
        out.append((tag.decode("latin1"), buf[pos + 8:pos + 8 + n]))
        pos += 8 + n + (n & 1)
    return out


def _book(appl_list):
    for data in appl_list:
        if data[4:16] == b"\x0bVADPCMCODES":
            ver, order, npred = struct.unpack(">hhh", data[16:22])
            vals = struct.unpack(">%dh" % (order * npred * 8), data[22:22 + order * npred * 16])
            return {"order": order, "npred": npred, "book": list(vals)}
    return None


def aiff_fact(buf):
    ch = chunks(buf)
    cd = dict(ch)
    comm = cd["COMM"]
    nch, nframes, bits = struct.unpack(">hIh", comm[:8])
    e, m = struct.unpack(">HQ", comm[8:18])
    rate = m * 2.0 ** ((e & 0x7FFF) - 16383 - 63)
    ssnd = cd["SSND"][8:]
    compressed = buf[8:12] == b"AIFC" and comm[18:22] == b"VAPC"
    if compressed:
        book = _book([d for t, d in ch if t == "APPL"])
        pcm = vadpcm.decode(ssnd, book, nframes).astype(np.float64) if book else np.zeros(nframes)
    else:
        pcm = np.frombuffer(ssnd[:nframes * 2], ">i2").astype(np.float64)
    d = {"nframes": nframes, "rate": rate, "comm": comm.hex(), "container": "aifc" if compressed else "aiff",
         "desc": descriptor.describe(pcm, rate)}
    f0 = median_f0((pcm / 32768).astype(np.float32), rate)
    if f0:
        d["f0"] = round(f0, 1)
    for tag in ("MARK", "INST"):
        if tag in cd:
            d[tag] = cd[tag].hex()
    return d


def wav_fact(path):
    import wave
    with wave.open(path) as w:
        rate, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(n), "<i2").astype(np.float64).reshape(-1, ch).mean(1)
    d = {"nframes": n, "rate": rate, "channels": ch, "container": "wav", "desc": descriptor.describe(pcm, rate)}
    f0 = median_f0((pcm / 32768).astype(np.float32), rate)
    if f0:
        d["f0"] = round(f0, 1)
    return d


def main(argv):
    dirty, census, out = argv[1], argv[2], argv[3]
    keep = argv[argv.index("--keep") + 1].split(",") if "--keep" in argv else []
    assets = json.load(open(census))["assets"]
    os.makedirs(os.path.join(out, "kept"), exist_ok=True)
    tex, smp, kept, unhandled, errors = {}, {}, [], [], []
    for i, a in enumerate(assets):
        p = os.path.join(dirty, a)
        try:
            if any(k in a for k in keep):
                dst = os.path.join(out, "kept", a)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(p, dst)
                kept.append(a)
            elif a.lower().endswith(".png"):
                tex[a] = texture_fact(a, png.read(p))
            elif a.lower().endswith((".aiff", ".aifc")):
                smp[a] = aiff_fact(open(p, "rb").read())
            elif a.lower().endswith(".wav"):
                smp[a] = wav_fact(p)
            else:
                unhandled.append(a)
        except Exception as e:                    # report, never stop the batch
            errors.append(f"{a}: {e}")
        if i % 1000 == 0:
            print(f"  {i}/{len(assets)}", flush=True)
    json.dump({"assets": assets, "kept": kept, "unhandled": unhandled}, open(os.path.join(out, "assets.json"), "w"), indent=0)
    json.dump(tex, open(os.path.join(out, "textures.json"), "w"), separators=(",", ":"))
    json.dump(smp, open(os.path.join(out, "samples.json"), "w"), separators=(",", ":"))
    print(f"spec: {len(tex)} textures, {len(smp)} samples, {len(kept)} kept, {len(unhandled)} unhandled, {len(errors)} errors -> {out}")
    if unhandled:
        import collections
        print("  unhandled by extension:", collections.Counter(os.path.splitext(u)[1] for u in unhandled).most_common(8))
    for e in errors[:5]:
        print("  ERROR", e)


if __name__ == "__main__":
    main(sys.argv)
