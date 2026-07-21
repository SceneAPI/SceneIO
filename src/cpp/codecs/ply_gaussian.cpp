// 3D Gaussian Splatting PLY codec (formats_survey.md §4) + the GaussianCloud
// Record — the memory representation that backs the `splat` DataType.
//
// The PLY stores RAW (pre-activation) values: scales in log space, opacity
// in logit space, colour as SH coefficients. This codec is pure I/O — it
// applies no activations; the convention is recorded, not baked in. The
// reader maps vertex properties by NAME, so it accepts both the gsply order
// (x,y,z,f_dc,f_rest,opacity,scale,rot; no normals) and the INRIA order
// (…with nx,ny,nz, which are ignored).
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>

#include <optional>
#include <sstream>
#include <unordered_map>

#include "io/common.hpp"
#include "records/gaussian_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

std::vector<std::string> tokens(const std::string &s) {
    std::vector<std::string> t;
    std::istringstream is(s);
    std::string w;
    while (is >> w) t.push_back(w);
    return t;
}

float maybe_swap(float v, bool swap) {
    if (!swap) return v;
    uint32_t u;
    std::memcpy(&u, &v, 4);
    u = (u >> 24) | ((u >> 8) & 0x0000ff00u) | ((u << 8) & 0x00ff0000u) | (u << 24);
    std::memcpy(&v, &u, 4);
    return v;
}

GaussianCloud read_gaussian_ply(nb::bytes data) {
    const uint8_t *p = reinterpret_cast<const uint8_t *>(data.c_str());
    const size_t n = data.size();
    size_t hp = 0;
    auto readline = [&]() {
        std::string s;
        while (hp < n && p[hp] != '\n') {
            if (p[hp] != '\r') s.push_back(static_cast<char>(p[hp]));
            hp++;
        }
        if (hp < n) hp++;
        return s;
    };
    if (readline() != "ply") throw std::invalid_argument("PLY: missing 'ply' magic");

    bool le = true, is_ascii = false;
    std::string cur;
    size_t vcount = 0;
    std::vector<std::string> vprops;
    while (true) {
        if (hp >= n) throw std::invalid_argument("PLY: header has no end_header");
        std::string line = readline();
        if (line == "end_header") break;
        auto tk = tokens(line);
        if (tk.empty()) continue;
        if (tk[0] == "format") {
            if (tk[1] == "binary_little_endian") le = true;
            else if (tk[1] == "binary_big_endian") le = false;
            else if (tk[1] == "ascii") is_ascii = true;
        } else if (tk[0] == "element") {
            cur = tk[1];
            if (cur == "vertex") vcount = std::stoul(tk[2]);
        } else if (tk[0] == "property" && cur == "vertex") {
            if (tk[1] == "list")
                throw std::invalid_argument("PLY: list properties unsupported (not a Gaussian PLY)");
            if (tk[1] != "float" && tk[1] != "float32")
                throw std::invalid_argument("PLY: only float32 vertex properties are supported");
            vprops.push_back(tk.back());
        }
    }
    if (is_ascii) throw std::invalid_argument("PLY: ASCII bodies are not supported (binary Gaussian PLY expected)");

    const size_t P = vprops.size();
    std::unordered_map<std::string, size_t> col;
    for (size_t i = 0; i < P; i++) col[vprops[i]] = i;
    auto need = [&](const std::string &nm) -> size_t {
        auto it = col.find(nm);
        if (it == col.end()) throw std::invalid_argument("PLY: missing Gaussian property '" + nm + "'");
        return it->second;
    };
    size_t R = 0;
    while (col.count("f_rest_" + std::to_string(R))) R++;
    int deg = gc_deg_from_rest(R);
    if (deg < 0) throw std::invalid_argument("PLY: unexpected f_rest count " + std::to_string(R));

    if (hp + static_cast<size_t>(vcount) * P * 4 > n)
        throw std::invalid_argument("PLY: truncated vertex data");
    const float *body = reinterpret_cast<const float *>(p + hp);
    const bool swap = (le != host_is_le());

    GaussianCloud g;
    g.n = vcount;
    g.num_rest = R;
    g.sh_degree = deg;
    g.means.resize(vcount * 3);
    g.sh_dc.resize(vcount * 3);
    g.sh_rest.resize(vcount * R);
    g.opacity.resize(vcount);
    g.scales.resize(vcount * 3);
    g.quats.resize(vcount * 4);

    const size_t cx = need("x"), cy = need("y"), cz = need("z");
    const size_t d0 = need("f_dc_0"), d1 = need("f_dc_1"), d2 = need("f_dc_2");
    const size_t co = need("opacity");
    const size_t s0 = need("scale_0"), s1 = need("scale_1"), s2 = need("scale_2");
    const size_t r0 = need("rot_0"), r1 = need("rot_1"), r2 = need("rot_2"), r3 = need("rot_3");
    std::vector<size_t> cr(R);
    for (size_t i = 0; i < R; i++) cr[i] = need("f_rest_" + std::to_string(i));
    auto v = [&](size_t row, size_t c) { return maybe_swap(body[row * P + c], swap); };
    for (size_t i = 0; i < vcount; i++) {
        g.means[i * 3] = v(i, cx); g.means[i * 3 + 1] = v(i, cy); g.means[i * 3 + 2] = v(i, cz);
        g.sh_dc[i * 3] = v(i, d0); g.sh_dc[i * 3 + 1] = v(i, d1); g.sh_dc[i * 3 + 2] = v(i, d2);
        for (size_t k = 0; k < R; k++) g.sh_rest[i * R + k] = v(i, cr[k]);
        g.opacity[i] = v(i, co);
        g.scales[i * 3] = v(i, s0); g.scales[i * 3 + 1] = v(i, s1); g.scales[i * 3 + 2] = v(i, s2);
        g.quats[i * 4] = v(i, r0); g.quats[i * 4 + 1] = v(i, r1);
        g.quats[i * 4 + 2] = v(i, r2); g.quats[i * 4 + 3] = v(i, r3);
    }
    return g;
}

nb::bytes write_gaussian_ply(const GaussianCloud &g) {
    std::string h = "ply\nformat binary_little_endian 1.0\nelement vertex " + std::to_string(g.n) + "\n";
    h += "property float x\nproperty float y\nproperty float z\n";
    h += "property float f_dc_0\nproperty float f_dc_1\nproperty float f_dc_2\n";
    for (size_t i = 0; i < g.num_rest; i++) h += "property float f_rest_" + std::to_string(i) + "\n";
    h += "property float opacity\n";
    h += "property float scale_0\nproperty float scale_1\nproperty float scale_2\n";
    h += "property float rot_0\nproperty float rot_1\nproperty float rot_2\nproperty float rot_3\n";
    h += "end_header\n";
    const size_t P = 3 + 3 + g.num_rest + 1 + 3 + 4;
    std::string out = h;
    out.reserve(h.size() + g.n * P * 4);
    std::vector<float> row(P);
    for (size_t i = 0; i < g.n; i++) {
        size_t j = 0;
        row[j++] = g.means[i * 3]; row[j++] = g.means[i * 3 + 1]; row[j++] = g.means[i * 3 + 2];
        row[j++] = g.sh_dc[i * 3]; row[j++] = g.sh_dc[i * 3 + 1]; row[j++] = g.sh_dc[i * 3 + 2];
        for (size_t k = 0; k < g.num_rest; k++) row[j++] = g.sh_rest[i * g.num_rest + k];
        row[j++] = g.opacity[i];
        row[j++] = g.scales[i * 3]; row[j++] = g.scales[i * 3 + 1]; row[j++] = g.scales[i * 3 + 2];
        row[j++] = g.quats[i * 4]; row[j++] = g.quats[i * 4 + 1];
        row[j++] = g.quats[i * 4 + 2]; row[j++] = g.quats[i * 4 + 3];
        out.append(reinterpret_cast<const char *>(row.data()), P * 4);  // little-endian (host LE)
    }
    return nb::bytes(out.data(), out.size());
}

using arr = nb::ndarray<const float, nb::c_contig, nb::device::cpu>;
GaussianCloud make_gc(arr means, arr scales, arr quats, arr opacities, arr sh_dc,
                      std::optional<arr> sh_rest) {
    size_t nn = means.shape(0);
    auto chk = [&](const arr &a, size_t d1, const char *nm) {
        if (a.shape(0) != nn || (d1 && (a.ndim() < 2 || a.shape(1) != d1)))
            throw std::invalid_argument(std::string("gaussian_cloud: bad shape for ") + nm);
    };
    chk(means, 3, "means"); chk(scales, 3, "scales"); chk(quats, 4, "quats");
    chk(opacities, 0, "opacities"); chk(sh_dc, 3, "sh_dc");
    GaussianCloud g;
    g.n = nn;
    g.means.assign(means.data(), means.data() + nn * 3);
    g.scales.assign(scales.data(), scales.data() + nn * 3);
    g.quats.assign(quats.data(), quats.data() + nn * 4);
    g.opacity.assign(opacities.data(), opacities.data() + nn);
    g.sh_dc.assign(sh_dc.data(), sh_dc.data() + nn * 3);
    if (sh_rest) {
        size_t R = sh_rest->ndim() >= 2 ? sh_rest->shape(1) : 0;
        if (sh_rest->shape(0) != nn || gc_deg_from_rest(R) < 0)
            throw std::invalid_argument("gaussian_cloud: bad sh_rest shape (n, {0,9,24,45})");
        g.num_rest = R;
        g.sh_degree = gc_deg_from_rest(R);
        g.sh_rest.assign(sh_rest->data(), sh_rest->data() + nn * R);
    }
    return g;
}

}  // namespace

void register_ply_gaussian(nb::module_ &m) {
    m.def("read_gaussian_ply", &read_gaussian_ply, "data"_a,
          "Decode a 3DGS Gaussian .ply (binary) into a GaussianCloud (raw/pre-activation values).");
    m.def("write_gaussian_ply", &write_gaussian_ply, "cloud"_a,
          "Encode a GaussianCloud to 3DGS Gaussian .ply bytes (binary little-endian).");
    m.def("gaussian_cloud", &make_gc, "means"_a, "scales"_a, "quaternions"_a, "opacities"_a,
          "sh_dc"_a, "sh_rest"_a = nb::none(),
          "Build a GaussianCloud from arrays (numpy/torch): means (N,3), scales (N,3), "
          "quaternions (N,4), opacities (N,), sh_dc (N,3), sh_rest (N,{0,9,24,45}).");
}
