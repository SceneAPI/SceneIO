// codecs/nvm.cpp — VisualSFM NVM_V3 sparse-model reader/writer into the shared
// Reconstruction record (records/reconstruction.hpp), the token-stream sibling
// of colmap_txt.cpp. NVM is a whitespace-delimited TOKEN stream (not line
// based): PBA reads it with operator>>, so newlines are not significant and CRLF
// tolerance falls out for free.
//
// Grammar (single reconstructed model):
//   NVM_V3
//   <ncam>
//   <name> <f> <qw qx qy qz> <cx cy cz> <radial> <0>           (per camera)
//   <npts>
//   <X Y Z> <r g b> <#meas> {<img_idx> <feat_idx> <x> <y>}     (per point)
//   0                                                          (model-list terminator)
//   <PLY section — ignored>
//
// POSE CONVENTION (nailed; recorded into the record's canonical WXYZ /
// world_to_camera frame — NO transpose, NO conjugate):
//   * The NVM quaternion (file order qw qx qy qz) is the WXYZ Hamilton quaternion
//     of the WORLD-TO-CAMERA rotation R (x_cam = R·x_world + t) — the SAME
//     convention as COLMAP's qvec — so it is stored into quats VERBATIM.
//   * NVM stores the camera CENTER C in world coords, not the translation, so
//     READ  t = -R(q_hat)·C   and   WRITE  C = -R(q_hat)^T·t   (q_hat = the
//     normalized copy; the stored quaternion stays raw). This center<->translation
//     reparameterization is THE transform of this codec.
//   Authority: PBA util.h LoadNVM — the reader the NVM format doc itself
//   designates as normative — calls SetQuaternionRotation(q) (the standard
//   Hamilton quat->matrix, term-identical to transforms_json.cpp's quat_to_matrix)
//   then SetCameraCenterAfterRotation(C) = "t = -R·C". MVE bundle_io (trans =
//   -rot·center) and TheiaSfM read_nvm_file.cc independently agree. The
//   "camera-to-world quaternion" phrasing in some secondary sources is the classic
//   mislabel (it describes R^T); the exact-FP permutation-quaternion pin test makes
//   the choice unfakeable.
//
// 2D MEASUREMENTS are relative to the IMAGE CENTER and NVM carries no width/height,
// so cameras get width = height = 0, cx = cy = 0 and obs_xy is stored VERBATIM in
// that centered frame — geometrically self-consistent (projecting xyz through q,t,f
// with pp=(0,0) predicts obs_xy directly) but a DIFFERENT 2D anchor than COLMAP's
// top-left. The record has no machine-readable obs-anchor slot, so it is carried in
// these comments + the docstrings and ENFORCED by the writer guards (cx=cy=0,
// w=h=0, no -1 obs) so a top-left-anchored COLMAP record can never be silently
// mislabeled as NVM.
//
// INTRINSICS: focal in pixels; radial == 0 -> SIMPLE_PINHOLE {f,0,0}, else
// SIMPLE_RADIAL {f,0,0,r} with r stored VERBATIM (VisualSFM's single radial
// coefficient is a measurement-space model, numerically NOT interchangeable with
// COLMAP SIMPLE_RADIAL's projection-space k1 — the codec records the value, a
// normalizer converts the meaning).
//
// DESCOPES / lossy (documented, loud): the NVM_V3_R9T rotation-matrix variant and
// FixedK fixed-calibration headers are refused; a genuine multi-model file (a
// second reconstruction WITH points) is refused, while VisualSFM's trailing
// "empty model of unregistered images" (cameras, 0 points) is tolerated and its
// cameras discarded; everything after the terminating 0 (the PLY section, which
// may hold free text) is ignored; NVM feature indices (into external .sift files)
// are DISCARDED and the writer re-emits the compact per-image observation index in
// their place (so re-writing a foreign NVM renumbers feature indices; write∘read is
// a byte-exact fixpoint after the first read); err has no NVM field and is set to
// the -1.0 COLMAP unknown-error sentinel; ids (camera/image/point) are synthesized
// 1-based; filenames are stored verbatim including VisualSFM's '"'-for-space escape
// (recorded, not translated).
//
// Portability/GIL: doubles are parsed with fast_float::from_chars (std::from_chars
// <double> is absent on manylinux2014 GCC-10 / older libc++) and integers with
// std::from_chars (complete everywhere); the pure-C++ decode/encode body runs with
// the GIL released (xyz.cpp precedent) — no Python objects are touched inside.
// Malformed input raises std::invalid_argument (-> ValueError -> FormatError) and
// never crashes: every from_chars is end-pointer bounded and hostile counts are
// capped against the byte budget before any allocation.
#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <string_view>
#include <system_error>  // std::errc (from_chars_result::ec)
#include <unordered_map>
#include <vector>

#include "fast_float/fast_float.h"
#include "records/reconstruction.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

// --- rotation from a WXYZ quaternion --------------------------------------
// Local copy of transforms_json.cpp's quat_to_matrix (Shepperd-consistent; term
// for term identical to PBA's SetQuaternionRotation, so the derived R matches the
// normative reader's). Normalizes internally. The duplicate-local-helper is the
// house precedent (pose_text.cpp, transforms_json.cpp each carry one); lifting the
// pair into a shared io/ header is an optional follow-up, not this change.
void quat_to_matrix(const double q[4], double R[9]) {
    double w = q[0], x = q[1], y = q[2], z = q[3];
    const double n = std::sqrt(w * w + x * x + y * y + z * z);
    if (n > 0.0) { w /= n; x /= n; y /= n; z /= n; }
    R[0] = 1.0 - 2.0 * (y * y + z * z); R[1] = 2.0 * (x * y - w * z);       R[2] = 2.0 * (x * z + w * y);
    R[3] = 2.0 * (x * y + w * z);       R[4] = 1.0 - 2.0 * (x * x + z * z); R[5] = 2.0 * (y * z - w * x);
    R[6] = 2.0 * (x * z - w * y);       R[7] = 2.0 * (y * z + w * x);       R[8] = 1.0 - 2.0 * (x * x + y * y);
}

// --- token stream over the whole buffer (NVM is grammar-per-token) ----------
inline bool is_ws(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

struct Toks {
    const char *p;
    const char *end;
    bool next(std::string_view &tok) {
        while (p < end && is_ws(*p)) ++p;
        if (p >= end) return false;
        const char *s = p;
        while (p < end && !is_ws(*p)) ++p;
        tok = std::string_view(s, static_cast<size_t>(p - s));
        return true;
    }
    std::string_view require(const char *what) {
        std::string_view t;
        if (!next(t)) throw std::invalid_argument(std::string("NVM: missing field ") + what);
        return t;
    }
};

// fast_float for doubles (portable; std::from_chars<double> is unavailable on
// manylinux2014 GCC-10 / older libc++). Full-consume check; the echoed token is
// bounded to 40 chars so a hostile "number" cannot bloat the message (xyz.cpp).
double parse_f64(std::string_view t, const char *what) {
    double v = 0.0;
    const auto r = fast_float::from_chars(t.data(), t.data() + t.size(), v);
    if (r.ec != std::errc{} || r.ptr != t.data() + t.size()) {
        const size_t len = std::min<size_t>(t.size(), 40);
        std::string shown(t.data(), t.data() + len);
        if (t.size() > len) shown += "...";
        throw std::invalid_argument(std::string("NVM: bad number for ") + what + " '" + shown + "'");
    }
    return v;
}

// std::from_chars for integers (complete on every toolchain).
template <typename T>
T parse_uint(std::string_view t, const char *what) {
    T v = 0;
    const auto r = std::from_chars(t.data(), t.data() + t.size(), v);
    if (r.ec != std::errc{} || r.ptr != t.data() + t.size())
        throw std::invalid_argument(std::string("NVM: bad integer for ") + what);
    return v;
}

// Append one double as canonical text: %.17g (parse-exact round-trip through
// fast_float) for finite values, canonical nan/-nan/inf/-inf for non-finite —
// NEVER the MSVC CRT "-nan(ind)"/"1.#INF" spellings (xyz.cpp append_coord).
void append_f64(std::string &out, double v) {
    if (std::isnan(v)) {
        out += std::signbit(v) ? "-nan" : "nan";
    } else if (std::isinf(v)) {
        out += std::signbit(v) ? "-inf" : "inf";
    } else {
        if (v == 0.0) v = 0.0;  // normalize -0.0 -> "0"
        char buf[64];
        const int len = std::snprintf(buf, sizeof(buf), "%.17g", v);
        out.append(buf, static_cast<size_t>(len));
    }
}

// ---- reader (pure C++, no Python objects: safe with the GIL released) -------
void decode_nvm(const char *p, size_t n, Reconstruction &r) {
    Toks toks{p, p + n};
    std::string_view tok;

    // 1. HEADER: first token must be exactly "NVM_V3".
    if (!toks.next(tok))
        throw std::invalid_argument("NVM: missing NVM_V3 header (not a VisualSFM NVM file)");
    if (tok == "NVM_V3_R9T")
        throw std::invalid_argument("NVM: NVM_V3_R9T (rotation-matrix) variant is not supported");
    if (tok != "NVM_V3")
        throw std::invalid_argument("NVM: missing NVM_V3 header (not a VisualSFM NVM file)");

    // Camera count — or a calibration header (FixedK ...). A token that does not
    // fully parse as a uint64 is a calibration form we do not support.
    if (!toks.next(tok))
        throw std::invalid_argument("NVM: missing field camera count");
    uint64_t ncam = 0;
    {
        const auto res = std::from_chars(tok.data(), tok.data() + tok.size(), ncam);
        if (res.ec != std::errc{} || res.ptr != tok.data() + tok.size()) {
            const size_t len = std::min<size_t>(tok.size(), 40);
            std::string shown(tok.data(), tok.data() + len);
            if (tok.size() > len) shown += "...";
            throw std::invalid_argument(
                "NVM: unsupported calibration header ('" + shown +
                "') — fixed-calibration (FixedK) files are not supported");
        }
    }
    if (ncam >= 0xFFFFFFFFULL)  // ids are i+1 in uint32
        throw std::invalid_argument("NVM: camera count too large");

    // Reserve with a hostile-count cap: a minimal camera record is ~21 bytes, so a
    // lying ncam cannot force an up-front allocation (xyz.cpp n/6 precedent).
    const size_t cam_cap = static_cast<size_t>(std::min<uint64_t>(ncam, n / 21 + 1));
    r.cameras.reserve(cam_cap);
    r.img_ids.reserve(cam_cap);
    r.img_cam_ids.reserve(cam_cap);
    r.img_names.reserve(cam_cap);
    r.quats.reserve(cam_cap * 4);
    r.trans.reserve(cam_cap * 3);

    // 2. CAMERAS (one Camera + one image per line; NVM focal is per-image).
    for (uint64_t i = 0; i < ncam; ++i) {
        const std::string_view name = toks.require("camera name");
        const double f = parse_f64(toks.require("camera focal"), "camera focal");
        double q[4];
        for (int k = 0; k < 4; ++k) q[k] = parse_f64(toks.require("camera quaternion"), "camera quaternion");
        double C[3];
        for (int k = 0; k < 3; ++k) C[k] = parse_f64(toks.require("camera center"), "camera center");
        const double radial = parse_f64(toks.require("camera radial"), "camera radial");
        parse_f64(toks.require("camera placeholder"), "camera placeholder");  // PBA parses & ignores

        Camera cam;
        cam.id = static_cast<uint32_t>(i + 1);
        cam.model_id = (radial != 0.0) ? 2 : 0;  // SIMPLE_RADIAL : SIMPLE_PINHOLE
        cam.width = 0;
        cam.height = 0;
        if (radial != 0.0)
            cam.params = {f, 0.0, 0.0, radial};
        else
            cam.params = {f, 0.0, 0.0};
        r.cameras.push_back(std::move(cam));

        r.img_ids.push_back(static_cast<uint32_t>(i + 1));
        r.img_cam_ids.push_back(static_cast<uint32_t>(i + 1));
        r.img_names.emplace_back(name.data(), name.size());  // verbatim ('"'-escape untranslated)

        r.quats.push_back(q[0]);  // WXYZ, stored raw (may be unnormalized)
        r.quats.push_back(q[1]);
        r.quats.push_back(q[2]);
        r.quats.push_back(q[3]);

        // t = -R(q_hat)·C. A zero/non-finite quaternion has no rotation -> raise
        // (deviation from PBA's silent identity fallback, per malformed-raises).
        const double nq = q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3];
        if (!std::isfinite(nq) || nq == 0.0)
            throw std::invalid_argument("NVM: camera " + std::to_string(i) +
                                        " has a zero/non-finite quaternion");
        double R[9];
        quat_to_matrix(q, R);
        for (int k = 0; k < 3; ++k)
            r.trans.push_back(-(R[k * 3 + 0] * C[0] + R[k * 3 + 1] * C[1] + R[k * 3 + 2] * C[2]));
    }

    // 3. POINTS (measurements arrive grouped by POINT; obs CSR is grouped by IMAGE
    // — buffer measurements flat, then scatter in pass 2).
    const uint64_t npts = parse_uint<uint64_t>(toks.require("point count"), "point count");
    const size_t pt_cap = static_cast<size_t>(std::min<uint64_t>(npts, n / 16 + 1));
    r.pt_ids.reserve(pt_cap);
    r.xyz.reserve(pt_cap * 3);
    r.rgb.reserve(pt_cap * 3);
    r.err.reserve(pt_cap);
    r.track_off.reserve(pt_cap + 1);

    const size_t N = r.cameras.size();  // == ncam (the camera loop ran to completion)
    std::vector<uint64_t> cnt(N, 0);    // per-image observation counts
    std::vector<uint32_t> meas_img;     // flat, file (point-scan) order
    std::vector<double> meas_x, meas_y;
    std::vector<uint64_t> point_m;      // per-point measurement count
    point_m.reserve(pt_cap);

    for (uint64_t j = 0; j < npts; ++j) {
        r.pt_ids.push_back(j + 1);  // NVM has no point ids; synthesize 1-based
        for (int k = 0; k < 3; ++k) r.xyz.push_back(parse_f64(toks.require("point xyz"), "point xyz"));
        for (int k = 0; k < 3; ++k) {
            const uint32_t v = parse_uint<uint32_t>(toks.require("point color"), "point color");
            if (v > 255) throw std::invalid_argument("NVM: RGB component out of range 0..255");
            r.rgb.push_back(static_cast<uint8_t>(v));
        }
        r.err.push_back(-1.0);  // NVM carries no reprojection error (COLMAP's sentinel)
        const uint64_t m = parse_uint<uint64_t>(toks.require("measurement count"), "measurement count");
        for (uint64_t k = 0; k < m; ++k) {
            const uint32_t img_idx =
                parse_uint<uint32_t>(toks.require("measurement image index"), "measurement image index");
            if (img_idx >= ncam)
                throw std::invalid_argument("NVM: point " + std::to_string(j) + " measurement " +
                                            std::to_string(k) + ": image index out of range");
            parse_uint<uint32_t>(toks.require("measurement feature index"),
                                 "measurement feature index");  // .sift index — not representable, discarded
            const double x = parse_f64(toks.require("measurement x"), "measurement x");
            const double y = parse_f64(toks.require("measurement y"), "measurement y");
            meas_img.push_back(img_idx);
            meas_x.push_back(x);
            meas_y.push_back(y);
            ++cnt[img_idx];
        }
        point_m.push_back(m);
    }

    // 4. CSR BUILD (pass 2): scatter measurements onto their image buckets in file
    // scan order. obs_off/track_off carry the leading 0 sentinel even when empty.
    r.obs_off.resize(N + 1);
    r.obs_off[0] = 0;
    for (size_t i = 0; i < N; ++i) r.obs_off[i + 1] = r.obs_off[i] + cnt[i];
    const uint64_t sumK = r.obs_off[N];
    r.obs_xy.resize(2 * sumK);
    r.obs_pt3d.resize(sumK);
    r.track.reserve(2 * sumK);
    std::vector<uint64_t> cursor(r.obs_off.begin(), r.obs_off.end());
    r.track_off.push_back(0);
    size_t kk = 0;  // running index into the flat meas_* arrays
    for (uint64_t j = 0; j < npts; ++j) {
        const uint64_t m = point_m[j];
        for (uint64_t e = 0; e < m; ++e) {
            const uint32_t img = meas_img[kk];
            const uint64_t slot = cursor[img]++;
            r.obs_xy[2 * slot] = meas_x[kk];
            r.obs_xy[2 * slot + 1] = meas_y[kk];
            r.obs_pt3d[slot] = static_cast<int64_t>(j + 1);  // pt id (never -1 on read)
            r.track.push_back(img + 1);                       // image_id (1-based)
            r.track.push_back(static_cast<uint32_t>(slot - r.obs_off[img]));  // re-based point2D_idx
            ++kk;
        }
        r.track_off.push_back(r.track.size() / 2);
    }

    // 5. TAIL (model list): another model's camera count, or the terminating 0.
    while (toks.next(tok)) {
        uint64_t n2 = 0;
        const auto res = std::from_chars(tok.data(), tok.data() + tok.size(), n2);
        if (res.ec != std::errc{} || res.ptr != tok.data() + tok.size())
            throw std::invalid_argument("NVM: trailing garbage after the model");
        if (n2 == 0) break;  // end-of-models terminator; the PLY section is ignored
        // VisualSFM's trailing "unregistered images" model: discard n2 cameras
        // (11 tokens each) and require 0 points; a real second model raises.
        for (uint64_t i = 0; i < n2; ++i)
            for (int t = 0; t < 11; ++t) toks.require("unregistered-model camera field");
        const uint64_t np2 = parse_uint<uint64_t>(toks.require("model point count"), "model point count");
        if (np2 != 0)
            throw std::invalid_argument(
                "NVM: multi-model NVM (a second reconstructed model with points) is not "
                "supported — split the file");
    }
}

// ---- writer (pure C++; construct nb::bytes only after the GIL is reacquired) -
void encode_nvm(const Reconstruction &r, std::string &out) {
    const size_t N = r.num_images();
    const size_t M = r.num_points();

    // GUARD (f): NVM cannot represent an observation without a 3D point. A
    // COLMAP-borne record is full of -1 sentinels; refuse rather than drop them.
    for (int64_t pid : r.obs_pt3d)
        if (pid < 0)
            throw std::invalid_argument(
                "NVM: observation without a 3D point (obs_pt3d == -1) cannot be represented — "
                "filter untriangulated observations first");

    std::unordered_map<uint32_t, size_t> cam_of;  // camera id -> index
    cam_of.reserve(r.cameras.size() * 2);
    for (size_t i = 0; i < r.cameras.size(); ++i) cam_of[r.cameras[i].id] = i;
    std::unordered_map<uint32_t, size_t> row_of;  // image id -> row (0-based)
    row_of.reserve(N * 2);
    for (size_t i = 0; i < N; ++i) row_of[r.img_ids[i]] = i;

    out.reserve(64 + N * 96 + M * 64 + (r.track.size() / 2) * 48);
    out += "NVM_V3\n";
    out += std::to_string(N);
    out += '\n';

    for (size_t i = 0; i < N; ++i) {
        const auto cit = cam_of.find(r.img_cam_ids[i]);
        if (cit == cam_of.end())
            throw std::invalid_argument("NVM: image " + std::to_string(r.img_ids[i]) +
                                        " references unknown camera id " +
                                        std::to_string(r.img_cam_ids[i]));
        const Camera &cam = r.cameras[cit->second];

        // (a) model must be SIMPLE_PINHOLE(0) or SIMPLE_RADIAL(2).
        if (cam.model_id != 0 && cam.model_id != 2)
            throw std::invalid_argument(
                std::string("NVM: camera model ") + colmap_model_info(cam.model_id).name +
                " is not representable — NVM stores a single focal + one radial coefficient; "
                "use SIMPLE_PINHOLE or SIMPLE_RADIAL (normalize first)");
        // (b) param count matches the model.
        const int nparams = colmap_model_info(cam.model_id).nparams;
        if (static_cast<int>(cam.params.size()) != nparams)
            throw std::invalid_argument("NVM: camera " + std::to_string(cam.id) + " has " +
                                        std::to_string(cam.params.size()) + " params, expected " +
                                        std::to_string(nparams));
        // (c) principal point must be at the image center (cx = cy = 0).
        if (cam.params[1] != 0.0 || cam.params[2] != 0.0)
            throw std::invalid_argument(
                "NVM: camera " + std::to_string(cam.id) +
                " has a non-zero principal point; NVM measurements are image-center-relative "
                "(cx = cy = 0) — normalize first");
        // (d) no image dimensions.
        if (cam.width != 0 || cam.height != 0)
            throw std::invalid_argument(
                "NVM: camera " + std::to_string(cam.id) +
                " has non-zero image dimensions; NVM cannot carry width/height — normalize first");
        // (e) filename token must be present and whitespace-free.
        const std::string &name = r.img_names[i];
        if (name.empty())
            throw std::invalid_argument("NVM: image " + std::to_string(r.img_ids[i]) +
                                        " has an empty name; NVM requires a filename token");
        for (char ch : name)
            if (is_ws(ch))
                throw std::invalid_argument(
                    "NVM: image name '" + name +
                    "' contains whitespace, which would corrupt the NVM token stream — "
                    "rename first (VisualSFM's '\"'-for-space escape is not applied)");

        out += name;
        out += ' ';
        append_f64(out, cam.params[0]);  // focal
        for (int k = 0; k < 4; ++k) {    // quaternion, WXYZ verbatim
            out += ' ';
            append_f64(out, r.quats[i * 4 + k]);
        }
        double R[9];
        quat_to_matrix(&r.quats[i * 4], R);
        const double *t = &r.trans[i * 3];
        for (int c = 0; c < 3; ++c) {  // camera center C = -R^T·t
            out += ' ';
            append_f64(out, -(R[0 * 3 + c] * t[0] + R[1 * 3 + c] * t[1] + R[2 * 3 + c] * t[2]));
        }
        out += ' ';
        if (cam.model_id == 2)
            append_f64(out, cam.params[3]);  // radial (verbatim)
        else
            out += '0';
        out += " 0\n";  // the placeholder terminator PBA parses and ignores
    }

    out += std::to_string(M);
    out += '\n';
    for (size_t j = 0; j < M; ++j) {
        for (int k = 0; k < 3; ++k) {
            if (k) out += ' ';
            append_f64(out, r.xyz[j * 3 + k]);
        }
        for (int k = 0; k < 3; ++k) {
            out += ' ';
            out += std::to_string(static_cast<unsigned>(r.rgb[j * 3 + k]));
        }
        const uint64_t a = r.track_off[j], e = r.track_off[j + 1];
        out += ' ';
        out += std::to_string(e - a);  // #measurements
        for (uint64_t pr = a; pr < e; ++pr) {
            const uint32_t img_id = r.track[2 * pr];
            const uint32_t p2d = r.track[2 * pr + 1];
            const auto rit = row_of.find(img_id);
            if (rit == row_of.end())
                throw std::invalid_argument("NVM: track references unknown image id " +
                                            std::to_string(img_id));
            const size_t row = rit->second;
            const uint64_t obs_cnt = r.obs_off[row + 1] - r.obs_off[row];
            if (p2d >= obs_cnt)
                throw std::invalid_argument("NVM: track point2D index " + std::to_string(p2d) +
                                            " out of range for image " + std::to_string(img_id));
            const uint64_t slot = r.obs_off[row] + p2d;
            out += ' ';
            out += std::to_string(row);  // NVM references images by 0-based LIST INDEX
            out += ' ';
            out += std::to_string(p2d);  // feature index := the compact point2D idx
            out += ' ';
            append_f64(out, r.obs_xy[2 * slot]);
            out += ' ';
            append_f64(out, r.obs_xy[2 * slot + 1]);
        }
        out += '\n';
    }
    out += "0\n";  // minimal spec-valid model-list terminator
}

Reconstruction read_nvm(nb::bytes data) {
    const char *p = data.c_str();  // grab the buffer while the GIL is held
    const size_t n = data.size();
    Reconstruction r;
    {
        nb::gil_scoped_release rel;  // pure-C++ parse; `data` stays alive for the call
        decode_nvm(p, n, r);
    }
    return r;  // nanobind converts to the Python Reconstruction with the GIL re-held
}

nb::bytes write_nvm(const Reconstruction &r) {
    std::string out;
    {
        nb::gil_scoped_release rel;  // pure-C++ encode; no Python objects touched
        encode_nvm(r, out);
    }
    return nb::bytes(out.data(), out.size());
}

}  // namespace

void register_nvm(nb::module_ &m) {
    m.def("read_nvm", &read_nvm, "data"_a,
          "Decode VisualSFM NVM_V3 bytes into a Reconstruction. The NVM quaternion is the WXYZ "
          "world_to_camera rotation (== COLMAP qvec, stored verbatim); NVM stores the camera "
          "center C, so the translation is derived t = -R*C. Measurements are image-center-relative, "
          "so cameras get width=height=cx=cy=0 and obs are stored verbatim in that frame. radial==0 "
          "-> SIMPLE_PINHOLE {f,0,0}, else SIMPLE_RADIAL {f,0,0,r} (r verbatim). err is set to -1 "
          "(no NVM field); ids are synthesized 1-based; NVM feature indices are re-based to compact "
          "per-image observation indices. NVM_V3_R9T, FixedK, and true multi-model files are refused; "
          "a trailing unregistered-images model and the PLY section are ignored.");
    m.def("write_nvm", &write_nvm, "recon"_a,
          "Encode a Reconstruction as VisualSFM NVM_V3 bytes (%.17g doubles, LF endings, camera "
          "center C = -R^T*t). Guards a record NVM cannot represent rather than mislabeling it: "
          "only SIMPLE_PINHOLE/SIMPLE_RADIAL cameras, principal point cx=cy=0, width=height=0, "
          "whitespace-free non-empty names, and no untriangulated (obs_pt3d == -1) observations.");
}
