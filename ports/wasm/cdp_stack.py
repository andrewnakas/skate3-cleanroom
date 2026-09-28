"""Dev tool: open a page in headless Edge, wait, pause JS and print the stack.

    python ports/wasm/cdp_stack.py <url> [--wait 8] [--webgl]

For finding where a wasm main thread hangs (build with --profiling-funcs
so frames carry function names). Prints console lines, then the top frames.
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request

import websocket

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--wait", type=float, default=8)
    ap.add_argument("--webgl", action="store_true")
    ap.add_argument("--port", type=int, default=9333)
    a = ap.parse_args()
    prof = tempfile.mkdtemp(prefix="cdp_")
    args = [EDGE, "--headless=new", f"--user-data-dir={prof}", f"--remote-debugging-port={a.port}", "--remote-allow-origins=*",
            "--no-first-run", "--autoplay-policy=no-user-gesture-required", "--window-size=1024,800"]
    if a.webgl:
        args += ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]
    p = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{a.port}/json"))
                break
            except OSError:
                time.sleep(0.2)
        tab = next(t for t in tabs if t.get("type") == "page")
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30)
        n = [0]

        def send(method, **params):
            n[0] += 1
            ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
            return n[0]

        send("Runtime.enable")
        send("Debugger.enable")
        send("Page.navigate", url=a.url)
        t_end = time.time() + a.wait
        ws.settimeout(0.5)
        while time.time() < t_end:
            try:
                m = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if m.get("method") == "Runtime.consoleAPICalled":
                print("console:", " ".join(str(x.get("value", x.get("description", "")))[:160]
                                           for x in m["params"]["args"]))
            elif m.get("method") == "Runtime.exceptionThrown":
                seen = n.append(1) or len(n) - 1
                if seen <= 2:
                    ed = m["params"]["exceptionDetails"]
                    print("EXCEPTION:", ed.get("exception", {}).get("description", "")[:200].split("\n")[0])
                    for f in (ed.get("stackTrace") or {}).get("callFrames", [])[:14]:
                        print("  at", f.get("functionName") or "?")
        send("Debugger.pause")
        ws.settimeout(10)
        while True:
            m = json.loads(ws.recv())
            if m.get("method") == "Debugger.paused":
                for f in m["params"]["callFrames"][:25]:
                    print("  at", f.get("functionName") or "?", f["location"].get("lineNumber"))
                break
    finally:
        p.kill()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    main()
