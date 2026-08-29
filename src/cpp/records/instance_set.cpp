// records/instance_set.cpp -- validation, construction, and nanobind views.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "records/instance_set.hpp"

using namespace nb::literals;

namespace {

using f32_array =
    nb::ndarray<const float, nb::c_contig, nb::device::cpu>;
using i64_array =
    nb::ndarray<const int64_t, nb::c_contig, nb::device::cpu>;
using u64_array =
    nb::ndarray<const uint64_t, nb::c_contig, nb::device::cpu>;

template <typename T>
void assign_nonempty(
    std::vector<T> &target, const T *data, size_t count) {
    if (count != 0) target.assign(data, data + count);
}

template <typename T>
nb::ndarray<nb::numpy, const T> owned_view(
    nb::handle owner, const std::vector<T> &values,
    std::vector<size_t> shape) {
    static const T sentinel{};
    const T *data = values.empty() ? &sentinel : values.data();
    return sio::view<const T>(owner, data, std::move(shape));
}

void require_shape(
    const f32_array &array, size_t rows, size_t columns,
    const char *name) {
    if (array.ndim() != 2 || array.shape(0) != rows ||
        array.shape(1) != columns)
        throw std::invalid_argument(
            std::string("instance_set: ") + name + " must be (N," +
            std::to_string(columns) + ") float32");
}

InstanceSet make_instance_set(
    u64_array prototype_nodes, u64_array prototype_indices,
    f32_array translations,
    std::optional<f32_array> orientations,
    std::optional<f32_array> scales,
    std::optional<i64_array> ids,
    std::optional<i64_array> invisible_ids,
    std::optional<TensorDict> attributes,
    const std::string &quaternion_order) {
    if (prototype_nodes.ndim() != 1)
        throw std::invalid_argument(
            "instance_set: prototype_nodes must be (P,) uint64");
    if (prototype_indices.ndim() != 1)
        throw std::invalid_argument(
            "instance_set: prototype_indices must be (N,) uint64");
    const size_t count = prototype_indices.shape(0);
    if (count >
        static_cast<size_t>(std::numeric_limits<int64_t>::max()))
        throw std::length_error(
            "instance_set: instance count exceeds the id domain");
    require_shape(translations, count, 3, "translations");
    if (orientations)
        require_shape(*orientations, count, 4, "orientations");
    if (scales) require_shape(*scales, count, 3, "scales");
    if (ids && (ids->ndim() != 1 || ids->shape(0) != count))
        throw std::invalid_argument(
            "instance_set: ids must be (N,) int64");
    if (invisible_ids && invisible_ids->ndim() != 1)
        throw std::invalid_argument(
            "instance_set: invisible_ids must be (K,) int64");

    InstanceSet result;
    result.n = count;
    assign_nonempty(
        result.prototype_nodes, prototype_nodes.data(),
        prototype_nodes.shape(0));
    assign_nonempty(
        result.prototype_indices, prototype_indices.data(), count);
    assign_nonempty(
        result.translations, translations.data(), count * 3);

    result.orientations.assign(count * 4, 0.0F);
    if (orientations) {
        assign_nonempty(
            result.orientations, orientations->data(), count * 4);
    } else {
        const size_t w =
            quaternion_order == "xyzw" ? size_t{3} : size_t{0};
        for (size_t row = 0; row < count; ++row)
            result.orientations[row * 4 + w] = 1.0F;
    }
    result.scales.assign(count * 3, 1.0F);
    if (scales)
        assign_nonempty(result.scales, scales->data(), count * 3);

    result.ids.resize(count);
    if (ids) {
        assign_nonempty(result.ids, ids->data(), count);
    } else {
        for (size_t row = 0; row < count; ++row)
            result.ids[row] = static_cast<int64_t>(row);
    }
    if (invisible_ids)
        assign_nonempty(
            result.invisible_ids, invisible_ids->data(),
            invisible_ids->shape(0));
    result.invisible_mask.assign(count, 0);
    std::unordered_map<int64_t, size_t> id_rows;
    id_rows.reserve(count);
    for (size_t row = 0; row < count; ++row)
        if (!id_rows.emplace(result.ids[row], row).second)
            throw std::invalid_argument(
                "instance_set: instance ids must be unique");
    for (int64_t id : result.invisible_ids) {
        const auto found = id_rows.find(id);
        if (found == id_rows.end())
            throw std::invalid_argument(
                "instance_set: invisible_ids must be a subset of ids");
        result.invisible_mask[found->second] = 1;
    }
    result.quaternion_order = quaternion_order;
    if (attributes) {
        result.attributes = std::move(*attributes);
        result.has_attributes = true;
    }
    {
        nb::gil_scoped_release release;
        validate_instance_set(result);
    }
    return result;
}

}  // namespace

void validate_instance_set(
    const InstanceSet &instances, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    const size_t count = instances.n;
    if (count > std::numeric_limits<size_t>::max() / 4 ||
        count >
            static_cast<size_t>(std::numeric_limits<int64_t>::max()) ||
        instances.prototype_indices.size() != count ||
        instances.ids.size() != count ||
        instances.translations.size() != count * 3 ||
        instances.orientations.size() != count * 4 ||
        instances.scales.size() != count * 3 ||
        instances.invisible_mask.size() != count)
        throw std::invalid_argument(
            prefix + "inconsistent InstanceSet field lengths");
    if (!instance_valid_quaternion_order(
            instances.quaternion_order))
        throw std::invalid_argument(
            prefix + "quaternion_order must be wxyz or xyzw");
    if (count != 0 && instances.prototype_nodes.empty())
        throw std::invalid_argument(
            prefix + "non-empty instances require prototypes");

    std::unordered_set<uint64_t> prototype_nodes;
    prototype_nodes.reserve(instances.prototype_nodes.size());
    for (uint64_t node : instances.prototype_nodes)
        if (!prototype_nodes.insert(node).second)
            throw std::invalid_argument(
                prefix + "prototype node indices must be unique");
    for (uint64_t prototype : instances.prototype_indices)
        if (prototype >= instances.prototype_nodes.size())
            throw std::invalid_argument(
                prefix + "prototype index is out of range");

    std::unordered_map<int64_t, size_t> id_rows;
    id_rows.reserve(count);
    for (size_t row = 0; row < count; ++row) {
        if (!id_rows.emplace(instances.ids[row], row).second)
            throw std::invalid_argument(
                prefix + "instance ids must be unique");
        for (size_t component = 0; component < 3; ++component) {
            if (!std::isfinite(
                    instances.translations[row * 3 + component]) ||
                !std::isfinite(
                    instances.scales[row * 3 + component]))
                throw std::invalid_argument(
                    prefix +
                    "translations and scales must be finite");
        }
        bool nonzero = false;
        for (size_t component = 0; component < 4; ++component) {
            const float value =
                instances.orientations[row * 4 + component];
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    prefix + "orientations must be finite");
            nonzero = nonzero || value != 0.0F;
        }
        if (!nonzero)
            throw std::invalid_argument(
                prefix + "orientation quaternions must be nonzero");
        if (instances.invisible_mask[row] > 1)
            throw std::invalid_argument(
                prefix + "invisible mask values must be zero or one");
    }

    std::unordered_set<int64_t> invisible;
    invisible.reserve(instances.invisible_ids.size());
    for (int64_t id : instances.invisible_ids) {
        const auto found = id_rows.find(id);
        if (found == id_rows.end())
            throw std::invalid_argument(
                prefix + "invisible ids must be a subset of ids");
        if (!invisible.insert(id).second)
            throw std::invalid_argument(
                prefix + "invisible ids must be unique");
        if (instances.invisible_mask[found->second] != 1)
            throw std::invalid_argument(
                prefix + "invisible ids and mask disagree");
    }
    for (size_t row = 0; row < count; ++row)
        if (instances.invisible_mask[row] !=
            static_cast<uint8_t>(
                invisible.count(instances.ids[row]) != 0))
            throw std::invalid_argument(
                prefix + "invisible ids and mask disagree");

    if (!instances.has_attributes) {
        if (!instances.attributes.entries.empty() ||
            !instances.attributes.attrs.empty() ||
            !instances.attributes.index.empty())
            throw std::invalid_argument(
                prefix + "detached attribute storage must be empty");
        return;
    }
    if (!instances.attributes.attrs.empty())
        throw std::invalid_argument(
            prefix + "per-instance attributes must be numeric tensors");
    if (instances.attributes.entries.size() !=
        instances.attributes.index.size())
        throw std::invalid_argument(
            prefix + "per-instance attribute index is inconsistent");
    for (size_t index = 0;
         index < instances.attributes.entries.size(); ++index) {
        const TensorEntry &entry =
            instances.attributes.entries[index];
        const auto found =
            instances.attributes.index.find(entry.name);
        if (entry.name.empty() ||
            entry.name.size() > 1024 * 1024 ||
            entry.name.find('\0') != std::string::npos ||
            !sio::valid_utf8(entry.name) ||
            found == instances.attributes.index.end() ||
            found->second != index)
            throw std::invalid_argument(
                prefix + "per-instance attribute names must be "
                         "non-empty, unique, valid UTF-8 without NUL, "
                         "and at most 1 MiB");
        if (entry.shape.empty() || entry.shape.front() != count)
            throw std::invalid_argument(
                prefix + "per-instance attributes must have N leading rows");
        const size_t expected = TensorDict::checked_size(
            entry.name, entry.dtype, entry.shape);
        if (entry.size_bytes() != expected ||
            (expected != 0 && entry.data() == nullptr))
            throw std::invalid_argument(
                prefix + "per-instance attribute storage disagrees "
                         "with its shape");
    }
}

void register_instance_set(nb::module_ &module) {
    nb::class_<InstanceSet>(module, "InstanceSet")
        .def_prop_ro(
            "num_instances",
            [](const InstanceSet &value) {
                return value.num_instances();
            })
        .def_prop_ro(
            "num_prototypes",
            [](const InstanceSet &value) {
                return value.num_prototypes();
            })
        .def_prop_ro(
            "prototype_nodes",
            [](nb::handle_t<InstanceSet> self) {
                const auto &value =
                    nb::cast<const InstanceSet &>(self);
                return owned_view(
                    self, value.prototype_nodes,
                    {value.prototype_nodes.size()});
            })
        .def_prop_ro(
            "prototype_indices",
            [](nb::handle_t<InstanceSet> self) {
                const auto &value =
                    nb::cast<const InstanceSet &>(self);
                return owned_view(
                    self, value.prototype_indices, {value.n});
            })
        .def_prop_ro(
            "ids",
            [](nb::handle_t<InstanceSet> self) {
                const auto &value =
                    nb::cast<const InstanceSet &>(self);
                return owned_view(self, value.ids, {value.n});
            })
        .def_prop_ro(
            "translations",
            [](nb::handle_t<InstanceSet> self) {
                const auto &value =
                    nb::cast<const InstanceSet &>(self);
                return owned_view(
                    self, value.translations, {value.n, 3});
            })
        .def_prop_ro(
            "orientations",
            [](nb::handle_t<InstanceSet> self) {
                const auto &value =
                    nb::cast<const InstanceSet &>(self);
                return owned_view(
                    self, value.orientations, {value.n, 4});
            })
        .def_prop_ro(
            "scales",
            [](nb::handle_t<InstanceSet> self) {
                const auto &value =
                    nb::cast<const InstanceSet &>(self);
                return owned_view(
                    self, value.scales, {value.n, 3});
            })
        .def_prop_ro(
            "invisible_ids",
            [](nb::handle_t<InstanceSet> self) {
                const auto &value =
                    nb::cast<const InstanceSet &>(self);
                return owned_view(
                    self, value.invisible_ids,
                    {value.invisible_ids.size()});
            })
        .def_prop_ro(
            "invisible_mask",
            [](nb::handle_t<InstanceSet> self) {
                const auto &value =
                    nb::cast<const InstanceSet &>(self);
                return owned_view(
                    self, value.invisible_mask, {value.n});
            })
        .def_ro(
            "quaternion_order",
            &InstanceSet::quaternion_order)
        .def_prop_ro(
            "has_attributes",
            [](const InstanceSet &value) {
                return value.has_attributes;
            })
        .def_prop_ro(
            "attributes",
            [](InstanceSet &value) -> TensorDict & {
                return value.attributes;
            },
            nb::rv_policy::reference_internal)
        .def(
            "__repr__",
            [](const InstanceSet &value) {
                return "<InstanceSet instances=" +
                       std::to_string(value.n) +
                       " prototypes=" +
                       std::to_string(
                           value.prototype_nodes.size()) +
                       ">";
            });

    module.def(
        "instance_set", &make_instance_set,
        "prototype_nodes"_a, "prototype_indices"_a,
        "translations"_a, "orientations"_a = nb::none(),
        "scales"_a = nb::none(), "ids"_a = nb::none(),
        "invisible_ids"_a = nb::none(),
        "attributes"_a = nb::none(),
        "quaternion_order"_a = "wxyz",
        "Build an owning point-instancer payload with stable prototype "
        "references, authored row order, and explicit conventions.");
}
