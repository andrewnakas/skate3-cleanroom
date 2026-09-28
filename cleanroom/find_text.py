"""DIRTY ROOM helper: rank decoded images by how much they look like text.

Text in N64 UI art is small, high contrast, wider than tall, and has many
short strokes: lots of on/off transitions along rows, glyph-sized gaps
between columns of ink. The score is a heuristic for ordering a contact
sheet that a person transcribes into a label table; it decides nothing
itself and nothing it produces goes into clean outputs.
"""
import numpy as np


def _inks(rgba):
    """Candidate ink masks: opaque pixels (alpha-cut art), bright pixels
    inside the opaque area (outlined text), pixels far from the dominant
    tone (text painted on a panel)."""
    a = rgba[..., 3].astype(np.float32)
    lum = rgba[..., :3].astype(np.float32) @ np.array([0.3, 0.59, 0.11], np.float32)
    opaque = a > 128
    out = [np.abs(lum - np.median(lum)) > 60]
    if 0.02 < opaque.mean() < 0.98:
        out.append(opaque)
        l = lum[opaque]
        out.append(opaque & (lum > (l.min() + l.max()) / 2))
    return out


def _score(ink, h, w):
    cover = ink.mean()
    if not 0.08 < cover < 0.6:
        return 0.0
    trans = np.abs(np.diff(ink.astype(np.int8), axis=1)).sum(1)      # per row
    rows = trans[ink.any(1)]
    if not len(rows):
        return 0.0
    per_char = rows.mean() / max(1.0, w / max(4.0, h * 0.7))         # transitions per glyph width
    gaps = np.abs(np.diff(ink.any(0).astype(np.int8))).sum() / 2     # ink runs along x
    aspect = min(w / h, 12) / 12
    return float(np.clip(per_char / 4, 0, 1) * 0.5 + np.clip(gaps / 12, 0, 1) * 0.3 + aspect * 0.2)


def text_score(rgba) -> float:
    h, w = rgba.shape[:2]
    if h < 5 or w < 8 or h > 64:
        return 0.0
    return max(_score(ink, h, w) for ink in _inks(rgba))


def contact_sheet(items, scale=4, width=1400, pad=6):
    """items: list of (key, rgba). Returns (sheet rgba, placements) where
    placements maps key -> (x, y, w, h) so a caller can annotate."""
    x = y = rowh = 0
    place = {}
    tiles = []
    for key, im in items:
        big = np.repeat(np.repeat(im, scale, 0), scale, 1)
        hh, ww = big.shape[:2]
        if x and x + ww > width:
            x, y, rowh = 0, y + rowh + pad, 0
        place[key] = (x, y, ww, hh)
        tiles.append((x, y, big))
        x += ww + pad
        rowh = max(rowh, hh)
    sheet = np.zeros((y + rowh + pad, width, 4), np.uint8)
    sheet[..., :3] = (0, 60, 90)
    sheet[..., 3] = 255
    for x0, y0, big in tiles:
        hh, ww = big.shape[:2]
        ww = min(ww, width - x0)
        a = big[:, :ww, 3:4].astype(np.float32) / 255
        region = sheet[y0:y0 + hh, x0:x0 + ww, :3].astype(np.float32)
        sheet[y0:y0 + hh, x0:x0 + ww, :3] = (region * (1 - a) + big[:, :ww, :3] * a).astype(np.uint8)
    return sheet, place
