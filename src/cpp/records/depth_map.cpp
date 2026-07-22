// records/depth_map.cpp -- DepthMap nanobind binding. Registered once (after the
// other records) and shared by the depth codecs later (16-bit depth PNG, .dmb,
// EXR/PFM depth). The depth (and optional confidence) accessor is a zero-copy
// float32 view with the record baked in as the ndarray owner (sio::view -- the
// same reason as Image.pixels: the confidence getter returns nb::object, so
// rv_policy::reference_internal cannot attach the owner the way the fixed-dtype
// records do). Conventions are metadata the codec recorded; a depth_map(...)
// factory builds one from arrays for tests, with a unit<->scale pairing guard.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>

#include <optional>
#include <string>

#include "records/depth_map.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

// dtype-erased, read-only, contiguous CPU array -- accepts numpy OR torch of ANY
// dtype at the binding layer; we dispatch on a.dtype() and raise our own clear
// "must be float32" error for unsupported kinds (never a silent nanobind
// convert). Non-contiguous input is copied by nb. Same as Image's anyarr.
using anyarr = nb::ndarray<nb::ro, nb::c_contig, nb::device::cpu>;

DepthMap make_depth_map(anyarr depth, std::optional<anyarr> confidence,
                        std::optional<std::string> unit, std::optional<double> scale_to_meters,
                        const std::string &invalid_policy) {
    // 1. shape: exactly (H,W), both >= 1 (the H,W >= 1 invariant keeps every
    // view over a non-empty buffer, so the null-data sentinel concern never
    // arises and confidence-absent can safely mean "empty vector").
    if (depth.ndim() != 2)
        throw std::invalid_argument("depth_map: depth must be (H,W) float32 with H,W >= 1");
    const size_t H = depth.shape(0), W = depth.shape(1);
    if (H < 1 || W < 1)
        throw std::invalid_argument("depth_map: depth must be (H,W) float32 with H,W >= 1");

    // 2. dtype: float32 only -- float64/int/uint give OUR clear error, no convert.
    if (depth.dtype() != nb::dtype<float>())
        throw std::invalid_argument("depth_map: depth must be float32");

    DepthMap d;
    d.height = H;
    d.width = W;
    const size_t cnt = H * W;
    const auto *dp = static_cast<const float *>(depth.data());
    d.depth.assign(dp, dp + cnt);  // one bulk copy

    // 3. confidence (optional): exactly (H,W) float32 matching depth.
    if (confidence) {
        const anyarr &c = *confidence;
        if (c.ndim() != 2 || c.shape(0) != H || c.shape(1) != W ||
            c.dtype() != nb::dtype<float>())
            throw std::invalid_argument(
                "depth_map: confidence must be (H,W) float32 matching depth");
        const auto *cp = static_cast<const float *>(c.data());
        d.confidence.assign(cp, cp + cnt);
    }

    // 4. unit / scale_to_meters resolution (both optional; derive-then-pair,
    // mirroring Image's per-dtype maxval defaulting). 0.0 is the non-metric
    // ("not convertible") sentinel for unitless|unknown.
    if (!unit && !scale_to_meters) {
        d.unit = "meters";  // struct defaults, spelled out for clarity
        d.scale_to_meters = 1.0;
    } else if (unit && !scale_to_meters) {  // unit only -> derive scale
        d.unit = *unit;
        if (!depth_map_valid_unit(d.unit))
            throw std::invalid_argument(
                "depth_map: unit must be meters|millimeters|custom|unitless|unknown");
        if (d.unit == "meters")
            d.scale_to_meters = 1.0;
        else if (d.unit == "millimeters")
            d.scale_to_meters = 0.001;
        else if (d.unit == "unitless" || d.unit == "unknown")
            d.scale_to_meters = 0.0;
        else  // custom: the scale is the whole point, so it must be given explicitly
            throw std::invalid_argument(
                "depth_map: unit 'custom' requires an explicit scale_to_meters");
    } else if (!unit && scale_to_meters) {  // scale only -> derive unit
        const double s = *scale_to_meters;
        d.scale_to_meters = s;
        if (s == 1.0)
            d.unit = "meters";
        else if (s == 0.001)
            d.unit = "millimeters";
        else if (s == 0.0)
            d.unit = "unknown";
        else if (std::isfinite(s) && s > 0.0)
            d.unit = "custom";
        else  // negative / NaN / Inf is not a usable scale
            throw std::invalid_argument(
                "depth_map: scale_to_meters must be finite and >= 0 (0.0 == non-metric/unknown)");
    } else {  // both given: validate the vocabulary, then the pairing.
        d.unit = *unit;
        d.scale_to_meters = *scale_to_meters;
        if (!depth_map_valid_unit(d.unit))
            throw std::invalid_argument(
                "depth_map: unit must be meters|millimeters|custom|unitless|unknown");
        if (!depth_map_unit_scale_consistent(d.unit, d.scale_to_meters))
            throw std::invalid_argument("depth_map: unit/scale mismatch -- convert the record first");
    }

    // 5. invalid_policy: vocabulary check ONLY; pixels are never scanned or
    // scrubbed (reader records, does not judge -- the netpbm "sample may exceed
    // maxval" precedent).
    if (!depth_map_valid_invalid_policy(invalid_policy))
        throw std::invalid_argument("depth_map: invalid_policy must be none|zero|nonfinite|negative");
    d.invalid_policy = invalid_policy;

    return d;
}

}  // namespace

void register_depth_map(nb::module_ &m) {
    nb::class_<DepthMap>(m, "DepthMap")
        .def_prop_ro("height", [](const DepthMap &d) { return d.height; })
        .def_prop_ro("width", [](const DepthMap &d) { return d.width; })
        .def_prop_ro("has_confidence", [](const DepthMap &d) { return d.has_confidence(); })
        // Owner-carrying zero-copy views. Because the confidence getter returns
        // a dynamically-typed nb::object (None or an array),
        // rv_policy::reference_internal cannot attach the owner the way the
        // fixed-dtype records (GaussianCloud, PosedViewSet) do through a bare
        // vw() return. Instead sio::view(self, ...) bakes `self` in as the
        // array's owner, so the backing buffer stays alive for as long as the
        // returned array does (the gc.collect() lifetime test pins this).
        // nb::handle_t<DepthMap> hands us the Python self to use as owner.
        .def_prop_ro("depth",
                     [](nb::handle_t<DepthMap> self) {
                         const DepthMap &d = nb::cast<const DepthMap &>(self);
                         return sio::view(self, d.depth.data(), {d.height, d.width});
                     })
        .def_prop_ro("confidence",
                     [](nb::handle_t<DepthMap> self) -> nb::object {
                         const DepthMap &d = nb::cast<const DepthMap &>(self);
                         if (!d.has_confidence()) return nb::none();
                         return nb::cast(sio::view(self, d.confidence.data(), {d.height, d.width}));
                     })
        // conventions the codec recorded (metadata):
        .def_prop_ro("unit", [](const DepthMap &d) { return d.unit; })
        .def_prop_ro("scale_to_meters", [](const DepthMap &d) { return d.scale_to_meters; })
        .def_prop_ro("invalid_policy", [](const DepthMap &d) { return d.invalid_policy; })
        // fixed canonical tag (derived, like Image.row_order / GaussianCloud.quaternion_order):
        .def_prop_ro("row_order", [](const DepthMap &) { return "top_to_bottom"; })
        .def("__repr__", [](const DepthMap &d) {
            return "<DepthMap " + std::to_string(d.height) + "x" + std::to_string(d.width) + " " +
                   d.unit + " invalid=" + d.invalid_policy +
                   (d.has_confidence() ? " +confidence" : "") + ">";
        });

    m.def("depth_map", &make_depth_map, "depth"_a, "confidence"_a = nb::none(),
          "unit"_a = nb::none(), "scale_to_meters"_a = nb::none(), "invalid_policy"_a = "none",
          "Build a DepthMap from a (H,W) float32 array (numpy or torch) + optional (H,W) float32 "
          "confidence; unit/scale_to_meters/invalid_policy recorded as metadata (arrays never "
          "rescaled). unit in {meters,millimeters,custom,unitless,unknown}; scale_to_meters is the "
          "machine-usable twin (meters=1.0, millimeters=0.001, custom=finite>0, unitless|unknown=0.0) "
          "and is derived from unit (or vice-versa) when only one is given.");
}
