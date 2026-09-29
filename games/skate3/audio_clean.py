"""Skate 3 player sounds for the web build, regenerated from coarse facts.

Dirty room (reads decoded retail PCM, writes only descriptors):
    python -m games.skate3.audio_clean describe <pcm dump dir> <spec dir>
  The dump comes from the engine's `dump_player_pcm` example (one WAV per bank
  sample and grain, plus index.json). Each role below names its source (an
  exact bank sample where the engine documents it, e.g. the landing impact
  `Skate_Collisions` 0x447 and ladder 0x35C/0x35D, otherwise a pick by coarse
  statistics) and keeps only a few dozen numbers of it:
    one-shots: length, overall level, a 64-step loudness envelope, up to 8
               resonant modes (frequency, level, decay rate), a 24-band noise
               spectrum at attack/body/tail, and the tone/noise balance;
    loops:     overall level, a 32-band average spectrum, up to 6 steady tones
               (frequency, level) and the loudness-flutter spectrum (4 bands).

Clean room (reads only the spec):
    python -m games.skate3.audio_clean build <spec dir> <clean assets dir>
  One-shots become decaying sinusoids plus shaped noise under the envelope;
  loops become circular shaped noise with the tones and flutter (seamless by
  construction). Writes <assets>/clean-audio/<role>.wav (mono 16-bit, 32 kHz)
  and sounds.json, keeping the sources' relative levels.

Check:
    python -m games.skate3.audio_clean taint <pcm dump dir> <clean assets dir>
No music and no speech: none of the banks used are music or voice banks.
"""
import json
import os
import sys
import wave

import numpy as np

from cleanroom import taint

RATE = 32000
LOG = np.log(10) / 20

# role: (source, rule, variants, kind, gain)
#   source "Bank#index" = that exact sample; "grains/<member>" = that grain;
#   "Bank" = pick `variants` samples of the bank by `rule`.
ROLES = {
    "roll_smooth": ("grains/concrete_smooth_hard.grain", None, 1, "loop", 1.0),
    "roll_rough": ("grains/asphalt_rough_hard.grain", None, 1, "loop", 1.0),
    "roll_wood": ("grains/wood_ramp_hard.grain", None, 1, "loop", 1.0),
    "roll_metal": ("grains/metal_smooth_hard.grain", None, 1, "loop", 1.0),
    "grind_metal": ("GRINDS", "long_bright", 1, "loop", 1.0),
    "grind_concrete": ("GRINDS", "long_dark", 1, "loop", 1.0),
    "powerslide": ("WHEEL_SKID_BANK", "longest", 1, "loop", 1.0),
    # Landing = the fixed impact plus one ladder layer (soft / hard by air time),
    # as the engine's LandingTuning documents (sample, ladder[0]).
    "land_impact": ("Skate_Collisions#1095", None, 1, "oneshot", 1.0),
    "land_soft": ("Skate_Collisions#860", None, 1, "oneshot", 1.0),
    "land_hard": ("Skate_Collisions#861", None, 1, "oneshot", 1.0),
    "pop": ("Skate_Collisions", "short_bright", 3, "oneshot", 1.0),
    "bail": ("HOM_Set_1", "loud_long", 2, "oneshot", 1.0),
    "footstep": ("fstep_skateshoe1_sm", "short_dark", 4, "oneshot", 1.0),
    "push": ("FOOT_DRAG", "short_dark", 2, "oneshot", 1.0),
    "flip": ("Sk8_Air_Flip_Tricks", "short_bright", 3, "oneshot", 1.0),
    "chime": ("sk8_menu", "tonal", 1, "oneshot", 1.0),
}


def _read_wav(path):
    with wave.open(path, "rb") as w:
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), "<i2").astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def _db(v, floor=-90):
    return int(max(floor, round(20 * np.log10(v + 1e-12))))


def _log_bands(lo, hi, n):
    edges = np.geomspace(lo, hi, n + 1)
    return edges, np.sqrt(edges[:-1] * edges[1:])


def _band_levels(power, freqs, edges):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (freqs >= lo) & (freqs < hi)
        out.append(_db(np.sqrt(power[m].mean()) if m.any() else 0.0))
    return out


def _peaks(mag_db, freqs, lo, hi, count, above):
    """Up to `count` local maxima standing `above` dB over a smoothed spectrum."""
    k = max(3, len(mag_db) // 200)
    smooth = np.convolve(mag_db, np.ones(k) / k, mode="same")
    cand = [i for i in range(1, len(mag_db) - 1)
            if lo <= freqs[i] <= hi and mag_db[i] >= mag_db[i - 1] and mag_db[i] >= mag_db[i + 1]
            and mag_db[i] - smooth[i] >= above]
    cand.sort(key=lambda i: -mag_db[i])
    chosen = []
    for i in cand:
        if all(abs(freqs[i] - freqs[j]) > max(30.0, 0.03 * freqs[i]) for j in chosen):
            chosen.append(i)
        if len(chosen) == count:
            break
    return chosen


# ---------------------------------------------------------------- one-shots

def describe_oneshot(x, rate):
    n = len(x)
    level = np.sqrt((x ** 2).mean())
    frames = np.array_split(x, 64) if n >= 64 else [x]
    env = [_db(np.sqrt((f ** 2).mean())) for f in frames]
    nfft = 1 << int(np.ceil(np.log2(max(n, 4096))))
    spec = np.abs(np.fft.rfft(x * np.hanning(n), nfft))
    freqs = np.fft.rfftfreq(nfft, 1.0 / rate)
    mag_db = 20 * np.log10(spec + 1e-12)
    modes = []
    hop = 128
    peaks = _peaks(mag_db, freqs, 60, min(15000, rate / 2 - 500), 8, 6.0)
    for i in peaks:
        f = freqs[i]
        # Decay: energy of this mode over time in short frames (Goertzel-like).
        win = 512
        t = np.arange(win) / rate
        probe = np.exp(-2j * np.pi * f * t) * np.hanning(win)
        lv = []
        for s in range(0, max(1, n - win), hop):
            seg = x[s:s + win]
            if len(seg) < win:
                break
            lv.append(20 * np.log10(abs((seg * probe).sum()) + 1e-12))
        lv = np.array(lv)
        if len(lv) >= 3:
            top = int(lv.argmax())
            tail = lv[top:]
            tt = np.arange(len(tail)) * hop / rate
            slope = np.polyfit(tt, tail, 1)[0] if len(tail) >= 3 else -60.0 / (n / rate)
        else:
            slope = -60.0 / (n / rate)
        modes.append([int(round(f)), int(round(mag_db[i] - mag_db.max())), int(round(min(-5.0, slope)))])
    edges, _ = _log_bands(40, min(16000, rate / 2), 24)
    parts = np.array_split(x, [max(1, n // 10), max(2, n // 2)])
    noise = []
    for p in parts:
        if len(p) < 32:
            p = x
        sp = np.abs(np.fft.rfft(p * np.hanning(len(p)))) ** 2
        noise.append(_band_levels(sp, np.fft.rfftfreq(len(p), 1.0 / rate), edges))
    power = spec ** 2
    width = max(2, nfft // 2048)  # a mode's main lobe, in bins
    tonal_energy = sum(power[max(0, i - width): i + width + 1].sum() for i in peaks)
    tone = float(np.clip(tonal_energy / (power.sum() + 1e-18), 0.0, 0.85))
    whole = _band_levels(np.abs(np.fft.rfft(x * np.hanning(n), nfft)) ** 2, freqs, edges)
    return {"kind": "oneshot", "seconds": round(n / rate, 4), "level": _db(level), "env": env,
            "modes": modes, "noise": noise, "spectrum": whole, "tone": round(tone, 2)}


def _shaped_noise(n, levels_db, edges, rate, rng):
    centers = np.sqrt(edges[:-1] * edges[1:])
    amp = 10 ** (np.asarray(levels_db, float) / 20)
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    gain = np.interp(np.log(np.maximum(freqs, 1.0)), np.log(centers), amp, left=amp[0], right=0.0)
    return np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) * gain, n)


def _norm(v):
    return v / (np.sqrt((v ** 2).mean()) + 1e-12)


def synth_oneshot(d, rng):
    n = max(64, int(round(d["seconds"] * RATE)))
    t = np.arange(n) / RATE
    modal = np.zeros(n)
    for f, lv, decay in d["modes"]:
        if f < RATE / 2 - 200:
            modal += 10 ** (lv / 20) * np.exp(decay * LOG * t) * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi))
    edges, _ = _log_bands(40, 16000, 24)
    # Attack / body / tail noise spectra, crossfaded over the length.
    shaped = [_shaped_noise(n, lv, edges, RATE, rng) for lv in d["noise"]]
    w = np.stack([np.interp(t, [0, 0.1 * t[-1], 0.5 * t[-1], t[-1]], c) for c in ([1, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1])])
    w[2] = np.maximum(w[2], 1 - w[0] - w[1])
    noise = sum(wi * _norm(si) for wi, si in zip(w, shaped))
    tone = d["tone"] if d["modes"] else 0.0
    x = tone * (_norm(modal) if modal.any() else 0) + (1 - tone) * _norm(noise)
    # Alternately equalise to the whole-sound 24-band spectrum and impose the
    # 64-step envelope; each disturbs the other a little, so iterate.
    k = len(d["env"])
    centres = (np.arange(k) + 0.5) * n / k
    target = np.interp(np.arange(n), centres, 10 ** (np.asarray(d["env"], float) / 20))
    nfft = 1 << int(np.ceil(np.log2(max(n, 4096))))
    f = np.fft.rfftfreq(nfft, 1.0 / RATE)
    centers = np.sqrt(edges[:-1] * edges[1:])
    for _ in range(4):
        if "spectrum" in d:
            X = np.fft.rfft(x, nfft)
            have = np.array(_band_levels(np.abs(X) ** 2, f, edges), float)
            want = np.array(d["spectrum"], float)
            corr = np.clip((want - want.max()) - (have - have.max()), -30, 30)
            g = 10 ** (np.interp(np.log(np.maximum(f, 1.0)), np.log(centers), corr) / 20)
            x = np.fft.irfft(X * g, nfft)[:n]
        frames = np.array_split(x, k)
        actual = np.interp(np.arange(n), centres, [np.sqrt((fr ** 2).mean()) + 1e-9 for fr in frames])
        x = x * target / actual
    tail = min(n // 8, RATE // 200)
    x[-tail:] *= np.linspace(1, 0, tail)
    return x


# ---------------------------------------------------------------- loops

def describe_loop(x, rate):
    seg = 4096
    level = np.sqrt((x ** 2).mean())
    frames = [x[i:i + seg] * np.hanning(seg) for i in range(0, len(x) - seg, seg // 2)] or [np.resize(x, seg)]
    power = np.mean([np.abs(np.fft.rfft(f)) ** 2 for f in frames], axis=0)
    freqs = np.fft.rfftfreq(seg, 1.0 / rate)
    edges, _ = _log_bands(30, min(16000, rate / 2), 32)
    bands = _band_levels(power, freqs, edges)
    mag_db = 10 * np.log10(power + 1e-18)
    tones = [[int(round(freqs[i])), int(round(mag_db[i] - mag_db.max()))]
             for i in _peaks(mag_db, freqs, 60, min(12000, rate / 2 - 500), 6, 10.0)]
    # Loudness flutter: 5 ms RMS envelope, its fluctuation spectrum in 4 bands.
    step = max(1, rate // 200)
    env = np.array([np.sqrt((x[i:i + step] ** 2).mean()) for i in range(0, len(x) - step, step)])
    depth = float(env.std() / (env.mean() + 1e-12)) if len(env) > 8 else 0.0
    mod = []
    if len(env) > 16:
        es = np.abs(np.fft.rfft((env - env.mean()) * np.hanning(len(env)))) ** 2
        ef = np.fft.rfftfreq(len(env), 1.0 / 200)
        mod = _band_levels(es, ef, np.array([1, 4, 12, 30, 80.0]))
    return {"kind": "loop", "level": _db(level), "bands": bands, "tones": tones,
            "flutter": {"depth": round(min(depth, 1.5), 2), "bands": mod}}


def synth_loop(d, seconds, rng):
    n = int(round(seconds * RATE))
    edges, _ = _log_bands(30, 16000, 32)
    freqs = np.fft.rfftfreq(n, 1.0 / RATE)
    centers = np.sqrt(edges[:-1] * edges[1:])
    amp = 10 ** (np.asarray(d["bands"], float) / 20)
    mag = np.interp(np.log(np.maximum(freqs, 1.0)), np.log(centers), amp, left=amp[0], right=0.0)
    # Random-phase spectrum -> circular noise: loops with no seam by construction.
    spec = mag * np.exp(2j * np.pi * rng.uniform(size=len(freqs)))
    spec[0] = 0
    x = _norm(np.fft.irfft(spec, n))
    t = np.arange(n) / RATE
    tonal = np.zeros(n)
    for f, lv in d["tones"]:
        fc = round(f * seconds) / seconds  # whole cycles per loop
        if fc < RATE / 2 - 200:
            tonal += 10 ** (lv / 20) * np.sin(2 * np.pi * fc * t + rng.uniform(0, 2 * np.pi))
    if d["tones"]:
        x = x + 0.5 * _norm(tonal) * min(1.0, sum(10 ** (lv / 20) for _, lv in d["tones"]))
    fl = d["flutter"]
    if fl["depth"] > 0.02 and fl["bands"]:
        mf = np.fft.rfftfreq(n, 1.0 / RATE)
        mamp = np.interp(mf, [2.5, 8, 21, 55], 10 ** (np.asarray(fl["bands"], float) / 20), left=0, right=0)
        m = np.fft.irfft(mamp * np.exp(2j * np.pi * rng.uniform(size=len(mf))), n)
        m = _norm(m) * fl["depth"] * 0.7
        x = x * np.clip(1 + m, 0.1, None)
    return x


# ---------------------------------------------------------------- commands

def _stats(x, rate):
    spec = np.abs(np.fft.rfft(x[: 1 << 15] * np.hanning(min(len(x), 1 << 15)))) ** 2
    f = np.fft.rfftfreq(min(len(x), 1 << 15), 1.0 / rate)
    return {"sec": len(x) / rate, "rms": float(np.sqrt((x ** 2).mean()) + 1e-9),
            "centroid": float((spec * f).sum() / (spec.sum() + 1e-12)),
            "flat": float(np.exp(np.log(spec + 1e-18).mean()) / (spec.mean() + 1e-18))}


def _pick(cands, rule, count):
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
        order = sorted(short, key=lambda c: c[1]["flat"])
    else:
        raise ValueError(rule)
    return [c[0] for c in order[:count]]


def cmd_describe(dump, spec):
    index = json.load(open(os.path.join(dump, "index.json")))
    out = {"rate": RATE, "roles": {}}
    for role, (src, rule, variants, kind, gain) in ROLES.items():
        if src.startswith("grains/"):
            chosen = [e for e in index if e["file"] == src + ".wav"]
        elif "#" in src:
            bank, i = src.split("#")
            chosen = [e for e in index if e["bank"].split(".")[0] == bank and e.get("index") == int(i)]
        else:
            cands = [e for e in index if e["bank"].split(".")[0] == src]
            scored = []
            for e in cands:
                x, rate = _read_wav(os.path.join(dump, e["file"]))
                if len(x) >= 64:
                    scored.append((e, _stats(x, rate)))
            chosen = _pick(scored, rule, variants)
        descs = []
        for e in chosen:
            x, rate = _read_wav(os.path.join(dump, e["file"]))
            if kind == "loop":
                if len(x) > 2 * rate:  # the steady middle
                    x = x[len(x) // 2 - rate: len(x) // 2 + rate]
                descs.append(describe_loop(x, rate))
            else:
                descs.append(describe_oneshot(x[: int(1.5 * rate)], rate))
        if not descs:
            print(f"  {role}: no source ({src}), skipped")
            continue
        out["roles"][role] = {"gain": gain, "descriptors": descs}
        print(f"  {role}: {len(descs)} x {kind} from {src}")
    os.makedirs(spec, exist_ok=True)
    with open(os.path.join(spec, "audio.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"describe: {len(out['roles'])} roles -> {os.path.join(spec, 'audio.json')}")


def _write_wav(path, x, seed):
    # Dense +-2 LSB dither: quiet tails of any two sounds otherwise quantise to
    # the same few values, which the byte-run taint scan cannot tell from copying.
    d = np.random.default_rng(seed).integers(-2, 3, len(x))
    pcm = np.clip(np.round(np.clip(x, -1, 1) * 32000) + d, -32768, 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def cmd_build(spec, assets):
    s = json.load(open(os.path.join(spec, "audio.json")))
    out_dir = os.path.join(assets, "clean-audio")
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.endswith(".wav"):
            os.remove(os.path.join(out_dir, f))
    rendered = {}
    for role, r in s["roles"].items():
        for i, d in enumerate(r["descriptors"]):
            name = role if len(r["descriptors"]) == 1 else f"{role}_{i + 1}"
            seed = sum(map(ord, name)) * 131 + i
            rng = np.random.default_rng(seed)
            if d["kind"] == "loop":
                x = synth_loop(d, 2.0, rng)
            else:
                x = synth_oneshot(d, rng)
            # Keep the source's level: relative loudness between roles is a fact.
            x = _norm(x) * 10 ** (d["level"] / 20)
            rendered[name] = (x, d["kind"] == "loop", r["gain"], seed)
    # One global scale so the loudest sound peaks at -1 dBFS.
    peak = max(np.abs(x).max() for x, *_ in rendered.values())
    scale = 0.89 / peak
    sounds = {}
    for name, (x, loop, gain, seed) in rendered.items():
        _write_wav(os.path.join(out_dir, name + ".wav"), x * scale, seed)
        sounds[name] = {"file": name + ".wav", "loop": loop, "gain": gain}
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
