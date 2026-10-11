"""CC0 PBR material library and synthesis for the clean MW2 maps (clean side).

    python -m games.mw2.materials fetch <cache dir>        # download + verify all sets
    python -m games.mw2.materials sheet <cache dir> <out.png>   # contact sheet of the library

The library is games/mw2/cc0_materials.toml: ambientCG sets (CC0 1.0), one per
material class. `fetch` downloads each set's 1K-JPG zip into a cache dir
(never committed), keeps only the maps we use, and verifies the asset
against the ambientCG API (asset id, data type Material, the manifest's
download URL) and the site's licence page (CC0 1.0 Universal). A set whose
check fails is not used. With no network, a cache verified earlier is used.

Synthesis (no retail pixels are read here; the inputs are coarse facts):
  albedo = the CC0 colour map tiled `reps` times across the texture, graded in
           linear light so its low-frequency colour is the retail texture's
           4x4 colour grid (upsampled with wrap, pulled toward the mean); the
           CC0 detail is kept, its contrast scaled toward the retail contrast.
  normal = the CC0 NormalGL map tiled the same way (OpenGL / +Y convention,
           what Bevy's StandardMaterial expects with flip_normal_map_y off).
  orm    = R ambient occlusion (CC0 AO map, else a cavity term from the CC0
           displacement), G roughness, B metalness (CC0 map scaled by the
           manifest's metal, else that constant), the glTF layout Bevy samples.
  alpha  = for alpha-tested materials only: the regenerated 2-bit outline
           (games.skate3.generate.regen) resized to the output.
Everything is deterministic for a given cache and Pillow version.
"""
import hashlib
import io
import json
import os
import sys
import tomllib
import urllib.request
import zipfile

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

MANIFEST = os.path.join(os.path.dirname(__file__), "cc0_materials.toml")
API = "https://ambientcg.com/api/v2/full_json?id={id}&include=downloadData,dimensionsData"
LICENCE_PAGE = "https://docs.ambientcg.com/license/"
LICENCE_PHRASE = "CC0 1.0 Universal"
MAPS = {
    "color": "_Color.jpg",
    "normal": "_NormalGL.jpg",
    "rough": "_Roughness.jpg",
    "ao": "_AmbientOcclusion.jpg",
    "metal": "_Metalness.jpg",
    "disp": "_Displacement.jpg",
}
# Classes with no set of their own borrow one.
ALIASES = {"foliage": "grass"}
UA = {"User-Agent": "skate3-cleanroom mw2 materials (CC0 fetch)"}


def load_manifest(path=MANIFEST):
    with open(path, "rb") as f:
        entries = tomllib.load(f)["material"]
    for e in entries:
        assert e["license"] == "CC0-1.0", f"{e['id']}: manifest licence must be CC0-1.0"
    return entries


def _get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def verify_licence(cache):
    """The site-wide licence page must still say CC0 1.0 Universal."""
    path = os.path.join(cache, "licence.json")
    try:
        text = _get(LICENCE_PAGE).decode("utf-8", "replace")
        ok = LICENCE_PHRASE in text
        rec = {"url": LICENCE_PAGE, "phrase": LICENCE_PHRASE, "found": ok}
        json.dump(rec, open(path, "w"), indent=1)
        return ok
    except OSError:
        return os.path.exists(path) and json.load(open(path)).get("found", False)


def verify_asset(e):
    """API record: same id, a Material, and the manifest URL is its 1K-JPG download."""
    d = json.loads(_get(API.format(id=e["id"])))
    found = [a for a in d.get("foundAssets", []) if a.get("assetId") == e["id"]]
    if not found or found[0].get("dataType") != "Material":
        return False, "not found as a Material"
    urls = []
    for folder in found[0].get("downloadFolders", {}).values():
        for cat in folder.get("downloadFiletypeCategories", {}).values():
            urls += [x.get("downloadLink") for x in cat.get("downloads", [])]
    if e["url"] not in urls:
        return False, "manifest url not offered by the API"
    return True, {"dimensionX_cm": found[0].get("dimensionX"), "shortLink": found[0].get("shortLink")}


def fetch(cache, entries=None, log=print):
    """Download + verify every set. Returns {class: set dir} of usable sets."""
    entries = entries or load_manifest()
    os.makedirs(cache, exist_ok=True)
    licence_ok = verify_licence(cache)
    usable = {}
    for e in entries:
        d = os.path.join(cache, e["id"])
        rec_path = os.path.join(d, "source.json")
        rec = json.load(open(rec_path)) if os.path.exists(rec_path) else None
        if rec and rec.get("verified") and rec.get("url") == e["url"] and licence_ok:
            usable[e["class"]] = d
            continue
        try:
            ok, info = verify_asset(e)
            if not ok:
                log(f"  cc0 {e['id']}: rejected ({info})")
                continue
            blob = _get(e["url"], timeout=180)
            os.makedirs(d, exist_ok=True)
            kept = []
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for name in z.namelist():
                    for key, suffix in MAPS.items():
                        if name.endswith(suffix) and "/" not in name:
                            open(os.path.join(d, key + ".jpg"), "wb").write(z.read(name))
                            kept.append(key)
            if "color" not in kept or "normal" not in kept or "rough" not in kept:
                log(f"  cc0 {e['id']}: zip lacks Color/NormalGL/Roughness")
                continue
            rec = {"id": e["id"], "url": e["url"], "source": e["source"], "author": e["author"],
                   "license": e["license"], "licence_page": LICENCE_PAGE, "api": info,
                   "zip_sha256": hashlib.sha256(blob).hexdigest(), "maps": sorted(kept),
                   "verified": bool(licence_ok)}
            json.dump(rec, open(rec_path, "w"), indent=1)
            if licence_ok:
                usable[e["class"]] = d
        except OSError as err:
            log(f"  cc0 {e['id']}: download failed ({err})")
    log(f"cc0 library: {len(usable)} of {len(entries)} sets verified CC0 in {cache}"
        + ("" if licence_ok else " (licence page check FAILED: no set used)"))
    return usable


def credits(cache, entries=None):
    out = []
    for e in entries or load_manifest():
        p = os.path.join(cache, e["id"], "source.json")
        if os.path.exists(p):
            r = json.load(open(p))
            out.append({k: r[k] for k in ("id", "url", "source", "author", "license", "zip_sha256")}
                       | {"what": e["what"], "class": e["class"]})
    return out


# ---------------------------------------------------------------- synthesis

def srgb_to_lin(x):
    x = np.asarray(x, np.float64)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def to_u8(x):
    return np.clip(np.rint(x * 255.0), 0, 255).astype(np.uint8)


def upsample_wrap(grid, size):
    """(n, n, c) cell means -> (size, size, c), bilinear with wrap so it tiles."""
    n = grid.shape[0]
    t = (np.arange(size) + 0.5) / size * n - 0.5
    i0 = np.floor(t).astype(int)
    f = t - i0
    f = f * f * (3 - 2 * f)
    i0 %= n
    i1 = (i0 + 1) % n
    rows = grid[i0] * (1 - f)[:, None, None] + grid[i1] * f[:, None, None]
    return rows[:, i0] * (1 - f)[None, :, None] + rows[:, i1] * f[None, :, None]


class Library:
    """Loaded CC0 sets, tiled per (class, size, reps) on demand."""

    def __init__(self, cache, usable, entries=None):
        self.cache = cache
        self.entries = {e["class"]: e for e in (entries or load_manifest())}
        self.usable = usable
        self._tiles = {}

    def resolve(self, cls):
        cls = ALIASES.get(cls, cls)
        return cls if cls in self.usable else None

    def size_m(self, cls):
        return float(self.entries[ALIASES.get(cls, cls)]["size_m"])

    def _load(self, cls, key, size, reps, mode):
        path = os.path.join(self.usable[cls], key + ".jpg")
        if not os.path.exists(path):
            return None
        tile = size // reps
        img = Image.open(path).convert(mode).resize((tile, tile), Image.LANCZOS)
        a = np.asarray(img)
        return np.tile(a, (reps, reps) + (1,) * (a.ndim - 2))

    def maps(self, cls, size, reps):
        k = (cls, size, reps)
        if k not in self._tiles:
            e = self.entries[cls]
            color = self._load(cls, "color", size, reps, "RGB")
            normal = self._load(cls, "normal", size, reps, "RGB")
            rough = self._load(cls, "rough", size, reps, "L")
            ao = self._load(cls, "ao", size, reps, "L")
            metal = self._load(cls, "metal", size, reps, "L")
            if ao is None:
                disp = self._load(cls, "disp", size, reps, "L")
                if disp is not None:
                    d = disp.astype(np.float64) / 255.0
                    cavity = np.maximum(0.0, gaussian_filter(d, size / 64, mode="wrap") - d)
                    ao = to_u8(np.clip(1.0 - 3.0 * cavity, 0.45, 1.0))
                else:
                    ao = np.full((size, size), 255, np.uint8)
            scale = float(e.get("metal", 0.0))
            if metal is None:
                metal = np.full((size, size), int(round(255 * scale)), np.uint8)
            else:
                metal = to_u8(metal / 255.0 * scale)
            strength = float(e.get("normal", 1.0))
            if strength != 1.0:
                n = normal.astype(np.float64) / 127.5 - 1.0
                n[..., :2] *= strength
                n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9
                normal = to_u8(n * 0.5 + 0.5)
            orm = np.stack([ao, rough, metal], -1)
            self._tiles[k] = (color, normal, orm)
        return self._tiles[k]

    def normal_rgba(self, cls, size, reps):
        n = self.maps(cls, size, reps)[1]
        return np.dstack([n, np.full(n.shape[:2], 255, np.uint8)])

    def orm_rgba(self, cls, size, reps):
        o = self.maps(cls, size, reps)[2]
        return np.dstack([o, np.full(o.shape[:2], 255, np.uint8)])

    def albedo(self, cls, size, reps, grid, mean, contrast, alpha=None,
               grid_strength=0.8, chroma=0.35):
        """CC0 detail, retail coarse colour. grid (n, n, 3) and mean (3,) are sRGB 0..255,
        contrast the retail luma std/mean (None keeps the CC0 contrast)."""
        color = self.maps(cls, size, reps)[0]
        lin = srgb_to_lin(color / 255.0)
        m = lin.reshape(-1, 3).mean(0) + 1e-6
        lum = lin @ np.array([0.2126, 0.7152, 0.0722])
        d = lum / (lum.mean() + 1e-6)
        if contrast is not None:
            own = float(d.std()) + 1e-6
            d = 1.0 + (d - 1.0) * float(np.clip(contrast / own, 0.6, 1.4))
        # Some CC0 chroma survives (rust spots, moss), bounded so a saturated
        # set (red paint) cannot blow a channel up after the regrade.
        detail = (1.0 - chroma) * d[..., None] + chroma * np.clip(lin / m, 0.5, 2.0)
        meanl = srgb_to_lin(np.asarray(mean, np.float64) / 255.0)
        target = upsample_wrap(srgb_to_lin(np.asarray(grid, np.float64) / 255.0), size)
        target = meanl + grid_strength * (target - meanl)
        rgb = to_u8(lin_to_srgb(target * np.maximum(detail, 0.0)))
        a = np.full((size, size), 255, np.uint8) if alpha is None else alpha
        return np.dstack([rgb, a])


def reps_for(m_per_uv, size_m, size):
    """Whole repeats (power of two) of a CC0 tile across one texture so the
    surface keeps the set's real-world scale; 1..8 and >= 64 px per repeat."""
    if not m_per_uv or m_per_uv <= 0:
        return 1
    want = np.log2(max(m_per_uv / size_m, 1e-3))
    return min((c for c in (1, 2, 4, 8) if size // c >= 64), key=lambda c: abs(np.log2(c) - want))


def contact_sheet(cache, out, size=256):
    usable = {e["class"]: os.path.join(cache, e["id"]) for e in load_manifest()
              if os.path.exists(os.path.join(cache, e["id"], "color.jpg"))}
    lib = Library(cache, usable)
    rows = []
    for cls in usable:
        c, n, o = lib.maps(cls, size, 1)
        rows.append(np.hstack([c, n, o]))
    if rows:
        Image.fromarray(np.vstack(rows)).save(out)
    print(f"wrote {out}: {len(rows)} sets ({', '.join(usable)}), columns colour | normal | ORM")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "fetch":
        fetch(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "sheet":
        contact_sheet(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
