"""CLEAN ROOM: build a sm64-port tree whose assets are all generated.

Reads only games/sm64/spec (coarse facts) and the pristine decomp source
(which contains no extracted assets). Writes every file the decomp's
extract_assets.py would have written:
  * textures  - coarse colour grid + 2-bit alpha outline + our own detail
                noise; font glyphs and HUD icons are drawn from scratch
                (cleanroom.gfx.strokefont + simple shapes) and mapped to
                characters from the decomp's C symbol names,
  * samples   - resynthesised from the coarse audio outline, same length,
                rate and loop points, with our own VADPCM codebook,
  * sequences / demo inputs - kept facts (user scope), copied.

Usage: python -m games.sm64.generate <pristine sm64-port> <clean tree out>
"""
import glob
import hashlib
import json
import os
import re
import shutil
import struct
import sys

import numpy as np

from cleanroom.gfx import png, strokefont
from cleanroom.audio import descriptor, vadpcm
from . import drawn, facepaint, voices, paintings

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec")
OVERRIDES = os.path.join(HERE, "overrides")


def _h(*parts) -> int:
    return int.from_bytes(hashlib.sha1("/".join(map(str, parts)).encode()).digest()[:4], "little")


# ----------------------------------------------------------------- textures

def _upsample_grid(grid, n, w, h):
    g = np.asarray(grid, np.float32).reshape(n, n, 4)
    ys = (np.arange(h, dtype=np.float32) + 0.5) / max(1, h) * n - 0.5
    xs = (np.arange(w, dtype=np.float32) + 0.5) / max(1, w) * n - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, n - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, n - 1)
    y1, x1 = np.clip(y0 + 1, 0, n - 1), np.clip(x0 + 1, 0, n - 1)
    fy = np.clip(ys - np.floor(ys), 0, 1)[:, None, None]
    fx = np.clip(xs - np.floor(xs), 0, 1)[None, :, None]
    top = g[y0][:, x0] * (1 - fx) + g[y0][:, x1] * fx
    bot = g[y1][:, x0] * (1 - fx) + g[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def _detail(seed, w, h, amount=0.06, cell=4.0):
    """Our own soft luminance noise (smoothed value noise)."""
    rng = np.random.default_rng(seed)
    gh, gw = int(h / cell) + 3, int(w / cell) + 3
    lat = rng.standard_normal((gh, gw)).astype(np.float32)
    ys, xs = np.arange(h, dtype=np.float32) / cell, np.arange(w, dtype=np.float32) / cell
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
    fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
    v = (lat[y0][:, x0] * (1 - fx) + lat[y0][:, x0 + 1] * fx) * (1 - fy) + \
        (lat[y0 + 1][:, x0] * (1 - fx) + lat[y0 + 1][:, x0 + 1] * fx) * fy
    return 1.0 + amount * v


def _unpack_alpha2(hexstr, w, h):
    b = np.frombuffer(bytes.fromhex(hexstr), np.uint8)
    a = np.empty(len(b) * 4, np.uint8)
    a[0::4], a[1::4], a[2::4], a[3::4] = b >> 6, (b >> 4) & 3, (b >> 2) & 3, b & 3
    return a[:w * h].reshape(h, w).astype(np.float32) * 85.0


def from_digest(path, d):
    w, h = d["w"], d["h"]
    n = int(round(len(d["grid"]) ** 0.5))
    rgba = _upsample_grid(d["grid"], n, w, h)
    amount = 0.03 if n > 4 else 0.07
    rgba[..., :3] *= _detail(_h("detail", path), w, h, amount, 4.0 if n == 4 else 8.0)[..., None]
    if "alpha2" in d:
        a = _unpack_alpha2(d["alpha2"], w, h)
        rgba[..., 3] = a
    else:
        rgba[..., 3] = 255
    return np.clip(rgba, 0, 255).astype(np.uint8)


# ------------------------------------------------------------ glyphs/icons

NAMED = {"ampersand": "&", "apostrophe": "'", "exclamation": "!", "question": "?", "percent": "%",
         "period": ".", "comma": ",", "colon": ":", "dash": "-", "slash": "/", "double_quote": '"',
         "double_quote_open": '"', "double_quote_close": '"', "decimal_point": ".",
         "open_parentheses": "(", "close_parentheses": ")", "close_open_parentheses": ")(",
         "tilde": "~", "multiply": "x*", "double_exclamation": "!!", "interpunct": "·",
         "ellipsis": "...", "umlaut": "¨", "cedilla_mayus": "C", "EU_slash": "/"}
ICONS = {"coin", "star", "star_filled", "star_hollow", "mario_head", "camera", "lakitu", "no_camera",
         "arrow_up", "arrow_down", "mface1", "mface2", "left_right_arrow", "beta_key"}


def glyph_map(tree):
    """png path -> (category, name) from the decomp's texture symbols."""
    out = {}
    files = glob.glob(os.path.join(tree, "bin", "*.c")) + \
        glob.glob(os.path.join(tree, "levels", "menu", "**", "*.c"), recursive=True)
    for f in files:
        s = open(f, encoding="latin1").read()
        for sym, path in re.findall(r"(texture_\w*char\w*)\[\] = \{\s*#include \"([^\"]+)\"", s):
            m = re.match(r"texture_(hud|font|menu_font|credits|menu_hud)_char_(us_|eu_|jp_)?(.+)", sym)
            if m:
                out[path.replace(".inc.c", ".png")] = (m.group(1), m.group(2) or "", m.group(3))
    return out


def charmap(tree):
    """char -> dialog code, from the decomp's charmap.txt (escapes resolved)."""
    cm = {}
    for line in open(os.path.join(tree, "charmap.txt"), encoding="utf8"):
        m = re.match(r"'(\\?.)'\s*=\s*0x([0-9A-Fa-f]+)\s*$", line.strip())
        if m:
            c = m.group(1)
            c = {"\\n": "\n", "\\t": "\t"}.get(c, c[-1])
            cm[c] = int(m.group(2), 16)
    return cm


def us_font_chars(tree):
    """US dialog glyph png path -> the ASCII character the game text uses
    for its code (main_font_lut + charmap). Symbol names can mislead: code
    0x9F is named 'slash' but is the text's '-'."""
    src = open(os.path.join(tree, "bin", "segment2.c"), encoding="latin1").read()
    body = src[src.index("main_font_lut[]"):]
    body = body[:body.index("};")]
    us = body[body.index("texture_font_char_us_0"):]
    us = re.sub(r"//[^\n]*|/\*.*?\*/", "", us[:us.index("#")], flags=re.S)
    syms = [t.strip() for t in us.replace("\n", " ").split(",") if t.strip()]
    paths = dict((sym, path.replace(".inc.c", ".png")) for sym, path in
                 re.findall(r"(texture_font_char_us_\w+)\[\] = \{\s*#include \"([^\"]+)\"", src))
    by_code = {}
    for ch, code in charmap(tree).items():
        if ch.isascii() and ch.isprintable():
            by_code.setdefault(code, ch)
    return {paths[sym]: by_code[i] for i, sym in enumerate(syms) if sym in paths and i in by_code}


def dialog_widths(tree):
    """Proportional advance per charmap character (from the decomp source)."""
    cm = charmap(tree)
    src = open(os.path.join(tree, "src", "game", "ingame_menu.c"), encoding="latin1").read()
    body = src[src.index("gDialogCharWidths[256]"):]
    body = body[body.index("{") + 1:]
    body = re.sub(r"#ifdef VERSION_EU.*?#else", "", body, flags=re.S)
    body = re.sub(r"#endif", "", body)
    vals = [int(v) for v in re.findall(r"\b\d+\b", body[:body.index("};")])]
    return {c: vals[code] for c, code in cm.items() if code < len(vals)}


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


DIALOG_STROKE = 0.6     # ~1 px strokes: small glyphs stay legible at 1-bit alpha
SMALL_STROKE = 0.55


def glyph_texture(cat, name, d, widths, char=None):
    w, h = d["w"], d["h"]
    if cat == "font" and name.startswith("button_"):
        dw, dh = h, w                       # stored transposed (see below)
        return button(name[7:], dw, dh).transpose(1, 0, 2)[::-1, ::-1]
    if name in ICONS:
        if cat == "font":
            return icon(name, h, w).transpose(1, 0, 2)[::-1, ::-1]
        return icon(name, w, h)
    ch = char or NAMED.get(name, name)
    ch = ch.split("*")[0] if "*" in ch else ch
    if cat == "font":
        # Dialog glyphs are stored as 16x8 and drawn rotated (8 wide, 16 tall;
        # s runs up, t runs left). Draw upright in the proportional advance.
        dw, dh = h, w
        adv = widths.get(ch, 7) if len(ch) == 1 else dw
        cellw = int(np.clip(adv - 1, 2, dw))
        m = np.zeros((dh, dw), np.float32)
        body = _text_mask(ch, cellw, dh - 2, th=DIALOG_STROKE)
        m[1:dh - 1, :cellw] = body >= 0.5      # ia4 keeps 1 bit of alpha
        img = np.zeros((dh, dw, 4), np.float32)
        img[..., :3] = 255
        img[..., 3] = m * 255
        return img.transpose(1, 0, 2)[::-1, ::-1]
    m = _text_mask(ch, w, h, th=SMALL_STROKE if h <= 8 else None)
    if cat == "menu_font":
        m = (m >= 0.5).astype(np.float32)
    img = np.zeros((h, w, 4), np.float32)
    if cat in ("hud", "menu_hud", "credits"):
        if w >= 16:
            _layer(img, _outline(m), (30, 15, 0))
        grad = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        fill = np.zeros((h, w, 4), np.float32)
        fill[..., 0] = 255
        fill[..., 1] = 235 - 110 * grad
        fill[..., 2] = 90 - 70 * grad
        a = m[..., None]
        img[..., :3] = img[..., :3] * (1 - a) + fill[..., :3] * a
        img[..., 3] = np.maximum(img[..., 3], m * 255)
    else:                                   # menu font: white with coverage
        img[..., :3] = 255
        img[..., 3] = m * 255
    return img


IPL3_ORDER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!\"#'*+,-./:=?@"


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


_LABELS = None


def text_labels():
    global _LABELS
    if _LABELS is None:
        _LABELS = {k: v for k, v in json.load(open(os.path.join(HERE, "text_labels.json"))).items()
                   if not k.startswith("_")}
    return _LABELS


def ipl3_glyph(path, w, h):
    k = int(re.search(r"ipl3_font_(\d+)", path).group(1))
    img = np.zeros((h, w, 4), np.float32)
    if k < len(IPL3_ORDER):
        m = strokefont.render(IPL3_ORDER[k], w, h)
        img[..., :3] = 255
        img[..., 3] = (m > 0.5) * 255.0          # 1-bit format
    return img


# ------------------------------------------------------------------ samples

def _pstr_len(b, o):
    n = b[o]
    return 1 + n + ((1 + n) & 1)


def _markers(mark_hex):
    b = bytes.fromhex(mark_hex)
    n = struct.unpack(">H", b[:2])[0]
    o, out = 2, {}
    for _ in range(n):
        mid, pos = struct.unpack(">HI", b[o:o + 6])
        out[mid] = pos
        o += 6 + _pstr_len(b, o + 6)
    return out


def _chunk(tag, data):
    return tag + struct.pack(">I", len(data)) + data + (b"\0" if len(data) & 1 else b"")


def two_predictors(x):
    """Two order-2 predictors fitted to our own waveform (least squares per
    16-sample frame, then 2-means). Retail banks use 2 predictors per book;
    bigger books grow the bank past the game's fixed audio pools."""
    fits = []
    for s in range(2, len(x) - 16, 16):
        y, p1, p2 = x[s:s + 16], x[s - 1:s + 15], x[s - 2:s + 14]
        A = np.stack([p1, p2], 1)
        if (y ** 2).sum() < 1e3:
            continue
        a, *_ = np.linalg.lstsq(A, y, rcond=None)
        fits.append(a)
    if len(fits) < 2:
        return [(1.0, 0.0), (1.8, -0.82)]
    f = np.clip(np.asarray(fits), [-1.95, -0.98], [1.95, 0.98])
    c = f[[np.argmin(f[:, 0]), np.argmax(f[:, 0])]].copy()
    for _ in range(12):
        lab = np.argmin(((f[:, None, :] - c[None]) ** 2).sum(-1), 1)
        for k in range(2):
            if (lab == k).any():
                c[k] = f[lab == k].mean(0)
    out = []
    for a1, a2 in c:                       # keep the filters stable
        a2 = float(np.clip(a2, -0.98, 0.98))
        a1 = float(np.clip(a1, -(1 - a2) + 0.02, (1 - a2) - 0.02))
        out.append((a1, a2))
    return out


def gen_sample(path, d):
    n, rate = d["nframes"], d["rate"]
    x = voices.cached(path)                 # spoken lines (TTS), else resynthesis
    if x is None:
        x = descriptor.synthesize(d["desc"], n, rate, seed=_h("smp", path))
    if "MARK" in d and "INST" in d:
        inst = bytes.fromhex(d["INST"])
        play, beg, end = struct.unpack(">hHH", inst[8:14])     # sustain loop
        mk = _markers(d["MARK"])
        if play and beg in mk and end in mk and mk[end] > mk[beg]:
            x = descriptor.make_loop_seamless(x, mk[beg], mk[end])
    # +-1 LSB of our own dither: smooth ramps would otherwise coincide with
    # ramps in unrelated retail samples byte-for-byte
    dither = np.random.default_rng(_h("dither", path)).integers(-1, 2, n)
    pcm = np.clip(np.round(np.clip(x, -1, 1) * 32000) + dither, -32768, 32767).astype(">i2").tobytes()
    book = vadpcm.make_book(two_predictors(np.frombuffer(pcm, ">i2").astype(np.float64)))
    codes = b"stoc" + b"\x0bVADPCMCODES" + struct.pack(">hhh", 1, book["order"], book["npred"]) + \
        struct.pack(">%dh" % len(book["book"]), *book["book"])
    body = b"AIFF" + _chunk(b"COMM", bytes.fromhex(d["comm"]))
    for tag in ("MARK", "INST"):
        if tag in d:
            body += _chunk(tag.encode(), bytes.fromhex(d[tag]))
    body += _chunk(b"APPL", codes) + _chunk(b"SSND", struct.pack(">II", 0, 0) + pcm)
    return b"FORM" + struct.pack(">I", len(body)) + body


# --------------------------------------------------------------------- main

def prepare_tree(pristine, out):
    if not os.path.exists(os.path.join(out, "Makefile")):
        shutil.copytree(pristine, out, ignore=shutil.ignore_patterns(".git", "build", "baserom.*"))


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def override(path):
    p = os.path.join(OVERRIDES, path)
    return p if os.path.exists(p) else None


def main(argv):
    pristine, out = argv[1], argv[2]
    only = argv[3] if len(argv) > 3 else None       # "tex" | "snd" | None
    prepare_tree(pristine, out)
    spec = json.load(open(os.path.join(SPEC, "assets.json")))
    tex = json.load(open(os.path.join(SPEC, "textures.json")))
    smp = json.load(open(os.path.join(SPEC, "samples.json")))
    gmap, widths, uschars = glyph_map(out), dialog_widths(out), us_font_chars(out)
    counts = {"digest": 0, "glyph": 0, "override": 0, "sample": 0, "kept": 0}
    for a in spec["assets"]:
        dst = os.path.join(out, a)
        if a in tex and only in (None, "tex"):
            d = tex[a]
            ov = override(a)
            if ov:
                img = png.read(ov)
                assert img.shape[:2] == (d["h"], d["w"]), (a, img.shape)
                counts["override"] += 1
            elif a in facepaint.briefs():
                alpha = _unpack_alpha2(d["alpha2"], d["w"], d["h"]) if "alpha2" in d else None
                img = facepaint.render(facepaint.briefs()[a], d["w"], d["h"], d["grid"], alpha, _h("face", a))
                img = np.clip(img, 0, 255).astype(np.uint8)
                counts["face"] = counts.get("face", 0) + 1
            elif "alpha2" in d and drawn.drawn(a, _unpack_alpha2(d["alpha2"], d["w"], d["h"])) is not None:
                img = drawn.drawn(a, _unpack_alpha2(d["alpha2"], d["w"], d["h"]))
                img = np.clip(img, 0, 255).astype(np.uint8)
                counts["drawn"] = counts.get("drawn", 0) + 1
            elif a in text_labels():
                img = np.clip(label_texture(text_labels()[a], d["w"], d["h"]), 0, 255).astype(np.uint8)
                counts["glyph"] += 1
            elif "ipl3_font_" in a:
                img = np.clip(ipl3_glyph(a, d["w"], d["h"]), 0, 255).astype(np.uint8)
                counts["glyph"] += 1
            elif a in gmap:
                cat, _, name = gmap[a]
                img = np.clip(glyph_texture(cat, name, d, widths, uschars.get(a)), 0, 255).astype(np.uint8)
                counts["glyph"] += 1
            else:
                img = from_digest(a, d)
                counts["digest"] += 1
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            png.write(dst, img)
        elif a in smp and only in (None, "snd"):
            _write(dst, gen_sample(a, smp[a]))
            counts["sample"] += 1
        elif only is None and (a.endswith(".m64") or a.endswith(".bin")):
            _write(dst, open(os.path.join(SPEC, "kept", a), "rb").read())
            counts["kept"] += 1
    if only in (None, "tex"):
        counts["pictures"] = paintings.write_all(out)     # needs the textures above
    with open(os.path.join(out, ".assets-local.txt"), "w", newline="\n") as f:
        f.write("\n".join(spec["header"] + spec["assets"]) + "\n")
    print("generated:", ", ".join(f"{k} {v}" for k, v in counts.items()), "->", out)


if __name__ == "__main__":
    main(sys.argv)
