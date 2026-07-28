// codecs/reconstruction/colmap.cpp -- COLMAP binary sparse-model reader/writer
// (formats_survey.md §3). Little-endian; observations + tracks are read and
// re-written so round-trips are byte-exact. The Reconstruction record and
// its conventions live in records/reconstruction.hpp.
#include <nanobind/stl/string.h>

#include <algorithm>
#include <fstream>
#include <iterator>
#include <limits>

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

template <typename T>
T read_stream_le(std::ifstream &file, const char *what) {
    static_assert(std::is_trivially_copyable_v<T>);
    uint8_t raw[sizeof(T)];
    file.read(reinterpret_cast<char *>(raw),
              static_cast<std::streamsize>(sizeof(T)));
    if (!file)
        throw std::invalid_argument(std::string("COLMAP: truncated ") + what);
    if (!host_is_le()) std::reverse(raw, raw + sizeof(T));
    T value;
    std::memcpy(&value, raw, sizeof(T));
    return value;
}

std::string read_stream_cstr(std::ifstream &file) {
    const std::streampos start = file.tellg();
    if (start == std::streampos(-1))
        throw std::invalid_argument("COLMAP: cannot locate image name");
    // Validate the terminator without growing a string from malformed input.
    file.ignore(std::numeric_limits<std::streamsize>::max(), '\0');
    if (!file || file.eof())
        throw std::invalid_argument("COLMAP: truncated image name");
    const std::streampos after = file.tellg();
    if (after == std::streampos(-1) || after <= start)
        throw std::invalid_argument("COLMAP: cannot size image name");
    const auto raw_length = after - start - std::streamoff{1};
    const uintmax_t length_u = static_cast<uintmax_t>(raw_length);
    if (length_u > std::numeric_limits<size_t>::max() ||
        length_u >
            static_cast<uintmax_t>(
                std::numeric_limits<std::streamsize>::max()))
        throw std::invalid_argument(
            "COLMAP: image name exceeds address space");
    const size_t length = static_cast<size_t>(length_u);
    file.seekg(start);
    if (!file)
        throw std::invalid_argument("COLMAP: cannot seek image name");
    std::string value(length, '\0');
    if (length != 0) {
        file.read(value.data(), static_cast<std::streamsize>(length));
        if (!file)
            throw std::invalid_argument("COLMAP: truncated image name");
    }
    if (file.get() != 0)
        throw std::invalid_argument("COLMAP: truncated image name");
    return value;
}

void skip_stream_cstr(std::ifstream &file) {
    file.ignore(std::numeric_limits<std::streamsize>::max(), '\0');
    if (!file || file.eof())
        throw std::invalid_argument("COLMAP: truncated image name");
}

uint64_t stream_remaining_bytes(std::ifstream &file, const char *what) {
    const std::streampos current = file.tellg();
    if (current == std::streampos(-1))
        throw std::invalid_argument(std::string("COLMAP: cannot locate ") +
                                    what);
    file.seekg(0, std::ios::end);
    const std::streampos end = file.tellg();
    if (end == std::streampos(-1) || end < current)
        throw std::invalid_argument(std::string("COLMAP: cannot size ") +
                                    what);
    file.seekg(current);
    if (!file)
        throw std::invalid_argument(std::string("COLMAP: cannot seek ") +
                                    what);
    return static_cast<uint64_t>(end - current);
}

void skip_stream_bytes(std::ifstream &file, uint64_t count, const char *what) {
    if (count >
        static_cast<uint64_t>(std::numeric_limits<std::streamoff>::max()))
        throw std::invalid_argument(std::string("COLMAP: oversized ") + what);
    if (count > stream_remaining_bytes(file, what))
        throw std::invalid_argument(std::string("COLMAP: truncated ") + what);
    file.seekg(static_cast<std::streamoff>(count), std::ios::cur);
    if (!file)
        throw std::invalid_argument(std::string("COLMAP: truncated ") + what);
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

Reconstruction read_sparse_image(const std::string &dir, uint32_t image_id) {
    nb::gil_scoped_release rel;
    Reconstruction r;
    r.obs_off.push_back(0);
    r.track_off.push_back(0);

    std::ifstream images(dir + "/images.bin", std::ios::binary);
    if (!images)
        throw std::invalid_argument("COLMAP: cannot open " + dir +
                                    "/images.bin");
    const uint64_t image_count =
        read_stream_le<uint64_t>(images, "images.bin header");
    bool found = false;
    uint32_t camera_id = 0;
    for (uint64_t i = 0; i < image_count; ++i) {
        const uint32_t current =
            read_stream_le<uint32_t>(images, "image id");
        double quat[4], trans[3];
        for (double &value : quat)
            value = read_stream_le<double>(images, "image quaternion");
        for (double &value : trans)
            value = read_stream_le<double>(images, "image translation");
        const uint32_t current_camera =
            read_stream_le<uint32_t>(images, "image camera id");
        std::string name;
        if (current == image_id)
            name = read_stream_cstr(images);
        else
            skip_stream_cstr(images);
        const uint64_t observation_count =
            read_stream_le<uint64_t>(images, "image observation count");
        if (observation_count >
            std::numeric_limits<uint64_t>::max() / 24)
            throw std::invalid_argument(
                "COLMAP: image observation byte count overflows");

        if (current != image_id) {
            skip_stream_bytes(images, observation_count * 24,
                              "image observations");
            continue;
        }

        if (observation_count >
            static_cast<uint64_t>(std::numeric_limits<size_t>::max() / 2))
            throw std::invalid_argument(
                "COLMAP: image observation count exceeds address space");
        const uint64_t observation_bytes = observation_count * 24;
        if (observation_bytes >
            stream_remaining_bytes(images, "image observations"))
            throw std::invalid_argument(
                "COLMAP: truncated image observations");
        const size_t count = static_cast<size_t>(observation_count);
        r.img_ids.push_back(current);
        r.quats.assign(quat, quat + 4);
        r.trans.assign(trans, trans + 3);
        r.img_cam_ids.push_back(current_camera);
        r.img_names.push_back(std::move(name));
        r.obs_xy.resize(count * 2);
        r.obs_pt3d.resize(count);
        for (size_t j = 0; j < count; ++j) {
            r.obs_xy[j * 2] =
                read_stream_le<double>(images, "observation x");
            r.obs_xy[j * 2 + 1] =
                read_stream_le<double>(images, "observation y");
            const uint64_t point_id =
                read_stream_le<uint64_t>(images, "observation point id");
            r.obs_pt3d[j] =
                point_id == UINT64_MAX ? -1 : static_cast<int64_t>(point_id);
        }
        r.obs_off.push_back(count);
        camera_id = current_camera;
        found = true;
        break;
    }
    if (!found)
        throw std::invalid_argument("COLMAP: image id " +
                                    std::to_string(image_id) + " not found");

    std::ifstream cameras(dir + "/cameras.bin", std::ios::binary);
    if (!cameras)
        throw std::invalid_argument("COLMAP: cannot open " + dir +
                                    "/cameras.bin");
    const uint64_t camera_count =
        read_stream_le<uint64_t>(cameras, "cameras.bin header");
    for (uint64_t i = 0; i < camera_count; ++i) {
        Camera camera;
        camera.id = read_stream_le<uint32_t>(cameras, "camera id");
        camera.model_id =
            read_stream_le<int32_t>(cameras, "camera model id");
        camera.width = read_stream_le<uint64_t>(cameras, "camera width");
        camera.height = read_stream_le<uint64_t>(cameras, "camera height");
        const int params = colmap_model_info(camera.model_id).nparams;
        camera.params.resize(static_cast<size_t>(params));
        for (double &value : camera.params)
            value = read_stream_le<double>(cameras, "camera parameter");
        if (camera.id == camera_id) {
            r.cameras.push_back(std::move(camera));
            return r;
        }
    }
    throw std::invalid_argument("COLMAP: camera id " +
                                std::to_string(camera_id) +
                                " referenced by image was not found");
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
    m.def("read_colmap_sparse_image", &read_sparse_image, "path"_a,
          "image_id"_a,
          "Read one COLMAP binary image and its camera without opening "
          "points3D.bin or materializing unrelated images.");
    m.def("write_colmap_sparse", &write_sparse, "recon"_a, "path"_a,
          "Write a Reconstruction as a COLMAP binary sparse model directory.");
}
