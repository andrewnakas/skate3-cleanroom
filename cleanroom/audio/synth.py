"""Small deterministic synthesiser for graybox instruments and effects.

All output is mono float32 in [-1, 1] at the requested rate.
"""
import numpy as np


def periodic(period: int, harmonics, cycles: int, phase_seed=0) -> np.ndarray:
    """`cycles` repetitions of one waveform period built from harmonic
    amplitudes; loops seamlessly on any whole number of periods."""
    t = np.arange(period * cycles, dtype=np.float64) / period
    rng = np.random.default_rng(phase_seed)
    out = np.zeros_like(t)
    for k, a in enumerate(harmonics, start=1):
        if a:
            out += a * np.sin(2 * np.pi * k * t + rng.uniform(0, 0.3))
    peak = np.max(np.abs(out)) or 1.0
    return (out / peak).astype(np.float32)


def noise(n: int, seed: int, color: float = 0.0) -> np.ndarray:
    """White noise, optionally low-passed (color in 0..0.99)."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(-1, 1, n)
    if color:
        y = np.empty_like(x)
        acc = 0.0
        for i in range(n):
            acc = color * acc + (1 - color) * x[i]
            y[i] = acc
        x = y / (np.max(np.abs(y)) or 1)
    return x.astype(np.float32)


def highpass(x: np.ndarray, amount: float = 0.9) -> np.ndarray:
    y = np.empty_like(x)
    prev_x = prev_y = 0.0
    for i, v in enumerate(x):
        prev_y = amount * (prev_y + v - prev_x)
        prev_x = v
        y[i] = prev_y
    return y / (np.max(np.abs(y)) or 1)


def env_ad(n: int, attack: int, decay_rate: float) -> np.ndarray:
    e = np.ones(n, np.float32)
    a = min(attack, n)
    if a:
        e[:a] = np.linspace(0, 1, a, endpoint=False)
    t = np.arange(n - a, dtype=np.float32)
    e[a:] = np.exp(-t * decay_rate)
    return e


def sweep(n: int, rate: int, f0: float, f1: float) -> np.ndarray:
    f = np.geomspace(max(1.0, f0), max(1.0, f1), n)
    ph = np.cumsum(f) / rate
    return np.sin(2 * np.pi * ph).astype(np.float32)


def to_pcm16be(x: np.ndarray, gain: float = 0.8) -> bytes:
    return (np.clip(x * gain, -1, 1) * 32767).astype(">i2").tobytes()
