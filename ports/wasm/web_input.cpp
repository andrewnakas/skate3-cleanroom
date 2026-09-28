// Web input (see web_audio.h): the page writes keyboard and gamepad state into
// these buffers from its main thread; the game's input callbacks read them.
#include <cstring>

#include <emscripten.h>
#include <emscripten/threading.h>

#include "web_audio.h"

namespace {
Uint8 g_keys[512];
// pad: [0] connected, [1..17] buttons (standard mapping, 0/1), [20..] int16 axes
// LX, LY, RX, RY, LT, RT scaled to SDL's -32768..32767 / 0..32767
alignas(4) Uint8 g_pad[64];
bool g_registered = false;
bool g_announced = false;

void register_buffers() {
    if (g_registered) return;
    g_registered = true;
    MAIN_THREAD_EM_ASM({ Module.pw64InputInit($0, $1); }, g_keys, g_pad);
}
}  // namespace

extern "C" const Uint8* pw64web_keys(void) {
    register_buffers();
    return g_keys;
}

extern "C" int pw64web_poll_event(SDL_Event* e) {
    register_buffers();
    // Surface a connected gamepad once, as SDL would, so the port opens it.
    if (!g_announced && __atomic_load_n(&g_pad[0], __ATOMIC_RELAXED)) {
        g_announced = true;
        std::memset(e, 0, sizeof(*e));
        e->type = SDL_CONTROLLERDEVICEADDED;
        e->cdevice.which = 0;
        return 1;
    }
    return 0;
}

extern "C" SDL_bool pw64web_pad_button(int b) {
    static const int map[] = {
        0,   // SDL_CONTROLLER_BUTTON_A
        1,   // B
        2,   // X
        3,   // Y
        8,   // BACK
        16,  // GUIDE
        9,   // START
        10,  // LEFTSTICK
        11,  // RIGHTSTICK
        4,   // LEFTSHOULDER
        5,   // RIGHTSHOULDER
        12,  // DPAD_UP
        13,  // DPAD_DOWN
        14,  // DPAD_LEFT
        15,  // DPAD_RIGHT
    };
    if (b < 0 || b >= int(sizeof(map) / sizeof(map[0]))) return SDL_FALSE;
    return g_pad[1 + map[b]] ? SDL_TRUE : SDL_FALSE;
}

extern "C" Sint16 pw64web_pad_axis(int a) {
    if (a < 0 || a > 5) return 0;
    Sint16 v;
    std::memcpy(&v, g_pad + 20 + a * 2, 2);   // LEFTX, LEFTY, RIGHTX, RIGHTY, TRIGGERLEFT, TRIGGERRIGHT
    return v;
}
