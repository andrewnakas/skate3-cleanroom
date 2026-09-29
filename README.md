# Skate 3 clean room (web)

Play: **https://andrewnakas.github.io/skate3-cleanroom/** (Chrome or Edge 113+ with WebGPU)

This is the Skate 3 Rust/Bevy engine rewrite ([skate-3-rust-engine](https://github.com/andrewnakas/skate-3-rust-engine), branch `cleanroom-web`) compiled to WebAssembly + WebGPU. It runs on a **clean asset pack**. Every image in the pack was regenerated from coarse facts, so no retail pixels are shipped.

## What the pack contains

| Kind | Treatment |
|---|---|
| Textures (maps, props, backdrops, skies, HUD, skater model): 7681 in total | **Regenerated.** Each one is rebuilt from its size, a 4x4 or 16x16 colour grid and a 2-bit alpha outline, plus our own detail noise and dither. |
| Map geometry, collision, grind rails, spawns/teleports | Kept (facts) |
| Skater skeleton, skin weights, mesh | Kept (facts) |
| Animations, state graphs, physics/VLT tuning, input/camera configs | Kept (facts) |
| HUD / sky layout data, lighting parameters, irradiance probes | Kept (facts) |
| Player sound effects (27: rolling per surface, grinds, powerslide, pops, landings, bails, footsteps, pushes, flips, a menu cue) | **Regenerated.** Each is synthesised from a coarse outline of a retail sample (per-frame pitch, harmonicity, 16-band loudness envelope) with new noise and partials; `audio_clean.py`. |
| Music, speech | Not shipped. |
| Everything else from the disc | Dropped |
| `dmjumpline` map | The author's own map (converted from a Descenders mod with their own tool); shipped as-is and taint-scanned like everything else. |
| Freestyle MX bike mod | Engine SDK example; the Lua script runs as a built-in Rust port on the web. Model: "KTM 450 EXC" by mx-3d (Sketchfab), CC BY 4.0. |

Taint scan: all regenerated textures (7692 incl. dmjumpline) and all 27 sounds are compared with the retail ones. The result is **0 failing**: no shared byte run of 32 bytes or more, no texture sharing 4+ sampled windows with any single retail texture, and no regenerated file identical to a retail one.

## Pipeline (`games/skate3/`)
1. The engine's `tools/prepare_assets.py` converts your own disc into a private pack. This stays private and is never published.
2. `python -m games.skate3.generate <private pack> <clean dir> <spec dir>` copies the kept facts and regenerates every texture (`skate14.py` rewrites SKATE14 map texture payloads).
3. `python -m games.skate3.taint_report <private pack> <clean dir>` runs the taint scan.
4. `python -m games.skate3.audio_clean describe <pcm dump> <spec>` (dirty: outlines only), `build <spec> <clean>/assets`, `taint <pcm dump> <clean>/assets`. The dump comes from the engine example `dump_player_pcm`.
5. In the engine repo, `tools/build_web.ps1 -Pack <clean dir> -Out <site>` builds the wasm, the page and the packed assets.

## Controls
See `docs/web.md` in the engine repo. Keyboard and browser gamepads are supported. Change maps with the picker, or add `?map=Name` to the URL.

## Known limits
- The three big districts (DownTown, University, Industrial) are not on the web build yet: University loads but never draws a frame in the browser.
- Web audio is a simple clean-room driver, not the desktop build's retail-exact audio runtime (that emulates the retail guest and needs the disc's banks).
- The first load takes a few seconds for loading plus shader compilation.
