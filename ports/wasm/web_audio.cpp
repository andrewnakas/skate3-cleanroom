// WebAudio output for the web build (see web_audio.h). Interleaved stereo
// S16 frames are copied into a JS queue on the main thread and played by a
// ScriptProcessorNode; the queue depth is reported back so the game paces
// its audio thread exactly as it does against SDL's queue on the desktop.
#include <emscripten.h>
#include <emscripten/threading.h>

#include "web_audio.h"

extern "C" SDL_AudioDeviceID pw64web_audio_open(const SDL_AudioSpec* want, SDL_AudioSpec* have) {
    int rate = MAIN_THREAD_EM_ASM_INT({ return Module.pw64AudioOpen(); });
    if (have != nullptr) {
        *have = *want;
        have->freq = rate;
        have->channels = 2;
        have->format = AUDIO_S16SYS;
    }
    return 1;
}

extern "C" int pw64web_audio_queue(const void* data, Uint32 bytes) {
    MAIN_THREAD_EM_ASM({ Module.pw64AudioQueue($0, $1); }, data, bytes);
    return 0;
}

extern "C" Uint32 pw64web_audio_queued_bytes(void) {
    return (Uint32)MAIN_THREAD_EM_ASM_INT({ return Module.pw64AudioFrames() * 4; });
}
