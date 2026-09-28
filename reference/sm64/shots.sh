#!/bin/sh
# Headless check: build site, take 6 frames through title -> file select -> level, one sheet.
# Usage: games/sm64/shots.sh <clean tree> <out dir> [extra query]
T="$1"; O="$2"; X="$3"
./games/sm64/make_site.sh "$T" E:/n64web/sm64site > /dev/null
python ports/wasm/headless_shot.py "$O" --secs 5,11,17,23,30,38 --base http://localhost:8065/index.html \
  --query "keys=12:Space:0.3,15:Space:0.3,19:Space:0.3,21:Space:0.3,25:KeyL:0.3,27:KeyW:6,34:KeyL:0.2$X" --wait 44 --webgl
python - "$O" <<'PY'
import sys, glob, numpy as np
from cleanroom.gfx import png
o = sys.argv[1]
ims = [png.read(f)[::2, ::2] for f in sorted(glob.glob(o + "/shot_*.png"))]
if ims:
    h, w = max(i.shape[0] for i in ims), max(i.shape[1] for i in ims)
    ims = [np.pad(i, ((0, h - i.shape[0]), (0, w - i.shape[1]), (0, 0))) for i in ims]
    while len(ims) % 3: ims.append(np.zeros_like(ims[0]))
    rows = [np.concatenate(ims[k:k + 3], 1) for k in range(0, len(ims), 3)]
    png.write(o + "/sheet.png", np.concatenate(rows, 0))
lines = open(o + "/console.txt", encoding="utf-8").read().splitlines()
bad = [l for l in lines if "Error" in l or "Abort" in l]
print(f"{len(ims)} frames; {len(bad)} error lines" + (": " + bad[0][:120] if bad else ""))
PY
