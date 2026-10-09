# Skate 3 clean room (web)

Play: **https://andrewnakas.github.io/skate3-cleanroom/** (Chrome or Edge 113+ with WebGPU)

This is the Skate 3 Rust/Bevy engine rewrite ([skate-3-rust-engine](https://github.com/andrewnakas/skate-3-rust-engine), branch `cleanroom-web`) compiled to WebAssembly + WebGPU. It runs on a **clean asset pack**. Every image, every sound and every visual mesh in the pack was regenerated, so no retail pixels, samples or mesh buffers are shipped. What is still kept as plain facts is listed below.

## What the pack contains

| Kind | Treatment |
|---|---|
| Textures (maps, props, backdrops, skies, HUD, skater model): 7681 in total | **Regenerated.** Each one is rebuilt from its size, a 4x4 or 16x16 colour grid and a 2-bit alpha outline, plus our own detail noise and dither. |
| Visual geometry (7 maps, their props and backdrops, the skater model): 5.0 million triangles | **Regenerated** (`geom.py`). Kept as fact: the surface to 0.4 mm, which material covers it, where the texture lands. Rebuilt from that: vertex positions on our own lattice, the triangulation (every nearly flat quad that can take the other diagonal gets it: 70% of all triangles), normals and tangent frames recomputed from the triangles, UVs on our own lattice, new vertex and triangle order. The skater's skin weights are re-quantised. |
| Collision | Triangle positions, edge codes and surface ids are **kept exactly** (the skating depends on them), in our own container: the retail headers, spatial tree and names are dropped. Old and new decode to the same triangle list bit for bit. |
| Grind rails, spawns/teleports, skater skeleton | Kept (facts) |
| Map manifest | Trimmed to the rail identities the engine checks; stream names, source offsets and asset tables are dropped. |
| Animations, state graphs, physics/VLT tuning, input/camera configs | Kept (facts) |
| HUD / sky layout data, lighting parameters, irradiance probes | Kept (facts) |
| Player sound effects (27: rolling per surface, grinds, powerslide, pops, landings, bails, footsteps, pushes, flips, a menu cue) | **Regenerated.** Each is synthesised from a coarse outline of a retail sample (per-frame pitch, harmonicity, 16-band loudness envelope) with new noise and partials; `audio_clean.py`. |
| Music, speech | Not shipped. |
| Everything else from the disc | Dropped |
| `dmjumpline` map | The author's own map (converted from a Descenders mod with their own tool); shipped as-is and taint-scanned like everything else. |
| Freestyle MX bike mod | Engine SDK example; the Lua script runs as a built-in Rust port on the web. Model: "KTM 450 EXC" by mx-3d (Sketchfab), CC BY 4.0. |

Geometry taint scan (`geom_taint.py`): the vertex buffer, index buffer and collision container of every regenerated file are compared with the private pack. **0 failing**: no shared 32-byte run; 615 of 6.6 million vertices (0.009%) keep the same three position floats (far-away backdrop corners where a float cannot hold a sub-millimetre change).

What "regenerated geometry" does not change: the parks are still the same parks. The layout of a level is the level; this pack ships none of the retail mesh data for it, not a different design.

Taint scan: all regenerated textures (7692 incl. dmjumpline) and all 27 sounds are compared with the retail ones. The result is **0 failing**: no shared byte run of 32 bytes or more, no texture sharing 4+ sampled windows with any single retail texture, and no regenerated file identical to a retail one.

## Pipeline (`games/skate3/`)
1. The engine's `tools/prepare_assets.py` converts your own disc into a private pack. This stays private and is never published.
2. `python -m games.skate3.generate <private pack> <clean dir> <spec dir>` copies the kept facts and regenerates every texture (`skate14.py` rewrites SKATE14 map texture payloads) and every map mesh (`geom.py`). `python -m games.skate3.geom <clean dir>` runs the geometry pass on its own (maps, props, backdrops, skater model); it marks what it has done and skips it next time.
3. `python -m games.skate3.taint_report <private pack> <clean dir>` runs the texture taint scan; `python -m games.skate3.geom_taint <private pack> <clean dir>` the geometry one.
4. `python -m games.skate3.audio_clean describe <pcm dump> <spec>` (dirty: outlines only), `build <spec> <clean>/assets`, `taint <pcm dump> <clean>/assets`. The dump comes from the engine example `dump_player_pcm`.
5. In the engine repo, `tools/build_web.ps1 -Pack <clean dir> -Out <site>` builds the wasm, the page and the packed assets.

## Controls
See `docs/web.md` in the engine repo. Keyboard and browser gamepads are supported. Change maps with the picker, or add `?map=Name` to the URL.

## Multiplayer
Use the **Multiplayer** menu next to the map picker: a private room gives you an invite link (`?room=CODE`) to send; a public room is listed in everyone's menu with its map and player count, so anyone can join. Up to 10 players skate the same map together: positions, full ragdolls, poses, tricks and player collisions use the engine's own skate-net session. The browser can't open UDP sockets, so datagrams go over a WebSocket to a small room relay (`relay/`, a Cloudflare Durable Object; it only forwards bytes between room members). The first player in a room hosts; if they leave, the others reload to continue.

Other Skate 3 projects with multiplayer (October 2026), for reference: [Splash250/skate-3-rust-engine](https://github.com/Splash250/skate-3-rust-engine) adds a 16-64 player dedicated UDP server, accounts, voice and scripted resources to the same engine (GPL-3.0, like ours); [SK8-ENGINE](https://github.com/SK8-ENGINE/skate-3-rust-engine) has the peer/Steam lobby code this build uses. Neither runs in a browser.

## Community maps
The map picker also loads maps that are not in this repository; they are fetched by your browser when you pick them and are never part of the clean pack.
- **skatemods.com**: every approved map on [skatemods.com/maps](https://skatemods.com/maps/) that has a `.skate` conversion is listed under "Community maps". Direct link: `?smap=<map id>`.
- **Any URL**: `?mapurl=https://.../park.skate` (the host must allow cross-origin reads; GitHub Pages and raw.githubusercontent.com do, GitHub release downloads do not).
- **Your own file**: "Open .skate file..." in the picker.
Community maps are their authors' work under the license shown on their skatemods page; they are not regenerated or taint-scanned.

## Known limits
- The three big districts (DownTown, University, Industrial) are not on the web build yet: University loads but never draws a frame in the browser.
- Web audio is a simple clean-room driver, not the desktop build's retail-exact audio runtime (that emulates the retail guest and needs the disc's banks).
- The first load takes a few seconds for loading plus shader compilation.
