"""N64 texel formats: encode/decode between RGBA8 numpy arrays and TMEM bytes.

fmt: 0=RGBA 1=YUV 2=CI 3=IA 4=I ; siz: 0=4b 1=8b 2=16b 3=32b (gbi.h G_IM_*).
"""
import numpy as np

RGBA, YUV, CI, IA, I = range(5)
B4, B8, B16, B32 = range(4)
BITS = {B4: 4, B8: 8, B16: 16, B32: 32}
FMT_NAMES = {RGBA: "RGBA", YUV: "YUV", CI: "CI", IA: "IA", I: "I"}


def texel_bytes(w, h, siz):
    return (w * h * BITS[siz] + 7) // 8


def _pack4(v):
    v = np.asarray(v, dtype=np.uint8).ravel()
    if len(v) % 2:
        v = np.append(v, 0)
    return ((v[0::2] << 4) | (v[1::2] & 0xF)).astype(np.uint8).tobytes()


def _unpack4(b, n):
    a = np.frombuffer(b, dtype=np.uint8)
    out = np.empty(len(a) * 2, dtype=np.uint8)
    out[0::2] = a >> 4
    out[1::2] = a & 0xF
    return out[:n]


def _luma(rgba):
    return (rgba[..., 0] * 0.299 + rgba[..., 1] * 0.587 + rgba[..., 2] * 0.114)


def encode(rgba: np.ndarray, fmt: int, siz: int, palette=None) -> bytes:
    """rgba: (h, w, 4) uint8. For CI, `palette` is (n, 4) uint8 and rgba is
    ignored in favour of an index array passed as rgba[..., 0]."""
    rgba = np.asarray(rgba, dtype=np.uint8)
    h, w = rgba.shape[:2]
    r = rgba[..., 0].astype(np.uint32)
    g = rgba[..., 1].astype(np.uint32)
    b = rgba[..., 2].astype(np.uint32)
    a = rgba[..., 3].astype(np.uint32)
    if fmt == RGBA and siz == B16:
        v = ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) | (a >= 128)
        return v.astype(">u2").tobytes()
    if fmt == RGBA and siz == B32:
        return np.stack([r, g, b, a], -1).astype(np.uint8).tobytes()
    if fmt == IA and siz == B16:
        return np.stack([_luma(rgba), a], -1).astype(np.uint8).tobytes()
    if fmt == IA and siz == B8:
        return (((_luma(rgba).astype(np.uint32) >> 4) << 4) | (a >> 4)).astype(np.uint8).tobytes()
    if fmt == IA and siz == B4:
        return _pack4(((_luma(rgba).astype(np.uint32) >> 5) << 1) | (a >= 128))
    if fmt == I and siz == B8:
        return _luma(rgba).astype(np.uint8).tobytes()
    if fmt == I and siz == B4:
        return _pack4(_luma(rgba).astype(np.uint32) >> 4)
    if fmt == CI and siz == B8:
        return rgba[..., 0].astype(np.uint8).tobytes()
    if fmt == CI and siz == B4:
        return _pack4(rgba[..., 0] & 0xF)
    raise ValueError(f"unsupported format {fmt}/{siz}")


def decode(data: bytes, w: int, h: int, fmt: int, siz: int, palette=None) -> np.ndarray:
    n = w * h
    out = np.zeros((n, 4), dtype=np.uint8)
    if fmt == RGBA and siz == B16:
        v = np.frombuffer(data[:n * 2], dtype=">u2").astype(np.int64)
        out[:, 0] = ((v >> 11) & 31) * 255 // 31
        out[:, 1] = ((v >> 6) & 31) * 255 // 31
        out[:, 2] = ((v >> 1) & 31) * 255 // 31
        out[:, 3] = (v & 1) * 255
    elif fmt == RGBA and siz == B32:
        out[:] = np.frombuffer(data[:n * 4], dtype=np.uint8).reshape(n, 4)
    elif fmt == IA and siz == B16:
        v = np.frombuffer(data[:n * 2], dtype=np.uint8).reshape(n, 2)
        out[:, 0] = out[:, 1] = out[:, 2] = v[:, 0]
        out[:, 3] = v[:, 1]
    elif fmt == IA and siz == B8:
        v = np.frombuffer(data[:n], dtype=np.uint8).astype(np.int32)
        out[:, 0] = out[:, 1] = out[:, 2] = (v >> 4) * 17
        out[:, 3] = (v & 15) * 17
    elif fmt == IA and siz == B4:
        v = _unpack4(data, n).astype(np.int32)
        out[:, 0] = out[:, 1] = out[:, 2] = (v >> 1) * 255 // 7
        out[:, 3] = (v & 1) * 255
    elif fmt == I and siz == B8:
        v = np.frombuffer(data[:n], dtype=np.uint8)
        out[:, 0] = out[:, 1] = out[:, 2] = out[:, 3] = v
    elif fmt == I and siz == B4:
        v = _unpack4(data, n).astype(np.int32) * 17
        out[:, 0] = out[:, 1] = out[:, 2] = out[:, 3] = v
    elif fmt == CI:
        idx = (np.frombuffer(data[:n], dtype=np.uint8) if siz == B8 else _unpack4(data, n))
        if palette is None:
            out[:, 0] = out[:, 1] = out[:, 2] = idx
            out[:, 3] = 255
        else:
            out[:] = np.asarray(palette, dtype=np.uint8)[idx]
    else:
        raise ValueError(f"unsupported format {fmt}/{siz}")
    return out.reshape(h, w, 4)
