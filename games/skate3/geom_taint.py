"""Geometry taint scan: regenerated SKATE14 files against the private pack.

    python -m games.skate3.geom_taint <private pack dir> <clean pack dir> [--only substr]

For the skinned model (assets/private/*.glb) every mesh accessor is compared the
same way. For every .skate in both packs (SKATE14 only) the decoded vertex buffer, index
buffer and collision container of the clean file are compared with the
private one:
  runs      32-byte windows (4-byte aligned) of the clean buffer that also occur
            anywhere in the private buffer; must be 0
  positions clean vertices whose three position floats equal a private vertex's
  re-cut    share of triangles that no longer have a private triangle's corners
Prints one line per file and a total. Exit code 1 if any shared run is found.
"""
import os
import sys

import numpy as np

from cleanroom import taint
from games.skate3 import geom

MULT = np.array([0x9E3779B97F4A7C15, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9, 0xD6E8FEB86659FD93,
                 0xA0761D6478BD642F, 0xE7037ED1A0B428DB, 0x8EBC6AF09C88C6E3, 0x589965CC75374CC3], np.uint64)


def window_hashes(buf):
    """64-bit hash of every 32-byte window starting on a 4-byte boundary."""
    words = np.frombuffer(buf[:len(buf) // 4 * 4], '<u4').astype(np.uint64)
    n = len(words) - 7
    if n <= 0:
        return np.zeros(0, np.uint64)
    h = np.zeros(n, np.uint64)
    with np.errstate(over='ignore'):
        for k in range(8):
            h += (words[k:k + n] + np.uint64(k + 1)) * MULT[k]
            h ^= h >> np.uint64(29)
    return h


def shared_runs(clean, dirty, distinct=taint.MIN_DISTINCT):
    """Count distinct 32-byte windows of clean that occur in dirty (hash match
    confirmed bytewise). Like the texture scan, windows made of a few repeated
    values (zero padding, flat fields) are not content. Stops counting at 1000."""
    hc, hd = window_hashes(clean), window_hashes(dirty)
    if not len(hc) or not len(hd):
        return 0
    hd_unique, hd_first = np.unique(hd, return_index=True)
    at = np.searchsorted(hd_unique, hc)
    at = np.minimum(at, len(hd_unique) - 1)
    hit = np.flatnonzero(hd_unique[at] == hc)
    if not len(hit):
        return 0
    _, first = np.unique(hc[hit], return_index=True)
    count = 0
    for i in hit[first]:
        k = int(hd_first[at[i]])
        window = clean[i * 4:i * 4 + 32]
        if window == dirty[k * 4:k * 4 + 32] and len(set(window)) >= distinct:
            count += 1
            if count >= 1000:
                break
    return count


def tri_keys(v, idx):
    """Order-free key per triangle from its corner positions on a 1 mm grid
    (regenerated corners move by up to ~0.2 mm, so equal floats are not needed)."""
    q = np.rint(v['p'].astype(np.float64) * 1000.0).astype(np.int64)
    h = (q[:, 0] * 73856093) ^ (q[:, 1] * 19349663) ^ (q[:, 2] * 83492791)
    c = np.sort(h[idx.astype(np.int64)], axis=1)
    return (c[:, 0] * 1000003) ^ (c[:, 1] * 10007) ^ c[:, 2]


def glb_runs(clean_path, dirty_path, rel):
    """Skinned model: every mesh accessor of the clean file (positions, normals,
    UVs, joints, weights, indices) against the whole binary chunk of the
    private file. The skeleton (inverse bind matrices) is a kept fact."""
    cj, cb = geom.glb_parts(clean_path)
    _, db = geom.glb_parts(dirty_path)
    runs = {}
    for m in cj.get('meshes', []):
        for pr in m['primitives']:
            for name, a in list(pr['attributes'].items()) + [('indices', pr['indices'])]:
                acc = cj['accessors'][a]
                view = cj['bufferViews'][acc['bufferView']]
                at = view.get('byteOffset', 0)
                # joints and weights only move with their vertices, so their runs are
                # counted with at least 12 distinct byte values (a real sequence)
                n = shared_runs(cb[at:at + view['byteLength']], db, 12 if name in ('JOINTS_0', 'WEIGHTS_0') else taint.MIN_DISTINCT)
                runs[name] = runs.get(name, 0) + n
    bad = sum(runs.values())
    print(f"  {rel}: shared runs " + " ".join(f"{k} {v}" for k, v in sorted(runs.items())) + ("  FAIL" if bad else ""), flush=True)
    return bad


def main(argv):
    dirty_root, clean_root = argv[1], argv[2]
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    failing = files = 0
    tot = np.zeros(4, np.int64)
    for dp, _, fs in os.walk(clean_root):
        for f in sorted(fs):
            cp = os.path.join(dp, f)
            rel = os.path.relpath(cp, clean_root).replace(os.sep, "/")
            dpth = os.path.join(dirty_root, rel)
            if only and only not in rel:
                continue
            if f.endswith(".glb") and rel.startswith("assets/private/") and os.path.exists(dpth):
                files += 1
                bad = glb_runs(cp, dpth, rel)
                failing += bad > 0
                continue
            if not f.endswith(".skate"):
                continue
            if not os.path.exists(dpth):
                print(f"  {rel}: no private counterpart (the author's own map), not compared")
                continue
            c, d = geom.read_sections(cp), geom.read_sections(dpth)
            if c is None or d is None:
                print(f"  {rel}: not SKATE14, not compared")
                continue
            _, _, _, cv, ci, _, _, cext = c
            _, _, _, dv, di, _, _, dext = d
            runs_v = shared_runs(cv.tobytes(), dv.tobytes())
            runs_i = shared_runs(ci.tobytes(), di.tobytes())
            # The manifest is a short list of rail identities the engine checks
            # (kept facts, listed in the README), so only the collision is scanned.
            runs_x = 0
            dmap = {tag: data for tag, _, data in dext}
            for tag, _, data in cext:
                if tag == b"RWCM" and tag in dmap:
                    runs_x += shared_runs(data, dmap[tag])
            pos_d = np.unique(np.ascontiguousarray(dv['p']).view([('', '<u4')] * 3))
            pos_c = np.ascontiguousarray(cv['p']).view([('', '<u4')] * 3).ravel()
            same_pos = int(np.isin(pos_c, pos_d).sum())
            same_tri = int(np.isin(tri_keys(cv, ci), tri_keys(dv, di)).sum())
            files += 1
            bad = runs_v + runs_i + runs_x
            failing += bad > 0
            tot += (len(cv), same_pos, len(ci), same_tri)
            print(f"  {rel}: shared runs vertices {runs_v} indices {runs_i} collision {runs_x}; "
                  f"identical positions {same_pos}/{len(cv)}; triangles re-cut "
                  f"{100 * (1 - same_tri / max(1, len(ci))):.1f}%" + ("  FAIL" if bad else ""), flush=True)
    print(f"geometry taint: {files} files, {failing} failing; identical positions {tot[1]}/{tot[0]} "
          f"({100 * tot[1] / max(1, tot[0]):.3f}%); triangles re-cut {100 * (1 - tot[3] / max(1, tot[2])):.1f}%")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
