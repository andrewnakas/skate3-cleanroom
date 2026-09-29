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
