"""Dirty installed pack -> clean pack (+ spec of coarse facts).

    python -m games.skate3.generate <dirty install dir> <clean dir> <spec dir> [--only substr]

Kept verbatim (user-approved facts): gameplay data (animation banks, state
graphs, VLT json, input/joystick/camera configs), map geometry/collision/rails
(everything in a .skate except texture payloads), sky/HUD layout json,
teleports, lighting parameters, irradiance probes.
Regenerated: every texture (.skate payloads, .rgba, .png, PNGs inside .glb)
from its spec fact: size + 4x4 / 16x16 colour grid + 2-bit alpha outline.
Dropped: everything else (raw retail containers, xml, logs).
"""
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import time

import numpy as np
from PIL import Image

from cleanroom.decomp.spec import texture_fact
from cleanroom.decomp.gen import from_digest
from games.skate3 import skate14

KEEP_EXT = {".abin", ".stategraph", ".cfg", ".pat", ".shk", ".irradiance"}
KEEP_JSON_DIRS = ("assets/private/stock/", "assets/private/native-skies/", "assets/private/native-props/",
                  "assets/private/hud/runtime/", "settings/")
KEEP_FILES = {"assets/private/game.json", "assets/private/teleports.json", "assets/private/render-parameters.json",
              "assets/private/exposure.json", "assets/private/exposure-profiles.json",
              "assets/private/character-lighting.json", "maps.json"}
FACTS = {}


def fact(key, rgba):
    d = texture_fact(key, rgba)
    FACTS[key] = d
    return d


def regen(key, rgba):
    """rgba HxWx4 (cube maps: (6H)xWx4) -> regenerated, same shape.
    A +-2 LSB per-pixel dither on RGB keeps near-flat textures (normal maps,
    plain colours) from reproducing retail byte runs by coincidence."""
    out = from_digest(key, fact(key, np.asarray(rgba))).astype(np.int16)
    rng = np.random.default_rng(int.from_bytes(hashlib.sha1(("dither/" + key).encode()).digest()[:8], "little"))
    out[..., :3] += rng.integers(-2, 3, out[..., :3].shape, dtype=np.int16)
    return np.clip(out, 0, 255).astype(np.uint8)


def classify(rel):
    ext = os.path.splitext(rel)[1].lower()
    if ext in (".skate",):
        return "skate"
    if ext in (".rgba",):
        return "rgba"
    if ext == ".png":
        return "png"
    if ext == ".glb":
        return "glb"
    if ext in KEEP_EXT or rel in KEEP_FILES:
        return "keep"
    if ext == ".json" and rel.startswith(KEEP_JSON_DIRS):
        return "keep"
    if rel == "assets/private/session-marker/hud.json":
        return "keep"
    return "drop"


def rgba_dims(root):
    """Map rgba relpath -> (w, h) from any json in the pack that describes it."""
    dims = {}

    def walk(o, base):
        if isinstance(o, dict):
            w, h = o.get("width"), o.get("height")
            for k, v in o.items():
                if isinstance(v, str) and v.endswith(".rgba") and isinstance(w, int):
                    dims[os.path.normpath(os.path.join(base, v)).replace("\\", "/")] = (w, h)
                    dims[os.path.basename(v)] = (w, h)
            for v in o.values():
                walk(v, base)
        elif isinstance(o, list):
            for v in o:
                walk(v, base)

    for dp, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith(".json"):
                continue
            p = os.path.join(dp, f)
            try:
                j = json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
            rel_dir = os.path.relpath(dp, root).replace("\\", "/")
            if "native-skies" in rel_dir and isinstance(j, dict) and "width" in j:
                stem = f[:-5]
                dims[f"{rel_dir}/{stem}.rgba"] = (j["width"], j["height"])
                if "sun_width" in j:
                    dims[f"{rel_dir}/{stem}.sun.rgba"] = (j["sun_width"], j["sun_height"])
            walk(j, rel_dir)
            walk(j, os.path.join(rel_dir, "..").replace("\\", "/"))
            if "hud" in rel_dir:
                walk(j, "assets/private/hud")
    return dims


def guess_dims(n):
    px = n // 4
    best = None
    for w in (1 << k for k in range(0, 14)):
        if px % w == 0:
            h = px // w
            r = max(w, h) / min(w, h)
            if best is None or r < best[0]:
                best = (r, w, h)
    return best[1], best[2]


def do_glb(src, dst, key):
    b = open(src, "rb").read()
    magic, ver, total = struct.unpack("<4sII", b[:12])
    jl, jt = struct.unpack("<I4s", b[12:20])
    j = json.loads(b[20:20 + jl])
    off = 20 + jl
    bl, bt = struct.unpack("<I4s", b[off:off + 8])
    binc = b[off + 8:off + 8 + bl]
    views = j["bufferViews"]
    img_views = {}
    for i, im in enumerate(j.get("images", [])):
        if "bufferView" in im:
            v = views[im["bufferView"]]
            data = binc[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]]
            rgba = np.array(Image.open(io.BytesIO(data)).convert("RGBA"))
            new = regen(f"{key}#image{i}:{im.get('name', '')}", rgba)
            out = io.BytesIO()
            Image.fromarray(new, "RGBA").save(out, "PNG", optimize=True)
            img_views[im["bufferView"]] = out.getvalue()
            im["mimeType"] = "image/png"
    # rebuild BIN with replaced views, 4-byte aligned, original order
    order = sorted(range(len(views)), key=lambda k: views[k].get("byteOffset", 0))
    nb = bytearray()
    for k in order:
        v = views[k]
        data = img_views.get(k)
        if data is None:
            data = binc[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]]
        while len(nb) % 4:
            nb.append(0)
        v["byteOffset"] = len(nb)
        v["byteLength"] = len(data)
        nb += data
    while len(nb) % 4:
        nb.append(0)
    j["buffers"][0]["byteLength"] = len(nb)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    out = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(nb))
    out += struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(nb), b"BIN\0") + bytes(nb)
    open(dst, "wb").write(out)
    return len(img_views)


def main(argv):
    src, dst, spec = argv[1], argv[2], argv[3]
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    t0 = time.time()
    dims = rgba_dims(src)
    counts = {}
    for dp, _, fs in os.walk(src):
        for f in fs:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, src).replace("\\", "/")
            kind = classify(rel)
            if only and only not in rel:
                continue
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "drop":
                continue
            out = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if kind == "keep":
                shutil.copyfile(p, out)
            elif kind == "skate":
                n = skate14.rewrite(p, out, lambda name, w, h, a, cube, rel=rel: regen(f"{rel}#{name}", a))
                counts["skate_textures"] = counts.get("skate_textures", 0) + n
            elif kind == "rgba":
                raw = open(p, "rb").read()
                w, h = dims.get(rel) or dims.get(f) or guess_dims(len(raw))
                if w * h * 4 != len(raw):
                    w, h = guess_dims(len(raw))
                a = np.frombuffer(raw, np.uint8).reshape(h, w, 4)
                open(out, "wb").write(regen(rel, a).tobytes())
            elif kind == "png":
                a = np.array(Image.open(p).convert("RGBA"))
                Image.fromarray(regen(rel, a), "RGBA").save(out, "PNG")
            elif kind == "glb":
                counts["glb_images"] = counts.get("glb_images", 0) + do_glb(p, out, rel)
    # session-marker hud.json: refresh output hashes of regenerated textures
    hj = os.path.join(dst, "assets/private/session-marker/hud.json")
    if os.path.exists(hj):
        j = json.load(open(hj))
        for t in j.get("textures", []):
            fp = os.path.join(os.path.dirname(hj), t["file"])
            if os.path.exists(fp):
                t["output_sha256"] = hashlib.sha256(open(fp, "rb").read()).hexdigest()
        json.dump(j, open(hj, "w"), indent=2)
    os.makedirs(spec, exist_ok=True)
    json.dump(FACTS, open(os.path.join(spec, "textures.json" if not only else f"textures-{only.replace('/', '_')}.json"), "w"))
    print(f"generate: {counts} textures regenerated={len(FACTS)} in {time.time() - t0:.0f}s -> {dst}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
