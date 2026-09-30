"""Real skateboard recordings (CC0 / public domain) for the web build's player sounds.

    python -m games.skate3.audio_cc0 <cc0 dir> <clean assets dir>

<cc0 dir>/sources.json lists {file, event, url, author, license, ...}; only
entries whose license is CC0 / public domain are used. Each event becomes one
or more roles the web driver plays (player_audio_web.rs):
  one-shots (pop, catch, push, landing, bail): every clear hit in the files is
  found by onset detection, cut with a short fade, and the strongest few kept
  as variants (pop_1, pop_2, ...);
  loops (rolling, grinds, powerslide): the steadiest 2.5 s stretch is taken and
  crossfaded into a seamless loop.
Levels are set per category so rolling sits under the hits. The files replace
the resynthesised ones for the same roles in <assets>/clean-audio; roles with
no recording keep the resynthesised sound. Credits go to clean-audio/CREDITS.json.
No retail audio is read here.
"""
import json
import os
import sys
import wave

import numpy as np
import soundfile as sf

RATE = 32000

# event keyword -> (role, kind, variants, level): level is peak dBFS for
# one-shots and RMS dBFS for loops.
EVENTS = [
    (("pop", "ollie"), "pop", "oneshot", 4, -4.0),
    (("catch",), "catch", "oneshot", 3, -7.0),
    (("push", "kick"), "push", "oneshot", 3, -10.0),
    (("land",), "land_impact", "oneshot", 4, -3.0),
    (("bail", "clatter", "fall"), "bail", "oneshot", 2, -4.0),
    (("roll_smooth", "roll_concrete", "smooth concrete", "rolling concrete"), "roll_smooth", "loop", 1, -24.0),
    (("rough", "asphalt"), "roll_rough", "loop", 1, -24.0),
    (("wood",), "roll_wood", "loop", 1, -24.0),
    (("grind_rail", "metal rail", "rail grind", "grind_metal", "metal grind"), "grind_metal", "loop", 1, -20.0),
    (("ledge", "concrete grind", "slide_concrete", "grind_concrete"), "grind_concrete", "loop", 1, -20.0),
    (("powerslide", "wheel slide", "slide"), "powerslide", "loop", 1, -22.0),
]


def _load(path, mid_side=False):
    x, rate = sf.read(path, dtype="float64", always_2d=True)
    # Mid/side recordings: the first channel is the mid (mono) signal.
    x = x[:, 0] if mid_side else x.mean(axis=1)
    if rate != RATE:
        t = np.arange(int(len(x) * RATE / rate)) * rate / RATE
        x = np.interp(t, np.arange(len(x)), x)
    return x


def _role_for(event):
    e = event.lower()
    for keys, role, kind, variants, level in EVENTS:
        if any(k in e for k in keys):
            return role, kind, variants, level
    return None


def _onsets(x):
    """Sample indices of clear hits: jumps in a 5 ms energy envelope."""
    hop = RATE // 200
    env = np.array([np.sqrt((x[i:i + hop] ** 2).mean()) for i in range(0, len(x) - hop, hop)])
    if len(env) < 4:
        return []
    db = 20 * np.log10(env + 1e-9)
    floor = np.percentile(db, 30)
    rise = np.diff(db, prepend=db[0])
    hits = []
    for i in np.argsort(-db):
        if db[i] < floor + 12:
            break
        # Walk back to where this hit started rising.
        j = i
        while j > 0 and db[j - 1] < db[j] - 0.5 and db[j - 1] > floor + 3:
            j -= 1
        if rise[max(j, 1)] < 3 and db[i] - floor < 20:
            continue
        if all(abs(j - h) > 30 for h, _ in hits):  # >= 150 ms apart
            hits.append((j, db[i]))
        if len(hits) >= 12:
            break
    return [(j * hop, peak) for j, peak in hits]


def _cut(x, start, max_seconds=0.6):
    a = max(0, start - RATE // 200)
    # Start just before the hit's actual peak if the onset guess was early.
    look = x[a:a + int(0.4 * RATE)]
    if len(look) and np.abs(look).argmax() > 0.04 * RATE:
        a += int(np.abs(look).argmax() - 0.008 * RATE)
    seg = x[a:a + int(max_seconds * RATE)].copy()
    hop = RATE // 200
    env = np.array([np.sqrt((seg[i:i + hop] ** 2).mean()) for i in range(0, len(seg) - hop, hop)])
    if len(env):
        peak = env.max()
        # End where the tail has fallen 40 dB below the peak (after the peak).
        after = np.nonzero(env[env.argmax():] < peak * 0.01)[0]
        if len(after):
            seg = seg[: (env.argmax() + after[0] + 1) * hop]
    fade_in, fade_out = min(len(seg), RATE // 1000), min(len(seg), RATE // 50)
    seg[:fade_in] *= np.linspace(0, 1, fade_in)
    seg[-fade_out:] *= np.linspace(1, 0, fade_out)
    return seg


def _loop(x, seconds=2.5):
    n = int(seconds * RATE)
    if len(x) < n + RATE // 4:
        n = max(RATE // 2, len(x) - RATE // 4)
    hop = RATE // 20
    best, where = None, 0
    for s in range(0, len(x) - n - RATE // 8, hop):
        seg = x[s:s + n]
        env = np.array([np.sqrt((seg[i:i + hop] ** 2).mean()) for i in range(0, n - hop, hop)])
        if env.mean() < 1e-4:
            continue
        # Steady and without sharp hits: a clack inside a loop repeats every lap.
        crest = 20 * np.log10(np.abs(seg).max() / (np.sqrt((seg ** 2).mean()) + 1e-12) + 1e-12)
        score = env.std() / env.mean() + 0.08 * max(0.0, crest - 10)
        if best is None or score < best:
            best, where = score, s
    xf = RATE // 8
    seg = x[where:where + n + xf].copy()
    if len(seg) < n + xf:
        return x[where:where + n]
    ramp = np.linspace(0, 1, xf)
    out = seg[:n].copy()
    out[:xf] = seg[:xf] * ramp + seg[n:n + xf] * (1 - ramp)
    return out


def _write(path, x):
    # Dense +-2 LSB dither, as for the resynthesised sounds: quiet stretches of
    # any recording otherwise quantise into byte runs the taint scan flags.
    d = np.random.default_rng(len(x)).integers(-2, 3, len(x))
    pcm = np.clip(np.round(np.clip(x, -1, 1) * 32000) + d, -32768, 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    src_dir, assets = argv[1], argv[2]
    sources = json.load(open(os.path.join(src_dir, "sources.json")))
    def cc0(s):
        lic = s.get("license", "").lower()
        return "cc0" in lic or "creative commons 0" in lic or "public domain" in lic
    ok = [s for s in sources if cc0(s)]
    out_dir = os.path.join(assets, "clean-audio")
    manifest_path = os.path.join(out_dir, "sounds.json")
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {"rate": RATE, "sounds": {}}
    by_role = {}
    for s in ok:
        r = _role_for(s["event"])
        if r:
            by_role.setdefault(r, []).append(s)
    credits = []
    extra_landings = []
    # Ollie clips first, so their landings are ready when land_impact is built.
    order = sorted(by_role.items(), key=lambda kv: kv[0][0] != "pop")
    for (role, kind, variants, level), items in order:
        takes = []
        for s in items:
            x = _load(os.path.join(src_dir, s["file"]), "M/S" in (s.get("notes") or ""))
            if kind == "loop":
                takes.append((np.sqrt((x ** 2).mean()), _loop(x), s))
                continue
            hits = sorted(_onsets(x))  # in time order
            if role == "land_impact" and (s.get("notes") or "").startswith("drop"):
                continue  # a dropped board is not a ridden landing
            if role == "pop" and hits:
                # An ollie clip is pop ... landing: the pop is the first hit.
                hits = hits[:1]
            elif role == "catch":
                # Flip clips are pop, catch, landing: keep what lies between.
                hits = hits[1:-1]
            for start, peak in hits:
                takes.append((peak, _cut(x, start, 0.35 if role in ("pop", "catch") else 0.6), s))
            if role == "pop" and len(sorted(_onsets(x))) > 1:
                # The loudest hit after the pop in an ollie clip is its landing.
                after = [h for h in sorted(_onsets(x))[1:] if h[0] > sorted(_onsets(x))[0][0] + 0.15 * RATE]
                if after:
                    start, peak = max(after, key=lambda h: h[1])
                    extra_landings.append((peak, _cut(x, start, 0.6), s))
        if role == "land_impact":
            takes += extra_landings
        takes.sort(key=lambda t: -t[0])
        takes = takes[:variants]
        if not takes:
            print(f"  {role}: no usable takes")
            continue
        # Replace this role (and its old variants) in the manifest. A recorded
        # landing replaces the synthetic impact and its soft/hard ladder layers.
        replaced = [role] + (["land_soft", "land_hard"] if role == "land_impact" else [])
        for name in [k for k in manifest["sounds"]
                     if any(k == r or (k.startswith(r + "_") and k[len(r) + 1:].isdigit()) for r in replaced)]:
            path = os.path.join(out_dir, manifest["sounds"][name]["file"])
            if os.path.exists(path):
                os.remove(path)
            del manifest["sounds"][name]
        for i, (_, x, s) in enumerate(takes):
            name = role if len(takes) == 1 else f"{role}_{i + 1}"
            if kind == "loop":
                x = x / (np.sqrt((x ** 2).mean()) + 1e-12) * 10 ** (level / 20)
                x = np.tanh(x * 1.5) / 1.5  # soft-limit stray peaks
            else:
                x = x / (np.abs(x).max() + 1e-12) * 10 ** (level / 20)
            _write(os.path.join(out_dir, name + ".wav"), x)
            manifest["sounds"][name] = {"file": name + ".wav", "loop": kind == "loop", "gain": 1.0, "source": "cc0"}
            credits.append({"sound": name, "url": s["url"], "author": s.get("author"), "license": s["license"]})
        print(f"  {role}: {len(takes)} CC0 take(s) from {len(items)} file(s)")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=1)
    with open(os.path.join(out_dir, "CREDITS.json"), "w") as f:
        json.dump(credits, f, indent=1)
    print(f"cc0: {len(credits)} sounds from {len(ok)} CC0 files; {len(manifest['sounds'])} sounds total")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
