// records/reconstruction.cpp — Camera + Reconstruction nanobind bindings.
// Array accessors return zero-copy views (rv_policy::reference_internal keeps
// the owning Record alive); conventions are exposed as metadata.
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <limits>
#include <set>
#include <tuple>
#include <unordered_map>
#include <unordered_set>

#include "records/reconstruction.hpp"

using namespace nb::literals;
using namespace sio;

namespace {
template <typename T>
nb::ndarray<nb::numpy, T> vw(const std::vector<T> &v, std::vector<size_t> shape) {
    return nb::ndarray<nb::numpy, T>(const_cast<T *>(v.data()), shape.size(), shape.data());
}
}  // namespace

void validate_colmap_rig_frame_model(
    const Reconstruction &r, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    if (!r.has_rig_frame_model) {
        if (!r.rig_ids.empty() || !r.rig_ref_sensor_types.empty() ||
            !r.rig_ref_sensor_ids.empty() || !r.rig_sensor_off.empty() ||
            !r.rig_sensor_types.empty() || !r.rig_sensor_ids.empty() ||
            !r.rig_sensor_has_pose.empty() ||
            !r.rig_sensor_quats.empty() || !r.rig_sensor_trans.empty() ||
            !r.frame_ids.empty() || !r.frame_rig_ids.empty() ||
            !r.frame_quats.empty() || !r.frame_trans.empty() ||
            !r.frame_data_off.empty() || !r.frame_sensor_types.empty() ||
            !r.frame_sensor_ids.empty() || !r.frame_data_ids.empty())
            throw std::invalid_argument(
                prefix +
                "rig/frame arrays require has_rig_frame_model");
        return;
    }

    const size_t rigs = r.rig_ids.size();
    const size_t sensors = r.rig_sensor_types.size();
    const size_t frames = r.frame_ids.size();
    const size_t data = r.frame_sensor_types.size();
    if (sensors > std::numeric_limits<size_t>::max() / 4 ||
        frames > std::numeric_limits<size_t>::max() / 4)
        throw std::invalid_argument(
            prefix +
            "rig/frame field extent overflows address space");
    if (r.rig_ref_sensor_types.size() != rigs ||
        r.rig_ref_sensor_ids.size() != rigs ||
        r.rig_sensor_off.size() != rigs + 1 ||
        r.rig_sensor_ids.size() != sensors ||
        r.rig_sensor_has_pose.size() != sensors ||
        r.rig_sensor_quats.size() != sensors * 4 ||
        r.rig_sensor_trans.size() != sensors * 3 ||
        r.frame_rig_ids.size() != frames ||
        r.frame_quats.size() != frames * 4 ||
        r.frame_trans.size() != frames * 3 ||
        r.frame_data_off.size() != frames + 1 ||
        r.frame_sensor_ids.size() != data ||
        r.frame_data_ids.size() != data)
        throw std::invalid_argument(
            prefix + "inconsistent rig/frame field lengths");
    if (r.rig_sensor_off.front() != 0 ||
        r.rig_sensor_off.back() != sensors ||
        r.frame_data_off.front() != 0 ||
        r.frame_data_off.back() != data)
        throw std::invalid_argument(
            prefix +
            "rig/frame offsets do not match value arrays");
    for (size_t index = 0; index < rigs; ++index) {
        if (r.rig_sensor_off[index] > r.rig_sensor_off[index + 1])
            throw std::invalid_argument(
                prefix +
                "rig sensor offsets must be nondecreasing");
        const uint64_t non_reference =
            r.rig_sensor_off[index + 1] - r.rig_sensor_off[index];
        if (non_reference >= std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                prefix + "rig sensor count exceeds uint32");
        if (!valid_colmap_sensor_type(
                r.rig_ref_sensor_types[index]))
            throw std::invalid_argument(
                prefix + "invalid rig reference sensor type");
        const bool has_reference =
            r.rig_ref_sensor_types[index] != -1;
        if (!has_reference &&
            (r.rig_ref_sensor_ids[index] != UINT32_MAX ||
             non_reference != 0))
            throw std::invalid_argument(
                prefix +
                "an empty rig must use the absent reference "
                "sensor sentinel");
    }
    for (size_t index = 0; index < sensors; ++index) {
        if (!valid_colmap_sensor_type(r.rig_sensor_types[index]) ||
            r.rig_sensor_types[index] == -1)
            throw std::invalid_argument(
                prefix +
                "non-reference rig sensor type is invalid");
        if (r.rig_sensor_has_pose[index] > 1)
            throw std::invalid_argument(
                prefix +
                "rig sensor pose flags must be zero or one");
    }
    for (size_t index = 0; index < frames; ++index) {
        if (r.frame_data_off[index] >
            r.frame_data_off[index + 1])
            throw std::invalid_argument(
                prefix +
                "frame data offsets must be nondecreasing");
        if (r.frame_data_off[index + 1] -
                r.frame_data_off[index] >
            std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                prefix + "frame data count exceeds uint32");
    }
    for (int32_t type : r.frame_sensor_types)
        if (!valid_colmap_sensor_type(type) || type == -1)
            throw std::invalid_argument(
                prefix + "frame data sensor type is invalid");
}

void validate_colmap_reconstruction(
    const Reconstruction &r, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    const size_t images = r.num_images();
    const size_t points = r.num_points();
    if (images > std::numeric_limits<size_t>::max() / 4 ||
        points > std::numeric_limits<size_t>::max() / 3 ||
        r.obs_pt3d.size() > std::numeric_limits<size_t>::max() / 2)
        throw std::invalid_argument(
            prefix +
            "reconstruction field extent overflows address space");
    if (r.quats.size() != images * 4 ||
        r.trans.size() != images * 3 ||
        r.img_cam_ids.size() != images ||
        r.img_names.size() != images ||
        r.obs_off.size() != images + 1 ||
        r.obs_xy.size() != r.obs_pt3d.size() * 2 ||
        r.xyz.size() != points * 3 ||
        r.rgb.size() != points * 3 ||
        r.err.size() != points ||
        r.track_off.size() != points + 1 ||
        r.track.size() % 2 != 0)
        throw std::invalid_argument(
            prefix + "inconsistent reconstruction field lengths");
    for (const Camera &camera : r.cameras) {
        const ModelInfo model = colmap_model_info(camera.model_id);
        if (camera.params.size() !=
            static_cast<size_t>(model.nparams))
            throw std::invalid_argument(
                prefix + "camera " + std::to_string(camera.id) +
                " parameter count does not match model " + model.name);
    }
    for (const std::string &name : r.img_names)
        if (name.find('\0') != std::string::npos)
            throw std::invalid_argument(
                prefix + "image names cannot contain NUL bytes");
    for (int64_t point_id : r.obs_pt3d)
        if (point_id < -1)
            throw std::invalid_argument(
                prefix +
                "observation point ids must be -1 or nonnegative");
    if (r.obs_off.front() != 0 ||
        r.obs_off.back() != r.obs_pt3d.size() ||
        r.track_off.front() != 0 ||
        r.track_off.back() != r.track.size() / 2)
        throw std::invalid_argument(
            prefix +
            "reconstruction offsets do not match value arrays");
    for (size_t index = 0; index < images; ++index)
        if (r.obs_off[index] > r.obs_off[index + 1])
            throw std::invalid_argument(
                prefix +
                "observation offsets must be nondecreasing");
    for (size_t index = 0; index < points; ++index)
        if (r.track_off[index] > r.track_off[index + 1])
            throw std::invalid_argument(
                prefix + "track offsets must be nondecreasing");
    validate_colmap_rig_frame_model(r, context);

    // These sentinels are invalid in both legacy three-file and modern
    // five-file COLMAP models.
    for (const Camera &camera : r.cameras)
        if (camera.id == UINT32_MAX)
            throw std::invalid_argument(
                prefix + "camera ids cannot use the invalid sentinel");
    for (size_t image = 0; image < images; ++image) {
        if (r.img_ids[image] == UINT32_MAX)
            throw std::invalid_argument(
                prefix + "image ids cannot use the invalid sentinel");
        if (r.img_cam_ids[image] == UINT32_MAX)
            throw std::invalid_argument(
                prefix +
                "image camera ids cannot use the invalid sentinel");
    }
    for (uint64_t point_id : r.pt_ids)
        if (point_id == UINT64_MAX)
            throw std::invalid_argument(
                prefix + "point3D ids cannot use the invalid sentinel");
    for (size_t entry = 0; entry < r.track.size() / 2; ++entry) {
        if (r.track[entry * 2] == UINT32_MAX)
            throw std::invalid_argument(
                prefix +
                "track image ids cannot use the invalid sentinel");
        if (r.track[entry * 2 + 1] == UINT32_MAX)
            throw std::invalid_argument(
                prefix +
                "track point2D indices cannot use the invalid sentinel");
    }

    // The association pass below is required by the modern rig/frame model:
    // its cross-file references must form one coherent reconstruction before
    // any of the five files is written. Keep the established three-file path
    // at its prior O(N) structural-validation cost.
    if (!r.has_rig_frame_model) return;

    std::unordered_map<uint32_t, size_t> camera_rows;
    camera_rows.reserve(r.cameras.size());
    for (size_t index = 0; index < r.cameras.size(); ++index) {
        if (!camera_rows.emplace(r.cameras[index].id, index).second)
            throw std::invalid_argument(
                prefix + "camera ids must be unique");
    }

    std::unordered_map<uint32_t, size_t> image_rows;
    image_rows.reserve(images);
    for (size_t index = 0; index < images; ++index) {
        if (!image_rows.emplace(r.img_ids[index], index).second)
            throw std::invalid_argument(
                prefix + "image ids must be unique");
        if (camera_rows.count(r.img_cam_ids[index]) == 0)
            throw std::invalid_argument(
                prefix + "image references missing camera " +
                std::to_string(r.img_cam_ids[index]));
    }

    std::unordered_map<uint64_t, size_t> point_rows;
    point_rows.reserve(points);
    for (size_t index = 0; index < points; ++index) {
        if (!point_rows.emplace(r.pt_ids[index], index).second)
            throw std::invalid_argument(
                prefix +
                "point3D ids must be unique");
    }
    for (int64_t point_id : r.obs_pt3d)
        if (point_id >= 0 &&
            point_rows.count(static_cast<uint64_t>(point_id)) == 0)
            throw std::invalid_argument(
                prefix + "observation references missing point3D " +
                std::to_string(point_id));
    for (size_t point = 0; point < points; ++point) {
        for (uint64_t entry = r.track_off[point];
             entry < r.track_off[point + 1]; ++entry) {
            const uint32_t image_id = r.track[entry * 2];
            const uint32_t point2D_index =
                r.track[entry * 2 + 1];
            const auto image = image_rows.find(image_id);
            if (image == image_rows.end())
                throw std::invalid_argument(
                    prefix + "track references missing image " +
                    std::to_string(image_id));
            const size_t row = image->second;
            const uint64_t observation_count =
                r.obs_off[row + 1] - r.obs_off[row];
            if (point2D_index >= observation_count)
                throw std::invalid_argument(
                    prefix +
                    "track point2D index exceeds image observations");
            const uint64_t observation =
                r.obs_off[row] + point2D_index;
            if (r.obs_pt3d[observation] !=
                static_cast<int64_t>(r.pt_ids[point]))
                throw std::invalid_argument(
                    prefix +
                    "track and observation point3D ids disagree");
        }
    }

    std::unordered_map<uint32_t, size_t> rig_rows;
    rig_rows.reserve(r.num_rigs());
    std::vector<std::set<uint64_t>> rig_sensors(r.num_rigs());
    auto sensor_key = [](int32_t type, uint32_t id) {
        return (static_cast<uint64_t>(
                    static_cast<uint32_t>(type + 1))
                << 32) |
               id;
    };
    for (size_t rig = 0; rig < r.num_rigs(); ++rig) {
        if (r.rig_ids[rig] == UINT32_MAX)
            throw std::invalid_argument(
                prefix + "rig ids cannot use the invalid sentinel");
        if (!rig_rows.emplace(r.rig_ids[rig], rig).second)
            throw std::invalid_argument(
                prefix + "rig ids must be unique");
        auto &sensors = rig_sensors[rig];
        if (r.rig_ref_sensor_types[rig] != -1) {
            const int32_t type = r.rig_ref_sensor_types[rig];
            const uint32_t id = r.rig_ref_sensor_ids[rig];
            if (id == UINT32_MAX)
                throw std::invalid_argument(
                    prefix +
                    "rig sensor ids cannot use the invalid sentinel");
            sensors.insert(sensor_key(type, id));
            if (type == 0 && camera_rows.count(id) == 0)
                throw std::invalid_argument(
                    prefix + "rig references missing camera " +
                    std::to_string(id));
        }
        for (uint64_t sensor = r.rig_sensor_off[rig];
             sensor < r.rig_sensor_off[rig + 1]; ++sensor) {
            const int32_t type = r.rig_sensor_types[sensor];
            const uint32_t id = r.rig_sensor_ids[sensor];
            if (id == UINT32_MAX)
                throw std::invalid_argument(
                    prefix +
                    "rig sensor ids cannot use the invalid sentinel");
            if (!sensors.insert(sensor_key(type, id)).second)
                throw std::invalid_argument(
                    prefix + "rig sensors must be unique");
            if (type == 0 && camera_rows.count(id) == 0)
                throw std::invalid_argument(
                    prefix + "rig references missing camera " +
                    std::to_string(id));
        }
    }

    std::unordered_set<uint32_t> frame_ids;
    frame_ids.reserve(r.num_frames());
    std::unordered_map<uint32_t, size_t> image_assignments;
    for (size_t frame = 0; frame < r.num_frames(); ++frame) {
        if (r.frame_ids[frame] == UINT32_MAX)
            throw std::invalid_argument(
                prefix + "frame ids cannot use the invalid sentinel");
        if (!frame_ids.insert(r.frame_ids[frame]).second)
            throw std::invalid_argument(
                prefix + "frame ids must be unique");
        const auto rig = rig_rows.find(r.frame_rig_ids[frame]);
        if (rig == rig_rows.end())
            throw std::invalid_argument(
                prefix + "frame references missing rig " +
                std::to_string(r.frame_rig_ids[frame]));
        const auto &sensors = rig_sensors[rig->second];
        std::set<std::tuple<int32_t, uint32_t, uint64_t>> data_ids;
        for (uint64_t data = r.frame_data_off[frame];
             data < r.frame_data_off[frame + 1]; ++data) {
            const int32_t type = r.frame_sensor_types[data];
            const uint32_t sensor_id = r.frame_sensor_ids[data];
            const uint64_t data_id = r.frame_data_ids[data];
            if (sensor_id == UINT32_MAX)
                throw std::invalid_argument(
                    prefix +
                    "frame sensor ids cannot use the invalid sentinel");
            if (data_id == UINT32_MAX)
                throw std::invalid_argument(
                    prefix +
                    "frame data ids cannot use the invalid sentinel");
            if (sensors.count(sensor_key(type, sensor_id)) == 0)
                throw std::invalid_argument(
                    prefix +
                    "frame data sensor does not belong to its rig");
            if (!data_ids.emplace(type, sensor_id, data_id).second)
                throw std::invalid_argument(
                    prefix + "frame data ids must be unique");
            if (type != 0) continue;
            if (data_id > UINT32_MAX)
                throw std::invalid_argument(
                    prefix + "camera data id exceeds uint32");
            const uint32_t image_id = static_cast<uint32_t>(data_id);
            const auto image = image_rows.find(image_id);
            if (image == image_rows.end())
                throw std::invalid_argument(
                    prefix + "frame references missing image " +
                    std::to_string(image_id));
            if (r.img_cam_ids[image->second] != sensor_id)
                throw std::invalid_argument(
                    prefix +
                    "frame camera sensor disagrees with image camera");
            ++image_assignments[image_id];
        }
    }
    for (uint32_t image_id : r.img_ids)
        if (image_assignments[image_id] != 1)
            throw std::invalid_argument(
                prefix + "image " + std::to_string(image_id) +
                " must belong to exactly one frame");
}

void select_colmap_rig_frame_for_image(
    const Reconstruction &source, uint32_t image_id,
    Reconstruction &destination, const char *context) {
    if (!source.has_rig_frame_model) return;
    validate_colmap_rig_frame_model(source, context);
    const std::string prefix = std::string(context) + ": ";

    size_t frame_index = source.num_frames();
    size_t selected_data_index = source.frame_data_ids.size();
    for (size_t index = 0; index < source.num_frames(); ++index) {
        const uint64_t begin = source.frame_data_off[index];
        const uint64_t end = source.frame_data_off[index + 1];
        for (uint64_t data = begin; data < end; ++data) {
            if (source.frame_sensor_types[data] == 0 &&
                source.frame_data_ids[data] == image_id) {
                if (frame_index != source.num_frames())
                    throw std::invalid_argument(
                        prefix + "image " +
                        std::to_string(image_id) +
                        " belongs to more than one frame");
                frame_index = index;
                selected_data_index = static_cast<size_t>(data);
            }
        }
    }
    if (frame_index == source.num_frames())
        throw std::invalid_argument(
            prefix + "image " + std::to_string(image_id) +
            " has no frame assignment");

    const uint32_t rig_id = source.frame_rig_ids[frame_index];
    size_t rig_index = source.num_rigs();
    for (size_t index = 0; index < source.num_rigs(); ++index) {
        if (source.rig_ids[index] != rig_id) continue;
        if (rig_index != source.num_rigs())
            throw std::invalid_argument(
                prefix + "duplicate rig id " +
                std::to_string(rig_id));
        rig_index = index;
    }
    if (rig_index == source.num_rigs())
        throw std::invalid_argument(
            prefix + "frame references missing rig " +
            std::to_string(rig_id));

    destination.has_rig_frame_model = true;
    destination.rig_ids.push_back(rig_id);
    destination.rig_ref_sensor_types.push_back(
        source.rig_ref_sensor_types[rig_index]);
    destination.rig_ref_sensor_ids.push_back(
        source.rig_ref_sensor_ids[rig_index]);
    const uint64_t sensor_begin =
        source.rig_sensor_off[rig_index];
    const uint64_t sensor_end =
        source.rig_sensor_off[rig_index + 1];
    destination.rig_sensor_off = {0, sensor_end - sensor_begin};
    for (uint64_t sensor = sensor_begin; sensor < sensor_end; ++sensor) {
        destination.rig_sensor_types.push_back(
            source.rig_sensor_types[sensor]);
        destination.rig_sensor_ids.push_back(
            source.rig_sensor_ids[sensor]);
        destination.rig_sensor_has_pose.push_back(
            source.rig_sensor_has_pose[sensor]);
        destination.rig_sensor_quats.insert(
            destination.rig_sensor_quats.end(),
            source.rig_sensor_quats.begin() +
                static_cast<size_t>(sensor) * 4,
            source.rig_sensor_quats.begin() +
                static_cast<size_t>(sensor) * 4 + 4);
        destination.rig_sensor_trans.insert(
            destination.rig_sensor_trans.end(),
            source.rig_sensor_trans.begin() +
                static_cast<size_t>(sensor) * 3,
            source.rig_sensor_trans.begin() +
                static_cast<size_t>(sensor) * 3 + 3);
    }

    destination.frame_ids.push_back(source.frame_ids[frame_index]);
    destination.frame_rig_ids.push_back(rig_id);
    destination.frame_quats.insert(
        destination.frame_quats.end(),
        source.frame_quats.begin() + frame_index * 4,
        source.frame_quats.begin() + frame_index * 4 + 4);
    destination.frame_trans.insert(
        destination.frame_trans.end(),
        source.frame_trans.begin() + frame_index * 3,
        source.frame_trans.begin() + frame_index * 3 + 3);
    destination.frame_data_off = {0, 1};
    destination.frame_sensor_types.push_back(
        source.frame_sensor_types[selected_data_index]);
    destination.frame_sensor_ids.push_back(
        source.frame_sensor_ids[selected_data_index]);
    destination.frame_data_ids.push_back(
        source.frame_data_ids[selected_data_index]);
    validate_colmap_rig_frame_model(destination, context);
}

void register_reconstruction(nb::module_ &m) {
    nb::class_<CameraIntrinsics>(m, "CameraIntrinsics")
        .def_ro("model_id", &CameraIntrinsics::model_id)
        .def_prop_ro("model", [](const CameraIntrinsics &c) {
            return colmap_model_info(c.model_id).name;
        })
        .def_ro("width", &CameraIntrinsics::width)
        .def_ro("height", &CameraIntrinsics::height)
        .def_prop_ro("params", [](const CameraIntrinsics &c) {
            return vw(c.params, {c.params.size()});
        })
        .def("__repr__", [](const CameraIntrinsics &c) {
            return "<CameraIntrinsics model=" + std::string(colmap_model_info(c.model_id).name) +
                   " " + std::to_string(c.width) + "x" + std::to_string(c.height) + ">";
        });

    auto ri = nb::rv_policy::reference_internal;
    nb::class_<Reconstruction>(m, "Reconstruction")
        .def_prop_ro("num_cameras", [](const Reconstruction &r) { return r.cameras.size(); })
        .def_prop_ro("num_images", [](const Reconstruction &r) { return r.num_images(); })
        .def_prop_ro("num_points3D", [](const Reconstruction &r) { return r.num_points(); })
        .def_ro("has_rig_frame_model", &Reconstruction::has_rig_frame_model)
        .def_prop_ro("num_rigs", [](const Reconstruction &r) { return r.num_rigs(); })
        .def_prop_ro("num_frames", [](const Reconstruction &r) { return r.num_frames(); })
        .def_prop_ro("camera_ids", [](const Reconstruction &r) {
            return ::camera_ids(r.cameras);
        })
        .def_prop_ro("cameras", [](const Reconstruction &r) {
            return camera_intrinsics(r.cameras);
        })
        .def_prop_ro("image_ids", [](const Reconstruction &r) { return vw(r.img_ids, {r.num_images()}); }, ri)
        .def_prop_ro("quaternions", [](const Reconstruction &r) { return vw(r.quats, {r.num_images(), 4}); }, ri)
        .def_prop_ro("translations", [](const Reconstruction &r) { return vw(r.trans, {r.num_images(), 3}); }, ri)
        .def_prop_ro("image_camera_ids", [](const Reconstruction &r) { return vw(r.img_cam_ids, {r.num_images()}); }, ri)
        .def_prop_ro("image_names", [](const Reconstruction &r) { return r.img_names; })
        .def_prop_ro("_observation_offsets", [](const Reconstruction &r) {
            return vw(r.obs_off, {r.obs_off.size()});
        }, ri)
        .def_prop_ro("_observation_point3D_ids", [](const Reconstruction &r) {
            return vw(r.obs_pt3d, {r.obs_pt3d.size()});
        }, ri)
        .def_prop_ro("point3D_ids", [](const Reconstruction &r) { return vw(r.pt_ids, {r.num_points()}); }, ri)
        .def_prop_ro("xyz", [](const Reconstruction &r) { return vw(r.xyz, {r.num_points(), 3}); }, ri)
        .def_prop_ro("rgb", [](const Reconstruction &r) { return vw(r.rgb, {r.num_points(), 3}); }, ri)
        .def_prop_ro("errors", [](const Reconstruction &r) { return vw(r.err, {r.num_points()}); }, ri)
        .def_prop_ro("rig_ids", [](const Reconstruction &r) {
            return vw(r.rig_ids, {r.num_rigs()});
        }, ri)
        .def_prop_ro("rig_reference_sensor_types", [](const Reconstruction &r) {
            return vw(r.rig_ref_sensor_types, {r.num_rigs()});
        }, ri)
        .def_prop_ro("rig_reference_sensor_ids", [](const Reconstruction &r) {
            return vw(r.rig_ref_sensor_ids, {r.num_rigs()});
        }, ri)
        .def_prop_ro("rig_sensor_offsets", [](const Reconstruction &r) {
            return vw(r.rig_sensor_off, {r.rig_sensor_off.size()});
        }, ri)
        .def_prop_ro("rig_sensor_types", [](const Reconstruction &r) {
            return vw(r.rig_sensor_types, {r.rig_sensor_types.size()});
        }, ri)
        .def_prop_ro("rig_sensor_ids", [](const Reconstruction &r) {
            return vw(r.rig_sensor_ids, {r.rig_sensor_ids.size()});
        }, ri)
        .def_prop_ro("rig_sensor_has_pose", [](const Reconstruction &r) {
            return vw(r.rig_sensor_has_pose, {r.rig_sensor_has_pose.size()});
        }, ri)
        .def_prop_ro("rig_sensor_quaternions", [](const Reconstruction &r) {
            return vw(r.rig_sensor_quats, {r.rig_sensor_types.size(), 4});
        }, ri)
        .def_prop_ro("rig_sensor_translations", [](const Reconstruction &r) {
            return vw(r.rig_sensor_trans, {r.rig_sensor_types.size(), 3});
        }, ri)
        .def_prop_ro("frame_ids", [](const Reconstruction &r) {
            return vw(r.frame_ids, {r.num_frames()});
        }, ri)
        .def_prop_ro("frame_rig_ids", [](const Reconstruction &r) {
            return vw(r.frame_rig_ids, {r.num_frames()});
        }, ri)
        .def_prop_ro("frame_quaternions", [](const Reconstruction &r) {
            return vw(r.frame_quats, {r.num_frames(), 4});
        }, ri)
        .def_prop_ro("frame_translations", [](const Reconstruction &r) {
            return vw(r.frame_trans, {r.num_frames(), 3});
        }, ri)
        .def_prop_ro("frame_data_offsets", [](const Reconstruction &r) {
            return vw(r.frame_data_off, {r.frame_data_off.size()});
        }, ri)
        .def_prop_ro("frame_sensor_types", [](const Reconstruction &r) {
            return vw(r.frame_sensor_types, {r.frame_sensor_types.size()});
        }, ri)
        .def_prop_ro("frame_sensor_ids", [](const Reconstruction &r) {
            return vw(r.frame_sensor_ids, {r.frame_sensor_ids.size()});
        }, ri)
        .def_prop_ro("frame_data_ids", [](const Reconstruction &r) {
            return vw(r.frame_data_ids, {r.frame_data_ids.size()});
        }, ri)
        // conventions (metadata, not comments)
        .def_prop_ro("quaternion_order", [](const Reconstruction &) { return "wxyz"; })
        .def_prop_ro("pose_convention", [](const Reconstruction &) { return "world_to_camera"; })
        .def("__repr__", [](const Reconstruction &r) {
            return "<Reconstruction cameras=" + std::to_string(r.cameras.size()) +
                   " images=" + std::to_string(r.num_images()) +
                   " points3D=" + std::to_string(r.num_points()) + ">";
        });
}
