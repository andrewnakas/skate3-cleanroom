// Software F3D + RDP for the web build: interprets the game's display lists
// (F3D NoN, SDK 2.0E -- Fast3D opcodes) and rasterises them into RGBA
// framebuffers keyed by their RDRAM address. Written from the public GBI
// documentation (gbi.h, n64brew); no microcode or emulator code involved.
#pragma once
#include <condition_variable>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

namespace webrdp {

struct Framebuffer {
    uint32_t addr = 0;
    int width = 320, height = 240;
    std::vector<uint32_t> rgba;   // 0xAABBGGRR (little-endian RGBA bytes)
    std::vector<int8_t> stencil;  // shadow-volume counts (emulates coverage-bit shadows)
};

class Renderer {
public:
    // The front renderer (bands > 0) interprets F3D and records RDP commands;
    // `bands` band renderers replay them in parallel, each drawing its rows.
    Renderer(uint8_t* rdram, int bands);
    ~Renderer();
    // Runs one graphics task's display list.
    void run(uint32_t dl_addr);
    // The framebuffer that contains VI origin `origin`, or null.
    const Framebuffer* find(uint32_t origin) const;

private:
    struct Vtx {
        float x, y, z, w;        // clip space
        float sx, sy, sz;        // screen (pixels) and depth 0..1
        float s, t;              // texel units
        float r, g, b, a;        // 0..255
        uint8_t clip;
    };
    struct Tile {
        int fmt = 0, siz = 0, line = 0, tmem = 0, palette = 0;
        int cms = 0, cmt = 0, masks = 0, maskt = 0, shifts = 0, shiftt = 0;
        int uls = 0, ult = 0, lrs = 0, lrt = 0;   // 10.2
    };
    struct Color { float r, g, b, a; };

    // memory
    uint32_t rd32(uint32_t a) const { return *reinterpret_cast<const uint32_t*>(rdram_ + (a & 0x7FFFFC)); }
    uint16_t rd16(uint32_t a) const { return *reinterpret_cast<const uint16_t*>(rdram_ + ((a ^ 2) & 0x7FFFFE)); }
    uint8_t rd8(uint32_t a) const { return rdram_[(a ^ 3) & 0x7FFFFF]; }
    uint32_t seg(uint32_t a) const { return (segments_[(a >> 24) & 0xF] + (a & 0xFFFFFF)) & 0x7FFFFF; }

    // F3D
    void load_matrix(uint32_t addr, float out[4][4]);
    void cmd_mtx(uint32_t w0, uint32_t w1);
    void cmd_vtx(uint32_t w0, uint32_t w1);
    void cmd_movemem(uint32_t w0, uint32_t w1);
    void cmd_moveword(uint32_t w0, uint32_t w1);
    void update_mvp();
    void triangle(int a, int b, int c);

    // RDP
    void set_other_mode(int word, uint32_t shift, uint32_t len, uint32_t value);
    void load_block(uint32_t w0, uint32_t w1);
    void load_tile(uint32_t w0, uint32_t w1);
    void load_tlut(uint32_t w0, uint32_t w1);
    void fill_rect(uint32_t w0, uint32_t w1);
    void tex_rect(uint32_t w0, uint32_t w1, uint32_t st, uint32_t dsdt, bool flip);
    Framebuffer& target();

    // raster
    void raster(const Vtx& v0, const Vtx& v1, const Vtx& v2, int mode = 0);  // +-1: shadow volume face
    Color texel(int tile, float s, float t) const;
    Color fetch(const Tile& tl, int s, int t) const;
    void shade_pixel(int x, int y, float z, const Color& shade, float s, float t, float lod, bool tex);

    uint8_t* rdram_;
    uint32_t segments_[16] = {};
    // matrices
    float proj_[4][4], mv_[10][4][4], mvp_[4][4];
    int mv_top_ = 0;
    // vertices
    Vtx vtx_[32];
    // viewport (pixels)
    float vp_scale_[3] = {160, 120, 0.5f}, vp_trans_[3] = {160, 120, 0.5f};
    // lights
    int num_lights_ = 1;
    float light_col_[8][3] = {}, light_dir_[8][3] = {};
    float lookat_[2][3] = {{1, 0, 0}, {0, 1, 0}};
    // state
    uint32_t geom_ = 0, om_h_ = 0, om_l_ = 0;
    int fog_mul_ = 0, fog_off_ = 0;
    float tex_scale_s_ = 1, tex_scale_t_ = 1;
    int tex_tile_ = 0, tex_on_ = 0;
    uint32_t combine_hi_ = 0, combine_lo_ = 0;
    Color prim_{255, 255, 255, 255}, env_{255, 255, 255, 255}, fog_{0, 0, 0, 0}, blend_{0, 0, 0, 0};
    float prim_lod_ = 0;
    uint32_t fill_color_ = 0;
    uint32_t timg_addr_ = 0; int timg_siz_ = 0, timg_width_ = 1, timg_fmt_ = 0;
    uint32_t cimg_addr_ = 0; int cimg_width_ = 320;
    uint32_t zimg_addr_ = 0;
    int sc_x0_ = 0, sc_y0_ = 0, sc_x1_ = 320, sc_y1_ = 240;
    Tile tiles_[8];
    uint8_t tmem_[4096] = {};
    uint32_t half1_ = 0;
    // ---- command recording (front) and replay (bands)
    struct Cmd { uint32_t op, w0, w1, a, b; int tri; };
    struct TriRec { Vtx v[3]; uint32_t geom; int tex_on, tex_tile; float area; bool volume; };
    Renderer(uint8_t* rdram, Renderer* shared, int y0, int y1);
    void exec(const Cmd& c);          // one recorded RDP command (band side)
    void replay();                    // all of shared_->cmds_ for this band
    void resolve_shadows();           // darken pixels inside shadow volumes
    float shadow_alpha_ = 0;
    void ensure_buffers();            // front: allocate the current cimg/zimg
    std::vector<Cmd> cmds_;
    std::vector<TriRec> tris_;
    Renderer* shared_ = nullptr;      // bands: the front renderer (owns buffers + commands)
    int band_y0_ = 0, band_y1_ = 1 << 20;
    std::vector<std::unique_ptr<Renderer>> bands_;
    std::vector<std::thread> workers_;
    std::mutex mu_;
    std::condition_variable cv_start_, cv_done_;
    unsigned generation_ = 0;
    int pending_ = 0;
    bool quit_ = false;

    // per-triangle combiner/blender decode
    struct Comb { int a, b, c, d; };
    Comb cc_[2], ac_[2];
    int csel_[2][4] = {}, asel_[2][4] = {};
    void decode_combiner();

    std::map<uint32_t, Framebuffer> fbs_;
    std::map<uint32_t, std::vector<float>> zbs_;   // keyed by the colour buffer they serve
    Framebuffer* cur_ = nullptr;
    std::vector<float>* curz_ = nullptr;
};

}  // namespace webrdp
