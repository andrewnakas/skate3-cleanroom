"""Prepare a copy of the port tree for the web build.

    python ports/wasm/setup_port.py <desktop port dir> <web port dir>

Copies the sources the web build needs (src, include, RecompiledFuncs,
RecompiledPatches, the runtime and its third-party headers) and applies the
web patches below. The desktop port is never modified.
"""
import shutil
import sys
from pathlib import Path

COPY = ["src", "include", "tools/scripts", "RecompiledFuncs", "RecompiledPatches",
        "lib/N64ModernRuntime/ultramodern", "lib/N64ModernRuntime/librecomp",
        "lib/N64ModernRuntime/thirdparty", "lib/N64ModernRuntime/N64Recomp/include",
        "lib/N64ModernRuntime/N64Recomp/lib/rabbitizer/include",
        "lib/N64ModernRuntime/N64Recomp/lib/rabbitizer/cplusplus/include"]

# (file, old, new): exact-text patches, applied once.
PATCHES = [
    ("lib/N64ModernRuntime/ultramodern/include/ultramodern/renderer_context.hpp",
     "#elif defined(__linux__) || defined(__ANDROID__)\n        using WindowHandle = SDL_Window*;",
     "#elif defined(__linux__) || defined(__ANDROID__) || defined(__EMSCRIPTEN__)\n        using WindowHandle = SDL_Window*;"),
    # xxHash would take its NEON path through Emscripten's SIMDe compat header,
    # which is C++ and breaks inside xxhash's extern "C"; use the scalar path.
    ("lib/N64ModernRuntime/thirdparty/xxHash/xxhash.h",
     "   || (defined(__wasm_simd128__) && XXH_HAS_INCLUDE(<arm_neon.h>)) /* WASM SIMD128 via SIMDe */",
     "   /* web build: no SIMDe NEON path */"),
    # wasm32 has a 32-bit size_t: fold the hook key instead of packing it.
    ("lib/N64ModernRuntime/librecomp/include/librecomp/mods.hpp",
     "        static_assert(sizeof(std::size_t) == 8);",
     "#if !defined(__EMSCRIPTEN__)\n        static_assert(sizeof(std::size_t) == 8);\n#endif"),
    ("lib/N64ModernRuntime/librecomp/include/librecomp/mods.hpp",
     "        return (size_t(def.section_rom) << 32) | size_t(def.function_vram) | size_t(def.at_return ? 1 : 0);",
     "        return size_t((uint64_t(def.section_rom) << 32 | uint64_t(def.function_vram) | uint64_t(def.at_return ? 1 : 0)) % 0xFFFFFFFBull);"),
    # wasm32: size_t is 32 bits, so the desktop's 4 GB reservation wraps to 0.
    # The game uses 4-8 MB of RDRAM; give it 32 MB (recomp heap from 16 MB).
    ("lib/N64ModernRuntime/librecomp/include/librecomp/addresses.hpp",
     "    constexpr size_t mem_size = 512ULL * 1024ULL * 1024ULL;\n    // 4GB (the full address space)\n    constexpr size_t allocation_size = 4096ULL * 1024ULL * 1024ULL;",
     "#if defined(__EMSCRIPTEN__)\n    constexpr size_t mem_size = 32ULL * 1024ULL * 1024ULL;\n    constexpr size_t allocation_size = mem_size;\n#else\n    constexpr size_t mem_size = 512ULL * 1024ULL * 1024ULL;\n    // 4GB (the full address space)\n    constexpr size_t allocation_size = 4096ULL * 1024ULL * 1024ULL;\n#endif"),
    # Mods patch native code; the web build has no mods, so the patcher aborts.
    ("lib/N64ModernRuntime/librecomp/src/mods.cpp",
     "#elif defined(__ARM_ARCH_ISA_A64)\n#   define IS_ARM64\n#else\n#   error \"Unsupported architecture!\"",
     "#elif defined(__ARM_ARCH_ISA_A64)\n#   define IS_ARM64\n#elif defined(__EMSCRIPTEN__)\n#   define IS_WASM\n#else\n#   error \"Unsupported architecture!\""),
    ("lib/N64ModernRuntime/librecomp/src/mods.cpp",
     "    }, replacement_func);\n#else\n#   error \"Unsupported architecture\"",
     "    }, replacement_func);\n#elif defined(IS_WASM)\n    (void)replacement_func; std::abort();  // no native code patching on the web\n#else\n#   error \"Unsupported architecture\""),
]


def patch(root: Path):
    for rel, old, new in PATCHES:
        p = root / rel
        s = p.read_text(encoding="utf-8")
        if new in s:
            continue
        if old not in s:
            raise SystemExit(f"patch target not found in {rel}")
        p.write_text(s.replace(old, new), encoding="utf-8")
        print(f"patched {rel}")


def main(argv):
    src, dst = Path(argv[1]), Path(argv[2])
    for rel in COPY:
        s, d = src / rel, dst / rel
        if not d.exists():
            print(f"copy {rel}")
            shutil.copytree(s, d)
    patch(dst)


if __name__ == "__main__":
    main(sys.argv)
