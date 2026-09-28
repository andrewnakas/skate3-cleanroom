"""Pitch (f0) tracking, YIN-style: per-frame f0 of voiced frames."""
import numpy as np


def f0_track(x, sr, fmin=70, fmax=900, frame=0.04, hop=0.01, thresh=0.25):
    n, h = int(frame * sr), int(hop * sr)
    tau_max = int(sr / fmin)
    lo = int(sr / fmax)
    out = []
    for s in range(0, len(x) - n - tau_max, h):
        fr = x[s:s + n + tau_max]
        if np.sqrt((fr[:n] ** 2).mean()) < 0.01:
            continue
        d = np.array([((fr[:n] - fr[t:t + n]) ** 2).sum() for t in range(1, tau_max)])
        cmnd = d * np.arange(1, tau_max) / (np.cumsum(d) + 1e-9)
        k = lo + int(np.argmin(cmnd[lo:]))
        if cmnd[k] < thresh:
            out.append(sr / (k + 1))
    return np.array(out)


def median_f0(x, sr):
    f = f0_track(x, sr)
    return float(np.median(f)) if len(f) >= 3 else None
