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

#include <algorithm>
#include <cmath>
#include <limits>
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

GaussianCloud read_gaussian_ply_impl(nb::handle source, bool partial,
                                     size_t start, size_t stop) {
    sio::ByteView data(source);
    const uint8_t *p = data.data();
    const size_t n = data.size();
    size_t hp = 0;
    auto readline = [&]() {
        std::string s;
        while (hp < n && p[hp] != '\n') {
            if (p[hp] != '\r') s.push_back(static_cast<char>(p[hp]));
            if (s.size() > 4096)
                throw std::invalid_argument(
                    "PLY: header line exceeds 4096 bytes");
            hp++;
        }
        if (hp < n) hp++;
        return s;
    };
    if (readline() != "ply") throw std::invalid_argument("PLY: missing 'ply' magic");

    bool le = true, is_ascii = false, saw_format = false;
    std::string cur;
    size_t vcount = 0;
    bool saw_vertex = false;
    std::vector<std::string> vprops;
    while (true) {
        if (hp >= n) throw std::invalid_argument("PLY: header has no end_header");
        std::string line = readline();
        if (line == "end_header") break;
        auto tk = tokens(line);
        if (tk.empty()) continue;
        if (tk[0] == "format") {
            if (tk.size() != 3)
                throw std::invalid_argument("PLY: malformed format header");
            if (saw_format)
                throw std::invalid_argument("PLY: duplicate format header");
            if (tk[2] != "1.0")
                throw std::invalid_argument("PLY: unsupported format version");
            saw_format = true;
            if (tk[1] == "binary_little_endian") le = true;
            else if (tk[1] == "binary_big_endian") le = false;
            else if (tk[1] == "ascii") is_ascii = true;
            else throw std::invalid_argument("PLY: unsupported format");
        } else if (tk[0] == "element") {
            if (tk.size() != 3)
                throw std::invalid_argument("PLY: malformed element header");
            cur = tk[1];
            if (cur == "vertex") {
                if (saw_vertex)
                    throw std::invalid_argument(
                        "PLY: duplicate vertex element");
                saw_vertex = true;
                try {
                    if (tk[2].empty() ||
                        !std::all_of(tk[2].begin(), tk[2].end(),
                                     [](unsigned char c) { return c >= '0' && c <= '9'; }))
                        throw std::invalid_argument("vertex count");
                    size_t consumed = 0;
                    const unsigned long long count = std::stoull(tk[2], &consumed);
                    if (consumed != tk[2].size())
                        throw std::invalid_argument("vertex count");
                    if (count > std::numeric_limits<size_t>::max())
                        throw std::out_of_range("vertex count");
                    vcount = static_cast<size_t>(count);
                } catch (const std::exception &) {
                    throw std::invalid_argument("PLY: malformed vertex count");
                }
            } else {
                unsigned long long count = 0;
                try {
                    if (tk[2].empty() ||
                        !std::all_of(
                            tk[2].begin(), tk[2].end(),
                            [](unsigned char c) {
                                return c >= '0' && c <= '9';
                            }))
                        throw std::invalid_argument("element count");
                    size_t consumed = 0;
                    count = std::stoull(tk[2], &consumed);
                    if (consumed != tk[2].size())
                        throw std::invalid_argument("element count");
                } catch (const std::invalid_argument &) {
                    throw std::invalid_argument(
                        "PLY: malformed non-vertex element count");
                } catch (const std::out_of_range &) {
                    throw std::invalid_argument(
                        "PLY: malformed non-vertex element count");
                }
                if (count != 0)
                    throw std::invalid_argument(
                        "PLY: nonzero non-vertex elements are unsupported by "
                        "the Gaussian PLY codec");
            }
        } else if (tk[0] == "property" && cur == "vertex") {
            if (tk.size() < 2)
                throw std::invalid_argument("PLY: malformed property header");
            if (tk[1] == "list")
                throw std::invalid_argument("PLY: list properties unsupported (not a Gaussian PLY)");
            if (tk.size() != 3)
                throw std::invalid_argument("PLY: malformed property header");
            if (tk[1] != "float" && tk[1] != "float32")
                throw std::invalid_argument("PLY: only float32 vertex properties are supported");
            if (std::find(vprops.begin(), vprops.end(), tk.back()) !=
                vprops.end())
                throw std::invalid_argument(
                    "PLY: duplicate vertex property '" + tk.back() + "'");
            vprops.push_back(tk.back());
        }
    }
    if (!saw_format) throw std::invalid_argument("PLY: missing format header");
    if (!saw_vertex) throw std::invalid_argument("PLY: missing vertex element");
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
    for (const std::string &name : vprops) {
        if (name.rfind("f_rest_", 0) != 0) continue;
        const std::string suffix = name.substr(7);
        if (suffix.empty() ||
            !std::all_of(suffix.begin(), suffix.end(), [](unsigned char c) {
                return c >= '0' && c <= '9';
            }))
            throw std::invalid_argument(
                "PLY: malformed Gaussian property '" + name + "'");
        size_t consumed = 0;
        unsigned long long index = 0;
        try {
            index = std::stoull(suffix, &consumed);
        } catch (const std::exception &) {
            throw std::invalid_argument(
                "PLY: malformed Gaussian property '" + name + "'");
        }
        if (consumed != suffix.size() || index >= R)
            throw std::invalid_argument(
                "PLY: f_rest properties must be consecutive from zero");
    }
    int deg = gc_deg_from_rest(R);
    if (deg < 0) throw std::invalid_argument("PLY: unexpected f_rest count " + std::to_string(R));

    const size_t cx = need("x"), cy = need("y"), cz = need("z");
    const size_t d0 = need("f_dc_0"), d1 = need("f_dc_1"), d2 = need("f_dc_2");
    const size_t co = need("opacity");
    const size_t s0 = need("scale_0"), s1 = need("scale_1"), s2 = need("scale_2");
    const size_t r0 = need("rot_0"), r1 = need("rot_1"), r2 = need("rot_2"), r3 = need("rot_3");
    std::vector<size_t> cr(R);
    for (size_t i = 0; i < R; i++) cr[i] = need("f_rest_" + std::to_string(i));

    if (P > std::numeric_limits<size_t>::max() / sizeof(float))
        throw std::invalid_argument("PLY: vertex stride overflows address space");
    const size_t stride = P * sizeof(float);
    if (stride == 0 || vcount > (n - hp) / stride)
        throw std::invalid_argument("PLY: truncated vertex data");
    const size_t body_size = vcount * stride;
    if (n - hp != body_size)
        throw std::invalid_argument("PLY: trailing bytes after vertex data");
    const bool swap = (le != host_is_le());
    if (!partial) {
        start = 0;
        stop = vcount;
    } else {
        checked_half_open_range(start, stop, vcount,
                                "PLY Gaussian point range");
    }
    const size_t selected = stop - start;

    GaussianCloud g;
    g.n = selected;
    g.num_rest = R;
    g.sh_degree = deg;
    g.means.resize(selected * 3);
    g.sh_dc.resize(selected * 3);
    g.sh_rest.resize(selected * R);
    g.opacity.resize(selected);
    g.scales.resize(selected * 3);
    g.quats.resize(selected * 4);

    auto v = [&](size_t row, size_t c) {
        float value;
        std::memcpy(&value, p + hp + row * stride + c * sizeof(float), sizeof(value));
        return maybe_swap(value, swap);
    };
    for (size_t i = 0; i < selected; i++) {
        const size_t row = start + i;
        g.means[i * 3] = v(row, cx); g.means[i * 3 + 1] = v(row, cy); g.means[i * 3 + 2] = v(row, cz);
        g.sh_dc[i * 3] = v(row, d0); g.sh_dc[i * 3 + 1] = v(row, d1); g.sh_dc[i * 3 + 2] = v(row, d2);
        for (size_t k = 0; k < R; k++) g.sh_rest[i * R + k] = v(row, cr[k]);
        g.opacity[i] = v(row, co);
        g.scales[i * 3] = v(row, s0); g.scales[i * 3 + 1] = v(row, s1); g.scales[i * 3 + 2] = v(row, s2);
        g.quats[i * 4] = v(row, r0); g.quats[i * 4 + 1] = v(row, r1);
        g.quats[i * 4 + 2] = v(row, r2); g.quats[i * 4 + 3] = v(row, r3);
    }
    return g;
}

GaussianCloud read_gaussian_ply(nb::handle source) {
    return read_gaussian_ply_impl(source, false, 0, 0);
}

GaussianCloud read_gaussian_ply_points(nb::handle source, size_t start,
                                       size_t stop) {
    return read_gaussian_ply_impl(source, true, start, stop);
}

nb::bytes write_gaussian_ply(const GaussianCloud &g) {
    require_legacy_gaussian_conventions(g, "gaussian PLY writer");
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
    return emit_bytes(out.data(), out.size());
}

using arr = nb::ndarray<const float, nb::c_contig, nb::device::cpu>;
GaussianCloud make_gc(arr means, arr scales, arr quats, arr opacities, arr sh_dc,
                       std::optional<arr> sh_rest,
                       std::string quaternion_order,
                       std::string scale_space,
                       std::string opacity_space,
                       std::string sh_layout,
                       std::string source_precision,
                       std::string projection_mode_hint,
                       std::string sorting_mode_hint,
                       std::string quaternion_norm,
                       std::string sh_basis,
                       std::string sh_phase,
                       std::string sh_coefficient_order,
                       std::string color_space,
                       std::string coordinate_frame,
                       std::optional<double> scale_to_meters,
                       std::string scale_to_meters_source) {
    if (means.ndim() != 2 || means.shape(1) != 3)
        throw std::invalid_argument(
            "gaussian_cloud: bad shape for means (expected (n, 3))");
    size_t nn = means.shape(0);
    auto chk_matrix = [&](const arr &a, size_t width, const char *name) {
        if (a.ndim() != 2 || a.shape(0) != nn || a.shape(1) != width)
            throw std::invalid_argument(
                std::string("gaussian_cloud: bad shape for ") + name);
    };
    chk_matrix(scales, 3, "scales");
    chk_matrix(quats, 4, "quats");
    chk_matrix(sh_dc, 3, "sh_dc");
    if (opacities.ndim() != 1 || opacities.shape(0) != nn)
        throw std::invalid_argument(
            "gaussian_cloud: bad shape for opacities (expected (n,))");
    GaussianCloud g;
    g.n = nn;
    g.means.assign(means.data(), means.data() + nn * 3);
    g.scales.assign(scales.data(), scales.data() + nn * 3);
    g.quats.assign(quats.data(), quats.data() + nn * 4);
    g.opacity.assign(opacities.data(), opacities.data() + nn);
    g.sh_dc.assign(sh_dc.data(), sh_dc.data() + nn * 3);
    g.quaternion_order = std::move(quaternion_order);
    g.scale_space = std::move(scale_space);
    g.opacity_space = std::move(opacity_space);
    g.sh_layout = std::move(sh_layout);
    g.source_precision = std::move(source_precision);
    g.projection_mode_hint = std::move(projection_mode_hint);
    g.sorting_mode_hint = std::move(sorting_mode_hint);
    g.quaternion_norm = std::move(quaternion_norm);
    g.sh_basis = std::move(sh_basis);
    g.sh_phase = std::move(sh_phase);
    g.sh_coefficient_order = std::move(sh_coefficient_order);
    g.color_space = std::move(color_space);
    g.coordinate_frame = std::move(coordinate_frame);
    g.scale_to_meters = scale_to_meters;
    g.scale_to_meters_source = std::move(scale_to_meters_source);
    validate_gaussian_conventions(g, "gaussian_cloud");
    if (sh_rest) {
        if (sh_rest->ndim() != 2 || sh_rest->shape(0) != nn)
            throw std::invalid_argument("gaussian_cloud: bad sh_rest shape (n, {0,9,24,45})");
        size_t R = sh_rest->shape(1);
        if (gc_deg_from_rest(R) < 0)
            throw std::invalid_argument("gaussian_cloud: bad sh_rest shape (n, {0,9,24,45})");
        g.num_rest = R;
        g.sh_degree = gc_deg_from_rest(R);
        g.sh_rest.assign(sh_rest->data(), sh_rest->data() + nn * R);
    }
    return g;
}

GaussianCloud convert_gc(
    const GaussianCloud &source,
    std::optional<std::string> quaternion_order,
    std::optional<std::string> scale_space,
    std::optional<std::string> opacity_space,
    std::optional<std::string> sh_layout,
    std::optional<std::string> source_precision,
    std::optional<std::string> projection_mode_hint,
    std::optional<std::string> sorting_mode_hint,
    bool normalize_quaternions,
    std::optional<std::string> quaternion_norm,
    std::optional<std::string> sh_basis,
    std::optional<std::string> sh_phase,
    std::optional<std::string> sh_coefficient_order,
    std::optional<std::string> color_space,
    std::optional<std::string> coordinate_frame,
    std::optional<std::string> scale_to_meters_source) {
    validate_gaussian_structure(
        source, "convert_gaussian_conventions input");
    validate_gaussian_conventions(source, "convert_gaussian_conventions input");
    GaussianCloud result = source;
    const std::string target_quaternion_order =
        quaternion_order.value_or(source.quaternion_order);
    const std::string target_scale_space =
        scale_space.value_or(source.scale_space);
    const std::string target_opacity_space =
        opacity_space.value_or(source.opacity_space);
    const std::string target_sh_layout =
        sh_layout.value_or(source.sh_layout);
    const std::string target_source_precision =
        source_precision.value_or(source.source_precision);
    const std::string target_projection_mode_hint =
        projection_mode_hint.value_or(source.projection_mode_hint);
    const std::string target_sorting_mode_hint =
        sorting_mode_hint.value_or(source.sorting_mode_hint);
    const std::string target_quaternion_norm = quaternion_norm.value_or(
        normalize_quaternions ? "unit" : source.quaternion_norm);
    const std::string target_sh_basis =
        sh_basis.value_or(source.sh_basis);
    const std::string target_sh_phase =
        sh_phase.value_or(source.sh_phase);
    const std::string target_sh_coefficient_order =
        sh_coefficient_order.value_or(source.sh_coefficient_order);
    const std::string target_color_space =
        color_space.value_or(source.color_space);
    const std::string target_coordinate_frame =
        coordinate_frame.value_or(source.coordinate_frame);
    const std::string target_scale_to_meters_source =
        scale_to_meters_source.value_or(source.scale_to_meters_source);

    result.quaternion_order = target_quaternion_order;
    result.scale_space = target_scale_space;
    result.opacity_space = target_opacity_space;
    result.sh_layout = target_sh_layout;
    result.source_precision = target_source_precision;
    result.projection_mode_hint = target_projection_mode_hint;
    result.sorting_mode_hint = target_sorting_mode_hint;
    result.quaternion_norm = target_quaternion_norm;
    result.sh_basis = target_sh_basis;
    result.sh_phase = target_sh_phase;
    result.sh_coefficient_order = target_sh_coefficient_order;
    result.color_space = target_color_space;
    result.coordinate_frame = target_coordinate_frame;
    result.scale_to_meters_source = target_scale_to_meters_source;
    if (normalize_quaternions && target_quaternion_norm != "unit")
        throw std::invalid_argument(
            "convert_gaussian_conventions: normalize_quaternions requires "
            "quaternion_norm='unit'");
    if (!normalize_quaternions && source.quaternion_norm != "unit" &&
        target_quaternion_norm == "unit")
        throw std::invalid_argument(
            "convert_gaussian_conventions: quaternion_norm='unit' requires "
            "normalize_quaternions=True");
    auto require_metadata_identity = [](
        const std::string &source_value, const std::string &target_value,
        const char *name) {
        if (source_value == target_value || target_value == "unknown") return;
        throw std::invalid_argument(
            std::string("convert_gaussian_conventions: ") + name +
            " conversion is not qualified");
    };
    require_metadata_identity(source.sh_basis, target_sh_basis, "sh_basis");
    require_metadata_identity(source.sh_phase, target_sh_phase, "sh_phase");
    require_metadata_identity(
        source.sh_coefficient_order, target_sh_coefficient_order,
        "sh_coefficient_order");
    require_metadata_identity(
        source.color_space, target_color_space, "color_space");
    if (source.coordinate_frame != target_coordinate_frame)
        throw std::invalid_argument(
            "convert_gaussian_conventions: use convert_coordinates for "
            "coordinate_frame changes");
    if (source.scale_to_meters_source != target_scale_to_meters_source)
        throw std::invalid_argument(
            "convert_gaussian_conventions: use convert_coordinates for "
            "scale_to_meters_source changes");
    if (source.source_precision == "float32" &&
        target_source_precision == "float16")
        throw std::invalid_argument(
            "convert_gaussian_conventions: float32 to float16 requires explicit "
            "numeric quantization and is not a metadata conversion");
    if (normalize_quaternions && target_source_precision == "float16")
        throw std::invalid_argument(
            "convert_gaussian_conventions: quaternion normalization requires "
            "source_precision='float32'");

    if (source.quaternion_order != target_quaternion_order) {
        for (size_t index = 0; index < source.n; ++index) {
            const float *input = source.quats.data() + index * 4;
            float *output = result.quats.data() + index * 4;
            if (source.quaternion_order == "wxyz") {
                output[0] = input[1];
                output[1] = input[2];
                output[2] = input[3];
                output[3] = input[0];
            } else {
                output[0] = input[3];
                output[1] = input[0];
                output[2] = input[1];
                output[3] = input[2];
            }
        }
    }
    if (normalize_quaternions) {
        for (size_t index = 0; index < source.n; ++index) {
            float *output = result.quats.data() + index * 4;
            double norm_squared = 0.0;
            for (size_t component = 0; component < 4; ++component) {
                const double value = output[component];
                if (!std::isfinite(value))
                    throw std::invalid_argument(
                        "convert_gaussian_conventions: quaternions must be finite");
                norm_squared += value * value;
            }
            if (!(norm_squared > 0.0) || !std::isfinite(norm_squared))
                throw std::invalid_argument(
                    "convert_gaussian_conventions: quaternions must have non-zero "
                    "finite norm");
            const double inverse_norm = 1.0 / std::sqrt(norm_squared);
            for (size_t component = 0; component < 4; ++component)
                output[component] =
                    static_cast<float>(output[component] * inverse_norm);
        }
    }

    validate_gaussian_conventions(
        result, "convert_gaussian_conventions target");

    if (source.scale_space != target_scale_space) {
        for (size_t index = 0; index < source.scales.size(); ++index) {
            const float input = source.scales[index];
            if (!std::isfinite(input))
                throw std::invalid_argument(
                    "convert_gaussian_conventions: scales must be finite");
            if (source.scale_space == "linear" && !(input > 0.0f))
                throw std::invalid_argument(
                    "convert_gaussian_conventions: linear scales must be positive");
            const float output =
                source.scale_space == "log" ? std::exp(input) : std::log(input);
            if (!std::isfinite(output) ||
                (target_scale_space == "linear" && !(output > 0.0f)))
                throw std::invalid_argument(
                    "convert_gaussian_conventions: scale conversion is outside "
                    "the finite positive domain");
            result.scales[index] = output;
        }
    }

    if (source.opacity_space != target_opacity_space) {
        for (size_t index = 0; index < source.opacity.size(); ++index) {
            const float input = source.opacity[index];
            if (!std::isfinite(input))
                throw std::invalid_argument(
                    "convert_gaussian_conventions: opacities must be finite");
            if (source.opacity_space == "logit") {
                const double value = static_cast<double>(input);
                const double output =
                    value >= 0.0
                        ? 1.0 / (1.0 + std::exp(-value))
                        : std::exp(value) / (1.0 + std::exp(value));
                result.opacity[index] = static_cast<float>(output);
            } else {
                if (!(input > 0.0f && input < 1.0f))
                    throw std::invalid_argument(
                        "convert_gaussian_conventions: linear opacities must "
                        "be strictly between zero and one for logit conversion");
                result.opacity[index] =
                    std::log(input) - std::log1p(-input);
            }
        }
    }

    if (source.sh_layout != target_sh_layout && source.num_rest != 0) {
        const size_t coefficients = source.num_rest / 3;
        for (size_t index = 0; index < source.n; ++index) {
            const float *input =
                source.sh_rest.data() + index * source.num_rest;
            float *output =
                result.sh_rest.data() + index * source.num_rest;
            for (size_t coefficient = 0;
                 coefficient < coefficients; ++coefficient) {
                for (size_t channel = 0; channel < 3; ++channel) {
                    if (source.sh_layout == "channel_grouped")
                        output[coefficient * 3 + channel] =
                            input[channel * coefficients + coefficient];
                    else
                        output[channel * coefficients + coefficient] =
                            input[coefficient * 3 + channel];
                }
            }
        }
    }
    return result;
}

}  // namespace

void register_ply_gaussian(nb::module_ &m) {
    m.def("read_gaussian_ply", &read_gaussian_ply, "data"_a,
          "Decode a 3DGS Gaussian .ply (binary) into a GaussianCloud (raw/pre-activation values).");
    m.def("read_gaussian_ply_points", &read_gaussian_ply_points, "data"_a,
          "start"_a, "stop"_a,
          "Decode a non-empty half-open binary Gaussian PLY point range "
          "without allocating the full cloud.");
    m.def("write_gaussian_ply", &write_gaussian_ply, "cloud"_a,
          "Encode a GaussianCloud to 3DGS Gaussian .ply bytes (binary little-endian).");
    m.def("gaussian_cloud", &make_gc, "means"_a, "scales"_a, "quaternions"_a, "opacities"_a,
          "sh_dc"_a, "sh_rest"_a = nb::none(),
          "quaternion_order"_a = "wxyz",
          "scale_space"_a = "log",
          "opacity_space"_a = "logit",
          "sh_layout"_a = "channel_grouped",
          "source_precision"_a = "float32",
          "projection_mode_hint"_a = "perspective",
          "sorting_mode_hint"_a = "zDepth",
          nb::kw_only(),
          "quaternion_norm"_a = "unconstrained",
          "sh_basis"_a = "3dgs_real",
          "sh_phase"_a = "3dgs",
          "sh_coefficient_order"_a = "degree_then_m_neg_to_pos",
          "color_space"_a = "unknown",
          "coordinate_frame"_a = "unknown",
          "scale_to_meters"_a = nb::none(),
          "scale_to_meters_source"_a = "unknown",
          "Build a GaussianCloud from arrays (numpy/torch): means (N,3), scales (N,3), "
          "quaternions (N,4), opacities (N,), sh_dc (N,3), sh_rest (N,{0,9,24,45}).");
    m.def(
        "convert_gaussian_conventions", &convert_gc, "cloud"_a,
        "quaternion_order"_a = nb::none(), "scale_space"_a = nb::none(),
        "opacity_space"_a = nb::none(), "sh_layout"_a = nb::none(),
        "source_precision"_a = nb::none(),
        "projection_mode_hint"_a = nb::none(),
        "sorting_mode_hint"_a = nb::none(),
        "normalize_quaternions"_a = false,
        nb::kw_only(),
        "quaternion_norm"_a = nb::none(),
        "sh_basis"_a = nb::none(), "sh_phase"_a = nb::none(),
        "sh_coefficient_order"_a = nb::none(),
        "color_space"_a = nb::none(),
        "coordinate_frame"_a = nb::none(),
        "scale_to_meters_source"_a = nb::none(),
        "Explicitly convert Gaussian activation, quaternion, SH layout, source "
        "precision, and rendering-hint conventions without changing the source "
        "record.");
}
