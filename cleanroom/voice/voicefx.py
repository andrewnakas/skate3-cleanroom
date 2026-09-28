"""Studio chain for the user's own voice takes -> game voice slots.

Per line: noise reduction, high-pass, take selection, pitch match to the
slot's kept pitch level, EQ match to the slot's kept 16-band outline,
timing fit (gap closing + WSOLA), compression, level match, limiter.
Targets come only from the spec's coarse descriptors (median f0, band
outline, RMS), never from the original audio.

    CLEANROOM_GAME=games/<g> python -m cleanroom.voice.voicefx <takes dir> [--report]
"""
import json
import os
import sys
import wave

import numpy as np
from scipy import signal

from cleanroom.audio import descriptor

HERE = os.environ.get("CLEANROOM_GAME", os.getcwd())   # game dir: spec/, voice_lines.json, voices/
CACHE = os.path.join(HERE, "voices")


def rd(p):
    with wave.open(p) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768, w.getframerate()


def wr(p, x, sr):
    with wave.open(p, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


# ------------------------------------------------------------- building blocks

def highpass(x, sr, hz=80):
    b, a = signal.butter(2, hz / (sr / 2), "high")
    return signal.lfilter(b, a, x).astype(np.float32)


def denoise(x, sr, noise_prof, strength=1.6, floor=0.12):
    f, t, Z = signal.stft(x, sr, nperseg=1024, noverlap=768)
    mag = np.abs(Z)
    g = np.clip(1 - strength * noise_prof[:, None] / (mag + 1e-9), floor, 1)
    g = signal.convolve2d(g, np.ones((3, 5)) / 15, mode="same", boundary="symm")      # smooth: no musical noise
    _, y = signal.istft(Z * g, sr, nperseg=1024, noverlap=768)
    return y[:len(x)].astype(np.float32)


def noise_profile(x, sr):
    f, t, Z = signal.stft(x, sr, nperseg=1024, noverlap=768)
    mag = np.abs(Z)
    e = mag.mean(0)
    quiet = mag[:, e <= np.percentile(e, 10)]
    return np.median(quiet, 1)


def deess(x, sr, thresh_db=-28, amount=0.5):
    b, a = signal.butter(2, [5000 / (sr / 2), min(0.99, 9000 / (sr / 2))], "band")
    s = signal.lfilter(b, a, x)
    env = np.sqrt(signal.lfilter([0.01], [1, -0.99], s ** 2) + 1e-12)
    over = np.clip(20 * np.log10(env + 1e-9) - thresh_db, 0, None)
    g = 10 ** (-over * amount / 20)
    return (x - s + s * g).astype(np.float32)


from cleanroom.audio.pitch import f0_track  # noqa: E402


def wsola(x, rate, sr):
    """Time-scale by 1/rate (rate > 1 = faster) keeping pitch."""
    if abs(rate - 1) < 1e-3 or len(x) < sr // 20:
        return x.copy()
    N = int(0.03 * sr)
    Hs = N // 2
    Ha = Hs * rate
    tol = int(0.01 * sr)
    win = np.hanning(N).astype(np.float32)
    out_len = int(len(x) / rate) + N
    y = np.zeros(out_len + N, np.float32)
    wsum = np.zeros_like(y)
    xp = np.concatenate([np.zeros(tol, np.float32), x, np.zeros(N + tol + int(Ha) + 2, np.float32)])
    prev = tol
    k = 0
    while True:
        out_pos = k * Hs
        a_pos = int(round(k * Ha)) + tol
        if out_pos + N > len(y) or a_pos - tol >= len(x):
            break
        if k == 0:
            best = a_pos
        else:
            nat = xp[prev + Hs:prev + Hs + N]
            lo, hi = max(0, a_pos - tol), a_pos + tol
            seg = xp[lo:hi + N]
            if len(seg) < N or len(nat) < N:
                break
            c = np.correlate(seg, nat, "valid")
            best = lo + int(np.argmax(c))
        y[out_pos:out_pos + N] += xp[best:best + N] * win
        wsum[out_pos:out_pos + N] += win
        prev = best
        k += 1
    return (y / np.maximum(wsum, 1e-3))[:int(len(x) / rate)].astype(np.float32)


def pitch_shift(x, sr, semitones):
    """Resample (pitch + formants move together) then WSOLA back to length."""
    if abs(semitones) < 0.05:
        return x
    f = 2 ** (semitones / 12)
    n = int(len(x) / f)
    y = signal.resample_poly(x, 1000, int(round(1000 * f))).astype(np.float32)[:n] if f != 1 else x
    return wsola(y, 1 / f, sr)[:len(x)]


def band_db(x, sr):
    """Long-term level in the descriptor's 16 log bands (dB)."""
    f, P = signal.welch(x, sr, nperseg=1024)
    out = []
    for lo, hi in zip(descriptor.EDGES[:-1], descriptor.EDGES[1:]):
        m = (f >= lo) & (f < hi)
        out.append(10 * np.log10(P[m].mean() + 1e-14) if m.any() else -120)
    return np.array(out)


def eq_match(x, sr, target_db, max_db=8.0):
    have = band_db(x, sr)
    ok = (target_db > -85) & (have > -100)
    if ok.sum() < 4:
        return x
    diff = np.where(ok, target_db - have, 0.0)
    diff -= np.median(diff[ok])                         # shape only; level comes later
    diff = np.clip(np.convolve(diff, [0.25, 0.5, 0.25], "same"), -max_db, max_db)
    f, t, Z = signal.stft(x, sr, nperseg=1024, noverlap=768)
    g_db = np.interp(np.log(np.maximum(f, 1)), np.log(descriptor.CENTERS), diff)
    _, y = signal.istft(Z * (10 ** (g_db / 20))[:, None], sr, nperseg=1024, noverlap=768)
    return y[:len(x)].astype(np.float32)


def compress(x, sr, thresh_db=-22, ratio=3.0, attack=0.004, release=0.08):
    a_at, a_re = np.exp(-1 / (attack * sr)), np.exp(-1 / (release * sr))
    env = np.zeros_like(x)
    e = 0.0
    ax = np.abs(x)
    for i in range(len(x)):
        c = a_at if ax[i] > e else a_re
        e = c * e + (1 - c) * ax[i]
        env[i] = e
    lvl = 20 * np.log10(env + 1e-9)
    g = np.where(lvl > thresh_db, (thresh_db + (lvl - thresh_db) / ratio) - lvl, 0.0)
    return (x * 10 ** (g / 20)).astype(np.float32)


def limit(x, ceiling=0.95):
    peak = np.abs(x).max()
    return x * (ceiling / peak) if peak > ceiling else x


def close_gaps(x, sr, max_gap=0.15, min_gap=0.25, xfade=0.012):
    """Shorten real pauses between words (>= min_gap of near-silence) to
    max_gap, joining the pieces with short crossfades so no clicks remain.
    Quiet consonants (t, s, k) are far shorter than min_gap and stay intact."""
    hop = int(0.01 * sr)
    n = len(x) // hop
    e = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1))
    quiet = e < max(0.006, e.max() * 0.03)
    cuts = []
    i = 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if 0 < i and j < n and (j - i) * 0.01 >= min_gap:
                a = i * hop + int(max_gap * sr / 2)
                b = j * hop - int(max_gap * sr / 2)
                if b > a:
                    cuts.append((a, b))
            i = j
        else:
            i += 1
    if not cuts:
        return x
    k = int(xfade * sr)
    out, pos = x[:0], 0
    for a, b in cuts:
        piece = x[pos:a + k]
        if len(out) >= k and len(piece) >= k:
            ramp = np.linspace(0, 1, k, dtype=np.float32)
            out[-k:] = out[-k:] * (1 - ramp) + piece[:k] * ramp
            piece = piece[k:]
        out = np.concatenate([out, piece])
        pos = b
    piece = x[pos:]
    if len(out) >= k and len(piece) >= k:
        ramp = np.linspace(0, 1, k, dtype=np.float32)
        out[-k:] = out[-k:] * (1 - ramp) + piece[:k] * ramp
        piece = piece[k:]
    return np.concatenate([out, piece]).astype(np.float32)


def utterances(x, sr, min_gap=0.35):
    """Split a response window into separate attempts at long pauses."""
    hop = int(0.01 * sr)
    n = len(x) // hop
    e = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1))
    act = e > max(0.012, e.max() * 0.08)
    segs, start, last = [], None, -999
    for i, a in enumerate(act):
        if a:
            if start is None:
                start = i
            elif (i - last) * 0.01 > min_gap:
                segs.append((start, last + 1))
                start = i
            last = i
    if start is not None:
        segs.append((start, last + 1))
    return [x[max(0, a - 3) * hop:min(len(x), (b + 5) * hop)] for a, b in segs if (b - a) > 4]


def fade(x, sr, ms=6):
    k = min(len(x) // 2, int(ms / 1000 * sr))
    if k > 0:
        x = x.copy()
        x[:k] *= np.linspace(0, 1, k)
        x[-k:] *= np.linspace(1, 0, k)
    return x


# ------------------------------------------------------------------ pipeline

def target(slot):
    fr = slot["desc"]["frames"]
    tonal = [f["f0"] for f in fr if f["f0"] > 60 and f["h"] > 0.35]
    bands = np.array([f["db"] for f in fr], np.float32)
    w = 10 ** (np.array([f["rms"] for f in fr]) / 20)
    band = 10 * np.log10((10 ** (bands / 10) * w[:, None]).sum(0) / w.sum() + 1e-14)
    rms = 20 * np.log10(np.sqrt((w ** 2).mean()) + 1e-9)
    return (float(np.median(tonal)) if len(tonal) >= 2 else None), band, rms


GENTLE_ST = 4.0      # below this pitch change, skip the vocoder

# character targets: formant lift (semitones; pitch comes from the slot's kept
# f0), intonation range multiplier, limits
FX_DEFAULT = {"formant_st": 0.0, "expressive": 1.1, "max_speed": 1.8, "max_st": 12.0, "default_f0": 200.0}


def char_fx(who):
    """Per-character chain settings from voice_lines.json "_characters"[who]["fx"]."""
    d = json.load(open(os.path.join(HERE, "voice_lines.json"))).get("_characters", {})
    return {**FX_DEFAULT, **d.get(who, {}).get("fx", {})}


def world_voice(x, sr, f0_goal, formant_st, expressive, stretch, max_st):
    """WORLD vocoder re-voicing: move the take's median pitch to the goal
    (keeping its own intonation, slightly widened), lift formants by a
    smaller amount (character timbre without chipmunk), and re-time by
    resampling the analysis frames."""
    import pyworld as pw
    fs = 32000
    y = signal.resample_poly(x, fs, sr).astype(np.float64)
    f0, t = pw.harvest(y, fs, f0_floor=60, f0_ceil=900, frame_period=5.0)
    sp = pw.cheaptrick(y, f0, t, fs)
    ap = pw.d4c(y, f0, t, fs)
    voiced = f0 > 0
    if voiced.sum() < 3:
        return x, 0.0
    med = float(np.median(f0[voiced]))
    # tracker glitches: fold octave jumps back toward the median, then a short
    # median filter over voiced runs (no warble from single-frame errors)
    fv = f0[voiced]
    k = np.round(np.log2(fv / med))
    fv = np.where(np.abs(k) >= 1, fv / 2 ** k, fv)
    f0[voiced] = signal.medfilt(fv, 5)
    st = float(np.clip(12 * np.log2(f0_goal / med), -6, max_st))
    ratio = 2 ** (st / 12)
    f0n = f0.copy()
    f0n[voiced] = med * ratio * (f0[voiced] / med) ** expressive
    # formant warp: sp_new(f) = sp(f / a)
    a = 2 ** (formant_st / 12)
    bins = sp.shape[1]
    src = np.arange(bins) / a
    lo = np.clip(np.floor(src).astype(int), 0, bins - 1)
    hi = np.clip(lo + 1, 0, bins - 1)
    fr = (src - np.floor(src))[None, :]
    spn = sp[:, lo] * (1 - fr) + sp[:, hi] * fr
    apn = ap[:, lo] * (1 - fr) + ap[:, hi] * fr
    # re-time: fewer frames = faster, same pitch
    if stretch > 1.001:
        n = len(f0n)
        m = max(2, int(n / stretch))
        idx = np.linspace(0, n - 1, m)
        i0 = np.floor(idx).astype(int)
        i1 = np.minimum(i0 + 1, n - 1)
        w = (idx - i0)[:, None]
        spn = spn[i0] * (1 - w) + spn[i1] * w
        apn = apn[i0] * (1 - w) + apn[i1] * w
        f0n = np.where((f0n[i0] > 0) & (f0n[i1] > 0), f0n[i0] * (1 - w[:, 0]) + f0n[i1] * w[:, 0],
                       np.maximum(f0n[i0], f0n[i1]) * ((f0n[i0] > 0) & (f0n[i1] > 0)))
    out = pw.synthesize(np.ascontiguousarray(f0n), np.ascontiguousarray(spn), np.ascontiguousarray(apn), fs, 5.0)
    return signal.resample_poly(out, sr, fs).astype(np.float32), st


def process(x, sr, slot, text, prof, words, text_who):
    hz = int(round(slot["rate"]))
    n_slot = slot["nframes"]
    f0_t, band_t, rms_t = target(slot)
    x = highpass(x, sr)
    x = denoise(x, sr, prof)
    x = deess(x, sr)
    # several attempts in one window only if it is much longer than the line;
    # otherwise pauses are just between sentences
    cands = utterances(x, sr) if len(x) / sr > 1.8 * n_slot / slot["rate"] + 0.6 else [x]
    cands = cands or [x]
    if len(cands) > 1:
        from cleanroom.voice.voices import _norm, _hear
        def score(c):
            dur = len(c) / sr
            fit = -abs(np.log(max(dur, 0.05) / (n_slot / slot["rate"])))
            if words:
                heard = _norm(_hear(c, sr))
                want = _norm(text)
                return sum(w in heard for w in want) / max(1, len(want)) * 3 + fit
            return fit + np.sqrt((c ** 2).mean()) * 2
        x = max(cands, key=score)
    info = {}
    x = close_gaps(x, sr)
    ch = char_fx(text_who)
    f0_goal = slot.get("f0") or ch["default_f0"]
    want_s = n_slot / slot["rate"]
    stretch = max(1.0, min(ch["max_speed"], (len(x) / sr) / want_s))
    f0s = f0_track(x, sr)
    need = 12 * np.log2(f0_goal / np.median(f0s)) if len(f0s) >= 3 else 99
    if abs(need) < GENTLE_ST:
        # small change: time-domain shift + WSOLA (no vocoder resynthesis, so
        # no lost voicing on creaky or breathy passages)
        st = float(need)
        x = pitch_shift(x, sr, st)
        x = wsola(x, stretch, sr)
        info["path"] = "gentle"
    else:
        x, st = world_voice(x, sr, f0_goal, ch["formant_st"], ch["expressive"], stretch, ch["max_st"])
    info["pitch"] = round(st, 1)
    if stretch > 1.001:
        info["speed"] = round(stretch, 2)
    x = eq_match(x, sr, band_t, max_db=6.0)
    y = signal.resample_poly(x, hz, sr).astype(np.float32)
    if len(y) > n_slot:                          # still long after the capped speed-up: fade the tail
        info["trim"] = round(len(y) / n_slot, 2)
        y = y[:n_slot]
        k = min(len(y) // 4, int(0.06 * hz))
        y[-k:] *= np.linspace(1, 0, k)
    y = compress(y, hz)
    cur = 20 * np.log10(np.sqrt((y ** 2).mean()) + 1e-9)
    y = y * 10 ** ((rms_t - cur) / 20)
    y = fade(limit(y), hz)
    out = np.zeros(n_slot, np.float32)
    out[:len(y)] = y[:n_slot]
    return out, info




def main(argv):
    takes = argv[1]
    S = json.load(open(os.path.join(HERE, "spec", "samples.json")))
    L = {os.path.basename(k)[:-5]: (k, v) for k, v in json.load(open(os.path.join(HERE, "voice_lines.json"))).items()
         if not k.startswith("_")}
    raw = {}
    for who in sorted(os.listdir(takes)):
        d = os.path.join(takes, who)
        if not os.path.isdir(d):
            continue
        clips = [(f[:-4], *rd(os.path.join(d, f))) for f in sorted(os.listdir(d)) if f.endswith(".wav")]
        allx = np.concatenate([c[1] for c in clips if len(c[1])])
        prof = noise_profile(allx, clips[0][2])
        for name, x, sr in clips:
            raw[name] = (x, sr, prof)
    os.makedirs(CACHE, exist_ok=True)
    done = []
    for name, (x, sr, prof) in raw.items():
        if name not in L or len(x) < sr * 0.05:
            continue
        p, v = L[name]
        words = v.get("words", True)             # False for grunts/cries
        y, info = process(x, sr, S[p], v.get("text", ""), prof, words, v["who"])
        wr(os.path.join(CACHE, name + ".wav"), y, int(round(S[p]["rate"])))
        done.append((name, info))
    print(f"voicefx: {len(done)} lines from your takes -> {CACHE}")
    print("  pitch moves (semitones):", ", ".join(f"{n.split('_', 1)[1]} {i['pitch']:+}" for n, i in done if "pitch" in i))
    print("  sped up to fit:", ", ".join(f"{n.split('_', 1)[1]} x{i['speed']}" for n, i in done if "speed" in i) or "none")
    print("  gentle path (no vocoder):", ", ".join(n.split("_", 1)[1] for n, i in done if i.get("path") == "gentle") or "none")
    print("  tail trimmed:", ", ".join(f"{n.split('_', 1)[1]} x{i['trim']}" for n, i in done if "trim" in i) or "none")


if __name__ == "__main__":
    main(sys.argv)
