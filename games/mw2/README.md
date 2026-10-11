# MW2 maps, clean room

Clean-room versions of Modern Warfare 2 (2009) multiplayer maps for the
**Skate 3 x MW2** web build ([andrewnakas/skate3-mw2](https://github.com/andrewnakas/skate3-mw2),
`andrewnakas.github.io/skate3-mw2`). The output is an ordinary `.skate` map: skate it, or press
J for MW2 mode (IW4L's MW2 movement, guns and bots on the same collision).

Same rules as the Skate 3 parks (`CLAUDE.md`). Kept as facts: collision triangles, spawns, which
material covers each surface, the surface layout (0.37 mm lattice), where the texture lands
(1/3000 tile), surface types. Regenerated: the visual mesh (`games.skate3.geom.regen_mesh`).
Surfaces: CC0 PBR materials (below) tinted by each retail texture's coarse colour, or, where no
CC0 set fits, the regenerated texture (Skate 3 rule). Dropped: everything else. The taint report must print
**0 failing** before a map is published. As with the parks, a map's layout is still the
map's layout: the page says so.

## Steps (Windows, everything on D:)

The retail game stays read-only wherever it is installed (Steam: `...\steamapps\common\Call of Duty Modern Warfare 2`,
with `main\` and `zone\english\mp_rust.ff`). Private data goes to `D:\n64work\mw2\` and is never committed.

1. **Export (dirty).** The exporter is a binary in the IW4L fork
   ([andrewnakas/mw2-skate-web](https://github.com/andrewnakas/mw2-skate-web), `crates/clean_export`):

   ```powershell
   git clone https://github.com/andrewnakas/mw2-skate-web D:\n64work\mw2\iw4l
   cd D:\n64work\mw2\iw4l
   $env:CARGO_TARGET_DIR = 'D:\n64work\mw2\target'
   $env:IW4L_GAMES = '<folder that contains the MW2 install>'
   cargo run --release -j4 -p clean_export -- mp_rust D:\n64work\mw2\private\mp_rust
   ```

   It writes `export.json`, `render.npz`, `collision.npz` and `images\*.png` (retail pixels).
2. **Generate (clean):** `python -m games.mw2.generate D:\n64work\mw2\private\mp_rust D:\n64work\mw2\clean\mp_rust D:\n64work\mw2\spec`

   Options: `--materials pbr|regen` (default `pbr`, see "Materials"), `--pbr-size 512|1024`
   (CC0 output size, default 512), `--cc0-cache <dir>` (default `D:\n64work\mw2\cc0`, the
   spec dir's sibling), `--max-texture N` (cap for regenerated textures, default 512).
   It prints a materials line (how many got a CC0 set, per class) and writes
   `spec\materials-mp_rust.json` (each material's class, the reason, and the coarse facts used).
3. **Taint:** `python -m games.mw2.taint_report D:\n64work\mw2\private\mp_rust D:\n64work\mw2\clean\mp_rust`
   must end with `0 failing` (exit code 0).
4. **Write the map** with the engine's writer (skate3-mw2 repo):
   `python tools\mesh_to_skate.py D:\n64work\mw2\clean\mp_rust D:\n64work\mw2\Rust.skate`
5. **Check** it loads: `cargo run -p skate-data --example inspect_skate -- D:\n64work\mw2\Rust.skate`,
   then in the browser with `?mapurl=` pointing at a local server
   (`python ports/wasm/serve.py D:\n64work\mw2 8000`, page `...skate3-mw2/?mapurl=http://localhost:8000/Rust.skate`).
6. **Publish** only `Rust.skate` (and nothing from `private/` or `spec/`): commit it to the skate3-mw2 repo as
   `maps/mw2/Rust.skate` (the site lists `maps/mw2/*.skate` under "MW2 maps"), with the taint line in the
   commit message. Files over 95 MB must be split (`.part0`, `.part1`, ...).

## Materials ("hybrid")

Every map surface gets a sharp CC0 PBR material (albedo + normal + roughness/AO) chosen per
material and tinted by MW2's coarse colour layout:

- **Library** (`cc0_materials.toml`, `materials.py`): 26 [ambientCG](https://ambientcg.com) sets,
  all CC0 1.0 (concrete smooth/rough/dirty, asphalt, cracked asphalt, paving, plaster, painted
  plaster, brick, rusted / corrugated / painted metal, tread plate, wood planks, wood floor,
  plywood, bark, sand, dirt, gravel, rubble, grass (also foliage), rock, tiles, fabric, carpet).
  Each entry records id, download URL, source, author and licence. At run time the 1K-JPG zips
  are downloaded into the cache (never committed); each asset is checked against the ambientCG
  API and the site's licence page must say "CC0 1.0 Universal", else the set is not used.
  `python -m games.mw2.materials fetch <cache>` pre-fetches; `... sheet <cache> out.png` draws
  the library.
- **Classification** (`classify.py`, dirty side, facts only): the IW4 surface type (the
  exporter's `materials[].surface`, or, while it writes 0, the surface of the collision faces the
  material's render triangles lie on), name keywords (input only: names are never shipped or
  written to the spec; tokens of the zone name are ignored), and coarse facts of the retail colour
  map (mean colour, 4x4 grid, contrast, saturation, alpha coverage). Alpha-blended materials and
  names like decal / sign / glass / window keep the regenerated texture.
- **Synthesis** (`materials.py`, clean side): albedo = the CC0 colour map tiled a power-of-two
  number of times (so its real-world size matches the material's texel density), regraded in
  linear light to the retail 4x4 colour grid + mean, its contrast pulled toward the retail
  contrast; normal = the set's NormalGL (OpenGL +Y, what Bevy expects); ORM = R AO (or a cavity
  term from the displacement), G roughness, B metalness. Alpha-tested materials (fences,
  foliage) keep the regenerated 2-bit alpha outline. Normal and ORM maps are shared per
  (class, size, repeats). The material's `roughness` is 1 (the engine multiplies ORM green by it).
  Deterministic for a given cache.
- **Taint**: the albedo, normal and ORM maps are all scanned against the retail images as before
  (must be 0 failing); the CC0 sets are listed as non-retail sources. `CREDITS.json` in the clean
  dir lists the sets used.

Engine notes (skate3-mw2 `crates/skate-game/src/skate_world.rs`): normal and ORM maps load as
linear `Rgba8Unorm` with repeat addressing (UV tiling > 1 repeats); tangents are generated
(mikktspace) because SKATE09 has no tangent frames; with an ORM map `metallic` is 1 and the
ORM blue channel is the metalness. These map textures (and albedo) get no mip chain in the
engine today, so distant tiled detail can shimmer.

Start with `mp_rust` (small). Then, one at a time: `mp_rundown`, `mp_highrise`, `mp_terminal`, `mp_favela`.
Log every run (counts, taint line, size) in `STATUS.md`.
