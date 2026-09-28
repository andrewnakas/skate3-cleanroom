# Skate 3 clean room: status

## Done (2026-09-28)
- Engine worktree `D:\n64work\skate3\engine` (branch cleanroom-web from cc41fb9); native debug exe built (CARGO_TARGET_DIR D:\n64work\skate3\target, -j3, long builds run detached).
- Dirty convert: `D:\n64work\skate3\dirty` (1.1 GB, 10 maps, SKATE14). Private; never committed.
- Clean pack: `python -m games.skate3.generate <dirty install> D:\n64work\skate3\clean D:\n64work\skate3\spec`
  - 7681 textures regenerated (7557 in .skate maps/props/backdrops, 45 raw .rgba skies/HUD/marker, 57 png, 22 in skater.glb) from size + 4x4/16x16 grid + 2-bit alpha.
  - 406 kept-fact files (abin, stategraphs, VLT/physics json, input.cfg, joystick .pat, camera .shk, sky/prop/HUD layout json, teleports, lighting params, irradiance probes); 1732 dropped (raw retail containers rx2/r2b, xml, logs).
  - Native `skate3rust --check-assets` passes on all 10 clean maps.
- Audio: the pack has no audio (engine plays none from the pack) -> nothing to clean; no music, no speech.

## In progress
- Taint report (`python -m games.skate3.taint_report <dirty> <clean>`): per-texture pairwise run check + 1/64 sampled global index.
- Web port (engine branch cleanroom-web): VFS, wasm gates, WebGPU, loader page, web_pack.py.

## Next
- Headless WebGPU check on the clean pack; publish `andrewnakas/skate3-cleanroom` + Pages (clean pack + wasm only; maps > 95 MB chunked).
