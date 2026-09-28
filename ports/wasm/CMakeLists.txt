# Pilotwings 64 (clean-room build) for the web: emcc + pthreads + SDL2 + WebGL2.
#   emcmake cmake -S ports/wasm -B <build> -DPORT=<copy of the port tree> -G Ninja
#   cmake --build <build>
cmake_minimum_required(VERSION 3.20)
project(pw64web C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(PORT "" CACHE PATH "Port tree (sources + RecompiledFuncs), patched by setup_port.py")
set(RT ${PORT}/lib/N64ModernRuntime)

set(THREAD_FLAGS -pthread)
# miniz's CMake normally generates this header.
file(WRITE ${CMAKE_BINARY_DIR}/gen/miniz_export.h "#pragma once
#define MINIZ_EXPORT
")
include_directories(${CMAKE_BINARY_DIR}/gen)
add_compile_options(${THREAD_FLAGS} -Wno-unused-parameter -Wno-everything -msimd128 -msse4.1)
add_compile_definitions(XXH_VECTOR=0 PW64_WITH_RUNTIME=1 PW64_WITH_RECOMPILED=1 PW64_WITH_FRONTEND=0
                        PW64_CLEAN_AUDIO=1 PW64_WEB=1)

# ---- ultramodern
file(GLOB UM_SRC ${RT}/ultramodern/src/*.cpp)
list(FILTER UM_SRC EXCLUDE REGEX "task_win32\.cpp$")
add_library(ultramodern STATIC ${UM_SRC})
target_include_directories(ultramodern PUBLIC ${RT}/ultramodern/include ${RT}/thirdparty
                           ${RT}/thirdparty/concurrentqueue ${RT}/thirdparty/sse2neon)

# ---- librecomp (mod loading/JIT compiled against stubs: no native codegen on the web)
file(GLOB LR_SRC ${RT}/librecomp/src/*.cpp)
add_library(librecomp STATIC ${LR_SRC} ${RT}/thirdparty/o1heap/o1heap/o1heap.c
            ${CMAKE_CURRENT_SOURCE_DIR}/web_stubs.cpp)
target_include_directories(librecomp PUBLIC ${RT}/librecomp/include ${RT}/librecomp/src
                           ${RT}/ultramodern/include ${RT}/thirdparty ${RT}/thirdparty/concurrentqueue
                           ${RT}/thirdparty/o1heap ${RT}/N64Recomp/include ${RT}/thirdparty/miniz
                           ${RT}/librecomp/include/librecomp
                           ${RT}/N64Recomp/lib/rabbitizer/include
                           ${RT}/N64Recomp/lib/rabbitizer/cplusplus/include)
file(GLOB MINIZ_SRC ${RT}/thirdparty/miniz/*.c)
if(MINIZ_SRC)
  target_sources(librecomp PRIVATE ${MINIZ_SRC})
endif()

# ---- recompiled game code
file(GLOB GAME_SRC ${PORT}/RecompiledFuncs/*.c ${PORT}/RecompiledPatches/*.c)
add_library(pw64_recompiled STATIC ${GAME_SRC})
target_include_directories(pw64_recompiled PRIVATE ${RT}/N64Recomp/include ${PORT}/RecompiledFuncs)
target_compile_options(pw64_recompiled PRIVATE -O2)

# ---- executable
set(APP ${PORT}/src)
add_executable(pw64 ${APP}/main.cpp ${APP}/callbacks.cpp ${APP}/rom.cpp ${APP}/sections.cpp
                    ${APP}/patch_host.cpp ${APP}/register_patches.cpp ${APP}/libultra_stubs.cpp
                    ${APP}/testdrive.cpp ${APP}/audio_hle.cpp ${APP}/resample.cpp ${APP}/audiodiag.cpp
                    ${APP}/crash_handler.cpp
                    ${CMAKE_CURRENT_SOURCE_DIR}/web_renderer.cpp
                    ${CMAKE_CURRENT_SOURCE_DIR}/web_rdp.cpp
                    ${CMAKE_CURRENT_SOURCE_DIR}/web_audio.cpp
                    ${CMAKE_CURRENT_SOURCE_DIR}/web_input.cpp)
set_source_files_properties(${CMAKE_CURRENT_SOURCE_DIR}/web_rdp.cpp PROPERTIES COMPILE_OPTIONS "-O3;-ffast-math")
set_source_files_properties(${APP}/callbacks.cpp PROPERTIES COMPILE_OPTIONS
                            "-include;${CMAKE_CURRENT_SOURCE_DIR}/web_audio.h")
target_include_directories(pw64 PRIVATE ${PORT}/include ${RT}/thirdparty/xxHash ${RT}/N64Recomp/include
                           ${PORT}/RecompiledFuncs)
target_link_libraries(pw64 PRIVATE librecomp ultramodern pw64_recompiled)
target_compile_options(pw64 PRIVATE -sUSE_SDL=2)
target_link_options(pw64 PRIVATE ${THREAD_FLAGS} -sUSE_SDL=2 -sUSE_WEBGL2=1 -sFULL_ES3=1
  -sPROXY_TO_PTHREAD=1 -sPTHREAD_POOL_SIZE=24 -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=256MB
  -sSTACK_SIZE=4MB -sDEFAULT_PTHREAD_STACK_SIZE=2MB -sOFFSCREENCANVAS_SUPPORT=1
  -sEXIT_RUNTIME=0 -Wl,--error-limit=0 -sEXPORTED_RUNTIME_METHODS=FS,callMain,ENV -sFORCE_FILESYSTEM=1
  "SHELL:--pre-js ${CMAKE_CURRENT_SOURCE_DIR}/web_pre.js"
  "SHELL:--shell-file ${CMAKE_CURRENT_SOURCE_DIR}/shell.html"
  "SHELL:--preload-file ${CMAKE_CURRENT_SOURCE_DIR}/../../build/pilotwings64.clean.z64@/pilotwings64.clean.z64"
  "SHELL:--preload-file ${PORT}/tools/scripts@/scripts")
set_target_properties(pw64 PROPERTIES SUFFIX ".html")
