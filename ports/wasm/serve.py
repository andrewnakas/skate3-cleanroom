"""Local dev server for the web build, with the cross-origin isolation
headers browsers require for SharedArrayBuffer (pthreads).

    python ports/wasm/serve.py [build dir] [port]
"""
import http.server
import os
import sys


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


Handler.extensions_map.update({".wasm": "application/wasm", ".js": "text/javascript"})

if __name__ == "__main__":
    os.chdir(sys.argv[1] if len(sys.argv) > 1 else ".")
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8064
    print(f"serving {os.getcwd()} on http://localhost:{port}/pw64.html")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
