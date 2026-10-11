"""MW2 map, private export -> clean input for the engine's mesh writer (+ spec).

    python -m games.mw2.generate <private export dir> <clean dir> <spec dir> [--max-texture 512]

Input: what the IW4L exporter writes (dirty side, D: only, never committed):
  export.json    zone, surface_names, spawns [[x, y, z, heading], ...],
                 materials [{name, image | null, alpha (0 opaque, 1 mask, 2 blend), surface}]
  render.npz     positions normals uv (Y-up metres), material (1-based), indices
  collision.npz  triangles (K,3,3) Y-up metres, surface (K,) IW4 surface type index
  images/*.png   decoded colour maps (retail pixels)

Kept as facts (as for the Skate 3 parks): collision triangles exactly, spawn
points, which material covers each surface, the surface layout to 0.37 mm,
where the texture lands to 1/3000 of a tile, each surface's type.
Regenerated: every texture (the Skate 3 rule: size + 4x4 / 16x16 colour grid
+ 2-bit alpha outline, our own noise and dither) and the visual mesh
(games.skate3.geom.regen_mesh: own lattice, re-cut quads, recomputed normals,
renumbered vertices). Dropped: everything else in the zone (techsets,
shaders, scripts, sounds, model and material names beyond a hash).

Output (<clean dir>): map.json, render.npz, collision.npz, textures/*.png:
the input of the engine's tools/mesh_to_skate.py.
"""
import hashlib
import json
import os
import sys
import time

import numpy as np
from PIL import Image

from games.skate3 import geom
from games.skate3.generate import FACTS, regen

# IW4 surface types (movement_iw4 SURFACE_TYPE_NAMES order) -> skate audio
# surface: 1 rough, 3 smooth, 5 wood, 9 metal (the web player's roll beds).
ROUGH = {"dirt", "gravel", "sand", "grass", "mud", "snow", "slush", "foliage", "bark", "rock"}
WOOD = {"wood"}
METAL = {"metal", "paintedmetal", "riotshield"}


def audio_surface(name):
    if name in METAL:
        return 9
    if name in WOOD:
        return 5
    if name in ROUGH:
        return 1
    return 3


def material_key(zone, name):
    # Names are not shipped; the key only seeds the generator.
    return f"mw2/{zone}/" + hashlib.sha1(name.encode()).hexdigest()[:16]


def shrink(rgba, cap):
    h, w = rgba.shape[:2]
    scale = min(1.0, cap / max(w, h))
    if scale >= 1.0:
        return rgba
    size = (max(4, int(w * scale)), max(4, int(h * scale)))
    return np.asarray(Image.fromarray(rgba, "RGBA").resize(size, Image.LANCZOS))


def main(argv):
    src, dst, spec = argv[1], argv[2], argv[3]
    cap = int(argv[argv.index("--max-texture") + 1]) if "--max-texture" in argv else 512
    t0 = time.time()
    ex = json.load(open(os.path.join(src, "export.json")))
    zone = ex["zone"]
    surface_names = ex["surface_names"]
    render = np.load(os.path.join(src, "render.npz"))
    collision = np.load(os.path.join(src, "collision.npz"))
    os.makedirs(os.path.join(dst, "textures"), exist_ok=True)
    os.makedirs(spec, exist_ok=True)

    # Textures.
    materials = []
    for i, m in enumerate(ex["materials"], 1):
        key = material_key(zone, m["name"])
        entry = {
            "name": f"m{i:03d}",
            "color": [1, 1, 1],
            "roughness": 0.9,
            "alpha_mode": int(m.get("alpha", 0)),
            "audio": audio_surface(surface_names[m.get("surface", 0)] if m.get("surface", 0) < len(surface_names) else ""),
        }
        if m.get("image"):
            rgba = np.asarray(Image.open(os.path.join(src, m["image"])).convert("RGBA"))
            clean = regen(key, shrink(rgba, cap))
            out = f"textures/m{i:03d}.png"
            Image.fromarray(clean, "RGBA").save(os.path.join(dst, out), optimize=True)
            entry["texture"] = out
        materials.append(entry)

    # Collision-only materials, one per surface type that collision uses.
    surf = np.asarray(collision["surface"], np.uint32)
    used = sorted(set(surf.tolist()))
    coll_mat = {}
    for s in used:
        name = surface_names[s] if s < len(surface_names) else "default"
        materials.append({"name": f"surface-{name}", "color": [1, 1, 1], "audio": audio_surface(name)})
        coll_mat[s] = len(materials)

    # Visual mesh through the Skate 3 geometry regenerator.
    n = len(render["positions"])
    v = np.zeros(n, geom.VERT)
    v["p"] = render["positions"]
    v["n"] = render["normals"]
    v["uv"] = render["uv"]
    v["lm"] = render["uv"]
    v["decal"] = render["uv"]
    v["mat"] = render["material"]
    idx = np.asarray(render["indices"], np.uint32).reshape(-1, 3)
    new_v, new_idx, stats = geom.regen_mesh(v, idx, f"mw2/{zone}/world")
    stats.pop("source", None)
    np.savez_compressed(
        os.path.join(dst, "render.npz"),
        positions=new_v["p"], normals=new_v["n"], uv=new_v["uv"],
        material=new_v["mat"], indices=new_idx.reshape(-1),
    )
    # Collision is a kept fact: the same triangles, our own container.
    np.savez_compressed(
        os.path.join(dst, "collision.npz"),
        triangles=np.asarray(collision["triangles"], np.float32),
        material=np.array([coll_mat[s] for s in surf.tolist()], np.uint32),
        surface=surf,
    )

    spawns = ex.get("spawns") or [[0, 0, 0, 0]]
    sx, sy, sz, heading = spawns[0]
    json.dump({
        "name": f"{ex.get('title', zone)} (clean room)",
        "spawn": [sx, sy, sz],
        "heading": heading,
        "spawns": spawns,
        "materials": materials,
    }, open(os.path.join(dst, "map.json"), "w"), indent=1)
    json.dump(FACTS, open(os.path.join(spec, f"textures-{zone}.json"), "w"))
    json.dump({k: v for k, v in stats.items() if not isinstance(v, np.ndarray)},
              open(os.path.join(spec, f"geometry-{zone}.json"), "w"), indent=1, default=float)
    print(f"mw2 generate {zone}: {len(ex['materials'])} materials, {len(FACTS)} textures regenerated, "
          f"{stats.get('tris', 0)} -> {len(new_idx)} triangles ({stats.get('tris_retessellated', 0)} re-cut), "
          f"{len(surf)} collision kept, {len(spawns)} spawns, {time.time() - t0:.0f}s -> {dst}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
