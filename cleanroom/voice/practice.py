"""Practice pack for recording voice lines (PERSONAL USE: built from the
user's own ROM extraction; written outside the repo, never published).

Writes numbered reference clips, one call-and-response track per character
(clip, 0.3 s, 80 ms beep at 880 Hz, a gap of 1.5x+1.5 s to repeat) and a
SCRIPT.txt. takes.py rebuilds this exact layout to cut the recordings.

    CLEANROOM_GAME=games/<g> python -m cleanroom.voice.practice <dirty tree> <out dir>
"""
import json
import os
import sys
import wave

import numpy as np

from cleanroom.decomp.taint import pcm_bytes

HERE = os.environ.get("CLEANROOM_GAME", os.getcwd())
HZ = 22050


def main(argv):
    dirty, out = argv[1], argv[2]
    S = json.load(open(os.path.join(HERE, "spec", "samples.json")))
    L = [(k, v) for k, v in json.load(open(os.path.join(HERE, "voice_lines.json"))).items()
         if not k.startswith("_") and v.get("kind", "speech") == "speech"]
    os.makedirs(os.path.join(out, "clips"), exist_ok=True)

    def load(p):
        raw = pcm_bytes(os.path.join(dirty, p))
        x = np.frombuffer(raw, "<i2" if p.lower().endswith(".wav") else ">i2").astype(np.float32) / 32768
        sr = int(round(S[p]["rate"]))
        return np.interp(np.arange(0, len(x) * HZ / sr) * sr / HZ, np.arange(len(x)), x).astype(np.float32)

    def wr(path, x):
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(HZ)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

    beep = (0.2 * np.sin(2 * np.pi * 880 * np.arange(int(0.08 * HZ)) / HZ)).astype(np.float32)
    tracks, lines = {}, ["Voice practice script: record in this order, 2-3 takes each, in character.",
                         "Play practice_<character>_call_and_response.wav and speak after each beep.", ""]
    for i, (p, v) in enumerate(L, 1):
        name = os.path.splitext(os.path.basename(p))[0]
        x = load(p)
        wr(os.path.join(out, "clips", f"{i:02d}_{name}.wav"), x)
        gap = np.zeros(int((len(x) / HZ * 1.5 + 1.5) * HZ), np.float32)
        tracks.setdefault(v["who"], []).extend([x, np.zeros(int(0.3 * HZ), np.float32), beep, gap])
        lines.append(f"{i:02d}  {v['who']:10s} {name:40s} max {S[p]['nframes'] / S[p]['rate']:.1f}s  \"{v.get('text', '')}\"")
    for who, parts in tracks.items():
        wr(os.path.join(out, f"practice_{who}_call_and_response.wav"), np.concatenate(parts))
    lines += ["", "Free talk for a voice model (optional): 5-10 min per character in voice.",
              "These clips come from your own ROM: practice only, do not share or commit them."]
    open(os.path.join(out, "SCRIPT.txt"), "w", encoding="utf8").write("\n".join(lines))
    print(f"practice pack: {len(L)} clips, tracks {sorted(tracks)} -> {out}")


if __name__ == "__main__":
    main(sys.argv)
