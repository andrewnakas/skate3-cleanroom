"""Skate 3 player sounds for the web build, regenerated from coarse outlines.

Dirty room (reads decoded retail PCM, writes only descriptors):
    python -m games.skate3.audio_clean describe <pcm dump dir> <spec dir>
  The dump comes from the engine's `dump_player_pcm` example (one WAV per bank
  sample and grain, plus index.json). For each role below a source is chosen by
  its bank and coarse statistics, and reduced to `cleanroom.audio.descriptor`
  frames (f0, harmonicity, 16-band dB envelope, RMS). Nothing else is kept.

Clean room (reads only the spec):
    python -m games.skate3.audio_clean build <spec dir> <clean assets dir>
  Writes <assets>/clean-audio/<role>.wav (mono 16-bit, 24 kHz) and sounds.json.

Check:
    python -m games.skate3.audio_clean taint <pcm dump dir> <clean assets dir>
  Every clean WAV's PCM against every retail sample's PCM; runs >= FAIL_RUN fail.
No music and no speech: none of the banks used are music or voice banks.
"""
import json
import os
import struct
import sys
import wave

import numpy as np

from cleanroom import taint
from cleanroom.audio import descriptor

RATE = 24000

# role: (source filter, pick rule, seconds, loop, variants, gain)
ROLES = {
    "roll_smooth": ("grains/concrete_smooth_hard.grain", "longest", 1.6, True, 1, 0.9),
    "roll_rough": ("grains/asphalt_rough_hard.grain", "longest", 1.6, True, 1, 0.9),
    "roll_wood": ("grains/wood_ramp_hard.grain", "longest", 1.6, True, 1, 0.9),
    "roll_metal": ("grains/metal_smooth_hard.grain", "longest", 1.6, True, 1, 0.9),
    "grind_metal": ("GRINDS", "long_bright", 1.4, True, 1, 0.8),
    "grind_concrete": ("GRINDS", "long_dark", 1.4, True, 1, 0.8),
    "powerslide": ("WHEEL_SKID_BANK", "longest", 1.0, True, 1, 0.7),
    "pop": ("Skate_Collisions", "short_bright", 0.25, False, 3, 1.0),
    "land": ("Skate_Collisions", "short_dark", 0.45, False, 3, 1.0),
    "land_hard": ("Skate_Collisions", "loud_long", 0.7, False, 2, 1.0),
    "bail": ("HOM_Set_1", "loud_long", 0.8, False, 2, 1.0),
    "footstep": ("fstep_skateshoe1_sm", "short_dark", 0.25, False, 4, 0.8),
    "push": ("FOOT_DRAG", "short_dark", 0.35, False, 2, 0.7),
    "flip": ("Sk8_Air_Flip_Tricks", "short_bright", 0.35, False, 3, 0.7),
    "chime": ("sk8_menu", "tonal", 0.5, False, 1, 0.6),
}


def _read_wav(path):
    with wave.open(path, "rb") as w:
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), "<i2").astype(np.float64)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def _stats(x, rate):
    a = x / 32768.0
    spec = np.abs(np.fft.rfft(a[: 1 << 15] * np.hanning(min(len(a), 1 << 15)))) ** 2
    f = np.fft.rfftfreq(min(len(a), 1 << 15), 1.0 / rate)
    centroid = float((spec * f).sum() / (spec.sum() + 1e-12))
    rms = float(np.sqrt((a ** 2).mean()) + 1e-9)
    return {"sec": len(a) / rate, "rms": rms, "centroid": centroid}


def _pick(cands, rule, count):
    """cands: list of (entry, stats). Returns up to `count` entries."""
    if rule == "longest":
        order = sorted(cands, key=lambda c: -c[1]["sec"])
    elif rule in ("long_bright", "long_dark"):
        longish = sorted(cands, key=lambda c: -c[1]["sec"])[: max(6, len(cands) // 4)]
        order = sorted(longish, key=lambda c: -c[1]["centroid"] if rule == "long_bright" else c[1]["centroid"])
    elif rule in ("short_bright", "short_dark"):
        short = [c for c in cands if 0.05 <= c[1]["sec"] <= 0.8 and c[1]["rms"] > 0.02] or cands
        order = sorted(short, key=lambda c: -c[1]["centroid"] if rule == "short_bright" else c[1]["centroid"])
    elif rule == "loud_long":
        order = sorted(cands, key=lambda c: -(c[1]["rms"] * min(c[1]["sec"], 1.5)))
    elif rule == "tonal":
        short = [c for c in cands if 0.1 <= c[1]["sec"] <= 1.5] or cands
        order = sorted(short, key=lambda c: -c[1].get("h", 0))
    else:
        raise ValueError(rule)
    return [c[0] for c in order[:count]]


def cmd_describe(dump, spec):
    index = json.load(open(os.path.join(dump, "index.json")))
    out = {"rate": RATE, "roles": {}}
    for role, (src, rule, sec, loop, variants, gain) in ROLES.items():
        if src.startswith("grains/"):
            cands = [e for e in index if e["file"] == src + ".wav"]
        else:
            cands = [e for e in index if e["bank"].split(".")[0] == src]
        if not cands:
            print(f"  {role}: no source in bank {src}, skipped")
            continue
        scored = []
        for e in cands:
            x, rate = _read_wav(os.path.join(dump, e["file"]))
            if len(x) < 64:
                continue
            st = _stats(x, rate)
            if rule == "tonal":
                d = descriptor.describe(x[: rate], rate)
                st["h"] = float(np.mean([f["h"] for f in d["frames"]] or [0]))
            scored.append((e, st))
        chosen = _pick(scored, rule, variants)
        descs = []
        for e in chosen:
            x, rate = _read_wav(os.path.join(dump, e["file"]))
            # Loops are described over their steady middle, one-shots from the start.
            if loop and len(x) > rate:
                mid = len(x) // 2
                x = x[max(0, mid - rate): mid + rate]
            descs.append(descriptor.describe(x, rate))
        out["roles"][role] = {"seconds": sec, "loop": loop, "gain": gain, "descriptors": descs}
        print(f"  {role}: {len(descs)} outline(s) from {src} ({rule})")
    os.makedirs(spec, exist_ok=True)
    with open(os.path.join(spec, "audio.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"describe: {len(out['roles'])} roles -> {os.path.join(spec, 'audio.json')}")


def _write_wav(path, x, rate, seed=0):
    # Dense +-2 LSB dither: quiet tails of any two sounds otherwise quantise to
    # the same few values, which the byte-run taint scan cannot tell from copying.
    d = np.random.default_rng(seed).integers(-2, 3, len(x))
    pcm = np.clip(np.round(np.clip(x, -1, 1) * 32000) + d, -32768, 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def _render(desc, sec, loop, seed):
    n = int(sec * RATE)
    if loop:
        xf = RATE // 8
        x = descriptor.synthesize(desc, n + xf, RATE, seed=seed)
        x = descriptor.make_loop_seamless(x, xf, n + xf, xfade=xf)[xf:n + xf]
    else:
        x = descriptor.synthesize(desc, n, RATE, seed=seed)
        # One-shots decay to silence so they never end on a step.
        tail = min(n, RATE // 20)
        x[-tail:] *= np.linspace(1, 0, tail)
    peak = float(np.max(np.abs(x))) or 1.0
    return (x / peak * 0.9).astype(np.float32)


def cmd_build(spec, assets):
    s = json.load(open(os.path.join(spec, "audio.json")))
    out_dir = os.path.join(assets, "clean-audio")
    os.makedirs(out_dir, exist_ok=True)
    sounds = {}
    for role, r in s["roles"].items():
        for i, desc in enumerate(r["descriptors"]):
            name = role if len(r["descriptors"]) == 1 else f"{role}_{i + 1}"
            seed = sum(map(ord, name)) * 131 + i
            x = _render(desc, r["seconds"], r["loop"], seed)
            _write_wav(os.path.join(out_dir, name + ".wav"), x, RATE, seed)
            sounds[name] = {"file": name + ".wav", "loop": r["loop"], "gain": r["gain"]}
    with open(os.path.join(out_dir, "sounds.json"), "w") as f:
        json.dump({"rate": RATE, "sounds": sounds}, f, indent=1)
    total = sum(os.path.getsize(os.path.join(out_dir, v["file"])) for v in sounds.values())
    print(f"build: {len(sounds)} clean sounds, {total // 1024} KB -> {out_dir}")


def cmd_taint(dump, assets):
    index = json.load(open(os.path.join(dump, "index.json")))
    streams = []
    for e in index:
        with wave.open(os.path.join(dump, e["file"]), "rb") as w:
            streams.append(w.readframes(w.getnframes()))
    idx = taint.build_index(streams)
    streams = None
    d = os.path.join(assets, "clean-audio")
    clean = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".wav"):
            with wave.open(os.path.join(d, f), "rb") as w:
                clean.append((f, w.readframes(w.getnframes())))
    hits = taint.scan(idx, clean)
    bad = [h for h in hits if h[3] >= taint.FAIL_RUN]
    print(f"audio taint: {len(clean)} clean sounds vs {len(index)} retail samples; "
          f"{len(hits)} with short coincidental windows; {len(bad)} failing (run >= {taint.FAIL_RUN} B)")
    for label, off, n, run in bad[:8]:
        print(f"  FAIL {label} run {run} B")
    return 1 if bad else 0


def main(argv):
    if len(argv) != 4 or argv[1] not in ("describe", "build", "taint"):
        print(__doc__)
        return 2
    return {"describe": cmd_describe, "build": cmd_build, "taint": cmd_taint}[argv[1]](argv[2], argv[3]) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
