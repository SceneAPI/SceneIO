// records/material_set.cpp -- MaterialSet validation, factory, and bindings.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <cmath>
#include <iterator>
#include <limits>
#include <optional>
#include <string>
#include <unordered_set>

#include "records/material_set.hpp"

using namespace nb::literals;

namespace {

constexpr size_t kStringLimit = 1024 * 1024;

using f32_array =
    nb::ndarray<const float, nb::c_contig, nb::device::cpu>;
using u32_array =
    nb::ndarray<const uint32_t, nb::c_contig, nb::device::cpu>;
using u64_array =
    nb::ndarray<const uint64_t, nb::c_contig, nb::device::cpu>;

struct TextureBindingKey {
    uint64_t material;
    uint8_t semantic;

    bool operator==(const TextureBindingKey &other) const {
        return material == other.material &&
               semantic == other.semantic;
    }
};

struct TextureBindingHash {
    size_t operator()(const TextureBindingKey &value) const {
        const size_t material =
            std::hash<uint64_t>{}(value.material);
        const size_t semantic =
            std::hash<uint8_t>{}(value.semantic);
        return material ^ (
            semantic + 0x9e3779b9U + (material << 6) +
            (material >> 2));
    }
};

template <typename T>
nb::ndarray<nb::numpy, T> material_view(
    const std::vector<T> &values, std::vector<size_t> shape) {
    static T sentinel{};
    T *data = values.empty() ? &sentinel
                             : const_cast<T *>(values.data());
    return nb::ndarray<nb::numpy, T>(
        data, shape.size(), shape.data());
}

template <typename T>
nb::ndarray<nb::numpy, const T> material_const_view(
    const std::vector<T> &values, std::vector<size_t> shape) {
    static const T sentinel{};
    const T *data = values.empty() ? &sentinel : values.data();
    return nb::ndarray<nb::numpy, const T>(
        data, shape.size(), shape.data());
}

void validate_text(
    const std::string &value, const char *context,
    bool allow_empty = false) {
    if (!allow_empty && value.empty())
        throw std::invalid_argument(
            std::string(context) + " must be non-empty");
    if (value.size() > kStringLimit)
        throw std::invalid_argument(
            std::string(context) + " exceeds 1 MiB");
    if (value.find('\0') != std::string::npos)
        throw std::invalid_argument(
            std::string(context) + " contains embedded NUL");
    if (!sio::valid_utf8(value))
        throw std::invalid_argument(
            std::string(context) + " must be valid UTF-8");
}

void encode_strings(
    const std::vector<std::string> &values,
    std::vector<uint64_t> &offsets,
    std::vector<uint8_t> &utf8,
    const char *context,
    bool allow_empty) {
    offsets.reserve(values.size() + 1);
    offsets.push_back(0);
    for (const std::string &value : values) {
        validate_text(value, context, allow_empty);
        if (value.size() >
            std::numeric_limits<size_t>::max() - utf8.size())
            throw std::length_error(
                std::string(context) + " table is too large");
        utf8.insert(utf8.end(), value.begin(), value.end());
        offsets.push_back(static_cast<uint64_t>(utf8.size()));
    }
}

std::vector<std::string> decode_strings(
    const std::vector<uint64_t> &offsets,
    const std::vector<uint8_t> &utf8) {
    std::vector<std::string> result;
    if (offsets.empty()) return result;
    if (offsets[0] != 0 || offsets.back() != utf8.size())
        throw std::invalid_argument(
            "material set: malformed string table extents");
    result.reserve(offsets.size() - 1);
    const char *data = utf8.empty()
                           ? ""
                           : reinterpret_cast<const char *>(utf8.data());
    for (size_t index = 0; index + 1 < offsets.size(); ++index) {
        const uint64_t begin_value = offsets[index];
        const uint64_t end_value = offsets[index + 1];
        if (begin_value > end_value || end_value > utf8.size())
            throw std::invalid_argument(
                "material set: malformed string table offsets");
        const size_t begin = static_cast<size_t>(begin_value);
        const size_t end = static_cast<size_t>(end_value);
        result.emplace_back(
            data + begin,
            end - begin);
    }
    return result;
}

uint8_t alpha_mode_code(const std::string &value) {
    if (value == "opaque") return 0;
    if (value == "mask") return 1;
    if (value == "blend") return 2;
    throw std::invalid_argument(
        "material set: alpha mode must be opaque|mask|blend");
}

uint8_t semantic_code(const std::string &value) {
    static constexpr const char *names[] = {
        "base_color",
        "ambient",
        "specular",
        "specular_highlight",
        "normal",
        "displacement",
        "alpha",
        "emissive",
        "metallic",
        "roughness",
        "metallic_roughness",
        "occlusion",
        "reflection",
    };
    for (uint8_t index = 0; index < std::size(names); ++index)
        if (value == names[index]) return index;
    throw std::invalid_argument(
        "material set: unsupported texture semantic '" + value + "'");
}

uint8_t wrap_code(const std::string &value) {
    if (value == "repeat") return 0;
    if (value == "clamp") return 1;
    if (value == "mirrored_repeat") return 2;
    throw std::invalid_argument(
        "material set: texture wrap must be "
        "repeat|clamp|mirrored_repeat");
}

uint8_t filter_code(const std::string &value, bool magnification) {
    static constexpr const char *names[] = {
        "unspecified",
        "nearest",
        "linear",
        "nearest_mipmap_nearest",
        "linear_mipmap_nearest",
        "nearest_mipmap_linear",
        "linear_mipmap_linear",
    };
    for (uint8_t index = 0; index < std::size(names); ++index) {
        if (value != names[index]) continue;
        if (magnification && index > 2)
            throw std::invalid_argument(
                "material set: magnification filter must be "
                "unspecified|nearest|linear");
        return index;
    }
    throw std::invalid_argument(
        "material set: unsupported texture filter '" + value + "'");
}

void require_f32_shape(
    const f32_array &array, size_t rows, size_t columns,
    const char *name) {
    if (array.ndim() != (columns == 1 ? 1 : 2) ||
        array.shape(0) != rows ||
        (columns != 1 && array.shape(1) != columns))
        throw std::invalid_argument(
            std::string("material set: ") + name + " must be (" +
            std::to_string(rows) +
            (columns == 1
                 ? ",) float32"
                 : "," + std::to_string(columns) + ") float32"));
}

template <typename T>
void assign_values(
    std::vector<T> &target, const T *data, size_t count) {
    if (count != 0) target.assign(data, data + count);
}

void assign_factor(
    std::vector<float> &target,
    const std::optional<f32_array> &source,
    size_t rows, size_t columns,
    std::initializer_list<float> defaults,
    const char *name) {
    if (source) {
        require_f32_shape(*source, rows, columns, name);
        assign_values(target, source->data(), rows * columns);
        return;
    }
    target.reserve(rows * columns);
    for (size_t row = 0; row < rows; ++row)
        target.insert(target.end(), defaults.begin(), defaults.end());
}

std::vector<uint8_t> codes_or_default(
    const std::vector<std::string> &values, size_t count,
    const std::string &default_value,
    uint8_t (*convert)(const std::string &),
    const char *name) {
    if (!values.empty() && values.size() != count)
        throw std::invalid_argument(
            std::string("material set: ") + name +
            " must have one entry per row");
    std::vector<uint8_t> result;
    result.reserve(count);
    if (values.empty()) {
        const uint8_t value = convert(default_value);
        result.assign(count, value);
    } else {
        for (const std::string &value : values)
            result.push_back(convert(value));
    }
    return result;
}

MaterialSet make_material_set(
    const std::vector<std::string> &names,
    std::optional<f32_array> base_colors,
    std::optional<f32_array> emissive_colors,
    std::optional<f32_array> metallic,
    std::optional<f32_array> roughness,
    const std::vector<std::string> &alpha_modes,
    std::optional<f32_array> alpha_cutoffs,
    std::optional<u64_array> texture_materials,
    const std::vector<std::string> &texture_semantics,
    const std::vector<std::string> &texture_paths,
    std::optional<u32_array> texture_uv_sets,
    const std::vector<std::string> &texture_wrap_s,
    const std::vector<std::string> &texture_wrap_t,
    const std::vector<std::string> &texture_min_filters,
    const std::vector<std::string> &texture_mag_filters) {
    MaterialSet result;
    result.n = names.size();
    result.t = texture_paths.size();
    if (result.n > std::numeric_limits<size_t>::max() / 4)
        throw std::length_error("material set: material count is too large");
    if (result.t == std::numeric_limits<size_t>::max())
        throw std::length_error("material set: texture count is too large");
    for (const std::string &name : names)
        validate_text(name, "material set: material name", true);
    if (texture_semantics.size() != result.t)
        throw std::invalid_argument(
            "material set: texture_semantics and texture_paths "
            "must have the same length");
    if (result.t != 0 && !texture_materials)
        throw std::invalid_argument(
            "material set: texture_materials is required for textures");
    if (texture_materials &&
        (texture_materials->ndim() != 1 ||
         texture_materials->shape(0) != result.t))
        throw std::invalid_argument(
            "material set: texture_materials must be (T,) uint64");
    if (texture_uv_sets &&
        (texture_uv_sets->ndim() != 1 ||
         texture_uv_sets->shape(0) != result.t))
        throw std::invalid_argument(
            "material set: texture_uv_sets must be (T,) uint32");

    assign_material_names(result, names);
    assign_material_texture_paths(result, texture_paths);

    result.alpha_modes = codes_or_default(
        alpha_modes, result.n, "opaque", alpha_mode_code,
        "alpha_modes");
    result.texture_semantics.reserve(result.t);
    for (const std::string &value : texture_semantics)
        result.texture_semantics.push_back(semantic_code(value));
    result.texture_wrap_s = codes_or_default(
        texture_wrap_s, result.t, "repeat", wrap_code,
        "texture_wrap_s");
    result.texture_wrap_t = codes_or_default(
        texture_wrap_t, result.t, "repeat", wrap_code,
        "texture_wrap_t");
    auto min_code = [](const std::string &value) {
        return filter_code(value, false);
    };
    auto mag_code = [](const std::string &value) {
        return filter_code(value, true);
    };
    result.texture_min_filters = codes_or_default(
        texture_min_filters, result.t, "unspecified", min_code,
        "texture_min_filters");
    result.texture_mag_filters = codes_or_default(
        texture_mag_filters, result.t, "unspecified", mag_code,
        "texture_mag_filters");

    {
        nb::gil_scoped_release release;
        assign_factor(
            result.base_colors, base_colors, result.n, 4,
            {1.0F, 1.0F, 1.0F, 1.0F}, "base_colors");
        assign_factor(
            result.emissive_colors, emissive_colors, result.n, 3,
            {0.0F, 0.0F, 0.0F}, "emissive_colors");
        assign_factor(
            result.metallic, metallic, result.n, 1,
            {0.0F}, "metallic");
        assign_factor(
            result.roughness, roughness, result.n, 1,
            {1.0F}, "roughness");
        assign_factor(
            result.alpha_cutoffs, alpha_cutoffs, result.n, 1,
            {0.5F}, "alpha_cutoffs");
        if (texture_materials)
            assign_values(
                result.texture_materials,
                texture_materials->data(), result.t);
        if (texture_uv_sets)
            assign_values(
                result.texture_uv_sets,
                texture_uv_sets->data(), result.t);
        else
            result.texture_uv_sets.assign(result.t, 0);
        validate_material_set(result);
    }
    return result;
}

}  // namespace

const char *material_alpha_mode_name(uint8_t value) {
    static constexpr const char *names[] = {
        "opaque", "mask", "blend"};
    if (value >= std::size(names))
        throw std::invalid_argument(
            "material set: invalid alpha mode code");
    return names[value];
}

const char *material_texture_semantic_name(uint8_t value) {
    static constexpr const char *names[] = {
        "base_color",
        "ambient",
        "specular",
        "specular_highlight",
        "normal",
        "displacement",
        "alpha",
        "emissive",
        "metallic",
        "roughness",
        "metallic_roughness",
        "occlusion",
        "reflection",
    };
    if (value >= std::size(names))
        throw std::invalid_argument(
            "material set: invalid texture semantic code");
    return names[value];
}

const char *material_wrap_name(uint8_t value) {
    static constexpr const char *names[] = {
        "repeat", "clamp", "mirrored_repeat"};
    if (value >= std::size(names))
        throw std::invalid_argument(
            "material set: invalid texture wrap code");
    return names[value];
}

const char *material_filter_name(uint8_t value) {
    static constexpr const char *names[] = {
        "unspecified",
        "nearest",
        "linear",
        "nearest_mipmap_nearest",
        "linear_mipmap_nearest",
        "nearest_mipmap_linear",
        "linear_mipmap_linear",
    };
    if (value >= std::size(names))
        throw std::invalid_argument(
            "material set: invalid texture filter code");
    return names[value];
}

std::vector<std::string> material_names(const MaterialSet &materials) {
    return decode_strings(
        materials.name_offsets, materials.name_utf8);
}

std::vector<std::string> material_texture_paths(
    const MaterialSet &materials) {
    return decode_strings(
        materials.texture_path_offsets,
        materials.texture_path_utf8);
}

void assign_material_names(
    MaterialSet &materials,
    const std::vector<std::string> &names) {
    materials.n = names.size();
    materials.name_offsets.clear();
    materials.name_utf8.clear();
    encode_strings(
        names, materials.name_offsets, materials.name_utf8,
        "material set: material name", true);
}

void assign_material_texture_paths(
    MaterialSet &materials,
    const std::vector<std::string> &paths) {
    materials.t = paths.size();
    materials.texture_path_offsets.clear();
    materials.texture_path_utf8.clear();
    encode_strings(
        paths, materials.texture_path_offsets,
        materials.texture_path_utf8,
        "material set: texture path", false);
}

void validate_material_set(
    const MaterialSet &materials, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    if (materials.n > std::numeric_limits<size_t>::max() / 4 ||
        materials.name_offsets.size() != materials.n + 1 ||
        materials.base_colors.size() != materials.n * 4 ||
        materials.emissive_colors.size() != materials.n * 3 ||
        materials.metallic.size() != materials.n ||
        materials.roughness.size() != materials.n ||
        materials.alpha_modes.size() != materials.n ||
        materials.alpha_cutoffs.size() != materials.n)
        throw std::invalid_argument(
            prefix + "inconsistent material-domain field lengths");
    if (materials.t == std::numeric_limits<size_t>::max() ||
        materials.texture_materials.size() != materials.t ||
        materials.texture_semantics.size() != materials.t ||
        materials.texture_path_offsets.size() != materials.t + 1 ||
        materials.texture_uv_sets.size() != materials.t ||
        materials.texture_wrap_s.size() != materials.t ||
        materials.texture_wrap_t.size() != materials.t ||
        materials.texture_min_filters.size() != materials.t ||
        materials.texture_mag_filters.size() != materials.t)
        throw std::invalid_argument(
            prefix + "inconsistent texture-domain field lengths");

    auto validate_table = [&](const std::vector<uint64_t> &offsets,
                              const std::vector<uint8_t> &utf8,
                              const char *name,
                              bool allow_empty) {
        if (offsets.empty() || offsets[0] != 0 ||
            offsets.back() != utf8.size())
            throw std::invalid_argument(
                prefix + name +
                " offsets must span the UTF-8 value buffer");
        for (size_t row = 0; row + 1 < offsets.size(); ++row) {
            const uint64_t begin_value = offsets[row];
            const uint64_t end_value = offsets[row + 1];
            if (end_value < begin_value || end_value > utf8.size() ||
                (!allow_empty && end_value == begin_value))
                throw std::invalid_argument(
                    prefix + name +
                    " entries must be non-empty and monotonic");
            const size_t begin = static_cast<size_t>(begin_value);
            const size_t end = static_cast<size_t>(end_value);
            validate_text(
                std::string(
                    utf8.empty()
                        ? ""
                        : reinterpret_cast<const char *>(
                              utf8.data() + begin),
                    end - begin),
                (prefix + name).c_str(), allow_empty);
        }
    };
    validate_table(
        materials.name_offsets, materials.name_utf8,
        "material name", true);
    validate_table(
        materials.texture_path_offsets,
        materials.texture_path_utf8, "texture path", false);

    auto finite_range = [&](const std::vector<float> &values,
                            float minimum, float maximum,
                            const char *name) {
        for (float value : values)
            if (!std::isfinite(value) || value < minimum ||
                value > maximum)
                throw std::invalid_argument(
                    prefix + name + " values are outside the supported range");
    };
    finite_range(
        materials.base_colors, 0.0F, 1.0F, "base color");
    finite_range(
        materials.emissive_colors, 0.0F,
        std::numeric_limits<float>::max(), "emissive color");
    finite_range(materials.metallic, 0.0F, 1.0F, "metallic");
    finite_range(materials.roughness, 0.0F, 1.0F, "roughness");
    finite_range(
        materials.alpha_cutoffs, 0.0F, 1.0F, "alpha cutoff");
    for (uint8_t mode : materials.alpha_modes)
        (void)material_alpha_mode_name(mode);

    std::unordered_set<TextureBindingKey, TextureBindingHash> bindings;
    for (size_t row = 0; row < materials.t; ++row) {
        const uint64_t material = materials.texture_materials[row];
        const uint8_t semantic = materials.texture_semantics[row];
        if (material >= materials.n)
            throw std::invalid_argument(
                prefix + "texture material index is out of range");
        (void)material_texture_semantic_name(semantic);
        (void)material_wrap_name(materials.texture_wrap_s[row]);
        (void)material_wrap_name(materials.texture_wrap_t[row]);
        (void)material_filter_name(
            materials.texture_min_filters[row]);
        if (materials.texture_mag_filters[row] > 2)
            throw std::invalid_argument(
                prefix + "invalid magnification filter");
        (void)material_filter_name(
            materials.texture_mag_filters[row]);
        if (!bindings.insert({material, semantic}).second)
            throw std::invalid_argument(
                prefix +
                "each material may bind a texture semantic only once");
    }
}

void register_material_set(nb::module_ &module) {
    const auto reference_internal = nb::rv_policy::reference_internal;
    nb::class_<MaterialSet>(module, "MaterialSet")
        .def_prop_ro(
            "num_materials",
            [](const MaterialSet &materials) {
                return materials.num_materials();
            })
        .def_prop_ro(
            "num_textures",
            [](const MaterialSet &materials) {
                return materials.num_textures();
            })
        .def_prop_ro("names", &material_names)
        .def_prop_ro(
            "name_offsets",
            [](const MaterialSet &materials) {
                return material_const_view(
                    materials.name_offsets, {materials.n + 1});
            },
            reference_internal)
        .def_prop_ro(
            "name_utf8",
            [](const MaterialSet &materials) {
                return material_const_view(
                    materials.name_utf8,
                    {materials.name_utf8.size()});
            },
            reference_internal)
        .def_prop_ro(
            "base_colors",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.base_colors, {materials.n, 4});
            },
            reference_internal)
        .def_prop_ro(
            "emissive_colors",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.emissive_colors, {materials.n, 3});
            },
            reference_internal)
        .def_prop_ro(
            "metallic",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.metallic, {materials.n});
            },
            reference_internal)
        .def_prop_ro(
            "roughness",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.roughness, {materials.n});
            },
            reference_internal)
        .def_prop_ro(
            "alpha_mode_codes",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.alpha_modes, {materials.n});
            },
            reference_internal)
        .def_prop_ro(
            "alpha_modes",
            [](const MaterialSet &materials) {
                std::vector<std::string> result;
                result.reserve(materials.n);
                for (uint8_t value : materials.alpha_modes)
                    result.emplace_back(material_alpha_mode_name(value));
                return result;
            })
        .def_prop_ro(
            "alpha_cutoffs",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.alpha_cutoffs, {materials.n});
            },
            reference_internal)
        .def_prop_ro(
            "texture_materials",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.texture_materials, {materials.t});
            },
            reference_internal)
        .def_prop_ro(
            "texture_semantic_codes",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.texture_semantics, {materials.t});
            },
            reference_internal)
        .def_prop_ro(
            "texture_semantics",
            [](const MaterialSet &materials) {
                std::vector<std::string> result;
                result.reserve(materials.t);
                for (uint8_t value : materials.texture_semantics)
                    result.emplace_back(
                        material_texture_semantic_name(value));
                return result;
            })
        .def_prop_ro("texture_paths", &material_texture_paths)
        .def_prop_ro(
            "texture_path_offsets",
            [](const MaterialSet &materials) {
                return material_const_view(
                    materials.texture_path_offsets,
                    {materials.t + 1});
            },
            reference_internal)
        .def_prop_ro(
            "texture_path_utf8",
            [](const MaterialSet &materials) {
                return material_const_view(
                    materials.texture_path_utf8,
                    {materials.texture_path_utf8.size()});
            },
            reference_internal)
        .def_prop_ro(
            "texture_uv_sets",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.texture_uv_sets, {materials.t});
            },
            reference_internal)
        .def_prop_ro(
            "texture_wrap_s_codes",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.texture_wrap_s, {materials.t});
            },
            reference_internal)
        .def_prop_ro(
            "texture_wrap_t_codes",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.texture_wrap_t, {materials.t});
            },
            reference_internal)
        .def_prop_ro(
            "texture_min_filter_codes",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.texture_min_filters, {materials.t});
            },
            reference_internal)
        .def_prop_ro(
            "texture_mag_filter_codes",
            [](const MaterialSet &materials) {
                return material_view(
                    materials.texture_mag_filters, {materials.t});
            },
            reference_internal)
        .def(
            "__repr__",
            [](const MaterialSet &materials) {
                return "<MaterialSet materials=" +
                       std::to_string(materials.n) +
                       " textures=" +
                       std::to_string(materials.t) + ">";
            });

    module.def(
        "material_set", &make_material_set,
        "names"_a,
        "base_colors"_a = nb::none(),
        "emissive_colors"_a = nb::none(),
        "metallic"_a = nb::none(),
        "roughness"_a = nb::none(),
        "alpha_modes"_a = std::vector<std::string>{},
        "alpha_cutoffs"_a = nb::none(),
        "texture_materials"_a = nb::none(),
        "texture_semantics"_a = std::vector<std::string>{},
        "texture_paths"_a = std::vector<std::string>{},
        "texture_uv_sets"_a = nb::none(),
        "texture_wrap_s"_a = std::vector<std::string>{},
        "texture_wrap_t"_a = std::vector<std::string>{},
        "texture_min_filters"_a = std::vector<std::string>{},
        "texture_mag_filters"_a = std::vector<std::string>{},
        "Build a canonical MaterialSet from material and texture SoA fields.");
}
