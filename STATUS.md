# Skate 3 clean room: status

**Live:** https://andrewnakas.github.io/skate3-cleanroom/ (WebGPU: Chrome/Edge 113+). Repo: andrewnakas/skate3-cleanroom (main = code, gh-pages = site).

## Done (2026-09-28)
- Engine worktree `D:\n64work\skate3\engine`, branch `cleanroom-web` (725acdb, ae8f459, 789f242; local only, not pushed to the engine repo): skate-vfs in-memory FS, wasm32 gating (mods/net/zstd->ruzstd/audio-core), WebGPU, keyboard+gamepad -> XInput packet, teleport start, `tools/build_web.ps1`, `tools/web_pack.py`, `docs/web.md`.
- Clean pack `D:\n64work\skate3\clean`: 7681 textures regenerated (grid + 2-bit alpha + detail noise + dense +-2 RGB dither), 406 kept-fact files, 1732 dropped. Taint: **0 failing**, 0 files identical to retail.
  - Dither notes: undithered = 1114 coincidental 33-66 B runs; sparse every-7th-pixel nudge = 990 failing (16-B windows); dense +-2 dither = 0 failing but ~2x texture bytes.
- Site `D:\n64work\skate3\site` (437 MB, 7 maps: StartPark, MegaPark, IndustrialSkatePark, BlackBoxPark, DownTownSkatePark, MaloofMoneyCup, SkateSchool). Headless Edge WebGPU: world + skater + HUD render locally and from Pages.

## Known issues / next
- DownTown, University, Industrial not published: University never draws a frame on web (1.6M tris, 2046 textures); dithered sizes 578/479/330 MB would also need a second Pages repo.
- Authored spawns have no supporting collision (native too) -> maps start at a teleport (`?teleport=none` for the authored spawn).
- No audio on web (XMA decode spawns ffmpeg). wasm 69.6 MB, no wasm-opt yet. First load: 150-220 MB download.
- Headless FPS reads 1-2 right after screenshots (capture artifact per the port notes); verify by playing.

## For the user
- Open the live URL in Chrome/Edge, pick a map (bottom right). Keyboard = Xbox pad (WASD left stick, arrows right stick, Space A, E B, Shift X, F Y, Z/C triggers, Q/R bumpers, Enter Start); gamepads work directly. Report FPS and how skating feels.

## Update (2026-09-28, later)
- Loader caches engine/core/map in Cache Storage (content-hash keys) -> map switches only download the new map.
- Canvas follows the window (no fixed 1280x800 on web) + Fullscreen button. Engine commits ccb9fa3, 1c5cfdf.
- User played it; one crash, cause unknown (need Edge F12 console).

## Update (2026-09-29)
- Merged the user's engine branch `audio/retail-exact-player-sound` (1415b5d: trick fixes/scoring, per-wheel rolling, retail-exact player audio, MX dirt bike) into `cleanroom-web` (engine commits 61824d9, 0b1984f).
- **Freestyle MX bike on web:** the Lua mod runs as a built-in Rust port (`skate-mods/src/native/freestyle_mx.rs`, Lua parity test passes). F9 spawns, E mounts, C throttle, V clutch (web), Q/R + arrows tricks. Model "KTM 450 EXC" by mx-3d, CC BY 4.0 (credited on the page and README).
- **Web audio:** the desktop's retail-exact audio emulates the retail guest (x86_64, needs retail banks), so the web gets `player_audio_web.rs`: 27 clean sounds (`audio_clean.py`, descriptors -> resynthesis), audio taint 0 failing.
- **dmjumpline** (user's own SKATE15 map) added; engine falls back to authored rails when a map has no WMET manifest.
- Taint: 7692 textures, 0 failing (new: failures attributed per retail texture; the one scattered dmjumpline wood texture shares at most 1 window with any retail texture), 0 files identical to retail.
- Headless: StartPark + dmjumpline render, bike spawns and mounts, audio loads. Driving/feel not verified headless (~1 FPS) - please try it.

## Next
- User playtest: bike driving on web, sound levels/mix, dmjumpline rails.
- Crash from 2026-09-28 still needs the Edge F12 console lines if it recurs.

## Update (2026-10-08): geometry regenerated, community maps
- **Visual geometry is no longer retail mesh data.** `games/skate3/geom.py` rewrites every SKATE14 file (10 maps, 5 prop sets, 3 backdrops) and `skater.glb`: positions on our own 0.37 mm lattice (0.13 mm for the skater), other diagonal on every nearly flat quad (70% of 5.0M triangles), normals/tangent frames recomputed, UVs re-quantised, new order. Collision values kept exactly but re-encoded in our own container (verified equal triangle lists); WMET trimmed to rail identities (StartPark 160 KB -> 120 B). Hooked into `generate.py`.
- **Geometry taint** `games/skate3/geom_taint.py`: 19 files, 0 failing (no shared 32-byte run in vertices, indices, collision, model accessors). Texture/audio taint unchanged.
- **Checked in headless Edge (WebGPU):** StartPark, MegaPark, SkateSchool load with the same collision triangle and rail counts as the old build (12533 / 12170 / 91790 triangles, 210 splines) and render the same within run-to-run noise.
- **Community maps in the picker** (engine `web/loader.js`): skatemods.com catalog (`?smap=<id>`), any CORS-readable URL (`?mapurl=`), local file. Checked end to end against a local copy of the skatemods API with dmjumpline uploaded through the real upload -> runner -> approve flow.
- **Needs deploying on skatemods.com before the catalog shows up live:** branch `engine-map-import` of andrewnakas/skatemods (CORS on the public map routes + `?cors=1` streaming for files stored as GitHub release assets, which have no CORS headers). Until then the picker shows "catalog unavailable". The live catalog also has 0 approved maps today.
- Not changed, still kept as facts: animations (ABIN), state graphs, VLT tuning, rails, skeleton, HUD/sky layout, irradiance probes, collision values.

## For the user (2026-10-08)
- Skate the 7 retail parks and look for visual seams, flicker on decals/thin layers, or lighting that looks off (trees and curved ramps are where recomputed normals differ most). Skating itself should feel identical: collision is bit-for-bit the same.
- Phones: triangle counts are unchanged, so performance should be too.

## Update (2026-10-08, later): browser multiplayer
- Looked at other Skate 3 projects: Splash250's GPL fork of the same engine has a dedicated UDP server (16-64 players, accounts, voice, Lua/JS/.NET resources, RP showcase, ~97k lines on newer upstream); SK8-ENGINE upstream has the peer/Steam lobby our branch already carries; chasmlol/2010-rust-rewrite-mashup (Apache-2.0) has its own net crate. All UDP or Steam, none browser-capable.
- Built: engine `multiplayer::transport::Web` + `web/net.js` (engine commit on `cleanroom-web`), room relay `relay/` (Durable Object, 10 per room, tests pass). Two headless Edge tabs in one room on StartPark: both "Connected 2/10, synced characters", RTT 66-90 ms, ~18 kB/s each way, spawns 1.5 m apart, no contacts.
- **Not deployed:** `cd relay && npx wrangler deploy` (route skatemods.com/rooms/*). The auto-mode permission check blocked me from deploying to Cloudflare. Until it is deployed the site hides the Multiplayer button.
- Free plan note: Durable Object WebSocket messages count 20:1 against 100k requests/day, roughly 15-20 player-hours a day at ~30 packets/s per player.

## Update (2026-10-09)
- Relay: public room directory (`/list`), page room menu (private / public / join listed). Tested with two headless tabs.
- Maps found in private andrewnakas/skatemods-testdata (release test-data): `kenney_park` (CC0 Kenney kit, original park) + JumpCity and Sunbad Art Gallery (community maps, marked retail-derived, not public). KenneyPark added as a built-in map (9 maps on the site). JumpCity (3.6M triangles, 95 MB) and Sunbad load through `?mapurl=` at ~50 FPS in headless Edge; they stay local in D:
64work\skatemods-testdata.
- geom.py leaves original maps (no WMET, or authored collision layout) alone.
- Still blocked for Claude (auto-mode permission): `wrangler deploy` of relay/ and of skatemods apps/api, and merging skatemods PR #1.

## Update (2026-10-10): grind edges derived from collision (custom maps)
- Report: community Kenney Park had no grinds. Cause: the engine only grinds map rail curves; the map has 2 (rails at 0.75 m and 1.35 m), nothing on copings/ledges.
- Engine (worktree, `cleanroom-web`, **uncommitted**): `crates/skate-game/src/grind_world/derive.rs` + `provider.rs` `StaticProvider::custom`. Maps without the stock WMET manifest get grind edges derived from their triangle collision (convex crease on a rideable face, >= 0.25 m drop beside it, >= 0.6 m long, thin bars merged to one centre rail, edges that already have a map rail skipped). Stock maps unchanged. Maps whose collision is an RWCM archive get nothing derived.
- Headless Edge on the new wasm: KenneyPark 2 -> 31 grind segments, dmjumpline 1417 -> 2200, SkateSchool 2009 -> 2009. 6 unit tests pass (compiled standalone with rustc; the skate-game test harness was not run).
- Staged only, not published: `D:\n64work\skate3\site-grind` (hardlinked copy of `site` + new wasm + its own pack.json). Not verified: an actual grind in play.
- Trap: a new wasm needs the `engine.size` in pack.json updated, or the page sits at "Loading ... 155 / 156 MB" with no console output.
- `D:\n64work\skate3\target\debug\.cargo-build-lock` is unreadable (Windows error 1392).

## Update (2026-10-11): grinds still failed in the owner's playtest
- Cause found: the engine's cross-section test refuses a rail line with surface 9 cm to both sides, so rail lines down the middle of Kenney Park's 30 cm bars (the map's own two, and the merged derived ones) never grind.
- `derive.rs` now runs that same test: wide bars keep both top edges, a map's own polyline rail is dropped when it is too wide to grind. Kenney Park: 34 edges. 7 unit tests pass (standalone rustc).
- Not yet verified in play. Copings and box edges passed the test in the failed build too, so a second cause is possible.
- Engine branch `cleanroom-web` is pushed to andrewnakas/skate-3-rust-engine (2026-10-11). Site build with this fix: `D:\n64work\skate3\rebuild_grind.ps1` -> `site-grind` (local only).
