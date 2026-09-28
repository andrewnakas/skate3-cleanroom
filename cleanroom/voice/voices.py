"""Voice lines: spoken by a neural TTS (Piper, offline) in character voices
(our own performances of the words, not the original actors), fitted to
each sample slot's length and rate.

Results are cached in <game>/voices/<slot>.wav, so builds on machines
without the speech engine reuse them.

    CLEANROOM_GAME=games/<g> python -m cleanroom.voice.voices build        # (re)speak every line, print fit summary
    CLEANROOM_GAME=games/<g> python -m cleanroom.voice.voices check        # speech-recognition intelligibility report
"""
import json
import os
import struct
import subprocess
import sys
import wave

import numpy as np

HERE = os.environ.get("CLEANROOM_GAME", os.getcwd())   # game dir: spec/, voice_lines.json, voices/
KIT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "voices")
WORK = os.path.join(CACHE, "_raw")

VOICE = {}   # SAPI fallback: {"who": ("Microsoft David Desktop", "+0%")}
RATES = [0, 15, 30, 45, 60, 80]          # SSML rate steps (percent faster) tried until a line fits


def lines():
    d = json.load(open(os.path.join(HERE, "voice_lines.json")))
    return {k: v for k, v in d.items() if not k.startswith("_")}


def slots():
    return json.load(open(os.path.join(HERE, "spec", "samples.json")))


def _name(path):
    return os.path.basename(path)[:-5]


def _read_wav(p):
    with wave.open(p) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
        return x, w.getframerate()


def _trim(x, thr=0.006):
    idx = np.nonzero(np.abs(x) > thr)[0]
    if not len(idx):
        return x[:0]
    pad = 320                               # keep soft onsets (h, p, s)
    return x[max(0, idx[0] - pad):idx[-1] + pad]


def _speak(jobs):
    os.makedirs(WORK, exist_ok=True)
    jf = os.path.join(WORK, "jobs.json")
    json.dump(jobs, open(jf, "w"))
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    os.path.join(KIT, "tts.ps1"), jf], check=True, capture_output=True)


def snore(n, rate, seed):
    """Breathy in/out cycles: filtered noise under a slow envelope."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / rate
    noise = np.convolve(rng.standard_normal(n), np.ones(24) / 24, "same")
    rumble = np.sin(2 * np.pi * 55 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 7 * t))
    cycle = max(0.3, min(2.2, n / rate))
    env = np.clip(np.sin(np.pi * (t % cycle) / cycle), 0, 1) ** 2
    x = (noise * 0.7 + rumble * 0.5) * env
    return (x / (np.abs(x).max() + 1e-9) * 0.5).astype(np.float32)


PIPER_DIR = os.environ.get("PIPER_VOICES", "C:/Users/andre/n64work/piper_voices")
# character styling: Piper voice, pitch lift (semitones), base speed, expressiveness
TTS_DEFAULT = {"model": "en_US-ryan-high", "semitones": 0.0, "length": 1.0, "noise": 0.8, "noise_w": 0.9}


class _Chars(dict):
    """Per-character TTS settings from voice_lines.json "_characters"[who]["tts"]."""
    def __missing__(self, who):
        d = json.load(open(os.path.join(HERE, "voice_lines.json"))).get("_characters", {})
        self[who] = {**TTS_DEFAULT, **d.get(who, {}).get("tts", {})}
        return self[who]


CHARACTERS = _Chars()
_VOICES = {}


def _piper(who, text, length):
    from piper import PiperVoice, SynthesisConfig
    ch = CHARACTERS[who]
    if who not in _VOICES:
        _VOICES[who] = PiperVoice.load(os.path.join(PIPER_DIR, ch["model"] + ".onnx"))
    v = _VOICES[who]
    cfg = SynthesisConfig(length_scale=length, noise_scale=ch["noise"], noise_w_scale=ch["noise_w"])
    x = np.concatenate([c.audio_float_array for c in v.synthesize(text, syn_config=cfg)]).astype(np.float32)
    return x, v.config.sample_rate


def _character(who, x, sr, hz):
    """Pitch lift by playback speed-up: the line was spoken slower by the same
    factor (see build), so duration is restored and pitch and formants rise
    together (a brighter, cartoon timbre) with no phase-vocoder artifacts."""
    import librosa
    f = 2 ** (CHARACTERS[who]["semitones"] / 12)
    return librosa.resample(x, orig_sr=sr * f, target_sr=hz).astype(np.float32)


TAKES = 6
_WHISPER = None


def _norm(t):
    import re as _re
    return [w for w in _re.sub(r"[^a-z' ]", " ", t.lower().replace("-", " ")).split() if w]


def _hear(x, hz):
    global _WHISPER
    import librosa
    from faster_whisper import WhisperModel
    if _WHISPER is None:
        _WHISPER = WhisperModel("base.en", device="cpu", compute_type="int8")
    x16 = librosa.resample(x, orig_sr=hz, target_sr=16000)
    segs, _ = _WHISPER.transcribe(np.concatenate([np.zeros(1600, np.float32), x16, np.zeros(8000, np.float32)]),
                                  language="en", beam_size=5)
    return " ".join(s.text for s in segs)


def _hear_score(x, hz, text):
    want, got = _norm(text), _norm(_hear(x, hz))
    return sum(1 for w in want if w in got) / max(1, len(want))


def build(only=None):
    L, S = lines(), slots()
    if only:
        L = {p: v for p, v in L.items() if any(o in p for o in only)}
    os.makedirs(CACHE, exist_ok=True)
    summary = []
    for p, v in L.items():
        n, hz = S[p]["nframes"], int(round(S[p]["rate"]))
        if v.get("kind") == "snore":
            x = snore(n, hz, hash(p) & 0xFFFF)
        else:
            base = CHARACTERS[v["who"]]["length"]
            f = 2 ** (CHARACTERS[v["who"]]["semitones"] / 12)
            for k in range(8):                     # speak faster until the line fits its slot
                length = base * (0.88 ** k)
                raw, sr = _piper(v["who"], v["text"], length * f)
                x = _trim(_character(v["who"], raw, sr, hz))
                if len(x) <= n:
                    break
            # several takes (synthesis is stochastic): keep the one a listener
            # model (Whisper) understands best
            takes = [x]
            for _ in range(TAKES - 1):
                raw, sr = _piper(v["who"], v["text"], length * f)
                y = _trim(_character(v["who"], raw, sr, hz))
                if len(y) <= n:
                    takes.append(y)
            if len(takes) > 1:
                scores = [_hear_score(t, hz, v["text"]) for t in takes]
                x = takes[int(np.argmax(scores))]
                if max(scores) < 0.5:
                    summary.append(f"{_name(p)} best {max(scores):.0%}")
            if k:
                summary.append(f"{_name(p)} x{base / length:.2f}")
            if len(x) > n:
                xs = np.linspace(0, len(x) - 1, n)
                summary.append(f"{_name(p)} squeezed {len(x) / n:.2f}")
                x = np.interp(xs, np.arange(len(x)), x).astype(np.float32)
        x = x / (np.abs(x).max() + 1e-9) * 0.9
        out = np.zeros(n, np.float32)
        out[:min(n, len(x))] = x[:n]
        with wave.open(os.path.join(CACHE, _name(p) + ".wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(hz)
            w.writeframes((out * 32767).astype("<i2").tobytes())
    print(f"voices: {len(L)} lines -> {CACHE}")
    print("sped up / squeezed:", ", ".join(summary) or "none")


def cached(path):
    """Float samples for a voice slot, or None if the slot is not a voice line."""
    p = os.path.join(CACHE, _name(path) + ".wav")
    if path not in lines() or not os.path.exists(p):
        return None
    return _read_wav(p)[0]


def check():
    # the recogniser needs lead-in silence; check padded copies
    adir = os.path.join(WORK, "asr")
    os.makedirs(adir, exist_ok=True)
    for f in os.listdir(CACHE):
        if f.endswith(".wav"):
            x, hz = _read_wav(os.path.join(CACHE, f))
            x = np.concatenate([np.zeros(hz // 20, np.float32), x, np.zeros(hz // 4, np.float32)])
            with wave.open(os.path.join(adir, f), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(hz)
                w.writeframes((x * 32767).astype("<i2").tobytes())
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          os.path.join(KIT, "asr_check.ps1"), adir], capture_output=True, text=True).stdout
    L = {_name(p): v for p, v in lines().items()}
    ok = 0
    rows = []
    for line in out.strip().splitlines():
        name, conf, heard = (line.split("\t") + ["", ""])[:3]
        want = L.get(name, {}).get("text", "")
        if not want:
            continue
        wn = set(w.strip("!.,?:").lower() for w in want.split())
        hn = set(w.strip("!.,?:").lower() for w in heard.split())
        hit = len(wn & hn) / max(1, len(wn))
        ok += hit >= 0.5
        rows.append(f"{hit:4.0%} {name:40s} want '{want}' heard '{heard}'")
    print(f"intelligibility: {ok}/{len(rows)} lines with >=50% of words recognised")
    for r in sorted(rows)[:60]:
        print(" ", r)


def whisper_check():
    """Intelligibility with Whisper (robust to accents, closer to a listener):
    word overlap between the intended line and what Whisper hears."""
    import re as _re
    from faster_whisper import WhisperModel
    m = WhisperModel("base.en", device="cpu", compute_type="int8")
    norm = lambda t: [w for w in _re.sub(r"[^a-z' ]", " ", t.lower().replace("-a ", " a ").replace("-", " ")).split() if w]
    rows, ok, n = [], 0, 0
    for p, v in lines().items():
        if v.get("kind") == "snore":
            continue
        x, hz = _read_wav(os.path.join(CACHE, _name(p) + ".wav"))
        import librosa
        x16 = librosa.resample(x, orig_sr=hz, target_sr=16000)
        segs, _ = m.transcribe(np.concatenate([np.zeros(1600, np.float32), x16, np.zeros(8000, np.float32)]),
                               language="en", beam_size=5, vad_filter=False)
        heard = " ".join(s.text for s in segs).strip()
        want, got = norm(v["text"]), norm(heard)
        hit = sum(1 for w in want if w in got) / max(1, len(want))
        n += 1
        ok += hit >= 0.5
        rows.append((hit, _name(p), v["text"], heard))
    print(f"whisper intelligibility: {ok}/{n} lines with >=50% of words heard")
    for hit, name, want, heard in sorted(rows):
        print(f"  {hit:4.0%} {name:36s} want '{want}' heard '{heard}'")


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2:] or None)
    else:
        {"check": check, "whisper": whisper_check}[sys.argv[1]]()
