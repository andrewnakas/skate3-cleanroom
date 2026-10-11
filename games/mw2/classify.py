"""Pick a CC0 material class for every exported MW2 material (dirty side, facts only).

Inputs per material, all read from the private export:
  - the IW4 surface type: export.json materials[].surface when the exporter
    sets it (index into surface_names), else inferred from the collision
    triangles the material's render triangles lie on (majority vote of the
    nearest collision faces with a matching normal);
  - coarse facts of its retail colour map: mean colour, 4x4 colour grid,
    luma contrast (std / mean), saturation of the 4x4 cells, alpha
    coverage, size;
  - keywords in its material name (classification input only: names are
    never shipped and never written to the spec);
  - texel density (metres per UV unit) from the render mesh, which sets how
    many times the CC0 tile repeats across one texture.
Output: one decision per material {index, class, reason, surface, facts}, written
to <spec>/materials-<zone>.json. Class "regen" means "no CC0 set fits": the
material keeps the regenerated texture (decals, signs, glass, blends).
"""
import re

import numpy as np

from games.mw2.materials import lin_to_srgb, srgb_to_lin

# name token -> class. First token hit (in this order of priority) wins.
KEYWORDS = [
    (("decal", "sign", "signs", "poster", "posters", "graffiti", "glass", "window", "windows", "sky", "water",
      "logo", "text", "letters", "numbers", "screen", "monitor", "tv", "label", "flag", "blood", "paper",
      "newspaper", "portrait", "billboard", "advert", "glow", "fx", "shadow", "caulk", "mirror"), "regen"),
    (("foliage", "leaf", "leaves", "bush", "bushes", "shrub", "ivy", "vine", "vines", "fern", "plant",
      "plants", "palm", "pine", "branch", "branches", "hedge", "tree_branch"), "foliage"),
    (("rust", "rusty", "rusted"), "rusted_metal"),
    (("corrugated", "corrugate", "siding", "tin"), "corrugated_metal"),
    (("diamond", "diamondplate", "tread", "grate", "grating"), "metal_plate"),
    (("plywood", "chipboard", "osb", "particleboard"), "plywood"),
    (("bark", "trunk"), "bark"),
    (("brick", "bricks", "cinderblock", "cinder", "cmu"), "brick"),
    (("tile", "tiles", "tiled", "ceramic"), "tiles"),
    (("carpet", "rug"), "carpet"),
    (("cloth", "fabric", "tarp", "canvas", "sandbag", "sandbags", "tent", "curtain", "banner", "net", "camo"), "fabric"),
    (("cobble", "cobblestone", "paving", "pavers", "pavement", "sidewalk", "curb", "flagstone"), "paving"),
    (("asphalt", "road", "tarmac", "street", "runway"), "asphalt"),
    (("gravel", "pebble", "pebbles"), "gravel"),
    (("rubble", "debris", "trash", "junk", "garbage"), "rubble"),
    (("sand", "beach", "desert", "dune"), "sand"),
    (("grass", "lawn", "weeds", "weed"), "grass"),
    (("dirt", "mud", "soil", "ground", "earth", "terrain"), "dirt"),
    (("rock", "rocks", "stone", "stones", "cliff", "boulder", "mountain"), "rock"),
    (("plaster", "stucco", "drywall", "painted_wall"), "plaster"),
    (("concrete", "cement", "conc"), "concrete"),
    (("floor", "floorboard", "floorboards", "parquet"), "floor"),
    (("wood", "wooden", "plank", "planks", "board", "boards", "crate", "crates", "pallet", "beam", "beams",
      "timber", "log", "logs"), "wood_planks"),
    (("metal", "steel", "iron", "pipe", "pipes", "dumpster", "container", "tank", "vent", "door", "railing",
      "rail", "ladder", "panel", "sheet", "girder", "fence", "chainlink", "barrel", "car", "truck", "van"), "metal"),
    (("wall", "walls", "building", "house", "ceiling"), "plaster"),
]

# IW4 surface type -> class (or a family resolved from the colour facts).
SURFACE = {
    "bark": "bark", "brick": "brick", "carpet": "carpet", "cloth": "fabric", "concrete": "concrete",
    "dirt": "dirt", "foliage": "foliage", "glass": "regen", "grass": "grass", "gravel": "gravel",
    "ice": "regen", "metal": "metal", "mud": "dirt", "paper": "regen", "plaster": "plaster", "rock": "rock",
    "sand": "sand", "snow": "regen", "water": "regen", "wood": "wood_planks", "asphalt": "asphalt",
    "ceramic": "tiles", "plastic": "painted_metal", "rubber": "asphalt", "cushion": "fabric",
    "fruit": "regen", "paintedmetal": "painted_metal", "riotshield": "regen", "slush": "regen",
    "flesh": "regen",
}


def tokens(name):
    return [t for t in re.split(r"[^a-z0-9]+", name.lower().replace("~", "_")) if t]


def image_facts(rgba):
    """Coarse facts of a retail colour map (HxWx4 uint8)."""
    rgb = rgba[..., :3].astype(np.float64) / 255.0
    lin = srgb_to_lin(rgb)
    h, w = rgba.shape[:2]
    gh, gw = max(1, h // 4), max(1, w // 4)
    cells = lin[: gh * 4, : gw * 4].reshape(4, gh, 4, gw, 3).mean(axis=(1, 3))
    mean = lin.reshape(-1, 3).mean(0)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722])
    # Saturation of the coarse colour (4x4 cells), not per pixel: texel noise is not hue.
    g = lin_to_srgb(cells)
    mx, mn = g.max(-1), g.min(-1)
    sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0.0)
    a = rgba[..., 3]
    return {
        "w": int(w), "h": int(h),
        "mean": [int(round(v)) for v in (lin_to_srgb(mean) * 255)],
        "grid4": [[[int(round(v)) for v in c] for c in row] for row in (lin_to_srgb(cells) * 255)],
        "contrast": round(float(lum.std() / (lum.mean() + 1e-6)), 4),
        "saturation": round(float(sat.mean()), 4),
        "alpha_coverage": round(float((a < 128).mean()), 4),
    }


def texel_density(render):
    """{material id: median metres per UV unit} from the (dirty) render mesh."""
    p = np.asarray(render["positions"], np.float64)
    uv = np.asarray(render["uv"], np.float64)
    mat = np.asarray(render["material"], np.int64)
    idx = np.asarray(render["indices"], np.int64).reshape(-1, 3)
    a, b, c = p[idx[:, 0]], p[idx[:, 1]], p[idx[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    ua, ub, uc = uv[idx[:, 0]], uv[idx[:, 1]], uv[idx[:, 2]]
    uarea = 0.5 * np.abs((ub[:, 0] - ua[:, 0]) * (uc[:, 1] - ua[:, 1]) - (ub[:, 1] - ua[:, 1]) * (uc[:, 0] - ua[:, 0]))
    ok = (uarea > 1e-9) & (area > 1e-6)
    ratio = np.sqrt(area[ok] / uarea[ok])
    tm = mat[idx[ok, 0]]
    out = {}
    for m in np.unique(tm):
        out[int(m)] = float(np.median(ratio[tm == m]))
    return out


def surfaces_from_collision(render, collision, n_materials, samples=400, max_dist=4.0, plane_tol=0.08):
    """{material id: surface index} by where its render triangles sit on collision."""
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        return {}
    tris = np.asarray(collision["triangles"], np.float64).reshape(-1, 3, 3)
    surf = np.asarray(collision["surface"], np.int64).reshape(-1)
    if not len(tris):
        return {}
    cn = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    cn /= np.linalg.norm(cn, axis=1, keepdims=True) + 1e-12
    # Sample points on every collision face (corners pulled in + centroid) so big faces are found.
    w = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1], [4, 1, 1], [1, 4, 1], [1, 1, 4]], np.float64)
    w /= w.sum(1, keepdims=True)
    pts = np.einsum("kj,tjc->tkc", w, tris).reshape(-1, 3)
    owner = np.repeat(np.arange(len(tris)), len(w))
    tree = cKDTree(pts)

    p = np.asarray(render["positions"], np.float64)
    mat = np.asarray(render["material"], np.int64)
    idx = np.asarray(render["indices"], np.int64).reshape(-1, 3)
    tri_mat = mat[idx[:, 0]]
    rng = np.random.default_rng(0)
    out = {}
    for m in range(1, n_materials + 1):
        sel = np.nonzero(tri_mat == m)[0]
        if not len(sel):
            continue
        if len(sel) > samples:
            sel = np.sort(rng.choice(sel, samples, replace=False))
        a, b, c = p[idx[sel, 0]], p[idx[sel, 1]], p[idx[sel, 2]]
        cen = (a + b + c) / 3
        rn = np.cross(b - a, c - a)
        rn /= np.linalg.norm(rn, axis=1, keepdims=True) + 1e-12
        dist, near = tree.query(cen, k=12, distance_upper_bound=max_dist)
        votes = {}
        for i in range(len(sel)):
            for d, j in zip(dist[i], near[i]):
                if not np.isfinite(d):
                    continue
                t = owner[j]
                # Same plane (within plane_tol metres) and facing the same way.
                if abs(float(cn[t] @ rn[i])) > 0.7 and abs(float(cn[t] @ (cen[i] - tris[t, 0]))) < plane_tol:
                    votes[int(surf[t])] = votes.get(int(surf[t]), 0) + 1
                    break
        if votes:
            out[m] = max(sorted(votes), key=votes.get)
    return out


def resolve_family(cls, f, alpha_mode):
    """Turn a family (concrete, metal, floor) into a set class from the colour facts."""
    mean = np.asarray(f["mean"], np.float64) / 255.0 if f else np.array([0.5, 0.5, 0.5])
    lum = float(srgb_to_lin(mean) @ np.array([0.2126, 0.7152, 0.0722]))
    sat = f["saturation"] if f else 0.0
    con = f["contrast"] if f else 0.2
    r, g, b = mean
    if cls == "concrete":
        if lum < 0.08 or (sat > 0.18 and r > b):
            return "concrete_dirty"
        return "concrete_rough" if con > 0.25 else "concrete_smooth"
    if cls == "metal":
        if r > g > b and sat > 0.3 and lum < 0.35:
            return "rusted_metal"
        return "painted_metal"
    if cls == "floor":
        return "wood_floor" if (r > g > b and sat > 0.2) else "tiles"
    if cls == "asphalt" and con > 0.35:
        return "asphalt_cracked"
    if cls == "plaster" and sat > 0.2:
        return "painted_plaster"
    return cls


def colour_guess(f, alpha_mode):
    """No keyword, no surface: a guess from the colour facts alone."""
    if not f:
        return "concrete_smooth", "colour:none"
    r, g, b = np.asarray(f["mean"], np.float64) / 255.0
    sat = f["saturation"]
    lum = float(srgb_to_lin(np.array([r, g, b])) @ np.array([0.2126, 0.7152, 0.0722]))
    if g > r * 1.08 and g > b * 1.08 and sat > 0.2:
        return ("foliage" if alpha_mode == 1 else "grass"), "colour:green"
    if sat > 0.45:
        return "regen", "colour:saturated"
    if r > g > b and 0.18 < sat <= 0.45:
        return ("dirt" if lum < 0.25 else "sand"), "colour:brown"
    if lum < 0.05:
        return "asphalt", "colour:dark"
    return resolve_family("concrete", f, alpha_mode), "colour:grey"


def classify(materials, surface_names, facts, inferred_surface, zone=""):
    """materials: export.json materials; facts: {i: image facts}; returns decisions.
    Tokens of the zone name are ignored (mp_rust's materials say "rust" everywhere)."""
    ignore = set(tokens(zone))
    out = []
    for i, m in enumerate(materials, 1):
        f = facts.get(i)
        alpha_mode = int(m.get("alpha", 0))
        s_idx = int(m.get("surface", 0) or 0)
        s_src = "export"
        if s_idx == 0 and i in inferred_surface:
            s_idx, s_src = inferred_surface[i], "collision"
        s_name = surface_names[s_idx] if 0 <= s_idx < len(surface_names) else "default"
        toks = set(tokens(m.get("name", ""))) - ignore
        cls, reason = None, None
        if not m.get("image"):
            cls, reason = "none", "no colour map"
        elif alpha_mode == 2:
            cls, reason = "regen", "alpha blend (decal / glass)"
        if cls is None:
            for words, c in KEYWORDS:
                hit = next((w for w in words if w in toks), None)
                if hit:
                    cls, reason = c, f"keyword:{hit}"
                    break
        if cls is None and s_name in SURFACE:
            cls, reason = SURFACE[s_name], f"surface:{s_name}({s_src})"
        if cls is None:
            cls, reason = colour_guess(f, alpha_mode)
        cls = resolve_family(cls, f, alpha_mode)
        out.append({"index": i, "class": cls, "reason": reason, "surface": s_name, "surface_from": s_src,
                    "alpha_mode": alpha_mode, "facts": f})
    return out
