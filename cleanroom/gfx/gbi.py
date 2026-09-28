"""Minimal F3D/F3DEX GBI command decoding (texture state only)."""
import struct

G_SETTIMG = 0xFD
G_SETTILE = 0xF5
G_SETTILESIZE = 0xF2
G_LOADBLOCK = 0xF3
G_LOADTLUT = 0xF0


def words(cmd: bytes):
    return struct.unpack(">II", cmd)


def render_tiles(dlist):
    """Decode render tiles (tile != 7, the load tile) from a list of 8-byte
    commands. Returns dicts with fmt, siz, line (in 64-bit words), tmem (in
    64-bit words), dims from G_SETTILESIZE and wrap/mask fields."""
    tiles = {}
    for c in dlist:
        w0, w1 = words(c)
        op = w0 >> 24
        if op == G_SETTILE:
            t = (w1 >> 24) & 7
            tiles.setdefault(t, {}).update(
                tile=t, fmt=(w0 >> 21) & 7, siz=(w0 >> 19) & 3,
                line=(w0 >> 9) & 0x1FF, tmem=w0 & 0x1FF, palette=(w1 >> 20) & 0xF,
                cmt=(w1 >> 18) & 3, maskt=(w1 >> 14) & 0xF, shiftt=(w1 >> 10) & 0xF,
                cms=(w1 >> 8) & 3, masks=(w1 >> 4) & 0xF, shifts=w1 & 0xF)
        elif op == G_SETTILESIZE:
            t = (w1 >> 24) & 7
            uls, ult = (w0 >> 12) & 0xFFF, w0 & 0xFFF
            lrs, lrt = (w1 >> 12) & 0xFFF, w1 & 0xFFF
            tiles.setdefault(t, {}).update(
                width=((lrs - uls) >> 2) + 1, height=((lrt - ult) >> 2) + 1)
    return [tiles[k] for k in sorted(tiles) if k != 7 and "fmt" in tiles[k] and "width" in tiles[k]]


def settimg_list(dlist):
    out = []
    for c in dlist:
        w0, w1 = words(c)
        if w0 >> 24 == G_SETTIMG:
            out.append(dict(fmt=(w0 >> 21) & 7, siz=(w0 >> 19) & 3,
                            width=(w0 & 0xFFF) + 1, addr=w1))
    return out
