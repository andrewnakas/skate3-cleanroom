# Playbook: the next game (first up: Super Mario 64)

**Principle:** tokens go to *decisions, coordination and hard problems*. Everything repeatable is a script that prints a **one-screen summary**, and the model reads summaries, not data.

## 0. Token discipline

| Do | Don't |
|---|---|
| Run long jobs (`build`, `extract`, `pytest`, `emcc`, headless runs) in the background and wait for the notification. | Poll or re-run to "check". |
| Have every tool print a short summary: counts, pass/fail, the worst five. | Cat JSON, specs or logs into the context. |
| Look at **one contact sheet** (`find_text.contact_sheet`, `headless_shot.py`, preview sheets). | Open images one by one. |
| Put fixes into scripts and patch lists (`setup_port.py` PATCHES, label JSON, config JSON). | Hand-edit generated or copied trees. |
| Write edit scripts with the Write tool, then run them. | Run `python - <<EOF` with C strings containing `\n` (it broke several times; the heredoc turns `\n` into a real newline). |
| Use `rg`/`grep -c` for counts, and `sed -n a,bp` for the exact lines needed. | Read whole large files. |
| Use one Agent or Workflow per independent mechanical batch (per-asset classes). | Spawn agents for decisions. |

## 1. Mechanical pipeline (scripts; model reads only the summaries)

| Step | Tool | Summary the model reads |
|---|---|---|
| Unpack ROM, verify CRC | `cleanroom/rom.py`, `codec/*` | size, CRC ok |
| Asset census | new `games/<g>/profile.py` + `extract_spec.py` | counts per asset type |
| Round-trip every format | `tests/test_<g>_retail.py` | n files byte-identical |
| Spec (dirty room) | `python -m cleanroom extract <g> <rom>` | files written, per-type provenance counts |
| Text finder | `find_text.py` | `sheet.png` (one look), then hand-transcribe labels to JSON |
| Generate + pack | `python -m cleanroom build <g>` | image size, segment fits |
| Taint | `taint_report` | failing count, worst run |
| Briefs for image generation | `python -m cleanroom briefs <g>` | n briefs |
| Web port | `ports/wasm/*` (reuse) | build errors (unique, counted), headless states + fps |
| Visual check | `headless_shot.py --query script=...` | one sheet of 6 frames |

## 2. Hard parts (where the model's attention goes)

- **Scope decisions** with the user: what counts as a kept fact versus regenerated.
- **Format traps** (see HARNESS.md §2). On a new game, check these first:
  - TMEM swizzle;
  - tiled or flipped UI;
  - unit glyphs in fonts;
  - coverage-bit effects such as the shadow columns;
  - 32-bit `size_t` in runtime code for the web.
- **Renderer semantics** when a frame looks wrong. Trace the render state with a one-shot filtered print; never dump full display lists.
- **Audio correctness** against the retail microcode (dev comparison harness), before judging content.
- **Integration**: tying the stages together and keeping the clean-room boundary: no retail bytes in outputs, dev images never shared.

## 3. Super Mario 64: what's different, and the plan

The SM64 decomp (`n64decomp/sm64`) is **already a source build**:
- Level geometry, collision, behaviours and object placements are C in the repo.
- `extract_assets.py` pulls only the **binary assets** from the ROM:
  - textures, as PNGs under `textures/`, `actors/` and `levels/`;
  - sound samples and banks (`sound/samples`, `sound/sound_banks`);
  - sequences (`sound/sequences`);
  - the text, skybox and some binary blobs.

So for SM64 the clean room is mostly **"regenerate what `extract_assets.py` writes"**:

1. **Census (mechanical).**
   - Run the decomp's extractor once in the dirty room, and list every extracted file with its type, size and format (from the filename, e.g. `.rgba16.png`, `.ia8.png`).
   - That list *is* the slot spec.
   - Keep per-texture coarse digests (grid plus alpha outline), like PW64.
2. **Textures (mechanical + optional image generation).**
   - Generate each PNG at its slot size and format from the digest (reuse `generate._from_digest` logic and `texfmt`).
   - Briefs and overrides work the same way as PW64, so a local SD/Flux model fills them.
3. **Text / HUD / fonts.**
   - Run `find_text` on the extracted textures.
   - The font glyphs (HUD numbers, dialog font) come from `strokefont`.
   - Dialog text is in the decomp as C (`text/us/*.h`); check the licensing and scope with the user.
4. **Audio.**
   - Samples: descriptors, then resynthesis, then VADPCM (`descriptor.py`, `vadpcm.py`), with bank structure kept.
   - Sequences: keep the note events (user scope) or compose new ones. `cseq`/m64 differ: SM64 uses its own sequence format (m64), which needs a codec plus a round-trip test first.
5. **Build.** The decomp builds natively (reuse the IDO toolchain from PW64: `tools/idowin`). No N64Recomp is needed for a web version: an SM64 **PC or web port** already exists in the community (sm64-port / sm64ex, with an Emscripten target). Point it at the clean assets instead of retail. Alternatively, reuse `ports/wasm` if we go the N64Recomp route. Decide with the user.
6. **Taint scan** over every generated asset against retail. Same `cleanroom/taint.py`.
7. **Web publish** with `make_site.py`-style packaging, `coi-sw.js` only if threads are used, and GitHub Pages.

## 4. Session checklist (copy into the first message of the next session)

1. `profile.py` for SM64. Round-trip or census, with summary only.
2. Scope questions to the user, answered in one question batch.
3. Build the extract → generate → pack/assets → taint scripts, and run them in the background.
4. Build the game with the clean assets, then run it headless (desktop or web) and look at one contact sheet.
5. Fix only what the sheet or summary shows. Commit, and push to a new repo if the user wants.

## 5. SM64 outcome (2026-09-24) and lessons

Done: https://andrewnakas.github.io/sm64-cleanroom/ (repo andrewnakas/sm64-cleanroom, exported from `games/sm64` by `export_repo.sh`). Route: sm64-port + Emscripten; ~0 game-code changes (`port_patches.py`). Pipeline: `extract_spec` (dirty) → `generate` → `build_web.sh` → `make_site.sh` → `shots.sh` / `taint_report` (0 failing).

Traps worth checking first next time:
- **Clone with `-c core.autocrlf=false -c core.eol=lf`**; repos with `* text=auto` otherwise get CRLF and every patch/heredoc breaks. Write Python edits to files (Edit tool), never through sed/heredoc with `\n`.
- **Headless browser caches the wasm** across runs: `headless_shot.py` now wipes its profile. WebGL pages need `--webgl` (SwiftShader).
- **A hang with no console output**: `ports/wasm/cdp_stack.py` pauses the page and prints the wasm stack (build with `--profiling-funcs`). Found an upstream out-of-bounds loop that clang -O2 turned into an infinite loop.
- **Make keeps empty outputs** from a failed first run (missing `hexdump` produced 0-byte `.inc.c`): after fixing a tool, delete zero-size generated files.
- **Symbol names can lie**: map font glyphs through the game's LUT + charmap (code 0x9F "slash" is the text's '-').
- **Check the draw path for glyph orientation** (SM64 US dialog glyphs are stored 16×8, drawn rotated via vertex UVs) and alpha depth (ia4 = 1-bit alpha: thin ~1 px strokes, threshold at 0.5; `font_check.py` simulates it).
- Coarse grids erase faces: draw eyes/emblems inside the kept alpha outline (`drawn.py`).
