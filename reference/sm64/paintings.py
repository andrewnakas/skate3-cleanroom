"""Castle pictures, made after the clean textures exist:

  * level paintings: renders of each level's own geometry (level_render.py)
    with our generated textures, in a gold frame; split into the painting's
    bottom/top texture halves,
  * Peach / Bowser portrait, star door, notice sign, sun window: our own
    illustrations (picture_briefs.json via facepaint),
  * stained-glass Peach windows: the Peach illustration as leaded glass
    (posterised panes + dark lead lines) inside the kept window outline.
"""
import json
import os

import numpy as np

from cleanroom.gfx import png
from . import facepaint, level_render

HERE = os.path.dirname(os.path.abspath(__file__))
CI = "levels/castle_inside/"

# painting -> (level, bottom file, top file, camera)
LEVEL_PAINTINGS = {
    "bob": ("bob", "18", "17", {"yaw": 35, "pitch": 26, "dist": 0.8}),
    "ccm": ("ccm", "20", "19", {"yaw": 20, "pitch": 14, "dist": 0.7}),
    "wf": ("wf", "22", "21", {"yaw": 160, "pitch": 22, "dist": 0.7}),
    "jrb": ("jrb", "24_us", "23_us", {"yaw": 40, "pitch": 10, "dist": 0.75}),
    "lll": ("lll", "25", "26", None),
    "ssl": ("ssl", "28", "27", {"yaw": 180, "pitch": 20, "dist": 0.6}),
    "wdw": ("wdw", "32", "31", None),
    "thi": ("thi", "34", "33", {"yaw": 120, "pitch": 15, "dist": 0.7}),
    "ttm": ("ttm", "36", "35", {"yaw": 30, "pitch": 12, "dist": 0.75}),
    "sl": ("sl", "40", "39", None),
}
GLASS = [(250, 210, 60), (252, 220, 185), (240, 145, 195), (60, 100, 225), (110, 90, 210),
         (225, 40, 60), (245, 245, 245), (70, 90, 200), (150, 110, 210)]
GOLD, GOLD_DARK =np.array([235, 180, 50], np.float32), np.array([120, 70, 15], np.float32)


def briefs():
    d = json.load(open(os.path.join(HERE, "picture_briefs.json")))
    return {k: v for k, v in d.items() if not k.startswith("_")}


def framed(img, px=3):
    out = img.copy()
    h, w = out.shape[:2]
    out[:px], out[-px:], out[:, :px], out[:, -px:] = GOLD, GOLD, GOLD, GOLD
    out[px - 1, px - 1:w - px + 1] = GOLD_DARK
    out[h - px, px - 1:w - px + 1] = GOLD_DARK
    out[px - 1:h - px + 1, px - 1] = GOLD_DARK
    out[px - 1:h - px + 1, w - px] = GOLD_DARK
    return out


def clock(w, h):
    """Tick Tock Clock painting: a clock face (the level is inside a clock)."""
    yy, xx = np.mgrid[0:h * 4, 0:w * 4].astype(np.float32) / 4 + 0.125
    cx, cy = w / 2, h / 2
    r = np.hypot(xx - cx, yy - cy) / (w * 0.45)
    img = np.zeros((h * 4, w * 4, 3), np.float32)
    img[:] = (110, 70, 30)
    img[r < 1] = (240, 230, 190)
    img[(r < 1) & (r > 0.9)] = (40, 140, 60)
    ang = np.degrees(np.arctan2(yy - cy, xx - cx))
    for k in range(12):
        a = -90 + k * 30
        d = np.abs(((ang - a + 180) % 360) - 180)
        img[(d < 3) & (r > 0.72) & (r < 0.86)] = (60, 40, 20)

    def hand(a, length, width, col):
        t = np.radians(a)
        dx, dy = np.cos(t), np.sin(t)
        px, py = xx - cx, yy - cy
        along = px * dx + py * dy
        across = np.abs(-px * dy + py * dx)
        img[(along > -2) & (along < length * w * 0.45) & (across < width)] = col
    hand(-60, 0.5, 1.4, (30, 30, 40))
    hand(10, 0.75, 0.9, (30, 30, 40))
    img[np.hypot(xx - cx, yy - cy) < 2.2] = (200, 160, 40)
    return img.reshape(h, 4, w, 4, 3).mean((1, 3))


def stained(img, alpha, levels=5, seed=0):
    """Leaded glass: posterise into panes, dark lead between panes, a
    little per-pane brightness variation, all inside the kept outline."""
    pal = np.array(GLASS, np.float32)
    d = ((np.clip(img, 0, 255)[..., None, :] - pal) ** 2).sum(-1)
    idx = d.argmin(-1)
    q = pal[idx]
    edge = np.zeros(q.shape[:2], bool)
    edge[:-1] |= idx[:-1] != idx[1:]
    edge[:, :-1] |= idx[:, :-1] != idx[:, 1:]
    rng = np.random.default_rng(seed)
    cell = rng.uniform(0.85, 1.15, (q.shape[0] // 6 + 1, q.shape[1] // 6 + 1))
    shimmer = np.kron(cell, np.ones((6, 6)))[:q.shape[0], :q.shape[1]]
    out = np.clip(q * shimmer[..., None], 0, 255)
    out[edge] = (35, 30, 40)
    rgba = np.zeros(q.shape[:2] + (4,), np.float32)
    rgba[..., :3] = out
    rgba[..., 3] = alpha
    return rgba


def _write(tree, rel, rgb, alpha=None):
    h, w = rgb.shape[:2]
    a = np.full((h, w), 255, np.float32) if alpha is None else alpha
    png.write(os.path.join(tree, rel), np.clip(np.dstack([rgb, a]), 0, 255).astype(np.uint8))


def _spec():
    return json.load(open(os.path.join(HERE, "spec", "textures.json")))


def _alpha(spec, rel):
    from .generate import _unpack_alpha2
    d = spec[rel]
    return _unpack_alpha2(d["alpha2"], d["w"], d["h"]) if "alpha2" in d else None


def write_all(tree):
    spec, B = _spec(), briefs()
    src = level_render.Source(tree)
    n = 0
    for name, (level, bot, top, cam) in LEVEL_PAINTINGS.items():
        img, _ = level_render.render_level(tree, level, 64, 64, cam, src=src)
        img = framed(img)
        _write(tree, CI + top + ".rgba16.png", img[:32])
        _write(tree, CI + bot + ".rgba16.png", img[32:])
        n += 1
    img, _ = level_render.render_level(tree, "hmc", 32, 32, {"yaw": 30, "pitch": 40, "dist": 0.6}, src=src)
    _write(tree, CI + "29.rgba16.png", framed(img, 2))
    img = framed(clock(64, 64))                                    # ttc
    _write(tree, CI + "38.rgba16.png", img[32:])
    _write(tree, CI + "37.rgba16.png", img[:32])
    # portraits: 2x2 tiles of 32x32 (top row first)
    for brief, tiles in (("peach_portrait", ("8", "9", "10", "11")), ("bowser_portrait", ("12", "13", "14", "15"))):
        img = framed(facepaint.render(B[brief], 64, 64, seed=n)[..., :3])
        for k, t in enumerate(tiles):
            y, x = (k // 2) * 32, (k % 2) * 32
            _write(tree, CI + t + ".rgba16.png", img[y:y + 32, x:x + 32])
    door = facepaint.render(B["star_door"], 64, 64, seed=5)[..., :3]
    _write(tree, CI + "5.rgba16.png", door[:, :32])
    _write(tree, CI + "6.rgba16.png", door[:, 32:])
    for brief, rel in (("sun_glass", CI + "1.rgba16.png"), ("notice_sign", CI + "4.rgba16.png")):
        a = _alpha(spec, rel)
        _write(tree, rel, facepaint.render(B[brief], 32, 32, seed=7)[..., :3], a)
    # stained glass Peach: outside window (grounds 2 over 1) and inside oval (castle_inside 3)
    peach = facepaint.render(B["peach_glass"], 64, 64, seed=9)[..., :3]
    g2, g1 = "levels/castle_grounds/2.rgba16.png", "levels/castle_grounds/1.rgba16.png"
    a = np.concatenate([_alpha(spec, g2), _alpha(spec, g1)], 0)
    glass = stained(peach, a, seed=3)
    png.write(os.path.join(tree, g2), np.clip(glass[:32], 0, 255).astype(np.uint8))
    png.write(os.path.join(tree, g1), np.clip(glass[32:], 0, 255).astype(np.uint8))
    tall = facepaint.render(B["peach_glass"], 32, 64, seed=11)[..., :3]
    png.write(os.path.join(tree, CI + "3.rgba16.png"),
              np.clip(stained(tall, _alpha(spec, CI + "3.rgba16.png"), seed=4), 0, 255).astype(np.uint8))
    return n
