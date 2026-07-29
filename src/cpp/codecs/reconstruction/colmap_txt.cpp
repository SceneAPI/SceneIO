// codecs/reconstruction/colmap_txt.cpp -- COLMAP *text* sparse-model reader/writer
// (legacy cameras/images/points3D and modern rigs/frames). The text twin of
// colmap.cpp: it
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
#include <nanobind/stl/tuple.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <locale.h>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <string_view>
#include <system_error>  // std::errc (from_chars_result::ec)
#include <unordered_set>

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
    const char *cursor = data.data();
    size_t remaining = data.size();
    const size_t max_chunk = static_cast<size_t>(
        std::numeric_limits<std::streamsize>::max());
    while (remaining != 0) {
        const size_t chunk = std::min(remaining, max_chunk);
        f.write(cursor, static_cast<std::streamsize>(chunk));
        if (!f)
            throw std::invalid_argument(
                "COLMAP text: cannot write " + path);
        cursor += chunk;
        remaining -= chunk;
    }
    f.flush();
    if (!f)
        throw std::invalid_argument(
            "COLMAP text: cannot write " + path);
}

bool path_exists(const std::string &path) {
    std::error_code error;
    const bool exists = std::filesystem::exists(path, error);
    if (error)
        throw std::invalid_argument(
            "COLMAP text: cannot inspect " + path + ": " +
            error.message());
    return exists;
}

void require_no_extension_sidecars(const std::string &dir) {
    constexpr std::array<const char *, 14> names = {
        "markers.txt",
        "marker_projections.txt",
        "charuco_boards.txt",
        "charuco_calibrations.txt",
        "time_frames.txt",
        "image_times.txt",
        "points3D_frames.txt",
        "markers.bin",
        "marker_projections.bin",
        "charuco_boards.bin",
        "charuco_calibrations.bin",
        "time_frames.bin",
        "image_times.bin",
        "points3D_frames.bin",
    };
    for (const char *name : names)
        if (path_exists(dir + "/" + name))
            throw std::invalid_argument(
                "COLMAP text: " + std::string(name) +
                " is present but this sparse-model record does not yet "
                "represent that sidecar");
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
constexpr size_t kStreamTokenLimit = 1024 * 1024;

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
    if (pos - s > kStreamTokenLimit)
        throw std::invalid_argument(
            "COLMAP text: token exceeds 1 MiB");
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

struct StreamToken {
    std::string value;
    bool present = false;
    bool line_end = false;
    bool eof = false;
};

// Read one token without ever materializing the physical line. Tokens are
// bounded because no valid numeric/model field needs to be large; selected
// image names use a separate unbounded remainder reader to retain full-reader
// behavior.
StreamToken read_line_token(std::ifstream &file, const char *what) {
    StreamToken result;
    char value;
    while (file.get(value)) {
        if (value == '\n') {
            result.line_end = true;
            return result;
        }
        if (is_sep(value)) continue;
        result.present = true;
        result.value.push_back(value);
        break;
    }
    if (!result.present) {
        if (file.bad())
            throw std::invalid_argument(std::string("COLMAP text: ") + what +
                                        " read failed");
        result.line_end = true;
        result.eof = file.eof();
        return result;
    }
    while (file.get(value)) {
        if (value == '\n') {
            result.line_end = true;
            return result;
        }
        if (is_sep(value)) return result;
        if (result.value.size() >= kStreamTokenLimit)
            throw std::invalid_argument(std::string("COLMAP text: ") + what +
                                        " token exceeds 1 MiB");
        result.value.push_back(value);
    }
    if (file.bad())
        throw std::invalid_argument(std::string("COLMAP text: ") + what +
                                    " read failed");
    result.line_end = true;
    result.eof = true;
    return result;
}

void ignore_line_remainder(std::ifstream &file, const char *what) {
    file.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
    if (file.bad())
        throw std::invalid_argument(std::string("COLMAP text: ") + what +
                                    " skip failed");
}

StreamToken read_data_line_first(std::ifstream &file, const char *what) {
    for (;;) {
        StreamToken token;
        char value;
        while (file.get(value)) {
            if (value == '\n') break;
            if (is_sep(value)) continue;
            if (value == '#') {
                ignore_line_remainder(file, what);
                break;
            }
            token.present = true;
            token.value.push_back(value);
            while (file.get(value)) {
                if (value == '\n') {
                    token.line_end = true;
                    return token;
                }
                if (is_sep(value)) return token;
                if (token.value.size() >= kStreamTokenLimit)
                    throw std::invalid_argument(
                        std::string("COLMAP text: ") + what +
                        " token exceeds 1 MiB");
                token.value.push_back(value);
            }
            if (file.bad())
                throw std::invalid_argument(
                    std::string("COLMAP text: ") + what +
                    " read failed");
            token.line_end = true;
            token.eof = true;
            return token;
        }
        if (file.bad())
            throw std::invalid_argument(std::string("COLMAP text: ") + what +
                                        " read failed");
        if (file.eof()) {
            token.line_end = true;
            token.eof = true;
            return token;
        }
    }
}

std::string read_name_remainder(std::ifstream &file) {
    std::string name;
    bool started = false;
    char value;
    while (file.get(value)) {
        if (value == '\n') break;
        if (!started && is_sep(value)) continue;
        started = true;
        name.push_back(value);
    }
    if (file.bad())
        throw std::invalid_argument(
            "COLMAP text: images.txt image name read failed");
    if (!name.empty() && name.back() == '\r') name.pop_back();
    return name;
}

// MODEL name -> id via the EXISTING colmap_model_info table (no new symbol).
int model_id_from_name(std::string_view name) {
    for (int id = 0; id <= 17; ++id)
        if (name == colmap_model_info(id).name) return id;
    throw std::invalid_argument("COLMAP text: unknown camera model '" + std::string(name) + "'");
}

int32_t sensor_type_from_name(std::string_view name) {
    if (name == "INVALID") return -1;
    if (name == "CAMERA") return 0;
    if (name == "IMU") return 1;
    throw std::invalid_argument(
        "COLMAP text: unknown sensor type '" + std::string(name) + "'");
}

const char *sensor_type_name(int32_t type) {
    switch (type) {
        case -1: return "INVALID";
        case 0: return "CAMERA";
        case 1: return "IMU";
        default:
            throw std::invalid_argument(
                "COLMAP text: invalid sensor type " +
                std::to_string(type));
    }
}

// ---- readers (populate the SAME fields, in the SAME order, as colmap.cpp) ---
void read_rigs_text(const std::string &text, Reconstruction &r) {
    Lines lines{text.data(), text.data() + text.size()};
    r.rig_sensor_off.push_back(0);
    std::string_view line;
    while (lines.next(line)) {
        if (blank_or_comment(line)) continue;
        size_t position = 0;
        r.rig_ids.push_back(parse_uint<uint32_t>(
            require_token(line, position, "RIG_ID"), "RIG_ID"));
        const uint32_t sensor_count = parse_uint<uint32_t>(
            require_token(line, position, "NUM_SENSORS"),
            "NUM_SENSORS");
        if (sensor_count == 0) {
            r.rig_ref_sensor_types.push_back(-1);
            r.rig_ref_sensor_ids.push_back(UINT32_MAX);
        } else {
            const int32_t reference_type = sensor_type_from_name(
                require_token(
                    line, position, "REF_SENSOR_TYPE"));
            if (reference_type == -1)
                throw std::invalid_argument(
                    "COLMAP text: rig reference sensor cannot be "
                    "INVALID");
            r.rig_ref_sensor_types.push_back(reference_type);
            r.rig_ref_sensor_ids.push_back(parse_uint<uint32_t>(
                require_token(
                    line, position, "REF_SENSOR_ID"),
                "REF_SENSOR_ID"));
        }
        for (uint32_t index = sensor_count == 0 ? 0 : 1;
             index < sensor_count; ++index) {
            const int32_t type = sensor_type_from_name(
                require_token(line, position, "SENSOR_TYPE"));
            if (type == -1)
                throw std::invalid_argument(
                    "COLMAP text: non-reference rig sensor cannot "
                    "be INVALID");
            r.rig_sensor_types.push_back(type);
            r.rig_sensor_ids.push_back(parse_uint<uint32_t>(
                require_token(line, position, "SENSOR_ID"),
                "SENSOR_ID"));
            const uint32_t has_pose = parse_uint<uint32_t>(
                require_token(line, position, "HAS_POSE"),
                "HAS_POSE");
            if (has_pose > 1)
                throw std::invalid_argument(
                    "COLMAP text: HAS_POSE must be zero or one");
            r.rig_sensor_has_pose.push_back(
                static_cast<uint8_t>(has_pose));
            for (int component = 0; component < 4; ++component)
                r.rig_sensor_quats.push_back(
                    has_pose
                        ? parse_f64(
                              require_token(
                                  line, position,
                                  "sensor quaternion"),
                              "sensor quaternion")
                        : (component == 0 ? 1.0 : 0.0));
            for (int component = 0; component < 3; ++component)
                r.rig_sensor_trans.push_back(
                    has_pose
                        ? parse_f64(
                              require_token(
                                  line, position,
                                  "sensor translation"),
                              "sensor translation")
                        : 0.0);
        }
        std::string_view extra;
        if (next_token(line, position, extra))
            throw std::invalid_argument(
                "COLMAP text: extra field in rigs.txt");
        r.rig_sensor_off.push_back(r.rig_sensor_types.size());
    }
}

void read_frames_text(const std::string &text, Reconstruction &r) {
    Lines lines{text.data(), text.data() + text.size()};
    r.frame_data_off.push_back(0);
    std::string_view line;
    while (lines.next(line)) {
        if (blank_or_comment(line)) continue;
        size_t position = 0;
        r.frame_ids.push_back(parse_uint<uint32_t>(
            require_token(line, position, "FRAME_ID"), "FRAME_ID"));
        r.frame_rig_ids.push_back(parse_uint<uint32_t>(
            require_token(line, position, "RIG_ID"), "RIG_ID"));
        for (int component = 0; component < 4; ++component)
            r.frame_quats.push_back(parse_f64(
                require_token(line, position, "frame quaternion"),
                "frame quaternion"));
        for (int component = 0; component < 3; ++component)
            r.frame_trans.push_back(parse_f64(
                require_token(line, position, "frame translation"),
                "frame translation"));
        const uint32_t data_count = parse_uint<uint32_t>(
            require_token(line, position, "NUM_DATA_IDS"),
            "NUM_DATA_IDS");
        for (uint32_t index = 0; index < data_count; ++index) {
            const int32_t type = sensor_type_from_name(
                require_token(line, position, "SENSOR_TYPE"));
            if (type == -1)
                throw std::invalid_argument(
                    "COLMAP text: frame data sensor cannot be "
                    "INVALID");
            r.frame_sensor_types.push_back(type);
            r.frame_sensor_ids.push_back(parse_uint<uint32_t>(
                require_token(line, position, "SENSOR_ID"),
                "SENSOR_ID"));
            r.frame_data_ids.push_back(parse_uint<uint64_t>(
                require_token(line, position, "DATA_ID"),
                "DATA_ID"));
        }
        std::string_view extra;
        if (next_token(line, position, extra))
            throw std::invalid_argument(
                "COLMAP text: extra field in frames.txt");
        r.frame_data_off.push_back(r.frame_sensor_types.size());
    }
}

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
    require_no_extension_sidecars(dir);
    Reconstruction r;
    const bool has_rigs = path_exists(dir + "/rigs.txt");
    const bool has_frames = path_exists(dir + "/frames.txt");
    if (has_rigs != has_frames)
        throw std::invalid_argument(
            "COLMAP text: modern sparse model requires both rigs.txt "
            "and frames.txt");
    r.has_rig_frame_model = has_rigs;
    if (has_rigs) read_rigs_text(read_file(dir + "/rigs.txt"), r);
    read_cameras_text(read_file(dir + "/cameras.txt"), r);
    if (has_frames)
        read_frames_text(read_file(dir + "/frames.txt"), r);
    read_images_text(read_file(dir + "/images.txt"), r);
    read_points_text(read_file(dir + "/points3D.txt"), r);
    validate_colmap_reconstruction(r, "COLMAP text");
    return r;
}

Reconstruction read_colmap_txt_image(const std::string &dir,
                                     uint32_t image_id) {
    nb::gil_scoped_release rel;
    require_no_extension_sidecars(dir);
    const bool has_rigs = path_exists(dir + "/rigs.txt");
    const bool has_frames = path_exists(dir + "/frames.txt");
    if (has_rigs != has_frames)
        throw std::invalid_argument(
            "COLMAP text: modern sparse model requires both rigs.txt "
            "and frames.txt");
    Reconstruction metadata;
    metadata.has_rig_frame_model = has_rigs;
    if (has_rigs) {
        read_rigs_text(read_file(dir + "/rigs.txt"), metadata);
        read_frames_text(read_file(dir + "/frames.txt"), metadata);
        validate_colmap_rig_frame_model(metadata, "COLMAP text");
    }
    Reconstruction r;
    r.obs_off.push_back(0);
    r.track_off.push_back(0);

    std::ifstream images(dir + "/images.txt", std::ios::binary);
    if (!images)
        throw std::invalid_argument("COLMAP text: cannot open " + dir +
                                    "/images.txt");
    bool found = false;
    uint32_t camera_id = 0;
    for (;;) {
        StreamToken token =
            read_data_line_first(images, "images.txt image line");
        if (!token.present) break;
        const uint32_t current =
            parse_uint<uint32_t>(token.value, "IMAGE_ID");
        bool line_end = token.line_end;
        auto required = [&](const char *what) {
            if (line_end)
                throw std::invalid_argument(
                    std::string("COLMAP text: missing field ") + what);
            StreamToken next = read_line_token(images, what);
            if (!next.present)
                throw std::invalid_argument(
                    std::string("COLMAP text: missing field ") + what);
            line_end = next.line_end;
            return next.value;
        };
        double quat[4], trans[3];
        for (double &value : quat)
            value = parse_f64(required("quaternion"), "quaternion");
        for (double &value : trans)
            value = parse_f64(required("translation"), "translation");
        const uint32_t current_camera = parse_uint<uint32_t>(
            required("CAMERA_ID"), "CAMERA_ID");
        std::string name;
        if (!line_end) {
            if (current == image_id)
                name = read_name_remainder(images);
            else
                ignore_line_remainder(images, "images.txt image name");
        }

        if (current != image_id) {
            // Line 2 is the immediately following physical line. It is
            // intentionally skipped without allocation for unrelated images.
            ignore_line_remainder(images, "images.txt observations");
            continue;
        }

        r.img_ids.push_back(current);
        r.quats.assign(quat, quat + 4);
        r.trans.assign(trans, trans + 3);
        r.img_cam_ids.push_back(current_camera);
        r.img_names.push_back(std::move(name));
        size_t token_index = 0;
        double x = 0.0, y = 0.0;
        for (;;) {
            StreamToken observation =
                read_line_token(images, "images.txt observation");
            if (observation.present) {
                if (token_index % 3 == 0)
                    x = parse_f64(observation.value, "observation X");
                else if (token_index % 3 == 1)
                    y = parse_f64(observation.value, "observation Y");
                else {
                    r.obs_xy.push_back(x);
                    r.obs_xy.push_back(y);
                    // The partial result excludes points3D.txt. Parse the
                    // source token for validation, then clear the reference
                    // so this remains a valid standalone reconstruction.
                    (void)parse_pt3d_id(observation.value);
                    r.obs_pt3d.push_back(-1);
                }
                ++token_index;
            }
            if (observation.line_end) break;
        }
        if (token_index % 3 != 0)
            throw std::invalid_argument(
                "COLMAP text: images.txt observation tokens are not a "
                "multiple of 3");
        r.obs_off.push_back(r.obs_pt3d.size());
        camera_id = current_camera;
        found = true;
        break;
    }
    if (images.bad())
        throw std::invalid_argument("COLMAP text: images.txt read failed");
    if (!found)
        throw std::invalid_argument("COLMAP text: image id " +
                                    std::to_string(image_id) + " not found");
    select_colmap_rig_frame_for_image(
        metadata, image_id, r, "COLMAP text");
    std::unordered_set<uint32_t> required_camera_ids = {camera_id};
    if (r.has_rig_frame_model) {
        if (r.rig_ref_sensor_types[0] == 0)
            required_camera_ids.insert(r.rig_ref_sensor_ids[0]);
        for (size_t sensor = 0;
             sensor < r.rig_sensor_types.size(); ++sensor)
            if (r.rig_sensor_types[sensor] == 0)
                required_camera_ids.insert(r.rig_sensor_ids[sensor]);
    }

    std::ifstream cameras(dir + "/cameras.txt", std::ios::binary);
    if (!cameras)
        throw std::invalid_argument("COLMAP text: cannot open " + dir +
                                    "/cameras.txt");
    for (;;) {
        StreamToken token =
            read_data_line_first(cameras, "cameras.txt line");
        if (!token.present) break;
        Camera camera;
        camera.id = parse_uint<uint32_t>(token.value, "CAMERA_ID");
        bool line_end = token.line_end;
        auto required = [&](const char *what) {
            if (line_end)
                throw std::invalid_argument(
                    std::string("COLMAP text: missing field ") + what);
            StreamToken next = read_line_token(cameras, what);
            if (!next.present)
                throw std::invalid_argument(
                    std::string("COLMAP text: missing field ") + what);
            line_end = next.line_end;
            return next.value;
        };
        camera.model_id = model_id_from_name(required("MODEL"));
        camera.width =
            parse_uint<uint64_t>(required("WIDTH"), "WIDTH");
        camera.height =
            parse_uint<uint64_t>(required("HEIGHT"), "HEIGHT");
        const int expected = colmap_model_info(camera.model_id).nparams;
        for (int i = 0; i < expected; ++i)
            camera.params.push_back(
                parse_f64(required("camera param"), "camera param"));
        bool extra = false;
        if (!line_end) {
            StreamToken tail =
                read_line_token(cameras, "camera param");
            extra = tail.present;
            if (!tail.line_end)
                ignore_line_remainder(cameras, "cameras.txt line");
        }
        if (extra)
            throw std::invalid_argument(
                "COLMAP text: camera " + std::to_string(camera.id) + " has " +
                "more than " + std::to_string(expected) +
                " params, expected " + std::to_string(expected) +
                " for model " +
                colmap_model_info(camera.model_id).name);
        if (required_camera_ids.erase(camera.id) != 0)
            r.cameras.push_back(std::move(camera));
    }
    if (cameras.bad())
        throw std::invalid_argument("COLMAP text: cameras.txt read failed");
    if (required_camera_ids.empty()) {
        validate_colmap_reconstruction(r, "COLMAP text");
        return r;
    }
    throw std::invalid_argument(
        "COLMAP text: camera id " +
        std::to_string(*std::min_element(
            required_camera_ids.begin(), required_camera_ids.end())) +
        " referenced by the selected image rig was not found");
}

size_t count_metadata_records(const std::string &path,
                              bool image_records) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::invalid_argument("COLMAP text: cannot open " + path);
    size_t count = 0;
    char block[65536];
    bool prefix = true;
    bool comment = false;
    bool data = false;
    bool skip_line = false;
    auto finish_line = [&]() {
        if (skip_line) {
            skip_line = false;
        } else if (data) {
            ++count;
            if (image_records) skip_line = true;
        }
        prefix = true;
        comment = false;
        data = false;
    };
    while (file) {
        file.read(block, sizeof(block));
        const std::streamsize got = file.gcount();
        for (std::streamsize i = 0; i < got; ++i) {
            const char c = block[i];
            if (c == '\n') {
                finish_line();
                continue;
            }
            if (skip_line || comment) continue;
            if (prefix) {
                if (c == ' ' || c == '\t' || c == '\r') continue;
                prefix = false;
                if (c == '#') {
                    comment = true;
                } else {
                    data = true;
                }
            }
        }
    }
    if (file.bad())
        throw std::invalid_argument("COLMAP text: file read failed");
    if (!skip_line && (!prefix || comment || data)) finish_line();
    return count;
}

std::tuple<size_t, size_t, size_t> inspect_colmap_txt(
    const std::string &dir) {
    size_t cameras, images, points;
    {
        nb::gil_scoped_release rel;
        cameras = count_metadata_records(dir + "/cameras.txt", false);
        images = count_metadata_records(dir + "/images.txt", true);
        points = count_metadata_records(dir + "/points3D.txt", false);
    }
    return {cameras, images, points};
}

// ---- writers (COLMAP WriteCamerasText/WriteImagesText/WritePoints3DText) ----
// "%.17g" == COLMAP's ostream precision(17): round-trips every double exactly.
class CNumericLocale {
public:
    CNumericLocale() {
#ifdef _WIN32
        locale_ = _create_locale(LC_NUMERIC, "C");
#else
        locale_ = newlocale(LC_NUMERIC_MASK, "C", nullptr);
#endif
        if (locale_ == nullptr)
            throw std::runtime_error(
                "COLMAP text: cannot create C numeric locale");
    }
    CNumericLocale(const CNumericLocale &) = delete;
    CNumericLocale &operator=(const CNumericLocale &) = delete;
    ~CNumericLocale() {
#ifdef _WIN32
        _free_locale(locale_);
#else
        freelocale(locale_);
#endif
    }

    int format(char *buffer, size_t size, double value) const {
#ifdef _WIN32
        return _snprintf_l(
            buffer, size, "%.17g", locale_, value);
#else
        const locale_t previous = uselocale(locale_);
        if (previous == static_cast<locale_t>(0))
            throw std::runtime_error(
                "COLMAP text: cannot select C numeric locale");
        const int result =
            std::snprintf(buffer, size, "%.17g", value);
        if (uselocale(previous) == static_cast<locale_t>(0))
            throw std::runtime_error(
                "COLMAP text: cannot restore numeric locale");
        return result;
#endif
    }

private:
#ifdef _WIN32
    _locale_t locale_ = nullptr;
#else
    locale_t locale_ = static_cast<locale_t>(0);
#endif
};

void fmt17(std::string &out, double v) {
    static const CNumericLocale locale;
    char buf[64];
    const int len = locale.format(buf, sizeof(buf), v);
    if (len < 0 || static_cast<size_t>(len) >= sizeof(buf))
        throw std::runtime_error(
            "COLMAP text: cannot format floating-point value");
    out.append(buf, static_cast<size_t>(len));
}

std::string write_rigs_text(const Reconstruction &r) {
    std::string out;
    out.reserve(256 + r.num_rigs() * 96 +
                r.rig_sensor_types.size() * 96);
    out += "# Rig calib list with one line of data per calib:\n";
    out += "#   RIG_ID, NUM_SENSORS, REF_SENSOR_TYPE, REF_SENSOR_ID, "
           "SENSORS[] as (SENSOR_TYPE, SENSOR_ID, HAS_POSE, [QW, QX, "
           "QY, QZ, TX, TY, TZ])\n";
    out += "# Number of rigs: " + std::to_string(r.num_rigs()) + "\n";
    for (size_t index = 0; index < r.num_rigs(); ++index) {
        const uint64_t begin = r.rig_sensor_off[index];
        const uint64_t end = r.rig_sensor_off[index + 1];
        const bool has_reference =
            r.rig_ref_sensor_types[index] != -1;
        const uint64_t count =
            (has_reference ? uint64_t{1} : uint64_t{0}) + end - begin;
        out += std::to_string(r.rig_ids[index]);
        out += ' ';
        out += std::to_string(count);
        if (has_reference) {
            out += ' ';
            out += sensor_type_name(r.rig_ref_sensor_types[index]);
            out += ' ';
            out += std::to_string(r.rig_ref_sensor_ids[index]);
        }
        for (uint64_t sensor = begin; sensor < end; ++sensor) {
            out += ' ';
            out += sensor_type_name(r.rig_sensor_types[sensor]);
            out += ' ';
            out += std::to_string(r.rig_sensor_ids[sensor]);
            out += ' ';
            out += std::to_string(r.rig_sensor_has_pose[sensor]);
            if (r.rig_sensor_has_pose[sensor]) {
                for (int component = 0; component < 4; ++component) {
                    out += ' ';
                    fmt17(
                        out,
                        r.rig_sensor_quats[sensor * 4 + component]);
                }
                for (int component = 0; component < 3; ++component) {
                    out += ' ';
                    fmt17(
                        out,
                        r.rig_sensor_trans[sensor * 3 + component]);
                }
            }
        }
        out += '\n';
    }
    return out;
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

std::string write_frames_text(const Reconstruction &r) {
    std::string out;
    out.reserve(256 + r.num_frames() * 128 +
                r.frame_sensor_types.size() * 32);
    out += "# Frame list with one line of data per frame:\n";
    out += "#   FRAME_ID, RIG_ID, RIG_FROM_WORLD[QW, QX, QY, QZ, TX, "
           "TY, TZ], NUM_DATA_IDS, DATA_IDS[] as (SENSOR_TYPE, "
           "SENSOR_ID, DATA_ID)\n";
    out +=
        "# Number of frames: " + std::to_string(r.num_frames()) + "\n";
    for (size_t index = 0; index < r.num_frames(); ++index) {
        out += std::to_string(r.frame_ids[index]);
        out += ' ';
        out += std::to_string(r.frame_rig_ids[index]);
        for (int component = 0; component < 4; ++component) {
            out += ' ';
            fmt17(
                out, r.frame_quats[index * 4 + component]);
        }
        for (int component = 0; component < 3; ++component) {
            out += ' ';
            fmt17(
                out, r.frame_trans[index * 3 + component]);
        }
        const uint64_t begin = r.frame_data_off[index];
        const uint64_t end = r.frame_data_off[index + 1];
        out += ' ';
        out += std::to_string(end - begin);
        for (uint64_t data = begin; data < end; ++data) {
            out += ' ';
            out += sensor_type_name(r.frame_sensor_types[data]);
            out += ' ';
            out += std::to_string(r.frame_sensor_ids[data]);
            out += ' ';
            out += std::to_string(r.frame_data_ids[data]);
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
    validate_colmap_reconstruction(r, "COLMAP text");
    for (const std::string &name : r.img_names)
        if (name.find('\r') != std::string::npos ||
            name.find('\n') != std::string::npos)
            throw std::invalid_argument(
                "COLMAP text: image names cannot contain line breaks");
    require_no_extension_sidecars(dir);
    if (!r.has_rig_frame_model &&
        (path_exists(dir + "/rigs.txt") ||
         path_exists(dir + "/frames.txt")))
        throw std::invalid_argument(
            "COLMAP text: refusing to leave stale rigs.txt/frames.txt "
            "while writing a legacy sparse model");
    if (r.has_rig_frame_model)
        write_file(dir + "/rigs.txt", write_rigs_text(r));
    write_file(dir + "/cameras.txt", write_cameras_text(r));
    if (r.has_rig_frame_model)
        write_file(dir + "/frames.txt", write_frames_text(r));
    write_file(dir + "/images.txt", write_images_text(r));
    write_file(dir + "/points3D.txt", write_points_text(r));
}

}  // namespace

void register_colmap_txt(nb::module_ &m) {
    m.def("_inspect_colmap_txt", &inspect_colmap_txt, "path"_a,
          "Return (camera_count, image_count, point_count) without constructing "
          "reconstruction arrays.");
    m.def("read_colmap_txt", &read_colmap_txt, "path"_a,
          "Read a legacy three-file or modern five-file COLMAP text sparse "
          "model directory into a Reconstruction, preserving rigs and "
          "frames (WXYZ, world_to_camera).");
    m.def("read_colmap_txt_image", &read_colmap_txt_image, "path"_a,
          "image_id"_a,
          "Read one COLMAP text image and its camera without opening "
          "points3D.txt or materializing unrelated images.");
    m.def("write_colmap_txt", &write_colmap_txt, "recon"_a, "path"_a,
          "Write a Reconstruction as a legacy three-file or modern "
          "five-file COLMAP text sparse model directory (%.17g doubles, "
          "LF endings).");
}
