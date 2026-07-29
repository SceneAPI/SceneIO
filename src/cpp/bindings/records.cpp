#include "bindings/registry.hpp"

#include <array>
#include <stdexcept>
#include <string>
#include <unordered_set>

void register_reconstruction(nanobind::module_ &);
void register_gaussian_cloud(nanobind::module_ &);
void register_posed_view_set(nanobind::module_ &);
void register_tensor_dict(nanobind::module_ &);
void register_image(nanobind::module_ &);
void register_image_sequence(nanobind::module_ &);
void register_point_cloud(nanobind::module_ &);
void register_depth_map(nanobind::module_ &);
void register_flow_field(nanobind::module_ &);
void register_state_trajectory(nanobind::module_ &);
void register_camera_rig(nanobind::module_ &);
void register_pose_graph(nanobind::module_ &);
void register_feature_match(nanobind::module_ &);
void register_material_set(nanobind::module_ &);
void register_mesh(nanobind::module_ &);
void register_mesh_scene(nanobind::module_ &);
void register_dense_mvs_records(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr std::array<RegistrationDescriptor, 17> RECORDS{{
    {0, "reconstruction", &::register_reconstruction},
    {1, "gaussian_cloud", &::register_gaussian_cloud},
    {2, "posed_view_set", &::register_posed_view_set},
    {3, "tensor_dict", &::register_tensor_dict},
    {4, "image", &::register_image},
    {5, "image_sequence", &::register_image_sequence},
    {6, "point_cloud", &::register_point_cloud},
    {7, "depth_map", &::register_depth_map},
    {8, "flow_field", &::register_flow_field},
    {9, "state_trajectory", &::register_state_trajectory},
    {10, "camera_rig", &::register_camera_rig},
    {11, "pose_graph", &::register_pose_graph},
    {12, "feature_match", &::register_feature_match},
    {13, "material_set", &::register_material_set},
    {14, "mesh", &::register_mesh},
    {15, "mesh_scene", &::register_mesh_scene},
    {16, "dense_mvs", &::register_dense_mvs_records},
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
