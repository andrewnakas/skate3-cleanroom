# Lessons from Pilotwings 64: the reusable harness for the next game

These are things we learned the hard way on PW64. Each one is either a reusable harness piece or a check that would have saved days.

## 1. Pipeline shape (keep it)

```
dirty room      extract_spec.py  ROM -> spec/ (facts + coarse digests + label text)
clean room      generate.py      spec/ + overrides/ -> IR -> bytes
                pack.py          fixed segment reservations -> clean image
checks          taint scan, round-trip tests, in-game capture
code            decomp built natively (IDO passes), clean asm for hasm, splat on a synthetic ROM
runtime         N64Recomp ELF mode + audio HLE + RT64 GBI override
```

**Reserve the segments.** Give every segment (filetable, filesys, audio seq/ctl/tbl) a fixed size. Asset rebuilds then never move code, and the recompiled exe stays valid. An asset iteration becomes a roughly 3-minute image build, not a 40-minute exe build.

## 2. Format facts that bite on every N64 game (check these first)

| Trap | Symptom | Harness check |
|---|---|---|
| **TMEM odd-row swizzle.** LoadBlock with dxt=0 stores odd rows with the 32-bit halves of each 64-bit word swapped (all 463 PW64 textures). | Zig-zag shimmer on every texture; label text looks scrambled when dumped. | `texlayout.swizzle` in both extractor and generator. Scan the dlist for `G_LOADBLOCK` dxt. |
| **Blits stored tile by tile** (bands of tile_h rows, tiles contiguous). | HUD panels sheared or garbled. | `misc.blit_detile`/`blit_retile`. |
| **Upside-down UI textures** (sprites drawn with flipped t). | Text upside down. | A `flip` fact per label. |
| **Fonts with unit glyphs.** A wide `k` cell holds "km/h"; `m` means metres. | Units render as one letter or a block. | Compare cell width to height; find special cells by aspect. |
| **VADPCM output keeps 16 history samples** before the decoded data. | Clicks and pitch errors. | HLE ADPCM writes history, then data at out+32. |
| **RT64 identifies the GBI by hashing ucode text.** | Black screen with clean ucode. | Override by text address. |
| **Library asm the runtime doesn't replace** (bcopy/bzero/sqrtf recompiled from game code). | Crash in math and memory helpers. | Clean asm plus unicorn tests. |
| **Undocumented chunk types** | Silent misbehaviour. | Byte-exact round-trip of every file before generating anything. |

## 3. What the user cares about (priorities that emerged)

1. **Nothing may be unreadable.** Text baked into textures and blits was the most visible failure. The dirty room should find every text-bearing asset early:
   - scan small, high-contrast textures and all blits;
   - dump them (after unswizzle, detile and flip) to a contact sheet;
   - transcribe them into `hud_labels.json` / `tex_labels.json`.
2. **Transparency and silhouettes matter more than texel detail.** A 2-bit alpha outline plus a 4x4 colour grid reads as "the same game". Flat colour without alpha reads as "broken".
3. **Audio engine correctness before audio content.** The dev comparison harness (clean HLE vs retail microcode, per command, per task) found the ADPCM bug in minutes, after hours of listening.

## 4. Speeding up asset generation (next steps)

### Briefs → local image generation → overrides (built)
- `python -m cleanroom briefs pilotwings64` writes `work/briefs/<id>/` for each slot:
  - `brief.json`: role (terrain/model/cutout/ui/hud-text), per-region size, format, alpha, wrap modes, colour words and a prompt;
  - `guide.png`: the coarse colour layout at slot size;
  - `mask.png`: the alpha outline.
- **Local model.** Feed a local model such as SDXL/Flux in ComfyUI or A1111:
  - img2img on `guide.png` at about 0.6–0.8 denoise, or ControlNet (tile/colour) with the brief's prompt;
  - `mask.png` as the alpha;
  - `tileable` → use a seamless/tiling node.
- **Import.** Drop results in `games/pilotwings64/overrides/textures/<id>.png` (any size), or `<id>_<k>.png` for extra regions. `generate.py` then:
  - resizes to the slot;
  - keeps the slot alpha if the PNG has none;
  - quantises to the slot format;
  - swizzles.
- **Batch order:**
  1. terrain (few textures, huge screen area);
  2. vehicle and pilot model textures;
  3. cutouts (trees, billboards);
  4. UI panels, portraits.
- **Clean-room note.** Only the coarse guide and the mask are derived from the ROM. Keep generation prompts and seeds in the brief so every output is reproducible and auditable, and never feed retail images into the model.

### More harness pieces worth building
- **`cleanroom/find_text.py`** (dirty room): rank textures and blits by an "is it text" score and emit the contact sheet automatically, so the labelling pass takes minutes.
- **Offline render check.** Render UI assets and composed font strings to PNGs (`prevlabels.py`/`prevfont.py`). This avoids screen capture of a real desktop, which grabs whatever window is on top.
- **An in-game capture that doesn't need the desktop.** Add a runtime hook to dump RT64 frames to PNG on a frame counter, driven by the input scripts. This allows fully unattended A/B screenshots of retail vs clean in the dev build.
- **Audio briefs.** Mirror the texture briefs: per-sample descriptors to text prompts ("short metallic click, 0.2 s, bright"). Feed a local audio model, then import WAVs into `overrides/sounds/<bank>/<wave>.wav` (VADPCM encoder already exists).
- **Model briefs.** Part hierarchy plus bounding boxes plus kept geometry as a glTF export, for re-texturing or remodelling in Blender. Re-import is checked against the slot's vertex budget and joint layout.
- **Per-game profile contract.** Everything game-specific lives in `games/<game>/`:
  - layout;
  - codecs;
  - extractor allowlist;
  - label tables;
  - brief roles.

  The next target should start by filling `profile.py`, running round-trip tests, then the text finder.
