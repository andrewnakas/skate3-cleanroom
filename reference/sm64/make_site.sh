#!/bin/sh
# Package the web build into a static site dir. Usage: make_site.sh <clean tree> <site dir>
B="$1/build/us_web"; S="$2"; mkdir -p "$S"
cp "$B/sm64.us.js" "$B/sm64.us.wasm" "$S/" && cp "$(dirname "$0")/web/shell.html" "$S/index.html"
touch "$S/.nojekyll"; ls -la "$S" | awk 'NR>1{print $5, $9}'
