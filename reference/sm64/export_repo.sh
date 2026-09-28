#!/bin/sh
# Copy the SM64 clean-room sources into a standalone repo dir. Usage: export_repo.sh <repo dir>
R="$1"; mkdir -p "$R/games" "$R/ports/wasm"
rsync_like() { (cd "$1" && find . -type f ! -path "*/__pycache__/*" ! -name "*.pyc") | while read f; do mkdir -p "$2/$(dirname "$f")"; cp "$1/$f" "$2/$f"; done; }
rsync_like cleanroom "$R/cleanroom"
rsync_like games/sm64 "$R/games/sm64"
cp games/__init__.py "$R/games/"
cp ports/wasm/headless_shot.py ports/wasm/serve.py ports/wasm/cdp_stack.py "$R/ports/wasm/"
cp games/sm64/README.md "$R/README.md"
printf '__pycache__/\n*.pyc\n*.z64\n*.n64\n*.v64\nbaserom.*\n' > "$R/.gitignore"
echo "exported: $(find "$R" -type f ! -path "*/.git/*" | wc -l) files -> $R"
