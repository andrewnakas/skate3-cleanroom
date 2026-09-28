"""Assemble the static site for GitHub Pages from a web build.

    python ports/wasm/make_site.py <build dir> <site dir>

The page is the build's pw64.html (from shell.html) as index.html, plus the
engine (pw64.js, pw64.wasm), the bundled clean image and scripts (pw64.data)
and the cross-origin-isolation service worker.
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv):
    build, site = Path(argv[1]), Path(argv[2])
    site.mkdir(parents=True, exist_ok=True)
    shutil.copy(build / "pw64.html", site / "index.html")
    for name in ("pw64.js", "pw64.wasm", "pw64.data"):
        shutil.copy(build / name, site / name)
    shutil.copy(HERE / "coi-sw.js", site / "coi-sw.js")
    (site / ".nojekyll").write_text("")
    total = sum(p.stat().st_size for p in site.iterdir() if p.is_file())
    print(f"site in {site}: {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv)
