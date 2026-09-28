"""Procedurally drawn textures for details a coarse colour grid cannot carry
(Mario's eyes and cap emblem). Shapes come only from the kept 2-bit alpha
outline in the spec; everything inside is drawn here.
"""
import numpy as np

from cleanroom.gfx import strokefont

SCLERA = (246, 246, 250)
IRIS = (40, 110, 220)
PUPIL = (12, 12, 20)
SKIN = (254, 196, 140)
BROW = (60, 30, 12)
LASH = (40, 20, 10)

GAZE = {"center": (0, 0), "left": (-0.22, 0), "right": (0.22, 0), "up": (0, -0.22), "down": (0, 0.22)}


def _eye_boxes(alpha):
    """Per half of the texture: (brow mask, eye mask, bbox) from the outline."""
    h, w = alpha.shape
    out = []
    for x0, x1 in ((0, w // 2), (w // 2, w)):
        half = np.zeros_like(alpha, bool)
        half[:, x0:x1] = alpha[:, x0:x1] > 0
        rows = np.nonzero(half.any(1))[0]
        if not len(rows):
            continue
        # the brow is the first band of rows, separated from the eye by a gap
        gap = [r for r in range(rows[0], rows[-1]) if not half[r].any()]
        split = gap[0] if gap else rows[0] - 1
        brow = half.copy()
        brow[split:] = False
        eye = half.copy()
        eye[:split + 1] = False
        ys, xs = np.nonzero(eye)
        if len(ys):
            out.append((brow, eye, (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)))
    return out


def eyes(kind, alpha):
    h, w = alpha.shape
    img = np.zeros((h, w, 4), np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) + 0.5
    for brow, eye, (bx0, by0, bx1, by1) in _eye_boxes(alpha):
        img[brow] = (*BROW, 255)
        img[eye] = (*SKIN, 255) if kind.startswith("closed") else (*SCLERA, 255)
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        ew, eh = bx1 - bx0, by1 - by0
        if kind.startswith("closed"):
            lash = eye & (np.abs(yy - cy) < 0.9)
            img[lash] = (*LASH, 255)
            continue
        if kind == "dead":
            d1 = np.abs((xx - cx) / ew - (yy - cy) / eh) < 0.07
            d2 = np.abs((xx - cx) / ew + (yy - cy) / eh) < 0.07
            img[eye & (d1 | d2)] = (*PUPIL, 255)
            continue
        gx, gy = GAZE.get(kind, (0, 0))
        ix, iy = cx + gx * ew, cy + gy * eh
        r = np.hypot((xx - ix) / (ew * 0.31), (yy - iy) / (eh * 0.36))
        img[eye & (r < 1.0)] = (*IRIS, 255)
        img[eye & (r < 0.5)] = (*PUPIL, 255)
        hl = np.hypot(xx - (ix - ew * 0.1), yy - (iy - eh * 0.14)) < max(0.8, ew * 0.07)
        img[eye & hl] = (*SCLERA, 255)
        if kind == "half_closed":
            lid = eye & (yy < cy)
            img[lid] = (*SKIN, 255)
            img[eye & (np.abs(yy - cy) < 0.8)] = (*LASH, 255)
    return img


def emblem(alpha, fg=(230, 20, 30), bg=(250, 250, 250)):
    """White oval with a bold red M, inside the kept outline."""
    h, w = alpha.shape
    img = np.zeros((h, w, 4), np.float32)
    inside = alpha > 0
    img[inside] = (*bg, 255)
    ys, xs = np.nonzero(inside)
    if len(ys):
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        mw, mh = int((x1 - x0) * 0.62), int((y1 - y0) * 0.8)
        m = strokefont.render("M", mw, mh, thickness=max(1.0, mh * 0.12))
        ox, oy = x0 + ((x1 - x0) - mw) // 2, y0 + ((y1 - y0) - mh) // 2
        a = m[..., None]
        reg = img[oy:oy + mh, ox:ox + mw, :3]
        img[oy:oy + mh, ox:ox + mw, :3] = reg * (1 - a) + np.asarray(fg, np.float32) * a
    img[..., 3] = np.where(inside, alpha, 0)
    return img


SEGMENTS = {"full": 8, "seven_segments": 7, "six_segments": 6, "five_segments": 5, "four_segments": 4,
            "three_segments": 3, "two_segments": 2, "one_segment": 1}


def _meter_color(n):
    return (40, 140, 255) if n >= 7 else (40, 200, 60) if n >= 5 else (250, 225, 20) if n >= 3 else (240, 40, 40)


def meter_pie(n, alpha):
    """Health pie: 8 wedges filled clockwise from 12 o'clock, gold rim."""
    h, w = alpha.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) + 0.5
    ys, xs = np.nonzero(alpha > 0)
    cx, cy = (xs.min() + xs.max() + 1) / 2, (ys.min() + ys.max() + 1) / 2
    rx, ry = (xs.max() + 1 - xs.min()) / 2, (ys.max() + 1 - ys.min()) / 2
    ang = (np.degrees(np.arctan2(yy - cy, xx - cx)) + 90) % 360        # 0 = up, clockwise
    r = np.hypot((xx - cx) / rx, (yy - cy) / ry)
    col = np.asarray(_meter_color(n), np.float32)
    wedge = (ang // 45).astype(int)
    img = np.zeros((h, w, 4), np.float32)
    img[..., :3] = np.where((wedge < n)[..., None], col, col * 0.22)
    shade = 1.15 - 0.35 * r                                              # soft dome
    img[..., :3] *= shade[..., None]
    line = (np.minimum(ang % 45, 45 - ang % 45) * np.pi / 180 * r * rx) < 0.5
    img[line & (r < 0.86), :3] *= 0.55
    img[r >= 0.86, :3] = (215, 160, 80)
    img[..., 3] = alpha
    return np.clip(img, 0, 255)


def meter_base(alpha64):
    """The dial behind the pie: tan rim, dark centre, 'POWER' letters above."""
    h, w = alpha64.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) + 0.5
    img = np.zeros((h, w, 4), np.float32)
    img[..., :3] = (228, 184, 122)
    img[..., :3] *= (1 + 0.08 * np.sin(yy * 0.9 + np.sin(xx * 0.3) * 2))[..., None]    # our wood grain
    cx, cy = w / 2, h * 0.62
    r = np.hypot((xx - cx) / (w * 0.26), (yy - cy) / (h * 0.22))
    img[r < 1, :3] = (70, 8, 10)
    img[(r < 1) & (r > 0.9), :3] = (120, 30, 20)
    colors = [(235, 40, 30), (250, 200, 20), (40, 190, 60), (40, 130, 250), (230, 80, 200)]
    lw, lh = 11, 14
    top = 18                                  # letters get our own alpha, not the old outline
    alpha64 = alpha64.copy()
    alpha64[:top] = 0
    for i, (ch, c) in enumerate(zip("POWER", colors)):
        x0 = 4 + i * lw
        y0 = 1 + int(round(abs(i - 2) * 1.2))                               # gentle arc
        m = strokefont.render(ch, lw, lh, thickness=1.3)
        edge = np.zeros_like(m)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                edge = np.maximum(edge, np.roll(np.roll(m, dy, 0), dx, 1))
        reg = img[y0:y0 + lh, x0:x0 + lw, :3]
        reg[:] = reg * (1 - edge[..., None]) + np.asarray((60, 20, 10), np.float32) * edge[..., None]
        reg[:] = reg * (1 - m[..., None]) + np.asarray(c, np.float32) * m[..., None]
        alpha64[y0:y0 + lh, x0:x0 + lw] = np.maximum(alpha64[y0:y0 + lh, x0:x0 + lw], edge * 255)
    img[..., 3] = alpha64
    return np.clip(img, 0, 255)


_METER_ALPHA = {}


def drawn(path, alpha):
    """Return an RGBA image for paths drawn here, else None."""
    name = path.rsplit("/", 1)[-1].split(".")[0]
    if name.startswith("power_meter_"):
        key = name[len("power_meter_"):]
        if key in SEGMENTS:
            return meter_pie(SEGMENTS[key], alpha)
        if key in ("left_side", "right_side"):
            _METER_ALPHA[key] = alpha
            other = "right_side" if key == "left_side" else "left_side"
            if other not in _METER_ALPHA:            # need both halves' outlines
                import json, os
                from .generate import _unpack_alpha2
                d = json.load(open(os.path.join(os.path.dirname(__file__), "spec", "textures.json")))[
                    path.replace(key, other)]
                _METER_ALPHA[other] = _unpack_alpha2(d["alpha2"], d["w"], d["h"])
            full = meter_base(np.concatenate([_METER_ALPHA["left_side"], _METER_ALPHA["right_side"]], 1))
            return full[:, :32] if key == "left_side" else full[:, 32:]
    if name.startswith("mario_eyes_"):
        kind = name[len("mario_eyes_"):].replace("_unused", "")
        kind = "closed" if kind.startswith("closed") else kind
        return eyes(kind, alpha)
    if name in ("mario_logo", "mario_cap_logo"):
        return emblem(alpha)
    return None
