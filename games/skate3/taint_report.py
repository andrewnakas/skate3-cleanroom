"""Taint report: every regenerated texture (RGBA bytes) in the clean pack vs
every retail texture in the dirty pack; runs >= taint.FAIL_RUN bytes fail.
Also checks that no clean file outside the kept list is byte-identical to a
dirty file. Kept facts are listed, not scanned.

    python -m games.skate3.taint_report <dirty install dir> <clean dir>
"""
import hashlib
import io
import json
import os
import struct
import sys

import numpy as np
from PIL import Image

from cleanroom import taint
from games.skate3 import skate14
from games.skate3.generate import classify


def glb_images(p):
    b = open(p, "rb").read()
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + jl])
    off = 20 + jl
    binc = b[off + 8:]
    for i, im in enumerate(j.get("images", [])):
        if "bufferView" in im:
            v = j["bufferViews"][im["bufferView"]]
            s = v.get("byteOffset", 0)
            yield f"#image{i}", np.array(Image.open(io.BytesIO(binc[s:s + v["byteLength"]])).convert("RGBA")).tobytes()


def file_streams(root, rel):
    p = os.path.join(root, rel)
    k = classify(rel)
    if k == "skate":
        for name, w, h, a, cube in skate14.textures(p):
            yield f"{rel}#{name}", a.tobytes()
    elif k == "rgba":
        yield rel, open(p, "rb").read()
    elif k == "png":
        yield rel, np.array(Image.open(p).convert("RGBA")).tobytes()
    elif k == "glb":
        for n, s in glb_images(p):
            yield rel + n, s


def files(root):
    for dp, _, fs in os.walk(root):
        for f in fs:
            yield os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")


def streams(root):
    for rel in files(root):
        yield from file_streams(root, rel)


SAMPLE = 64  # content-defined sampling keeps the index ~45M hashes for ~3 GB of retail texels


def sampled(s):
    h, per = taint._hashes(s)
    keep = ~per & ((h % np.uint64(SAMPLE)) == 0)
    return h[keep]


def max_same_run(a, b):
    if len(a) != len(b):
        return 0
    m = np.frombuffer(a, np.uint8) == np.frombuffer(b, np.uint8)
    # ignore runs made only of a repeated value (flat colour, opaque alpha)
    d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
    st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    best = 0
    arr = np.frombuffer(a, np.uint8)
    long = (en - st) >= taint.FAIL_RUN
    for s, e in zip(st[long], en[long]):
        if e - s >= taint.FAIL_RUN and e - s > best and len(np.unique(arr[s:e])) >= taint.MIN_DISTINCT:
            best = e - s
    return best


def main(argv):
    dirty, clean = argv[1], argv[2]
    parts = []
    for _, s in streams(dirty):
        parts.append(np.unique(sampled(s)))
    index = np.unique(np.concatenate(parts)); parts = None
    n, hits, bad = 0, [], []
    for rel in files(clean):
      src = dict(file_streams(dirty, rel)) if os.path.exists(os.path.join(dirty, rel)) else {}
      for label, s in file_streams(clean, rel):
        n += 1
        h = sampled(s)
        if len(h) and len(index):
            pos = np.minimum(np.searchsorted(index, h), len(index) - 1)
            k = int((index[pos] == h).sum())
            if k:
                hits.append((label, k))
        run = max_same_run(s, src.get(label, b""))
        if run >= taint.FAIL_RUN:
            bad.append((label, 0, 0, run))
    bad += [(l, 0, 0, f"{k} sampled 16-B windows") for l, k in hits if k >= 4]
    # whole-file identity check for anything not on the kept list
    dh = {}
    for dp, _, fs in os.walk(dirty):
        for f in fs:
            p = os.path.join(dp, f)
            dh.setdefault(hashlib.sha1(open(p, "rb").read()).hexdigest(), os.path.relpath(p, dirty))
    same, kept = [], []
    for dp, _, fs in os.walk(clean):
        for f in fs:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, clean).replace("\\", "/")
            if classify(rel) == "keep":
                kept.append(rel)
            elif hashlib.sha1(open(p, "rb").read()).hexdigest() in dh:
                same.append(rel)
    print(f"taint: {n} generated textures scanned; {len(hits)} with short coincidental matches; "
          f"{len(bad)} failing (run >= {taint.FAIL_RUN} B); {len(same)} non-kept files identical to retail; "
          f"{len(kept)} kept-fact files not scanned")
    for label, off, ln, run in bad[:8]:
        print(f"  FAIL {label} run {run} B")
    for s in same[:8]:
        print(f"  IDENTICAL {s}")
    return 1 if bad or same else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
