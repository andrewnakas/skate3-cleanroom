"""Taint report for a clean MW2 map against its private export.

    python -m games.mw2.taint_report <private export dir> <clean dir>

Textures: every regenerated texture (RGBA bytes) against every retail colour
map of the export, at full size and at the size it was shrunk to: shared runs
of taint.FAIL_RUN bytes or more fail, and so does a texture with 4+ sampled
16-byte windows in common with any single retail texture (the Skate 3 rule).
Geometry: the clean vertex streams (positions, normals, UVs) and index buffer
against the retail ones: any shared 32-byte window fails (games.skate3.geom_taint).
PBR maps (generate --materials pbr): every albedo, normal and ORM map is
scanned the same way; an albedo against its own retail texture, the shared
normal / ORM maps against every retail texture of the same byte size. Their
detail comes from the CC0 sets listed in the clean CREDITS.json (ambientCG,
CC0 1.0): non-retail sources, listed, not scanned against.
Collision triangles and spawns are kept facts: listed, not scanned.
Exit code 1 on any failure.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

from cleanroom import taint
from games.mw2.generate import shrink
from games.skate3.geom_taint import shared_runs
from games.skate3.taint_report import max_same_run, sampled


def retail_textures(src, caps):
    ex = json.load(open(os.path.join(src, "export.json")))
    for i, m in enumerate(ex["materials"], 1):
        if not m.get("image"):
            continue
        rgba = np.asarray(Image.open(os.path.join(src, m["image"])).convert("RGBA"))
        yield i, "full", rgba
        for cap in caps:
            small = shrink(rgba, cap)
            if small.shape != rgba.shape:
                yield i, f"{cap}", small


def main(argv):
    src, clean = argv[1], argv[2]
    spec = json.load(open(os.path.join(clean, "map.json")))
    bad = []

    retail = list(retail_textures(src, [512, 256, 1024]))
    index = np.unique(np.concatenate([sampled(a.tobytes()) for _, _, a in retail])) if retail else np.zeros(0, np.uint64)
    by_material = {}
    for i, _, a in retail:
        by_material.setdefault(i, []).append(a.tobytes())
    by_size = {}
    for i, _, a in retail:
        by_size.setdefault(a.nbytes, []).append(a.tobytes())
    scanned = 0
    kinds = {"texture": 0, "normal": 0, "orm": 0}
    seen = set()
    for i, m in enumerate(spec["materials"], 1):
        for kind in ("texture", "normal", "orm"):
            path = m.get(kind)
            if not path or path in seen:
                continue
            seen.add(path)
            s = np.asarray(Image.open(os.path.join(clean, path)).convert("RGBA")).tobytes()
            scanned += 1
            kinds[kind] += 1
            # Albedo: its own retail texture (as before). Shared maps: every retail texture of its size.
            against = by_material.get(i, []) if kind == "texture" else by_size.get(len(s), [])
            for r in against:
                run = max_same_run(s, r)
                if run >= taint.FAIL_RUN:
                    bad.append((path, f"run {run} B with a retail texture"))
                    break
            h = sampled(s)
            if len(h) and len(index):
                pos = np.minimum(np.searchsorted(index, h), len(index) - 1)
                if int((index[pos] == h).sum()) >= 4:
                    worst = max(len(set(h.tolist()) & set(sampled(a.tobytes()).tolist())) for _, _, a in retail)
                    if worst >= 4:
                        bad.append((path, f"{worst} sampled windows shared with one retail texture"))

    dirty = np.load(os.path.join(src, "render.npz"))
    new = np.load(os.path.join(clean, "render.npz"))
    geometry = {}
    for field in ("positions", "normals", "uv", "indices"):
        runs = shared_runs(np.ascontiguousarray(new[field]).tobytes(), np.ascontiguousarray(dirty[field]).tobytes())
        geometry[field] = runs
        if runs:
            bad.append((f"render.{field}", f"{runs} shared 32-byte windows"))
    same_positions = 0
    if len(dirty["positions"]) and len(new["positions"]):
        old = {tuple(p) for p in np.asarray(dirty["positions"], np.float32).view(np.uint32).reshape(-1, 3).tolist()}
        same_positions = sum(tuple(p) in old for p in np.asarray(new["positions"], np.float32).view(np.uint32).reshape(-1, 3).tolist())

    kept = len(np.load(os.path.join(clean, "collision.npz"))["triangles"])
    credits_path = os.path.join(clean, "CREDITS.json")
    cc0 = json.load(open(credits_path))["sets"] if os.path.exists(credits_path) else []
    if cc0:
        print(f"non-retail sources (CC0 1.0, not scanned against): "
              + ", ".join(f"{c['id']} ({c['license']}, {c['source']})" for c in cc0))
    print(f"mw2 taint: {scanned} textures scanned ({kinds['texture']} albedo, {kinds['normal']} normal, "
          f"{kinds['orm']} ORM), geometry windows {geometry}, "
          f"{same_positions} of {len(new['positions'])} vertices keep a retail position exactly; "
          f"kept facts not scanned: {kept} collision triangles, {len(spec.get('spawns', []))} spawns; "
          f"{len(bad)} failing")
    for label, why in bad[:12]:
        print(f"  FAIL {label}: {why}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
