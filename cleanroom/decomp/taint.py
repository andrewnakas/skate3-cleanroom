"""Taint report for decomp asset trees: every generated texture (RGBA
bytes) and sample (PCM) vs every retail one; runs >= taint.FAIL_RUN bytes
fail. Kept facts are listed, not scanned.

    python -m cleanroom.decomp.taint <dirty tree> <clean tree> <spec dir>
"""
import json
import os
import struct
import sys
import wave

import numpy as np

from cleanroom import taint
from cleanroom.gfx import png


def pcm_bytes(path):
    if path.lower().endswith(".wav"):
        with wave.open(path) as w:
            return w.readframes(w.getnframes())
    b = open(path, "rb").read()
    pos = 12
    while pos + 8 <= len(b):
        tag, n = b[pos:pos + 4], struct.unpack(">I", b[pos + 4:pos + 8])[0]
        if tag == b"SSND":
            return b[pos + 16:pos + 8 + n]
        pos += 8 + n + (n & 1)
    return b""


def streams(tree, assets):
    for a in assets:
        p = os.path.join(tree, a)
        if not os.path.exists(p):
            continue
        if a.lower().endswith(".png"):
            yield a, png.read(p).tobytes()
        elif a.lower().endswith((".aiff", ".aifc", ".wav")):
            yield a, pcm_bytes(p)


def main(argv):
    dirty, clean, spec = argv[1], argv[2], argv[3]
    A = json.load(open(os.path.join(spec, "assets.json")))
    kept = set(A.get("kept", []))
    gen = [a for a in A["assets"] if a not in kept]
    index = taint.build_index(s for _, s in streams(dirty, gen))
    hits = taint.scan(index, streams(clean, gen))
    bad = sorted((h for h in hits if h[3] >= taint.FAIL_RUN), key=lambda h: -h[3])
    print(f"taint: {len(gen)} generated assets scanned; {len(hits)} with short coincidental matches; "
          f"{len(bad)} failing (run >= {taint.FAIL_RUN} B); {len(kept)} kept facts not scanned")
    for label, off, n, run in bad[:8]:
        print(f"  FAIL {label} run {run} B")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
