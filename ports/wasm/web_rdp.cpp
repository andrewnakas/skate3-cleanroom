// Software F3D + RDP for the web build. See web_rdp.h.
#include "web_rdp.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace webrdp {

namespace {

// Othermode H/L fields (gbi.h).
constexpr int CYCLE_SHIFT = 20;
constexpr uint32_t CYC_1 = 0, CYC_2 = 1, CYC_COPY = 2, CYC_FILL = 3;
constexpr int TEXTFILT_SHIFT = 12, TEXTLUT_SHIFT = 14;

constexpr uint32_t G_ZBUFFER = 0x1, G_SHADE = 0x4, G_SHADING_SMOOTH = 0x200, G_CULL_FRONT = 0x1000,
                   G_CULL_BACK = 0x2000, G_FOG = 0x10000, G_LIGHTING = 0x20000, G_TEXTURE_GEN = 0x40000;

constexpr uint32_t Z_CMP = 0x10, Z_UPD = 0x20, FORCE_BL = 0x4000, ALPHA_CVG_SEL = 0x2000,
                   CVG_X_ALPHA = 0x1000;

inline float clamp255(float v) { return v < 0 ? 0 : (v > 255 ? 255 : v); }

inline uint32_t pack(float r, float g, float b) {
    return 0xFF000000u | (uint32_t(clamp255(b)) << 16) | (uint32_t(clamp255(g)) << 8) | uint32_t(clamp255(r));
}

inline void unpack(uint32_t p, float& r, float& g, float& b) {
    r = float(p & 0xFF); g = float((p >> 8) & 0xFF); b = float((p >> 16) & 0xFF);
}

void mul(const float a[4][4], const float b[4][4], float out[4][4]) {
    float r[4][4];
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++)
            r[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] + a[i][3] * b[3][j];
    std::memcpy(out, r, sizeof(r));
}

}  // namespace

// ------------------------------------------------------------------ memory/fb

Framebuffer& Renderer::target() {
    Renderer* owner = shared_ ? shared_ : this;
    Framebuffer& fb = owner->fbs_[cimg_addr_];     // allocated by the front (ensure_buffers)
    cur_ = &fb;
    curz_ = &owner->zbs_[zimg_addr_];
    return fb;
}

void Renderer::ensure_buffers() {
    Framebuffer& fb = fbs_[cimg_addr_];
    if (fb.rgba.empty() || fb.width != cimg_width_) {
        fb.addr = cimg_addr_;
        fb.width = cimg_width_;
        fb.height = cimg_width_ * 3 / 4;
        fb.rgba.assign(size_t(fb.width) * fb.height, 0xFF000000u);
        fb.stencil.assign(fb.rgba.size(), 0);
    }
    auto& z = zbs_[zimg_addr_];
    if (z.size() < fb.rgba.size()) z.assign(fb.rgba.size(), 1e30f);
}

const Framebuffer* Renderer::find(uint32_t origin) const {
    origin &= 0x7FFFFF;
    const Framebuffer* best = nullptr;
    for (auto& [addr, fb] : fbs_) {
        uint32_t end = addr + uint32_t(fb.width * fb.height * 2);
        if (origin >= addr && origin < end) best = &fb;
    }
    return best;
}

// ------------------------------------------------------------------ F3D

void Renderer::load_matrix(uint32_t addr, float out[4][4]) {
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) {
            int k = i * 4 + j;
            int16_t hi = int16_t(rd16(addr + k * 2));
            uint16_t lo = rd16(addr + 32 + k * 2);
            out[i][j] = float((int32_t(hi) << 16) | lo) / 65536.0f;
        }
}

void Renderer::update_mvp() { mul(mv_[mv_top_], proj_, mvp_); }

void Renderer::cmd_mtx(uint32_t w0, uint32_t w1) {
    uint32_t p = (w0 >> 16) & 0xFF;
    float m[4][4];
    load_matrix(seg(w1), m);
    if (p & 0x01) {                         // projection
        if (p & 0x02) std::memcpy(proj_, m, sizeof(m));
        else mul(m, proj_, proj_);
    } else {
        if ((p & 0x04) && mv_top_ < 9) {    // push
            std::memcpy(mv_[mv_top_ + 1], mv_[mv_top_], sizeof(m));
            mv_top_++;
        }
        if (p & 0x02) std::memcpy(mv_[mv_top_], m, sizeof(m));
        else mul(m, mv_[mv_top_], mv_[mv_top_]);
    }
    update_mvp();
}

void Renderer::cmd_vtx(uint32_t w0, uint32_t w1) {
    int n = ((w0 >> 20) & 0xF) + 1;
    int v0 = (w0 >> 16) & 0xF;
    uint32_t a = seg(w1);
    const float (*mv)[4] = mv_[mv_top_];
    // light directions into model space (the ucode transforms them by the
    // modelview so object-space normals can be dotted directly)
    float ldir[8][3];
    if (geom_ & (G_LIGHTING | G_TEXTURE_GEN)) {
        for (int l = 0; l <= num_lights_ && l < 8; l++) {
            const float* d = light_dir_[l];
            float x = mv[0][0] * d[0] + mv[0][1] * d[1] + mv[0][2] * d[2];
            float y = mv[1][0] * d[0] + mv[1][1] * d[1] + mv[1][2] * d[2];
            float z = mv[2][0] * d[0] + mv[2][1] * d[1] + mv[2][2] * d[2];
            float len = std::sqrt(x * x + y * y + z * z);
            if (len > 0) { x /= len; y /= len; z /= len; }
            ldir[l][0] = x; ldir[l][1] = y; ldir[l][2] = z;
        }
    }
    for (int i = 0; i < n && v0 + i < 32; i++, a += 16) {
        Vtx& v = vtx_[v0 + i];
        float x = int16_t(rd16(a)), y = int16_t(rd16(a + 2)), z = int16_t(rd16(a + 4));
        float s = int16_t(rd16(a + 8)), t = int16_t(rd16(a + 10));
        uint8_t c0 = rd8(a + 12), c1 = rd8(a + 13), c2 = rd8(a + 14), c3 = rd8(a + 15);
        v.x = x * mvp_[0][0] + y * mvp_[1][0] + z * mvp_[2][0] + mvp_[3][0];
        v.y = x * mvp_[0][1] + y * mvp_[1][1] + z * mvp_[2][1] + mvp_[3][1];
        v.z = x * mvp_[0][2] + y * mvp_[1][2] + z * mvp_[2][2] + mvp_[3][2];
        v.w = x * mvp_[0][3] + y * mvp_[1][3] + z * mvp_[2][3] + mvp_[3][3];
        v.a = c3;
        if (geom_ & G_LIGHTING) {
            float nx = int8_t(c0), ny = int8_t(c1), nz = int8_t(c2);
            float len = std::sqrt(nx * nx + ny * ny + nz * nz);
            if (len > 0) { nx /= len; ny /= len; nz /= len; }
            float r = light_col_[num_lights_][0], g = light_col_[num_lights_][1], b = light_col_[num_lights_][2];
            for (int l = 0; l < num_lights_; l++) {
                float d = nx * ldir[l][0] + ny * ldir[l][1] + nz * ldir[l][2];
                if (d > 0) { r += d * light_col_[l][0]; g += d * light_col_[l][1]; b += d * light_col_[l][2]; }
            }
            v.r = clamp255(r); v.g = clamp255(g); v.b = clamp255(b);
            if (geom_ & G_TEXTURE_GEN) {
                // normal in eye space, projected on the lookat axes
                float ex = nx * mv[0][0] + ny * mv[1][0] + nz * mv[2][0];
                float ey = nx * mv[0][1] + ny * mv[1][1] + nz * mv[2][1];
                float ez = nx * mv[0][2] + ny * mv[1][2] + nz * mv[2][2];
                float el = std::sqrt(ex * ex + ey * ey + ez * ez);
                if (el > 0) { ex /= el; ey /= el; ez /= el; }
                float ds = ex * lookat_[0][0] + ey * lookat_[0][1] + ez * lookat_[0][2];
                float dt = ex * lookat_[1][0] + ey * lookat_[1][1] + ez * lookat_[1][2];
                s = (ds * 0.5f + 0.5f) * 1024.0f * 32.0f;
                t = (dt * 0.5f + 0.5f) * 1024.0f * 32.0f;
            }
        } else {
            v.r = c0; v.g = c1; v.b = c2;
        }
        v.s = s * tex_scale_s_ / 32.0f;
        v.t = t * tex_scale_t_ / 32.0f;
        if (geom_ & G_FOG) {
            float wz = v.w != 0 ? v.z / v.w : 0;
            if (v.w < 0) wz = -wz;
            float f = wz * float(fog_mul_) + float(fog_off_);
            v.a = std::clamp(f, 0.0f, 255.0f);
        }
        v.clip = 0;
        if (v.w <= 0.0001f) v.clip = 1;
    }
}

void Renderer::cmd_movemem(uint32_t w0, uint32_t w1) {
    int idx = (w0 >> 16) & 0xFF;
    uint32_t a = seg(w1);
    if (idx == 0x80) {                      // viewport (quarter pixels)
        for (int i = 0; i < 3; i++) {
            vp_scale_[i] = int16_t(rd16(a + i * 2)) / 4.0f;
            vp_trans_[i] = int16_t(rd16(a + 8 + i * 2)) / 4.0f;
        }
        vp_scale_[2] = int16_t(rd16(a + 4)) / 1023.0f / 1.0f;
        vp_trans_[2] = int16_t(rd16(a + 12)) / 1023.0f;
    } else if (idx == 0x82 || idx == 0x84) { // lookat y / x
        int k = idx == 0x84 ? 0 : 1;
        float x = int8_t(rd8(a + 8)), y = int8_t(rd8(a + 9)), z = int8_t(rd8(a + 10));
        float len = std::sqrt(x * x + y * y + z * z);
        if (len > 0) { lookat_[k][0] = x / len; lookat_[k][1] = y / len; lookat_[k][2] = z / len; }
    } else if (idx >= 0x86 && idx <= 0x94) { // lights
        int l = (idx - 0x86) / 2;
        light_col_[l][0] = rd8(a); light_col_[l][1] = rd8(a + 1); light_col_[l][2] = rd8(a + 2);
        float x = int8_t(rd8(a + 8)), y = int8_t(rd8(a + 9)), z = int8_t(rd8(a + 10));
        float len = std::sqrt(x * x + y * y + z * z);
        if (len > 0) { x /= len; y /= len; z /= len; }
        light_dir_[l][0] = x; light_dir_[l][1] = y; light_dir_[l][2] = z;
    }
}

void Renderer::cmd_moveword(uint32_t w0, uint32_t w1) {
    int index = w0 & 0xFF;
    int offset = (w0 >> 8) & 0xFFFF;
    switch (index) {
        case 0x02: num_lights_ = std::clamp(int((w1 & 0x7FFFFFFF) / 32) - 1, 0, 7); break;  // NUMLIGHT
        case 0x06: segments_[(offset >> 2) & 0xF] = w1 & 0x7FFFFF; break;                     // SEGMENT
        case 0x08: fog_mul_ = int16_t(w1 >> 16); fog_off_ = int16_t(w1 & 0xFFFF); break;       // FOG
        case 0x0A: {                                                                          // LIGHTCOL
            int l = (offset >> 5) & 7;
            light_col_[l][0] = (w1 >> 24) & 0xFF; light_col_[l][1] = (w1 >> 16) & 0xFF; light_col_[l][2] = (w1 >> 8) & 0xFF;
            break;
        }
        default: break;
    }
}

// ------------------------------------------------------------------ RDP state

void Renderer::set_other_mode(int word, uint32_t shift, uint32_t len, uint32_t value) {
    uint32_t mask = (len >= 32 ? 0xFFFFFFFFu : ((1u << len) - 1)) << shift;
    uint32_t& m = word ? om_h_ : om_l_;
    m = (m & ~mask) | (value & mask);
}

void Renderer::decode_combiner() {
    uint32_t w0 = combine_hi_, w1 = combine_lo_;
    cc_[0] = {int((w0 >> 20) & 0xF), int((w1 >> 28) & 0xF), int((w0 >> 15) & 0x1F), int((w1 >> 15) & 0x7)};
    ac_[0] = {int((w0 >> 12) & 0x7), int((w1 >> 12) & 0x7), int((w0 >> 9) & 0x7), int((w1 >> 9) & 0x7)};
    cc_[1] = {int((w0 >> 5) & 0xF), int((w1 >> 24) & 0xF), int(w0 & 0x1F), int((w1 >> 6) & 0x7)};
    ac_[1] = {int((w1 >> 21) & 0x7), int((w1 >> 3) & 0x7), int((w1 >> 18) & 0x7), int(w1 & 0x7)};
    // colour selects -> table offsets (see shade_pixel)
    static const int base[8] = {0, 3, 6, 9, 12, 15, 18, 21};  // comb t0 t1 prim shade env one zero
    for (int k = 0; k < 2; k++) {
        const Comb& c = cc_[k];
        csel_[k][0] = c.a < 7 ? base[c.a] : (c.a == 7 ? 48 : 21);
        csel_[k][1] = c.b < 6 ? base[c.b] : 21;
        static const int cmap[16] = {0, 3, 6, 9, 12, 15, 21, 24, 27, 30, 33, 36, 39, 42, 45, 21};
        csel_[k][2] = c.c < 16 ? cmap[c.c] : 21;
        csel_[k][3] = c.d < 7 ? base[c.d] : 21;
        const Comb& a = ac_[k];
        static const int amap[8] = {24, 27, 30, 33, 36, 39, 18, 21};     // comb t0 t1 prim shade env one zero
        static const int acmap[8] = {42, 27, 30, 33, 36, 39, 45, 21};    // lod t0 t1 prim shade env primlod zero
        asel_[k][0] = amap[a.a]; asel_[k][1] = amap[a.b]; asel_[k][2] = acmap[a.c]; asel_[k][3] = amap[a.d];
    }
}

void Renderer::load_block(uint32_t w0, uint32_t w1) {
    int tile = (w1 >> 24) & 7;
    int uls = (w0 >> 12) & 0xFFF, ult = w0 & 0xFFF;
    int lrs = (w1 >> 12) & 0xFFF, dxt = w1 & 0xFFF;
    Tile& tl = tiles_[tile];
    int bytes;
    if (timg_siz_ == 0) bytes = (lrs + 1 + 1) / 2;
    else bytes = (lrs + 1) << (timg_siz_ - 1);
    bytes = (bytes + 7) & ~7;
    uint32_t src = timg_addr_ + uint32_t((ult * timg_width_ + uls) << timg_siz_ >> 1);
    int dst = tl.tmem * 8;
    int line_acc = 0;
    for (int i = 0; i < bytes; i += 8) {
        bool odd = dxt != 0 && ((line_acc >> 11) & 1);
        for (int k = 0; k < 8; k++) {
            int d = (dst + i + (odd ? (k ^ 4) : k)) & 0xFFF;
            tmem_[d] = rd8(src + i + k);
        }
        line_acc += dxt;
    }
}

void Renderer::load_tile(uint32_t w0, uint32_t w1) {
    int tile = (w1 >> 24) & 7;
    int uls = ((w0 >> 12) & 0xFFF) >> 2, ult = (w0 & 0xFFF) >> 2;
    int lrs = ((w1 >> 12) & 0xFFF) >> 2, lrt = (w1 & 0xFFF) >> 2;
    Tile& tl = tiles_[tile];
    tl.uls = uls << 2; tl.ult = ult << 2; tl.lrs = lrs << 2; tl.lrt = lrt << 2;
    int row_bytes = ((lrs - uls + 1) << timg_siz_) >> 1;
    int line = tl.line * 8;
    for (int y = 0; y <= lrt - ult; y++) {
        uint32_t src = timg_addr_ + uint32_t((((ult + y) * timg_width_ + uls) << timg_siz_) >> 1);
        int dst = tl.tmem * 8 + y * line;
        for (int k = 0; k < row_bytes; k++) {
            int d = dst + k;
            if (y & 1) d ^= 4;
            tmem_[d & 0xFFF] = rd8(src + k);
        }
    }
}

void Renderer::load_tlut(uint32_t w0, uint32_t w1) {
    int tile = (w1 >> 24) & 7;
    int uls = ((w0 >> 12) & 0xFFF) >> 2;
    int lrs = ((w1 >> 12) & 0xFFF) >> 2;
    int count = lrs - uls + 1;
    int dst = tiles_[tile].tmem * 8;
    uint32_t src = timg_addr_ + uint32_t(uls * 2);
    for (int i = 0; i < count * 2; i++) tmem_[(dst + i) & 0xFFF] = rd8(src + i);
}

// ------------------------------------------------------------------ textures

Renderer::Color Renderer::fetch(const Tile& tl, int s, int t) const {
    int line = tl.line * 8;
    int base = tl.tmem * 8 + t * line;
    int x = (t & 1) ? 4 : 0;
    auto b = [&](int off) { return tmem_[((base + off) ^ x) & 0xFFF]; };
    switch (tl.siz) {
        case 0: {  // 4-bit
            uint8_t v = b(s >> 1);
            int n = (s & 1) ? (v & 0xF) : (v >> 4);
            if (tl.fmt == 2) {  // CI4
                int idx = (tl.palette << 4) | n;
                uint16_t c = uint16_t(tmem_[(0x800 + idx * 2) & 0xFFF] << 8 | tmem_[(0x801 + idx * 2) & 0xFFF]);
                return {float((c >> 11) & 31) * 8.2258f, float((c >> 6) & 31) * 8.2258f, float((c >> 1) & 31) * 8.2258f, (c & 1) ? 255.f : 0.f};
            }
            if (tl.fmt == 3) {  // IA4
                float i = float(n >> 1) * 36.43f;
                return {i, i, i, (n & 1) ? 255.f : 0.f};
            }
            float i = float(n) * 17.0f;  // I4
            return {i, i, i, i};
        }
        case 1: {  // 8-bit
            uint8_t v = b(s);
            if (tl.fmt == 2) {  // CI8
                uint16_t c = uint16_t(tmem_[(0x800 + v * 2) & 0xFFF] << 8 | tmem_[(0x801 + v * 2) & 0xFFF]);
                return {float((c >> 11) & 31) * 8.2258f, float((c >> 6) & 31) * 8.2258f, float((c >> 1) & 31) * 8.2258f, (c & 1) ? 255.f : 0.f};
            }
            if (tl.fmt == 3) {  // IA8
                float i = float(v >> 4) * 17.0f;
                return {i, i, i, float(v & 0xF) * 17.0f};
            }
            float i = v;       // I8
            return {i, i, i, i};
        }
        case 2: {  // 16-bit
            uint16_t c = uint16_t(b(s * 2) << 8 | b(s * 2 + 1));
            if (tl.fmt == 3) {  // IA16
                float i = float(c >> 8);
                return {i, i, i, float(c & 0xFF)};
            }
            return {float((c >> 11) & 31) * 8.2258f, float((c >> 6) & 31) * 8.2258f, float((c >> 1) & 31) * 8.2258f, (c & 1) ? 255.f : 0.f};
        }
        default: {  // 32-bit RGBA: RG in low TMEM half, BA in high half
            int off = base + s * 2;
            float r = tmem_[(off ^ x) & 0x7FF], g = tmem_[((off + 1) ^ x) & 0x7FF];
            float bb = tmem_[(0x800 | ((off ^ x) & 0x7FF))], a = tmem_[(0x800 | (((off + 1) ^ x) & 0x7FF))];
            return {r, g, bb, a};
        }
    }
}

namespace {
inline int wrap(int c, int mask, int cm, int lo, int hi) {
    // clamp first (if clamp bit or no mask), then mirror/wrap within the mask
    if ((cm & 2) || mask == 0) c = std::clamp(c, lo, hi);
    if (mask) {
        int m = (1 << mask) - 1;
        if (cm & 1) {
            if (c & (m + 1)) c = m - (c & m);
            else c &= m;
        } else {
            c &= m;
        }
    }
    return c;
}
}  // namespace

Renderer::Color Renderer::texel(int tile, float s, float t) const {
    const Tile& tl = tiles_[tile & 7];
    auto shift = [](float v, int sh) {
        if (sh == 0) return v;
        if (sh <= 10) return v / float(1 << sh);
        return v * float(1 << (16 - sh));
    };
    s = shift(s, tl.shifts) - tl.uls / 4.0f;
    t = shift(t, tl.shiftt) - tl.ult / 4.0f;
    int ws = (tl.lrs - tl.uls) / 4, wt = (tl.lrt - tl.ult) / 4;
    int filt = (om_h_ >> TEXTFILT_SHIFT) & 3;
    if (filt == 0 || ((om_h_ >> CYCLE_SHIFT) & 3) == CYC_COPY) {
        int is = wrap(int(std::floor(s)), tl.masks, tl.cms, 0, ws);
        int it = wrap(int(std::floor(t)), tl.maskt, tl.cmt, 0, wt);
        return fetch(tl, is, it);
    }
    s -= 0.5f; t -= 0.5f;
    int s0 = int(std::floor(s)), t0 = int(std::floor(t));
    float fs = s - s0, ft = t - t0;
    int sa = wrap(s0, tl.masks, tl.cms, 0, ws), sb = wrap(s0 + 1, tl.masks, tl.cms, 0, ws);
    int ta = wrap(t0, tl.maskt, tl.cmt, 0, wt), tb = wrap(t0 + 1, tl.maskt, tl.cmt, 0, wt);
    Color c00 = fetch(tl, sa, ta), c10 = fetch(tl, sb, ta), c01 = fetch(tl, sa, tb), c11 = fetch(tl, sb, tb);
    auto lerp2 = [&](float a, float b, float c, float d) {
        return (a * (1 - fs) + b * fs) * (1 - ft) + (c * (1 - fs) + d * fs) * ft;
    };
    return {lerp2(c00.r, c10.r, c01.r, c11.r), lerp2(c00.g, c10.g, c01.g, c11.g),
            lerp2(c00.b, c10.b, c01.b, c11.b), lerp2(c00.a, c10.a, c01.a, c11.a)};
}

// ------------------------------------------------------------------ pixel pipeline

void Renderer::shade_pixel(int x, int y, float z, const Color& shade, float s, float t, float lod, bool tex) {
    Framebuffer& fb = *cur_;
    size_t idx = size_t(y) * fb.width + x;
    uint32_t cyc = (om_h_ >> CYCLE_SHIFT) & 3;
    bool zcmp = (om_l_ & Z_CMP) && (geom_ & G_ZBUFFER) && cyc < 2;
    if (zcmp) {
        float zb = (*curz_)[idx];
        bool decal = ((om_l_ >> 10) & 3) == 3;
        if (decal ? z > zb * 1.004f + 0.5f : z > zb * 1.00002f) return;
    }
    Color t0{0, 0, 0, 0}, t1{0, 0, 0, 0};
    if (tex) {
        t0 = texel(tex_tile_, s, t);
        if (cyc == CYC_2) t1 = texel(tex_tile_ + 1, s, t);
    }
    // Source table for the combiner: every input the four slots can select,
    // laid out so a decoded select is just an offset (see decode_combiner).
    //  0 comb.rgb  3 t0.rgb  6 t1.rgb  9 prim.rgb 12 shade.rgb 15 env.rgb
    // 18 one      21 zero   24 comb.a 27 t0.a  30 t1.a  33 prim.a 36 shade.a
    // 39 env.a    42 lod    45 primlod 48 noise(128)
    float T[51];
    auto put3 = [&](int o, const Color& c) { T[o] = c.r; T[o + 1] = c.g; T[o + 2] = c.b; };
    auto putA = [&](int o, float v) { T[o] = T[o + 1] = T[o + 2] = v; };
    put3(0, {0, 0, 0, 0}); put3(3, t0); put3(6, t1); put3(9, prim_); put3(12, shade); put3(15, env_);
    putA(18, 255.f); putA(21, 0.f); putA(24, 0.f); putA(27, t0.a); putA(30, t1.a); putA(33, prim_.a);
    putA(36, shade.a); putA(39, env_.a); putA(42, lod * 255.f); putA(45, prim_lod_ * 255.f); putA(48, 128.f);
    Color comb{0, 0, 0, 0};
    int cycles = (cyc == CYC_2) ? 2 : 1;
    for (int k = 0; k < cycles; k++) {
        const int* sel = csel_[k];
        const int* asel = asel_[k];
        comb.r = clamp255((T[sel[0]] - T[sel[1]]) * T[sel[2]] * (1.f / 255.f) + T[sel[3]]);
        comb.g = clamp255((T[sel[0] + 1] - T[sel[1] + 1]) * T[sel[2] + 1] * (1.f / 255.f) + T[sel[3] + 1]);
        comb.b = clamp255((T[sel[0] + 2] - T[sel[1] + 2]) * T[sel[2] + 2] * (1.f / 255.f) + T[sel[3] + 2]);
        comb.a = clamp255((T[asel[0]] - T[asel[1]]) * T[asel[2]] * (1.f / 255.f) + T[asel[3]]);
        put3(0, comb);
        putA(24, comb.a);
    }
    // alpha compare / coverage-as-alpha cutout
    if ((om_l_ & 3) == 1 && comb.a < blend_.a) return;
    // alpha used as coverage (ALPHA_CVG_SEL) without FORCE_BL: on hardware the
    // partial coverage resolves to a blend with memory, not a hard cutout
    float cvg = 1.0f;
    if ((om_l_ & ALPHA_CVG_SEL) && !(om_l_ & FORCE_BL)) {
        if (comb.a < 8.f) return;
        cvg = comb.a / 255.f;
    }
    if ((om_l_ & 3) == 0 && (om_l_ & CVG_X_ALPHA) && comb.a < 1.f) return;

    // blender
    float mr, mg, mb;
    unpack(fb.rgba[idx], mr, mg, mb);
    float inr = comb.r, ing = comb.g, inb = comb.b, ina = comb.a;
    auto run = [&](int c, float& r, float& g, float& b) {
        int P = (om_l_ >> (30 - c * 2)) & 3, A = (om_l_ >> (26 - c * 2)) & 3;
        int M = (om_l_ >> (22 - c * 2)) & 3, B = (om_l_ >> (18 - c * 2)) & 3;
        auto clr = [&](int sel, float& cr, float& cg, float& cb) {
            switch (sel) { case 0: cr = r; cg = g; cb = b; break; case 1: cr = mr; cg = mg; cb = mb; break;
                case 2: cr = blend_.r; cg = blend_.g; cb = blend_.b; break; default: cr = fog_.r; cg = fog_.g; cb = fog_.b; }
        };
        float pa;
        switch (A) { case 0: pa = ina; break; case 1: pa = fog_.a; break; case 2: pa = shade.a; break; default: pa = 0; }
        float pb;
        switch (B) { case 0: pb = 255.f - pa; break; case 1: pb = 255.f; break; case 2: pb = 255.f; break; default: pb = 0; }
        float pr, pg, pbv, qr, qg, qb;
        clr(P, pr, pg, pbv);
        clr(M, qr, qg, qb);
        float den = pa + pb;
        if (den <= 0) den = 255.f;
        r = (pr * pa + qr * pb) / den; g = (pg * pa + qg * pb) / den; b = (pbv * pa + qb * pb) / den;
    };
    float r = inr, g = ing, b = inb;
    if (cyc == CYC_2) run(0, r, g, b);
    if (om_l_ & FORCE_BL) {
        run(1, r, g, b);
    } else if (cyc == CYC_2) {
        // first-term only (no edge AA): colour selected by cycle 1's P
        int P = (om_l_ >> 28) & 3;
        if (P == 3) { r = fog_.r; g = fog_.g; b = fog_.b; }
        else if (P == 2) { r = blend_.r; g = blend_.g; b = blend_.b; }
        else if (P == 1) { r = mr; g = mg; b = mb; }
    }
    if (cvg < 1.0f) { r = mr + (r - mr) * cvg; g = mg + (g - mg) * cvg; b = mb + (b - mb) * cvg; }
    fb.rgba[idx] = pack(r, g, b);
    if ((om_l_ & Z_UPD) && (geom_ & G_ZBUFFER) && cyc < 2 && cvg >= 0.5f) (*curz_)[idx] = z;
}

// ------------------------------------------------------------------ rasteriser

void Renderer::raster(const Vtx& v0, const Vtx& v1, const Vtx& v2, int mode) {
    Framebuffer& fb = *cur_;
    float area = (v1.sx - v0.sx) * (v2.sy - v0.sy) - (v2.sx - v0.sx) * (v1.sy - v0.sy);
    if (std::fabs(area) < 1e-6f) return;
    int x0 = std::max({sc_x0_, 0, int(std::floor(std::min({v0.sx, v1.sx, v2.sx})))});
    int x1 = std::min({sc_x1_ - 1, fb.width - 1, int(std::ceil(std::max({v0.sx, v1.sx, v2.sx})))});
    int y0 = std::max({sc_y0_, 0, band_y0_, int(std::floor(std::min({v0.sy, v1.sy, v2.sy})))});
    int y1 = std::min({sc_y1_ - 1, fb.height - 1, band_y1_ - 1, int(std::ceil(std::max({v0.sy, v1.sy, v2.sy})))});
    if (x0 > x1 || y0 > y1) return;
    float iw0 = 1.0f / v0.w, iw1 = 1.0f / v1.w, iw2 = 1.0f / v2.w;
    bool tex = tex_on_ != 0;
    bool smooth = (geom_ & G_SHADING_SMOOTH) != 0;
    float inv = 1.0f / area;
    // texture LOD (for LOD_FRACTION): texels per pixel from the triangle's extents
    float lod = 0;
    // barycentrics are affine in screen space: w(px,py) = ax*px + ay*py + c
    const float a0x = -(v2.sy - v1.sy) * inv, a0y = (v2.sx - v1.sx) * inv;
    const float c0 = (v1.sx * v2.sy - v2.sx * v1.sy) * inv;
    const float a1x = -(v0.sy - v2.sy) * inv, a1y = (v0.sx - v2.sx) * inv;
    const float c1 = (v2.sx * v0.sy - v0.sx * v2.sy) * inv;
    for (int y = y0; y <= y1; y++) {
        float py = y + 0.5f;
        float px0 = x0 + 0.5f;
        float w0 = a0x * px0 + a0y * py + c0;
        float w1 = a1x * px0 + a1y * py + c1;
        for (int x = x0; x <= x1; x++, w0 += a0x, w1 += a1x) {
            float w2 = 1.0f - w0 - w1;
            if (w0 < 0 || w1 < 0 || w2 < 0) continue;
            float p0 = w0 * iw0, p1 = w1 * iw1, p2 = w2 * iw2;
            float ps = p0 + p1 + p2;
            float z = 1.0f / ps;   // eye depth: even relative precision near and far
            if (mode != 0) {
                // shadow volume face: z-pass counting against the scene depth
                size_t si = size_t(y) * fb.width + x;
                if (z < (*curz_)[si]) fb.stencil[si] = int8_t(fb.stencil[si] + mode);
                continue;
            }

            p0 /= ps; p1 /= ps; p2 /= ps;
            Color shade;
            if (smooth) {
                shade = {p0 * v0.r + p1 * v1.r + p2 * v2.r, p0 * v0.g + p1 * v1.g + p2 * v2.g,
                         p0 * v0.b + p1 * v1.b + p2 * v2.b, p0 * v0.a + p1 * v1.a + p2 * v2.a};
            } else {
                shade = {v0.r, v0.g, v0.b, p0 * v0.a + p1 * v1.a + p2 * v2.a};
            }
            float s = 0, t = 0;
            if (tex) {
                s = p0 * v0.s + p1 * v1.s + p2 * v2.s;
                t = p0 * v0.t + p1 * v1.t + p2 * v2.t;
            }
            shade_pixel(x, y, z, shade, s, t, lod, tex);
        }
    }
}

void Renderer::triangle(int ia, int ib, int ic) {
    Vtx in[3] = {vtx_[ia], vtx_[ib], vtx_[ic]};
    // clip against the near plane (w > eps) in homogeneous space
    constexpr float EPS = 0.01f;
    Vtx poly[8];
    int n = 0;
    for (int i = 0; i < 3; i++) {
        const Vtx& a = in[i];
        const Vtx& b = in[(i + 1) % 3];
        bool ain = a.w > EPS, bin = b.w > EPS;
        if (ain) poly[n++] = a;
        if (ain != bin) {
            float t = (EPS - a.w) / (b.w - a.w);
            Vtx v;
            v.x = a.x + (b.x - a.x) * t; v.y = a.y + (b.y - a.y) * t; v.z = a.z + (b.z - a.z) * t; v.w = EPS;
            v.s = a.s + (b.s - a.s) * t; v.t = a.t + (b.t - a.t) * t;
            v.r = a.r + (b.r - a.r) * t; v.g = a.g + (b.g - a.g) * t; v.b = a.b + (b.b - a.b) * t; v.a = a.a + (b.a - a.a) * t;
            poly[n++] = v;
        }
    }
    if (n < 3) return;
    for (int i = 0; i < n; i++) {
        Vtx& v = poly[i];
        float iw = 1.0f / v.w;
        v.sx = vp_trans_[0] + v.x * iw * vp_scale_[0];
        v.sy = vp_trans_[1] - v.y * iw * vp_scale_[1];
        v.sz = std::clamp(0.5f + 0.5f * v.z * iw, 0.0f, 1.0f);
    }
    // backface culling on the first triangle's winding
    float area = (poly[1].sx - poly[0].sx) * (poly[2].sy - poly[0].sy) - (poly[2].sx - poly[0].sx) * (poly[1].sy - poly[0].sy);
    // Shadow volumes (black, alpha 0: the *_SHADOW_COLUMN models) keep both
    // faces; the band decides from the render mode whether it really is one.
    bool volume = !(geom_ & G_FOG) && in[0].r == 0 && in[0].g == 0 && in[0].b == 0 &&
                  in[1].r == 0 && in[1].g == 0 && in[2].r == 0 && in[2].g == 0 &&
                  in[0].a > 0 && in[0].a < 255 && in[1].a > 0 && in[1].a < 255;
    if (!volume) {
        if ((geom_ & G_CULL_BACK) && area > 0) return;
        if ((geom_ & G_CULL_FRONT) && area < 0) return;
    }
    for (int i = 1; i + 1 < n; i++) {
        TriRec tr;
        tr.v[0] = poly[0]; tr.v[1] = poly[i]; tr.v[2] = poly[i + 1];
        tr.geom = geom_; tr.tex_on = tex_on_; tr.tex_tile = tex_tile_; tr.area = area; tr.volume = volume;
        tris_.push_back(tr);
        cmds_.push_back({0x100, 0, 0, 0, 0, int(tris_.size() - 1)});
    }
}

// ------------------------------------------------------------------ rectangles

void Renderer::fill_rect(uint32_t w0, uint32_t w1) {
    int lrx = ((w0 >> 12) & 0xFFF) >> 2, lry = (w0 & 0xFFF) >> 2;
    int ulx = ((w1 >> 12) & 0xFFF) >> 2, uly = (w1 & 0xFFF) >> 2;
    uint32_t cyc = (om_h_ >> CYCLE_SHIFT) & 3;
    if (cyc == CYC_FILL || cyc == CYC_COPY) { lrx++; lry++; }
    Framebuffer& fb = target();
    uly = std::max(uly, band_y0_); lry = std::min(lry, band_y1_);
    if (cimg_addr_ == zimg_addr_) {                   // depth clear (this band's rows)
        auto& z = *curz_;
        for (int y = std::max(uly, 0); y < std::min(lry, fb.height); y++)
            std::fill(z.begin() + size_t(y) * fb.width, z.begin() + size_t(y + 1) * fb.width, 1e30f);
        // the depth clear starts a frame: reset the shadow counts of every colour buffer's band rows
        Renderer* owner = shared_ ? shared_ : this;
        for (auto& [addr, cfb] : owner->fbs_) {
            if (cfb.stencil.size() != cfb.rgba.size()) continue;
            for (int y = std::max(uly, 0); y < std::min(lry, cfb.height); y++)
                std::fill(cfb.stencil.begin() + size_t(y) * cfb.width, cfb.stencil.begin() + size_t(y + 1) * cfb.width, 0);
        }
        return;
    }
    ulx = std::max(ulx, sc_x0_); uly = std::max(uly, sc_y0_);
    lrx = std::min({lrx, sc_x1_, fb.width}); lry = std::min({lry, sc_y1_, fb.height});
    uint32_t c;
    if (cyc == CYC_FILL) {
        uint16_t p = uint16_t(fill_color_ >> 16);
        c = pack(((p >> 11) & 31) * 8.2258f, ((p >> 6) & 31) * 8.2258f, ((p >> 1) & 31) * 8.2258f);
    } else {
        c = pack(prim_.r, prim_.g, prim_.b);   // 1/2-cycle fill rect: combiner usually prim
        for (int y = uly; y < lry; y++)
            for (int x = ulx; x < lrx; x++)
                shade_pixel(x, y, 0, prim_, 0, 0, 0, false);
        return;
    }
    for (int y = uly; y < lry; y++)
        for (int x = ulx; x < lrx; x++) fb.rgba[size_t(y) * fb.width + x] = c;
}

void Renderer::tex_rect(uint32_t w0, uint32_t w1, uint32_t st, uint32_t dsdt, bool flip) {
    float lrx = ((w0 >> 12) & 0xFFF) / 4.0f, lry = (w0 & 0xFFF) / 4.0f;
    int tile = (w1 >> 24) & 7;
    float ulx = ((w1 >> 12) & 0xFFF) / 4.0f, uly = (w1 & 0xFFF) / 4.0f;
    float s0 = int16_t(st >> 16) / 32.0f, t0 = int16_t(st & 0xFFFF) / 32.0f;
    float dsdx = int16_t(dsdt >> 16) / 1024.0f, dtdy = int16_t(dsdt & 0xFFFF) / 1024.0f;
    uint32_t cyc = (om_h_ >> CYCLE_SHIFT) & 3;
    if (cyc == CYC_COPY) { dsdx /= 4.0f; lrx += 1; lry += 1; }
    Framebuffer& fb = target();
    int x0 = std::max(int(ulx), sc_x0_), y0 = std::max({int(uly), sc_y0_, band_y0_});
    int x1 = std::min({int(std::ceil(lrx)), sc_x1_, fb.width});
    int y1 = std::min({int(std::ceil(lry)), sc_y1_, fb.height, band_y1_});
    int saved_tile = tex_tile_;
    tex_tile_ = tile;
    Color shade{0, 0, 0, 0};
    uint32_t saved_geom = geom_;
    geom_ &= ~G_ZBUFFER;
    for (int y = y0; y < y1; y++)
        for (int x = x0; x < x1; x++) {
            float dx = x - ulx, dy = y - uly;
            float s = flip ? s0 + dy * dsdx : s0 + dx * dsdx;
            float t = flip ? t0 + dx * dtdy : t0 + dy * dtdy;
            if (cyc == CYC_COPY) {
                Color c = texel(tile, s, t);
                if ((om_l_ & 3) == 1 && c.a < 1) continue;   // copy-mode alpha threshold
                if (c.a < 1 && (om_l_ & 3) != 0) continue;
                fb.rgba[size_t(y) * fb.width + x] = pack(c.r, c.g, c.b);
            } else {
                shade_pixel(x, y, 0, shade, s, t, 0, true);
            }
        }
    geom_ = saved_geom;
    tex_tile_ = saved_tile;
}

// ------------------------------------------------------------------ display list

Renderer::Renderer(uint8_t* rdram, int bands) : rdram_(rdram) {
    const int h = 240;
    for (int i = 0; i < bands; i++) {
        int y0 = i == 0 ? 0 : h * i / bands;
        int y1 = (i == bands - 1) ? (1 << 20) : h * (i + 1) / bands;
        bands_.push_back(std::unique_ptr<Renderer>(new Renderer(rdram, this, y0, y1)));
    }
    for (int i = 1; i < bands; i++) {
        workers_.emplace_back([this, i] {
            unsigned seen = 0;
            for (;;) {
                {
                    std::unique_lock<std::mutex> lk(mu_);
                    cv_start_.wait(lk, [&] { return quit_ || generation_ != seen; });
                    if (quit_) return;
                    seen = generation_;
                }
                bands_[i]->replay();
                std::lock_guard<std::mutex> lk(mu_);
                if (--pending_ == 0) cv_done_.notify_one();
            }
        });
    }
}

Renderer::Renderer(uint8_t* rdram, Renderer* shared, int y0, int y1)
    : rdram_(rdram), shared_(shared), band_y0_(y0), band_y1_(y1) {}

Renderer::~Renderer() {
    {
        std::lock_guard<std::mutex> lk(mu_);
        quit_ = true;
    }
    cv_start_.notify_all();
    for (auto& t : workers_) t.join();
}

void Renderer::replay() {
    shadow_alpha_ = 0;
    for (const Cmd& c : shared_->cmds_) exec(c);
    resolve_shadows();
}

void Renderer::resolve_shadows() {
    if (shadow_alpha_ <= 0) return;
    float keep = 1.0f - shadow_alpha_ / 255.0f;
    Renderer* owner = shared_ ? shared_ : this;
    for (auto& [addr, fb] : owner->fbs_) {
        if (fb.stencil.size() != fb.rgba.size()) continue;
        int y0 = std::max(band_y0_, 0), y1 = std::min(band_y1_, fb.height);
        for (int y = y0; y < y1; y++) {
            for (int x = 0; x < fb.width; x++) {
                size_t i = size_t(y) * fb.width + x;
                if (fb.stencil[i] == 0) continue;
                fb.stencil[i] = 0;
                float r, g, b;
                unpack(fb.rgba[i], r, g, b);
                fb.rgba[i] = pack(r * keep, g * keep, b * keep);
            }
        }
    }
}

void Renderer::exec(const Cmd& c) {
    uint32_t w0 = c.w0, w1 = c.w1;
    switch (c.op) {
        case 0x100: {                                        // recorded triangle
            const TriRec& t = shared_->tris_[c.tri];
            geom_ = t.geom; tex_on_ = t.tex_on; tex_tile_ = t.tex_tile;
            target();
            constexpr uint32_t IM_RD = 0x40;
            if (t.volume && (om_l_ & FORCE_BL) && (om_l_ & IM_RD) && !(om_l_ & (Z_CMP | Z_UPD))) {
                // The *_SHADOW_COLUMN / *_SHADOW models: translucent black drawn with
                // no depth test, which the hardware confines to the ground through
                // coverage bits. Emulated as a shadow volume: count faces in front
                // of the scene, darken non-zero pixels once the frame is drawn.
                shadow_alpha_ = std::max(shadow_alpha_, (t.v[0].a + t.v[1].a + t.v[2].a) / 3.0f);
                raster(t.v[0], t.v[1], t.v[2], t.area > 0 ? 1 : -1);
            } else {
                if (t.volume && (geom_ & G_CULL_BACK) && t.area > 0) break;
                if (t.volume && (geom_ & G_CULL_FRONT) && t.area < 0) break;
                raster(t.v[0], t.v[1], t.v[2]);
            }
            break;
        }
        case 0xB9: set_other_mode(0, (w0 >> 8) & 0xFF, w0 & 0xFF, w1); break;
        case 0xBA: set_other_mode(1, (w0 >> 8) & 0xFF, w0 & 0xFF, w1); break;
        case 0xE4: case 0xE5: tex_rect(w0, w1, c.a, c.b, c.op == 0xE5); break;
        case 0xED:
            sc_x0_ = ((w0 >> 12) & 0xFFF) >> 2; sc_y0_ = (w0 & 0xFFF) >> 2;
            sc_x1_ = ((w1 >> 12) & 0xFFF) >> 2; sc_y1_ = (w1 & 0xFFF) >> 2;
            break;
        case 0xEF: om_h_ = (om_h_ & 0xFF000000u) | (w0 & 0x00FFFFFF); om_l_ = w1; break;
        case 0xF0: load_tlut(w0, w1); break;
        case 0xF2: {
            Tile& tl = tiles_[(w1 >> 24) & 7];
            tl.uls = (w0 >> 12) & 0xFFF; tl.ult = w0 & 0xFFF; tl.lrs = (w1 >> 12) & 0xFFF; tl.lrt = w1 & 0xFFF;
            break;
        }
        case 0xF3: load_block(w0, w1); break;
        case 0xF4: load_tile(w0, w1); break;
        case 0xF5: {
            Tile& tl = tiles_[(w1 >> 24) & 7];
            tl.fmt = (w0 >> 21) & 7; tl.siz = (w0 >> 19) & 3; tl.line = (w0 >> 9) & 0x1FF; tl.tmem = w0 & 0x1FF;
            tl.palette = (w1 >> 20) & 0xF; tl.cmt = (w1 >> 18) & 3; tl.maskt = (w1 >> 14) & 0xF;
            tl.shiftt = (w1 >> 10) & 0xF; tl.cms = (w1 >> 8) & 3; tl.masks = (w1 >> 4) & 0xF; tl.shifts = w1 & 0xF;
            break;
        }
        case 0xF6: fill_rect(w0, w1); break;
        case 0xF7: fill_color_ = w1; break;
        case 0xF8: fog_ = {float(w1 >> 24), float((w1 >> 16) & 0xFF), float((w1 >> 8) & 0xFF), float(w1 & 0xFF)}; break;
        case 0xF9: blend_ = {float(w1 >> 24), float((w1 >> 16) & 0xFF), float((w1 >> 8) & 0xFF), float(w1 & 0xFF)}; break;
        case 0xFA:
            prim_ = {float(w1 >> 24), float((w1 >> 16) & 0xFF), float((w1 >> 8) & 0xFF), float(w1 & 0xFF)};
            prim_lod_ = float(w0 & 0xFF) / 255.0f;
            break;
        case 0xFB: env_ = {float(w1 >> 24), float((w1 >> 16) & 0xFF), float((w1 >> 8) & 0xFF), float(w1 & 0xFF)}; break;
        case 0xFC: combine_hi_ = w0 & 0x00FFFFFF; combine_lo_ = w1; decode_combiner(); break;
        case 0xFD:                                           // address already resolved by the front
            timg_fmt_ = (w0 >> 21) & 7; timg_siz_ = (w0 >> 19) & 3; timg_width_ = (w0 & 0xFFF) + 1;
            timg_addr_ = w1;
            break;
        case 0xFE: zimg_addr_ = w1; break;
        case 0xFF: cimg_addr_ = w1; cimg_width_ = (w0 & 0xFFF) + 1; break;
        default: break;
    }
}

void Renderer::run(uint32_t dl_addr) {
    cmds_.clear();
    tris_.clear();
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) proj_[i][j] = mv_[0][i][j] = (i == j) ? 1.f : 0.f;
    mv_top_ = 0;
    update_mvp();
    uint32_t stack[32];
    int sp = 0;
    uint32_t pc = dl_addr & 0x7FFFFF;
    int guard = 0;
    bool done = false;
    while (!done && guard++ < 400000) {
        uint32_t w0 = rd32(pc), w1 = rd32(pc + 4);
        pc += 8;
        uint32_t op = w0 >> 24;
        switch (op) {
            case 0x01: cmd_mtx(w0, w1); break;
            case 0x03: cmd_movemem(w0, w1); break;
            case 0x04: cmd_vtx(w0, w1); break;
            case 0x06:                                           // G_DL
                if (((w0 >> 16) & 0xFF) == 0 && sp < 32) stack[sp++] = pc;
                pc = seg(w1);
                break;
            case 0xB8:                                           // G_ENDDL
                if (sp == 0) done = true;
                else pc = stack[--sp];
                break;
            case 0xB6: geom_ &= ~w1; break;
            case 0xB7: geom_ |= w1; break;
            case 0xBB:                                           // G_TEXTURE
                tex_tile_ = (w0 >> 8) & 7;
                tex_on_ = w0 & 0xFF;
                tex_scale_s_ = float(w1 >> 16) / 65536.0f;
                tex_scale_t_ = float(w1 & 0xFFFF) / 65536.0f;
                if (tex_scale_s_ == 0) tex_scale_s_ = 1.0f / 65536.0f;
                if (tex_scale_t_ == 0) tex_scale_t_ = 1.0f / 65536.0f;
                break;
            case 0xBC: cmd_moveword(w0, w1); break;
            case 0xBD: if (mv_top_ > 0) { mv_top_--; update_mvp(); } break;
            case 0xBF: triangle(((w1 >> 16) & 0xFF) / 10, ((w1 >> 8) & 0xFF) / 10, (w1 & 0xFF) / 10); break;
            case 0xE4: case 0xE5: {                              // TEXRECT + RDPHALF_1/2
                uint32_t h1 = rd32(pc + 4), h2 = rd32(pc + 12);
                if ((rd32(pc) >> 24) == 0xB4 && (rd32(pc + 8) >> 24) == 0xB3) pc += 16;
                cmds_.push_back({op, w0, w1, h1, h2, -1});
                break;
            }
            case 0xFD: cmds_.push_back({op, w0, seg(w1), 0, 0, -1}); break;
            case 0xFE:
                zimg_addr_ = seg(w1);
                ensure_buffers();
                cmds_.push_back({op, w0, zimg_addr_, 0, 0, -1});
                break;
            case 0xFF:
                cimg_addr_ = seg(w1); cimg_width_ = (w0 & 0xFFF) + 1;
                ensure_buffers();
                cmds_.push_back({op, w0, cimg_addr_, 0, 0, -1});
                break;
            case 0xB9: case 0xBA: case 0xED: case 0xEF: case 0xF0: case 0xF2: case 0xF3: case 0xF4:
            case 0xF5: case 0xF6: case 0xF7: case 0xF8: case 0xF9: case 0xFA: case 0xFB: case 0xFC:
                cmds_.push_back({op, w0, w1, 0, 0, -1});
                break;
            default: break;                                      // syncs, noop, cull (not culled)
        }
    }
    // Replay in parallel: band 0 on this thread, the others on the workers.
    {
        std::lock_guard<std::mutex> lk(mu_);
        pending_ = int(bands_.size()) - 1;
        generation_++;
    }
    cv_start_.notify_all();
    bands_[0]->replay();
    std::unique_lock<std::mutex> lk(mu_);
    cv_done_.wait(lk, [&] { return pending_ == 0; });
}

}  // namespace webrdp
