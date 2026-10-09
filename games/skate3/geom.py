"""Regenerate the mesh data of SKATE14 maps (visual geometry, collision container, manifest).

    python -m games.skate3.geom <pack dir> [--only substr] [--dry]

Rewrites every SKATE14 file under <pack dir> in place (maps, native-props,
native-backdrops). Newer containers (SKATE15: the author's own maps) are left
alone. Textures are not touched here (skate14.py does those).

Visual geometry. Kept as fact: the surface (to 0.4 mm), which material covers
it, where the texture and lightmap land on it (to 1/3000 and 1/12000 of a tile),
and whether an edge is smooth or hard. Regenerated from that:
  positions      snapped to our own lattice (0.37 mm; coarser far from the origin)
  tessellation   every flat or nearly flat quad that can take the other diagonal gets it
  normals        recomputed from the triangles (angle weighted over the smooth
                 neighbourhood); authored normals that are not the surface normal
                 (foliage, bent normals) are kept only as a 10-bit octahedral direction
  tangent frames recomputed from the triangles and UVs
  UVs            snapped to our own lattice
  order          triangle corners rotated, vertices renumbered (first use, shuffled
                 in blocks of 256), unreferenced vertices dropped

Collision. The skating depends on the exact collision triangles, edge codes and
surface ids, so those values are kept as facts, but the retail container is not:
each cluster is re-encoded (own header, own vertex order, plain float vertices)
and everything the engine does not read (retail headers, spatial tree, mesh
names, padding) is dropped. Decoding old and new gives the same triangle list bit for bit.

Manifest (WMET). Only the rail identities the engine checks are kept; stream
names, source offsets, asset tables and local paths are dropped.
"""
import hashlib
import json
import os
import struct
import sys
import time
import zlib

import numpy as np

VERT = np.dtype([('p', '<f4', (3,)), ('n', '<f4', (3,)), ('uv', '<f4', (2,)), ('lm', '<f4', (2,)),
                 ('mat', '<u4'), ('decal', '<f4', (2,)), ('frame', 'i1', (4,))])
assert VERT.itemsize == 56

PITCH = 0.00037
OFFSET = np.array([0.00011, 0.00017, 0.00005])
UV_STEPS, UV_OFF = 3000.0, 1.0 / 7000.0
LM_STEPS, LM_OFF = 12000.0, 1.0 / 29000.0
FLIP_COS = np.cos(np.radians(3.0))      # the two triangles of a quad must be this flat
FLIP_PLANE = 0.006                      # and the fourth corner this close to the plane (m)
SMOOTH_COS = np.cos(np.radians(55.0))   # faces that belong to a vertex's smooth neighbourhood
KEEP_COS = np.cos(np.radians(30.0))     # authored normal further than this from ours: keep its direction
MARK = "regenerated-v1"                # written into the manifest; a marked file is not processed again
RAIL_KEYS = ("stream_file", "asset_id", "section_index", "section_offset", "rail_index", "spline_id",
             "segment_count", "type_signature", "flags", "trailing_word", "closed")


def seed(key):
    return int.from_bytes(hashlib.sha1(("geom/" + key).encode()).digest()[:8], "little")


def unit(a):
    return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-30)


# ---------------------------------------------------------------- positions / uvs

def snap_positions(p, base=PITCH):
    """float64 Nx3 -> (float32 Nx3 on our lattice, int64 lattice keys)."""
    mag = np.maximum(np.abs(p), 1e-9)
    k = np.maximum(0, np.ceil(np.log2(mag / 512.0))).astype(np.int64)
    pitch = base * (2.0 ** k)
    q = np.rint((p - OFFSET) / pitch)
    return (q * pitch + OFFSET).astype('<f4'), (q.astype(np.int64) * 64 + k)


def snap_uv(uv, steps, off):
    return (np.rint((uv.astype(np.float64) - off) * steps) / steps + off).astype('<f4')


# ---------------------------------------------------------------- tessellation

def _quality(a, b, c):
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) * 0.5
    edges = ((b - a) ** 2).sum(1) + ((c - b) ** 2).sum(1) + ((a - c) ** 2).sum(1)
    return 4.0 * np.sqrt(3.0) * area / np.maximum(edges, 1e-30), area


def flip_round(P, idx, done, rng, plane=FLIP_PLANE):
    """One round of diagonal flips on quads made of two triangles that share an
    edge by index (so every attribute is continuous across it). Returns count."""
    T = len(idx)
    nv = np.uint64(len(P))
    e_from = idx.ravel()
    e_to = idx[:, [1, 2, 0]].ravel()
    e_opp = idx[:, [2, 0, 1]].ravel()
    tri = np.repeat(np.arange(T), 3)
    key = np.minimum(e_from, e_to).astype(np.uint64) * nv + np.maximum(e_from, e_to).astype(np.uint64)
    order = np.argsort(key, kind='stable')
    ks = key[order]
    start = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
    count = np.diff(np.r_[start, len(ks)])
    two = start[count == 2]
    e1, e2 = order[two], order[two + 1]
    ok = (e_from[e1] == e_to[e2]) & (e_to[e1] == e_from[e2])
    e1, e2 = e1[ok], e2[ok]
    t1, t2 = tri[e1], tri[e2]
    a, b, c, d = e_from[e1], e_to[e1], e_opp[e1], e_opp[e2]
    ok = (t1 != t2) & (c != d) & ~done[t1] & ~done[t2]
    # the new diagonal must not already be an edge
    new_key = np.minimum(c, d).astype(np.uint64) * nv + np.maximum(c, d).astype(np.uint64)
    uniq = ks[start]
    at = np.searchsorted(uniq, new_key)
    ok &= ~((at < len(uniq)) & (uniq[np.minimum(at, len(uniq) - 1)] == new_key))
    pa, pb, pc, pd = P[a], P[b], P[c], P[d]
    n1 = np.cross(pb - pa, pc - pa)
    n2 = np.cross(pa - pb, pd - pb)
    l1, l2 = np.linalg.norm(n1, axis=1), np.linalg.norm(n2, axis=1)
    ok &= (l1 > 1e-12) & (l2 > 1e-12)
    u1 = n1 / np.maximum(l1, 1e-30)[:, None]
    u2 = n2 / np.maximum(l2, 1e-30)[:, None]
    ok &= (u1 * u2).sum(1) > FLIP_COS
    ok &= np.abs(((pd - pa) * u1).sum(1)) < plane
    # new triangles (a, d, c) and (d, b, c): same facing, not much thinner
    m1 = np.cross(pd - pa, pc - pa)
    m2 = np.cross(pb - pd, pc - pd)
    ok &= ((m1 * u1).sum(1) > 0) & ((m2 * u1).sum(1) > 0)
    q_old = np.minimum(_quality(pa, pb, pc)[0], _quality(pb, pa, pd)[0])
    qa, area_a = _quality(pa, pd, pc)
    qb, area_b = _quality(pd, pb, pc)
    ok &= (np.minimum(qa, qb) >= 0.5 * q_old) & (np.minimum(area_a, area_b) > 1e-10)
    sel = np.flatnonzero(ok)
    if not len(sel):
        return 0
    t1, t2, a, b, c, d = t1[sel], t2[sel], a[sel], b[sel], c[sel], d[sel]
    prio = rng.random(len(sel))
    best = np.full(T, -1.0)
    np.maximum.at(best, t1, prio)
    np.maximum.at(best, t2, prio)
    win = (prio == best[t1]) & (prio == best[t2])
    t1, t2, a, b, c, d = t1[win], t2[win], a[win], b[win], c[win], d[win]
    idx[t1] = np.stack([a, d, c], 1)
    idx[t2] = np.stack([d, b, c], 1)
    done[t1] = True
    done[t2] = True
    return len(t1)


# ---------------------------------------------------------------- normals / tangents

def oct_quantise(n, bits=10):
    """Unit vectors -> the same direction rounded to a bits-per-axis octahedral grid."""
    n = unit(n.astype(np.float64))
    s = np.abs(n).sum(1, keepdims=True)
    o = n[:, :2] / np.maximum(s, 1e-30)
    neg = n[:, 2] < 0
    wrap = (1.0 - np.abs(o[:, ::-1])) * np.where(o >= 0, 1.0, -1.0)
    o = np.where(neg[:, None], wrap, o)
    scale = (1 << bits) - 1
    o = np.rint((o * 0.5 + 0.5) * scale) / scale * 2.0 - 1.0
    z = 1.0 - np.abs(o).sum(1)
    xy = np.where((z < 0)[:, None], (1.0 - np.abs(o[:, ::-1])) * np.where(o >= 0, 1.0, -1.0), o)
    return unit(np.column_stack([xy, z]))


def corner_data(P, idx):
    """Per corner: unit face normal and interior angle (0 for degenerate faces)."""
    a, b, c = P[idx[:, 0]], P[idx[:, 1]], P[idx[:, 2]]
    fn = np.cross(b - a, c - a)
    ln = np.linalg.norm(fn, axis=1)
    good = ln > 1e-14
    fn = fn / np.maximum(ln, 1e-30)[:, None]
    angles = np.empty((len(idx), 3))
    for k, (o, p, q) in enumerate(((a, b, c), (b, c, a), (c, a, b))):
        u, v = unit(p - o), unit(q - o)
        angles[:, k] = np.arccos(np.clip((u * v).sum(1), -1.0, 1.0))
    angles[~good] = 0.0
    return fn, angles


def new_normals(P, idx, pid, authored):
    """Angle-weighted normals over each vertex's smooth neighbourhood: all faces
    touching the same point whose normal is within 55 degrees of the authored
    one (that is the smooth/hard fact). Returns (normals, kept_authored mask)."""
    fn, angles = corner_data(P, idx)
    cp = pid[idx.ravel()]
    cn = np.repeat(fn, 3, axis=0)
    cw = angles.ravel()
    order = np.argsort(cp, kind='stable')
    cp, cn, cw = cp[order], cn[order], cw[order]
    npid = int(pid.max()) + 1 if len(pid) else 0
    cstart = np.searchsorted(cp, np.arange(npid))
    ccount = np.searchsorted(cp, np.arange(npid), side='right') - cstart
    auth = unit(authored.astype(np.float64))
    out = np.zeros((len(P), 3))
    per = ccount[pid]
    step = 400_000
    for lo in range(0, len(P), step):
        hi = min(len(P), lo + step)
        n = per[lo:hi]
        total = int(n.sum())
        if not total:
            continue
        v = np.repeat(np.arange(lo, hi), n)
        first = np.repeat(np.cumsum(n) - n, n)
        k = np.repeat(cstart[pid[lo:hi]], n) + (np.arange(total) - first)
        w = cw[k] * ((cn[k] * auth[v]).sum(1) > SMOOTH_COS)
        for axis in range(3):
            out[lo:hi, axis] = np.bincount(v - lo, weights=w * cn[k, axis], minlength=hi - lo)
    length = np.linalg.norm(out, axis=1)
    ours = out / np.maximum(length, 1e-30)[:, None]
    keep = (length < 1e-9) | ((ours * auth).sum(1) < KEEP_COS)
    ours[keep] = oct_quantise(auth[keep]) if keep.any() else ours[keep]
    return ours.astype('<f4'), keep


def new_frames(P, idx, normals, uv, old_frame):
    """Tangent frames (binormal*127, handedness*127) from triangles and UVs, for
    the vertices that had one. Convention checked against the engine's writer:
    binormal = cross(normal, tangent) * handedness."""
    has = (old_frame != 0).any(1)
    frame = np.zeros_like(old_frame)
    if not has.any():
        return frame, 0
    a, b, c = P[idx[:, 0]], P[idx[:, 1]], P[idx[:, 2]]
    ua, ub, uc = (uv[idx[:, k]].astype(np.float64) for k in range(3))
    e1, e2 = b - a, c - a
    d1, d2 = ub - ua, uc - ua
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    good = np.abs(det) > 1e-14
    r = np.where(good, 1.0 / np.where(good, det, 1.0), 0.0)[:, None]
    tan = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r
    bit = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r
    _, angles = corner_data(P, idx)
    T = np.zeros((len(P), 3))
    B = np.zeros((len(P), 3))
    w = angles.ravel()[:, None]
    np.add.at(T, idx.ravel(), np.repeat(unit(tan), 3, axis=0) * w)
    np.add.at(B, idx.ravel(), np.repeat(unit(bit), 3, axis=0) * w)
    n = normals.astype(np.float64)
    t = T - n * (T * n).sum(1, keepdims=True)
    tl = np.linalg.norm(t, axis=1)
    t = t / np.maximum(tl, 1e-30)[:, None]
    # The stored v axis is flipped (1 - v), hence the sign (checked against the
    # frames the engine's writer produces: 93-100% agree).
    sign = np.sign((np.cross(n, t) * B).sum(1))
    sign[sign == 0] = 1.0
    binormal = np.cross(n, t) * sign[:, None]
    ok = has & (tl > 1e-9)
    frame[ok, :3] = np.rint(np.clip(binormal[ok], -1, 1) * 127).astype('i1')
    frame[ok, 3] = np.rint(sign[ok] * 127).astype('i1')
    fallback = has & ~ok
    frame[fallback] = old_frame[fallback]
    return frame, int(fallback.sum())


# ---------------------------------------------------------------- visual mesh

def regen_mesh(v, idx, key, pitch=PITCH, plane=FLIP_PLANE, uv_steps=UV_STEPS):
    """v: VERT array, idx: Tx3 uint32. Returns (new v, new idx, stats);
    stats["source"] maps each new vertex to the one it came from."""
    stats = {"verts": len(v), "tris": len(idx)}
    if not len(v) or not len(idx):
        return v, idx, stats
    rng = np.random.default_rng(seed(key))
    P = v['p'].astype(np.float64)
    idx = idx.astype(np.int64).copy()

    done = np.zeros(len(idx), bool)
    flipped = 0
    for _ in range(4):
        n = flip_round(P, idx, done, rng, plane)
        flipped += n
        if not n:
            break
    stats["tris_retessellated"] = flipped * 2

    snapped, lattice = snap_positions(P, pitch)
    _, pid = np.unique(lattice, axis=0, return_inverse=True)
    pid = pid.reshape(-1)
    normals, kept = new_normals(P, idx, pid, v['n'])
    stats["normals_kept_direction"] = int(kept.sum())

    uv = snap_uv(v['uv'], uv_steps, UV_OFF)
    lm = np.where((v['lm'] == v['uv']).all(1)[:, None], uv, snap_uv(v['lm'], LM_STEPS, LM_OFF))
    decal = np.where((v['decal'] == v['uv']).all(1)[:, None], uv, snap_uv(v['decal'], uv_steps, UV_OFF))
    frame, frame_fallback = new_frames(P, idx, normals, v['uv'], v['frame'])
    stats["frames_kept"] = frame_fallback

    # rotate corners, renumber vertices (first-use order keeps them local for the
    # GPU; the shuffle inside each block of 256 makes the numbers our own), drop
    # unreferenced ones
    rot = rng.integers(0, 3, len(idx))
    idx = np.stack([np.take_along_axis(idx, ((rot + k) % 3)[:, None], 1)[:, 0] for k in range(3)], 1)
    flat = idx.ravel()
    _, first = np.unique(flat, return_index=True)
    used = flat[np.sort(first)]
    for lo in range(0, len(used), 256):
        rng.shuffle(used[lo:lo + 256])
    remap = np.full(len(v), -1, np.int64)
    remap[used] = np.arange(len(used))
    out = np.zeros(len(used), VERT)
    out['p'] = snapped[used]
    out['n'] = normals[used]
    out['uv'] = uv[used]
    out['lm'] = lm[used]
    out['mat'] = v['mat'][used]
    out['decal'] = decal[used]
    out['frame'] = frame[used]
    new_idx = remap[idx].astype('<u4')
    stats["verts_out"] = len(out)
    stats["source"] = used
    stats["max_shift_mm"] = float(np.abs(snapped.astype(np.float64) - P)[used].max() * 1000.0)
    return out, new_idx, stats


# ---------------------------------------------------------------- skinned model (GLB)

GLB_MARK = "geometry " + "regenerated-v1"
GLB_PITCH = 0.00013        # the skater is 1.8 m tall; 0.13 mm lattice
GLB_PLANE = 0.0005
GLB_UV_STEPS = 6000.0
_GL = {5121: 'u1', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
_WIDTH = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def glb_parts(path):
    b = open(path, 'rb').read()
    if b[:4] != b'glTF':
        raise ValueError("not a GLB")
    jl = struct.unpack_from('<I', b, 12)[0]
    j = json.loads(b[20:20 + jl])
    off = 20 + jl
    bl = struct.unpack_from('<I', b, off)[0]
    return j, b[off + 8:off + 8 + bl]


def glb_array(j, binc, index):
    acc = j['accessors'][index]
    view = j['bufferViews'][acc['bufferView']]
    if view.get('byteStride') or acc.get('sparse'):
        raise ValueError("interleaved or sparse accessors are not supported")
    width = _WIDTH[acc['type']]
    start = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
    a = np.frombuffer(binc, _GL[acc['componentType']], acc['count'] * width, start)
    return a.reshape(acc['count'], width) if width > 1 else a


def glb_mesh_accessors(j):
    """Accessor indices that hold mesh data (not skins or animations)."""
    out = set()
    for m in j.get('meshes', []):
        for pr in m['primitives']:
            out.update(pr['attributes'].values())
            if 'indices' in pr:
                out.add(pr['indices'])
    return out


def snap_weights(w):
    """Skin weights on our own lattice (1/1021), still summing to one. The
    largest weight of each vertex absorbs the rounding (at most 0.2%)."""
    q = np.rint(w.astype(np.float64) * 1021.0) / 1021.0
    top = np.argmax(q, axis=1)
    rows = np.arange(len(q))
    q[rows, top] = 0.0
    q[rows, top] = 1.0 - q.sum(1)
    return q.astype('<f4')


def rewrite_glb(src, dst, key):
    """Regenerate the meshes of a skinned GLB: same treatment as the maps
    (lattice, diagonals, normals, UVs, order). Joints follow their vertices,
    weights are re-quantised; the skeleton and materials are not touched."""
    j, binc = glb_parts(src)
    if GLB_MARK in j['asset'].get('generator', ''):
        return {"already": True}
    views = j['bufferViews']
    owner = {}
    for i, acc in enumerate(j['accessors']):
        if 'bufferView' in acc:
            owner.setdefault(acc['bufferView'], []).append(i)
    new_view = {}
    stats = {"verts": 0, "tris": 0, "tris_retessellated": 0, "verts_out": 0, "normals_kept_direction": 0}
    number = 0
    for m in j.get('meshes', []):
        for pr in m['primitives']:
            if pr.get('mode', 4) != 4 or pr.get('targets') or 'indices' not in pr:
                raise ValueError("unsupported GLB primitive")
            att = pr['attributes']
            touched = list(att.values()) + [pr['indices']]
            if any(len(owner[j['accessors'][a]['bufferView']]) != 1 or j['accessors'][a].get('byteOffset', 0) for a in touched):
                raise ValueError("GLB accessors share buffer views")
            P = glb_array(j, binc, att['POSITION'])
            v = np.zeros(len(P), VERT)
            v['p'] = P
            v['n'] = glb_array(j, binc, att['NORMAL'])
            v['uv'] = v['lm'] = v['decal'] = glb_array(j, binc, att['TEXCOORD_0'])
            v['mat'] = 1
            idx = glb_array(j, binc, pr['indices']).reshape(-1, 3)
            v2, idx2, st = regen_mesh(v, idx, f"{key}#{number}", GLB_PITCH, GLB_PLANE, GLB_UV_STEPS)
            number += 1
            for k in ("verts", "tris", "tris_retessellated", "verts_out", "normals_kept_direction"):
                stats[k] += st.get(k, 0)
            src_of = st["source"]
            data = {'POSITION': v2['p'], 'NORMAL': v2['n'], 'TEXCOORD_0': v2['uv']}
            for name, a in att.items():
                acc = j['accessors'][a]
                arr = data[name] if name in data else glb_array(j, binc, a)[src_of]
                if name == 'WEIGHTS_0' and acc['componentType'] == 5126:
                    arr = snap_weights(arr)
                arr = np.ascontiguousarray(arr, _GL[acc['componentType']])
                acc['count'] = len(arr)
                if name == 'POSITION':
                    acc['min'] = [float(x) for x in arr.min(0)]
                    acc['max'] = [float(x) for x in arr.max(0)]
                new_view[acc['bufferView']] = arr.tobytes()
            acc = j['accessors'][pr['indices']]
            acc['count'] = idx2.size
            new_view[acc['bufferView']] = idx2.astype(_GL[acc['componentType']]).tobytes()
    order = sorted(range(len(views)), key=lambda k: views[k].get('byteOffset', 0))
    nb = bytearray()
    for k in order:
        view = views[k]
        data = new_view.get(k)
        if data is None:
            at = view.get('byteOffset', 0)
            data = binc[at:at + view['byteLength']]
        nb += b"\0" * ((-len(nb)) % 4)
        view['byteOffset'] = len(nb)
        view['byteLength'] = len(data)
        nb += data
    nb += b"\0" * ((-len(nb)) % 4)
    j['buffers'][0]['byteLength'] = len(nb)
    j['asset']['generator'] = (j['asset'].get('generator', '') + "; " + GLB_MARK).lstrip("; ")
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    out = struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(js) + 8 + len(nb))
    out += struct.pack('<I4s', len(js), b'JSON') + js + struct.pack('<I4s', len(nb), b'BIN\0') + bytes(nb)
    tmp = dst + ".tmp"
    open(tmp, 'wb').write(out)
    os.replace(tmp, dst)
    return stats


# ---------------------------------------------------------------- collision container

def _be16(d, at):
    return struct.unpack_from('>H', d, at)[0]


def _be32(d, at):
    return struct.unpack_from('>I', d, at)[0]


def rwcm_triangles(data):
    """Decode an RWCMSET1 archive the way the engine does (retail_collision.rs):
    list of (mesh name, one_sided, [clusters of (points float32 3x3, edges, group, surface)])."""
    if data[:8] != b"RWCMSET1":
        raise ValueError("not RWCMSET1")
    at = 8
    count = struct.unpack_from('<I', data, at)[0]; at += 4
    meshes = []
    for _ in range(count):
        n = struct.unpack_from('<I', data, at)[0]; at += 4
        name = data[at:at + n]; at += n
        size = struct.unpack_from('<I', data, at)[0]; at += 4
        mesh = data[at:at + size]; at += size
        meshes.append((name, *_mesh(mesh)))
    if at != len(data):
        raise ValueError("RWCM trailing bytes")
    return meshes


def _mesh(mesh):
    size = _be32(mesh, 80)
    d = mesh[:size]
    table, count = _be32(d, 52), _be32(d, 64)
    gran = struct.unpack_from('>f', d, 56)[0]
    head = {"gran_bits": d[56:60], "one_sided": bool(_be16(d, 60) & 0x10), "gw": d[62], "sw": d[63],
            "total": _be32(d, 40)}
    clusters = []
    for i in range(count):
        off = _be32(d, table + i * 4)
        clusters.append(_cluster(d[off:off + _be16(d, off + 8)], gran, d[62], d[63]))
    return head, clusters


def _cluster(d, gran, gw, sw):
    unit_count = _be16(d, 0)
    unit_start = (_be16(d, 4) + 1) * 16
    units = d[unit_start:unit_start + _be16(d, 2)]
    n, mode = d[10], d[12]
    ints = None
    if mode == 0:
        raw = np.frombuffer(d, '>u4', n * 4, 16).reshape(n, 4)[:, :3].copy()
    elif mode == 1:
        base = np.frombuffer(d, '>i4', 3, 16).astype(np.int64)
        delta = np.frombuffer(d, '>u2', n * 3, 28).reshape(n, 3).astype(np.int64)
        ints = np.clip(base + delta, -2 ** 31, 2 ** 31 - 1).astype(np.int32)
    elif mode == 2:
        ints = np.frombuffer(d, '>i4', n * 3, 16).reshape(n, 3).copy()
    else:
        raise ValueError(f"RWCM vertex compression {mode}")
    if ints is not None:
        points = ints.astype(np.float32) * np.float32(gran)
    else:
        points = raw.view('>f4').astype(np.float32)
    tris = []
    at = 0
    for _ in range(unit_count):
        flags = units[at]; at += 1
        if flags & 15 != 1:
            raise ValueError("RWCM unit type")
        ind = bytes(units[at:at + 3]); at += 3
        edges = None
        if flags & 0x20:
            edges = bytes(units[at:at + 3]); at += 3
        group = surface = 0
        if flags & 0x40:
            group = int.from_bytes(units[at:at + gw], 'little'); at += gw
        if flags & 0x80:
            surface = int.from_bytes(units[at:at + sw], 'little'); at += sw
        tris.append((flags, ind, edges, group, surface))
    if at != len(units):
        raise ValueError("RWCM unit stream trailing bytes")
    return {"n": n, "ints": ints, "raw": None if ints is not None else raw, "points": points, "tris": tris}


def recode_rwcm(data):
    """Same triangles, own container: see the module docstring."""
    out = bytearray(b"RWCMSET1")
    meshes = rwcm_triangles(data)
    out += struct.pack('<I', len(meshes))
    for number, (_retail_name, head, clusters) in enumerate(meshes):
        name = b"collision%d" % number
        blobs = []
        for c in clusters:
            n = c["n"]
            perm = np.arange(n)[::-1]                 # new slot -> old vertex
            where = np.empty(n, np.int64); where[perm] = np.arange(n)
            # Always plain floats: for integer-coded clusters these are exactly the
            # values the engine computes (integer as f32 * granularity).
            bits = c["points"][perm].astype('>f4').view('>u4')
            mode = 0
            body = np.concatenate([bits, np.zeros((n, 1), '>u4')], 1).astype('>u4').tobytes()
            body += b"\0" * ((-(16 + len(body))) % 16)
            units = bytearray()
            for flags, ind, edges, group, surface in c["tris"]:
                units.append(flags)
                units += bytes(int(where[i]) for i in ind)
                if edges is not None:
                    units += edges
                if flags & 0x40:
                    units += group.to_bytes(head["gw"], 'little')
                if flags & 0x80:
                    units += surface.to_bytes(head["sw"], 'little')
            unit_start = 16 + len(body)
            size = unit_start + len(units)
            if size > 0xFFFF or len(units) > 0xFFFF:
                raise ValueError("RWCM cluster too large to re-encode")
            header = bytearray(16)
            struct.pack_into('>HHH', header, 0, len(c["tris"]), len(units), unit_start // 16 - 1)
            struct.pack_into('>H', header, 8, size)
            header[10] = n
            header[12] = mode
            blobs.append(bytes(header) + body + bytes(units))
        table = 96
        first = table + 4 * len(blobs)
        mesh = bytearray(96)
        struct.pack_into('>I', mesh, 40, head["total"])
        struct.pack_into('>I', mesh, 52, table)
        mesh[56:60] = head["gran_bits"]
        struct.pack_into('>H', mesh, 60, 0x10 if head["one_sided"] else 0)
        mesh[62], mesh[63] = head["gw"], head["sw"]
        struct.pack_into('>I', mesh, 64, len(blobs))
        at = first
        offsets = []
        for b in blobs:
            offsets.append(at); at += len(b)
        struct.pack_into('>I', mesh, 80, at)
        mesh += struct.pack(f'>{len(offsets)}I', *offsets) + b"".join(blobs)
        out += struct.pack('<I', len(name)) + name + struct.pack('<I', len(mesh)) + mesh
    new = bytes(out)
    check_same_collision(meshes, rwcm_triangles(new))
    return new


def check_same_collision(old, new):
    if len(old) != len(new):
        raise ValueError("collision mesh count changed")
    for (n1, h1, c1), (n2, h2, c2) in zip(old, new):
        if h1["one_sided"] != h2["one_sided"] or len(c1) != len(c2):
            raise ValueError("collision mesh header changed")
        for a, b in zip(c1, c2):
            if len(a["tris"]) != len(b["tris"]):
                raise ValueError("collision cluster changed")
            for (_, ia, ea, ga, sa), (_, ib, eb, gb, sb) in zip(a["tris"], b["tris"]):
                pa = a["points"][list(ia)].tobytes()
                pb = b["points"][list(ib)].tobytes()
                if pa != pb or ea != eb or ga != gb or sa != sb:
                    raise ValueError("collision triangle changed")


# ---------------------------------------------------------------- manifest

def trim_wmet(data):
    m = json.loads(data)
    if m.get("geometry") == MARK:
        return None
    keep = {
        "geometry": MARK,
        "map_name": m.get("map_name"),
        "grind_coordinate_policy": {"mode": (m.get("grind_coordinate_policy") or {}).get("mode", "world_space")},
        "grind_splines": [{k: r[k] for k in RAIL_KEYS if k in r} for r in m.get("grind_splines", [])],
    }
    return json.dumps(keep, separators=(",", ":")).encode()


# ---------------------------------------------------------------- container

def _stored_read(f):
    method, size = struct.unpack('<II', f.read(8))
    raw = f.read(size)
    if method == 1:
        return zlib.decompress(raw)
    if method == 0:
        return raw
    raise ValueError(f"stored method {method}")


def _stored_write(o, data, level=6):
    z = zlib.compress(data, level)
    if len(z) >= len(data):
        o.write(struct.pack('<II', 0, len(data))); o.write(data)
    else:
        o.write(struct.pack('<II', 1, len(z))); o.write(z)


def read_sections(path):
    """-> (prefix bytes up to and including textures, counts offset, counts,
    vertices, indices, collision bytes, rails bytes, extensions)."""
    from games.skate3 import skate14
    with open(path, 'rb') as f:
        r = skate14._R(f)
        if r.read(8) != b"SKATE14\0" or r.u() != 0x12345678:
            return None
        r.s(); r.read(49 * 4)
        counts_at = f.tell()
        f.seek(0)
        counts = skate14._skip_prefix(r)
        for _ in range(counts[1]):
            r.s(); r.read(12); r.u(); f.seek(r.u(), 1)
        end = f.tell()
        f.seek(0)
        prefix = f.read(end)
        vb = _stored_read(f)
        ib = _stored_read(f)
        cb = _stored_read(f)
        rails_at = f.tell()
        for _ in range(counts[5]):
            r.s(); r.read(8 + 16 + 8); f.seek(r.u() * 120, 1)
        rails_end = f.tell()
        f.seek(rails_at)
        rails = f.read(rails_end - rails_at)
        ext = []
        for _ in range(r.u()):
            tag = f.read(4)
            schema, _length = struct.unpack('<II', f.read(8))
            ext.append((tag, schema, _stored_read(f)))
        if f.read(1):
            raise ValueError("trailing bytes after extensions")
    if counts[4] or counts[6] or counts[7] or counts[8]:
        raise ValueError(f"unsupported sections in {path}: {counts}")
    v = np.frombuffer(vb, VERT)
    idx = np.frombuffer(ib, '<u4').reshape(-1, 3)
    if len(v) != counts[2] or idx.size != counts[3]:
        raise ValueError("geometry counts mismatch")
    return prefix, counts_at, counts, v, idx, cb, rails, ext


def rewrite(src, dst, key):
    """Regenerate one SKATE14 file. Returns stats, None if not SKATE14, or
    {'already': True} if it carries the regenerated mark."""
    sections = read_sections(src)
    if sections is None:
        return None
    prefix, counts_at, counts, v, idx, cb, rails, ext = sections
    if any(tag == b"WMET" and trim_wmet(data) is None for tag, _, data in ext):
        return {"already": True}
    # Every file from the retail conversion carries a WMET manifest. One without
    # it is an original map (e.g. the CC0 Kenney park): nothing to regenerate.
    if not any(tag == b"WMET" for tag, _, _ in ext):
        return {"already": True, "original": True}
    v2, idx2, stats = regen_mesh(v, idx, key)
    counts = list(counts)
    counts[2], counts[3] = len(v2), idx2.size
    prefix = bytearray(prefix)
    struct.pack_into('<9I', prefix, counts_at, *counts)
    new_ext = []
    for tag, schema, data in ext:
        if tag == b"RWCM":
            new = recode_rwcm(data)
            stats["collision_bytes"] = (len(data), len(new))
            data = new
        elif tag == b"WMET":
            new = trim_wmet(data)
            stats["manifest_bytes"] = (len(data), len(new))
            data = new
        new_ext.append((tag, schema, data))
    tmp = dst + ".tmp"
    with open(tmp, 'wb') as o:
        o.write(prefix)
        _stored_write(o, v2.tobytes())
        _stored_write(o, idx2.tobytes())
        _stored_write(o, cb)
        o.write(rails)
        o.write(struct.pack('<I', len(new_ext)))
        for tag, schema, data in new_ext:
            o.write(tag); o.write(struct.pack('<II', schema, len(data))); _stored_write(o, data)
    os.replace(tmp, dst)
    return stats


def main(argv):
    root = argv[1]
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    dry = "--dry" in argv
    t0 = time.time()
    total = {"files": 0, "tris": 0, "tris_retessellated": 0, "verts": 0, "skipped": 0}
    for dp, _, fs in os.walk(root):
        for f in sorted(fs):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            # Models under mods/ are not from the game (credited separately).
            glb = f.endswith(".glb") and rel.startswith("assets/private/")
            if not (f.endswith(".skate") or glb) or (only and only not in rel):
                continue
            try:
                s = (rewrite_glb if glb else rewrite)(p, p + ".dry" if dry else p, rel)
            except ValueError as e:
                # Authored collision or rails: not the retail conversion's layout,
                # so an original map. Said out loud so a broken retail file shows.
                total["skipped"] += 1
                print(f"  {rel}: not the retail pipeline's layout ({e}), left as is")
                continue
            if dry and os.path.exists(p + ".dry"):
                os.remove(p + ".dry")
            if s is None or s.get("already"):
                total["skipped"] += 1
                print(f"  {rel}: " + ("original map, left as is" if s and s.get("original") else "already regenerated" if s else "not SKATE14 (the author's own map), left as is"))
                continue
            total["files"] += 1
            for k in ("tris", "tris_retessellated", "verts"):
                total[k] += s.get(k, 0)
            print(f"  {rel}: {s['tris']} tris, {s.get('tris_retessellated', 0)} retessellated, "
                  f"verts {s['verts']}->{s.get('verts_out', 0)}, shift<={s.get('max_shift_mm', 0):.2f} mm, "
                  f"normals kept as direction {s.get('normals_kept_direction', 0)}, "
                  f"collision {s.get('collision_bytes')}, manifest {s.get('manifest_bytes')}", flush=True)
    share = 100.0 * total["tris_retessellated"] / max(1, total["tris"])
    print(f"geometry: {total['files']} files, {total['tris']} triangles, {share:.1f}% retessellated, "
          f"{total['skipped']} left as is, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(sys.argv)
