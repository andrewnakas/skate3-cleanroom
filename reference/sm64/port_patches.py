"""Idempotent source patches applied to the clean sm64-port tree.

Each entry is (file, old, new). Patches only adapt the build to our
toolchain (emsdk 6, zig as host cc, Windows); no game logic changes.

Usage: python -m games.sm64.port_patches <clean tree>
"""
import os
import sys

PATCHES = [
    # emscripten 6: -g4 and EXTRA_EXPORTED_RUNTIME_METHODS are gone
    ("Makefile", "    OPT_FLAGS += -g4 --source-map-base http://localhost:8080/\n", ""),
    ("Makefile",
     "-s TOTAL_MEMORY=20MB -g4 --source-map-base http://localhost:8080/ -s \"EXTRA_EXPORTED_RUNTIME_METHODS=['callMain']\"",
     "-s INITIAL_MEMORY=64MB -s ALLOW_MEMORY_GROWTH=1 --profiling-funcs -s \"EXPORTED_RUNTIME_METHODS=['callMain']\""),
    ("Makefile", "-fno-strict-aliasing -fwrapv -march=native", "-fno-strict-aliasing -fwrapv"),
    # C++ sources (gfx backends, all #ifdef'd out on web) go to em++ too
    ("Makefile", "else\n  CC := emcc\nendif", "else\n  CC := emcc\n  CXX := em++\nendif"),
    # Windows command lines cap at 32 KB: link from a response file
    ("Makefile",
     "\t$(LD) -L $(BUILD_DIR) -o $@ $(O_FILES) $(ULTRA_O_FILES) $(GODDARD_O_FILES) $(LDFLAGS)\n",
     "\t$(file >$(BUILD_DIR)/link.rsp,$(O_FILES) $(ULTRA_O_FILES) $(GODDARD_O_FILES))\n"
     "\t$(LD) -L $(BUILD_DIR) -o $@ @$(BUILD_DIR)/link.rsp $(LDFLAGS)\n"),
    # web: requestAnimationFrame paces frames; SDL_Delay would busy-wait
    ("src/pc/gfx/gfx_sdl2.c",
     "static void gfx_sdl_swap_buffers_begin(void) {\n    if (!vsync_enabled) {",
     "static void gfx_sdl_swap_buffers_begin(void) {\n#ifdef TARGET_WEB\n    if (0) {\n#else\n    if (!vsync_enabled) {\n#endif"),
    # upstream bug: loop over the nonextended table indexed the (shorter)
    # extended one; clang -O2 turns that out-of-bounds UB into an endless loop
    ("src/pc/gfx/gfx_sdl2.c",
     "        inverted_scancode_table[scancode_rmapping_extended[i][0]] = inverted_scancode_table[scancode_rmapping_extended[i][1]];\n"
     "        inverted_scancode_table[scancode_rmapping_extended[i][1]] += 0x100;\n",
     "        inverted_scancode_table[scancode_rmapping_nonextended[i][0]] = inverted_scancode_table[scancode_rmapping_nonextended[i][1]];\n"
     "        inverted_scancode_table[scancode_rmapping_nonextended[i][1]] += 0x100;\n"),
    # WebGL 1 takes GLSL ES 1.00 only (#version 100 + a float precision)
    ("src/pc/gfx/gfx_opengl.c",
     '    append_line(vs_buf, &vs_len, "#version 110");\n',
     '#ifdef TARGET_WEB\n    append_line(vs_buf, &vs_len, "#version 100");\n#else\n'
     '    append_line(vs_buf, &vs_len, "#version 110");\n#endif\n'),
    ("src/pc/gfx/gfx_opengl.c",
     '    append_line(fs_buf, &fs_len, "#version 110");\n',
     '#ifdef TARGET_WEB\n    append_line(fs_buf, &fs_len, "#version 100");\n'
     '    append_line(fs_buf, &fs_len, "precision mediump float;");\n#else\n'
     '    append_line(fs_buf, &fs_len, "#version 110");\n#endif\n'),
    # emscripten 6: dynCall() is not in the runtime; use the rAF API
    ("src/pc/pc_main.c",
     """static void request_anim_frame(void (*func)(double time)) {
    EM_ASM(requestAnimationFrame(function(time) {
        dynCall("vd", $0, [time]);
    }), func);
}""",
     """static EM_BOOL raf_trampoline(double time, void *func) {
    ((void (*)(double))func)(time);
    return EM_FALSE;
}

static void request_anim_frame(void (*func)(double time)) {
    emscripten_request_animation_frame(raf_trampoline, (void *)func);
}"""),
]


def apply(tree):
    done = skipped = 0
    for rel, old, new in PATCHES:
        p = os.path.join(tree, rel)
        s = open(p, encoding="utf8", newline="").read()
        if new and new in s:
            skipped += 1
        elif old in s:
            s = s.replace(old, new)
            open(p, "w", encoding="utf8", newline="").write(s)
            done += 1
        elif not new:
            skipped += 1
        else:
            raise SystemExit(f"patch does not apply: {rel}: {old[:60]!r}")
    print(f"patches: {done} applied, {skipped} already present")


if __name__ == "__main__":
    apply(sys.argv[1])
