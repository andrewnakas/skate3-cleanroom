"""CLEAN ROOM check: typeset text with the generated US dialog font.

Reads the US main_font_lut (code -> texture symbol) and charmap from the
decomp source, un-rotates our generated glyph PNGs and lays out each test
line with gDialogCharWidths. Writes one image; prints unmapped characters.

Usage: python -m games.sm64.font_check <clean tree> <out.png> ["text" ...]
"""
import os
import re
import sys

import numpy as np

from cleanroom.gfx import png
from .generate import dialog_widths, charmap

DEFAULT = ["Dear Mario: Please come to the castle.", "I've baked a cake for you. Yours truly--",
           "ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789", "abcdefghijklmnopqrstuvwxyz !?&%()',.-"]


def font_lut(tree):
    src = open(os.path.join(tree, "bin", "segment2.c"), encoding="latin1").read()
    body = src[src.index("main_font_lut[]"):]
    body = body[:body.index("};")]
    us = body[body.index("texture_font_char_us_0"):]
    us = us[:us.index("#")] if "#" in us else us
    us = re.sub(r"//[^\n]*|/\*.*?\*/", "", us, flags=re.S)
    syms = [t.strip() for t in us.replace("\n", " ").split(",") if t.strip()]
    paths = dict((sym, path.replace(".inc.c", ".png")) for sym, path in
                 re.findall(r"(texture_font_char_us_\w+)\[\] = \{\s*#include \"([^\"]+)\"", src))
    return [paths.get(s) for s in syms]


def main(argv):
    tree, out = argv[1], argv[2]
    lines = argv[3:] or DEFAULT
    lut, cm, widths = font_lut(tree), charmap(tree), dialog_widths(tree)
    rows, missing = [], set()
    for text in lines:
        canvas = np.zeros((18, 8 * len(text) + 8, 4), np.uint8)
        canvas[..., 3] = 255
        x = 2
        for ch in text:
            if ch == " ":
                x += 5
                continue
            code = cm.get(ch)
            path = lut[code] if code is not None and code < len(lut) else None
            if not path:
                missing.add(ch)
                x += 6
                continue
            g = png.read(os.path.join(tree, path))[::-1, ::-1].transpose(1, 0, 2)   # stored -> upright
            a = (g[..., 3:4] >= 128).astype(np.float32)     # ia4: 1-bit alpha in game
            reg = canvas[1:17, x:x + 8, :3].astype(np.float32)
            canvas[1:17, x:x + 8, :3] = (reg * (1 - a) + g[..., :3] * a).astype(np.uint8)
            x += widths.get(ch, 7)
        rows.append(canvas[:, :x + 4])
    w = max(r.shape[1] for r in rows)
    img = np.concatenate([np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0))) for r in rows], 0)
    png.write(out, np.repeat(np.repeat(img, 3, 0), 3, 1))
    print(f"{len(lines)} lines -> {out}; unmapped: {''.join(sorted(missing)) or 'none'}")


if __name__ == "__main__":
    main(sys.argv)
