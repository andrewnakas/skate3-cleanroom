"""Import the user's own voice performances recorded against the practice
call-and-response tracks: align with the known track layout (beeps), cut
each response window, pick the voiced take.

The practice track layout is rebuilt from the spec (clip lengths only); the
original clips themselves are not read here.

    python -m games.sm64.takes cut <recording> <mario|peach> <out dir>
"""
import json
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HZ = 22050          # the practice tracks' rate


def load_audio(path):
    import av
    c = av.open(path)
    s = c.streams.audio[0]
    parts = []
    for fr in c.decode(s):
        a = fr.to_ndarray().astype(np.float32)
        a = a.reshape(len(fr.layout.channels), -1) if a.ndim > 1 or len(fr.layout.channels) > 1 else a[None]
        parts.append(a.mean(0))
    x = np.concatenate(parts)
    if np.abs(x).max() > 2:
        x /= 32768
    return x, s.rate


def layout(who):
    """[(name, clip_start, clip_len, window_start, window_len)] in seconds, as
    the practice track was built (clip, 0.3 s, 80 ms beep, 1.5x+1.5 s gap)."""
    S = json.load(open(os.path.join(HERE, "spec", "samples.json")))
    L = [(k, v) for k, v in json.load(open(os.path.join(HERE, "voice_lines.json"))).items()
         if not k.startswith("_") and v.get("kind") != "snore"]
    t, out = 0.0, []
    for p, v in L:
        name = os.path.basename(p)[:-5]
        if ("peach_" in name) != (who == "peach"):
            continue
        n = int(len(np.arange(0, S[p]["nframes"] * HZ / S[p]["rate"])))
        clip = n / HZ
        beep_t = t + clip + 0.3
        gap = int((clip * 1.5 + 1.5) * HZ) / HZ
        out.append((name, t, clip, beep_t, beep_t + 0.08, gap))
        t = beep_t + 0.08 + gap
    return out


def beep_track(x, sr):
    """Per-10 ms energy at 880 Hz relative to broadband energy."""
    hop = int(0.01 * sr)
    n = len(x) // hop
    fr = x[:n * hop].reshape(n, hop)
    t = np.arange(hop) / sr
    c, s = np.cos(2 * np.pi * 880 * t), np.sin(2 * np.pi * 880 * t)
    tone = np.hypot(fr @ c, fr @ s) / hop
    rms = np.sqrt((fr ** 2).mean(1)) + 1e-6
    return tone / rms


def find_offset(x, sr, lay):
    """Recording time of track time 0, by matching the expected beep times."""
    b = beep_track(x, sr)
    beeps = np.array([l[3] for l in lay])
    best, best_off = -1, 0.0
    for off in np.arange(-5.0, 15.0, 0.01):
        idx = ((beeps + off) / 0.01).astype(int)
        idx = idx[(idx >= 0) & (idx < len(b) - 8)]
        if not len(idx):
            continue
        score = sum(b[i:i + 8].max() for i in idx)
        if score > best:
            best, best_off = score, off
    return best_off, best / len(beeps)


def voiced(x, sr, thr_db=-38):
    """Trim to the voiced part (with margins)."""
    hop = int(0.01 * sr)
    n = len(x) // hop
    e = 20 * np.log10(np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    on = np.nonzero(e > max(thr_db, e.max() - 35))[0]
    if not len(on):
        return x[:0]
    a, b = max(0, on[0] - 3) * hop, min(len(x), (on[-1] + 6) * hop)
    return x[a:b]


def cut(path, who, out):
    x, sr = load_audio(path)
    lay = layout(who)
    off, conf = find_offset(x, sr, lay)
    os.makedirs(out, exist_ok=True)
    rows = []
    for name, cs, cl, bs, be, gap in lay:
        a, b = int((be + off) * sr), int((be + off + gap) * sr)
        seg = voiced(x[a:b], sr)
        with wave.open(os.path.join(out, name + ".wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((np.clip(seg, -1, 1) * 32767).astype("<i2").tobytes())
        rows.append((name, len(seg) / sr, cl))
    print(f"{who}: offset {off:+.2f}s (beep match {conf:.1f}); {len(rows)} takes -> {out}")
    for name, got, want in rows:
        flag = "  EMPTY" if got < 0.05 else ("  long" if got > want * 2 + 0.3 else "")
        print(f"  {name:38s} take {got:4.2f}s  slot {want:4.2f}s{flag}")


if __name__ == "__main__":
    if sys.argv[1] == "cut":
        cut(sys.argv[2], sys.argv[3], sys.argv[4])
