"""Render SM64 level geometry (from the decomp's C source) with our generated
textures: perspective, z-buffer, perspective-correct UVs, alpha test.

Used to make the castle's level paintings: each painting becomes a picture
of its own level. Inputs are the decomp source (geometry, UVs, display
lists) and the clean tree's generated PNGs; no retail pixels.

    python -m games.sm64.level_render <clean tree> <level> <out.png> [--cam eye_x,eye_y,eye_z,at_x,at_y,at_z,fov]
"""
import glob
import math
import os
import re
import sys

import numpy as np

from cleanroom.gfx import png

VTX_RE = re.compile(r"static const Vtx (\w+)\[\] = \{(.*?)\};", re.S)
VTX_ROW = re.compile(r"\{\{\{\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\},\s*\d+,\s*\{\s*(-?\d+),\s*(-?\d+)\},\s*\{\s*(0x[0-9a-fA-F]+|\d+),\s*(0x[0-9a-fA-F]+|\d+),\s*(0x[0-9a-fA-F]+|\d+),\s*(0x[0-9a-fA-F]+|\d+)\}\}\}")
GFX_RE = re.compile(r"(?:static )?const Gfx (\w+)\[\] = \{(.*?)\};", re.S)
TEX_RE = re.compile(r"(\w+)\[\] = \{\s*#include \"([^\"]+)\.inc\.c\"")

BACKGROUNDS = {"BACKGROUND_OCEAN_SKY": "water", "BACKGROUND_SNOW_MOUNTAINS": "ccm", "BACKGROUND_UNDERWATER_CITY": "wdw",
               "BACKGROUND_BELOW_CLOUDS": "clouds", "BACKGROUND_FLAMING_SKY": "bitfs", "BACKGROUND_ABOVE_CLOUDS": "cloud_floor",
               "BACKGROUND_HAUNTED": "bbh", "BACKGROUND_GREEN_SKY": "bidw", "BACKGROUND_PURPLE_SKY": "bits",
               "BACKGROUND_DESERT": "ssl", "BACKGROUND_CUSTOM": "water"}


class Source:
    """Symbol tables over the decomp tree (textures, vertices, display lists)."""

    def __init__(self, tree):
        self.tree = tree
        self.tex, self.vtx, self.gfx = {}, {}, {}
        files = glob.glob(os.path.join(tree, "bin", "*.c")) + glob.glob(os.path.join(tree, "levels", "**", "*.c"), recursive=True)
        for f in files:
            s = open(f, encoding="latin1").read()
            for sym, path in TEX_RE.findall(s):
                self.tex[sym] = path + ".png"
            for sym, body in VTX_RE.findall(s):
                self.vtx[sym] = [tuple(int(v, 0) for v in r) for r in VTX_ROW.findall(body)]
            for sym, body in GFX_RE.findall(s):
                self.gfx[sym] = body
        self._img = {}

    def image(self, sym):
        if sym not in self._img:
            p = os.path.join(self.tree, self.tex.get(sym, ""))
            self._img[sym] = png.read(p).astype(np.float32) if sym in self.tex and os.path.exists(p) else None
        return self._img[sym]

    def triangles(self, dl, out, state=None):
        """Walk a display list; append (xyz(3,3), uv(3,2), rgba(3,4), tex sym, lit)."""
        state = state or {"tex": None, "lit": True, "vb": [None] * 64}
        body = self.gfx.get(dl)
        if body is None:
            return out
        for cmd, args in re.findall(r"(gs\w+)\((.*?)\),?\s*$", body, re.M):
            a = [x.strip() for x in args.split(",")]
            if cmd in ("gsDPSetTextureImage",):
                state["tex"] = a[3]
            elif cmd.startswith("gsDPLoadTextureBlock"):
                state["tex"] = a[0]
            elif cmd == "gsSPClearGeometryMode" and "G_LIGHTING" in args:
                state["lit"] = False
            elif cmd == "gsSPSetGeometryMode" and "G_LIGHTING" in args:
                state["lit"] = True
            elif cmd == "gsSPVertex":
                m = re.match(r"(\w+)(?:\s*\+\s*(\d+))?", a[0])
                verts = self.vtx.get(m.group(1), [])
                off = int(m.group(2) or 0)
                n, v0 = int(a[1], 0), int(a[2], 0)
                for i in range(n):
                    if off + i < len(verts):
                        state["vb"][v0 + i] = verts[off + i]
            elif cmd in ("gsSP1Triangle", "gsSP2Triangles"):
                idx = [int(x, 0) for x in a]
                tris = [idx[0:3]] + ([idx[4:7]] if cmd == "gsSP2Triangles" else [])
                for t in tris:
                    vs = [state["vb"][i] for i in t]
                    if any(v is None for v in vs):
                        continue
                    xyz = np.array([v[0:3] for v in vs], np.float32)
                    uv = np.array([v[3:5] for v in vs], np.float32) / 32.0
                    col = np.array([v[5:9] for v in vs], np.float32)
                    out.append((xyz, uv, col, state["tex"], state["lit"]))
            elif cmd == "gsSPDisplayList":
                self.triangles(a[0], out, state)
            elif cmd == "gsSPBranchList":
                self.triangles(a[0], out, state)
                break
        return out


def area_lists(tree, level, area=1):
    """Display lists drawn by an area's geo layout, with node translations
    accumulated through GEO_OPEN_NODE / GEO_CLOSE_NODE."""
    geo = open(os.path.join(tree, "levels", level, "areas", str(area), "geo.inc.c"), encoding="latin1").read()
    dls, stack, cur = [], [], np.zeros(3, np.float32)
    last = cur
    for m in re.finditer(r"(GEO_\w+)\(([^()]*(?:\([^()]*\)[^()]*)*)\)", geo):
        name, args = m.group(1), [a.strip() for a in m.group(2).split(",")]
        if name == "GEO_OPEN_NODE":
            stack.append(cur)
            cur = last
        elif name == "GEO_CLOSE_NODE":
            cur = stack.pop() if stack else np.zeros(3, np.float32)
            last = cur
        elif name == "GEO_DISPLAY_LIST":
            dls.append((args[1], cur.copy()))
            last = cur
        elif name in ("GEO_TRANSLATE_NODE_WITH_DL", "GEO_TRANSLATE_ROTATE_WITH_DL", "GEO_ANIMATED_PART", "GEO_TRANSLATE_NODE"):
            try:
                t = np.array([float(eval(a)) for a in args[1:4]], np.float32)
            except Exception:
                t = np.zeros(3, np.float32)
            last = cur + t
            if name != "GEO_TRANSLATE_NODE" and args[-1] not in ("NULL", "0"):
                dls.append((args[-1], last.copy()))
        else:
            last = cur
    bg = re.search(r"GEO_BACKGROUND\((\w+)", geo)
    return dls, (BACKGROUNDS.get(bg.group(1)) if bg else None)


def _look(eye, at):
    f = np.asarray(at, np.float32) - np.asarray(eye, np.float32)
    f /= np.linalg.norm(f)
    r = np.cross(f, [0, 1, 0]).astype(np.float32)
    r /= np.linalg.norm(r) + 1e-9
    u = np.cross(r, f)
    return np.stack([r, u, -f])        # rows: camera axes (x right, y up, z back)


def _clip_near(P, UV, C, near):
    """Clip a triangle (camera space, looking down -z) against z = -near."""
    poly = list(zip(P, UV, C))
    out = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ina, inb = a[0][2] <= -near, b[0][2] <= -near
        if ina:
            out.append(a)
        if ina != inb:
            t = (-near - a[0][2]) / (b[0][2] - a[0][2])
            out.append(tuple(x + (y - x) * t for x, y in zip(a, b)))
    return [(out[0], out[k], out[k + 1]) for k in range(1, len(out) - 1)]


def render(src, tris, eye, at, fov, w, h, bg=None, ss=3, light=(0.3, 0.9, 0.35)):
    W, H = w * ss, h * ss
    img = np.zeros((H, W, 3), np.float32)
    if bg is not None:
        img[:] = bg
    zbuf = np.full((H, W), np.inf, np.float32)
    R = _look(eye, at)
    E = np.asarray(eye, np.float32)
    f = 0.5 * H / math.tan(math.radians(fov) / 2)
    L = np.asarray(light, np.float32)
    L /= np.linalg.norm(L)
    near = 20.0
    for xyz, uv, col, tex, lit in tris:
        n = np.cross(xyz[1] - xyz[0], xyz[2] - xyz[0])
        nn = np.linalg.norm(n)
        shade = 0.5 + 0.5 * abs(float(n @ L) / nn) if nn > 0 else 1.0
        if not lit:
            shade = 1.0
        P = (xyz - E) @ R.T
        if (P[:, 2] > -near).all():
            continue
        parts = [(P, uv, col)] if (P[:, 2] <= -near).all() else \
            [tuple(np.array(x) for x in zip(*t)) for t in _clip_near(P, uv, col, near)]
        timg = src.image(tex) if tex else None
        for Pp, UVp, Cp in parts:
            iz = -1.0 / Pp[:, 2]
            x = W / 2 + Pp[:, 0] * f * iz
            y = H / 2 - Pp[:, 1] * f * iz
            x0, x1 = int(max(0, math.floor(x.min()))), int(min(W - 1, math.ceil(x.max())))
            y0, y1 = int(max(0, math.floor(y.min()))), int(min(H - 1, math.ceil(y.max())))
            if x0 > x1 or y0 > y1:
                continue
            d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
            if abs(d) < 1e-9:
                continue
            yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1].astype(np.float32) + 0.5
            b0 = ((y[1] - y[2]) * (xx - x[2]) + (x[2] - x[1]) * (yy - y[2])) / d
            b1 = ((y[2] - y[0]) * (xx - x[2]) + (x[0] - x[2]) * (yy - y[2])) / d
            b2 = 1 - b0 - b1
            inside = (b0 >= 0) & (b1 >= 0) & (b2 >= 0)
            if not inside.any():
                continue
            wz = b0 * iz[0] + b1 * iz[1] + b2 * iz[2]
            depth = 1.0 / wz
            zb = zbuf[y0:y1 + 1, x0:x1 + 1]
            m = inside & (depth < zb)
            if not m.any():
                continue
            k0, k1, k2 = b0 * iz[0] / wz, b1 * iz[1] / wz, b2 * iz[2] / wz
            vc = (k0[..., None] * Cp[0] + k1[..., None] * Cp[1] + k2[..., None] * Cp[2])
            if timg is not None:
                th, tw = timg.shape[:2]
                u = (k0 * UVp[0, 0] + k1 * UVp[1, 0] + k2 * UVp[2, 0]) % tw
                v = (k0 * UVp[0, 1] + k1 * UVp[1, 1] + k2 * UVp[2, 1]) % th
                texel = timg[v.astype(int) % th, u.astype(int) % tw]
                m &= texel[..., 3] >= 128
                rgb = texel[..., :3]
            else:
                rgb = np.full(xx.shape + (3,), 200, np.float32)
            if not lit:
                rgb = rgb * vc[..., :3] / 255.0
            rgb = rgb * shade
            reg = img[y0:y1 + 1, x0:x1 + 1]
            reg[m] = rgb[m]
            zb[m] = depth[m]
    return img.reshape(h, ss, w, ss, 3).mean((1, 3))


def sky(tree, name, w, h):
    """Background from our generated skybox texture (upper band, stretched)."""
    if not name:
        return None
    p = os.path.join(tree, "textures", "skyboxes", name + ".png")
    if not os.path.exists(p):
        return None
    s = png.read(p).astype(np.float32)[..., :3]
    band = s[: s.shape[0] // 2]
    ys = np.linspace(0, band.shape[0] - 1, h).astype(int)
    xs = np.linspace(0, band.shape[1] - 1, w).astype(int)
    return band[ys][:, xs]


def auto_cam(tris, yaw=35, pitch=28, dist=0.9, fov=50):
    pts = np.concatenate([t[0] for t in tris])
    lo, hi = np.percentile(pts, 3, 0), np.percentile(pts, 97, 0)
    c = (lo + hi) / 2
    r = np.linalg.norm(hi - lo) / 2
    yw, pt = math.radians(yaw), math.radians(pitch)
    d = np.array([math.sin(yw) * math.cos(pt), math.sin(pt), math.cos(yw) * math.cos(pt)])
    return (c + d * r * dist * 2.2).tolist(), c.tolist(), fov


def render_level(tree, level, w=64, h=64, cam=None, src=None, area=1):
    src = src or Source(tree)
    dls, bgname = area_lists(tree, level, area)
    tris = []
    for dl, off in dls:
        part = src.triangles(dl, [])
        tris += [(xyz + off, uv, col, tex, lit) for xyz, uv, col, tex, lit in part]
    if cam is None:
        eye, at, fov = auto_cam(tris)
    elif "yaw" in cam:
        eye, at, fov = auto_cam(tris, cam["yaw"], cam.get("pitch", 28), cam.get("dist", 0.9), cam.get("fov", 50))
    else:
        eye, at, fov = cam["eye"], cam["at"], cam.get("fov", 50)
    bg = sky(tree, bgname, w * 3, h * 3)
    img = render(src, tris, eye, at, fov, w, h, bg=bg)
    return img, len(tris)


def main(argv):
    tree, level, out = argv[1], argv[2], argv[3]
    cam = None
    if "--cam" in argv:
        v = [float(x) for x in argv[argv.index("--cam") + 1].split(",")]
        cam = {"eye": v[:3], "at": v[3:6], "fov": v[6] if len(v) > 6 else 50}
    img, n = render_level(tree, level, 128, 128, cam)
    rgba = np.concatenate([np.clip(img, 0, 255), np.full(img.shape[:2] + (1,), 255, np.float32)], 2)
    png.write(out, rgba.astype(np.uint8))
    print(f"{level}: {n} triangles -> {out}")


if __name__ == "__main__":
    main(sys.argv)
