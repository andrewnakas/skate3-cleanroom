"""Render face briefs (face_briefs.json) into textures.

A brief is our own description of a face texture: a base colour, then a
list of primitives in normalised texture coordinates (x right, y down,
0..1). Where the spec kept a 2-bit alpha outline, it is used as the alpha;
everything inside is painted from the brief.

Primitives (one key names the kind):
  {"e": [cx, cy, rx, ry], "c": rgb, "rot": deg}        filled ellipse
  {"ring": [cx, cy, rx, ry], "w": width, "c": rgb}     ellipse outline
  {"sphere": [cx, cy, rx, ry], "c": rgb}               shaded ball
  {"hl": [cx, cy, r]}                                  white highlight
  {"glow": [cx, cy, rx, ry], "c": rgb}                 soft radial light
  {"poly": [[x, y], ...], "c": rgb}                    filled polygon
  {"line": [[x, y], ...], "w": width, "c": rgb}        stroked polyline
  {"arc": [cx, cy, rx, ry, a0, a1], "w": width, "c"}   arc, degrees, 90 = down
  {"rect": [x0, y0, x1, y1], "c": rgb}
  {"clip": [cx, cy, rx, ry]} / {"clip": null}          limit later ops to an ellipse
  {"outline": px, "c": rgb}                            darken the kept alpha edge
  {"eye": {...}}                                       sclera, iris, pupil, gaze, lid
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SS = 4                                    # supersampling


class Canvas:
    def __init__(self, w, h, base):
        self.w, self.h = w, h
        self.W, self.H = w * SS, h * SS
        ys, xs = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
        self.x = (xs + 0.5) / self.W
        self.y = (ys + 0.5) / self.H
        self.img = np.zeros((self.H, self.W, 3), np.float32)
        self.img[:] = base
        self.clip = None
        self.aspect = w / h                   # to make "round" things round

    def paint(self, mask, color):
        if self.clip is not None:
            mask = mask * self.clip
        m = np.clip(mask, 0, 1)[..., None]
        self.img = self.img * (1 - m) + np.asarray(color[:3], np.float32) * m

    def ell(self, cx, cy, rx, ry, rot=0.0):
        dx, dy = self.x - cx, self.y - cy
        if rot:
            a = math.radians(rot)
            # rotate in pixel space so the angle looks right on wide textures
            px, py = dx * self.aspect, dy
            qx = px * math.cos(a) + py * math.sin(a)
            qy = -px * math.sin(a) + py * math.cos(a)
            dx, dy = qx / self.aspect, qy
        return (dx / max(rx, 1e-4)) ** 2 + (dy / max(ry, 1e-4)) ** 2

    def seg_dist(self, pts):
        d = np.full(self.x.shape, 1e9, np.float32)
        px, py = self.x * self.aspect, self.y
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            x0, x1 = x0 * self.aspect, x1 * self.aspect
            vx, vy = x1 - x0, y1 - y0
            ll = vx * vx + vy * vy or 1e-9
            t = np.clip(((px - x0) * vx + (py - y0) * vy) / ll, 0, 1)
            d = np.minimum(d, np.hypot(px - (x0 + t * vx), py - (y0 + t * vy)))
        return d

    def result(self):
        img = self.img.reshape(self.h, SS, self.w, SS, 3).mean((1, 3))
        return img


def _poly_mask(cv, pts):
    inside = np.zeros(cv.x.shape, bool)
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        cond = ((y0 > cv.y) != (y1 > cv.y)) & (cv.x < (x1 - x0) * (cv.y - y0) / (y1 - y0 + 1e-9) + x0)
        inside ^= cond
    return inside.astype(np.float32)


def _sphere(cv, cx, cy, rx, ry, color, light=(-0.45, -0.55)):
    r2 = cv.ell(cx, cy, rx, ry)
    inside = (r2 <= 1).astype(np.float32)
    nx, ny = (cv.x - cx) / rx, (cv.y - cy) / ry
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
    lx, ly = light
    lz = math.sqrt(max(0.0, 1 - lx * lx - ly * ly))
    lam = np.clip(nx * lx + ny * ly + nz * lz, 0, 1)
    shade = np.asarray(color, np.float32) * (0.3 + 0.75 * lam)[..., None]
    spec = np.clip(lam, 0, 1) ** 24 * 255
    col = np.clip(shade + spec[..., None], 0, 255)
    m = inside[..., None] * (cv.clip[..., None] if cv.clip is not None else 1)
    cv.img = cv.img * (1 - m) + col * m


def _eye(cv, e):
    cx, cy = e["c"]
    rx, ry = e["r"]
    sclera = e.get("sclera", [250, 250, 250])
    lid = e.get("lid", 0.0)
    lidc = e.get("lidc", [0, 0, 0])
    rot = e.get("rot", 0)
    inside = (cv.ell(cx, cy, rx, ry, rot) <= 1).astype(np.float32)
    if e.get("border"):
        cv.paint((cv.ell(cx, cy, rx * (1 + e["border"]), ry * (1 + e["border"] * cv.aspect), rot) <= 1)
                 .astype(np.float32), e.get("borderc", [20, 20, 20]))
    cv.paint(inside, sclera)
    old = cv.clip
    cv.clip = inside if old is None else inside * old
    if e.get("iris"):
        gx, gy = e.get("look", [0, 0])
        ix, iy = cx + gx * rx, cy + gy * ry
        f = e.get("irisr", 0.55)
        irx, iry = rx * f, ry * f * e.get("irisy", 1.0)
        if e.get("ring"):
            cv.paint((cv.ell(ix, iy, irx * 1.18, iry * 1.18) <= 1).astype(np.float32), e["ring"])
        cv.paint((cv.ell(ix, iy, irx, iry) <= 1).astype(np.float32), e["iris"])
        p = e.get("pupil", 0.5)
        if p:
            cv.paint((cv.ell(ix, iy, irx * p, iry * p) <= 1).astype(np.float32), e.get("pupilc", [10, 10, 16]))
        if e.get("hl", True):
            hr = max(irx, iry) * 0.28
            cv.paint((cv.ell(ix - irx * 0.35, iy - iry * 0.4, hr, hr * cv.aspect) <= 1).astype(np.float32),
                     [255, 255, 255])
    if lid > 0:
        top = cy - ry + 2 * ry * lid
        cv.paint((cv.y < top).astype(np.float32), lidc)
        if e.get("lash"):
            cv.paint((np.abs(cv.y - top) < e.get("lashw", 0.03)).astype(np.float32), e["lash"])
    cv.clip = old


def render(brief, w, h, grid=None, alpha=None, seed=0):
    base = brief.get("base", [128, 128, 128])
    if base == "grid" and grid is not None:
        from .generate import _upsample_grid, _detail
        n = int(round(len(grid) ** 0.5))
        g = _upsample_grid(grid, n, w * SS, h * SS)[..., :3]
        g *= _detail(seed, w * SS, h * SS, brief.get("detail", 0.05), 4.0 * SS)[..., None]
        cv = Canvas(w, h, 0)
        cv.img = g.astype(np.float32)
    elif isinstance(base, dict):
        cv = Canvas(w, h, 0)
        t = cv.y[..., None]
        cv.img = np.asarray(base["grad"][0], np.float32) * (1 - t) + np.asarray(base["grad"][1], np.float32) * t
    else:
        cv = Canvas(w, h, base)
        if brief.get("detail"):                  # our own surface noise (scales, skin)
            from .generate import _detail
            cv.img = cv.img * _detail(seed, w * SS, h * SS, brief["detail"], 3.0 * SS)[..., None]
    for op in brief.get("ops", []):
        c = op.get("c", [0, 0, 0])
        if "e" in op:
            cx, cy, rx, ry = op["e"]
            cv.paint((cv.ell(cx, cy, rx, ry, op.get("rot", 0)) <= 1).astype(np.float32), c)
        elif "ring" in op:
            cx, cy, rx, ry = op["ring"]
            wdt = op.get("w", 0.05)
            r2 = cv.ell(cx, cy, rx, ry, op.get("rot", 0))
            cv.paint(((r2 <= 1) & (r2 >= (1 - wdt / max(rx, ry)) ** 2)).astype(np.float32), c)
        elif "sphere" in op:
            _sphere(cv, *op["sphere"], c)
        elif "hl" in op:
            cx, cy, r = op["hl"]
            cv.paint((cv.ell(cx, cy, r, r * cv.aspect) <= 1).astype(np.float32), op.get("c", [255, 255, 255]))
        elif "glow" in op:
            cx, cy, rx, ry = op["glow"]
            cv.paint(np.clip(1 - np.sqrt(cv.ell(cx, cy, rx, ry)), 0, 1) ** 1.5, c)
        elif "poly" in op:
            cv.paint(_poly_mask(cv, op["poly"]), c)
        elif "line" in op:
            cv.paint((cv.seg_dist(op["line"]) <= op.get("w", 0.05) / 2).astype(np.float32), c)
        elif "arc" in op:
            cx, cy, rx, ry, a0, a1 = op["arc"]
            ts = np.radians(np.linspace(a0, a1, 24))
            pts = [(cx + rx * math.cos(t), cy + ry * math.sin(t)) for t in ts]
            cv.paint((cv.seg_dist(pts) <= op.get("w", 0.05) / 2).astype(np.float32), c)
        elif "rect" in op:
            x0, y0, x1, y1 = op["rect"]
            cv.paint(((cv.x >= x0) & (cv.x <= x1) & (cv.y >= y0) & (cv.y <= y1)).astype(np.float32), c)
        elif "clip" in op:
            cv.clip = None if op["clip"] is None else (cv.ell(*op["clip"]) <= 1).astype(np.float32)
        elif "eye" in op:
            _eye(cv, op["eye"])
    rgb = cv.result()
    out = np.zeros((h, w, 4), np.float32)
    out[..., :3] = rgb
    out[..., 3] = 255 if alpha is None else alpha
    for op in brief.get("ops", []):
        if "outline" in op and alpha is not None:
            a = alpha > 0
            k = int(op["outline"])
            edge = np.zeros_like(a)
            for dy in range(-k, k + 1):
                for dx in range(-k, k + 1):
                    edge |= ~np.roll(np.roll(a, dy, 0), dx, 1)
            edge &= a
            out[edge, :3] = op.get("c", [0, 0, 0])
    return out


_BRIEFS = None


def briefs():
    global _BRIEFS
    if _BRIEFS is None:
        raw = json.load(open(os.path.join(HERE, "face_briefs.json")))
        out = {}
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            if "use" in v:                      # variant: another brief + overrides
                base = dict(raw[v["use"]])
                base.update({kk: vv for kk, vv in v.items() if kk != "use"})
                v = base
            out[k] = v
        _BRIEFS = out
    return _BRIEFS
