#include "bindings/registry.hpp"

void register_ply_mesh(nanobind::module_ &);
void register_obj_mtl(nanobind::module_ &);
void register_stl_off(nanobind::module_ &);
void register_gltf(nanobind::module_ &);

namespace sio::bindings {
namespace {

constexpr RegistrationDescriptor REGISTRATIONS[] = {
    {7, "ply_mesh", &::register_ply_mesh},
    {8, "obj_mtl", &::register_obj_mtl},
    {9, "stl_off", &::register_stl_off},
    {10, "gltf", &::register_gltf},
};

constexpr CodecDescriptor CODECS[] = {
    {6,
     "ply_mesh",
     "meshes",
     symbols("read_ply_mesh"),
     symbols("write_ply_mesh"),
     symbols(),
     symbols("read_ply_mesh"),
     symbols("write_ply_mesh"),
     symbols("read_ply_mesh_faces")},
    {7,
     "obj",
     "meshes",
     symbols("obj_material_library", "read_obj"),
     symbols("write_obj", "write_mtl"),
     symbols("inspect_obj", "inspect_mtl"),
     symbols("obj_material_library", "read_obj"),
     symbols("write_obj", "write_mtl"),
     symbols()},
    {8,
     "stl",
     "meshes",
     symbols("read_stl"),
     symbols("write_stl"),
     symbols("_inspect_stl"),
     symbols("read_stl"),
     symbols("write_stl"),
     symbols("read_stl_faces")},
    {9,
     "off",
     "meshes",
     symbols("read_off"),
     symbols("write_off"),
     symbols("_inspect_off"),
     symbols("read_off"),
     symbols("write_off"),
     symbols("read_off_faces")},
    {10,
     "gltf",
     "meshes",
     symbols("gltf_external_buffer_uris", "read_gltf"),
     symbols("write_gltf", "_write_gltf_to_files"),
     symbols("inspect_gltf"),
     symbols("gltf_external_buffer_uris", "read_gltf"),
     symbols("write_gltf", "_write_gltf_to_files"),
     symbols("read_gltf_mesh", "read_gltf_primitive")},
    {11,
     "glb",
     "meshes",
     symbols("read_glb"),
     symbols("write_glb"),
     symbols("inspect_glb"),
     symbols("read_glb"),
     symbols("write_glb"),
     symbols("read_glb_mesh", "read_glb_primitive")},
};

constexpr FamilyBindings FAMILY{
    "meshes",
    REGISTRATIONS,
    sizeof(REGISTRATIONS) / sizeof(REGISTRATIONS[0]),
    CODECS,
    sizeof(CODECS) / sizeof(CODECS[0]),
};

} // namespace

const FamilyBindings &mesh_bindings() { return FAMILY; }

} // namespace sio::bindings
