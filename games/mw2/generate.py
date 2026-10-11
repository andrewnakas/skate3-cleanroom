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

Materials (default --materials pbr, the "hybrid" look): every material is
classified (games.mw2.classify, dirty side: IW4 surface type, coarse colour
facts, name keywords) to one of the CC0 sets in games/mw2/cc0_materials.toml
(ambientCG, downloaded into --cc0-cache and verified CC0 at run time). Its
albedo is the CC0 colour map graded to the retail 4x4 colour grid + mean, its
normal and ORM maps are the set's own (games.mw2.materials). Alpha-tested
materials keep the regenerated 2-bit alpha outline. Materials no set fits
(decals, signs, glass, blends) keep the regenerated texture, as does
everything with --materials regen.

Options:
  --materials pbr|regen   (default pbr)
  --pbr-size 512|1024     CC0 output texture size (default 512)
  --cc0-cache <dir>       CC0 download cache (default <spec dir>/../cc0)
  --max-texture N         cap for regenerated textures (default 512)

Output (<clean dir>): map.json, render.npz, collision.npz, textures/*.png
(textures/pbr/*: shared normal + ORM maps), CREDITS.json (CC0 sets used):
the input of the engine's tools/mesh_to_skate.py. Spec: materials-<zone>.json
(the classification decisions and the coarse facts behind them; no names).
"""
import hashlib
import json
import os
import sys
import time

import numpy as np
from PIL import Image

from games.mw2 import classify as cls_mod
from games.mw2 import materials as lib_mod
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


def option(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv):
    src, dst, spec = argv[1], argv[2], argv[3]
    cap = int(option(argv, "--max-texture", 512))
    mode = option(argv, "--materials", "pbr")
    size = int(option(argv, "--pbr-size", 512))
    assert mode in ("pbr", "regen") and size in (512, 1024), "--materials pbr|regen, --pbr-size 512|1024"
    cache = option(argv, "--cc0-cache", os.path.join(os.path.dirname(os.path.abspath(spec)), "cc0"))
    t0 = time.time()
    ex = json.load(open(os.path.join(src, "export.json")))
    zone = ex["zone"]
    surface_names = ex["surface_names"]
    render = np.load(os.path.join(src, "render.npz"))
    collision = np.load(os.path.join(src, "collision.npz"))
    os.makedirs(os.path.join(dst, "textures"), exist_ok=True)
    os.makedirs(spec, exist_ok=True)

    # Classification (dirty side: facts only, names never leave this function).
    retail = {}
    for i, m in enumerate(ex["materials"], 1):
        if m.get("image"):
            retail[i] = np.asarray(Image.open(os.path.join(src, m["image"])).convert("RGBA"))
    facts = {i: cls_mod.image_facts(a) for i, a in retail.items()}
    density = cls_mod.texel_density(render)
    inferred = {}
    if any(not m.get("surface") for m in ex["materials"]):
        inferred = cls_mod.surfaces_from_collision(render, collision, len(ex["materials"]))
    decisions = cls_mod.classify(ex["materials"], surface_names, facts, inferred, zone)
    for d in decisions:
        d["m_per_uv"] = round(density.get(d["index"], 0.0), 4)

    lib = None
    if mode == "pbr":
        usable = lib_mod.fetch(cache)
        lib = lib_mod.Library(cache, usable)
        os.makedirs(os.path.join(dst, "textures", "pbr"), exist_ok=True)

    # Textures.
    materials = []
    shared = set()
    counts = {"pbr": 0, "regen": 0}
    for (i, m), d in zip(enumerate(ex["materials"], 1), decisions):
        key = material_key(zone, m["name"])
        entry = {
            "name": f"m{i:03d}",
            "color": [1, 1, 1],
            "roughness": 0.9,
            "alpha_mode": int(m.get("alpha", 0)),
            "audio": audio_surface(d["surface"]),
        }
        if i in retail:
            rgba = retail[i]
            out = f"textures/m{i:03d}.png"
            cls = lib.resolve(d["class"]) if lib else None
            if cls:
                f = facts[i]
                reps = lib_mod.reps_for(d["m_per_uv"], lib.size_m(cls), size)
                alpha = None
                if entry["alpha_mode"] == 1 and f["alpha_coverage"] > 0:
                    outline = regen(key, shrink(rgba, cap))[..., 3]
                    alpha = np.asarray(Image.fromarray(outline, "L").resize((size, size), Image.NEAREST))
                clean = lib.albedo(cls, size, reps, f["grid4"], f["mean"], f["contrast"], alpha)
                tag = f"textures/pbr/{cls}-{size}-r{reps}"
                if tag not in shared:
                    Image.fromarray(lib.normal_rgba(cls, size, reps), "RGBA").save(os.path.join(dst, tag + "-n.png"), optimize=True)
                    Image.fromarray(lib.orm_rgba(cls, size, reps), "RGBA").save(os.path.join(dst, tag + "-orm.png"), optimize=True)
                    shared.add(tag)
                # ORM green is the roughness; the scalar multiplies it, so 1.
                entry.update(normal=tag + "-n.png", orm=tag + "-orm.png", roughness=1.0)
                d.update(used=cls, reps=reps)
                counts["pbr"] += 1
            else:
                clean = regen(key, shrink(rgba, cap))
                d["used"] = "regen"
                counts["regen"] += 1
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
    json.dump(decisions, open(os.path.join(spec, f"materials-{zone}.json"), "w"), indent=1)
    if lib:
        json.dump({"note": "Textures of this map use these CC0 1.0 sets from ambientCG (no attribution required).",
                   "sets": [c for c in lib_mod.credits(cache) if any(d.get("used") == c["class"] for d in decisions)]},
                  open(os.path.join(dst, "CREDITS.json"), "w"), indent=1)
    json.dump({k: v for k, v in stats.items() if not isinstance(v, np.ndarray)},
              open(os.path.join(spec, f"geometry-{zone}.json"), "w"), indent=1, default=float)
    by_class = {}
    for d in decisions:
        by_class[d.get("used", d["class"])] = by_class.get(d.get("used", d["class"]), 0) + 1
    print(f"mw2 materials {zone} ({mode}, {size}px): {counts['pbr']} CC0 PBR, {counts['regen']} regenerated, "
          f"{len(shared)} shared normal/ORM pairs; {dict(sorted(by_class.items()))}")
    print(f"mw2 generate {zone}: {len(ex['materials'])} materials, {len(FACTS)} textures regenerated, "
          f"{stats.get('tris', 0)} -> {len(new_idx)} triangles ({stats.get('tris_retessellated', 0)} re-cut), "
          f"{len(surf)} collision kept, {len(spawns)} spawns, {time.time() - t0:.0f}s -> {dst}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
