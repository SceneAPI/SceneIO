// codecs/colmap.cpp — COLMAP binary sparse-model reader/writer
// (formats_survey.md §3). Little-endian; observations + tracks are read and
// re-written so round-trips are byte-exact. The Reconstruction record and
// its conventions live in records/reconstruction.hpp.
#include <nanobind/stl/string.h>

#include <fstream>
#include <iterator>

#include "records/reconstruction.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

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
        int np = colmap_model_info(c.model_id).nparams;
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

}  // namespace

void register_colmap(nb::module_ &m) {
    m.def("read_colmap_sparse", &read_sparse, "path"_a,
          "Read a COLMAP binary sparse model directory (cameras.bin/images.bin/points3D.bin).");
    m.def("write_colmap_sparse", &write_sparse, "recon"_a, "path"_a,
          "Write a Reconstruction as a COLMAP binary sparse model directory.");
}
