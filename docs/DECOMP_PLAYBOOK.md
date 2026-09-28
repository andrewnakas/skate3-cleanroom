# Decomp clean-room playbook (from Pilotwings 64 + Super Mario 64)

Goal per game: a **playable web build with no ROM data except user-approved
facts**. Every asset the decomp would extract from a ROM is regenerated.
Tokens go to decisions and hard problems; everything repeatable is a script
that prints a one-screen summary.

## 0. Rules (non-negotiable)

- **Dirty room vs clean room.** Only `extract_spec`-style scripts (and dev A/B builds) read the retail ROM or its extracted files. Clean outputs come from `spec/` + our code. Dirty trees, dev builds and practice clips are **never** published or committed.
- **Kept facts only by user scope**: geometry/collision/behaviour code already in the decomp, texture format + size + 4x4 colour grid + 2-bit alpha outline, sample length/rate/loops + coarse spectral outline + median pitch, note sequences, text (as in the decomp), demo inputs. Anything else must be generated.
- **No voice cloning** of real performers and no model trained on retail audio. Voices = TTS character voices (placeholder) or the user's own recordings (practice pack -> takes -> voicefx).
- **Taint scan must print 0 failing** before publishing (`cleanroom.decomp.taint`).
- The user drives with a controller and reports. Launch the game only when asked; verify with headless shots.

## 1. Pipeline (commands; read only the summaries)

| Step | Command | Read |
|---|---|---|
| Toolchain | `tools/setup_winbin.sh` (gcc/g++ -> zig, as -> clang, objcopy, hexdump, python3, make) | "ok" |
| Clone | `git clone -c core.autocrlf=false -c core.eol=lf <decomp> pristine` (**always LF**) | - |
| Dirty extract | copy pristine -> dirty, add baserom, run the decomp's own extractor | tail of log |
| Census | `python -m cleanroom.decomp.census pristine dirty spec_census.json` | counts per kind |
| Spec | `python -m cleanroom.decomp.spec dirty census.json games/<g>/spec --keep <approved patterns>` | textures/samples/kept/**unhandled** |
| Round-trip | decomp's own build on the dirty tree must match (sha1) before anything else | OK/mismatch |
| Generate | `games/<g>/generate.py` = `cleanroom.decomp.gen.write_all(..., texture_hook, sample_hook)` into a copy of pristine | counts |
| Build | decomp build (N64 ROM) and/or web port build; patch lists in `port_patches.py` | unique errors |
| Taint | `python -m cleanroom.decomp.taint dirty clean games/<g>/spec` | 0 failing |
| Look | `ports/wasm/headless_shot.py ... --webgl` + one contact sheet; `ports/wasm/cdp_stack.py` for hangs | one image |
| Publish | new repo `andrewnakas/<g>-cleanroom` + gh-pages site | Pages "built" |

## 2. Traps (check these first; each cost hours once)

**Environment**
- CRLF clones break patches, heredocs and shell scripts: clone with `core.autocrlf=false core.eol=lf`. Edit Python with the Edit tool, not sed/heredocs containing `\n`.
- Windows command line limit (32 KB): link from a response file (`$(file >...)` in make).
- A tool that was missing on the first build leaves **0-byte outputs** that make treats as up to date: after fixing, `find build -size 0 -delete`, and delete objects that include them.
- Headless browser **caches the wasm**: headless_shot wipes its profile per run. WebGL pages need `--webgl` (SwiftShader).
- A hang with no output: `ports/wasm/cdp_stack.py <url> --webgl` pauses the page and prints the wasm stack (link with `--profiling-funcs`). SM64 had an upstream out-of-bounds loop that clang -O2 turned into an infinite loop.
- E: is nearly full: build on C:\Users\andre\n64work.

**Formats**
- TMEM odd-row swizzle for LoadBlock dxt=0 textures; UI blits stored tile by tile; some UI textures stored upside down (PW64).
- **Glyph storage**: check the draw path (vertex UVs / texrect flip). SM64 US dialog glyphs are 16x8 stored, drawn rotated: `glyphs.store(img, "transpose_flip")`.
- **Symbol names lie**: map font glyphs through the game's LUT + charmap (SM64 code 0x9F named "slash" is '-').
- **Alpha depth**: IA4/I4/IA1 fonts keep 1 bit of alpha: thin (~1 px) strokes and a 0.5 threshold, verify with a font_check that simulates it.
- Unit glyphs in fonts (PW64 "km/h" cell).
- **Audio pool sizes are fixed**: VADPCM books must stay 2 predictors (retail size) or sound banks outgrow their pools and audio dies mid-game. Check `sound_data.ctl` (or equivalent) size == retail.
- Sequences built from `.s` must be byte-identical to retail (compare once, dev only).
- Descriptor f0 has octave errors: use the spec's `f0` (YIN median) for pitch targets.

**What the user notices first (fix in this order)**
1. Anything unreadable: text in textures, fonts, HUD, dialog. Find text-bearing textures early (`find_text`, symbol names, contact sheet) and re-typeset them (`glyphs.label_texture`).
2. Faces: eyes/mouths turn to mush in a 4x4 grid. List them by name (eye|face|mouth|...), look once at a dirty contact sheet, write `face_briefs.json`, render with `cleanroom.gfx.facepaint`, compare side by side.
3. Pictures/illustrations (paintings, portraits, stained glass, title art, sprites): render them from the game's own geometry (`cleanroom.gfx.c_render`) or draw briefs; stained glass = palette panes + lead lines.
4. HUD widgets with meaning (power meter slices, health, counters): draw procedurally, per state.
5. Silhouettes/transparency (kept alpha) matter more than texel detail.
6. Audio engine correctness before content (bank sizes, sequences, samples play at all).
7. Voices: placeholder TTS (Piper, pitch lift via slow-speak + resample, best of 6 takes by Whisper). The user records real takes in the morning: build the practice pack (`cleanroom.voice.practice`) and leave `takes`/`voicefx` ready.

## 3. Shared library map

| Module | Use |
|---|---|
| `cleanroom.decomp.census / spec / gen / taint` | asset census, dirty spec, generation (textures, AIFF/AIFC/WAV with 2-predictor books), taint |
| `cleanroom.gfx.glyphs` | stroke-font glyphs (white/hud/ink), icons (coin, star, head, camera, arrows), buttons, `label_texture`, `store`, `one_bit` |
| `cleanroom.gfx.facepaint` | primitive painter + briefs (`eye` macro, spheres, arcs, polys, outline from kept alpha) |
| `cleanroom.gfx.c_render` | perspective textured render of Vtx/Gfx display lists from decomp C (paintings, portraits, icons) |
| `cleanroom.gfx.strokefont / png / texfmt / raster` | primitives |
| `cleanroom.audio.descriptor / vadpcm / pitch` | outline + resynthesis, VADPCM codec, YIN pitch |
| `cleanroom.voice.voices / practice / takes / voicefx` | TTS placeholders, practice pack, cut recordings, WORLD studio chain |
| `ports/wasm/headless_shot.py, cdp_stack.py, serve.py` | headless screenshots/keys/audio log, hang stacks, local server |
| `ports/web/shell.html` | page template with dev hooks: `?dump=5,10`, `?keys=t:Code:dur`, `?audiolog=1`, `?hb=1` |

## 4. Web route (decide in the first hour)

1. **PC port exists with an Emscripten target** (SM64: sm64-port): build it with clean assets. Fastest, best fps.
2. **PC port without web target** (OoT: Ship of Harkinian, MK64: SpaghettiKart): usually heavy (C++/ImGui/LUS). Only if its web build is realistic.
3. **Clean N64 ROM + N64 emulator in WASM** (works for any matching decomp): build the decomp with clean assets to a ROM, ship it with a WASM N64 core (for example a mupen64plus-next/ParaLLEl based web build; check its license and that it runs headless). Default for games without a web-ready port.
4. N64Recomp + `ports/wasm` software RDP (PW64 route): only if 1-3 fail.

## 5. Token discipline

- Background every long job; wait for the notification. Never poll with sleeps.
- One contact sheet per question; never open images one by one.
- Scripts print summaries; never cat JSON/logs; `grep -c`, `sed -n a,bp`.
- Fixes go into patch lists / JSON briefs, not hand edits of generated trees.
- Use subagents for independent mechanical batches, not for decisions.
