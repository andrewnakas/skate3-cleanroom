#!/bin/sh
# Build the clean tree for the web. Usage: games/sm64/build_web.sh <clean tree> [make args]
# Prints only a summary; full log at <tree>/build_web.log
T="$1"; shift
python -m games.sm64.port_patches "$T" || exit 1
export PATH="$HOME/bin:/e/n64web/emsdk/upstream/emscripten:/e/n64web/emsdk/upstream/bin:$PATH"
export EM_CACHE=E:/n64web/emcache EMSDK=E:/n64web/emsdk
cd "$T" && make -j12 TARGET_WEB=1 NOEXTRACT=1 VERSION=us "$@" > build_web.log 2>&1
rc=$?
echo "make rc=$rc"
grep -E "error|Error" build_web.log | sed -E 's/^[^ ]*:[0-9]+:[0-9]+: //' | sort | uniq -c | sort -rn | head -12
ls -la build/us_web/sm64.us.f3dex2e.* 2>/dev/null | awk '{print $5, $9}'
