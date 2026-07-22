// codecs/transforms_json.cpp — NeRF / Instant-NGP / Nerfstudio transforms.json
// camera poses <-> PosedViewSet (io_implementation_plan.md).
//
// The file is a JSON object of (usually shared) intrinsics — fl_x/fl_y/cx/cy/w/h
// plus optional OpenCV distortion and a "camera_model" tag — and a "frames"
// array; each frame carries a "file_path" and a 4x4 row-major camera-to-world
// "transform_matrix" in the OpenGL/Blender camera axes (x right, y up, z back).
// We RECORD those conventions on the PosedViewSet (wxyz / camera_to_world /
// opengl) rather than converting: the top-left 3x3 becomes a WXYZ quaternion,
// the top-right 3x1 the translation. read->write->read reproduces poses +
// intrinsics + tags exactly (nlohmann's shortest-round-trip float dump).
#include <nlohmann/json.hpp>

#include <cmath>
#include <stdexcept>
#include <string>
#include <vector>

#include "records/posed_view_set.hpp"

using namespace nb::literals;
using json = nlohmann::json;

namespace {

// --- rotation <-> quaternion (WXYZ) ----------------------------------------
// Row-major 3x3 R (R[r*3+c]); the pair are inverses up to the quaternion
// double-cover. matrix_to_quat is Shepperd's method (stable on every branch of
// the trace); both renormalize so a read->write->read round-trip is exact.
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

// --- intrinsics <-> COLMAP Camera ------------------------------------------
// A frame "owns" intrinsics if it carries its own focal length.
bool has_intrinsics(const json &o) { return o.contains("fl_x") || o.contains("fl_y"); }

// Read a numeric field from `o`, else from the file-root fallback `fb`, else def.
double jget(const json &o, const json &fb, const char *k, double def) {
    auto it = o.find(k);
    if (it != o.end() && it->is_number()) return it->get<double>();
    it = fb.find(k);
    if (it != fb.end() && it->is_number()) return it->get<double>();
    return def;
}
uint64_t jgetu(const json &o, const json &fb, const char *k, uint64_t def) {
    auto pick = [&](const json &j) -> const json * {
        auto it = j.find(k);
        return (it != j.end() && it->is_number()) ? &*it : nullptr;
    };
    const json *v = pick(o);
    if (!v) v = pick(fb);
    if (!v) return def;
    if (v->is_number_unsigned()) return v->get<uint64_t>();
    if (v->is_number_integer()) return static_cast<uint64_t>(v->get<int64_t>());
    return static_cast<uint64_t>(std::llround(v->get<double>()));
}
std::string jgets(const json &o, const json &fb, const char *k) {
    auto it = o.find(k);
    if (it != o.end() && it->is_string()) return it->get<std::string>();
    it = fb.find(k);
    if (it != fb.end() && it->is_string()) return it->get<std::string>();
    return std::string();
}

// Build one COLMAP-model Camera from an intrinsics-bearing object `src`, falling
// back to `top` (the file root) for any field the frame omits. The COLMAP model
// id + params layout mirror records/reconstruction.hpp: SIMPLE_PINHOLE(0)=
// {f,cx,cy}, PINHOLE(1)={fx,fy,cx,cy}, OPENCV(4)={fx,fy,cx,cy,k1,k2,p1,p2}.
Camera parse_camera(const json &src, const json &top, uint32_t id) {
    const std::string cm = jgets(src, top, "camera_model");
    auto has = [&](const char *k) {
        auto it = src.find(k);
        if (it != src.end() && !it->is_null()) return true;
        it = top.find(k);
        return it != top.end() && !it->is_null();
    };
    const bool dist = has("k1") || has("k2") || has("p1") || has("p2");
    int model;
    if (cm == "SIMPLE_PINHOLE") model = 0;
    else if (cm == "PINHOLE") model = 1;
    else if (cm == "OPENCV") model = 4;
    else if (dist) model = 4;          // undeclared but distorted -> OPENCV
    else if (has("fl_y")) model = 1;   // two focals -> PINHOLE
    else model = 0;                    // single focal -> SIMPLE_PINHOLE

    const double fx = jget(src, top, "fl_x", 0.0);
    const double fy = jget(src, top, "fl_y", fx);
    const double cx = jget(src, top, "cx", 0.0);
    const double cy = jget(src, top, "cy", 0.0);

    Camera c;
    c.id = id;
    c.model_id = model;
    c.width = jgetu(src, top, "w", 0);
    c.height = jgetu(src, top, "h", 0);
    if (model == 0)
        c.params = {fx, cx, cy};
    else if (model == 1)
        c.params = {fx, fy, cx, cy};
    else
        c.params = {fx, fy, cx, cy, jget(src, top, "k1", 0.0), jget(src, top, "k2", 0.0),
                    jget(src, top, "p1", 0.0), jget(src, top, "p2", 0.0)};
    return c;
}

// Emit a Camera's intrinsics into a JSON object (file root for shared, or a
// frame for per-view). Inverse of parse_camera; only the three transforms.json
// camera models are representable.
void write_intrinsics(json &o, const Camera &c) {
    const std::vector<double> &p = c.params;
    switch (c.model_id) {
        case 0:  // SIMPLE_PINHOLE
            o["camera_model"] = "SIMPLE_PINHOLE";
            o["fl_x"] = p.at(0);
            o["fl_y"] = p.at(0);
            o["cx"] = p.at(1);
            o["cy"] = p.at(2);
            break;
        case 1:  // PINHOLE
            o["camera_model"] = "PINHOLE";
            o["fl_x"] = p.at(0);
            o["fl_y"] = p.at(1);
            o["cx"] = p.at(2);
            o["cy"] = p.at(3);
            break;
        case 4:  // OPENCV
            o["camera_model"] = "OPENCV";
            o["fl_x"] = p.at(0);
            o["fl_y"] = p.at(1);
            o["cx"] = p.at(2);
            o["cy"] = p.at(3);
            o["k1"] = p.at(4);
            o["k2"] = p.at(5);
            o["p1"] = p.at(6);
            o["p2"] = p.at(7);
            break;
        default:
            throw std::invalid_argument("transforms.json: camera model id " +
                                        std::to_string(c.model_id) + " is not representable");
    }
    o["w"] = c.width;
    o["h"] = c.height;
}

PosedViewSet read_transforms_json(nb::bytes data) {
    json d;
    try {  // map JSON parse/type errors to ValueError, per the codec bad-input contract
        d = json::parse(std::string(data.c_str(), data.size()));
    } catch (const json::exception &e) {
        throw std::invalid_argument(std::string("transforms.json: ") + e.what());
    }
    auto fit = d.find("frames");
    if (fit == d.end() || !fit->is_array())
        throw std::invalid_argument("transforms.json: missing 'frames' array");
    const json &frames = *fit;
    const size_t nv = frames.size();

    PosedViewSet p;
    p.quaternion_order = "wxyz";
    p.pose_convention = "camera_to_world";
    p.axis_frame = "opengl";
    p.scale_to_meters = 1.0;
    p.quats.reserve(nv * 4);
    p.trans.reserve(nv * 3);
    p.names.reserve(nv);

    // Intrinsics are shared (one top-level Camera, cam_idx all 0) unless any
    // frame carries its own, in which case we emit one Camera per frame.
    const bool top_has = has_intrinsics(d);
    bool any_frame_has = false;
    for (const auto &f : frames)
        if (has_intrinsics(f)) { any_frame_has = true; break; }
    const bool per_frame = any_frame_has;
    const bool shared = top_has && !any_frame_has;
    if (shared) p.cameras.push_back(parse_camera(d, d, 0));

    uint32_t idx = 0;
    for (const auto &f : frames) {
        auto mit = f.find("transform_matrix");
        if (mit == f.end() || !mit->is_array() || mit->size() < 3)
            throw std::invalid_argument("transforms.json: frame missing a 4x4 'transform_matrix'");
        const json &M = *mit;
        double R[9], t[3];
        for (int r = 0; r < 3; r++) {
            const json &row = M[static_cast<size_t>(r)];
            if (!row.is_array() || row.size() < 4)
                throw std::invalid_argument("transforms.json: 'transform_matrix' rows need 4 entries");
            R[r * 3 + 0] = row[0].get<double>();
            R[r * 3 + 1] = row[1].get<double>();
            R[r * 3 + 2] = row[2].get<double>();
            t[r] = row[3].get<double>();
        }
        double q[4];
        matrix_to_quat(R, q);
        p.quats.insert(p.quats.end(), {q[0], q[1], q[2], q[3]});
        p.trans.insert(p.trans.end(), {t[0], t[1], t[2]});

        auto pit = f.find("file_path");
        p.names.push_back((pit != f.end() && pit->is_string()) ? pit->get<std::string>()
                                                               : std::string());

        if (per_frame) {
            p.cameras.push_back(parse_camera(f, d, idx));
            p.cam_idx.push_back(static_cast<int32_t>(idx));
        } else if (shared) {
            p.cam_idx.push_back(0);
        }
        idx++;
    }
    return p;
}

nb::bytes write_transforms_json(const PosedViewSet &views) {
    // record-don't-convert: refuse to emit a foreign-convention record under
    // transforms.json's implicit camera_to_world / OpenGL / meters labeling
    // rather than silently mislabel it (normalize the PosedViewSet first).
    if (views.pose_convention != "camera_to_world" || views.axis_frame != "opengl" ||
        views.scale_to_meters != 1.0)
        throw std::invalid_argument(
            "transforms.json needs a camera_to_world / opengl / scale-1.0 PosedViewSet; got " +
            views.pose_convention + " / " + views.axis_frame + " — normalize it first");
    const size_t nv = views.num_views();
    json d = json::object();

    // Shared iff exactly one Camera indexed by every view; >1 Camera -> per-frame.
    bool shared = views.cameras.size() == 1;
    if (shared)
        for (int32_t ci : views.cam_idx)
            if (ci != 0) { shared = false; break; }
    const bool per_frame = !views.cameras.empty() && !shared;
    if (shared) write_intrinsics(d, views.cameras[0]);

    json frames = json::array();
    for (size_t i = 0; i < nv; i++) {
        json f = json::object();
        f["file_path"] = (i < views.names.size()) ? views.names[i] : std::string();

        // honor the record's stored quaternion order (e.g. an xyzw record) -> WXYZ
        const double *qs = views.quats.data() + i * 4;
        double q[4];
        if (views.quaternion_order == "xyzw") {
            q[0] = qs[3]; q[1] = qs[0]; q[2] = qs[1]; q[3] = qs[2];
        } else {
            q[0] = qs[0]; q[1] = qs[1]; q[2] = qs[2]; q[3] = qs[3];
        }
        double R[9];
        quat_to_matrix(q, R);
        json M = json::array();
        for (int r = 0; r < 4; r++) {
            json row = json::array();
            for (int c = 0; c < 4; c++) {
                double v;
                if (r < 3 && c < 3) v = R[r * 3 + c];
                else if (r < 3) v = views.trans[i * 3 + r];  // c == 3
                else v = (c == 3) ? 1.0 : 0.0;               // bottom row [0 0 0 1]
                row.push_back(v);
            }
            M.push_back(std::move(row));
        }
        f["transform_matrix"] = std::move(M);

        if (per_frame) {
            int32_t ci = (i < views.cam_idx.size()) ? views.cam_idx[i] : 0;
            if (ci < 0 || static_cast<size_t>(ci) >= views.cameras.size()) ci = 0;
            write_intrinsics(f, views.cameras[static_cast<size_t>(ci)]);
        }
        frames.push_back(std::move(f));
    }
    d["frames"] = std::move(frames);

    const std::string s = d.dump();
    return nb::bytes(s.data(), s.size());
}

}  // namespace

void register_transforms_json(nb::module_ &m) {
    m.def("read_transforms_json", &read_transforms_json, "data"_a,
          "Decode transforms.json (NeRF/Instant-NGP/Nerfstudio) bytes into a PosedViewSet.");
    m.def("write_transforms_json", &write_transforms_json, "views"_a,
          "Encode a PosedViewSet to transforms.json bytes.");
}
