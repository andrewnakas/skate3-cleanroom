# MW2 maps, clean room

Clean-room versions of Modern Warfare 2 (2009) multiplayer maps for the
**Skate 3 x MW2** web build ([andrewnakas/skate3-mw2](https://github.com/andrewnakas/skate3-mw2),
`andrewnakas.github.io/skate3-mw2`). The output is an ordinary `.skate` map: skate it, or press
J for MW2 mode (IW4L's MW2 movement, guns and bots on the same collision).

Same rules as the Skate 3 parks (`CLAUDE.md`). Kept as facts: collision triangles, spawns, which
material covers each surface, the surface layout (0.37 mm lattice), where the texture lands
(1/3000 tile), surface types. Regenerated: every texture (Skate 3 rule) and the visual mesh
(`games.skate3.geom.regen_mesh`). Dropped: everything else. The taint report must print
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

Start with `mp_rust` (small). Then, one at a time: `mp_rundown`, `mp_highrise`, `mp_terminal`, `mp_favela`.
Log every run (counts, taint line, size) in `STATUS.md`.
