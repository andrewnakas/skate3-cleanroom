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
| Music, speech, sound effects | Not shipped. The pack has no audio. |
| Everything else from the disc | Dropped |

Taint scan: all 7681 regenerated textures are compared with the retail ones. The result is **0 failing**: no shared byte run of 32 bytes or more, and no regenerated file is identical to a retail one.

## Pipeline (`games/skate3/`)
1. The engine's `tools/prepare_assets.py` converts your own disc into a private pack. This stays private and is never published.
2. `python -m games.skate3.generate <private pack> <clean dir> <spec dir>` copies the kept facts and regenerates every texture (`skate14.py` rewrites SKATE14 map texture payloads).
3. `python -m games.skate3.taint_report <private pack> <clean dir>` runs the taint scan.
4. In the engine repo, `tools/build_web.ps1 -Pack <clean dir> -Out <site>` builds the wasm, the page and the packed assets.

## Controls
See `docs/web.md` in the engine repo. Keyboard and browser gamepads are supported. Change maps with the picker, or add `?map=Name` to the URL.

## Known limits
- The three big districts (DownTown, University, Industrial) are not on the web build yet: University loads but never draws a frame in the browser.
- There is no audio.
- The first load takes a few seconds for loading plus shader compilation.
