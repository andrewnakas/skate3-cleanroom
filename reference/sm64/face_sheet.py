"""Contact sheets of face textures (eyes, mouths, faces).

DIRTY mode shows the retail extraction so a person can describe each face's
layout in face_briefs.json; nothing here is copied into outputs.
COMPARE mode puts dirty | clean side by side for the briefed textures.

Usage: python -m games.sm64.face_sheet <tree> <out.png> [--compare <clean tree>] [--only a,b]
"""
import json
import os
import re
import sys

import numpy as np

from cleanroom import find_text
from cleanroom.gfx import png, strokefont

HERE = os.path.dirname(os.path.abspath(__file__))
FACE = re.compile(r"eye|face|mouth|nose|teeth|tooth|lip|nostril|brow|mustache|iris|head", re.I)


def face_assets():
    t = json.load(open(os.path.join(HERE, "spec", "textures.json")))
    return [p for p in t if p.startswith("actors/") and FACE.search(p.rsplit("/", 1)[-1])
            and not p.startswith("actors/mario/mario_eyes") and "metal" not in p]


def _tile(i, img, scale):
    big = np.repeat(np.repeat(img, scale, 0), scale, 1)
    tag = strokefont.render_line(str(i), 12)
    lab = np.zeros((13, max(big.shape[1], tag.shape[1]), 4), np.uint8)
    lab[:12, :tag.shape[1], :3] = 255
    lab[:12, :tag.shape[1], 3] = (tag * 255).astype(np.uint8)
    body = np.zeros((big.shape[0], lab.shape[1], 4), np.uint8)
    body[:, :big.shape[1]] = big
    return np.concatenate([lab, body], 0)


def main(argv):
    tree, out = argv[1], argv[2]
    clean = argv[argv.index("--compare") + 1] if "--compare" in argv else None
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None
    assets = face_assets()
    items = []
    for i, a in enumerate(assets):
        if only and str(i) not in only and a not in only:
            continue
        img = png.read(os.path.join(tree, a))
        if clean:
            c = png.read(os.path.join(clean, a))
            img = np.concatenate([img, np.zeros((img.shape[0], 2, 4), np.uint8), c], 1)
        items.append((a, _tile(i, img, 3)))
    sheet, _ = find_text.contact_sheet(items, scale=1, width=1400)
    png.write(out, sheet)
    print(f"{len(items)} face textures -> {out}")
    if "--list" in argv:
        for i, a in enumerate(assets):
            print(i, a.split("/", 1)[1])


if __name__ == "__main__":
    main(sys.argv)
