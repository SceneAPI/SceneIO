// codecs/reconstruction/colmap.cpp -- COLMAP binary sparse-model reader/writer
// for legacy cameras/images/points3D and modern five-file rigs/frames models.
// Little-endian; every represented field is re-written byte-exactly. Large
// files use a bounded direct-file writer instead of output-sized buffers.
#include <nanobind/stl/string.h>

#include <algorithm>
#include <array>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <type_traits>
#include <unordered_set>
#include <vector>

#include "records/reconstruction.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

std::filesystem::path native_path(const std::string &path) {
    return std::filesystem::u8path(path);
}

std::string read_file(const std::string &path) {
    std::ifstream f(native_path(path), std::ios::binary);
    if (!f) throw std::invalid_argument("COLMAP: cannot open " + path);
    return std::string(std::istreambuf_iterator<char>(f), {});
}

bool path_exists(const std::string &path) {
    std::error_code error;
    const bool exists = std::filesystem::exists(native_path(path), error);
    if (error)
        throw std::invalid_argument(
            "COLMAP: cannot inspect " + path + ": " + error.message());
    return exists;
}

void require_no_extension_sidecars(const std::string &dir) {
    constexpr std::array<const char *, 14> names = {
        "markers.bin",
        "marker_projections.bin",
        "charuco_boards.bin",
        "charuco_calibrations.bin",
        "time_frames.bin",
        "image_times.bin",
        "points3D_frames.bin",
        "markers.txt",
        "marker_projections.txt",
        "charuco_boards.txt",
        "charuco_calibrations.txt",
        "time_frames.txt",
        "image_times.txt",
        "points3D_frames.txt",
    };
    for (const char *name : names)
        if (path_exists(dir + "/" + name))
            throw std::invalid_argument(
                "COLMAP: " + std::string(name) +
                " is present but this sparse-model record does not yet "
                "represent that sidecar");
}

class BufferedFileWriter {
public:
    explicit BufferedFileWriter(const std::string &path)
        : path_(path),
          file_(native_path(path), std::ios::binary | std::ios::trunc) {
        if (!file_)
            throw std::invalid_argument("COLMAP: cannot write " + path);
        buffer_.reserve(1 << 16);
    }

    BufferedFileWriter(const BufferedFileWriter &) = delete;
    BufferedFileWriter &operator=(const BufferedFileWriter &) = delete;

    template <typename T>
    void put(T value) {
        static_assert(std::is_trivially_copyable_v<T>);
        std::array<uint8_t, sizeof(T)> bytes;
        std::memcpy(bytes.data(), &value, sizeof(T));
        if (!host_is_le()) std::reverse(bytes.begin(), bytes.end());
        write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
    }

    template <typename T>
    void put_array(const T *values, size_t count) {
        static_assert(std::is_trivially_copyable_v<T>);
        if (count == 0) return;
        if (host_is_le()) {
            if (count > std::numeric_limits<size_t>::max() / sizeof(T))
                throw std::invalid_argument(
                    "COLMAP: output array size overflows address space");
            write(reinterpret_cast<const char *>(values),
                  count * sizeof(T));
            return;
        }
        for (size_t index = 0; index < count; ++index) put(values[index]);
    }

    void put_cstr(const std::string &value) {
        write(value.data(), value.size());
        const char terminator = '\0';
        write(&terminator, 1);
    }

    void finish() {
        flush();
        file_.flush();
        if (!file_)
            throw std::invalid_argument("COLMAP: cannot write " + path_);
    }

private:
    void write(const char *data, size_t size) {
        if (size == 0) return;
        if (size > buffer_.capacity()) {
            flush();
            write_direct(data, size);
            return;
        }
        if (buffer_.size() + size > buffer_.capacity()) flush();
        const size_t offset = buffer_.size();
        buffer_.resize(offset + size);
        std::memcpy(buffer_.data() + offset, data, size);
    }

    void flush() {
        if (buffer_.empty()) return;
        write_direct(buffer_.data(), buffer_.size());
        buffer_.clear();
    }

    void write_direct(const char *data, size_t size) {
        const size_t max_chunk = static_cast<size_t>(
            std::numeric_limits<std::streamsize>::max());
        while (size != 0) {
            const size_t chunk = std::min(size, max_chunk);
            file_.write(data, static_cast<std::streamsize>(chunk));
            if (!file_)
                throw std::invalid_argument(
                    "COLMAP: cannot write " + path_);
            data += chunk;
            size -= chunk;
        }
    }

    std::string path_;
    std::ofstream file_;
    std::vector<char> buffer_;
};

int32_t checked_sensor_type(int32_t value, const char *what) {
    if (!valid_colmap_sensor_type(value))
        throw std::invalid_argument(
            std::string("COLMAP: invalid sensor type in ") + what);
    return value;
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
    const uint64_t n = rd.get<uint64_t>();
    constexpr size_t minimum_camera_size =
        sizeof(uint32_t) + sizeof(int32_t) +
        2 * sizeof(uint64_t);
    if (n > (b.size() - sizeof(uint64_t)) / minimum_camera_size)
        throw std::invalid_argument(
            "COLMAP: oversized cameras.bin count");
    r.cameras.reserve(static_cast<size_t>(n));
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
    if (rd.pos != rd.n)
        throw std::invalid_argument(
            "COLMAP: trailing bytes in cameras.bin");
}

void read_rigs(const std::string &b, Reconstruction &r) {
    LeReader rd(b.data(), b.size());
    const uint64_t count = rd.get<uint64_t>();
    if (count > (b.size() - sizeof(uint64_t)) /
                    (sizeof(uint32_t) + sizeof(uint32_t)))
        throw std::invalid_argument("COLMAP: oversized rigs.bin count");
    r.rig_ids.reserve(static_cast<size_t>(count));
    r.rig_ref_sensor_types.reserve(static_cast<size_t>(count));
    r.rig_ref_sensor_ids.reserve(static_cast<size_t>(count));
    r.rig_sensor_off.push_back(0);
    for (uint64_t index = 0; index < count; ++index) {
        r.rig_ids.push_back(rd.get<uint32_t>());
        const uint32_t sensor_count = rd.get<uint32_t>();
        if (sensor_count == 0) {
            r.rig_ref_sensor_types.push_back(-1);
            r.rig_ref_sensor_ids.push_back(UINT32_MAX);
            r.rig_sensor_off.push_back(r.rig_sensor_types.size());
            continue;
        }
        r.rig_ref_sensor_types.push_back(checked_sensor_type(
            rd.get<int32_t>(), "rig reference sensor"));
        if (r.rig_ref_sensor_types.back() == -1)
            throw std::invalid_argument(
                "COLMAP: rig reference sensor cannot be INVALID");
        r.rig_ref_sensor_ids.push_back(rd.get<uint32_t>());
        const uint32_t non_reference = sensor_count - 1;
        if (non_reference >
            (b.size() - rd.pos) /
                (sizeof(int32_t) + sizeof(uint32_t) + sizeof(uint8_t)))
            throw std::invalid_argument(
                "COLMAP: oversized rigs.bin sensor count");
        for (uint32_t sensor = 0; sensor < non_reference; ++sensor) {
            const int32_t type = checked_sensor_type(
                rd.get<int32_t>(), "rig sensor");
            if (type == -1)
                throw std::invalid_argument(
                    "COLMAP: non-reference rig sensor cannot be INVALID");
            r.rig_sensor_types.push_back(type);
            r.rig_sensor_ids.push_back(rd.get<uint32_t>());
            const uint8_t has_pose = rd.get<uint8_t>();
            if (has_pose > 1)
                throw std::invalid_argument(
                    "COLMAP: rig sensor pose flag must be zero or one");
            r.rig_sensor_has_pose.push_back(has_pose);
            for (int component = 0; component < 4; ++component)
                r.rig_sensor_quats.push_back(
                    has_pose ? rd.get<double>()
                             : (component == 0 ? 1.0 : 0.0));
            for (int component = 0; component < 3; ++component)
                r.rig_sensor_trans.push_back(
                    has_pose ? rd.get<double>() : 0.0);
        }
        r.rig_sensor_off.push_back(r.rig_sensor_types.size());
    }
    if (rd.pos != rd.n)
        throw std::invalid_argument("COLMAP: trailing bytes in rigs.bin");
}

void read_frames(const std::string &b, Reconstruction &r) {
    LeReader rd(b.data(), b.size());
    const uint64_t count = rd.get<uint64_t>();
    constexpr size_t fixed_size =
        2 * sizeof(uint32_t) + 7 * sizeof(double) + sizeof(uint32_t);
    if (count > (b.size() - sizeof(uint64_t)) / fixed_size)
        throw std::invalid_argument("COLMAP: oversized frames.bin count");
    r.frame_ids.reserve(static_cast<size_t>(count));
    r.frame_rig_ids.reserve(static_cast<size_t>(count));
    r.frame_quats.reserve(static_cast<size_t>(count) * 4);
    r.frame_trans.reserve(static_cast<size_t>(count) * 3);
    r.frame_data_off.push_back(0);
    for (uint64_t index = 0; index < count; ++index) {
        r.frame_ids.push_back(rd.get<uint32_t>());
        r.frame_rig_ids.push_back(rd.get<uint32_t>());
        for (int component = 0; component < 4; ++component)
            r.frame_quats.push_back(rd.get<double>());
        for (int component = 0; component < 3; ++component)
            r.frame_trans.push_back(rd.get<double>());
        const uint32_t data_count = rd.get<uint32_t>();
        constexpr size_t data_size =
            sizeof(int32_t) + sizeof(uint32_t) + sizeof(uint64_t);
        if (data_count > (b.size() - rd.pos) / data_size)
            throw std::invalid_argument(
                "COLMAP: oversized frames.bin data count");
        for (uint32_t data = 0; data < data_count; ++data) {
            const int32_t type =
                checked_sensor_type(rd.get<int32_t>(), "frame data");
            if (type == -1)
                throw std::invalid_argument(
                    "COLMAP: frame data sensor cannot be INVALID");
            r.frame_sensor_types.push_back(type);
            r.frame_sensor_ids.push_back(rd.get<uint32_t>());
            r.frame_data_ids.push_back(rd.get<uint64_t>());
        }
        r.frame_data_off.push_back(r.frame_sensor_types.size());
    }
    if (rd.pos != rd.n)
        throw std::invalid_argument("COLMAP: trailing bytes in frames.bin");
}

void read_images(const std::string &b, Reconstruction &r) {
    LeReader rd(b.data(), b.size());
    const uint64_t n = rd.get<uint64_t>();
    constexpr size_t minimum_image_size =
        sizeof(uint32_t) + 7 * sizeof(double) + sizeof(uint32_t) +
        sizeof(char) + sizeof(uint64_t);
    if (n > (b.size() - sizeof(uint64_t)) / minimum_image_size)
        throw std::invalid_argument(
            "COLMAP: oversized images.bin count");
    r.img_ids.reserve(static_cast<size_t>(n));
    r.quats.reserve(static_cast<size_t>(n) * 4);
    r.trans.reserve(static_cast<size_t>(n) * 3);
    r.img_cam_ids.reserve(static_cast<size_t>(n));
    r.img_names.reserve(static_cast<size_t>(n));
    r.obs_off.reserve(static_cast<size_t>(n) + 1);
    r.obs_off.push_back(0);
    for (uint64_t i = 0; i < n; i++) {
        r.img_ids.push_back(rd.get<uint32_t>());
        for (int k = 0; k < 4; k++) r.quats.push_back(rd.get<double>());
        for (int k = 0; k < 3; k++) r.trans.push_back(rd.get<double>());
        r.img_cam_ids.push_back(rd.get<uint32_t>());
        r.img_names.push_back(rd.get_cstr());
        const uint64_t k = rd.get<uint64_t>();
        constexpr size_t observation_size =
            3 * sizeof(uint64_t);
        if (k > (b.size() - rd.pos) / observation_size ||
            k > (std::numeric_limits<size_t>::max() -
                 r.obs_pt3d.size()) ||
            k > (std::numeric_limits<size_t>::max() -
                 r.obs_xy.size()) / 2)
            throw std::invalid_argument(
                "COLMAP: oversized images.bin observation count");
        for (uint64_t j = 0; j < k; j++) {
            r.obs_xy.push_back(rd.get<double>());
            r.obs_xy.push_back(rd.get<double>());
            const uint64_t pid = rd.get<uint64_t>();
            if (pid != UINT64_MAX &&
                pid > static_cast<uint64_t>(INT64_MAX))
                throw std::invalid_argument(
                    "COLMAP: observation point id exceeds int64");
            r.obs_pt3d.push_back(
                pid == UINT64_MAX ? -1 : static_cast<int64_t>(pid));
        }
        r.obs_off.push_back(r.obs_pt3d.size());
    }
    if (rd.pos != rd.n)
        throw std::invalid_argument(
            "COLMAP: trailing bytes in images.bin");
}
void read_points(const std::string &b, Reconstruction &r) {
    LeReader rd(b.data(), b.size());
    const uint64_t n = rd.get<uint64_t>();
    constexpr size_t minimum_point_size =
        sizeof(uint64_t) + 3 * sizeof(double) +
        3 * sizeof(uint8_t) + sizeof(double) + sizeof(uint64_t);
    if (n > (b.size() - sizeof(uint64_t)) / minimum_point_size)
        throw std::invalid_argument(
            "COLMAP: oversized points3D.bin count");
    r.pt_ids.reserve(static_cast<size_t>(n));
    r.xyz.reserve(static_cast<size_t>(n) * 3);
    r.rgb.reserve(static_cast<size_t>(n) * 3);
    r.err.reserve(static_cast<size_t>(n));
    r.track_off.reserve(static_cast<size_t>(n) + 1);
    r.track_off.push_back(0);
    for (uint64_t i = 0; i < n; i++) {
        r.pt_ids.push_back(rd.get<uint64_t>());
        for (int k = 0; k < 3; k++) r.xyz.push_back(rd.get<double>());
        for (int k = 0; k < 3; k++) r.rgb.push_back(rd.get<uint8_t>());
        r.err.push_back(rd.get<double>());
        const uint64_t t = rd.get<uint64_t>();
        constexpr size_t track_entry_size =
            2 * sizeof(uint32_t);
        if (t > (b.size() - rd.pos) / track_entry_size ||
            t > (std::numeric_limits<size_t>::max() -
                 r.track.size()) / 2)
            throw std::invalid_argument(
                "COLMAP: oversized points3D.bin track count");
        for (uint64_t j = 0; j < t; j++) {
            r.track.push_back(rd.get<uint32_t>());
            r.track.push_back(rd.get<uint32_t>());
        }
        r.track_off.push_back(r.track.size() / 2);
    }
    if (rd.pos != rd.n)
        throw std::invalid_argument(
            "COLMAP: trailing bytes in points3D.bin");
}

Reconstruction read_sparse(const std::string &dir,
                           bool allow_extension_sidecars) {
    nb::gil_scoped_release rel;
    if (!allow_extension_sidecars) require_no_extension_sidecars(dir);
    Reconstruction r;
    const bool has_rigs = path_exists(dir + "/rigs.bin");
    const bool has_frames = path_exists(dir + "/frames.bin");
    if (has_rigs != has_frames)
        throw std::invalid_argument(
            "COLMAP: modern sparse model requires both rigs.bin and "
            "frames.bin");
    r.has_rig_frame_model = has_rigs;
    if (has_rigs) read_rigs(read_file(dir + "/rigs.bin"), r);
    read_cameras(read_file(dir + "/cameras.bin"), r);
    if (has_frames) read_frames(read_file(dir + "/frames.bin"), r);
    read_images(read_file(dir + "/images.bin"), r);
    read_points(read_file(dir + "/points3D.bin"), r);
    validate_colmap_reconstruction(r, "COLMAP");
    return r;
}

Reconstruction read_sparse_image(const std::string &dir, uint32_t image_id) {
    nb::gil_scoped_release rel;
    require_no_extension_sidecars(dir);
    const bool has_rigs = path_exists(dir + "/rigs.bin");
    const bool has_frames = path_exists(dir + "/frames.bin");
    if (has_rigs != has_frames)
        throw std::invalid_argument(
            "COLMAP: modern sparse model requires both rigs.bin and "
            "frames.bin");
    Reconstruction metadata;
    metadata.has_rig_frame_model = has_rigs;
    if (has_rigs) {
        read_rigs(read_file(dir + "/rigs.bin"), metadata);
        read_frames(read_file(dir + "/frames.bin"), metadata);
        validate_colmap_rig_frame_model(metadata, "COLMAP");
    }
    Reconstruction r;
    r.obs_off.push_back(0);
    r.track_off.push_back(0);

    std::ifstream images(native_path(dir + "/images.bin"), std::ios::binary);
    if (!images)
        throw std::invalid_argument("COLMAP: cannot open " + dir +
                                    "/images.bin");
    const uint64_t image_count =
        read_stream_le<uint64_t>(images, "images.bin header");
    // A weak physical bound rejects impossible headers without masking the
    // more specific truncated-name/observation errors for the selected first
    // record. The streaming loop performs exact per-record bounds below.
    constexpr uint64_t minimum_image_size = sizeof(uint32_t);
    if (image_count >
        stream_remaining_bytes(images, "images.bin") /
            minimum_image_size)
        throw std::invalid_argument(
            "COLMAP: oversized images.bin count");
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
            // A partial reconstruction deliberately omits points3D.bin.
            // Preserve the measured 2D coordinates but clear their otherwise
            // dangling point references so the returned model remains valid
            // and can be written as a standalone COLMAP model.
            (void)point_id;
            r.obs_pt3d[j] = -1;
        }
        r.obs_off.push_back(count);
        camera_id = current_camera;
        found = true;
        break;
    }
    if (!found)
        throw std::invalid_argument("COLMAP: image id " +
                                    std::to_string(image_id) + " not found");
    select_colmap_rig_frame_for_image(
        metadata, image_id, r, "COLMAP");
    std::unordered_set<uint32_t> required_camera_ids = {camera_id};
    if (r.has_rig_frame_model) {
        if (r.rig_ref_sensor_types[0] == 0)
            required_camera_ids.insert(r.rig_ref_sensor_ids[0]);
        for (size_t sensor = 0;
             sensor < r.rig_sensor_types.size(); ++sensor)
            if (r.rig_sensor_types[sensor] == 0)
                required_camera_ids.insert(r.rig_sensor_ids[sensor]);
    }

    std::ifstream cameras(native_path(dir + "/cameras.bin"), std::ios::binary);
    if (!cameras)
        throw std::invalid_argument("COLMAP: cannot open " + dir +
                                    "/cameras.bin");
    const uint64_t camera_count =
        read_stream_le<uint64_t>(cameras, "cameras.bin header");
    constexpr uint64_t minimum_camera_size = sizeof(uint32_t);
    if (camera_count >
        stream_remaining_bytes(cameras, "cameras.bin") /
            minimum_camera_size)
        throw std::invalid_argument(
            "COLMAP: oversized cameras.bin count");
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
        if (required_camera_ids.erase(camera.id) != 0)
            r.cameras.push_back(std::move(camera));
    }
    if (required_camera_ids.empty()) {
        validate_colmap_reconstruction(r, "COLMAP");
        return r;
    }
    throw std::invalid_argument(
        "COLMAP: camera id " +
        std::to_string(*std::min_element(
            required_camera_ids.begin(), required_camera_ids.end())) +
        " referenced by the selected image rig was not found");
}

void write_rigs(const Reconstruction &r, const std::string &path) {
    BufferedFileWriter writer(path);
    writer.put<uint64_t>(r.rig_ids.size());
    for (size_t index = 0; index < r.rig_ids.size(); ++index) {
        writer.put<uint32_t>(r.rig_ids[index]);
        const uint64_t begin = r.rig_sensor_off[index];
        const uint64_t end = r.rig_sensor_off[index + 1];
        const bool has_reference =
            r.rig_ref_sensor_types[index] != -1;
        const uint64_t count =
            (has_reference ? uint64_t{1} : uint64_t{0}) + end - begin;
        writer.put<uint32_t>(static_cast<uint32_t>(count));
        if (has_reference) {
            writer.put<int32_t>(r.rig_ref_sensor_types[index]);
            writer.put<uint32_t>(r.rig_ref_sensor_ids[index]);
        }
        for (uint64_t sensor = begin; sensor < end; ++sensor) {
            writer.put<int32_t>(r.rig_sensor_types[sensor]);
            writer.put<uint32_t>(r.rig_sensor_ids[sensor]);
            const uint8_t has_pose = r.rig_sensor_has_pose[sensor];
            writer.put<uint8_t>(has_pose);
            if (has_pose) {
                writer.put_array(
                    r.rig_sensor_quats.data() + sensor * 4, 4);
                writer.put_array(
                    r.rig_sensor_trans.data() + sensor * 3, 3);
            }
        }
    }
    writer.finish();
}

void write_cameras(const Reconstruction &r, const std::string &path) {
    BufferedFileWriter writer(path);
    writer.put<uint64_t>(r.cameras.size());
    for (const auto &c : r.cameras) {
        const ModelInfo model = colmap_model_info(c.model_id);
        if (c.params.size() != static_cast<size_t>(model.nparams))
            throw std::invalid_argument(
                "COLMAP: camera " + std::to_string(c.id) +
                " parameter count does not match model " + model.name);
        writer.put<uint32_t>(c.id);
        writer.put<int32_t>(c.model_id);
        writer.put<uint64_t>(c.width);
        writer.put<uint64_t>(c.height);
        writer.put_array(c.params.data(), c.params.size());
    }
    writer.finish();
}

void write_frames(const Reconstruction &r, const std::string &path) {
    BufferedFileWriter writer(path);
    writer.put<uint64_t>(r.frame_ids.size());
    for (size_t index = 0; index < r.frame_ids.size(); ++index) {
        writer.put<uint32_t>(r.frame_ids[index]);
        writer.put<uint32_t>(r.frame_rig_ids[index]);
        writer.put_array(r.frame_quats.data() + index * 4, 4);
        writer.put_array(r.frame_trans.data() + index * 3, 3);
        const uint64_t begin = r.frame_data_off[index];
        const uint64_t end = r.frame_data_off[index + 1];
        writer.put<uint32_t>(static_cast<uint32_t>(end - begin));
        for (uint64_t data = begin; data < end; ++data) {
            writer.put<int32_t>(r.frame_sensor_types[data]);
            writer.put<uint32_t>(r.frame_sensor_ids[data]);
            writer.put<uint64_t>(r.frame_data_ids[data]);
        }
    }
    writer.finish();
}

void write_images(const Reconstruction &r, const std::string &path) {
    BufferedFileWriter writer(path);
    const uint64_t n = r.num_images();
    writer.put<uint64_t>(n);
    for (uint64_t i = 0; i < n; i++) {
        writer.put<uint32_t>(r.img_ids[i]);
        writer.put_array(r.quats.data() + i * 4, 4);
        writer.put_array(r.trans.data() + i * 3, 3);
        writer.put<uint32_t>(r.img_cam_ids[i]);
        writer.put_cstr(r.img_names[i]);
        uint64_t a = r.obs_off[i], e = r.obs_off[i + 1];
        writer.put<uint64_t>(e - a);
        for (uint64_t j = a; j < e; j++) {
            writer.put_array(r.obs_xy.data() + j * 2, 2);
            int64_t pid = r.obs_pt3d[j];
            writer.put<uint64_t>(
                pid < 0 ? UINT64_MAX : static_cast<uint64_t>(pid));
        }
    }
    writer.finish();
}

void write_points(const Reconstruction &r, const std::string &path) {
    BufferedFileWriter writer(path);
    const uint64_t n = r.num_points();
    writer.put<uint64_t>(n);
    for (uint64_t i = 0; i < n; i++) {
        writer.put<uint64_t>(r.pt_ids[i]);
        writer.put_array(r.xyz.data() + i * 3, 3);
        writer.put_array(r.rgb.data() + i * 3, 3);
        writer.put<double>(r.err[i]);
        uint64_t a = r.track_off[i], e = r.track_off[i + 1];
        writer.put<uint64_t>(e - a);
        writer.put_array(r.track.data() + a * 2, (e - a) * 2);
    }
    writer.finish();
}

void write_sparse(const Reconstruction &r, const std::string &dir,
                  bool allow_extension_sidecars) {
    nb::gil_scoped_release rel;
    validate_colmap_reconstruction(r, "COLMAP");
    if (!allow_extension_sidecars) require_no_extension_sidecars(dir);
    if (!r.has_rig_frame_model &&
        (path_exists(dir + "/rigs.bin") ||
         path_exists(dir + "/frames.bin")))
        throw std::invalid_argument(
            "COLMAP: refusing to leave stale rigs.bin/frames.bin while "
            "writing a legacy sparse model");
    if (r.has_rig_frame_model) write_rigs(r, dir + "/rigs.bin");
    write_cameras(r, dir + "/cameras.bin");
    if (r.has_rig_frame_model) write_frames(r, dir + "/frames.bin");
    write_images(r, dir + "/images.bin");
    write_points(r, dir + "/points3D.bin");
}

}  // namespace

void register_colmap(nb::module_ &m) {
    m.def("read_colmap_sparse",
          [](const std::string &path) { return read_sparse(path, false); },
          "path"_a,
          "Read a legacy three-file or modern five-file COLMAP binary "
          "sparse model directory, preserving rigs and frames.");
    m.def("_read_colmap_sparse_with_sidecars",
          [](const std::string &path) { return read_sparse(path, true); },
          "path"_a,
          "Internal extended-adapter sparse reader.");
    m.def("read_colmap_sparse_image", &read_sparse_image, "path"_a,
          "image_id"_a,
          "Read one COLMAP binary image and its camera without opening "
          "points3D.bin or materializing unrelated images.");
    m.def("write_colmap_sparse",
          [](const Reconstruction &reconstruction,
             const std::string &path) {
              write_sparse(reconstruction, path, false);
          },
          "recon"_a, "path"_a,
          "Write a Reconstruction as a legacy three-file or modern "
          "five-file COLMAP binary sparse model directory using bounded "
          "direct-file streaming.");
}
