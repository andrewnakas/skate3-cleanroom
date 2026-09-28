// Web renderer context: display lists go to the software RDP (web_rdp.cpp) on
// the graphics worker; the framebuffer the VI is showing is copied out and
// presented by the page's main thread (web_pre.js, Module.pw64Present).
#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

#include <emscripten.h>
#include <emscripten/threading.h>

#include "pw64/renderer.h"
#include "web_rdp.h"

namespace {

class WebContext final : public ultramodern::renderer::RendererContext {
public:
    explicit WebContext(uint8_t* rdram) : rdp_(rdram, 4) {
        setup_result = ultramodern::renderer::SetupResult::Success;
        chosen_api = ultramodern::renderer::GraphicsApi::Auto;
    }
    bool valid() override { return true; }
    bool update_config(const ultramodern::renderer::GraphicsConfig&,
                       const ultramodern::renderer::GraphicsConfig&) override { return true; }
    void enable_instant_present() override {}
    void send_dl(const OSTask* task) override {
        double t0 = emscripten_get_now();
        rdp_.run(uint32_t(task->t.data_ptr) & 0x1FFFFFFF);
        rdp_ms_ += emscripten_get_now() - t0;
        ++dls_;
    }
    void send_dummy_workload(uint32_t) override {}
    void update_screen() override {
        uint32_t origin = ultramodern::renderer::get_vi_regs()->VI_ORIGIN_REG & 0x1FFFFFFF;
        const webrdp::Framebuffer* fb = rdp_.find(origin);
        if (fb != nullptr) {
            // Double-buffered so the async present never reads a frame being written.
            std::vector<uint32_t>& out = present_[flip_ ^= 1];
            out = fb->rgba;
            MAIN_THREAD_ASYNC_EM_ASM({ Module.pw64Present($0, $1, $2); }, out.data(), fb->width, fb->height);
        }
        if (++frames_ % 300 == 0) {
            std::fprintf(stderr, "[web] frame %u, display lists %u, rdp %.1f ms/dl\n", frames_, dls_,
                         dls_ > last_dls_ ? rdp_ms_ / (dls_ - last_dls_) : 0.0);
            rdp_ms_ = 0;
            last_dls_ = dls_;
        }
    }
    void shutdown() override {}
    uint32_t get_display_framerate() const override { return 60; }
    float get_resolution_scale() const override { return 1.0f; }

private:
    webrdp::Renderer rdp_;
    std::vector<uint32_t> present_[2];
    int flip_ = 0;
    unsigned frames_ = 0;
    unsigned dls_ = 0, last_dls_ = 0;
    double rdp_ms_ = 0;
};

}  // namespace

namespace pw64 {
std::unique_ptr<ultramodern::renderer::RendererContext> create_render_context(
        uint8_t* rdram, ultramodern::renderer::WindowHandle, bool) {
    return std::make_unique<WebContext>(rdram);
}
}  // namespace pw64
