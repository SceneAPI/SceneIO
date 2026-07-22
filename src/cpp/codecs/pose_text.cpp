// codecs/pose_text.cpp — plain-text pose-trajectory formats <-> PosedViewSet:
// TUM (`timestamp tx ty tz qx qy qz qw`) and KITTI (12 numbers = a 3x4
// row-major pose matrix per line). Both are permissive/spec-only formats.
//
// Each reader RECORDS the source's conventions as metadata rather than
// canonicalizing (docs/io_implementation_plan.md): TUM is an XYZW quaternion,
// camera_to_world, meters; KITTI is a row-major 3x4 [R|t] matrix that we
// convert to a WXYZ quaternion (camera_to_world). TUM round-trips exactly (the
// quaternion is stored verbatim); KITTI round-trips to floating-point tolerance
// (it passes through R->quat->R). The writers refuse a foreign-convention
// record rather than mislabel it. (g2o pose graphs are deferred — their edges
// don't fit PosedViewSet.)
#include <cmath>
#include <cstdio>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "records/posed_view_set.hpp"

using namespace nb::literals;

namespace {

// --- text helpers ----------------------------------------------------------

// Format a double with enough precision (17 significant digits) that a
// subsequent parse recovers the identical IEEE-754 value -> exact round-trip.
std::string fmt(double v) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.17g", v);
    return std::string(buf);
}

// A blank or '#'-comment line (leading whitespace allowed) is skipped by both
// formats.
bool skip_line(const std::string &line) {
    for (char c : line) {
        if (c == ' ' || c == '\t' || c == '\r' || c == '\n') continue;
        return c == '#';
    }
    return true;  // all whitespace
}

// --- rotation <-> quaternion (WXYZ) for KITTI's 3x3 [R] block --------------
// R is row-major 3x3 (R[3*row + col]). Both directions normalize, so the
// conversion is orthonormal-safe and matrix->quat->matrix round-trips.

void mat_to_quat_wxyz(const double R[9], double q[4]) {
    const double trace = R[0] + R[4] + R[8];
    double w, x, y, z;
    if (trace > 0.0) {
        double s = std::sqrt(trace + 1.0) * 2.0;  // s = 4w
        w = 0.25 * s;
        x = (R[7] - R[5]) / s;
        y = (R[2] - R[6]) / s;
        z = (R[3] - R[1]) / s;
    } else if (R[0] > R[4] && R[0] > R[8]) {
        double s = std::sqrt(1.0 + R[0] - R[4] - R[8]) * 2.0;  // s = 4x
        w = (R[7] - R[5]) / s;
        x = 0.25 * s;
        y = (R[1] + R[3]) / s;
        z = (R[2] + R[6]) / s;
    } else if (R[4] > R[8]) {
        double s = std::sqrt(1.0 + R[4] - R[0] - R[8]) * 2.0;  // s = 4y
        w = (R[2] - R[6]) / s;
        x = (R[1] + R[3]) / s;
        y = 0.25 * s;
        z = (R[5] + R[7]) / s;
    } else {
        double s = std::sqrt(1.0 + R[8] - R[0] - R[4]) * 2.0;  // s = 4z
        w = (R[3] - R[1]) / s;
        x = (R[2] + R[6]) / s;
        y = (R[5] + R[7]) / s;
        z = 0.25 * s;
    }
    const double norm = std::sqrt(w * w + x * x + y * y + z * z);
    if (norm == 0.0) {
        q[0] = 1.0;
        q[1] = q[2] = q[3] = 0.0;
        return;
    }
    q[0] = w / norm;
    q[1] = x / norm;
    q[2] = y / norm;
    q[3] = z / norm;
}

void quat_wxyz_to_mat(double w, double x, double y, double z, double R[9]) {
    double norm = std::sqrt(w * w + x * x + y * y + z * z);
    if (norm == 0.0) {
        w = 1.0;
        x = y = z = 0.0;
        norm = 1.0;
    }
    w /= norm;
    x /= norm;
    y /= norm;
    z /= norm;
    R[0] = 1.0 - 2.0 * (y * y + z * z);
    R[1] = 2.0 * (x * y - w * z);
    R[2] = 2.0 * (x * z + w * y);
    R[3] = 2.0 * (x * y + w * z);
    R[4] = 1.0 - 2.0 * (x * x + z * z);
    R[5] = 2.0 * (y * z - w * x);
    R[6] = 2.0 * (x * z - w * y);
    R[7] = 2.0 * (y * z + w * x);
    R[8] = 1.0 - 2.0 * (x * x + y * y);
}

// A view's quaternion as (w,x,y,z), honoring the record's stated order so a
// writer serializes faithfully regardless of how the record was built.
void view_quat_wxyz(const PosedViewSet &p, size_t i, double &w, double &x, double &y, double &z) {
    const double *q = p.quats.data() + i * 4;
    if (p.quaternion_order == "xyzw") {
        x = q[0];
        y = q[1];
        z = q[2];
        w = q[3];
    } else {  // default / "wxyz"
        w = q[0];
        x = q[1];
        y = q[2];
        z = q[3];
    }
}

// --- TUM: `timestamp tx ty tz qx qy qz qw` (XYZW, camera_to_world, meters) --

PosedViewSet read_tum(nb::bytes data) {
    std::string text(data.c_str(), data.size());
    std::istringstream stream(text);
    std::string line;
    PosedViewSet p;
    while (std::getline(stream, line)) {
        if (skip_line(line)) continue;
        std::istringstream ls(line);
        double ts, tx, ty, tz, qx, qy, qz, qw;
        if (!(ls >> ts >> tx >> ty >> tz >> qx >> qy >> qz >> qw))
            throw std::invalid_argument(
                "TUM: malformed line (expected 'timestamp tx ty tz qx qy qz qw')");
        p.stamps.push_back(ts);
        p.trans.push_back(tx);
        p.trans.push_back(ty);
        p.trans.push_back(tz);
        p.quats.push_back(qx);
        p.quats.push_back(qy);
        p.quats.push_back(qz);
        p.quats.push_back(qw);
    }
    p.quaternion_order = "xyzw";
    p.pose_convention = "camera_to_world";
    p.axis_frame = "opencv";
    p.scale_to_meters = 1.0;
    return p;
}

nb::bytes write_tum(const PosedViewSet &p) {
    if (p.pose_convention != "camera_to_world" || p.axis_frame != "opencv" || p.scale_to_meters != 1.0)
        throw std::invalid_argument(
            "TUM needs a camera_to_world / opencv / scale-1.0 PosedViewSet; got " + p.pose_convention +
            " / " + p.axis_frame + " — normalize it first");
    const size_t nv = p.num_views();
    const bool has_stamps = p.stamps.size() == nv;
    std::string out;
    for (size_t i = 0; i < nv; i++) {
        double w, x, y, z;
        view_quat_wxyz(p, i, w, x, y, z);  // TUM stores XYZW
        const double ts = has_stamps ? p.stamps[i] : static_cast<double>(i);
        const double *t = p.trans.data() + i * 3;
        out += fmt(ts);
        out += ' ';
        out += fmt(t[0]);
        out += ' ';
        out += fmt(t[1]);
        out += ' ';
        out += fmt(t[2]);
        out += ' ';
        out += fmt(x);
        out += ' ';
        out += fmt(y);
        out += ' ';
        out += fmt(z);
        out += ' ';
        out += fmt(w);
        out += '\n';
    }
    return nb::bytes(out.data(), out.size());
}

// --- KITTI: 12 numbers = row-major 3x4 [R|t] (camera_to_world; R<->WXYZ) ----

PosedViewSet read_kitti(nb::bytes data) {
    std::string text(data.c_str(), data.size());
    std::istringstream stream(text);
    std::string line;
    PosedViewSet p;
    while (std::getline(stream, line)) {
        if (skip_line(line)) continue;
        std::istringstream ls(line);
        double m[12];
        for (int k = 0; k < 12; k++)
            if (!(ls >> m[k]))
                throw std::invalid_argument(
                    "KITTI: malformed line (expected 12 numbers = row-major 3x4 [R|t])");
        const double R[9] = {m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]};
        double q[4];
        mat_to_quat_wxyz(R, q);
        p.quats.push_back(q[0]);
        p.quats.push_back(q[1]);
        p.quats.push_back(q[2]);
        p.quats.push_back(q[3]);
        p.trans.push_back(m[3]);
        p.trans.push_back(m[7]);
        p.trans.push_back(m[11]);
    }
    p.quaternion_order = "wxyz";
    p.pose_convention = "camera_to_world";
    p.axis_frame = "opencv";
    p.scale_to_meters = 1.0;
    return p;
}

nb::bytes write_kitti(const PosedViewSet &p) {
    if (p.pose_convention != "camera_to_world" || p.axis_frame != "opencv" || p.scale_to_meters != 1.0)
        throw std::invalid_argument(
            "KITTI needs a camera_to_world / opencv / scale-1.0 PosedViewSet; got " + p.pose_convention +
            " / " + p.axis_frame + " — normalize it first");
    const size_t nv = p.num_views();
    std::string out;
    for (size_t i = 0; i < nv; i++) {
        double w, x, y, z;
        view_quat_wxyz(p, i, w, x, y, z);
        double R[9];
        quat_wxyz_to_mat(w, x, y, z, R);
        const double *t = p.trans.data() + i * 3;
        const double row[12] = {R[0], R[1], R[2], t[0], R[3], R[4],
                                R[5], t[1], R[6], R[7], R[8], t[2]};
        for (int k = 0; k < 12; k++) {
            out += fmt(row[k]);
            out += (k == 11) ? '\n' : ' ';
        }
    }
    return nb::bytes(out.data(), out.size());
}

}  // namespace

void register_pose_text(nb::module_ &m) {
    m.def("read_tum", &read_tum, "data"_a, "Decode a TUM trajectory (bytes) into a PosedViewSet.");
    m.def("write_tum", &write_tum, "views"_a, "Encode a PosedViewSet to TUM trajectory bytes.");
    m.def("read_kitti", &read_kitti, "data"_a, "Decode a KITTI pose file (bytes) into a PosedViewSet.");
    m.def("write_kitti", &write_kitti, "views"_a, "Encode a PosedViewSet to KITTI pose bytes.");
}
