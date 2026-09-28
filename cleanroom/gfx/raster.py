"""A tiny software rasteriser (numpy): z-buffered, Gouraud-shaded triangles
with per-vertex RGBA and optional per-triangle texture sampling. Used to
render kept model geometry into UI pictures (icons, portraits) -- our own
renders, no original pixels involved."""
import numpy as np


def look_at(yaw, pitch):
    """Rotation matrix for a camera orbiting the origin (radians)."""
    cy, sy, cp, sp = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
    return rx @ ry


def render(tris, w, h, rot, ss=3, light=(0.4, 0.8, 0.45), fit=0.9, bg=(0, 0, 0, 0), px_per_unit=None):
    """tris: list of (p (3,3) positions, c (3,4) RGBA 0..255, lit bool).
    Returns an (h, w, 4) float32 image, supersampled ss x ss."""
    W, H = w * ss, h * ss
    img = np.zeros((H, W, 4), np.float32)
    img[...] = bg
    z = np.full((H, W), -np.inf, np.float32)
    if not tris:
        return img[::ss, ::ss]
    P = np.array([t[0] for t in tris], np.float32) @ rot.T          # (n,3,3)
    C = np.array([t[1] for t in tris], np.float32)                   # (n,3,4)
    lo, hi = P.reshape(-1, 3).min(0), P.reshape(-1, 3).max(0)
    span = max(hi[0] - lo[0], (hi[1] - lo[1]) * W / H, 1e-6)
    scale = fit * W / span
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    if px_per_unit:
        # fixed scale, feet on the bottom edge (for groups at a common size)
        scale = px_per_unit * ss
        cy = lo[1] + (H / 2) / scale
    X = (P[..., 0] - cx) * scale + W / 2
    Y = H / 2 - (P[..., 1] - cy) * scale
    Z = P[..., 2]
    L = np.asarray(light, np.float32)
    L /= np.linalg.norm(L)
    for i, t in enumerate(tris):
        e1, e2 = P[i, 1] - P[i, 0], P[i, 2] - P[i, 0]
        n = np.cross(e1, e2)
        nn = np.linalg.norm(n)
        shade = 1.0
        if nn > 0:
            shade = 0.45 + 0.55 * abs(float(n @ L) / nn)
        x, y = X[i], Y[i]
        x0, x1 = int(max(0, np.floor(x.min()))), int(min(W - 1, np.ceil(x.max())))
        y0, y1 = int(max(0, np.floor(y.min()))), int(min(H - 1, np.ceil(y.max())))
        if x0 > x1 or y0 > y1:
            continue
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1].astype(np.float32) + 0.5
        d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(d) < 1e-9:
            continue
        a = ((y[1] - y[2]) * (xx - x[2]) + (x[2] - x[1]) * (yy - y[2])) / d
        b = ((y[2] - y[0]) * (xx - x[2]) + (x[0] - x[2]) * (yy - y[2])) / d
        c = 1 - a - b
        inside = (a >= 0) & (b >= 0) & (c >= 0)
        if not inside.any():
            continue
        zz = a * Z[i, 0] + b * Z[i, 1] + c * Z[i, 2]
        zs = z[y0:y1 + 1, x0:x1 + 1]
        win = inside & (zz > zs)
        if not win.any():
            continue
        col = a[..., None] * C[i, 0] + b[..., None] * C[i, 1] + c[..., None] * C[i, 2]
        col[..., :3] *= shade
        reg = img[y0:y1 + 1, x0:x1 + 1]
        alpha = col[..., 3:4] / 255.0
        reg[win, :3] = (reg[..., :3] * (1 - alpha) + col[..., :3] * alpha)[win]
        reg[win, 3] = np.maximum(reg[..., 3], col[..., 3])[win]
        zs[win] = zz[win]
    return img.reshape(h, ss, w, ss, 4).mean((1, 3))
