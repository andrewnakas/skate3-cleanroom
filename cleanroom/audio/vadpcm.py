"""N64 VADPCM encoder/decoder (4-bit, 16 samples per 9-byte frame).

Frame: header byte (scale << 4 | predictor), then 16 signed 4-bit residuals.
Each 8-sample group is reconstructed from the two previous output samples
and the residuals with a codebook entry of two 8-tap vectors (order 2):

    y[i] = ( r[i]*2048 + b0[i]*y[-2] + b1[i]*y[-1] + sum_{k<i} b1[i-1-k]*r[k] ) >> 11
    r[k] = nibble[k] << scale

The codebook here is designed by us: a fixed family of 2-pole predictors
(b0/b1 are their impulse responses), chosen per frame by closed-loop search.
"""
import numpy as np

ORDER = 2
# (a1, a2): y[n] ~ a1*y[n-1] + a2*y[n-2]
PREDICTORS = [(0.0, 0.0), (1.0, 0.0), (1.8, -0.82), (1.95, -0.96)]


def _vectors(a1, a2):
    """Impulse responses (x2048) of the recursion to y[-2] and y[-1]."""
    def run(ym2, ym1):
        out = []
        p2, p1 = ym2, ym1
        for _ in range(8):
            v = a1 * p1 + a2 * p2
            out.append(v)
            p2, p1 = p1, v
        return out
    b0 = run(1.0, 0.0)
    b1 = run(0.0, 1.0)
    q = lambda v: int(max(-32768, min(32767, round(v * 2048))))
    return [q(v) for v in b0], [q(v) for v in b1]


def make_book(predictors=PREDICTORS):
    book = []
    for a1, a2 in predictors:
        b0, b1 = _vectors(a1, a2)
        book.extend(b0)
        book.extend(b1)
    return {"order": ORDER, "npred": len(predictors), "book": book}


def _entries(book):
    b = np.asarray(book["book"], dtype=np.int64).reshape(book["npred"], ORDER, 8)
    return b


def _group(b0, b1, r, y2, y1):
    out = np.empty(8, dtype=np.int64)
    for i in range(8):
        acc = (r[i] << 11) + b0[i] * y2 + b1[i] * y1
        for k in range(i):
            acc += b1[i - 1 - k] * r[k]
        out[i] = max(-32768, min(32767, acc >> 11))
    return out


def decode(data: bytes, book, nsamples=None):
    ent = _entries(book)
    y2 = y1 = 0
    out = []
    for f in range(0, len(data) - 8, 9):
        hdr = data[f]
        scale, pred = hdr >> 4, hdr & 0xF
        nib = []
        for b in data[f + 1:f + 9]:
            nib += [b >> 4, b & 0xF]
        nib = [n - 16 if n >= 8 else n for n in nib]
        for g in range(2):
            r = [n << scale for n in nib[g * 8:g * 8 + 8]]
            o = _group(ent[pred][0], ent[pred][1], r, y2, y1)
            out.extend(o.tolist())
            y2, y1 = int(o[6]), int(o[7])
    out = np.asarray(out, dtype=np.int16)
    return out[:nsamples] if nsamples else out


def _encode_group(b0, b1, target, y2, y1, scale):
    """Greedy closed-loop quantisation of 8 samples. Returns nibbles, outputs, err."""
    r = [0] * 8
    nib = [0] * 8
    out = np.empty(8, dtype=np.int64)
    err = 0
    for i in range(8):
        acc = b0[i] * y2 + b1[i] * y1
        for k in range(i):
            acc += b1[i - 1 - k] * r[k]
        pred = acc / 2048.0
        want = (target[i] - pred) / (1 << scale)
        n = int(max(-8, min(7, round(want))))
        # Avoid 16-bit wrap after clamping by nudging towards zero if needed.
        while True:
            val = (acc + ((n << scale) << 11)) >> 11
            if -32768 <= val <= 32767 or n == 0:
                break
            n += -1 if n > 0 else 1
        nib[i] = n
        r[i] = n << scale
        out[i] = max(-32768, min(32767, (acc + (r[i] << 11)) >> 11))
        err += (int(out[i]) - int(target[i])) ** 2
    return nib, out, err


def _encode_group_vec(b0, b1, shift, target, y2, y1):
    """Vectorised _encode_group over C candidates (arrays of shape (C, 8)/(C,))."""
    C = b0.shape[0]
    r = np.zeros((C, 8), dtype=np.int64)
    nib = np.zeros((C, 8), dtype=np.int64)
    out = np.zeros((C, 8), dtype=np.int64)
    err = np.zeros(C, dtype=np.int64)
    step = (np.int64(1) << shift)
    for i in range(8):
        acc = b0[:, i] * y2 + b1[:, i] * y1
        for k in range(i):
            acc = acc + b1[:, i - 1 - k] * r[:, k]
        want = (target[i] - acc / 2048.0) / step
        n = np.clip(np.round(want), -8, 7).astype(np.int64)
        for _ in range(8):
            val = (acc + ((n << shift) << 11)) >> 11
            bad = ((val < -32768) | (val > 32767)) & (n != 0)
            if not bad.any():
                break
            n = np.where(bad, n - np.sign(n), n)
        nib[:, i] = n
        r[:, i] = n << shift
        o = np.clip((acc + (r[:, i] << 11)) >> 11, -32768, 32767)
        out[:, i] = o
        err += (o - int(target[i])) ** 2
    return nib, out, err


def encode(samples, book=None):
    """samples: int16-range ints. Returns (bytes, book, decoded int16 array)."""
    book = book or make_book()
    ent = _entries(book)
    npred = book["npred"]
    preds = np.repeat(np.arange(npred), 13)
    scales = np.tile(np.arange(13), npred).astype(np.int64)
    b0 = ent[preds, 0, :]
    b1 = ent[preds, 1, :]
    x = np.asarray(samples, dtype=np.int64)
    pad = (-len(x)) % 16
    x = np.concatenate([x, np.zeros(pad, dtype=np.int64)])
    out = bytearray()
    dec = np.zeros(len(x), dtype=np.int64)
    y2 = y1 = 0
    C = len(preds)
    for f in range(0, len(x), 16):
        frame = x[f:f + 16]
        n0, o0, e0 = _encode_group_vec(b0, b1, scales, frame[:8], np.full(C, y2), np.full(C, y1))
        n1, o1, e1 = _encode_group_vec(b0, b1, scales, frame[8:], o0[:, 6], o0[:, 7])
        c = int(np.argmin(e0 + e1))
        out.append((int(scales[c]) << 4) | int(preds[c]))
        nib = np.concatenate([n0[c], n1[c]])
        for i in range(0, 16, 2):
            out.append(((int(nib[i]) & 0xF) << 4) | (int(nib[i + 1]) & 0xF))
        dec[f:f + 8] = o0[c]
        dec[f + 8:f + 16] = o1[c]
        y2, y1 = int(o1[c][6]), int(o1[c][7])
    return bytes(out), book, dec.astype(np.int16)


def loop_state(decoded, start):
    """ADPCM_STATE for a loop starting at a multiple of 16: the 16 decoded
    samples preceding it (the decoder only needs the last two)."""
    s = np.zeros(16, dtype=np.int64)
    if start >= 16:
        s[:] = decoded[start - 16:start]
    return [int(v) for v in s]
