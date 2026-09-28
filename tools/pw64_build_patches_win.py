"""Run the port's tools/build_patches.py natively on Windows, without WSL.

The port compiles its MIPS C patches with a Linux Clang (Windows LLVM builds
lack the MIPS target). Zig's bundled clang/lld have every target, so this
imports build_patches.py and swaps its WSL runner for local execution with
`zig clang` / `zig ld.lld` and the Windows build of N64Recomp.

    python tools/pw64_build_patches_win.py <pilotwings-64-recomp dir> <zig.exe>
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def main(argv):
    repo = Path(argv[1]).resolve()
    zig = str(Path(argv[2]).resolve())
    spec = importlib.util.spec_from_file_location("build_patches", repo / "tools" / "build_patches.py")
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)

    def local(args, **kwargs):
        args = [str(a) for a in args]
        if args[0] == "clang":
            args = [zig, "clang"] + args[1:]
        elif args[0] == "ld.lld":
            args = [zig, "ld.lld"] + args[1:]
        elif (repo / args[0]).is_file():
            # Windows resolves a relative executable against our cwd, not cwd=.
            args[0] = str(repo / args[0])
        result = subprocess.run(args, cwd=repo, **kwargs)
        if result.returncode != 0:
            if kwargs.get("capture_output"):
                sys.stderr.write(result.stdout or "")
                sys.stderr.write(result.stderr or "")
            sys.exit(f"failed: {' '.join(args[:5])} ...")
        return result

    bp.linux = local
    bp.find_llvm = lambda: ("clang", "ld.lld")
    bp.N64RECOMP = repo / "lib" / "N64ModernRuntime" / "N64Recomp" / "build-win" / "N64Recomp.exe"
    return bp.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
