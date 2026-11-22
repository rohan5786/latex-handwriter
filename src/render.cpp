// render.cpp -- items.tsv + samples/ -> handwritten page PNGs.
//
//   build/render items.tsv samples_dir out_prefix [--scale 4] [--seed 1] [--xscale 1.0]
//
// Writes out_prefix-1.png, out_prefix-2.png, ...   (--scale = pixels per PDF point)
//
// Per glyph record:
//   * key has samples -> pick one at random, scale by font size, anchor on the
//     baseline, add small random rotation/scale/offset
//   * stretch == 1    -> stretch the sample to the measured ink box instead
//   * no samples      -> black box (so missing symbols are impossible to miss)
// Per line record: a slightly wobbly pen stroke.
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <random>
#include <sstream>
#include <string>
#include <vector>

static const double PI = 3.14159265358979323846;
static const float INK[3] = {20, 22, 48};        // blue-black pen
static const float PEN_OPACITY = 0.93f;

// ---------------------------------------------------------------- data ----
struct Sample {                                  // one handwritten glyph image
    int w = 0, h = 0;
    std::vector<float> a;                        // alpha 0..1, row-major
    double baseline = 0, em = 1;                 // px from crop top; reference em in px
};
using Library = std::map<std::string, std::vector<Sample>>;

struct Glyph { std::string key; double x, y, size, adv; bool stretch; double ix0, iy0, ix1, iy1; std::string anchor; };
static double XSCALE = 1.0;                       // --xscale: widen/narrow ordinary glyphs
struct Line  { double x0, y0, x1, y1, t; };
struct Page  { int n = 0; double w = 0, h = 0; std::vector<Glyph> glyphs; std::vector<Line> lines; };

struct Canvas {
    int w, h;
    std::vector<float> d;                        // ink density 0..1
    Canvas(int w_, int h_) : w(w_), h(h_), d((size_t)w_ * h_, 0.f) {}
};

static std::vector<std::string> split_tabs(const std::string& s) {
    std::vector<std::string> out; std::string cur;
    for (char c : s) { if (c == '\t') { out.push_back(cur); cur.clear(); } else if (c != '\r') cur += c; }
    out.push_back(cur);
    return out;
}

static Library load_library(const std::string& dir) {
    Library lib;
    std::ifstream f(dir + "/index.tsv");
    if (!f) { fprintf(stderr, "cannot open %s/index.tsv (run tools/index_samples.py)\n", dir.c_str()); exit(1); }
    std::string line;
    while (std::getline(f, line)) {
        auto c = split_tabs(line);                // key file w h baseline cap em
        if (c.size() < 7) continue;
        int w, h, n;
        unsigned char* px = stbi_load((dir + "/" + c[0] + "/" + c[1]).c_str(), &w, &h, &n, 4);
        if (!px) { fprintf(stderr, "warn: cannot load %s/%s\n", c[0].c_str(), c[1].c_str()); continue; }
        Sample s; s.w = w; s.h = h; s.a.resize((size_t)w * h);
        for (size_t i = 0; i < s.a.size(); i++) s.a[i] = px[4 * i + 3] / 255.f;
        stbi_image_free(px);
        s.baseline = atof(c[4].c_str()); s.em = std::max(1.0, atof(c[6].c_str()));
        lib[c[0]].push_back(std::move(s));
    }
    return lib;
}

static std::vector<Page> load_items(const std::string& path) {
    std::vector<Page> pages;
    std::ifstream f(path);
    if (!f) { fprintf(stderr, "cannot open %s\n", path.c_str()); exit(1); }
    std::string line;
    while (std::getline(f, line)) {
        auto c = split_tabs(line);
        if (c[0] == "PAGE" && c.size() >= 4) {
            pages.emplace_back(); pages.back().n = atoi(c[1].c_str());
            pages.back().w = atof(c[2].c_str()); pages.back().h = atof(c[3].c_str());
        } else if (c[0] == "G" && c.size() >= 11 && !pages.empty()) {
            Glyph g{c[1], atof(c[2].c_str()), atof(c[3].c_str()), atof(c[4].c_str()), atof(c[5].c_str()),
                    c[6] == "1", 0, 0, 0, 0, c.size() > 11 ? c[11] : std::string("center")};
            if (g.stretch) { g.ix0 = atof(c[7].c_str()); g.iy0 = atof(c[8].c_str());
                             g.ix1 = atof(c[9].c_str()); g.iy1 = atof(c[10].c_str()); }
            pages.back().glyphs.push_back(g);
        } else if (c[0] == "L" && c.size() >= 6 && !pages.empty()) {
            pages.back().lines.push_back({atof(c[1].c_str()), atof(c[2].c_str()), atof(c[3].c_str()),
                                          atof(c[4].c_str()), atof(c[5].c_str())});
        }
    }
    return pages;
}

// ------------------------------------------------------------- drawing ----
static float tap(const Sample& s, int x, int y) {          // alpha, 0 outside
    return (x < 0 || y < 0 || x >= s.w || y >= s.h) ? 0.f : s.a[(size_t)y * s.w + x];
}
static float bilinear(const Sample& s, double x, double y) {
    int x0 = (int)std::floor(x), y0 = (int)std::floor(y);
    float fx = (float)(x - x0), fy = (float)(y - y0);
    return (1 - fy) * ((1 - fx) * tap(s, x0, y0) + fx * tap(s, x0 + 1, y0)) +
           fy * ((1 - fx) * tap(s, x0, y0 + 1) + fx * tap(s, x0 + 1, y0 + 1));
}

// Draw sample so its point (ax, ay) lands on canvas (dx, dy); scaled (sx, sy), rotated by rot.
static void stamp(Canvas& c, const Sample& s, double ax, double ay, double dx, double dy,
                  double sx, double sy, double rot) {
    double cs = std::cos(rot), sn = std::sin(rot);
    double minx = 1e18, miny = 1e18, maxx = -1e18, maxy = -1e18;
    for (int i = 0; i < 4; i++) {                              // bounding box of the transformed image
        double u = ((i & 1) ? s.w : 0) - ax, v = ((i & 2) ? s.h : 0) - ay;
        u *= sx; v *= sy;
        double qx = dx + cs * u - sn * v, qy = dy + sn * u + cs * v;
        minx = std::min(minx, qx); maxx = std::max(maxx, qx); miny = std::min(miny, qy); maxy = std::max(maxy, qy);
    }
    int x0 = std::max(0, (int)std::floor(minx) - 1), x1 = std::min(c.w - 1, (int)std::ceil(maxx) + 1);
    int y0 = std::max(0, (int)std::floor(miny) - 1), y1 = std::min(c.h - 1, (int)std::ceil(maxy) + 1);
    int k = std::clamp((int)std::ceil(1.0 / std::min(sx, sy)), 1, 6);   // supersample when shrinking
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++) {
            float acc = 0;
            for (int j = 0; j < k; j++)
                for (int i = 0; i < k; i++) {
                    double X = x + (i + 0.5) / k - dx, Y = y + (j + 0.5) / k - dy;       // inverse transform
                    double px = ax + (cs * X + sn * Y) / sx, py = ay + (-sn * X + cs * Y) / sy;
                    acc += bilinear(s, px - 0.5, py - 0.5);
                }
            float a = acc / (k * k) * PEN_OPACITY;
            if (a > 0) { float& d = c.d[(size_t)y * c.w + x]; d = 1 - (1 - d) * (1 - a); }  // overlapping ink darkens
        }
}

static void fill_rect(Canvas& c, double x0, double y0, double x1, double y1) {
    for (int y = std::max(0, (int)y0); y <= std::min(c.h - 1, (int)y1); y++)
        for (int x = std::max(0, (int)x0); x <= std::min(c.w - 1, (int)x1); x++) c.d[(size_t)y * c.w + x] = 1.f;
}

static void disc(Canvas& c, double cx, double cy, double r) {
    for (int y = std::max(0, (int)(cy - r - 1)); y <= std::min(c.h - 1, (int)(cy + r + 1)); y++)
        for (int x = std::max(0, (int)(cx - r - 1)); x <= std::min(c.w - 1, (int)(cx + r + 1)); x++) {
            double dist = std::hypot(x + 0.5 - cx, y + 0.5 - cy);
            float a = (float)std::clamp(r + 0.5 - dist, 0.0, 1.0) * PEN_OPACITY;
            float& d = c.d[(size_t)y * c.w + x]; d = std::max(d, a);
        }
}

static void wobbly_line(Canvas& c, const Line& l, double S, std::mt19937& rng) {
    std::uniform_real_distribution<double> U(0, 1);
    double x0 = l.x0 * S, y0 = l.y0 * S, x1 = l.x1 * S, y1 = l.y1 * S;
    double len = std::hypot(x1 - x0, y1 - y0);
    if (len < 1) return;
    double ux = (x1 - x0) / len, uy = (y1 - y0) / len, nx = -uy, ny = ux;
    double over = 0.5 * S * U(rng);                               // pens overshoot a little
    x0 -= ux * over; y0 -= uy * over; x1 += ux * over; y1 += uy * over; len += 2 * over;
    double r = std::max(0.9, l.t * S * 1.2), amp = std::min(1.5, 0.4 + 0.004 * len);
    double p1 = 2 * PI * U(rng), p2 = 2 * PI * U(rng);
    int n = (int)len + 2;
    for (int i = 0; i < n; i++) {
        double t = (double)i / (n - 1);
        double off = amp * (0.7 * std::sin(2 * PI * 1.1 * t + p1) + 0.3 * std::sin(2 * PI * 2.7 * t + p2));
        disc(c, x0 + (x1 - x0) * t + nx * off, y0 + (y1 - y0) * t + ny * off, r);
    }
}

static void draw_glyph(Canvas& c, const Glyph& g, const Library& lib, double S, std::mt19937& rng,
                       std::map<std::string, int>& missing) {
    std::uniform_real_distribution<double> U(-1, 1);
    auto it = lib.find(g.key);
    if (it == lib.end() || it->second.empty()) {                  // fallback: black box
        missing[g.key]++;
        double w = g.adv > 0 ? g.adv : 0.5 * g.size;
        if (g.stretch) fill_rect(c, g.ix0 * S, g.iy0 * S, g.ix1 * S, g.iy1 * S);
        else fill_rect(c, g.x * S, (g.y - 0.7 * g.size) * S, (g.x + w) * S, (g.y + 0.2 * g.size) * S);
        return;
    }
    const Sample& s = it->second[(size_t)(rng() % it->second.size())];
    double rot = U(rng) * 1.5 * PI / 180, jit = 1 + 0.04 * U(rng);
    if (g.stretch) {                                              // fit sample to measured ink box
        double W = (g.ix1 - g.ix0) * S, H = (g.iy1 - g.iy0) * S;
        double sy = H / s.h * jit;
        if (g.anchor == "topright") {                                         // radical: keep proportions, pin top-right end to the bar
            stamp(c, s, s.w, 0, g.ix1 * S, g.iy0 * S, sy, sy, rot);
            return;
        }
        double sx = std::clamp(W / s.w, 0.5 * sy, 2.0 * sy);
        stamp(c, s, s.w / 2.0, s.h / 2.0, (g.ix0 + g.ix1) / 2 * S, (g.iy0 + g.iy1) / 2 * S, sx, sy, rot);
    } else {                                                      // size by em, sit on the baseline
        double sc = g.size * S / s.em * jit;
        double adv = g.adv > 0 ? g.adv : 0.25 * g.size;           // zero-width accents: nudge right
        double cx = (g.x + adv / 2 + 0.03 * g.size * U(rng)) * S;
        double by = (g.y + 0.03 * g.size * U(rng)) * S;
        double sx = g.anchor == "fitw" ? 0.96 * adv * S / s.w * jit : sc * XSCALE;   // arrows: fit width to the glyph
        stamp(c, s, s.w / 2.0, s.baseline, cx, by, sx, sc, rot);
    }
}

static void write_png(const Canvas& c, const std::string& path) {
    std::vector<unsigned char> rgb((size_t)c.w * c.h * 3);
    for (size_t i = 0; i < c.d.size(); i++)
        for (int k = 0; k < 3; k++) rgb[3 * i + k] = (unsigned char)std::lround(255 * (1 - c.d[i]) + INK[k] * c.d[i]);
    if (!stbi_write_png(path.c_str(), c.w, c.h, 3, rgb.data(), c.w * 3)) fprintf(stderr, "failed to write %s\n", path.c_str());
}

int main(int argc, char** argv) {
    if (argc < 4) { fprintf(stderr, "usage: %s items.tsv samples_dir out_prefix [--scale 4] [--seed 1] [--xscale 1.0]\n", argv[0]); return 2; }
    double S = 4; unsigned seed = 1;
    for (int i = 4; i + 1 < argc; i += 2) {
        if (std::string(argv[i]) == "--scale") S = atof(argv[i + 1]);
        else if (std::string(argv[i]) == "--seed") seed = (unsigned)atoi(argv[i + 1]);
        else if (std::string(argv[i]) == "--xscale") XSCALE = atof(argv[i + 1]);
    }
    Library lib = load_library(argv[2]);
    std::vector<Page> pages = load_items(argv[1]);
    std::mt19937 rng(seed);
    std::map<std::string, int> missing;
    for (const Page& p : pages) {
        Canvas c((int)std::ceil(p.w * S), (int)std::ceil(p.h * S));
        for (const Line& l : p.lines) wobbly_line(c, l, S, rng);
        for (const Glyph& g : p.glyphs) draw_glyph(c, g, lib, S, rng, missing);
        std::string out = std::string(argv[3]) + "-" + std::to_string(p.n) + ".png";
        write_png(c, out);
        printf("wrote %s (%zu glyphs, %zu lines)\n", out.c_str(), p.glyphs.size(), p.lines.size());
    }
    if (!missing.empty()) {
        fprintf(stderr, "black boxes drawn (no samples):\n");
        for (auto& kv : missing) fprintf(stderr, "  %s x%d\n", kv.first.c_str(), kv.second);
    }
    return 0;
}
