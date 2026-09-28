# Skate 3 — clean-room pack for the Rust/Bevy engine

You are running **unattended**. The user prompts once and checks in later. Work autonomously: decide with the defaults below, log every decision in `STATUS.md`, and never stop to ask unless something is truly blocking (then write the question in STATUS.md and continue with anything else).

## Goal
The user's Skate 3 Rust/Bevy rewrite (engine repo below) today runs only on a private pack converted from the retail Xbox 360 disc. Build a **clean pack** regenerated from coarse facts so the engine runs with **no retail content**, then ship:
1. **Desktop:** engine exe + clean pack (the user tests with a controller).
2. **Web:** Bevy `wasm32-unknown-unknown` (WebGPU, WebGL2 fallback) loading the clean pack over HTTP, published as `andrewnakas/skate3-cleanroom` + GitHub Pages (`andrewnakas.github.io/skate3-cleanroom`). gh CLI is logged in as andrewnakas.

## Pre-answered scope (do not ask)
- **Kept as facts:** map geometry, collision (RWCM), grind splines, spawns/teleports, materials; skater skeleton, skin weights, mesh geometry; ABIN animations, state graphs, VLT/AttribSys tuning, control maps; APT UI layout + strings; texture format, size, 4x4 colour grid (16x16 for large/sky), 2-bit alpha; SFX/ambience length, rate, loops, coarse outline, median pitch.
- **Regenerated:** every texture (`cleanroom.decomp.spec.texture_fact` + gen; faces/logos via briefs with `cleanroom.gfx.facepaint`), bitmap fonts (`cleanroom.gfx.glyphs`), UI images (labels/briefs), SFX + ambience (resynthesised from descriptors, written as plain PCM/WAV).
- **Dropped:** all music and all speech — not kept, not regenerated; the engine treats them as silent.
- No voice cloning, no models trained on retail audio.
- Taint scan (texel RGBA + PCM vs the dirty pack) must report **0 failing** before anything is published. Never publish or commit the retail disc, dirty packs, dev builds or retail clips.

## Pipeline (scripts print one-screen summaries; code lives in `games/skate3/`)
1. **Dirty convert:** `python tools\prepare_assets.py --game-root <retail> --output D:\n64work\skate3\dirty --game-exe <retail>\default.xex` (engine repo tool) → manifest `game.json`, 10 `.skate` maps, skater GLB, ABIN banks + state graphs, APT HUD + fonts, VLT data, audio banks. Run the engine on it once as the baseline (log + a few headless/offline renders).
2. **Census** (`census.py`, generalising `cleanroom.decomp.census`): every file by kind, sub-asset counts via the engine's own readers (`crates/skate-data/src/{skate_map.rs,manifest.rs}`, `tools/asset_pipeline/*`).
3. **Spec** (`extract_spec.py`): the kept facts above → `D:\n64work\skate3\spec` (dirty side; never committed).
4. **Generate** (`generate.py`): clean pack at `D:\n64work\skate3\clean` with the same manifest shape; rewrite `.skate` maps with regenerated textures using the engine's writer (`tools/asset_pipeline/map_writer.py` / `build_map.py`); re-texture the skater GLB (`character_glb.py`); rebuild HUD/fonts; SFX as WAV.
5. **Engine patches** (small, feature-gated, branch `cleanroom-web`): accept PCM/WAV SFX when EA/XMA2 banks are absent; missing music/speech banks = silent; no gameplay changes.
6. **Taint** (`taint_report.py`, adapted from `cleanroom.decomp.taint` / `reference/sm64/taint_report.py`): must print 0 failing; lists kept facts.
7. **Desktop:** build the exe, run it on the clean pack (`scripts\Launch.ps1 --assets D:\n64work\skate3\clean`), check the log loads every map; texture contact sheets per map for yourself. Write "for the user" test steps in STATUS.md — do not launch the game on the desktop for the user.
8. **Web:** cargo features to drop native-only crates (`skate-mods` Lua, `skate-net`, `skate-steam-relay`, ffmpeg path); HTTP asset loading; wasm-bindgen (no emsdk needed); page from `ports/web/shell.html` (see `reference/sm64/make_site.sh`, `reference/sm64/web`); headless check with `ports/wasm/headless_shot.py --webgl` (+ WebGPU flags). Publish repo + Pages with the clean pack and wasm only.

## Engine repo rules
- Engine: `C:\Users\andre\OneDrive\Documents\ChatGPT\Sk8EngineAudio` (Rust/Bevy 0.18 workspace: skate-core, skate-data, skate-game = exe `skate3rust`, skate-mods, skate-vehicles, skate-net, skate-steam-relay, skate-audio-formats, skate-audio-core). Origin andrewnakas/skate-3-rust-engine.
- **Never modify that OneDrive checkout**: it has 5 uncommitted audio files and local branches (audio/retail-exact-player-sound, mx/*). Work in a worktree: `git -C C:\Users\andre\OneDrive\Documents\ChatGPT\Sk8EngineAudio worktree add D:\n64work\skate3\engine -b cleanroom-web` (it is a shallow detached clone; base the branch on its current HEAD).
- Build with `CARGO_TARGET_DIR=D:\n64work\skate3\target` and `-j4`.
- Critical files: `tools/prepare_assets.py`, `tools/asset_pipeline/{map_writer.py,build_map.py,character_glb.py}`, `tools/owned_game/{big.py,refpack.py}`, `tools/vendor/skate3_ui/*`, `crates/skate-data/src/{manifest.rs,skate_map.rs,texture_decode.rs,retail_collision.rs,abin/}`, `crates/skate-game/src/{config.rs,setup.rs,custom_models.rs}`, `crates/skate-audio-formats/src/*`, `crates/skate-data/src/audio/{mod.rs,ffmpeg.rs}`.

## Where things are
- This repo: `cleanroom/` shared library (copy; extend freely), `ports/`, `tools/`, `docs/DECOMP_PLAYBOOK.md` (**read first**: rules and traps; its N64 build routes don't apply here), `reference/sm64/` (finished SM64 module: generate.py, facepaint briefs, taint_report.py, make_site.sh, web/).
- Retail game (read-only): `C:\Users\andre\Documents\skate4maps\skate3\freeskate\runtime\game` (`default.xex` + `data`). Other skate4maps folders are unrelated.
- Work dir: `D:\n64work\skate3\` (dirty, spec, clean, build, engine worktree, target). **C: and E: are nearly full — everything goes on D:.**
- Python 3.12 with numpy, scipy, librosa, pyworld, av, websocket-client.
- Browser checks: `python ports/wasm/serve.py <site> <port>` + `python ports/wasm/headless_shot.py <out> --base http://localhost:<port>/index.html --secs 5,10 --webgl`; hangs: `ports/wasm/cdp_stack.py`.

## Machine budget
Other clean-room sessions share this PC: ≤8 GB RAM, `cargo -j4`, check `df -h /d` before big jobs, one headless browser at a time, long jobs in the background.

## How to work (token-minimal)
- Scripts print one-screen summaries; one contact sheet per question; fixes as patch lists / JSON briefs.
- Keep `STATUS.md` current: what works, decisions, what's next, and a short "for the user" list (what to test on the desktop, what to look at).
- Commit often (git user andre / treesixtyweather@gmail.com; end commit messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`).
