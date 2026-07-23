// codecs/colmap_txt.cpp — COLMAP *text* sparse-model reader/writer
// (cameras.txt / images.txt / points3D.txt). The text twin of colmap.cpp: it
// reads into and writes from the SAME Reconstruction record with the SAME
// conventions (WXYZ quaternions, world->camera pose, model-tagged params[]),
// populating the identical SoA / CSR fields in the identical order so a
// bin->txt->bin round-trip is byte-exact against the binary codec.
//
// Parsing is a single pointer pass (no std::istringstream): fast_float::from_chars
// for doubles (portable across every wheel toolchain — std::from_chars<double> is
// absent on manylinux2014 GCC-10 and older macOS libc++) and std::from_chars for
// integers (complete everywhere), '#'-comment and blank tolerance, CRLF tolerance
// (a trailing '\r' is stripped per physical line).
// MODEL names map to ids by reverse-scanning the existing colmap_model_info
// table (no new header symbol). The GIL is released for the whole read/write
// body (npy_npz precedent): every helper is Python-free (plain std::string /
// Reconstruction in, std::string out); Python objects are only touched by the
// arg/return casters, which run with the GIL held outside the release scope.
//
// Doubles are written with "%.17g" (== COLMAP's ostream precision(17)), which
// round-trips every IEEE-754 double bit-exactly through text, so value parity
// with pycolmap is exact even though the byte layout is not (COLMAP text bytes
// vary by platform: CRLF text-mode writes, CRT %g nuances). Files are opened
// std::ios::binary so emitted line endings are LF-only on every platform.
// Malformed input raises std::invalid_argument (mapped to ValueError by the io
// layer) and never crashes: from_chars is bounded by an explicit end pointer and
// the tokenizer is bounded by the line length.
#include <nanobind/stl/string.h>

#include <charconv>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string_view>
#include <system_error>  // std::errc (from_chars_result::ec)

#include "fast_float/fast_float.h"
#include "records/reconstruction.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

// ---- whole-file I/O (binary both ways: raw bytes in, LF-only bytes out) ----
std::string read_file(const std::string &path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::invalid_argument("COLMAP text: cannot open " + path);
    return std::string(std::istreambuf_iterator<char>(f), {});
}
void write_file(const std::string &path, const std::string &data) {
    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::invalid_argument("COLMAP text: cannot write " + path);
    f.write(data.data(), static_cast<std::streamsize>(data.size()));
}

// ---- physical-line iterator: split on '\n', strip one trailing '\r' --------
struct Lines {
    const char *p, *end;
    bool next(std::string_view &line) {
        if (p >= end) return false;
        const char *s = p;
        const char *nl = static_cast<const char *>(std::memchr(p, '\n', static_cast<size_t>(end - p)));
        size_t len;
        if (nl) {
            len = static_cast<size_t>(nl - s);
            p = nl + 1;
        } else {
            len = static_cast<size_t>(end - s);
            p = end;
        }
        if (len && s[len - 1] == '\r') len--;  // CRLF tolerance
        line = std::string_view(s, len);
        return true;
    }
};

inline bool is_sep(char c) { return c == ' ' || c == '\t' || c == '\r'; }

// A blank (all-whitespace) or '#'-comment line (leading ws allowed).
bool blank_or_comment(std::string_view line) {
    size_t i = 0;
    while (i < line.size() && is_sep(line[i])) i++;
    return i == line.size() || line[i] == '#';
}

// Next whitespace-delimited token (runs of [ \t\r] collapse). false at line end.
bool next_token(std::string_view line, size_t &pos, std::string_view &tok) {
    while (pos < line.size() && is_sep(line[pos])) pos++;
    if (pos >= line.size()) return false;
    size_t s = pos;
    while (pos < line.size() && !is_sep(line[pos])) pos++;
    tok = line.substr(s, pos - s);
    return true;
}
std::string_view require_token(std::string_view line, size_t &pos, const char *what) {
    std::string_view t;
    if (!next_token(line, pos, t))
        throw std::invalid_argument(std::string("COLMAP text: missing field ") + what);
    return t;
}

double parse_f64(std::string_view t, const char *what) {
    double v = 0.0;
    const auto r = fast_float::from_chars(t.data(), t.data() + t.size(), v);
    if (r.ec != std::errc{} || r.ptr != t.data() + t.size())
        throw std::invalid_argument(std::string("COLMAP text: bad number for ") + what);
    return v;
}
template <typename T>
T parse_uint(std::string_view t, const char *what) {
    T v = 0;
    const auto r = std::from_chars(t.data(), t.data() + t.size(), v);
    if (r.ec != std::errc{} || r.ptr != t.data() + t.size())
        throw std::invalid_argument(std::string("COLMAP text: bad integer for ") + what);
    return v;
}
// images.txt observation ids: "-1" (no 3D point) -> -1; else a uint64 id cast to
// int64 (the record's sentinel model, matching the .bin reader's UINT64_MAX->-1).
int64_t parse_pt3d_id(std::string_view t) {
    if (t == "-1") return -1;
    const uint64_t v = parse_uint<uint64_t>(t, "POINT3D_ID");
    if (v > static_cast<uint64_t>(INT64_MAX))
        throw std::invalid_argument("COLMAP text: POINT3D_ID out of int64 range");
    return static_cast<int64_t>(v);
}

// MODEL name -> id via the EXISTING colmap_model_info table (no new symbol).
int model_id_from_name(std::string_view name) {
    for (int id = 0; id <= 10; ++id)
        if (name == colmap_model_info(id).name) return id;
    throw std::invalid_argument("COLMAP text: unknown camera model '" + std::string(name) + "'");
}

// ---- readers (populate the SAME fields, in the SAME order, as colmap.cpp) ---
void read_cameras_text(const std::string &text, Reconstruction &r) {
    Lines lr{text.data(), text.data() + text.size()};
    std::string_view line;
    while (lr.next(line)) {
        if (blank_or_comment(line)) continue;
        size_t pos = 0;
        Camera c;
        c.id = parse_uint<uint32_t>(require_token(line, pos, "CAMERA_ID"), "CAMERA_ID");
        c.model_id = model_id_from_name(require_token(line, pos, "MODEL"));
        c.width = parse_uint<uint64_t>(require_token(line, pos, "WIDTH"), "WIDTH");
        c.height = parse_uint<uint64_t>(require_token(line, pos, "HEIGHT"), "HEIGHT");
        const int nparams = colmap_model_info(c.model_id).nparams;
        std::string_view t;
        while (next_token(line, pos, t)) c.params.push_back(parse_f64(t, "camera param"));
        if (static_cast<int>(c.params.size()) != nparams)
            throw std::invalid_argument(
                "COLMAP text: camera " + std::to_string(c.id) + " has " +
                std::to_string(c.params.size()) + " params, expected " + std::to_string(nparams) +
                " for model " + colmap_model_info(c.model_id).name);
        r.cameras.push_back(std::move(c));
    }
}

void read_images_text(const std::string &text, Reconstruction &r) {
    Lines lr{text.data(), text.data() + text.size()};
    r.obs_off.push_back(0);
    std::string_view line;
    while (lr.next(line)) {
        if (blank_or_comment(line)) continue;  // header/blank skip applies to line 1 ONLY
        size_t pos = 0;
        r.img_ids.push_back(parse_uint<uint32_t>(require_token(line, pos, "IMAGE_ID"), "IMAGE_ID"));
        for (int k = 0; k < 4; k++)
            r.quats.push_back(parse_f64(require_token(line, pos, "quaternion"), "quaternion"));
        for (int k = 0; k < 3; k++)
            r.trans.push_back(parse_f64(require_token(line, pos, "translation"), "translation"));
        r.img_cam_ids.push_back(parse_uint<uint32_t>(require_token(line, pos, "CAMERA_ID"), "CAMERA_ID"));
        // NAME = remainder of line 1 after CAMERA_ID (one ws run skipped; may be empty).
        while (pos < line.size() && is_sep(line[pos])) pos++;
        r.img_names.emplace_back(line.data() + pos, line.size() - pos);
        // Line 2 is the IMMEDIATELY following physical line (NO blank/comment skip):
        // an empty line, or EOF after line 1, means zero observations.
        std::string_view obs;
        if (lr.next(obs)) {
            size_t p2 = 0, k = 0;
            std::string_view t;
            double x = 0.0, y = 0.0;
            while (next_token(obs, p2, t)) {
                if (k % 3 == 0) x = parse_f64(t, "observation X");
                else if (k % 3 == 1) y = parse_f64(t, "observation Y");
                else {
                    r.obs_xy.push_back(x);
                    r.obs_xy.push_back(y);
                    r.obs_pt3d.push_back(parse_pt3d_id(t));
                }
                k++;
            }
            if (k % 3 != 0)
                throw std::invalid_argument(
                    "COLMAP text: images.txt observation tokens are not a multiple of 3");
        }
        r.obs_off.push_back(r.obs_pt3d.size());
    }
}

void read_points_text(const std::string &text, Reconstruction &r) {
    Lines lr{text.data(), text.data() + text.size()};
    r.track_off.push_back(0);
    std::string_view line;
    while (lr.next(line)) {
        if (blank_or_comment(line)) continue;
        size_t pos = 0;
        r.pt_ids.push_back(parse_uint<uint64_t>(require_token(line, pos, "POINT3D_ID"), "POINT3D_ID"));
        for (int k = 0; k < 3; k++) r.xyz.push_back(parse_f64(require_token(line, pos, "xyz"), "xyz"));
        for (int k = 0; k < 3; k++) {
            const uint32_t v = parse_uint<uint32_t>(require_token(line, pos, "color"), "color");
            if (v > 255)
                throw std::invalid_argument("COLMAP text: RGB component out of range 0..255");
            r.rgb.push_back(static_cast<uint8_t>(v));
        }
        r.err.push_back(parse_f64(require_token(line, pos, "ERROR"), "ERROR"));
        size_t k = 0;
        uint32_t img_id = 0;
        std::string_view t;
        while (next_token(line, pos, t)) {
            if (k % 2 == 0) img_id = parse_uint<uint32_t>(t, "track IMAGE_ID");
            else {
                r.track.push_back(img_id);
                r.track.push_back(parse_uint<uint32_t>(t, "track POINT2D_IDX"));
            }
            k++;
        }
        if (k % 2 != 0)
            throw std::invalid_argument(
                "COLMAP text: points3D.txt track tokens are not a multiple of 2");
        r.track_off.push_back(r.track.size() / 2);
    }
}

Reconstruction read_colmap_txt(const std::string &dir) {
    nb::gil_scoped_release rel;  // pure-C++ body: file I/O + parse, no Python objects
    Reconstruction r;
    read_cameras_text(read_file(dir + "/cameras.txt"), r);
    read_images_text(read_file(dir + "/images.txt"), r);
    read_points_text(read_file(dir + "/points3D.txt"), r);
    return r;
}

// ---- writers (COLMAP WriteCamerasText/WriteImagesText/WritePoints3DText) ----
// "%.17g" == COLMAP's ostream precision(17): round-trips every double exactly.
void fmt17(std::string &out, double v) {
    char buf[64];
    const int len = std::snprintf(buf, sizeof(buf), "%.17g", v);
    out.append(buf, static_cast<size_t>(len));
}

std::string write_cameras_text(const Reconstruction &r) {
    std::string out;
    out.reserve(160 + r.cameras.size() * 48);
    out += "# Camera list with one line of data per camera:\n";
    out += "#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n";
    out += "# Number of cameras: " + std::to_string(r.cameras.size()) + "\n";
    for (const auto &c : r.cameras) {
        const ModelInfo mi = colmap_model_info(c.model_id);  // guard: throws on unknown id
        if (static_cast<int>(c.params.size()) != mi.nparams)  // guard: refuse a file COLMAP can't read
            throw std::invalid_argument(
                "COLMAP text: camera " + std::to_string(c.id) + " params length " +
                std::to_string(c.params.size()) + " != " + std::to_string(mi.nparams) +
                " for model " + mi.name);
        out += std::to_string(c.id);
        out += ' ';
        out += mi.name;
        out += ' ';
        out += std::to_string(c.width);
        out += ' ';
        out += std::to_string(c.height);
        for (double p : c.params) {
            out += ' ';
            fmt17(out, p);
        }
        out += '\n';
    }
    return out;
}

std::string write_images_text(const Reconstruction &r) {
    const size_t N = r.num_images();
    // mean observations per image = triangulated 2D points / images, matching
    // COLMAP's ComputeMeanObservationsPerRegImage (which sums Image::NumPoints3D,
    // counting only points2D WITH a 3D point). The -1 "no 3D point" sentinels are
    // excluded, so this differs from obs_pt3d.size()/N whenever any are present.
    size_t tri = 0;
    for (int64_t id : r.obs_pt3d)
        if (id >= 0) ++tri;
    const double mean_obs = N == 0 ? 0.0 : static_cast<double>(tri) / static_cast<double>(N);
    std::string out;
    out.reserve(256 + N * 96 + r.obs_pt3d.size() * 24);
    out += "# Image list with two lines of data per image:\n";
    out += "#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n";
    out += "#   POINTS2D[] as (X, Y, POINT3D_ID)\n";
    out += "# Number of images: " + std::to_string(N) + ", mean observations per image: ";
    fmt17(out, mean_obs);
    out += '\n';
    for (size_t i = 0; i < N; i++) {
        out += std::to_string(r.img_ids[i]);
        for (int k = 0; k < 4; k++) {
            out += ' ';
            fmt17(out, r.quats[i * 4 + k]);
        }
        for (int k = 0; k < 3; k++) {
            out += ' ';
            fmt17(out, r.trans[i * 3 + k]);
        }
        out += ' ';
        out += std::to_string(r.img_cam_ids[i]);
        out += ' ';
        out += r.img_names[i];
        out += '\n';
        // line 2: "X Y POINT3D_ID" triples, single-space separated, no trailing
        // space; an empty line (just '\n') for a zero-observation image.
        const uint64_t a = r.obs_off[i], e = r.obs_off[i + 1];
        for (uint64_t j = a; j < e; j++) {
            if (j != a) out += ' ';
            fmt17(out, r.obs_xy[j * 2]);
            out += ' ';
            fmt17(out, r.obs_xy[j * 2 + 1]);
            out += ' ';
            out += std::to_string(r.obs_pt3d[j]);  // int64; -1 sentinel prints "-1"
        }
        out += '\n';
    }
    return out;
}

std::string write_points_text(const Reconstruction &r) {
    const size_t M = r.num_points();
    const size_t pairs = r.track.size() / 2;
    const double mean_track =
        M == 0 ? 0.0 : static_cast<double>(pairs) / static_cast<double>(M);
    std::string out;
    out.reserve(256 + M * 64 + pairs * 16);
    out += "# 3D point list with one line of data per point:\n";
    out += "#   POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)\n";
    out += "# Number of points: " + std::to_string(M) + ", mean track length: ";
    fmt17(out, mean_track);
    out += '\n';
    for (size_t i = 0; i < M; i++) {
        out += std::to_string(r.pt_ids[i]);
        for (int k = 0; k < 3; k++) {
            out += ' ';
            fmt17(out, r.xyz[i * 3 + k]);
        }
        for (int k = 0; k < 3; k++) {
            out += ' ';
            out += std::to_string(static_cast<unsigned>(r.rgb[i * 3 + k]));
        }
        out += ' ';
        fmt17(out, r.err[i]);
        const uint64_t a = r.track_off[i], e = r.track_off[i + 1];
        for (uint64_t j = a; j < e; j++) {
            out += ' ';
            out += std::to_string(r.track[j * 2]);
            out += ' ';
            out += std::to_string(r.track[j * 2 + 1]);
        }
        out += '\n';
    }
    return out;
}

void write_colmap_txt(const Reconstruction &r, const std::string &dir) {
    nb::gil_scoped_release rel;  // pure-C++ body: formatting + file I/O, no Python objects
    write_file(dir + "/cameras.txt", write_cameras_text(r));
    write_file(dir + "/images.txt", write_images_text(r));
    write_file(dir + "/points3D.txt", write_points_text(r));
}

}  // namespace

void register_colmap_txt(nb::module_ &m) {
    m.def("read_colmap_txt", &read_colmap_txt, "path"_a,
          "Read a COLMAP text sparse model directory (cameras.txt/images.txt/points3D.txt) into "
          "a Reconstruction (WXYZ quaternions, world_to_camera; the text twin of read_colmap_sparse).");
    m.def("write_colmap_txt", &write_colmap_txt, "recon"_a, "path"_a,
          "Write a Reconstruction as a COLMAP text sparse model directory (%.17g doubles, LF line "
          "endings; guards unknown camera models and wrong per-model param counts).");
}
