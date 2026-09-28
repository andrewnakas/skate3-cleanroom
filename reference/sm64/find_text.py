"""DIRTY ROOM: rank extracted SM64 textures by text-likeness, one contact sheet.

Glyph textures (mapped from symbol names) are skipped; they are drawn from
the stroke font anyway. Writes <out>/sheet.png and prints the ranked
index -> path list so labels can be transcribed into text_labels.json.

Usage: python -m games.sm64.find_text <dirty tree> <pristine tree> <out dir> [n]
"""
import json
import os
import sys

import numpy as np

from cleanroom import find_text
from cleanroom.gfx import png, strokefont
from .generate import glyph_map

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv):
    dirty, pristine, out = argv[1], argv[2], argv[3]
    n = int(argv[4]) if len(argv) > 4 else 48
    assets = json.load(open(os.path.join(HERE, "spec", "assets.json")))["assets"]
    glyphs = glyph_map(pristine)
    scored = []
    for a in assets:
        if a.endswith(".png") and a not in glyphs and "skyboxes" not in a:
            img = png.read(os.path.join(dirty, a))
            s = find_text.text_score(img)
            if s > 0:
                scored.append((s, a, img))
    scored.sort(key=lambda t: -t[0])
    items = []
    for i, (s, a, img) in enumerate(scored[:n]):
        tag = strokefont.render_line(str(i), 12)
        lab = np.zeros((12, max(tag.shape[1], img.shape[1]), 4), np.uint8)
        lab[:, :tag.shape[1], :3] = 255
        lab[:, :tag.shape[1], 3] = (tag * 255).astype(np.uint8)
        body = np.zeros((img.shape[0], lab.shape[1], 4), np.uint8)
        body[:, :img.shape[1]] = img
        items.append((a, np.concatenate([lab, body], 0)))
        print(f"{i:3d} {s:5.2f} {a}")
    os.makedirs(out, exist_ok=True)
    sheet, _ = find_text.contact_sheet(items, scale=2, width=1400)
    png.write(os.path.join(out, "sheet.png"), sheet)
    print(f"{len(scored)} candidates; top {len(items)} on {out}/sheet.png")


if __name__ == "__main__":
    main(sys.argv)
