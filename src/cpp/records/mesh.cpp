// records/mesh.cpp -- Mesh validation, factory, and nanobind surface.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>

#include <cmath>
#include <limits>
#include <optional>
#include <string>

#include "records/mesh.hpp"

using namespace nb::literals;

namespace {

using f32_array =
    nb::ndarray<const float, nb::c_contig, nb::device::cpu>;
using f64_array =
    nb::ndarray<const double, nb::c_contig, nb::device::cpu>;
using u8_array =
    nb::ndarray<const uint8_t, nb::c_contig, nb::device::cpu>;
using u64_array =
    nb::ndarray<const uint64_t, nb::c_contig, nb::device::cpu>;
using i32_array =
    nb::ndarray<const int32_t, nb::c_contig, nb::device::cpu>;

template <typename T>
void assign_nonempty(std::vector<T> &target, const T *data, size_t count) {
    if (count != 0) target.assign(data, data + count);
}
template <typename T>
nb::ndarray<nb::numpy, T> mesh_view(
    const std::vector<T> &values, std::vector<size_t> shape) {
    static T sentinel{};
    T *data = values.empty() ? &sentinel
                             : const_cast<T *>(values.data());
    return nb::ndarray<nb::numpy, T>(
        data, shape.size(), shape.data());
}

void require_f32_shape(
    const f32_array &array, size_t rows, size_t columns,
    const char *name) {
    if (array.ndim() != 2 || array.shape(0) != rows ||
        array.shape(1) != columns)
        throw std::invalid_argument(
            std::string("mesh: ") + name + " must be (" +
            std::to_string(rows) + "," + std::to_string(columns) +
            ") float32");
}

void require_u8_shape(
    const u8_array &array, size_t rows, size_t columns,
    const char *name) {
    if (array.ndim() != 2 || array.shape(0) != rows ||
        array.shape(1) != columns)
        throw std::invalid_argument(
            std::string("mesh: ") + name + " must be (" +
            std::to_string(rows) + "," + std::to_string(columns) +
            ") uint8");
}

Mesh make_mesh(
    f32_array positions, u64_array face_offsets,
    u64_array face_indices,
    std::optional<f32_array> vertex_normals,
    std::optional<f32_array> corner_normals,
    std::optional<f32_array> vertex_uvs,
    std::optional<f32_array> corner_uvs,
    std::optional<u8_array> vertex_colors,
    std::optional<u8_array> corner_colors,
    std::optional<u64_array> primitive_offsets,
    std::optional<i32_array> primitive_materials,
    const std::string &coordinate_frame,
    double scale_to_meters,
    std::optional<f64_array> local_transform) {
    if (positions.ndim() != 2 || positions.shape(1) != 3)
        throw std::invalid_argument(
            "mesh: positions must be (N,3) float32");
    if (face_offsets.ndim() != 1 ||
        face_offsets.shape(0) == 0)
        throw std::invalid_argument(
            "mesh: face_offsets must be a non-empty (F+1,) uint64 array");
    if (face_indices.ndim() != 1)
        throw std::invalid_argument(
            "mesh: face_indices must be (C,) uint64");

    Mesh mesh;
    mesh.n = positions.shape(0);
    mesh.f = face_offsets.shape(0) - 1;
    mesh.c = face_indices.shape(0);
    mesh.coordinate_frame = coordinate_frame;
    mesh.scale_to_meters = scale_to_meters;

    if (mesh.n > std::numeric_limits<size_t>::max() / 4 ||
        mesh.c > std::numeric_limits<size_t>::max() / 4)
        throw std::invalid_argument(
            "mesh: record extents overflow address space");

    if (vertex_normals)
        require_f32_shape(
            *vertex_normals, mesh.n, 3, "vertex_normals");
    if (corner_normals)
        require_f32_shape(
            *corner_normals, mesh.c, 3, "corner_normals");
    if (vertex_uvs)
        require_f32_shape(*vertex_uvs, mesh.n, 2, "vertex_uvs");
    if (corner_uvs)
        require_f32_shape(*corner_uvs, mesh.c, 2, "corner_uvs");
    if (vertex_colors)
        require_u8_shape(
            *vertex_colors, mesh.n, 4, "vertex_colors");
    if (corner_colors)
        require_u8_shape(
            *corner_colors, mesh.c, 4, "corner_colors");

    if (primitive_offsets) {
        if (primitive_offsets->ndim() != 1 ||
            primitive_offsets->shape(0) == 0)
            throw std::invalid_argument(
                "mesh: primitive_offsets must be a non-empty (P+1,) "
                "uint64 array");
        const size_t primitives = primitive_offsets->shape(0) - 1;
        if (primitive_materials) {
            if (primitive_materials->ndim() != 1 ||
                primitive_materials->shape(0) != primitives)
                throw std::invalid_argument(
                    "mesh: primitive_materials must be (P,) int32");
        }
        assign_nonempty(
            mesh.primitive_offsets, primitive_offsets->data(),
            primitives + 1);
        if (primitive_materials)
            assign_nonempty(
                mesh.primitive_materials,
                primitive_materials->data(), primitives);
        else
            mesh.primitive_materials.assign(primitives, -1);
    } else {
        if (primitive_materials)
            throw std::invalid_argument(
                "mesh: primitive_materials requires primitive_offsets");
        mesh.primitive_offsets = {0};
        if (mesh.f != 0) {
            mesh.primitive_offsets.push_back(
                static_cast<uint64_t>(mesh.f));
            mesh.primitive_materials.push_back(-1);
        }
    }

    if (local_transform) {
        if (local_transform->ndim() != 2 ||
            local_transform->shape(0) != 4 ||
            local_transform->shape(1) != 4)
            throw std::invalid_argument(
                "mesh: local_transform must be (4,4) float64");
        for (size_t index = 0; index < 16; ++index)
            mesh.local_transform[index] =
                local_transform->data()[index];
    }

    {
        nb::gil_scoped_release release;
        assign_nonempty(
            mesh.positions, positions.data(), mesh.n * 3);
        assign_nonempty(
            mesh.face_offsets, face_offsets.data(), mesh.f + 1);
        assign_nonempty(
            mesh.face_indices, face_indices.data(), mesh.c);
        if (vertex_normals)
            assign_nonempty(
                mesh.vertex_normals, vertex_normals->data(),
                mesh.n * 3);
        if (corner_normals)
            assign_nonempty(
                mesh.corner_normals, corner_normals->data(),
                mesh.c * 3);
        if (vertex_uvs)
            assign_nonempty(
                mesh.vertex_uvs, vertex_uvs->data(), mesh.n * 2);
        if (corner_uvs)
            assign_nonempty(
                mesh.corner_uvs, corner_uvs->data(), mesh.c * 2);
        if (vertex_colors)
            assign_nonempty(
                mesh.vertex_colors, vertex_colors->data(),
                mesh.n * 4);
        if (corner_colors)
            assign_nonempty(
                mesh.corner_colors, corner_colors->data(),
                mesh.c * 4);
        validate_mesh(mesh);
    }
    return mesh;
}

}  // namespace

void validate_mesh(const Mesh &mesh, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    if (mesh.n > std::numeric_limits<size_t>::max() / 4 ||
        mesh.c > std::numeric_limits<size_t>::max() / 4 ||
        mesh.positions.size() != mesh.n * 3 ||
        mesh.face_offsets.size() != mesh.f + 1 ||
        mesh.face_indices.size() != mesh.c)
        throw std::invalid_argument(
            prefix + "inconsistent required mesh field lengths");

    auto optional_size = [&](size_t actual, size_t expected,
                             const char *name) {
        if (actual != 0 && actual != expected)
            throw std::invalid_argument(
                prefix + "inconsistent " + name + " field length");
    };
    optional_size(
        mesh.vertex_normals.size(), mesh.n * 3, "vertex_normals");
    optional_size(
        mesh.corner_normals.size(), mesh.c * 3, "corner_normals");
    optional_size(mesh.vertex_uvs.size(), mesh.n * 2, "vertex_uvs");
    optional_size(mesh.corner_uvs.size(), mesh.c * 2, "corner_uvs");
    optional_size(
        mesh.vertex_colors.size(), mesh.n * 4, "vertex_colors");
    optional_size(
        mesh.corner_colors.size(), mesh.c * 4, "corner_colors");

    if (mesh.face_offsets.empty() || mesh.face_offsets[0] != 0 ||
        mesh.face_offsets.back() != mesh.c)
        throw std::invalid_argument(
            prefix +
            "face_offsets must start at zero and end at num_corners");
    for (size_t face = 0; face < mesh.f; ++face) {
        const uint64_t begin = mesh.face_offsets[face];
        const uint64_t end = mesh.face_offsets[face + 1];
        if (end < begin)
            throw std::invalid_argument(
                prefix + "face_offsets must be monotonic");
        if (end - begin < 3)
            throw std::invalid_argument(
                prefix + "every face must have at least three corners");
    }
    for (uint64_t index : mesh.face_indices)
        if (index >= mesh.n)
            throw std::invalid_argument(
                prefix + "face index is outside the vertex domain");

    if (mesh.primitive_offsets.empty() ||
        mesh.primitive_offsets[0] != 0 ||
        mesh.primitive_offsets.back() != mesh.f ||
        mesh.primitive_materials.size() + 1 !=
            mesh.primitive_offsets.size())
        throw std::invalid_argument(
            prefix + "primitive ranges must partition every face");
    for (size_t primitive = 0;
         primitive < mesh.primitive_materials.size(); ++primitive) {
        if (mesh.primitive_offsets[primitive + 1] <=
            mesh.primitive_offsets[primitive])
            throw std::invalid_argument(
                prefix + "primitive ranges must be non-empty");
        if (mesh.primitive_materials[primitive] < -1)
            throw std::invalid_argument(
                prefix + "material indices must be -1 or nonnegative");
    }

    if (!mesh_valid_frame(mesh.coordinate_frame))
        throw std::invalid_argument(
            prefix +
            "coordinate_frame must be unknown|opencv|opengl|enu|ned");
    if (!std::isfinite(mesh.scale_to_meters) ||
        mesh.scale_to_meters <= 0.0)
        throw std::invalid_argument(
            prefix + "scale_to_meters must be finite and positive");

    auto finite = [&](const std::vector<float> &values,
                      const char *name) {
        for (float value : values)
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    prefix + name + " values must be finite");
    };
    finite(mesh.positions, "position");
    finite(mesh.vertex_normals, "vertex normal");
    finite(mesh.corner_normals, "corner normal");
    finite(mesh.vertex_uvs, "vertex UV");
    finite(mesh.corner_uvs, "corner UV");
    for (double value : mesh.local_transform)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                prefix + "local_transform values must be finite");
}

void register_mesh(nb::module_ &module) {
    const auto reference_internal = nb::rv_policy::reference_internal;
    nb::class_<Mesh>(module, "Mesh")
        .def_prop_ro(
            "num_vertices",
            [](const Mesh &mesh) { return mesh.num_vertices(); })
        .def_prop_ro(
            "num_faces",
            [](const Mesh &mesh) { return mesh.num_faces(); })
        .def_prop_ro(
            "num_corners",
            [](const Mesh &mesh) { return mesh.num_corners(); })
        .def_prop_ro(
            "num_primitives",
            [](const Mesh &mesh) { return mesh.num_primitives(); })
        .def_prop_ro(
            "positions",
            [](const Mesh &mesh) {
                return mesh_view(mesh.positions, {mesh.n, 3});
            },
            reference_internal)
        .def_prop_ro(
            "face_offsets",
            [](const Mesh &mesh) {
                return mesh_view(mesh.face_offsets, {mesh.f + 1});
            },
            reference_internal)
        .def_prop_ro(
            "face_indices",
            [](const Mesh &mesh) {
                return mesh_view(mesh.face_indices, {mesh.c});
            },
            reference_internal)
        .def_prop_ro(
            "vertex_normals",
            [](const Mesh &mesh) {
                return mesh_view(
                    mesh.vertex_normals,
                    {mesh.has_vertex_normals() ? mesh.n : 0, 3});
            },
            reference_internal)
        .def_prop_ro(
            "corner_normals",
            [](const Mesh &mesh) {
                return mesh_view(
                    mesh.corner_normals,
                    {mesh.has_corner_normals() ? mesh.c : 0, 3});
            },
            reference_internal)
        .def_prop_ro(
            "vertex_uvs",
            [](const Mesh &mesh) {
                return mesh_view(
                    mesh.vertex_uvs,
                    {mesh.has_vertex_uvs() ? mesh.n : 0, 2});
            },
            reference_internal)
        .def_prop_ro(
            "corner_uvs",
            [](const Mesh &mesh) {
                return mesh_view(
                    mesh.corner_uvs,
                    {mesh.has_corner_uvs() ? mesh.c : 0, 2});
            },
            reference_internal)
        .def_prop_ro(
            "vertex_colors",
            [](const Mesh &mesh) {
                return mesh_view(
                    mesh.vertex_colors,
                    {mesh.has_vertex_colors() ? mesh.n : 0, 4});
            },
            reference_internal)
        .def_prop_ro(
            "corner_colors",
            [](const Mesh &mesh) {
                return mesh_view(
                    mesh.corner_colors,
                    {mesh.has_corner_colors() ? mesh.c : 0, 4});
            },
            reference_internal)
        .def_prop_ro(
            "primitive_offsets",
            [](const Mesh &mesh) {
                return mesh_view(
                    mesh.primitive_offsets,
                    {mesh.primitive_offsets.size()});
            },
            reference_internal)
        .def_prop_ro(
            "primitive_materials",
            [](const Mesh &mesh) {
                return mesh_view(
                    mesh.primitive_materials,
                    {mesh.primitive_materials.size()});
            },
            reference_internal)
        .def_prop_ro(
            "local_transform",
            [](const Mesh &mesh) {
                return nb::ndarray<nb::numpy, double>(
                    const_cast<double *>(mesh.local_transform),
                    {4, 4});
            },
            reference_internal)
        .def_ro("coordinate_frame", &Mesh::coordinate_frame)
        .def_ro("scale_to_meters", &Mesh::scale_to_meters)
        .def_prop_ro(
            "has_vertex_normals",
            [](const Mesh &mesh) { return mesh.has_vertex_normals(); })
        .def_prop_ro(
            "has_corner_normals",
            [](const Mesh &mesh) { return mesh.has_corner_normals(); })
        .def_prop_ro(
            "has_vertex_uvs",
            [](const Mesh &mesh) { return mesh.has_vertex_uvs(); })
        .def_prop_ro(
            "has_corner_uvs",
            [](const Mesh &mesh) { return mesh.has_corner_uvs(); })
        .def_prop_ro(
            "has_vertex_colors",
            [](const Mesh &mesh) { return mesh.has_vertex_colors(); })
        .def_prop_ro(
            "has_corner_colors",
            [](const Mesh &mesh) { return mesh.has_corner_colors(); })
        .def(
            "__repr__",
            [](const Mesh &mesh) {
                return "<Mesh vertices=" + std::to_string(mesh.n) +
                       " faces=" + std::to_string(mesh.f) +
                       " corners=" + std::to_string(mesh.c) +
                       " primitives=" +
                       std::to_string(mesh.num_primitives()) + ">";
            });

    module.def(
        "mesh", &make_mesh,
        "positions"_a, "face_offsets"_a, "face_indices"_a,
        "vertex_normals"_a = nb::none(),
        "corner_normals"_a = nb::none(),
        "vertex_uvs"_a = nb::none(),
        "corner_uvs"_a = nb::none(),
        "vertex_colors"_a = nb::none(),
        "corner_colors"_a = nb::none(),
        "primitive_offsets"_a = nb::none(),
        "primitive_materials"_a = nb::none(),
        "coordinate_frame"_a = "unknown",
        "scale_to_meters"_a = 1.0,
        "local_transform"_a = nb::none(),
        "Build a polygon-preserving Mesh from contiguous canonical arrays.");
}
