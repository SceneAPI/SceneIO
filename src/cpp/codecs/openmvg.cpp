// codecs/openmvg.cpp — OpenMVG sfm_data.json reader/writer into the shared
// Reconstruction record (records/reconstruction.hpp), a sibling of colmap_txt.cpp
// (record population order) + transforms_json.cpp (nlohmann usage) + xyz.cpp
// (nb::bytes + GIL discipline).
//
// FORMAT. sfm_data.json is a cereal JSON archive:
//   { "sfm_data_version": "0.3", "root_path": "...",
//     "views":       [ {"key": img_id,  "value": {"polymorphic_id":1073741824,
//                        "ptr_wrapper": {"id":.., "data": {local_path, filename,
//                        width, height, id_view, id_intrinsic, id_pose}}}} ],
//     "intrinsics":  [ {"key": cam_id,  "value": {"polymorphic_id":..,
//                        ["polymorphic_name": "pinhole..",] "ptr_wrapper":
//                        {"id":.., "data": {width, height, focal_length,
//                        principal_point:[ppx,ppy] [, disto_*: [...]]}}}} ],
//     "extrinsics":  [ {"key": pose_id, "value": {"rotation": [[..],[..],[..]],
//                        "center": [cx,cy,cz]}} ],
//     "structure":   [ {"key": pt_id,   "value": {"X":[x,y,z], "observations":
//                        [ {"key": img_id, "value": {"id_feat":.., "x":[u,v]}} ]}} ],
//     "control_points": [] }
// The maps are serialized as arrays of {key,value} pairs (JSON keys must be
// strings; cereal keeps them separate). views/intrinsics/extrinsics are required;
// structure is optional (absent -> zero points). Cereal wrappers: an intrinsic's
// polymorphic *type* is named on first occurrence (polymorphic_id has its msb
// 0x80000000 set and a polymorphic_name is present) and back-referenced by the
// bare id afterwards; the non-polymorphic View pointer uses the fixed marker
// 0x40000000 = 1073741824 (ignored). A ptr_wrapper "data" is the object payload;
// a cereal shared back-reference (id without data) is unsupported and raises.
//
// POSE MATH (pure reparameterization — OpenMVG's camera axes are the COLMAP/OpenCV
// ones: +x right, +y down, +z forward, so NO axis flip). geometry::Pose3 stores a
// row-major world_to_camera rotation R and a camera CENTER C in world coordinates;
// projection is X_cam = R*(X_world - C), i.e. the record's translation is t = -R*C.
//   READ:  q_wxyz = shepperd(R) (renormalized, raw sign — COLMAP double-cover
//          tolerance); t[r] = -(R[r0]*C0 + R[r1]*C1 + R[r2]*C2) left-to-right.
//   WRITE: R = quat_to_matrix(q); C[c] = -(R[0c]*t0 + R[1c]*t1 + R[2c]*t2) (= -R^T t).
// The fixed left-to-right association is contractual so the scalar Python test
// oracle matches bit-for-bit on non-FMA codegen.
//
// INTRINSICS (focal + principal point in pixels; OpenMVG has a single focal f).
//   read:  pinhole            -> SIMPLE_PINHOLE(0) {f,ppx,ppy}
//          pinhole_radial_k1  -> SIMPLE_RADIAL(2)  {f,ppx,ppy,k1}
//          pinhole_radial_k3  -> FULL_OPENCV(6)    {f,f,ppx,ppy,k1,k2,0,0,k3,0,0,0}
//          pinhole_brown_t2   -> FULL_OPENCV(6)    {f,f,ppx,ppy,k1,k2,t1,t2,k3,0,0,0}
//          fisheye            -> OPENCV_FISHEYE(5) {f,f,ppx,ppy,k1,k2,k3,k4}
//   write: the exact inverse plus guards (PINHOLE/OPENCV/OPENCV_FISHEYE/FULL_OPENCV
//          require fx==fy; FULL_OPENCV requires k4=k5=k6=0; RADIAL -> radial_k3 with
//          k3=0; FOV / *_FISHEYE-simple / THIN_PRISM -> refused). The model-id
//          asymmetry across a write+read hop (RADIAL->radial_k3->FULL_OPENCV,
//          PINHOLE fx==fy -> pinhole -> SIMPLE_PINHOLE) is value-exact and documented.
//
// LOSSY, by design (documented, not silent surprises): read fills rgb={0,0,0}
// (sfm_data.json landmarks carry no color) and err=-1.0 (no reprojection error;
// COLMAP's unknown-error sentinel), and drops root_path, per-view width/height,
// pose ids, the observation id_feat (a VisualSFM/OpenMVG feature-file index, not
// representable — the writer re-emits the compact per-image POINT2D_IDX in its
// place), view_priors extras and control_points. write drops rgb/err and every
// observation whose obs_pt3d == -1 (untriangulated 2D point — not representable),
// and remaps model ids as noted above (values exact).
//
// PORTABILITY: numeric parsing is entirely nlohmann's (portable everywhere), so
// this codec needs no fast_float (the roadmap's fast_float rule targets
// hand-rolled text parsers). The pure-C++ decode/encode runs with the GIL released
// (xyz.cpp precedent); nb objects are only touched outside that scope. Every
// malformed/missing-key condition raises std::invalid_argument (prefixed
// "OpenMVG sfm_data: ") -> Python ValueError -> FormatError at the io layer; the
// whole reader body is wrapped so nlohmann's own type/parse errors surface as
// ValueError too, and every integer field goes through a range-checked helper
// (nlohmann's get<unsigned> silently wraps negatives).
#include <nlohmann/json.hpp>

#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "records/reconstruction.hpp"

using namespace nb::literals;
using namespace sio;
using json = nlohmann::ordered_json;

namespace {

// --- rotation <-> quaternion (WXYZ) ----------------------------------------
// Local copies of transforms_json.cpp's normalized Shepperd pair (house
// precedent: pose_text.cpp and transforms_json.cpp each carry their own private
// copy; lifting these into a shared io/ header is an integrator concern and out
// of scope for this file, whose task edits only openmvg.cpp). Kept byte-identical
// to transforms_json.cpp so the branch-mirroring Python test oracle stays valid.
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

// --- error + JSON access helpers -------------------------------------------
[[noreturn]] void bad(const std::string &msg) {
    throw std::invalid_argument("OpenMVG sfm_data: " + msg);
}

const json &member(const json &o, const char *k, const char *ctx) {
    if (!o.is_object()) bad(std::string("expected an object for ") + ctx);
    const auto it = o.find(k);
    if (it == o.end()) bad(std::string("missing '") + k + "' in " + ctx);
    return *it;
}

double get_f64(const json &v, const char *what) {
    if (!v.is_number()) bad(std::string("field ") + what + " must be a number");
    return v.get<double>();
}

// Require an integer; return it as int64, rejecting values that don't fit int64
// (nlohmann stores big positives as unsigned and get<int64> would wrap).
int64_t get_i64(const json &v, const char *what) {
    if (!v.is_number_integer()) bad(std::string("field ") + what + " must be an integer");
    if (v.is_number_unsigned()) {
        const uint64_t u = v.get<uint64_t>();
        if (u > static_cast<uint64_t>(INT64_MAX))
            bad(std::string("field ") + what + " out of int64 range");
        return static_cast<int64_t>(u);
    }
    return v.get<int64_t>();
}

uint32_t get_u32(const json &v, const char *what) {
    const int64_t x = get_i64(v, what);
    if (x < 0 || x > static_cast<int64_t>(UINT32_MAX))
        bad(std::string("field ") + what + " out of uint32 range");
    return static_cast<uint32_t>(x);
}

uint64_t get_u64(const json &v, const char *what) {
    const int64_t x = get_i64(v, what);  // rejects > INT64_MAX and non-integers
    if (x < 0) bad(std::string("field ") + what + " must be non-negative");
    return static_cast<uint64_t>(x);
}

// Require an array of exactly `len` elements; returns it for element access.
const json &fixed_array(const json &v, size_t len, const char *what) {
    if (!v.is_array() || v.size() != len)
        bad(std::string("field ") + what + " must be an array of length " + std::to_string(len));
    return v;
}

// cereal ptr_wrapper payload: value.ptr_wrapper.data (a back-reference, i.e. an
// id with no data, is unsupported and surfaces as "missing 'data'").
const json &unwrap_ptr(const json &value, const char *ctx) {
    const json &pw = member(value, "ptr_wrapper", ctx);
    return member(pw, "data", ctx);
}

// Resolve an intrinsic entry's cereal polymorphic type name, maintaining the
// first-occurrence registry (msb-flagged id introduces a name; a bare id
// back-references it).
std::string resolve_poly(const json &value, std::unordered_map<uint32_t, std::string> &by_id,
                         const char *ctx) {
    const auto nit = value.find("polymorphic_name");
    const auto pit = value.find("polymorphic_id");
    if (nit != value.end() && nit->is_string()) {
        std::string name = nit->get<std::string>();
        if (pit != value.end() && pit->is_number_integer())
            by_id[get_u32(*pit, "polymorphic_id") & 0x7fffffffu] = name;
        return name;
    }
    if (pit != value.end() && pit->is_number_integer()) {
        const auto f = by_id.find(get_u32(*pit, "polymorphic_id") & 0x7fffffffu);
        if (f != by_id.end()) return f->second;
    }
    bad(std::string("intrinsic ") + ctx + " has no polymorphic_name and no known polymorphic_id");
}

// --- reader: OpenMVG polymorphic name -> COLMAP model id + params ----------
void map_intrinsic(const std::string &name, const json &data, double f, double ppx, double ppy,
                   Camera &c) {
    if (name == "pinhole") {
        c.model_id = 0;
        c.params = {f, ppx, ppy};
    } else if (name == "pinhole_radial_k1") {
        const json &d = fixed_array(member(data, "disto_k1", "intrinsic"), 1, "disto_k1");
        c.model_id = 2;
        c.params = {f, ppx, ppy, get_f64(d[0], "disto_k1")};
    } else if (name == "pinhole_radial_k3") {
        const json &d = fixed_array(member(data, "disto_k3", "intrinsic"), 3, "disto_k3");
        const double k1 = get_f64(d[0], "disto_k3"), k2 = get_f64(d[1], "disto_k3"),
                     k3 = get_f64(d[2], "disto_k3");
        c.model_id = 6;  // FULL_OPENCV: 1 + k1 r^2 + k2 r^4 + k3 r^6, no tangential
        c.params = {f, f, ppx, ppy, k1, k2, 0.0, 0.0, k3, 0.0, 0.0, 0.0};
    } else if (name == "pinhole_brown_t2") {
        const json &d = fixed_array(member(data, "disto_t2", "intrinsic"), 5, "disto_t2");
        const double k1 = get_f64(d[0], "disto_t2"), k2 = get_f64(d[1], "disto_t2"),
                     k3 = get_f64(d[2], "disto_t2"), t1 = get_f64(d[3], "disto_t2"),
                     t2 = get_f64(d[4], "disto_t2");
        c.model_id = 6;  // Brown t2 == OpenCV {k1,k2,p1,p2,k3}
        c.params = {f, f, ppx, ppy, k1, k2, t1, t2, k3, 0.0, 0.0, 0.0};
    } else if (name == "fisheye") {
        const json &d = fixed_array(member(data, "fisheye", "intrinsic"), 4, "fisheye");
        const double k1 = get_f64(d[0], "fisheye"), k2 = get_f64(d[1], "fisheye"),
                     k3 = get_f64(d[2], "fisheye"), k4 = get_f64(d[3], "fisheye");
        c.model_id = 5;  // OPENCV_FISHEYE equidistant polynomial
        c.params = {f, f, ppx, ppy, k1, k2, k3, k4};
    } else {
        bad("intrinsic polymorphic_name '" + name +
            "' is not supported (pinhole, pinhole_radial_k1, pinhole_radial_k3, "
            "pinhole_brown_t2, fisheye)");
    }
}

struct PoseQT {
    double q[4];
    double t[3];
};

void parse_sfm(const char *p, size_t n, Reconstruction &r) {
    try {
        const json d = json::parse(p, p + n);
        if (!d.is_object()) bad("root must be a JSON object");

        // 1. intrinsics -> cameras (array order) + known-id set --------------
        const json &intr = member(d, "intrinsics", "root");
        if (!intr.is_array()) bad("'intrinsics' must be an array");
        std::unordered_map<uint32_t, std::string> by_id;
        std::unordered_set<uint32_t> known_cams;
        r.cameras.reserve(intr.size());
        for (const json &e : intr) {
            const uint32_t cid = get_u32(member(e, "key", "intrinsic entry"), "intrinsic key");
            const json &v = member(e, "value", "intrinsic entry");
            const std::string name = resolve_poly(v, by_id, std::to_string(cid).c_str());
            const json &data = unwrap_ptr(v, "intrinsic");
            Camera c;
            c.id = cid;
            c.width = get_u64(member(data, "width", "intrinsic"), "intrinsic width");
            c.height = get_u64(member(data, "height", "intrinsic"), "intrinsic height");
            const double f = get_f64(member(data, "focal_length", "intrinsic"), "focal_length");
            const json &pp =
                fixed_array(member(data, "principal_point", "intrinsic"), 2, "principal_point");
            map_intrinsic(name, data, f, get_f64(pp[0], "principal_point"),
                          get_f64(pp[1], "principal_point"), c);
            known_cams.insert(cid);
            r.cameras.push_back(std::move(c));
        }

        // 2. extrinsics -> pose map (rotation + center -> WXYZ q, t = -R*C) ---
        const json &extr = member(d, "extrinsics", "root");
        if (!extr.is_array()) bad("'extrinsics' must be an array");
        std::unordered_map<uint32_t, PoseQT> poses;
        poses.reserve(extr.size());
        for (const json &e : extr) {
            const uint32_t pid = get_u32(member(e, "key", "extrinsic entry"), "extrinsic key");
            const json &v = member(e, "value", "extrinsic entry");
            const json &rot = fixed_array(member(v, "rotation", "extrinsic"), 3, "rotation");
            double R[9];
            for (int i = 0; i < 3; i++) {
                const json &row = fixed_array(rot[static_cast<size_t>(i)], 3, "rotation row");
                for (int j = 0; j < 3; j++) R[i * 3 + j] = get_f64(row[static_cast<size_t>(j)], "rotation");
            }
            const json &ctr = fixed_array(member(v, "center", "extrinsic"), 3, "center");
            const double C0 = get_f64(ctr[0], "center"), C1 = get_f64(ctr[1], "center"),
                         C2 = get_f64(ctr[2], "center");
            PoseQT pq;
            matrix_to_quat(R, pq.q);
            for (int i = 0; i < 3; i++)
                pq.t[i] = -(R[i * 3 + 0] * C0 + R[i * 3 + 1] * C1 + R[i * 3 + 2] * C2);
            poses[pid] = pq;
        }

        // 3. views -> images (skip unreconstructed) + img_id -> row index ----
        const json &views = member(d, "views", "root");
        if (!views.is_array()) bad("'views' must be an array");
        std::unordered_map<uint32_t, size_t> img_index;
        r.img_ids.reserve(views.size());
        for (const json &e : views) {
            const uint32_t iid = get_u32(member(e, "key", "view entry"), "view key");
            const json &data = unwrap_ptr(member(e, "value", "view entry"), "view");
            const json &fn = member(data, "filename", "view");
            if (!fn.is_string()) bad("view filename must be a string");
            std::string filename = fn.get<std::string>();
            std::string local_path;
            const auto lit = data.find("local_path");
            if (lit != data.end() && lit->is_string()) local_path = lit->get<std::string>();
            const uint32_t id_intrinsic = get_u32(member(data, "id_intrinsic", "view"), "id_intrinsic");
            const uint32_t id_pose = get_u32(member(data, "id_pose", "view"), "id_pose");
            // UndefinedIndexT intrinsic or a pose absent from extrinsics -> the
            // view is not reconstructed (a normal OpenMVG state), skip it.
            if (id_intrinsic == 0xffffffffu) continue;
            const auto pose_it = poses.find(id_pose);
            if (pose_it == poses.end()) continue;
            if (!known_cams.count(id_intrinsic))
                bad("view " + std::to_string(iid) + " references missing intrinsic " +
                    std::to_string(id_intrinsic));
            img_index[iid] = r.img_ids.size();
            r.img_ids.push_back(iid);
            const PoseQT &pq = pose_it->second;
            r.quats.insert(r.quats.end(), {pq.q[0], pq.q[1], pq.q[2], pq.q[3]});
            r.trans.insert(r.trans.end(), {pq.t[0], pq.t[1], pq.t[2]});
            r.img_cam_ids.push_back(id_intrinsic);
            r.img_names.push_back(local_path.empty() ? filename : local_path + "/" + filename);
        }
        const size_t N = r.img_ids.size();

        // 4. structure -> points3D + per-image observation CSR + tracks ------
        //    Two passes: count per image, prefix-sum into obs_off, then scatter.
        const auto sit = d.find("structure");
        const bool has_structure = sit != d.end() && !sit->is_null();
        if (has_structure && !sit->is_array()) bad("'structure' must be an array");

        std::vector<uint64_t> count(N, 0);
        if (has_structure) {
            for (const json &lm : *sit) {
                const json &obs = member(member(lm, "value", "structure entry"), "observations",
                                         "landmark");
                if (!obs.is_array()) bad("landmark 'observations' must be an array");
                for (const json &ob : obs) {
                    const uint32_t vk =
                        get_u32(member(ob, "key", "observation entry"), "observation view key");
                    const auto f = img_index.find(vk);
                    if (f == img_index.end())
                        bad("observation references view " + std::to_string(vk) +
                            " which is not a posed view");
                    count[f->second]++;
                }
            }
        }
        r.obs_off.resize(N + 1);
        r.obs_off[0] = 0;
        for (size_t i = 0; i < N; i++) r.obs_off[i + 1] = r.obs_off[i] + count[i];
        const uint64_t total_obs = r.obs_off[N];
        r.obs_xy.resize(2 * total_obs);
        r.obs_pt3d.resize(total_obs);
        std::vector<uint64_t> cursor(r.obs_off.begin(), r.obs_off.end());
        r.track_off.push_back(0);

        if (has_structure) {
            r.pt_ids.reserve(sit->size());
            for (const json &lm : *sit) {
                const int64_t pid_i = get_i64(member(lm, "key", "structure entry"), "structure key");
                if (pid_i < 0) bad("structure key must be non-negative");
                const json &v = member(lm, "value", "structure entry");
                const json &X = fixed_array(member(v, "X", "landmark"), 3, "landmark X");
                r.pt_ids.push_back(static_cast<uint64_t>(pid_i));
                r.xyz.insert(r.xyz.end(),
                             {get_f64(X[0], "landmark X"), get_f64(X[1], "landmark X"),
                              get_f64(X[2], "landmark X")});
                r.rgb.push_back(0);  // sfm_data.json landmarks carry no color
                r.rgb.push_back(0);
                r.rgb.push_back(0);
                r.err.push_back(-1.0);
                const json &obs = member(v, "observations", "landmark");
                for (const json &ob : obs) {
                    const uint32_t vk =
                        get_u32(member(ob, "key", "observation entry"), "observation view key");
                    const json &x = fixed_array(
                        member(member(ob, "value", "observation entry"), "x", "observation"), 2,
                        "observation x");
                    const auto f = img_index.find(vk);
                    if (f == img_index.end())
                        bad("observation references view " + std::to_string(vk) +
                            " which is not a posed view");
                    const size_t idx = f->second;
                    const uint64_t slot = cursor[idx]++;
                    r.obs_xy[2 * slot] = get_f64(x[0], "observation x");
                    r.obs_xy[2 * slot + 1] = get_f64(x[1], "observation x");
                    r.obs_pt3d[slot] = static_cast<int64_t>(pid_i);
                    r.track.push_back(vk);
                    r.track.push_back(static_cast<uint32_t>(slot - r.obs_off[idx]));
                }
                r.track_off.push_back(r.track.size() / 2);
            }
        }
    } catch (const json::exception &e) {
        // nlohmann parse/type errors surface as ValueError too (bad() throws
        // std::invalid_argument, which is not a json::exception, so our own
        // messages propagate untouched).
        bad(e.what());
    }
}

Reconstruction read_openmvg(nb::bytes data) {
    const char *p = data.c_str();  // grabbed with the GIL held; `data` stays alive
    const size_t n = data.size();
    Reconstruction r;
    {
        nb::gil_scoped_release rel;  // pure-C++ parse, no Python objects touched
        parse_sfm(p, n, r);
    }
    return r;  // nanobind converts to the Python Reconstruction with the GIL re-held
}

// --- writer: COLMAP model -> OpenMVG pinhole family ------------------------
struct MvgIntr {
    const char *type_name;
    double f, ppx, ppy;
    const char *disto_key;  // nullptr => no distortion array
    std::vector<double> disto;
};

MvgIntr camera_to_mvg(const Camera &c) {
    const ModelInfo info = colmap_model_info(c.model_id);  // throws on unknown id
    if (static_cast<int>(c.params.size()) != info.nparams)
        bad("camera " + std::to_string(c.id) + " has " + std::to_string(c.params.size()) +
            " params, expected " + std::to_string(info.nparams) + " for model " + info.name);
    const std::vector<double> &p = c.params;
    auto need_single_focal = [&](double fx, double fy) {
        if (fx != fy)
            bad("OpenMVG intrinsics have a single focal length; camera " + std::to_string(c.id) +
                " has fx != fy (normalize first)");
    };
    switch (c.model_id) {
        case 0:  // SIMPLE_PINHOLE {f,cx,cy}
            return {"pinhole", p[0], p[1], p[2], nullptr, {}};
        case 1:  // PINHOLE {fx,fy,cx,cy}
            need_single_focal(p[0], p[1]);
            return {"pinhole", p[0], p[2], p[3], nullptr, {}};
        case 2:  // SIMPLE_RADIAL {f,cx,cy,k}
            return {"pinhole_radial_k1", p[0], p[1], p[2], "disto_k1", {p[3]}};
        case 3:  // RADIAL {f,cx,cy,k1,k2} -> radial_k3 with k3=0
            return {"pinhole_radial_k3", p[0], p[1], p[2], "disto_k3", {p[3], p[4], 0.0}};
        case 4:  // OPENCV {fx,fy,cx,cy,k1,k2,p1,p2} -> brown_t2 {k1,k2,k3=0,t1=p1,t2=p2}
            need_single_focal(p[0], p[1]);
            return {"pinhole_brown_t2", p[0], p[2], p[3], "disto_t2", {p[4], p[5], 0.0, p[6], p[7]}};
        case 5:  // OPENCV_FISHEYE {fx,fy,cx,cy,k1,k2,k3,k4}
            need_single_focal(p[0], p[1]);
            return {"fisheye", p[0], p[2], p[3], "fisheye", {p[4], p[5], p[6], p[7]}};
        case 6: {  // FULL_OPENCV {fx,fy,cx,cy,k1,k2,p1,p2,k3,k4,k5,k6}
            need_single_focal(p[0], p[1]);
            if (p[9] != 0.0 || p[10] != 0.0 || p[11] != 0.0)
                bad("OpenMVG cannot represent FULL_OPENCV with nonzero k4/k5/k6; camera " +
                    std::to_string(c.id) + " (normalize first)");
            if (p[6] == 0.0 && p[7] == 0.0)  // no tangential -> radial_k3
                return {"pinhole_radial_k3", p[0], p[2], p[3], "disto_k3", {p[4], p[5], p[8]}};
            return {"pinhole_brown_t2", p[0], p[2], p[3], "disto_t2",
                    {p[4], p[5], p[8], p[6], p[7]}};
        }
        default:  // FOV(7), SIMPLE_RADIAL_FISHEYE(8), RADIAL_FISHEYE(9), THIN_PRISM_FISHEYE(10)
            bad("COLMAP model " + std::string(info.name) +
                " is not representable in OpenMVG sfm_data");
    }
}

std::string write_impl(const Reconstruction &r) {
    // lookup maps (unknown references are refused, not silently dropped)
    std::unordered_map<uint32_t, size_t> cam_index;
    for (size_t i = 0; i < r.cameras.size(); i++) cam_index[r.cameras[i].id] = i;
    std::unordered_map<uint32_t, size_t> img_index;
    for (size_t i = 0; i < r.img_ids.size(); i++) img_index[r.img_ids[i]] = i;

    // cereal shared-pointer id counter: 0x80000000 | (sequential), spanning views
    // then intrinsics (the archive order).
    uint32_t ptr_next = 0;
    auto next_ptr = [&]() -> uint32_t { return 0x80000000u | (++ptr_next); };
    const size_t N = r.img_ids.size();

    json d = json::object();
    d["sfm_data_version"] = "0.3";
    d["root_path"] = "";

    // views
    json jviews = json::array();
    for (size_t i = 0; i < N; i++) {
        const uint32_t cid = r.img_cam_ids[i];
        const auto ci = cam_index.find(cid);
        if (ci == cam_index.end())
            bad("image " + std::to_string(r.img_ids[i]) + " references unknown camera " +
                std::to_string(cid));
        const Camera &cam = r.cameras[ci->second];
        json data = json::object();
        data["local_path"] = "";
        data["filename"] = i < r.img_names.size() ? r.img_names[i] : std::string();
        data["width"] = cam.width;
        data["height"] = cam.height;
        data["id_view"] = r.img_ids[i];
        data["id_intrinsic"] = cid;
        data["id_pose"] = r.img_ids[i];  // pose ids are not stored in the record
        json pw = json::object();
        pw["id"] = next_ptr();
        pw["data"] = std::move(data);
        json val = json::object();
        val["polymorphic_id"] = 1073741824u;  // cereal's non-polymorphic View marker
        val["ptr_wrapper"] = std::move(pw);
        json ent = json::object();
        ent["key"] = r.img_ids[i];
        ent["value"] = std::move(val);
        jviews.push_back(std::move(ent));
    }
    d["views"] = std::move(jviews);

    // intrinsics
    json jintr = json::array();
    std::unordered_map<std::string, uint32_t> type_id;  // type_name -> local type id
    uint32_t type_next = 0;
    for (const Camera &c : r.cameras) {
        const MvgIntr mi = camera_to_mvg(c);  // guards + maps
        json data = json::object();
        data["width"] = c.width;
        data["height"] = c.height;
        data["focal_length"] = mi.f;
        data["principal_point"] = json::array({mi.ppx, mi.ppy});
        if (mi.disto_key) data[mi.disto_key] = mi.disto;
        json pw = json::object();
        pw["id"] = next_ptr();
        pw["data"] = std::move(data);
        json val = json::object();
        const auto tit = type_id.find(mi.type_name);
        if (tit == type_id.end()) {  // first of this type: introduce the name
            const uint32_t tid = ++type_next;
            type_id[mi.type_name] = tid;
            val["polymorphic_id"] = 0x80000000u | tid;
            val["polymorphic_name"] = mi.type_name;
        } else {  // cereal back-reference by bare id
            val["polymorphic_id"] = tit->second;
        }
        val["ptr_wrapper"] = std::move(pw);
        json ent = json::object();
        ent["key"] = c.id;
        ent["value"] = std::move(val);
        jintr.push_back(std::move(ent));
    }
    d["intrinsics"] = std::move(jintr);

    // extrinsics (one per image; R = quat_to_matrix(q), C = -R^T t)
    json jextr = json::array();
    for (size_t i = 0; i < N; i++) {
        const double q[4] = {r.quats[i * 4], r.quats[i * 4 + 1], r.quats[i * 4 + 2],
                             r.quats[i * 4 + 3]};
        double R[9];
        quat_to_matrix(q, R);
        const double t0 = r.trans[i * 3], t1 = r.trans[i * 3 + 1], t2 = r.trans[i * 3 + 2];
        double C[3];
        for (int c = 0; c < 3; c++)
            C[c] = -(R[0 * 3 + c] * t0 + R[1 * 3 + c] * t1 + R[2 * 3 + c] * t2);
        json rot = json::array();
        for (int rr = 0; rr < 3; rr++)
            rot.push_back(json::array({R[rr * 3 + 0], R[rr * 3 + 1], R[rr * 3 + 2]}));
        json val = json::object();
        val["rotation"] = std::move(rot);
        val["center"] = json::array({C[0], C[1], C[2]});
        json ent = json::object();
        ent["key"] = r.img_ids[i];
        ent["value"] = std::move(val);
        jextr.push_back(std::move(ent));
    }
    d["extrinsics"] = std::move(jextr);

    // structure (observations rebuilt from the record's per-image CSR via tracks;
    // untriangulated obs -- those with obs_pt3d == -1, never referenced by a track
    // -- are naturally absent)
    json jstruct = json::array();
    const size_t M = r.pt_ids.size();
    for (size_t k = 0; k < M; k++) {
        json obsarr = json::array();
        const uint64_t a = r.track_off[k], e = r.track_off[k + 1];
        for (uint64_t j = a; j < e; j++) {
            const uint32_t img_id = r.track[2 * j];
            const uint32_t p2d = r.track[2 * j + 1];
            const auto ii = img_index.find(img_id);
            if (ii == img_index.end())
                bad("structure track references unknown image " + std::to_string(img_id));
            const size_t row = ii->second;
            if (p2d >= r.obs_off[row + 1] - r.obs_off[row])
                bad("structure track references a point2D index out of range");
            const uint64_t slot = r.obs_off[row] + p2d;
            json ov = json::object();
            ov["id_feat"] = p2d;  // re-emit the compact POINT2D_IDX (id_feat is not kept)
            ov["x"] = json::array({r.obs_xy[2 * slot], r.obs_xy[2 * slot + 1]});
            json oent = json::object();
            oent["key"] = img_id;
            oent["value"] = std::move(ov);
            obsarr.push_back(std::move(oent));
        }
        json val = json::object();
        val["X"] = json::array({r.xyz[k * 3], r.xyz[k * 3 + 1], r.xyz[k * 3 + 2]});
        val["observations"] = std::move(obsarr);
        json ent = json::object();
        ent["key"] = r.pt_ids[k];
        ent["value"] = std::move(val);
        jstruct.push_back(std::move(ent));
    }
    d["structure"] = std::move(jstruct);
    d["control_points"] = json::array();

    std::string out;
    try {
        out = d.dump();  // compact; nlohmann emits shortest-round-trip doubles
    } catch (const json::exception &e) {
        bad(std::string("serialization failed: ") + e.what());
    }
    return out;
}

nb::bytes write_openmvg(const Reconstruction &r) {
    std::string out;
    {
        nb::gil_scoped_release rel;  // pure-C++ encode
        out = write_impl(r);
    }
    return nb::bytes(out.data(), out.size());  // constructed with the GIL re-held
}

}  // namespace

void register_openmvg(nb::module_ &m) {
    m.def("read_openmvg", &read_openmvg, "data"_a,
          "Decode OpenMVG sfm_data.json bytes into a Reconstruction (WXYZ quaternions, "
          "world_to_camera). Poses are converted from OpenMVG's rotation + world-space camera "
          "center: q = shepperd(R), t = -R*C. Intrinsics map onto COLMAP models (pinhole -> "
          "SIMPLE_PINHOLE, pinhole_radial_k1 -> SIMPLE_RADIAL, pinhole_radial_k3 / "
          "pinhole_brown_t2 -> FULL_OPENCV, fisheye -> OPENCV_FISHEYE). Unreconstructed views "
          "(no pose, or id_intrinsic == UndefinedIndexT) are skipped. rgb is 0 and error is -1 "
          "(sfm_data.json carries neither); the observation id_feat is dropped.");
    m.def("write_openmvg", &write_openmvg, "recon"_a,
          "Encode a Reconstruction as OpenMVG sfm_data.json bytes (cereal JSON archive: "
          "sfm_data_version 0.3, ptr_wrapper / polymorphic wrappers). Extrinsics store the camera "
          "center C = -R^T t. Guards intrinsics not representable as a single-focal OpenMVG "
          "pinhole model (PINHOLE/OPENCV/FULL_OPENCV require fx == fy; FOV and the fisheye/thin "
          "-prism variants are refused). rgb, error and untriangulated observations are dropped.");
}
