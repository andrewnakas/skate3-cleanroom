"""Dev tool: run the web build in headless Edge/Chrome and save screenshots.

    python ports/wasm/headless_shot.py <out dir> [--secs 5,10] [--query extra=1] [--wait 30]

Needs serve.py running on :8064. The page's ?dump= hook logs PNGs to the
console; this collects them from the browser log and writes shot_<k>.png,
plus console.txt with the page's own messages.
"""
import argparse
import base64
import os
import re
import shutil
import subprocess
import time

BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--secs", default="5,10")
    ap.add_argument("--query", default="")
    ap.add_argument("--wait", type=float, default=None)
    ap.add_argument("--port", type=int, default=8064)
    ap.add_argument("--base", default=None, help="page URL instead of the local dev server")
    ap.add_argument("--webgl", action="store_true", help="software WebGL (SwiftShader) for GL pages")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    exe = next(b for b in BROWSERS if os.path.exists(b))
    wait = a.wait or max(float(s) for s in a.secs.split(",")) + 8
    page = a.base or f"http://localhost:{a.port}/pw64.html"
    url = f"{page}?dump={a.secs}" + (f"&{a.query}" if a.query else "")
    prof = os.path.join(a.out, "_profile")
    shutil.rmtree(prof, ignore_errors=True)      # no stale HTTP cache between builds
    log = os.path.join(a.out, "_browser.log")
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        p = subprocess.Popen([exe, "--headless=new", f"--user-data-dir={prof}", "--enable-logging=stderr",
                              "--v=0", "--no-first-run", "--autoplay-policy=no-user-gesture-required",
                              "--window-size=1024,800"] +
                             (["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"] if a.webgl else []) +
                             [url], stderr=f, stdout=subprocess.DEVNULL)
        time.sleep(wait)
        p.kill()
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    chunks, console = {}, []
    pat = re.compile(r'"(.*)", source: https?://(localhost|[\w.-]+\.github\.io)')
    for line in open(log, encoding="utf-8", errors="replace"):
        m = pat.search(line)
        if not m:
            continue
        msg = m.group(1)
        if msg.startswith("PW64PNG:"):
            _, k, data = msg.split(":", 2)
            if data not in ("END", "none"):
                chunks.setdefault(k, []).append(data)
        else:
            console.append(msg)
    with open(os.path.join(a.out, "console.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(console))
    for k, parts in chunks.items():
        url = "".join(parts)
        with open(os.path.join(a.out, f"shot_{k}.png"), "wb") as f:
            f.write(base64.b64decode(url.split(",", 1)[1]))
    print(f"{len(chunks)} screenshots, {len(console)} console lines -> {a.out}")


if __name__ == "__main__":
    main()
