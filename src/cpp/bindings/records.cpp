#include "bindings/registry.hpp"

#include <array>
#include <stdexcept>
#include <string>
#include <unordered_set>

void register_reconstruction(nanobind::module_ &);
void register_gaussian_cloud(nanobind::module_ &);
void register_pose_storage(nanobind::module_ &);
void register_tensor_dict(nanobind::module_ &);
void register_image(nanobind::module_ &);
void register_image_sequence(nanobind::module_ &);
void register_point_cloud(nanobind::module_ &);
void register_depth_map(nanobind::module_ &);
void register_flow_field(nanobind::module_ &);
void register_state_trajectory(nanobind::module_ &);
void register_imu(nanobind::module_ &);
void register_camera_rig(nanobind::module_ &);
void register_pose_graph(nanobind::module_ &);
void register_feature_match(nanobind::module_ &);
void register_material_set(nanobind::module_ &);
void register_mesh(nanobind::module_ &);
void register_instance_set(nanobind::module_ &);
void register_scene_graph(nanobind::module_ &);
void register_dense_mvs_records(nanobind::module_ &);
void register_point_scan(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr std::array<RegistrationDescriptor, 20> RECORDS{{
    {0, "reconstruction", &::register_reconstruction},
    {1, "gaussian_cloud", &::register_gaussian_cloud},
    {2, "pose_storage", &::register_pose_storage},
    {3, "tensor_dict", &::register_tensor_dict},
    {4, "image", &::register_image},
    {5, "image_sequence", &::register_image_sequence},
    {6, "point_cloud", &::register_point_cloud},
    {7, "depth_map", &::register_depth_map},
    {8, "flow_field", &::register_flow_field},
    {9, "state_trajectory", &::register_state_trajectory},
    {10, "imu", &::register_imu},
    {11, "camera_rig", &::register_camera_rig},
    {12, "pose_graph", &::register_pose_graph},
    {13, "feature_match", &::register_feature_match},
    {14, "material_set", &::register_material_set},
    {15, "mesh", &::register_mesh},
    {16, "instance_set", &::register_instance_set},
    {17, "scene_graph", &::register_scene_graph},
    {18, "dense_mvs", &::register_dense_mvs_records},
    {19, "point_scan", &::register_point_scan},
}};

} // namespace

void register_records(nb::module_ &module) {
    std::unordered_set<std::string> names;
    for (std::size_t index = 0; index < RECORDS.size(); ++index) {
        const auto &entry = RECORDS[index];
        bool repeated_function = false;
        for (std::size_t previous = 0; previous < index; ++previous)
            repeated_function =
                repeated_function ||
                RECORDS[previous].function == entry.function;
        if (entry.order != index || entry.function == nullptr ||
            entry.name == nullptr || entry.name[0] == '\0' ||
            repeated_function || !names.emplace(entry.name).second) {
            throw std::runtime_error(
                "native record registration table is inconsistent");
        }
        entry.function(module);
    }
}

} // namespace sio::bindings
