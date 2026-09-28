"""DIRTY ROOM: which files did the decomp's extractor add? That list is the
slot spec for the clean room.

Compares a pristine checkout with the extracted (dirty) tree and lists every
file that exists only in the dirty tree (ignoring build output and VCS
dirs), classified by kind. Prints a one-screen census; writes assets.json.

    python -m cleanroom.decomp.census <pristine> <dirty> <out assets.json> [--ignore build,baserom]
"""
import collections
import json
import os
import sys

SKIP_DIRS = {".git", "build", "__pycache__", "tools", "node_modules", ".venv"}
KINDS = [
    ("texture", (".png",)),
    ("sample", (".aiff", ".aifc", ".wav")),
    ("sequence", (".m64", ".seq", ".mid")),
    ("text_or_code", (".json", ".txt", ".xml", ".h", ".c", ".s", ".yaml", ".yml")),
    ("binary", (".bin", ".yay0", ".mio0", ".raw", ".data", ".zdata")),
]


def kind(path):
    p = path.lower()
    for k, exts in KINDS:
        if p.endswith(exts):
            return k
    return "other"


def walk(root, ignore):
    out = set()
    for d, dirs, files in os.walk(root):
        rel_d = os.path.relpath(d, root).replace("\\", "/")
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not any(i in (rel_d + "/" + x) for i in ignore)]
        for f in files:
            rel = f if rel_d == "." else rel_d + "/" + f
            if not any(i in rel for i in ignore):
                out.add(rel)
    return out


def main(argv):
    pristine, dirty, out = argv[1], argv[2], argv[3]
    ignore = argv[argv.index("--ignore") + 1].split(",") if "--ignore" in argv else ["baserom"]
    added = sorted(walk(dirty, ignore) - walk(pristine, ignore))
    by = collections.defaultdict(list)
    for a in added:
        by[kind(a)].append(a)
    size = {k: sum(os.path.getsize(os.path.join(dirty, a)) for a in v) for k, v in by.items()}
    json.dump({"assets": added, "by_kind": {k: len(v) for k, v in by.items()}}, open(out, "w"), indent=0)
    print(f"census: {len(added)} extracted files -> {out}")
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        tops = collections.Counter(a.split("/")[0] for a in v).most_common(4)
        print(f"  {k:13s} {len(v):6d}  {size[k] // 1024:7d} KB   top dirs: {tops}")
    fmt = collections.Counter(".".join(os.path.basename(a).split(".")[-2:]) for a in by.get("texture", []))
    if fmt:
        print("  texture formats (from names):", fmt.most_common(10))


if __name__ == "__main__":
    main(sys.argv)
