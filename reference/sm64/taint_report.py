"""Taint report: generated SM64 assets vs the retail extraction.

Texels (as RGBA bytes) and sample PCM of every generated asset are scanned
for >= taint.FAIL_RUN byte runs shared with any retail texture or sample.
Kept facts (m64 sequences, demo inputs) are listed, not scanned.

Usage: python -m games.sm64.taint_report <dirty tree> <clean tree>
"""
import json
import os
import struct
import sys

from cleanroom import taint
from cleanroom.gfx import png

HERE = os.path.dirname(os.path.abspath(__file__))


def _ssnd(path):
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
        if a.endswith(".png"):
            img = png.read(p)
            # opaque texels only: fully transparent areas carry no content
            yield a, img.tobytes()
        elif a.endswith(".aiff"):
            yield a, _ssnd(p)


def main(argv):
    dirty, clean = argv[1], argv[2]
    assets = json.load(open(os.path.join(HERE, "spec", "assets.json")))["assets"]
    index = taint.build_index(s for _, s in streams(dirty, assets))
    hits = taint.scan(index, streams(clean, assets))
    bad = sorted((h for h in hits if h[3] >= taint.FAIL_RUN), key=lambda h: -h[3])
    kept = [a for a in assets if a.endswith((".m64", ".bin"))]
    print(f"scanned {len(assets) - len(kept)} generated assets; {len(hits)} with short coincidental "
          f"matches; {len(bad)} failing (run >= {taint.FAIL_RUN} B); {len(kept)} kept facts not scanned")
    for label, off, n, run in bad[:8]:
        print(f"  FAIL {label} run {run} B ({n} windows)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
