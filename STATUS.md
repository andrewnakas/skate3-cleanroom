# Skate 3 clean room: status

## Done (2026-09-28)
- Engine worktree `D:\n64work\skate3\engine` (branch cleanroom-web from cc41fb9); wasm32 target + wasm-bindgen 0.2.127 installed.
- Survey: pack has no audio (nothing to clean there); required core = game.json, skater.glb, abin, stategraphs, input.cfg, VLT json, camera/joystick files; .skate textures are RGBA8 (zlib/zstd) -> `tools/asset_pipeline/refresh_textures.py` rewrites them (SKATE14).
- Web blockers: ~127 std::fs sites (plan: preloaded in-memory VFS shim), ~80 Instant::now (-> bevy::platform::time), mlua/socket2 (feature-gate), Vulkan hard-coded, bindless binding_array material (needs non-bindless fallback for WebGPU).

## Blocked
- Desktop `cargo build -p skate-game` was killed by Claude Code for low system memory (other sessions running). Needed before the dirty convert (install.py runs the exe with --check-assets).

## Next
1. Build exe (CARGO_TARGET_DIR=D:\n64work\skate3\target, -j4 or -j2).
2. `python tools\prepare_assets.py --game-root <retail> --output D:\n64work\skate3\dirty --game-exe D:\n64work\skate3\target\debug\skate3rust.exe`.
3. census -> spec -> generate -> taint -> web port.
