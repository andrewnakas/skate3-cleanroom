# Super Mario 64 — clean room web build

Play: **https://andrewnakas.github.io/sm64-cleanroom/**

Super Mario 64 built from the [n64decomp](https://github.com/n64decomp/sm64) /
[sm64-port](https://github.com/sm64-port/sm64-port) source for the browser (Emscripten + WebGL),
with **every asset the decomp normally extracts from a ROM regenerated**: textures, fonts,
HUD icons, instrument and sound-effect samples. No ROM is needed to build or play it.

Controls: `W A S D` move · `L` A (jump) · `,` B (punch) · `K` Z · `Space` Start ·
arrow keys C buttons · `Right Shift` R · gamepads work too. Saves are kept in the browser.

## What is kept, what is generated

The decomp is already source code (level geometry, collision, behaviours, text). Its
`extract_assets.py` pulls the remaining binary assets from a ROM. This project reads the
ROM **once, in a "dirty room" step** (`extract_spec.py`), keeps only coarse facts, and
builds every asset from those facts:

| Asset (count) | Kept fact | Generated |
|---|---|---|
| Textures (1278) | format, size, a 4×4 colour grid (16×16 for skyboxes), a 2-bit alpha outline | colour from the grid plus our own noise detail |
| Fonts, HUD glyphs, icons (297) | cell size; character from the decomp's symbol names / charmap | drawn with an original stroke font and simple shapes |
| Text-bearing textures | the words (as in the decomp's text) | re-typeset (`text_labels.json`) |
| Mario's eyes and cap emblem (12) | alpha outline | drawn procedurally (`drawn.py`) |
| Other faces: eyes, mouths, whole faces (106) | alpha outline where kept | painted from our own written descriptions (`face_briefs.json`, `facepaint.py`) |
| Castle paintings, portraits, stained glass, star door, power meter | kept outlines where present | paintings are renders of each level's own geometry with our textures (`level_render.py`, `paintings.py`); portraits/glass/door/meter drawn from our own descriptions |
| Voices: Mario and Peach (47 lines + 3 snores) | length, rate, the words, one median-pitch number per line | performed by the project author against practice tracks, cut automatically (`takes.py`), then a studio chain (`voicefx.py`): noise reduction, de-essing, WORLD-vocoder pitch/formant/timing change toward the line's pitch level, EQ toward the line's coarse band outline, compression, level match. No original audio is used. (Earlier TTS voices: `voices.py`.) |
| Other samples (169) | length, rate, loop points, a coarse spectral outline | resynthesised; our own 2-predictor VADPCM codebooks (bank sizes match the game's fixed audio pools) |
| Music (m64 sequences) | the note events (user scope: melodies kept) | played by the resynthesised instruments |
| Attract-mode demos | button inputs | — |

`taint_report.py` scans every generated texture (RGBA) and sample (PCM) against the retail
extraction for shared byte runs of 32 bytes or more: **0 failing**.

## Build (Windows, Git Bash)

Needs Python 3 with numpy, GNU make, [Zig](https://ziglang.org) (host C compiler), an LLVM
release (clang/llvm-objcopy for data-only assembly) and emsdk. `winbin/` holds the small
shims (`gcc`→zig, `as`→clang, `objcopy`, `hexdump`, `python3`); edit their paths and put the
directory first on `PATH`.

```sh
# dirty room, once: needs your own ROM, never published
git clone https://github.com/sm64-port/sm64-port sm64_dirty    # clone with core.autocrlf=false
cp baserom.us.z64 sm64_dirty/ && (cd sm64_dirty && python extract_assets.py us)
python -m games.sm64.extract_spec sm64_dirty                    # -> games/sm64/spec

# clean room: from the spec only
git clone -c core.autocrlf=false https://github.com/sm64-port/sm64-port sm64-port
python -m games.sm64.generate sm64-port sm64_clean              # assets into a clean tree
games/sm64/build_web.sh sm64_clean                              # patches + make TARGET_WEB=1
games/sm64/make_site.sh sm64_clean site                         # index.html + js + wasm
python -m games.sm64.taint_report sm64_dirty sm64_clean         # optional check
```

`port_patches.py` lists every source change: emscripten 6 flags, a response-file link,
`em++` for C++, GLSL ES shaders for WebGL, `requestAnimationFrame` pacing, and one upstream
out-of-bounds loop that clang turns into a hang.

Dev tools: `shots.sh` (headless contact sheet with scripted key presses),
`font_check.py`, `find_text.py`, `ports/wasm/cdp_stack.py` (pauses a hung page, prints the wasm stack).

## Legal note

This repository contains no ROM data other than the kept facts above (in `games/sm64/spec`).
All textures, fonts, icons and samples are generated. The game code is the community
decompilation. Super Mario 64 is a trademark of Nintendo; this project is not affiliated
with Nintendo.
