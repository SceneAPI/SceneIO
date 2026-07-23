// codecs/bundler.cpp — Bundler v0.3 `.out` sparse-model reader/writer into the
// SAME Reconstruction record as colmap.cpp / colmap_txt.cpp (WXYZ quaternions,
// world->camera pose, model-tagged params[], per-image CSR observations,
// points3D tracks). The text sibling of colmap_txt.cpp: single pointer pass,
// fast_float::from_chars for doubles (portable across every wheel toolchain —
// std::from_chars<double> is absent on manylinux2014 GCC-10 / older libc++),
// std::from_chars for integers (complete everywhere), the GIL released around
// the pure-C++ decode/encode body (npy_npz/xyz precedent — every helper is
// Python-free; nb objects are built only outside the release scope).
//
// GRAMMAR (Noah Snavely's Bundler v0.3, bundler.io). Line 1 is EXACTLY
// `# Bundle file v0.3` (SIGNIFICANT — a '#' anywhere after it is a parse error,
// not a comment). Everything after the first newline is a pure whitespace-
// delimited TOKEN stream (Bundler's own ReadBundleFile uses fscanf, so physical
// line boundaries carry no meaning; this also gives CRLF tolerance for free):
//     <num_cameras> <num_points>
//   then per camera, 15 numbers:  f k1 k2 / R00 R01 R02 / R10 R11 R12 /
//                                 R20 R21 R22 / t0 t1 t2
//   then per point:  x y z / r g b (ints 0..255) / m  (cam key x y) * m
//
// FRAME CONVERSION (the load-bearing math; documented here verbatim).
// Bundler's camera model is `P = R_b·X + t_b` (world->camera) with an
// OpenGL-style camera frame: +X right, +Y up, +Z BACKWARD (the camera looks
// down -Z). Its projection is `p = -P / P.z`, `p' = f · r(p) · p`, with
// `r(p) = 1 + k1·|p|^2 + k2·|p|^4`, f in pixels. The Reconstruction record's
// canonical frame is COLMAP's: +Z forward, +Y down. With F = diag(1,-1,-1)
// (its own inverse), `X_colmap_cam = F·X_bundler_cam`, hence:
//   READ:   R' = F·R_b (negate rows 2 and 3), t' = F·t_b (negate t[1], t[2]);
//           q_wxyz = matrix_to_quat(R') -> quats/trans.
//   WRITE:  R_b = F·quat_to_matrix(q), t_b = F·t  — the identical negation.
// 2D: a Bundler view-list pixel (x_b, y_b) is CENTER-origin, +Y UP. The COLMAP
// pixel (X, Y) (top-left origin, +Y down) relates by X = cx + x_b, Y = cy - y_b.
// The .out file carries NO width/height/cx/cy, so the reader stores
// obs = (x_b, -y_b) with cx = cy = 0 cameras — exactly COLMAP's projection of
// the flipped pose (under F, x_n' = x_n and y_n' = -y_n, and r(p) is the same
// polynomial as COLMAP SIMPLE_RADIAL/RADIAL, so the intrinsic mapping is exact).
// The writer emits (X - cx, cy - Y) using each image's camera — COLMAP's own
// ExportBundler formula — so foreign records with a real principal point export
// correctly and our own read->write round-trips bit-exact.
//
// LOSSY EDGES (documented; enforced): Bundler focal f + k1[,k2] map to COLMAP
// SIMPLE_RADIAL {f,0,0,k1} (k2==0) or RADIAL {f,0,0,k1,k2} (k2!=0) — identical
// distortion polynomial, lossless; width=height=0 (no dimensions in the format).
// SIFT keypoint indices in the view list are NOT representable (point2D_idx is
// CSR-positional) — parsed for stream integrity then renumbered to the compact
// per-image observation index (files we wrote round-trip keys exactly; foreign
// files renumber on read->write, geometry identical). err = -1 (COLMAP's
// not-computed sentinel; the format has no per-point error). Image names live in
// the sibling list.txt (out of scope) -> "". All-zero 15-number camera blocks
// are Bundler's UNREGISTERED-image marker: skipped (no camera/image row) with
// ids preserving 1-based file position; a view list referencing one raises, and
// such a file re-writes COMPACTED (fully-registered files round-trip exactly).
//
// Doubles are written with "%.17g" (round-trips every IEEE-754 double through
// fast_float), LF-only line endings, single-space separators. Malformed input
// raises std::invalid_argument (mapped to ValueError -> FormatError by the io
// layer) and never crashes: from_chars is end-pointer bounded, header counts are
// byte-budget capped before any reservation, and the parse loops die fast at EOF
// via require-token.
#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
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

// ---- rotation <-> quaternion (WXYZ) — verbatim copy of transforms_json.cpp's
// normalized Shepperd pair (stable on every trace branch). House precedent is a
// private per-codec copy (pose_text.cpp, transforms_json.cpp each carry one); do
// NOT refactor a shared header in this change. -----------------------------
void quat_to_matrix(const double q[4], double R[9]) {
    double w = q[0], x = q[1], y = q[2], z = q[3];
    const double n = std::sqrt(w * w + x * x + y * y + z * z);
    if (n > 0.0) { w /= n; x /= n; y /= n; z /= n; }
    R[0] = 1.0 - 2.0 * (y * y + z * z); R[1] = 2.0 * (x * y - w * z);       R[2] = 2.0 * (x * z + w * y);
    R[3] = 2.0 * (x * y + w * z);       R[4] = 1.0 - 2.0 * (x * x + z * z); R[5] = 2.0 * (y * z - w * x);
    R[6] = 2.0 * (x * z - w * y);       R[7] = 2.0 * (y * z + w * x);       R[8] = 1.0 - 2.0 * (x * x + y * y);
}

void matrix_to_quat(const double R[9], double q[4]) {
    const double m00 = R[0], m01 = R[1], m02 = R[2];
    const double m10 = R[3], m11 = R[4], m12 = R[5];
    const double m20 = R[6], m21 = R[7], m22 = R[8];
    const double tr = m00 + m11 + m22;
    double w, x, y, z;
    if (tr > 0.0) {
        const double s = std::sqrt(tr + 1.0) * 2.0;
        w = 0.25 * s; x = (m21 - m12) / s; y = (m02 - m20) / s; z = (m10 - m01) / s;
    } else if (m00 > m11 && m00 > m22) {
        const double s = std::sqrt(1.0 + m00 - m11 - m22) * 2.0;
        w = (m21 - m12) / s; x = 0.25 * s; y = (m01 + m10) / s; z = (m02 + m20) / s;
    } else if (m11 > m22) {
        const double s = std::sqrt(1.0 + m11 - m00 - m22) * 2.0;
        w = (m02 - m20) / s; x = (m01 + m10) / s; y = 0.25 * s; z = (m12 + m21) / s;
    } else {
        const double s = std::sqrt(1.0 + m22 - m00 - m11) * 2.0;
        w = (m10 - m01) / s; x = (m02 + m20) / s; y = (m12 + m21) / s; z = 0.25 * s;
    }
    const double n = std::sqrt(w * w + x * x + y * y + z * z);
    if (n > 0.0) { w /= n; x /= n; y /= n; z /= n; }
    q[0] = w; q[1] = x; q[2] = y; q[3] = z;
}

// ---- token stream over the post-header bytes (fscanf-equivalent) -----------
inline bool is_ws(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

struct Toks {
    const char *p, *end;
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
        if (!next(t)) throw std::invalid_argument(std::string("Bundler: missing field ") + what);
        return t;
    }
};

// Bound a hostile token echoed into an error message (xyz.cpp precedent).
std::string bound_tok(std::string_view t) {
    const size_t len = std::min<size_t>(t.size(), 40);
    std::string shown(t.data(), len);
    if (t.size() > len) shown += "...";
    return shown;
}

double f64(std::string_view t, const char *what) {
    double v = 0.0;
    const auto r = fast_float::from_chars(t.data(), t.data() + t.size(), v);
    if (r.ec != std::errc{} || r.ptr != t.data() + t.size())
        throw std::invalid_argument(std::string("Bundler: bad number for ") + what + " '" +
                                    bound_tok(t) + "'");
    return v;
}
template <typename T>
T uint_(std::string_view t, const char *what) {
    T v = 0;
    const auto r = std::from_chars(t.data(), t.data() + t.size(), v);
    if (r.ec != std::errc{} || r.ptr != t.data() + t.size())
        throw std::invalid_argument(std::string("Bundler: bad integer for ") + what + " '" +
                                    bound_tok(t) + "'");
    return v;
}

// "%.17g" == COLMAP's ostream precision(17): round-trips every double exactly
// through fast_float (colmap_txt::fmt17 copy; non-finite handling is out of
// scope — Bundler poses come from quat->matrix and are finite for finite input).
void fmt17(std::string &out, double v) {
    if (v == 0.0) v = 0.0;  // normalize -0.0 (from the diag(1,-1,-1) flip) to "0"
    char buf[64];
    const int len = std::snprintf(buf, sizeof(buf), "%.17g", v);
    out.append(buf, static_cast<size_t>(len));
}

// ============================ READER =======================================
void decode(const char *p, size_t n, Reconstruction &r) {
    // -- header: line 1 must be EXACTLY "# Bundle file v0.3" (trailing CR and
    //    spaces tolerated). A "# Bundle file <other>" is a version error. --
    const char *nl = static_cast<const char *>(std::memchr(p, '\n', n));
    size_t hlen = nl ? static_cast<size_t>(nl - p) : n;
    if (hlen && p[hlen - 1] == '\r') --hlen;
    while (hlen && (p[hlen - 1] == ' ' || p[hlen - 1] == '\t')) --hlen;
    const std::string_view header(p, hlen);
    const std::string_view kHdr = "# Bundle file v0.3";
    const std::string_view kPfx = "# Bundle file";
    if (header != kHdr) {
        if (header.size() >= kPfx.size() && header.substr(0, kPfx.size()) == kPfx)
            throw std::invalid_argument("Bundler: unsupported Bundle file version (only v0.3)");
        throw std::invalid_argument("Bundler: missing '# Bundle file v0.3' header");
    }
    Toks tk{nl ? nl + 1 : p + n, p + n};

    // -- counts + byte-budget bomb guard (a camera is >=15 tokens => >=29 bytes,
    //    a point >=7 tokens => >=13 bytes; never reserve from an unchecked count).
    const uint64_t ncam = uint_<uint64_t>(tk.require("num_cameras"), "num_cameras");
    const uint64_t npts = uint_<uint64_t>(tk.require("num_points"), "num_points");
    if (ncam > 0xFFFFFFFEull)  // ids are uint32(i+1)
        throw std::invalid_argument("Bundler: declared camera count is too large");
    if (ncam > n / 29 + 1 || npts > n / 13 + 1)
        throw std::invalid_argument("Bundler: declared counts exceed file size");

    r.cameras.reserve(static_cast<size_t>(ncam));
    r.img_ids.reserve(static_cast<size_t>(ncam));
    r.img_cam_ids.reserve(static_cast<size_t>(ncam));
    r.img_names.reserve(static_cast<size_t>(ncam));
    r.quats.reserve(static_cast<size_t>(ncam) * 4);
    r.trans.reserve(static_cast<size_t>(ncam) * 3);
    r.xyz.reserve(static_cast<size_t>(npts) * 3);
    r.rgb.reserve(static_cast<size_t>(npts) * 3);
    r.err.reserve(static_cast<size_t>(npts));
    r.pt_ids.reserve(static_cast<size_t>(npts));

    // -- cameras: 15 doubles each. All-zero block == unregistered image (skip,
    //    record SIZE_MAX in row_of so a later view-list reference raises). --
    std::vector<size_t> row_of(static_cast<size_t>(ncam), SIZE_MAX);
    for (uint64_t i = 0; i < ncam; ++i) {
        const double f = f64(tk.require("focal length"), "focal length");
        const double k1 = f64(tk.require("radial k1"), "radial k1");
        const double k2 = f64(tk.require("radial k2"), "radial k2");
        double Rb[9];
        for (int k = 0; k < 9; ++k) Rb[k] = f64(tk.require("rotation matrix"), "rotation matrix");
        double tb[3];
        for (int k = 0; k < 3; ++k) tb[k] = f64(tk.require("translation"), "translation");

        bool all_zero = (f == 0.0 && k1 == 0.0 && k2 == 0.0);
        if (all_zero)
            for (int k = 0; k < 9 && all_zero; ++k)
                if (Rb[k] != 0.0) all_zero = false;
        if (all_zero)
            for (int k = 0; k < 3 && all_zero; ++k)
                if (tb[k] != 0.0) all_zero = false;
        if (all_zero) {
            row_of[static_cast<size_t>(i)] = SIZE_MAX;  // unregistered
            continue;
        }
        if (f == 0.0)
            throw std::invalid_argument("Bundler: camera " + std::to_string(i) +
                                        " has zero focal length");

        row_of[static_cast<size_t>(i)] = r.img_ids.size();
        Camera c;
        c.id = static_cast<uint32_t>(i + 1);
        c.model_id = (k2 == 0.0) ? 2 /*SIMPLE_RADIAL*/ : 3 /*RADIAL*/;
        c.width = 0;
        c.height = 0;
        if (k2 == 0.0) c.params = {f, 0.0, 0.0, k1};
        else c.params = {f, 0.0, 0.0, k1, k2};
        r.cameras.push_back(std::move(c));
        r.img_ids.push_back(static_cast<uint32_t>(i + 1));
        r.img_cam_ids.push_back(static_cast<uint32_t>(i + 1));  // one camera per image
        r.img_names.emplace_back();                             // names live in list.txt

        // R' = F·R_b (rows 2,3 negated); q = Shepperd(R'); t' = F·t_b.
        double Rp[9] = {Rb[0],  Rb[1],  Rb[2],  -Rb[3], -Rb[4],
                        -Rb[5], -Rb[6], -Rb[7], -Rb[8]};
        double q[4];
        matrix_to_quat(Rp, q);
        r.quats.insert(r.quats.end(), {q[0], q[1], q[2], q[3]});
        r.trans.insert(r.trans.end(), {tb[0], -tb[1], -tb[2]});
    }

    const size_t N = r.img_ids.size();

    // -- points + view lists. View lists are grouped by POINT but the record's
    //    obs are per-IMAGE CSR, so buffer flat then bucket (two passes). --
    std::vector<uint64_t> per_img_count(N, 0);
    std::vector<size_t> v_row;    // entry -> image row
    std::vector<double> v_xy;     // 2*entries (already flipped to (x,-y))
    std::vector<uint32_t> v_ptm;  // per-point entry count
    v_ptm.reserve(static_cast<size_t>(npts));
    for (uint64_t j = 0; j < npts; ++j) {
        r.pt_ids.push_back(j + 1);  // 1-based, like image ids
        for (int k = 0; k < 3; ++k) r.xyz.push_back(f64(tk.require("point xyz"), "point coordinate"));
        for (int k = 0; k < 3; ++k) {
            const uint32_t v = uint_<uint32_t>(tk.require("point color"), "color component");
            if (v > 255)
                throw std::invalid_argument("Bundler: RGB component out of range 0..255");
            r.rgb.push_back(static_cast<uint8_t>(v));
        }
        r.err.push_back(-1.0);  // format carries no reprojection error

        const uint32_t m = uint_<uint32_t>(tk.require("view-list length"), "view-list length");
        for (uint32_t e = 0; e < m; ++e) {
            const uint32_t cam = uint_<uint32_t>(tk.require("view-list camera"), "view-list camera index");
            if (cam >= ncam)
                throw std::invalid_argument("Bundler: view list camera index out of range");
            const size_t row = row_of[cam];
            if (row == SIZE_MAX)
                throw std::invalid_argument("Bundler: view list references unregistered camera");
            (void)uint_<uint32_t>(tk.require("view-list key"), "view-list key");  // SIFT key discarded
            const double x = f64(tk.require("view-list x"), "view-list x");
            const double y = f64(tk.require("view-list y"), "view-list y");
            v_row.push_back(row);
            v_xy.push_back(x);
            v_xy.push_back(-y);  // center-origin y-up -> COLMAP pixel (cx=cy=0)
            ++per_img_count[row];
        }
        v_ptm.push_back(m);
    }
    std::string_view extra;
    if (tk.next(extra)) throw std::invalid_argument("Bundler: trailing data after last point");

    // -- CSR build: obs grouped by image (ordered by point then view-list
    //    position); tracks in file order with the compact per-image index. --
    r.obs_off.assign(N + 1, 0);
    for (size_t i = 0; i < N; ++i) r.obs_off[i + 1] = r.obs_off[i] + per_img_count[i];
    const size_t total = static_cast<size_t>(r.obs_off[N]);
    r.obs_xy.assign(total * 2, 0.0);
    r.obs_pt3d.assign(total, -1);
    std::vector<uint64_t> cursor(r.obs_off.begin(), r.obs_off.end());
    r.track_off.push_back(0);
    size_t eidx = 0;
    for (uint64_t j = 0; j < npts; ++j) {
        const uint32_t m = v_ptm[static_cast<size_t>(j)];
        for (uint32_t e = 0; e < m; ++e) {
            const size_t row = v_row[eidx];
            const uint64_t slot = cursor[row]++;
            r.obs_xy[slot * 2] = v_xy[eidx * 2];
            r.obs_xy[slot * 2 + 1] = v_xy[eidx * 2 + 1];
            r.obs_pt3d[slot] = static_cast<int64_t>(j + 1);
            const uint32_t local = static_cast<uint32_t>(slot - r.obs_off[row]);
            r.track.push_back(r.img_ids[row]);
            r.track.push_back(local);
            ++eidx;
        }
        r.track_off.push_back(r.track.size() / 2);
    }
}

Reconstruction read_bundler(nb::bytes data) {
    const char *p = data.c_str();  // grab the buffer while the GIL is held
    const size_t n = data.size();
    Reconstruction r;
    {
        nb::gil_scoped_release rel;  // pure-C++ parse; `data` stays alive for the call
        decode(p, n, r);
    }
    return r;  // nanobind converts to the Python Reconstruction with the GIL re-held
}

// ============================ WRITER =======================================
// Resolve a COLMAP Camera to Bundler intrinsics (f, k1, k2) + its principal
// point (cx, cy). Refuses a record it cannot represent rather than silently
// converting (the xyz/netpbm/transforms_json refuse-not-convert rule).
void resolve_camera(const Camera &c, double &f, double &k1, double &k2, double &cx, double &cy) {
    const ModelInfo mi = colmap_model_info(c.model_id);  // throws on unknown id (>10)
    if (c.model_id > 3)
        throw std::invalid_argument(std::string("Bundler: camera model ") + mi.name +
                                    " is not representable");
    if (static_cast<int>(c.params.size()) != mi.nparams)
        throw std::invalid_argument("Bundler: camera " + std::to_string(c.id) + " has " +
                                    std::to_string(c.params.size()) + " params, expected " +
                                    std::to_string(mi.nparams) + " for model " + mi.name);
    switch (c.model_id) {
        case 0:  // SIMPLE_PINHOLE {f, cx, cy}
            f = c.params[0]; k1 = 0.0; k2 = 0.0; cx = c.params[1]; cy = c.params[2]; break;
        case 1:  // PINHOLE {fx, fy, cx, cy}
            if (c.params[0] != c.params[1])
                throw std::invalid_argument(
                    "Bundler: PINHOLE fx != fy is not representable (COLMAP averages; "
                    "normalize first)");
            f = c.params[0]; k1 = 0.0; k2 = 0.0; cx = c.params[2]; cy = c.params[3]; break;
        case 2:  // SIMPLE_RADIAL {f, cx, cy, k}
            f = c.params[0]; k1 = c.params[3]; k2 = 0.0; cx = c.params[1]; cy = c.params[2]; break;
        default:  // 3 == RADIAL {f, cx, cy, k1, k2}
            f = c.params[0]; k1 = c.params[3]; k2 = c.params[4]; cx = c.params[1]; cy = c.params[2];
            break;
    }
    if (!(f > 0.0))  // an f<=0 block would read back as unregistered (all-zero) or invalid
        throw std::invalid_argument("Bundler: camera " + std::to_string(c.id) +
                                    " has non-positive focal length");
}

void encode(const Reconstruction &r, std::string &out) {
    const size_t N = r.num_images();
    const size_t M = r.num_points();

    std::unordered_map<uint32_t, const Camera *> cam_by_id;
    cam_by_id.reserve(r.cameras.size() * 2);
    for (const auto &c : r.cameras) cam_by_id.emplace(c.id, &c);
    std::unordered_map<uint32_t, size_t> row_by_img;
    row_by_img.reserve(N * 2);
    for (size_t i = 0; i < N; ++i) row_by_img.emplace(r.img_ids[i], i);

    out.reserve(64 + N * 160 + M * 72 + (r.track.size() / 2) * 40);
    out += "# Bundle file v0.3\n";
    out += std::to_string(N);
    out += ' ';
    out += std::to_string(M);
    out += '\n';

    // Per-image camera blocks (record row order == Bundler camera index). Cache
    // each image's principal point for the point pass's obs emission.
    std::vector<double> img_cx(N), img_cy(N);
    for (size_t i = 0; i < N; ++i) {
        const uint32_t cid = r.img_cam_ids[i];
        const auto it = cam_by_id.find(cid);
        if (it == cam_by_id.end())
            throw std::invalid_argument("Bundler: image " + std::to_string(r.img_ids[i]) +
                                        " references unknown camera " + std::to_string(cid));
        double f, k1, k2, cx, cy;
        resolve_camera(*it->second, f, k1, k2, cx, cy);
        img_cx[i] = cx;
        img_cy[i] = cy;

        double q[4] = {r.quats[i * 4], r.quats[i * 4 + 1], r.quats[i * 4 + 2], r.quats[i * 4 + 3]};
        double R[9];
        quat_to_matrix(q, R);
        const double Rb[9] = {R[0],  R[1],  R[2],  -R[3], -R[4],
                              -R[5], -R[6], -R[7], -R[8]};  // R_b = F·R'
        const double tb[3] = {r.trans[i * 3], -r.trans[i * 3 + 1], -r.trans[i * 3 + 2]};

        fmt17(out, f); out += ' '; fmt17(out, k1); out += ' '; fmt17(out, k2); out += '\n';
        for (int row = 0; row < 3; ++row) {
            fmt17(out, Rb[row * 3 + 0]); out += ' ';
            fmt17(out, Rb[row * 3 + 1]); out += ' ';
            fmt17(out, Rb[row * 3 + 2]); out += '\n';
        }
        fmt17(out, tb[0]); out += ' '; fmt17(out, tb[1]); out += ' '; fmt17(out, tb[2]); out += '\n';
    }

    // Per-point position/color/view-list. The view list rebuilds Bundler's
    // (cam, key, x, y): camera index = the image's 0-based row, key = the
    // point2D_idx (our compact obs index), (x, y) = (obs_x - cx, cy - obs_y).
    for (size_t i = 0; i < M; ++i) {
        fmt17(out, r.xyz[i * 3]); out += ' ';
        fmt17(out, r.xyz[i * 3 + 1]); out += ' ';
        fmt17(out, r.xyz[i * 3 + 2]); out += '\n';
        out += std::to_string(static_cast<unsigned>(r.rgb[i * 3])); out += ' ';
        out += std::to_string(static_cast<unsigned>(r.rgb[i * 3 + 1])); out += ' ';
        out += std::to_string(static_cast<unsigned>(r.rgb[i * 3 + 2])); out += '\n';

        const uint64_t a = r.track_off[i], e = r.track_off[i + 1];
        out += std::to_string(e - a);  // m
        for (uint64_t j = a; j < e; ++j) {
            const uint32_t img_id = r.track[j * 2];
            const uint32_t p2d = r.track[j * 2 + 1];
            const auto it = row_by_img.find(img_id);
            if (it == row_by_img.end())
                throw std::invalid_argument("Bundler: track references unknown image id " +
                                            std::to_string(img_id));
            const size_t row = it->second;
            const uint64_t oa = r.obs_off[row], oe = r.obs_off[row + 1];
            if (p2d >= oe - oa)
                throw std::invalid_argument("Bundler: track references out-of-range observation");
            const uint64_t slot = oa + p2d;
            const double ox = r.obs_xy[slot * 2], oy = r.obs_xy[slot * 2 + 1];
            out += ' ';
            out += std::to_string(row);  // 0-based camera index
            out += ' ';
            out += std::to_string(p2d);  // key := point2D_idx
            out += ' ';
            fmt17(out, ox - img_cx[row]);
            out += ' ';
            fmt17(out, img_cy[row] - oy);
        }
        out += '\n';
    }
}

nb::bytes write_bundler(const Reconstruction &r) {
    std::string out;
    {
        nb::gil_scoped_release rel;  // pure-C++ encode; the record's C++ fields only
        encode(r, out);
    }
    return nb::bytes(out.data(), out.size());  // built with the GIL re-held
}

}  // namespace

void register_bundler(nb::module_ &m) {
    m.def("read_bundler", &read_bundler, "data"_a,
          "Decode Bundler v0.3 `.out` bytes into a Reconstruction (WXYZ quaternions, "
          "world_to_camera). Bundler poses are world->camera in an OpenGL-style camera frame "
          "(+Z backward), converted to COLMAP's +Z-forward frame with F = diag(1,-1,-1): rows 2 "
          "and 3 of R and t[1],t[2] are negated. Observations are stored (x, -y) in the "
          "center-origin frame with cx=cy=0, width=height=0 SIMPLE_RADIAL/RADIAL cameras "
          "({f,0,0,k1[,k2]}). All-zero (unregistered) camera blocks are skipped, keeping 1-based "
          "file-position ids; a view list referencing one raises. SIFT keypoint indices are "
          "renumbered to compact per-image observation indices; per-point error is set to -1; "
          "image names are empty (they live in the sibling list.txt).");
    m.def("write_bundler", &write_bundler, "recon"_a,
          "Encode a Reconstruction as Bundler v0.3 `.out` bytes (%.17g doubles, LF endings). "
          "Applies the identical diag(1,-1,-1) flip on write (R_b = F·R', t_b = F·t) and emits "
          "each observation as (X - cx, cy - Y) using its image's camera — COLMAP's own "
          "ExportBundler formula. Supported models: SIMPLE_PINHOLE, PINHOLE (requires fx==fy), "
          "SIMPLE_RADIAL, RADIAL; any other model, a non-positive focal, or a track referencing "
          "an unknown image / out-of-range observation raises. Per-point error, image names, "
          "cameras used by no image, and observations without a 3D point are dropped.");
}
