// COLMAP binary sparse-model codec (formats_survey.md §3) + the
// Reconstruction Record: the first SoA in-memory representation, exposing
// zero-copy ndarray views into its buffers (rv_policy::reference_internal
// keeps the owning Record alive for as long as any view references it).
//
// Conventions carried explicitly (the survey's #1 bug class): quaternions
// are WXYZ, the pose is world->camera; camera intrinsics are an ordered
// params[] whose meaning is set by the COLMAP model id.
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <fstream>
#include <iterator>

#include "common.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

struct Camera {
    uint32_t id;
    int32_t model_id;
    uint64_t width, height;
    std::vector<double> params;
};

struct Reconstruction {
    std::vector<Camera> cameras;
    // images (SoA) + names + CSR observations (per-image 2D points)
    std::vector<uint32_t> img_ids;
    std::vector<double> quats;  // N*4, WXYZ
    std::vector<double> trans;  // N*3
    std::vector<uint32_t> img_cam_ids;
    std::vector<std::string> img_names;
    std::vector<double> obs_xy;     // 2*sumK
    std::vector<int64_t> obs_pt3d;  // sumK (-1 = no 3D point)
    std::vector<uint64_t> obs_off;  // N+1
    // points3D (SoA) + CSR tracks
    std::vector<uint64_t> pt_ids;
    std::vector<double> xyz;  // M*3
    std::vector<uint8_t> rgb;  // M*3
    std::vector<double> err;  // M
    std::vector<uint32_t> track;    // 2*sumT (image_id, point2D_idx)
    std::vector<uint64_t> track_off;  // M+1

    size_t num_images() const { return img_ids.size(); }
    size_t num_points() const { return pt_ids.size(); }
};

struct ModelInfo {
    const char *name;
    int nparams;
};
ModelInfo model_info(int id) {
    switch (id) {
        case 0: return {"SIMPLE_PINHOLE", 3};
        case 1: return {"PINHOLE", 4};
        case 2: return {"SIMPLE_RADIAL", 4};
        case 3: return {"RADIAL", 5};
        case 4: return {"OPENCV", 8};
        case 5: return {"OPENCV_FISHEYE", 8};
        case 6: return {"FULL_OPENCV", 12};
        case 7: return {"FOV", 5};
        case 8: return {"SIMPLE_RADIAL_FISHEYE", 4};
        case 9: return {"RADIAL_FISHEYE", 5};
        case 10: return {"THIN_PRISM_FISHEYE", 12};
        default: throw std::invalid_argument("COLMAP: unknown camera model id " + std::to_string(id));
    }
}

std::string read_file(const std::string &path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::invalid_argument("COLMAP: cannot open " + path);
    return std::string(std::istreambuf_iterator<char>(f), {});
}
void write_file(const std::string &path, const std::string &data) {
    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::invalid_argument("COLMAP: cannot write " + path);
    f.write(data.data(), static_cast<std::streamsize>(data.size()));
}

void read_cameras(const std::string &b, Reconstruction &r) {
    LeReader rd(b.data(), b.size());
    uint64_t n = rd.get<uint64_t>();
    r.cameras.reserve(n);
    for (uint64_t i = 0; i < n; i++) {
        Camera c;
        c.id = rd.get<uint32_t>();
        c.model_id = rd.get<int32_t>();
        c.width = rd.get<uint64_t>();
        c.height = rd.get<uint64_t>();
        int np = model_info(c.model_id).nparams;
        c.params.resize(np);
        for (int k = 0; k < np; k++) c.params[k] = rd.get<double>();
        r.cameras.push_back(std::move(c));
    }
}
void read_images(const std::string &b, Reconstruction &r) {
    LeReader rd(b.data(), b.size());
    uint64_t n = rd.get<uint64_t>();
    r.obs_off.push_back(0);
    for (uint64_t i = 0; i < n; i++) {
        r.img_ids.push_back(rd.get<uint32_t>());
        for (int k = 0; k < 4; k++) r.quats.push_back(rd.get<double>());
        for (int k = 0; k < 3; k++) r.trans.push_back(rd.get<double>());
        r.img_cam_ids.push_back(rd.get<uint32_t>());
        r.img_names.push_back(rd.get_cstr());
        uint64_t k = rd.get<uint64_t>();
        for (uint64_t j = 0; j < k; j++) {
            r.obs_xy.push_back(rd.get<double>());
            r.obs_xy.push_back(rd.get<double>());
            uint64_t pid = rd.get<uint64_t>();
            r.obs_pt3d.push_back(pid == UINT64_MAX ? -1 : static_cast<int64_t>(pid));
        }
        r.obs_off.push_back(r.obs_pt3d.size());
    }
}
void read_points(const std::string &b, Reconstruction &r) {
    LeReader rd(b.data(), b.size());
    uint64_t n = rd.get<uint64_t>();
    r.track_off.push_back(0);
    for (uint64_t i = 0; i < n; i++) {
        r.pt_ids.push_back(rd.get<uint64_t>());
        for (int k = 0; k < 3; k++) r.xyz.push_back(rd.get<double>());
        for (int k = 0; k < 3; k++) r.rgb.push_back(rd.get<uint8_t>());
        r.err.push_back(rd.get<double>());
        uint64_t t = rd.get<uint64_t>();
        for (uint64_t j = 0; j < t; j++) {
            r.track.push_back(rd.get<uint32_t>());
            r.track.push_back(rd.get<uint32_t>());
        }
        r.track_off.push_back(r.track.size() / 2);
    }
}

Reconstruction read_sparse(const std::string &dir) {
    Reconstruction r;
    read_cameras(read_file(dir + "/cameras.bin"), r);
    read_images(read_file(dir + "/images.bin"), r);
    read_points(read_file(dir + "/points3D.bin"), r);
    return r;
}

std::string write_cameras(const Reconstruction &r) {
    LeWriter w;
    w.put<uint64_t>(r.cameras.size());
    for (const auto &c : r.cameras) {
        w.put<uint32_t>(c.id);
        w.put<int32_t>(c.model_id);
        w.put<uint64_t>(c.width);
        w.put<uint64_t>(c.height);
        for (double p : c.params) w.put<double>(p);
    }
    return std::move(w.out);
}
std::string write_images(const Reconstruction &r) {
    LeWriter w;
    uint64_t n = r.num_images();
    w.put<uint64_t>(n);
    for (uint64_t i = 0; i < n; i++) {
        w.put<uint32_t>(r.img_ids[i]);
        for (int k = 0; k < 4; k++) w.put<double>(r.quats[i * 4 + k]);
        for (int k = 0; k < 3; k++) w.put<double>(r.trans[i * 3 + k]);
        w.put<uint32_t>(r.img_cam_ids[i]);
        w.put_cstr(r.img_names[i]);
        uint64_t a = r.obs_off[i], e = r.obs_off[i + 1];
        w.put<uint64_t>(e - a);
        for (uint64_t j = a; j < e; j++) {
            w.put<double>(r.obs_xy[j * 2]);
            w.put<double>(r.obs_xy[j * 2 + 1]);
            int64_t pid = r.obs_pt3d[j];
            w.put<uint64_t>(pid < 0 ? UINT64_MAX : static_cast<uint64_t>(pid));
        }
    }
    return std::move(w.out);
}
std::string write_points(const Reconstruction &r) {
    LeWriter w;
    uint64_t n = r.num_points();
    w.put<uint64_t>(n);
    for (uint64_t i = 0; i < n; i++) {
        w.put<uint64_t>(r.pt_ids[i]);
        for (int k = 0; k < 3; k++) w.put<double>(r.xyz[i * 3 + k]);
        for (int k = 0; k < 3; k++) w.put<uint8_t>(r.rgb[i * 3 + k]);
        w.put<double>(r.err[i]);
        uint64_t a = r.track_off[i], e = r.track_off[i + 1];
        w.put<uint64_t>(e - a);
        for (uint64_t j = a; j < e; j++) {
            w.put<uint32_t>(r.track[j * 2]);
            w.put<uint32_t>(r.track[j * 2 + 1]);
        }
    }
    return std::move(w.out);
}
void write_sparse(const Reconstruction &r, const std::string &dir) {
    write_file(dir + "/cameras.bin", write_cameras(r));
    write_file(dir + "/images.bin", write_images(r));
    write_file(dir + "/points3D.bin", write_points(r));
}

// Zero-copy view of an internal buffer (owner = the Record, via
// reference_internal on the property).
template <typename T>
nb::ndarray<nb::numpy, T> vw(const std::vector<T> &v, std::vector<size_t> shape) {
    return nb::ndarray<nb::numpy, T>(const_cast<T *>(v.data()), shape.size(), shape.data());
}

}  // namespace

void register_colmap(nb::module_ &m) {
    nb::class_<Camera>(m, "Camera")
        .def_ro("id", &Camera::id)
        .def_ro("model_id", &Camera::model_id)
        .def_prop_ro("model", [](const Camera &c) { return model_info(c.model_id).name; })
        .def_ro("width", &Camera::width)
        .def_ro("height", &Camera::height)
        .def_prop_ro("params", [](const Camera &c) { return vw(c.params, {c.params.size()}); })
        .def("__repr__", [](const Camera &c) {
            return "<Camera id=" + std::to_string(c.id) + " model=" + model_info(c.model_id).name +
                   " " + std::to_string(c.width) + "x" + std::to_string(c.height) + ">";
        });

    auto ri = nb::rv_policy::reference_internal;
    nb::class_<Reconstruction>(m, "Reconstruction")
        .def_prop_ro("num_cameras", [](const Reconstruction &r) { return r.cameras.size(); })
        .def_prop_ro("num_images", [](const Reconstruction &r) { return r.num_images(); })
        .def_prop_ro("num_points3D", [](const Reconstruction &r) { return r.num_points(); })
        .def_prop_ro("cameras", [](const Reconstruction &r) { return r.cameras; })
        .def_prop_ro("image_ids", [](const Reconstruction &r) { return vw(r.img_ids, {r.num_images()}); }, ri)
        .def_prop_ro("quaternions", [](const Reconstruction &r) { return vw(r.quats, {r.num_images(), 4}); }, ri)
        .def_prop_ro("translations", [](const Reconstruction &r) { return vw(r.trans, {r.num_images(), 3}); }, ri)
        .def_prop_ro("image_camera_ids", [](const Reconstruction &r) { return vw(r.img_cam_ids, {r.num_images()}); }, ri)
        .def_prop_ro("image_names", [](const Reconstruction &r) { return r.img_names; })
        .def_prop_ro("point3D_ids", [](const Reconstruction &r) { return vw(r.pt_ids, {r.num_points()}); }, ri)
        .def_prop_ro("xyz", [](const Reconstruction &r) { return vw(r.xyz, {r.num_points(), 3}); }, ri)
        .def_prop_ro("rgb", [](const Reconstruction &r) { return vw(r.rgb, {r.num_points(), 3}); }, ri)
        .def_prop_ro("errors", [](const Reconstruction &r) { return vw(r.err, {r.num_points()}); }, ri)
        .def("__repr__", [](const Reconstruction &r) {
            return "<Reconstruction cameras=" + std::to_string(r.cameras.size()) +
                   " images=" + std::to_string(r.num_images()) +
                   " points3D=" + std::to_string(r.num_points()) + ">";
        });

    m.def("read_colmap_sparse", &read_sparse, "path"_a,
          "Read a COLMAP binary sparse model directory (cameras.bin/images.bin/points3D.bin).");
    m.def("write_colmap_sparse", &write_sparse, "recon"_a, "path"_a,
          "Write a Reconstruction as a COLMAP binary sparse model directory.");
}
