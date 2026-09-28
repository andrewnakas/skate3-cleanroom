"""Glyphs, icons, buttons and text labels drawn from scratch (stroke font +
simple shapes). Shared by every game: HUD digits/letters, dialog fonts,
coin/star/heart-style icons, controller buttons, re-typeset text textures.

Storage helpers cover what the SM64/PW64 fonts needed:
  store(img, rotate="none"|"cw90_flip"|"transpose", flip_v=False)
  one_bit(img)  - for IA4/I4 fonts whose alpha keeps 1 bit (use thin strokes)
"""
import numpy as np

from cleanroom.gfx import strokefont

ICONS = {"coin", "star", "star_filled", "star_hollow", "mario_head", "camera", "lakitu", "no_camera",
         "arrow_up", "arrow_down", "mface1", "mface2", "left_right_arrow", "beta_key"}


def _poly_mask(w, h, pts, ss=4):
    yy, xx = np.mgrid[0:h * ss, 0:w * ss].astype(np.float32)
    xx, yy = (xx + 0.5) / ss, (yy + 0.5) / ss
    inside = np.zeros(xx.shape, bool)
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        cond = ((y0 > yy) != (y1 > yy)) & (xx < (x1 - x0) * (yy - y0) / (y1 - y0 + 1e-9) + x0)
        inside ^= cond
    return inside.reshape(h, ss, w, ss).mean((1, 3))


def _disc(w, h, cx, cy, r, ss=4):
    yy, xx = np.mgrid[0:h * ss, 0:w * ss].astype(np.float32)
    d = np.hypot((xx + 0.5) / ss - cx, (yy + 0.5) / ss - cy)
    return (d <= r).reshape(h, ss, w, ss).mean((1, 3))


def _star_pts(cx, cy, r, inner=0.45):
    pts = []
    for i in range(10):
        a = -np.pi / 2 + i * np.pi / 5
        rr = r if i % 2 == 0 else r * inner
        pts.append((cx + rr * np.cos(a), cy + rr * np.sin(a)))
    return pts


def _layer(img, mask, color):
    a = mask[..., None] * (color[3] / 255.0 if len(color) > 3 else 1.0)
    img[..., :3] = img[..., :3] * (1 - a) + np.asarray(color[:3], np.float32) * a
    img[..., 3] = np.maximum(img[..., 3], a[..., 0] * 255)


def _outline(mask, r=1):
    m = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            m = np.maximum(m, np.roll(np.roll(mask, dy, 0), dx, 1))
    return m


def icon(name, w, h):
    img = np.zeros((h, w, 4), np.float32)
    cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 0.5
    if name == "coin":
        _layer(img, _disc(w, h, cx, cy, r), (120, 70, 0))
        _layer(img, _disc(w, h, cx, cy, r - 1), (250, 200, 40))
        _layer(img, _poly_mask(w, h, [(cx - r * .15, cy - r * .55), (cx + r * .15, cy - r * .55),
                                      (cx + r * .15, cy + r * .55), (cx - r * .15, cy + r * .55)]), (170, 110, 10))
    elif name in ("star", "star_filled", "star_hollow", "beta_key"):
        pts = _star_pts(cx, cy + r * 0.08, r)
        m = _poly_mask(w, h, pts)
        if name == "star_hollow":
            inner = _poly_mask(w, h, _star_pts(cx, cy + r * 0.08, r * 0.55))
            m = np.clip(m - inner, 0, 1)
            _layer(img, m, (255, 255, 255))
        elif name == "star_filled" and w <= 16 and h <= 16 and False:
            pass
        else:
            _layer(img, _outline(m), (90, 50, 0))
            _layer(img, m, (255, 225, 40))
    elif name in ("mario_head", "mface1", "mface2"):
        _layer(img, _disc(w, h, cx, cy + r * .1, r * .95), (60, 20, 10))
        _layer(img, _disc(w, h, cx, cy + r * .15, r * .8), (250, 190, 140))
        cap = _disc(w, h, cx, cy - r * .25, r * .8) * (np.arange(h)[:, None] < cy - r * .05)
        _layer(img, cap, (220, 20, 20))
        _layer(img, _disc(w, h, cx, cy - r * .45, r * .22), (255, 255, 255))
        _layer(img, _poly_mask(w, h, [(cx - r * .55, cy + r * .35), (cx + r * .55, cy + r * .35),
                                      (cx + r * .45, cy + r * .5), (cx - r * .45, cy + r * .5)]), (50, 25, 10))
    elif name in ("camera", "no_camera", "lakitu"):
        body = _poly_mask(w, h, [(cx - r * .9, cy - r * .5), (cx + r * .5, cy - r * .5),
                                 (cx + r * .5, cy + r * .5), (cx - r * .9, cy + r * .5)])
        lens = _poly_mask(w, h, [(cx + r * .5, cy - r * .2), (cx + r * .95, cy - r * .5),
                                 (cx + r * .95, cy + r * .5), (cx + r * .5, cy + r * .2)])
        if name == "lakitu":
            _layer(img, _disc(w, h, cx, cy, r * .95), (240, 240, 240))
            _layer(img, _disc(w, h, cx, cy - r * .1, r * .45), (250, 200, 60))
            _layer(img, _disc(w, h, cx - r * .15, cy - r * .2, r * .12), (20, 20, 20))
        else:
            _layer(img, _outline(np.maximum(body, lens)), (20, 20, 20))
            _layer(img, np.maximum(body, lens), (150, 160, 175))
            _layer(img, _disc(w, h, cx - r * .2, cy, r * .28), (40, 50, 70))
            if name == "no_camera":
                x = strokefont._stroke(np.zeros((h, w), np.float32), [[(0, 0), (1, 1)], [(1, 0), (0, 1)]],
                                       2, 2, w - 4, h - 4, 1.0)
                _layer(img, x, (230, 30, 30))
    elif name in ("arrow_up", "arrow_down"):
        pts = [(cx, cy - r * .8), (cx + r * .8, cy + r * .5), (cx - r * .8, cy + r * .5)]
        if name == "arrow_down":
            pts = [(x, h - y) for x, y in pts]
        m = _poly_mask(w, h, pts)
        _layer(img, _outline(m), (40, 20, 0))
        _layer(img, m, (255, 220, 60))
    elif name == "left_right_arrow":
        m = _poly_mask(w, h, [(0.5, cy), (w * .35, cy - h * .3), (w * .35, cy + h * .3)])
        m = np.maximum(m, m[:, ::-1])
        m = np.maximum(m, _poly_mask(w, h, [(w * .3, cy - 1), (w * .7, cy - 1), (w * .7, cy + 1), (w * .3, cy + 1)]))
        _layer(img, m, (255, 255, 255))
    return img


BUTTON_COLORS = {"A": (70, 110, 255), "B": (60, 190, 80), "Z": (150, 150, 150), "R": (150, 150, 150)}


def button(name, w, h):
    img = np.zeros((h, w, 4), np.float32)
    r = min(w, h) / 2 - 0.5
    cx, cy = w / 2, h / 2
    if name.startswith("C"):
        _layer(img, _disc(w, h, cx, cy, r), (240, 200, 30))
        d = name[2:] if len(name) > 1 else ""
        tri = {"up": [(cx, cy - r * .6), (cx + r * .6, cy + r * .4), (cx - r * .6, cy + r * .4)],
               "down": [(cx, cy + r * .6), (cx + r * .6, cy - r * .4), (cx - r * .6, cy - r * .4)],
               "left": [(cx - r * .6, cy), (cx + r * .4, cy - r * .6), (cx + r * .4, cy + r * .6)],
               "right": [(cx + r * .6, cy), (cx - r * .4, cy - r * .6), (cx - r * .4, cy + r * .6)]}.get(d)
        if tri:
            _layer(img, _poly_mask(w, h, tri), (60, 40, 0))
        else:
            _layer(img, strokefont.render("C", w, h), (60, 40, 0))
    else:
        _layer(img, _disc(w, h, cx, cy, r), BUTTON_COLORS.get(name, (150, 150, 150)))
        _layer(img, strokefont.render(name, w, h), (255, 255, 255))
    return img


def _text_mask(s, w, h, th=None):
    if len(s) == 1 or s in ("...",):
        return strokefont.render(s[0], w, h, th) if s != "..." else strokefont.render_line("...", h, thickness=th)[:, :w]
    line = strokefont.render_line(s, h, thickness=th)
    out = np.zeros((h, w), np.float32)
    lw = min(w, line.shape[1])
    out[:, :lw] = line[:, :lw]
    return out


def _fit_line(text, w, h):
    """One line of stroke text, squeezed to fit w (never wider)."""
    line = strokefont.render_line(text, h)
    if line.shape[1] > w:                       # squeeze horizontally
        xs = np.linspace(0, line.shape[1] - 1, w)
        x0 = np.floor(xs).astype(int)
        x1 = np.minimum(x0 + 1, line.shape[1] - 1)
        f = (xs - x0)[None, :]
        line = np.maximum(line[:, x0] * (1 - f) + line[:, x1] * f, 0)
    out = np.zeros((h, w), np.float32)
    out[:, :min(w, line.shape[1])] = line[:, :w]
    return out


def label_texture(label, w, h):
    lines = list(label["lines"]) + ([label["sig"]] if label.get("sig") else [])
    lh = max(3, h // len(lines))
    m = np.zeros((h, w), np.float32)
    for i, t in enumerate(lines):
        x0 = w // 3 if label.get("sig") and i == len(lines) - 1 else 1
        m[i * lh:(i + 1) * lh, x0:] = _fit_line(t, w - x0, lh)
    img = np.zeros((h, w, 4), np.float32)
    img[:] = label["bg"]
    _layer(img, m, label["ink"])
    if label["bg"][3] == 0:
        img[..., 3] = m * label["ink"][3]
    return img


def store(img, rotate="none", flip_v=False):
    """Draw upright, then convert to how the game stores the texture. SM64 US
    dialog glyphs: rotate="transpose_flip" (stored = upright.T flipped both ways)."""
    if rotate == "transpose":
        img = img.transpose(1, 0, 2)
    elif rotate == "transpose_flip":
        img = img.transpose(1, 0, 2)[::-1, ::-1]
    return img[::-1] if flip_v else img


def one_bit(img, thresh=128):
    out = img.copy()
    out[..., 3] = (out[..., 3] >= thresh) * 255.0
    return out


def text_glyph(ch, w, h, style="white", thickness=None):
    """One character in a cell. style: white (alpha = coverage), hud (gold
    gradient + dark outline), ink (dark on transparent)."""
    m = _text_mask(ch, w, h, th=thickness)
    img = np.zeros((h, w, 4), np.float32)
    if style == "hud":
        if w >= 12:
            _layer(img, _outline(m), (30, 15, 0))
        g = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        fill = np.stack([np.full_like(g * np.ones((1, w)), 255), 235 - 110 * g * np.ones((1, w)), 90 - 70 * g * np.ones((1, w))], -1)
        img[..., :3] = img[..., :3] * (1 - m[..., None]) + fill * m[..., None]
        img[..., 3] = np.maximum(img[..., 3], m * 255)
    elif style == "ink":
        img[..., :3] = (30, 25, 25)
        img[..., 3] = m * 255
    else:
        img[..., :3] = 255
        img[..., 3] = m * 255
    return img
