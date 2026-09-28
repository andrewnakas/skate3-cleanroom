#!/bin/sh
# Install the Windows toolchain shims into ~/bin (Git Bash):
#   gcc/g++ -> zig cc (writes X and X.exe), as -> clang integrated assembler,
#   objcopy -> llvm-objcopy, hexdump -> python, python3 -> python, clang, ar, make.
# Paths inside the shims point at C:/Users/andre/.local/{zig-*,clang+llvm-*}.
set -e
D="$(cd "$(dirname "$0")" && pwd)/winbin"
mkdir -p "$HOME/bin"
cp "$D"/* "$HOME/bin/" && chmod +x "$HOME/bin/"*
M=$(ls -d /c/Users/andre/AppData/Local/Microsoft/WinGet/Packages/ezwinports.make*/bin 2>/dev/null | head -1)
[ -n "$M" ] && cp "$M/make.exe" "$HOME/bin/" || echo "make: winget install ezwinports.make"
export PATH="$HOME/bin:$PATH"
gcc --version >/dev/null 2>&1 && echo "gcc(zig) ok"; make --version | head -1; clang --version | head -1
echo 'add to builds: export PATH="$HOME/bin:/e/n64web/emsdk/upstream/emscripten:/e/n64web/emsdk/upstream/bin:$PATH" EM_CACHE=E:/n64web/emcache'
