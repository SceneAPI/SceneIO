// records/point_cloud.cpp — PointCloud nanobind binding. Registered once (after
// the other records) and shared by the point codecs (.xyz/.pts, point PLY,
// PCD, and LAS; LAZ/E57 later). Array accessors are fixed-dtype zero-copy
// views (the vw + rv_policy::reference_internal pattern, like GaussianCloud /
// PosedViewSet — NOT the sio::view(self,...) trick, which Image needs only
// because its getter returns a dtype-polymorphic nb::object). Conventions are
// metadata the codec recorded, and a `point_cloud(...)` factory builds one from
// arrays for tests.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>

#include <array>
#include <cmath>
#include <optional>

#include "records/point_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {
// Fixed-dtype zero-copy view (the GaussianCloud/PosedViewSet vw + rv_policy
// pattern). The optional fields legitimately produce shaped-empty views ((0,3),
// (0,)) when absent or when N==0, whose vector .data() may be nullptr; feed
// numpy a static sentinel instead so a 0-size view never carries a null base
// pointer (the tensor_dict.cpp view_entry precedent — numpy reads 0 elements
// from it, so the byte's value is never observed).
template <typename T>
nb::ndarray<nb::numpy, T> vw(const std::vector<T> &v, std::vector<size_t> shape) {
    static T sentinel{};
    T *data = v.empty() ? &sentinel : const_cast<T *>(v.data());
    return nb::ndarray<nb::numpy, T>(data, shape.size(), shape.data());
}

// Fixed-dtype, read-only, contiguous CPU arrays. A foreign dtype / framework
// (float64 positions, a torch tensor, an int32 color array) is copy-converted
// to the canonical dtype by nanobind's typed caster (the make_pvs precedent);
// non-contiguous input is likewise copied. We assign() straight into our own
// vectors, so the caster's temporary lifetime is irrelevant.
using farr = nb::ndarray<const float, nb::c_contig, nb::device::cpu>;
using carr = nb::ndarray<const uint8_t, nb::c_contig, nb::device::cpu>;
using c16arr = nb::ndarray<const uint16_t, nb::c_contig, nb::device::cpu>;
using darr = nb::ndarray<const double, nb::c_contig, nb::device::cpu>;

bool fixed_ascii(
    const uint8_t *data, size_t size,
    std::string_view expected) {
    size_t length = 0;
    while (length < size && data[length] != 0) ++length;
    if (std::string_view(
            reinterpret_cast<const char *>(data), length) != expected)
        return false;
    for (size_t index = length; index < size; ++index)
        if (data[index] != 0) return false;
    return true;
}

size_t waveform_offset(uint8_t point_format) {
    switch (point_format) {
        case 4:
            return 28;
        case 5:
            return 34;
        case 9:
            return 30;
        case 10:
            return 38;
        default:
            throw std::invalid_argument(
                "LAS waveform sidecar: point format must be 4, 5, 9, or 10");
    }
}

size_t waveform_record_minimum(uint8_t point_format) {
    return waveform_offset(point_format) + 29;
}

LasWaveformSidecar make_las_waveform_sidecar(
    uint8_t point_format, uint8_t version_minor,
    uint16_t global_encoding, carr point_records,
    carr descriptor_vlrs, carr waveform_packet_record) {
    if (point_records.ndim() != 2)
        throw std::invalid_argument(
            "LAS waveform sidecar: point_records must be (N,L) uint8");
    if (point_records.shape(1) >
        std::numeric_limits<uint16_t>::max())
        throw std::invalid_argument(
            "LAS waveform sidecar: point record length exceeds uint16");
    if (descriptor_vlrs.ndim() != 1 ||
        waveform_packet_record.ndim() != 1)
        throw std::invalid_argument(
            "LAS waveform sidecar: descriptor_vlrs and "
            "waveform_packet_record must be one-dimensional uint8 arrays");

    LasWaveformSidecar result;
    result.n = point_records.shape(0);
    result.point_format = point_format;
    result.version_minor = version_minor;
    result.global_encoding = global_encoding;
    result.point_record_length =
        static_cast<uint16_t>(point_records.shape(1));
    if (result.n != 0 &&
        result.point_record_length >
            std::numeric_limits<size_t>::max() / result.n)
        throw std::length_error(
            "LAS waveform sidecar: point-record extent overflows size_t");
    const size_t record_bytes =
        result.n * static_cast<size_t>(result.point_record_length);
    if (record_bytes != 0)
        result.point_records.assign(
            point_records.data(),
            point_records.data() + record_bytes);
    if (descriptor_vlrs.shape(0) != 0)
        result.descriptor_vlrs.assign(
            descriptor_vlrs.data(),
            descriptor_vlrs.data() + descriptor_vlrs.shape(0));
    if (waveform_packet_record.shape(0) != 0)
        result.waveform_packet_record.assign(
            waveform_packet_record.data(),
            waveform_packet_record.data() +
                waveform_packet_record.shape(0));
    validate_las_waveform_sidecar(result);
    return result;
}

PointCloud make_pc(farr positions, std::optional<carr> colors, std::optional<farr> normals,
                   std::optional<farr> intensity, const std::string &coordinate_frame,
                   double scale_to_meters, const std::string &intensity_range,
                   std::optional<c16arr> colors16, std::optional<darr> origin,
                   std::optional<size_t> width, std::optional<size_t> height,
                   std::optional<darr> viewpoint,
                   std::optional<LasWaveformSidecar> las_waveform) {
    // 1. positions (N,3): ndim==2 && shape(1)==3; N==0 is legal (an empty .xyz
    //    file must round-trip once the codec lands).
    if (positions.ndim() != 2 || positions.shape(1) != 3)
        throw std::invalid_argument("point_cloud: positions must be (N,3) float32");
    const size_t N = positions.shape(0);
    PointCloud p;
    p.n = N;
    p.xyz.assign(positions.data(), positions.data() + N * 3);  // one bulk copy

    // 2. optional fields: each must be exactly (N,3) / (N,); absent -> empty vector.
    if (colors) {
        if (colors->ndim() != 2 || colors->shape(1) != 3 || colors->shape(0) != N)
            throw std::invalid_argument("point_cloud: colors must be (N,3) uint8");
        p.rgb.assign(colors->data(), colors->data() + N * 3);
    }
    if (normals) {
        if (normals->ndim() != 2 || normals->shape(1) != 3 || normals->shape(0) != N)
            throw std::invalid_argument("point_cloud: normals must be (N,3) float32");
        p.normals.assign(normals->data(), normals->data() + N * 3);
    }
    if (intensity) {
        if (intensity->ndim() != 1 || intensity->shape(0) != N)
            throw std::invalid_argument("point_cloud: intensity must be (N,) float32");
        p.intensity.assign(intensity->data(), intensity->data() + N);
    }
    if (colors16) {
        if (colors16->ndim() != 2 || colors16->shape(1) != 3 || colors16->shape(0) != N)
            throw std::invalid_argument("point_cloud: colors16 must be (N,3) uint16");
        p.rgb16.assign(colors16->data(), colors16->data() + N * 3);
    }
    if (origin) {
        if (origin->ndim() != 1 || origin->shape(0) != 3)
            throw std::invalid_argument("point_cloud: origin must be (3,) float64");
        for (int i = 0; i < 3; i++) {
            if (!std::isfinite(origin->data()[i]))
                throw std::invalid_argument(
                    "point_cloud: origin values must be finite");
            p.origin[i] = origin->data()[i];
        }
    }
    if (width.has_value() != height.has_value())
        throw std::invalid_argument(
            "point_cloud: width and height must be provided together");
    if (width) {
        if (*height == 0 || (*width == 0 && *height != 1) ||
            (*width != 0 &&
             *height > std::numeric_limits<size_t>::max() / *width) ||
            *width * *height != N)
            throw std::invalid_argument(
                "point_cloud: width*height must equal the point count");
        p.organized_width = *width;
        p.organized_height = *height;
    }
    if (viewpoint) {
        if (viewpoint->ndim() != 1 || viewpoint->shape(0) != 7)
            throw std::invalid_argument(
                "point_cloud: viewpoint must be (7,) float64 "
                "(tx,ty,tz,qw,qx,qy,qz)");
        for (int i = 0; i < 7; ++i) {
            const double value = viewpoint->data()[i];
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "point_cloud: viewpoint values must be finite");
            p.viewpoint[i] = value;
        }
    }

    // 3. conventions: validate the closed vocabulary (Image's color_space
    //    precedent; stricter than make_pvs, which validates nothing).
    if (!pc_valid_frame(coordinate_frame))
        throw std::invalid_argument(
            "point_cloud: coordinate_frame must be unknown|opencv|opengl|enu|ned");
    if (!pc_valid_intensity_range(intensity_range))
        throw std::invalid_argument(
            "point_cloud: intensity_range must be unknown|unit|u8|u16");
    p.coordinate_frame = coordinate_frame;
    p.scale_to_meters = scale_to_meters;
    p.intensity_range = intensity_range;
    if (las_waveform) {
        validate_las_waveform_sidecar(*las_waveform);
        if (las_waveform->n != N)
            throw std::invalid_argument(
                "point_cloud: LAS waveform sidecar point count "
                "must match positions");
        p.las_waveform = std::make_shared<LasWaveformSidecar>(
            std::move(*las_waveform));
    }
    validate_point_cloud(p);
    return p;
}
}  // namespace

void validate_las_waveform_sidecar(
    const LasWaveformSidecar &sidecar, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    const size_t wave_offset = waveform_offset(sidecar.point_format);
    const size_t minimum =
        waveform_record_minimum(sidecar.point_format);
    if ((sidecar.point_format == 4 ||
         sidecar.point_format == 5)
            ? (sidecar.version_minor != 3 &&
               sidecar.version_minor != 4)
            : sidecar.version_minor != 4)
        throw std::invalid_argument(
            prefix + "point format is incompatible with LAS version");
    if ((sidecar.global_encoding & 0x0002U) == 0 ||
        (sidecar.global_encoding & 0x0004U) != 0 ||
        (sidecar.global_encoding & 0xfff4U) != 0)
        throw std::invalid_argument(
            prefix + "only internal waveform packets are supported");
    if (sidecar.point_record_length < minimum)
        throw std::invalid_argument(
            prefix + "point record is too short for its waveform format");
    if (sidecar.n != 0 &&
        sidecar.point_record_length >
            std::numeric_limits<size_t>::max() / sidecar.n)
        throw std::length_error(
            prefix + "point-record extent overflows size_t");
    if (sidecar.point_records.size() !=
        sidecar.n * sidecar.point_record_length)
        throw std::invalid_argument(
            prefix + "point-record bytes disagree with count and stride");

    std::array<bool, 256> descriptors{};
    size_t cursor = 0;
    while (cursor < sidecar.descriptor_vlrs.size()) {
        if (sidecar.descriptor_vlrs.size() - cursor < 54)
            throw std::invalid_argument(
                prefix + "truncated waveform descriptor VLR header");
        LeReader header(
            sidecar.descriptor_vlrs.data() + cursor,
            sidecar.descriptor_vlrs.size() - cursor);
        const uint16_t reserved = header.get<uint16_t>();
        const uint8_t *user_id =
            sidecar.descriptor_vlrs.data() + cursor + 2;
        header.pos = 18;
        const uint16_t record_id = header.get<uint16_t>();
        const uint16_t length = header.get<uint16_t>();
        if (reserved != 0 ||
            !fixed_ascii(user_id, 16, "LASF_Spec") ||
            record_id < 100 || record_id > 354 ||
            length != 26)
            throw std::invalid_argument(
                prefix + "only canonical LASF_Spec waveform "
                "descriptor VLRs are retained");
        if (cursor > sidecar.descriptor_vlrs.size() - 54 - length)
            throw std::invalid_argument(
                prefix + "truncated waveform descriptor VLR");
        const uint8_t index =
            static_cast<uint8_t>(record_id - 99);
        if (descriptors[index])
            throw std::invalid_argument(
                prefix + "duplicate waveform descriptor index");
        descriptors[index] = true;
        const uint8_t *payload =
            sidecar.descriptor_vlrs.data() + cursor + 54;
        const uint8_t bits = payload[0];
        const uint8_t compression = payload[1];
        if (bits < 2 || bits > 32 || compression != 0)
            throw std::invalid_argument(
                prefix + "waveform descriptor uses an unsupported "
                "bit depth or compression type");
        cursor += 54 + length;
    }
    if (cursor == 0)
        throw std::invalid_argument(
            prefix + "at least one waveform descriptor VLR is required");

    if (sidecar.waveform_packet_record.size() < 60)
        throw std::invalid_argument(
            prefix + "waveform packet EVLR is truncated");
    LeReader packet_header(
        sidecar.waveform_packet_record.data(),
        sidecar.waveform_packet_record.size());
    const uint16_t packet_reserved =
        packet_header.get<uint16_t>();
    const uint8_t *packet_user =
        sidecar.waveform_packet_record.data() + 2;
    packet_header.pos = 18;
    const uint16_t packet_id =
        packet_header.get<uint16_t>();
    const uint64_t packet_length =
        packet_header.get<uint64_t>();
    if (packet_reserved != 0 ||
        !fixed_ascii(packet_user, 16, "LASF_Spec") ||
        packet_id != 65535 ||
        packet_length !=
            sidecar.waveform_packet_record.size() - 60)
        throw std::invalid_argument(
            prefix + "waveform packet EVLR header is malformed");

    for (size_t row = 0; row < sidecar.n; ++row) {
        const uint8_t *record =
            sidecar.point_records.data() +
            row * sidecar.point_record_length;
        LeReader values(record, sidecar.point_record_length);
        values.pos = wave_offset;
        const uint8_t descriptor = values.get<uint8_t>();
        const uint64_t offset = values.get<uint64_t>();
        const uint32_t size = values.get<uint32_t>();
        const float location = values.get<float>();
        const float dx = values.get<float>();
        const float dy = values.get<float>();
        const float dz = values.get<float>();
        if (descriptor == 0) {
            if (offset != 0 || size != 0)
                throw std::invalid_argument(
                    prefix + "point without a waveform descriptor "
                    "has a non-empty packet reference");
        } else {
            if (!descriptors[descriptor])
                throw std::invalid_argument(
                    prefix + "point references a missing waveform descriptor");
            if (offset < 60 ||
                offset > sidecar.waveform_packet_record.size() ||
                size >
                    sidecar.waveform_packet_record.size() -
                        static_cast<size_t>(offset))
                throw std::invalid_argument(
                    prefix + "waveform packet reference is out of bounds");
        }
        if (!std::isfinite(location) || !std::isfinite(dx) ||
            !std::isfinite(dy) || !std::isfinite(dz))
            throw std::invalid_argument(
                prefix + "waveform location and direction must be finite");
    }
}

void validate_point_cloud(
    const PointCloud &cloud, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    const size_t count = cloud.n;
    if (count > std::numeric_limits<size_t>::max() / 3 ||
        cloud.xyz.size() != count * 3 ||
        (!cloud.rgb.empty() && cloud.rgb.size() != count * 3) ||
        (!cloud.rgb16.empty() && cloud.rgb16.size() != count * 3) ||
        (!cloud.normals.empty() &&
         cloud.normals.size() != count * 3) ||
        (!cloud.intensity.empty() &&
         cloud.intensity.size() != count))
        throw std::invalid_argument(
            prefix + "inconsistent PointCloud field lengths");
    if (!pc_valid_frame(cloud.coordinate_frame) ||
        !pc_valid_intensity_range(cloud.intensity_range))
        throw std::invalid_argument(
            prefix + "invalid convention metadata");
    // PointCloud has historically preserved every float bit pattern, including
    // NaN payloads and unknown/non-positive unit tags. Format writers apply
    // their own representability rules; structural validation must not narrow
    // that established record contract.
    for (double value : cloud.origin)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                prefix + "origin must be finite");
    for (double value : cloud.viewpoint)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                prefix + "viewpoint must be finite");
    if (cloud.organized_height != 0) {
        if (cloud.organized_width != 0 &&
            cloud.organized_height >
                std::numeric_limits<size_t>::max() /
                    cloud.organized_width)
            throw std::length_error(
                prefix + "organized extent overflows size_t");
        if (cloud.organized_height == 0 ||
            cloud.organized_width * cloud.organized_height != count)
            throw std::invalid_argument(
                prefix + "organized dimensions disagree with point count");
    } else if (cloud.organized_width != 0) {
        throw std::invalid_argument(
            prefix + "organized width requires an explicit height");
    }
    if (cloud.las_waveform) {
        validate_las_waveform_sidecar(
            *cloud.las_waveform,
            (prefix + "LAS waveform").c_str());
        if (cloud.las_waveform->n != count)
            throw std::invalid_argument(
                prefix + "LAS waveform count disagrees with points");
    }
}

void register_point_cloud(nb::module_ &m) {
    auto ri = nb::rv_policy::reference_internal;  // fixed-dtype record => vw + ri
    nb::class_<LasWaveformSidecar>(
        m, "LasWaveformSidecar")
        .def_prop_ro(
            "num_points",
            [](const LasWaveformSidecar &sidecar) {
                return sidecar.n;
            })
        .def_prop_ro(
            "point_format",
            [](const LasWaveformSidecar &sidecar) {
                return sidecar.point_format;
            })
        .def_prop_ro(
            "version_minor",
            [](const LasWaveformSidecar &sidecar) {
                return sidecar.version_minor;
            })
        .def_prop_ro(
            "global_encoding",
            [](const LasWaveformSidecar &sidecar) {
                return sidecar.global_encoding;
            })
        .def_prop_ro(
            "point_record_length",
            [](const LasWaveformSidecar &sidecar) {
                return sidecar.point_record_length;
            })
        .def_prop_ro(
            "point_records",
            [](const LasWaveformSidecar &sidecar) {
                return vw(
                    sidecar.point_records,
                    {sidecar.n, sidecar.point_record_length});
            },
            ri)
        .def_prop_ro(
            "descriptor_vlrs",
            [](const LasWaveformSidecar &sidecar) {
                return vw(
                    sidecar.descriptor_vlrs,
                    {sidecar.descriptor_vlrs.size()});
            },
            ri)
        .def_prop_ro(
            "waveform_packet_record",
            [](const LasWaveformSidecar &sidecar) {
                return vw(
                    sidecar.waveform_packet_record,
                    {sidecar.waveform_packet_record.size()});
            },
            ri);
    m.def(
        "las_waveform_sidecar", &make_las_waveform_sidecar,
        "point_format"_a, "version_minor"_a,
        "global_encoding"_a, "point_records"_a,
        "descriptor_vlrs"_a, "waveform_packet_record"_a,
        "Build a validated opaque sidecar for internal LAS waveform "
        "point formats 4, 5, 9, or 10.");

    nb::class_<PointCloud>(m, "PointCloud")
        .def_prop_ro("num_points", [](const PointCloud &p) { return p.num_points(); })
        .def_prop_ro("positions", [](const PointCloud &p) { return vw(p.xyz, {p.n, 3}); }, ri)
        .def_prop_ro(
            "colors", [](const PointCloud &p) { return vw(p.rgb, {p.has_rgb() ? p.n : 0, 3}); }, ri)
        .def_prop_ro(
            "colors16", [](const PointCloud &p) { return vw(p.rgb16, {p.has_rgb16() ? p.n : 0, 3}); },
            ri)
        .def_prop_ro(
            "normals",
            [](const PointCloud &p) { return vw(p.normals, {p.has_normals() ? p.n : 0, 3}); }, ri)
        .def_prop_ro(
            "intensities", [](const PointCloud &p) { return vw(p.intensity, {p.intensity.size()}); },
            ri)
        .def_prop_ro("has_rgb", [](const PointCloud &p) { return p.has_rgb(); })
        .def_prop_ro("has_rgb16", [](const PointCloud &p) { return p.has_rgb16(); })
        .def_prop_ro("has_normals", [](const PointCloud &p) { return p.has_normals(); })
        .def_prop_ro("has_intensity", [](const PointCloud &p) { return p.has_intensity(); })
        .def_prop_ro(
            "has_las_waveform",
            [](const PointCloud &p) {
                return p.has_las_waveform();
            })
        .def_prop_ro(
            "las_waveform",
            [](PointCloud &p) -> LasWaveformSidecar * {
                return p.las_waveform.get();
            },
            ri)
        .def_prop_ro("width", [](const PointCloud &p) { return p.width(); })
        .def_prop_ro("height", [](const PointCloud &p) { return p.height(); })
        .def_prop_ro("is_organized", [](const PointCloud &p) { return p.is_organized(); })
        // conventions the codec recorded (metadata, not fixed):
        .def_prop_ro("coordinate_frame", [](const PointCloud &p) { return p.coordinate_frame; })
        .def_prop_ro("scale_to_meters", [](const PointCloud &p) { return p.scale_to_meters; })
        .def_prop_ro("intensity_range", [](const PointCloud &p) { return p.intensity_range; })
        .def_prop_ro("origin",
                     [](const PointCloud &p) {
                         return nb::make_tuple(p.origin[0], p.origin[1], p.origin[2]);
                     })
        .def_prop_ro(
            "viewpoint",
            [](const PointCloud &p) {
                return nb::make_tuple(
                    p.viewpoint[0], p.viewpoint[1], p.viewpoint[2],
                    p.viewpoint[3], p.viewpoint[4], p.viewpoint[5],
                    p.viewpoint[6]);
            })
        .def("__repr__", [](const PointCloud &p) {
            return "<PointCloud n=" + std::to_string(p.n) + (p.has_rgb() ? " rgb" : "") +
                   (p.has_normals() ? " normals" : "") + (p.has_intensity() ? " intensity" : "") +
                   (p.has_las_waveform() ? " las-waveform" : "") +
                   (p.is_organized() ? " organized" : "") +
                   " " + p.coordinate_frame + ">";
        });

    m.def("point_cloud", &make_pc, "positions"_a, "colors"_a = nb::none(), "normals"_a = nb::none(),
          "intensity"_a = nb::none(), "coordinate_frame"_a = "unknown", "scale_to_meters"_a = 1.0,
          "intensity_range"_a = "unknown", "colors16"_a = nb::none(), "origin"_a = nb::none(),
          "width"_a = nb::none(), "height"_a = nb::none(),
          "viewpoint"_a = nb::none(),
          "las_waveform"_a = nb::none(),
          "Build a PointCloud from arrays (numpy/torch): positions (N,3) float32, optional "
          "colors (N,3) uint8 / colors16 (N,3) uint16 / normals (N,3) float32 / intensity (N,) "
          "float32 (foreign dtypes are copy-converted), recorded convention tags "
          "(coordinate_frame, scale_to_meters, intensity_range), a georef origin (3,) float64, "
          "optional organized width/height, viewpoint (tx,ty,tz,qw,qx,qy,qz), "
          "and a validated opaque LAS waveform sidecar.");
}
