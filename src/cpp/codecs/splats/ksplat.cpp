// mkkellogg/GaussianSplats3D KSplat v0.1 codec.
//
// The format contract is pinned to GaussianSplats3D v0.4.7 commit
// eb2fc4593e3ea5e75388296fcdde2459542d1290 (MIT):
//   * one 4096-byte little-endian file header;
//   * maxSectionCount 1024-byte section headers;
//   * per-section optional position buckets followed by interleaved splats;
//   * compression 0 = float32, 1 = float16, 2 = float16 plus UNORM8 SH;
//   * per-section SH degree 0, 1, or 2.
//
// GaussianCloud stores WXYZ quaternions, log scales, logit opacity, and
// channel-grouped SH. KSplat stores WXYZ, linear scales, RGBA8, and a
// degree-grouped/channel-grouped SH hybrid, so those mappings are explicit.
// The writer emits one deterministic section and refuses degree-3 SH because
// v0.1 cannot represent it.
#include <nanobind/nanobind.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include "io/common.hpp"
#include "records/gaussian_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kHeaderSize = 4096;
constexpr size_t kSectionHeaderSize = 1024;
constexpr uint8_t kVersionMajor = 0;
constexpr uint8_t kVersionMinor = 1;
constexpr uint16_t kBucketStorageSize = 12;
constexpr uint32_t kCompressionScaleRange = 32767;
constexpr float kDefaultShMin = -1.5f;
constexpr float kDefaultShMax = 1.5f;
constexpr double kShC0 = 0.28209479177387814;
constexpr double kAlphaEpsilon = 1e-6;

size_t checked_add(size_t a, size_t b, const char *what) {
    if (b > std::numeric_limits<size_t>::max() - a)
        throw std::invalid_argument(std::string("ksplat: ") + what +
                                    " overflows address space");
    return a + b;
}

size_t checked_mul(size_t a, size_t b, const char *what) {
    if (a != 0 && b > std::numeric_limits<size_t>::max() / a)
        throw std::invalid_argument(std::string("ksplat: ") + what +
                                    " overflows address space");
    return a * b;
}

uint16_t load_u16(const uint8_t *p) {
    return static_cast<uint16_t>(p[0]) |
           static_cast<uint16_t>(static_cast<uint16_t>(p[1]) << 8);
}

uint32_t load_u32(const uint8_t *p) {
    return static_cast<uint32_t>(p[0]) |
           (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}

float load_f32(const uint8_t *p) {
    const uint32_t bits = load_u32(p);
    float value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

void store_u16(uint8_t *p, uint16_t value) {
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8);
}

void store_u32(uint8_t *p, uint32_t value) {
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8);
    p[2] = static_cast<uint8_t>(value >> 16);
    p[3] = static_cast<uint8_t>(value >> 24);
}

void store_f32(uint8_t *p, float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    store_u32(p, bits);
}

// Matches THREE.DataUtils.toHalfFloat(): clamp is handled by the caller and
// the mantissa is truncated, not rounded to nearest.
uint16_t to_three_half(float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    const uint32_t sign = (bits >> 16) & 0x8000u;
    const int exponent = static_cast<int>((bits >> 23) & 0xffu) - 127;
    const uint32_t mantissa = bits & 0x007fffffu;
    if (exponent < -27) return static_cast<uint16_t>(sign);
    if (exponent < -14) {
        const uint32_t base = 0x0400u >> (-exponent - 14);
        const uint32_t shift = static_cast<uint32_t>(-exponent - 1);
        return static_cast<uint16_t>(sign | base | (mantissa >> shift));
    }
    if (exponent <= 15)
        return static_cast<uint16_t>(
            sign | (static_cast<uint32_t>(exponent + 15) << 10) |
            (mantissa >> 13));
    if (exponent < 128) return static_cast<uint16_t>(sign | 0x7c00u);
    return static_cast<uint16_t>(sign | 0x7c00u | (mantissa >> 13));
}

float from_half(uint16_t value) {
    const uint32_t sign = static_cast<uint32_t>(value & 0x8000u) << 16;
    uint32_t exponent = (value >> 10) & 0x1fu;
    uint32_t mantissa = value & 0x03ffu;
    uint32_t bits;
    if (exponent == 0) {
        if (mantissa == 0) {
            bits = sign;
        } else {
            int shift = 0;
            while ((mantissa & 0x0400u) == 0) {
                mantissa <<= 1;
                ++shift;
            }
            mantissa &= 0x03ffu;
            const uint32_t exp32 =
                static_cast<uint32_t>(127 - 14 - shift);
            bits = sign | (exp32 << 23) | (mantissa << 13);
        }
    } else if (exponent == 31) {
        bits = sign | 0x7f800000u | (mantissa << 13);
    } else {
        exponent = exponent + (127 - 15);
        bits = sign | (exponent << 23) | (mantissa << 13);
    }
    float result;
    std::memcpy(&result, &bits, sizeof(result));
    return result;
}

size_t coefficients_per_channel(int degree) {
    if (degree == 0) return 0;
    if (degree == 1) return 3;
    if (degree == 2) return 8;
    throw std::invalid_argument("ksplat: SH degree must be 0, 1, or 2");
}

size_t bytes_per_splat(int compression, int degree) {
    const size_t sh = coefficients_per_channel(degree) * 3;
    if (compression == 0) return checked_add(44, checked_mul(sh, 4, "SH storage"), "record storage");
    if (compression == 1) return checked_add(24, checked_mul(sh, 2, "SH storage"), "record storage");
    if (compression == 2) return checked_add(24, sh, "record storage");
    throw std::invalid_argument("ksplat: compression level must be 0, 1, or 2");
}

struct Section {
    size_t count = 0;
    size_t loaded_count = 0;
    uint32_t bucket_size = 0;
    size_t bucket_count = 0;
    float block_size = 0;
    uint32_t scale_range = 0;
    size_t full_buckets = 0;
    size_t partial_buckets = 0;
    int degree = 0;
    size_t record_size = 0;
    size_t base = 0;
    size_t buckets_base = 0;
    size_t data_base = 0;
    size_t storage_size = 0;
    size_t global_offset = 0;
    std::vector<size_t> bucket_prefix;
};

struct Layout {
    int compression = 0;
    size_t count = 0;
    size_t loaded_count = 0;
    size_t declared_sections = 0;
    size_t loaded_sections = 0;
    int degree = 0;
    float scene_x = 0;
    float scene_y = 0;
    float scene_z = 0;
    float sh_min = kDefaultShMin;
    float sh_max = kDefaultShMax;
    std::vector<Section> sections;
};

Layout parse_layout(const uint8_t *data, size_t available, size_t file_size,
                    bool validate_payload) {
    if (available < kHeaderSize)
        throw std::invalid_argument("ksplat: truncated 4096-byte header");
    if (data[0] != kVersionMajor || data[1] != kVersionMinor)
        throw std::invalid_argument(
            "ksplat: unsupported version " + std::to_string(data[0]) + "." +
            std::to_string(data[1]) + " (expected 0.1)");

    Layout layout;
    layout.declared_sections = load_u32(data + 4);
    layout.loaded_sections = load_u32(data + 8);
    const size_t header_max_count = load_u32(data + 12);
    const size_t header_loaded_count = load_u32(data + 16);
    layout.compression = static_cast<int>(load_u16(data + 20));
    if (layout.compression < 0 || layout.compression > 2)
        throw std::invalid_argument(
            "ksplat: compression level must be 0, 1, or 2");
    if (layout.declared_sections == 0)
        throw std::invalid_argument("ksplat: maxSectionCount must be positive");
    if (layout.loaded_sections > layout.declared_sections)
        throw std::invalid_argument(
            "ksplat: sectionCount exceeds maxSectionCount");
    if (header_loaded_count > header_max_count)
        throw std::invalid_argument(
            "ksplat: splatCount exceeds maxSplatCount");

    layout.scene_x = load_f32(data + 24);
    layout.scene_y = load_f32(data + 28);
    layout.scene_z = load_f32(data + 32);
    if (!std::isfinite(layout.scene_x) || !std::isfinite(layout.scene_y) ||
        !std::isfinite(layout.scene_z))
        throw std::invalid_argument("ksplat: scene center is non-finite");
    const float raw_sh_min = load_f32(data + 36);
    const float raw_sh_max = load_f32(data + 40);
    layout.sh_min = raw_sh_min == 0.0f ? kDefaultShMin : raw_sh_min;
    layout.sh_max = raw_sh_max == 0.0f ? kDefaultShMax : raw_sh_max;
    if (!std::isfinite(layout.sh_min) || !std::isfinite(layout.sh_max))
        throw std::invalid_argument("ksplat: SH quantization range is non-finite");

    const size_t section_header_bytes =
        checked_mul(layout.declared_sections, kSectionHeaderSize,
                    "section headers");
    const size_t headers_end =
        checked_add(kHeaderSize, section_header_bytes, "section headers");
    if (headers_end > file_size || headers_end > available)
        throw std::invalid_argument("ksplat: truncated section headers");

    layout.sections.reserve(layout.declared_sections);
    size_t section_base = headers_end;
    size_t global_offset = 0;
    size_t loaded_total = 0;
    int minimum_degree = 2;
    for (size_t index = 0; index < layout.declared_sections; ++index) {
        const uint8_t *header =
            data + kHeaderSize + index * kSectionHeaderSize;
        Section section;
        section.loaded_count = load_u32(header);
        section.count = load_u32(header + 4);
        section.bucket_size = load_u32(header + 8);
        section.bucket_count = load_u32(header + 12);
        section.block_size = load_f32(header + 16);
        const uint16_t bucket_storage = load_u16(header + 20);
        section.scale_range = load_u32(header + 24);
        const size_t declared_storage = load_u32(header + 28);
        section.full_buckets = load_u32(header + 32);
        section.partial_buckets = load_u32(header + 36);
        section.degree = static_cast<int>(load_u16(header + 40));
        section.record_size =
            bytes_per_splat(layout.compression, section.degree);
        section.global_offset = global_offset;
        if (section.loaded_count > section.count)
            throw std::invalid_argument(
                "ksplat: section splatCount exceeds maxSplatCount");

        size_t bucket_metadata = 0;
        if (layout.compression == 0) {
            if (section.bucket_size != 0 || section.bucket_count != 0 ||
                section.block_size != 0.0f || bucket_storage != 0 ||
                section.scale_range != 0 || section.full_buckets != 0 ||
                section.partial_buckets != 0)
                throw std::invalid_argument(
                    "ksplat: uncompressed section contains bucket metadata");
        } else {
            if (section.count == 0) {
                if (section.bucket_count != 0 || section.full_buckets != 0 ||
                    section.partial_buckets != 0)
                    throw std::invalid_argument(
                        "ksplat: empty section contains buckets");
            } else if (section.bucket_count == 0) {
                throw std::invalid_argument(
                    "ksplat: compressed non-empty section has no buckets");
            }
            if (section.bucket_size == 0)
                throw std::invalid_argument(
                    "ksplat: compressed section has zero bucket size");
            if (!std::isfinite(section.block_size) ||
                !(section.block_size > 0.0f))
                throw std::invalid_argument(
                    "ksplat: compressed section has invalid block size");
            if (bucket_storage != kBucketStorageSize)
                throw std::invalid_argument(
                    "ksplat: bucket centers must contain three float32 values");
            if (section.scale_range == 0)
                section.scale_range = kCompressionScaleRange;
            if (section.scale_range > 65535u)
                throw std::invalid_argument(
                    "ksplat: position compression range exceeds uint16");
            if (section.full_buckets > section.bucket_count ||
                section.partial_buckets >
                    section.bucket_count - section.full_buckets ||
                section.full_buckets + section.partial_buckets !=
                    section.bucket_count)
                throw std::invalid_argument(
                    "ksplat: inconsistent bucket counts");
            bucket_metadata = checked_add(
                checked_mul(section.partial_buckets, 4,
                            "partial-bucket metadata"),
                checked_mul(section.bucket_count, kBucketStorageSize,
                            "bucket centers"),
                "bucket metadata");
        }
        const size_t records =
            checked_mul(section.count, section.record_size, "section records");
        section.storage_size =
            checked_add(bucket_metadata, records, "section storage");
        if (declared_storage != section.storage_size)
            throw std::invalid_argument(
                "ksplat: section storageSizeBytes disagrees with its layout");
        section.base = section_base;
        section.buckets_base = checked_add(
            section.base, checked_mul(section.partial_buckets, 4,
                                      "partial-bucket metadata"),
            "bucket center offset");
        section.data_base =
            checked_add(section.base, bucket_metadata, "record offset");
        section_base =
            checked_add(section_base, section.storage_size, "file extent");
        if (section_base > file_size)
            throw std::invalid_argument("ksplat: truncated section payload");

        global_offset =
            checked_add(global_offset, section.count, "splat count");
        loaded_total =
            checked_add(loaded_total, section.loaded_count, "loaded splat count");
        minimum_degree = std::min(minimum_degree, section.degree);
        layout.sections.push_back(std::move(section));
    }
    if (section_base != file_size)
        throw std::invalid_argument(
            section_base < file_size ? "ksplat: trailing bytes after sections"
                                     : "ksplat: truncated section payload");
    if (global_offset != header_max_count)
        throw std::invalid_argument(
            "ksplat: header maxSplatCount disagrees with section counts");
    if (loaded_total != header_loaded_count)
        throw std::invalid_argument(
            "ksplat: header splatCount disagrees with section counts");
    layout.count = global_offset;
    layout.loaded_count = loaded_total;
    layout.degree = minimum_degree;
    if (layout.compression == 2 && layout.degree > 0 &&
        layout.sh_min > layout.sh_max)
        throw std::invalid_argument(
            "ksplat: reversed SH quantization range");

    if (!validate_payload) return layout;
    if (available != file_size)
        throw std::invalid_argument(
            "ksplat: full validation requires the complete file");

    for (Section &section : layout.sections) {
        if (layout.compression == 0) continue;
        section.bucket_prefix.reserve(section.bucket_count + 1);
        section.bucket_prefix.push_back(0);
        size_t covered = 0;
        const size_t full_points =
            checked_mul(section.full_buckets,
                        static_cast<size_t>(section.bucket_size),
                        "full-bucket point count");
        if (full_points > section.count)
            throw std::invalid_argument(
                "ksplat: full buckets exceed the section point count");
        for (size_t i = 0; i < section.full_buckets; ++i) {
            covered = checked_add(covered, section.bucket_size,
                                  "bucket point count");
            section.bucket_prefix.push_back(covered);
        }
        for (size_t i = 0; i < section.partial_buckets; ++i) {
            const size_t length = load_u32(data + section.base + i * 4);
            if (length == 0 || length >= section.bucket_size)
                throw std::invalid_argument(
                    "ksplat: invalid partially-filled bucket length");
            covered =
                checked_add(covered, length, "partial-bucket point count");
            if (covered > section.count)
                throw std::invalid_argument(
                    "ksplat: bucket lengths exceed the section point count");
            section.bucket_prefix.push_back(covered);
        }
        if (covered != section.count ||
            section.bucket_prefix.size() != section.bucket_count + 1)
            throw std::invalid_argument(
                "ksplat: buckets do not cover the section point count");
        for (size_t bucket = 0; bucket < section.bucket_count; ++bucket) {
            const uint8_t *center =
                data + section.buckets_base + bucket * kBucketStorageSize;
            if (!std::isfinite(load_f32(center)) ||
                !std::isfinite(load_f32(center + 4)) ||
                !std::isfinite(load_f32(center + 8)))
                throw std::invalid_argument(
                    "ksplat: bucket center is non-finite");
        }
    }
    return layout;
}

float decode_scalar(const uint8_t *p, int compression) {
    return compression == 0 ? load_f32(p) : from_half(load_u16(p));
}

size_t sh_record_index(size_t channel, size_t coefficient) {
    if (coefficient < 3) return channel * 3 + coefficient;
    return 9 + channel * 5 + (coefficient - 3);
}

GaussianCloud read_ksplat_impl(nb::handle source, bool partial, size_t start,
                               size_t stop) {
    ByteView view(source);
    const uint8_t *data = view.data();
    const size_t size = view.size();
    GaussianCloud cloud;
    cloud.quaternion_norm = "unit";
    {
        nb::gil_scoped_release release;
        Layout layout = parse_layout(data, size, size, true);
        if (!partial) {
            start = 0;
            stop = layout.count;
        } else {
            checked_half_open_range(start, stop, layout.count,
                                    "ksplat point range");
        }
        const size_t selected = stop - start;
        const size_t coefficients =
            coefficients_per_channel(layout.degree);
        cloud.n = selected;
        cloud.sh_degree = layout.degree;
        cloud.num_rest = coefficients * 3;
        cloud.means.resize(checked_mul(selected, 3, "output means"));
        cloud.scales.resize(checked_mul(selected, 3, "output scales"));
        cloud.quats.resize(checked_mul(selected, 4, "output quaternions"));
        cloud.opacity.resize(selected);
        cloud.sh_dc.resize(checked_mul(selected, 3, "output DC"));
        cloud.sh_rest.resize(
            checked_mul(selected, cloud.num_rest, "output SH"));

        size_t output = 0;
        for (const Section &section : layout.sections) {
            const size_t section_start = section.global_offset;
            const size_t section_stop =
                checked_add(section_start, section.count, "section range");
            if (stop <= section_start || start >= section_stop) continue;
            const size_t local_start =
                std::max(start, section_start) - section_start;
            const size_t local_stop =
                std::min(stop, section_stop) - section_start;
            const size_t scale_offset = layout.compression == 0 ? 12 : 6;
            const size_t rotation_offset = layout.compression == 0 ? 24 : 12;
            const size_t color_offset = layout.compression == 0 ? 40 : 20;
            const size_t sh_offset = layout.compression == 0 ? 44 : 24;
            const size_t scalar_bytes = layout.compression == 0 ? 4 : 2;

            for (size_t local = local_start; local < local_stop;
                 ++local, ++output) {
                const uint8_t *record =
                    data + section.data_base + local * section.record_size;
                if (layout.compression == 0) {
                    for (size_t axis = 0; axis < 3; ++axis) {
                        const float value = load_f32(record + axis * 4);
                        if (!std::isfinite(value))
                            throw std::invalid_argument(
                                "ksplat: position is non-finite");
                        cloud.means[output * 3 + axis] = value;
                    }
                } else {
                    const auto it = std::upper_bound(
                        section.bucket_prefix.begin(),
                        section.bucket_prefix.end(), local);
                    if (it == section.bucket_prefix.begin())
                        throw std::invalid_argument(
                            "ksplat: invalid bucket point mapping");
                    const size_t bucket = static_cast<size_t>(
                        it - section.bucket_prefix.begin() - 1);
                    if (bucket >= section.bucket_count)
                        throw std::invalid_argument(
                            "ksplat: invalid bucket point mapping");
                    const uint8_t *center =
                        data + section.buckets_base +
                        bucket * kBucketStorageSize;
                    const double factor =
                        (static_cast<double>(section.block_size) * 0.5) /
                        static_cast<double>(section.scale_range);
                    for (size_t axis = 0; axis < 3; ++axis) {
                        const double quantized =
                            static_cast<double>(
                                load_u16(record + axis * 2)) -
                            static_cast<double>(section.scale_range);
                        const double value =
                            quantized * factor +
                            static_cast<double>(load_f32(center + axis * 4));
                        if (!std::isfinite(value))
                            throw std::invalid_argument(
                                "ksplat: decoded position is non-finite");
                        cloud.means[output * 3 + axis] =
                            static_cast<float>(value);
                    }
                }

                for (size_t axis = 0; axis < 3; ++axis) {
                    const float linear =
                        decode_scalar(record + scale_offset +
                                          axis * scalar_bytes,
                                      layout.compression);
                    if (!std::isfinite(linear) || !(linear > 0.0f))
                        throw std::invalid_argument(
                            "ksplat: scale must decode to a finite positive value");
                    cloud.scales[output * 3 + axis] = std::log(linear);
                }

                double quaternion[4];
                double norm_squared = 0.0;
                for (size_t component = 0; component < 4; ++component) {
                    const float value =
                        decode_scalar(record + rotation_offset +
                                          component * scalar_bytes,
                                      layout.compression);
                    if (!std::isfinite(value))
                        throw std::invalid_argument(
                            "ksplat: quaternion is non-finite");
                    quaternion[component] = value;
                    norm_squared += quaternion[component] *
                                    quaternion[component];
                }
                const double norm = std::sqrt(norm_squared);
                if (!std::isfinite(norm) || !(norm > 0.0))
                    throw std::invalid_argument(
                        "ksplat: quaternion has zero or invalid norm");
                const double sign = quaternion[0] < 0.0 ? -1.0 : 1.0;
                for (size_t component = 0; component < 4; ++component)
                    cloud.quats[output * 4 + component] =
                        static_cast<float>(quaternion[component] / norm * sign);

                for (size_t channel = 0; channel < 3; ++channel) {
                    const double color =
                        static_cast<double>(record[color_offset + channel]) /
                        255.0;
                    cloud.sh_dc[output * 3 + channel] =
                        static_cast<float>((color - 0.5) / kShC0);
                }
                double alpha =
                    static_cast<double>(record[color_offset + 3]) / 255.0;
                alpha = std::min(std::max(alpha, kAlphaEpsilon),
                                 1.0 - kAlphaEpsilon);
                cloud.opacity[output] =
                    static_cast<float>(std::log(alpha / (1.0 - alpha)));

                for (size_t channel = 0; channel < 3; ++channel) {
                    for (size_t coefficient = 0;
                         coefficient < coefficients; ++coefficient) {
                        const size_t encoded_index =
                            sh_record_index(channel, coefficient);
                        float value;
                        if (layout.compression == 0) {
                            value = load_f32(record + sh_offset +
                                             encoded_index * 4);
                        } else if (layout.compression == 1) {
                            value = from_half(load_u16(
                                record + sh_offset + encoded_index * 2));
                        } else {
                            const double range =
                                static_cast<double>(layout.sh_max) -
                                static_cast<double>(layout.sh_min);
                            value = static_cast<float>(
                                static_cast<double>(
                                    record[sh_offset + encoded_index]) /
                                    255.0 *
                                    range +
                                static_cast<double>(layout.sh_min));
                        }
                        if (!std::isfinite(value))
                            throw std::invalid_argument(
                                "ksplat: SH coefficient is non-finite");
                        cloud.sh_rest[output * cloud.num_rest +
                                      channel * coefficients + coefficient] =
                            value;
                    }
                }
            }
        }
        if (output != selected)
            throw std::invalid_argument(
                "ksplat: point range did not map to section data");
    }
    return cloud;
}

GaussianCloud read_ksplat(nb::handle source) {
    return read_ksplat_impl(source, false, 0, 0);
}

GaussianCloud read_ksplat_points(nb::handle source, size_t start, size_t stop) {
    return read_ksplat_impl(source, true, start, stop);
}

struct Bucket {
    std::vector<size_t> rows;
    std::array<double, 3> center{};
};

uint64_t checked_u64_mul(uint64_t a, uint64_t b, const char *what) {
    if (a != 0 && b > std::numeric_limits<uint64_t>::max() / a)
        throw std::invalid_argument(std::string("ksplat: ") + what +
                                    " exceeds the supported bucket grid");
    return a * b;
}

uint64_t checked_u64_add(uint64_t a, uint64_t b, const char *what) {
    if (b > std::numeric_limits<uint64_t>::max() - a)
        throw std::invalid_argument(std::string("ksplat: ") + what +
                                    " exceeds the supported bucket grid");
    return a + b;
}

std::vector<Bucket> make_buckets(const GaussianCloud &cloud,
                                 double block_size, size_t bucket_size,
                                 size_t &full_count) {
    std::vector<Bucket> full;
    std::map<uint64_t, Bucket> partial;
    full_count = 0;
    if (cloud.n == 0) return full;

    std::array<double, 3> minimum{};
    std::array<double, 3> maximum{};
    for (size_t row = 0; row < cloud.n; ++row) {
        for (size_t axis = 0; axis < 3; ++axis) {
            const double value = cloud.means[row * 3 + axis];
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "ksplat: means must be finite");
            if (row == 0 || value < minimum[axis]) minimum[axis] = value;
            if (row == 0 || value > maximum[axis]) maximum[axis] = value;
        }
    }
    auto block_count = [&](size_t axis) -> uint64_t {
        // Include the block containing an exact positive boundary. The
        // reference's ceil(extent/block) collapses that block onto the next
        // radix digit when the extent is an exact multiple of block_size.
        const double count =
            std::floor((maximum[axis] - minimum[axis]) / block_size) + 1.0;
        if (!std::isfinite(count) ||
            count >= static_cast<double>(
                         std::numeric_limits<uint64_t>::max()))
            throw std::invalid_argument(
                "ksplat: point extent exceeds the supported bucket grid");
        return static_cast<uint64_t>(count);
    };
    const uint64_t y_blocks = block_count(1);
    const uint64_t z_blocks = block_count(2);
    const uint64_t yz_blocks =
        checked_u64_mul(y_blocks, z_blocks, "bucket grid");
    const double half = block_size * 0.5;

    for (size_t row = 0; row < cloud.n; ++row) {
        uint64_t coordinates[3];
        for (size_t axis = 0; axis < 3; ++axis) {
            const double coordinate =
                std::floor((static_cast<double>(
                                cloud.means[row * 3 + axis]) -
                            minimum[axis]) /
                           block_size);
            if (!std::isfinite(coordinate) || coordinate < 0.0 ||
                coordinate >=
                    static_cast<double>(std::numeric_limits<uint64_t>::max()))
                throw std::invalid_argument(
                    "ksplat: invalid bucket coordinate");
            coordinates[axis] = static_cast<uint64_t>(coordinate);
        }
        uint64_t id =
            checked_u64_mul(coordinates[0], yz_blocks, "bucket id");
        id = checked_u64_add(
            id, checked_u64_mul(coordinates[1], z_blocks, "bucket id"),
            "bucket id");
        id = checked_u64_add(id, coordinates[2], "bucket id");
        auto [it, inserted] = partial.try_emplace(id);
        Bucket &bucket = it->second;
        if (inserted) {
            for (size_t axis = 0; axis < 3; ++axis)
                bucket.center[axis] =
                    static_cast<double>(coordinates[axis]) * block_size +
                    minimum[axis] + half;
        }
        bucket.rows.push_back(row);
        if (bucket.rows.size() == bucket_size) {
            full.push_back(std::move(bucket));
            partial.erase(it);
        }
    }

    full_count = full.size();
    full.reserve(full.size() + partial.size());
    for (auto &entry : partial) full.push_back(std::move(entry.second));
    return full;
}

uint8_t quantize_byte_floor(double value) {
    if (std::isnan(value)) return 0;
    value = std::floor(value);
    value = std::min(std::max(value, 0.0), 255.0);
    return static_cast<uint8_t>(value);
}

double sigmoid(double value) {
    if (value >= 0.0) return 1.0 / (1.0 + std::exp(-value));
    const double e = std::exp(value);
    return e / (1.0 + e);
}

nb::bytes write_ksplat(const GaussianCloud &cloud, int compression_level,
                       float block_size, size_t bucket_size) {
    require_3dgs_gaussian_conventions(cloud, "ksplat writer");
    std::string encoded;
    {
        nb::gil_scoped_release release;
        if (compression_level < 0 || compression_level > 2)
            throw std::invalid_argument(
                "ksplat: compression_level must be 0, 1, or 2");
        if (!std::isfinite(block_size) || !(block_size > 0.0f))
            throw std::invalid_argument(
                "ksplat: block_size must be finite and positive");
        if (bucket_size == 0 ||
            bucket_size > std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "ksplat: bucket_size must be in [1, 2^32-1]");
        if (cloud.n > std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "ksplat: point count exceeds the v0.1 uint32 limit");
        if (cloud.sh_degree < 0 || cloud.sh_degree > 2)
            throw std::invalid_argument(
                "ksplat: v0.1 cannot represent SH degree above 2");

        const size_t coefficients =
            coefficients_per_channel(cloud.sh_degree);
        const size_t rest = coefficients * 3;
        if (cloud.num_rest != rest)
            throw std::invalid_argument(
                "ksplat: GaussianCloud SH layout is inconsistent");
        for (float value : cloud.scales)
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "ksplat: log scales must be finite");
        for (float value : cloud.sh_dc)
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "ksplat: DC coefficients must be finite");
        for (float value : cloud.opacity)
            if (std::isnan(value))
                throw std::invalid_argument(
                    "ksplat: opacities must not be NaN");
        for (float value : cloud.sh_rest)
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "ksplat: SH coefficients must be finite");

        size_t full_bucket_count = 0;
        std::vector<Bucket> buckets =
            make_buckets(cloud, static_cast<double>(block_size), bucket_size,
                         full_bucket_count);
        if (buckets.size() > std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "ksplat: bucket count exceeds the v0.1 uint32 limit");
        const size_t partial_bucket_count =
            buckets.size() - full_bucket_count;
        const size_t record_size =
            bytes_per_splat(compression_level, cloud.sh_degree);
        const size_t partial_bytes =
            compression_level == 0
                ? 0
                : checked_mul(partial_bucket_count, 4,
                              "partial-bucket metadata");
        const size_t center_bytes =
            compression_level == 0
                ? 0
                : checked_mul(buckets.size(), kBucketStorageSize,
                              "bucket centers");
        const size_t bucket_bytes =
            checked_add(partial_bytes, center_bytes, "bucket metadata");
        const size_t record_bytes =
            checked_mul(cloud.n, record_size, "record storage");
        const size_t section_size =
            checked_add(bucket_bytes, record_bytes, "section storage");
        if (section_size > std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "ksplat: section exceeds the v0.1 uint32 storage limit");
        const size_t total_size =
            checked_add(kHeaderSize + kSectionHeaderSize, section_size,
                        "file storage");
        encoded.assign(total_size, '\0');
        auto *out = reinterpret_cast<uint8_t *>(encoded.data());

        out[0] = kVersionMajor;
        out[1] = kVersionMinor;
        store_u32(out + 4, 1);
        store_u32(out + 8, 1);
        store_u32(out + 12, static_cast<uint32_t>(cloud.n));
        store_u32(out + 16, static_cast<uint32_t>(cloud.n));
        store_u16(out + 20, static_cast<uint16_t>(compression_level));

        float sh_min = kDefaultShMin;
        float sh_max = kDefaultShMax;
        if (rest != 0 && !cloud.sh_rest.empty()) {
            sh_min = cloud.sh_rest.front();
            sh_max = cloud.sh_rest.front();
            for (float value : cloud.sh_rest) {
                sh_min = std::min(sh_min, value);
                sh_max = std::max(sh_max, value);
            }
            if (sh_min == 0.0f) sh_min = kDefaultShMin;
            if (sh_max == 0.0f) sh_max = kDefaultShMax;
            if (sh_min > sh_max)
                throw std::invalid_argument(
                    "ksplat: invalid SH quantization range");
        }
        store_f32(out + 36, sh_min);
        store_f32(out + 40, sh_max);

        uint8_t *section_header = out + kHeaderSize;
        store_u32(section_header, static_cast<uint32_t>(cloud.n));
        store_u32(section_header + 4, static_cast<uint32_t>(cloud.n));
        if (compression_level != 0) {
            store_u32(section_header + 8,
                      static_cast<uint32_t>(bucket_size));
            store_u32(section_header + 12,
                      static_cast<uint32_t>(buckets.size()));
            store_f32(section_header + 16, block_size);
            store_u16(section_header + 20, kBucketStorageSize);
            store_u32(section_header + 24, kCompressionScaleRange);
            store_u32(section_header + 32,
                      static_cast<uint32_t>(full_bucket_count));
            store_u32(section_header + 36,
                      static_cast<uint32_t>(partial_bucket_count));
        }
        store_u32(section_header + 28,
                  static_cast<uint32_t>(section_size));
        store_u16(section_header + 40,
                  static_cast<uint16_t>(cloud.sh_degree));

        uint8_t *section = out + kHeaderSize + kSectionHeaderSize;
        if (compression_level != 0) {
            for (size_t i = 0; i < partial_bucket_count; ++i) {
                const size_t length =
                    buckets[full_bucket_count + i].rows.size();
                store_u32(section + i * 4,
                          static_cast<uint32_t>(length));
            }
            uint8_t *centers = section + partial_bytes;
            for (size_t bucket = 0; bucket < buckets.size(); ++bucket) {
                for (size_t axis = 0; axis < 3; ++axis) {
                    const float center =
                        static_cast<float>(buckets[bucket].center[axis]);
                    if (!std::isfinite(center))
                        throw std::invalid_argument(
                            "ksplat: bucket center exceeds float32");
                    store_f32(centers + bucket * kBucketStorageSize +
                                  axis * 4,
                              center);
                }
            }
        }
        uint8_t *records = section + bucket_bytes;
        const size_t scale_offset = compression_level == 0 ? 12 : 6;
        const size_t rotation_offset = compression_level == 0 ? 24 : 12;
        const size_t color_offset = compression_level == 0 ? 40 : 20;
        const size_t sh_offset = compression_level == 0 ? 44 : 24;
        size_t output_row = 0;
        for (const Bucket &bucket : buckets) {
            for (size_t source_row : bucket.rows) {
                uint8_t *record = records + output_row * record_size;
                if (compression_level == 0) {
                    for (size_t axis = 0; axis < 3; ++axis)
                        store_f32(record + axis * 4,
                                  cloud.means[source_row * 3 + axis]);
                } else {
                    const double factor =
                        static_cast<double>(kCompressionScaleRange) /
                        (static_cast<double>(block_size) * 0.5);
                    for (size_t axis = 0; axis < 3; ++axis) {
                        const double delta =
                            static_cast<double>(
                                cloud.means[source_row * 3 + axis]) -
                            bucket.center[axis];
                        const double quantized =
                            std::floor(delta * factor + 0.5) +
                            static_cast<double>(kCompressionScaleRange);
                        if (!std::isfinite(quantized) || quantized < 0.0 ||
                            quantized > 65535.0)
                            throw std::invalid_argument(
                                "ksplat: point lies outside its position bucket");
                        store_u16(record + axis * 2,
                                  static_cast<uint16_t>(quantized));
                    }
                }

                for (size_t axis = 0; axis < 3; ++axis) {
                    const double linear =
                        std::exp(static_cast<double>(
                            cloud.scales[source_row * 3 + axis]));
                    const float linear32 = static_cast<float>(linear);
                    if (!std::isfinite(linear32) || !(linear32 > 0.0f))
                        throw std::invalid_argument(
                            "ksplat: log scale is outside float32 linear range");
                    if (compression_level == 0) {
                        store_f32(record + scale_offset + axis * 4, linear32);
                    } else {
                        if (linear32 > 65504.0f)
                            throw std::invalid_argument(
                                "ksplat: scale exceeds float16 range");
                        const uint16_t half = to_three_half(linear32);
                        if ((half & 0x7fffu) == 0)
                            throw std::invalid_argument(
                                "ksplat: scale underflows float16");
                        store_u16(record + scale_offset + axis * 2, half);
                    }
                }

                double quaternion[4];
                double norm_squared = 0.0;
                for (size_t component = 0; component < 4; ++component) {
                    const double value =
                        cloud.quats[source_row * 4 + component];
                    if (!std::isfinite(value))
                        throw std::invalid_argument(
                            "ksplat: quaternions must be finite");
                    quaternion[component] = value;
                    norm_squared += value * value;
                }
                const double norm = std::sqrt(norm_squared);
                if (!std::isfinite(norm) || !(norm > 0.0))
                    throw std::invalid_argument(
                        "ksplat: quaternion has zero or invalid norm");
                for (size_t component = 0; component < 4; ++component) {
                    const float value =
                        static_cast<float>(quaternion[component] / norm);
                    if (compression_level == 0) {
                        store_f32(record + rotation_offset + component * 4,
                                  value);
                    } else {
                        store_u16(record + rotation_offset + component * 2,
                                  to_three_half(value));
                    }
                }

                for (size_t channel = 0; channel < 3; ++channel) {
                    const double value =
                        (0.5 +
                         kShC0 *
                             static_cast<double>(
                                 cloud.sh_dc[source_row * 3 + channel])) *
                        255.0;
                    record[color_offset + channel] =
                        quantize_byte_floor(value);
                }
                record[color_offset + 3] = quantize_byte_floor(
                    sigmoid(cloud.opacity[source_row]) * 255.0);

                for (size_t channel = 0; channel < 3; ++channel) {
                    for (size_t coefficient = 0;
                         coefficient < coefficients; ++coefficient) {
                        const float value =
                            cloud.sh_rest[source_row * rest +
                                          channel * coefficients +
                                          coefficient];
                        const size_t encoded_index =
                            sh_record_index(channel, coefficient);
                        if (compression_level == 0) {
                            store_f32(record + sh_offset +
                                          encoded_index * 4,
                                      value);
                        } else if (compression_level == 1) {
                            if (std::abs(value) > 65504.0f)
                                throw std::invalid_argument(
                                    "ksplat: SH coefficient exceeds float16 range");
                            store_u16(record + sh_offset +
                                          encoded_index * 2,
                                      to_three_half(value));
                        } else {
                            const double range =
                                static_cast<double>(sh_max) -
                                static_cast<double>(sh_min);
                            const double quantized =
                                range == 0.0
                                    ? 0.0
                                    : (static_cast<double>(value) -
                                       static_cast<double>(sh_min)) /
                                          range *
                                          255.0;
                            record[sh_offset + encoded_index] =
                                quantize_byte_floor(quantized);
                        }
                    }
                }
                ++output_row;
            }
        }
        if (output_row != cloud.n)
            throw std::invalid_argument(
                "ksplat: bucket partition lost points");
    }
    return emit_bytes(encoded.data(), encoded.size());
}

nb::tuple inspect_ksplat_metadata(nb::handle source, size_t file_size) {
    ByteView view(source);
    Layout layout;
    {
        nb::gil_scoped_release release;
        layout = parse_layout(view.data(), view.size(), file_size, false);
    }
    return nb::make_tuple(
        layout.count, layout.degree, layout.compression,
        layout.declared_sections, layout.loaded_sections, layout.loaded_count,
        layout.scene_x, layout.scene_y, layout.scene_z, layout.sh_min,
        layout.sh_max);
}

}  // namespace

void register_ksplat(nb::module_ &m) {
    m.def("read_ksplat", &read_ksplat, "data"_a,
          "Decode mkkellogg KSplat v0.1 compression levels 0-2 and SH "
          "degrees 0-2 into a GaussianCloud.");
    m.def("read_ksplat_points", &read_ksplat_points, "data"_a, "start"_a,
          "stop"_a,
          "Decode a non-empty half-open KSplat point range while validating "
          "the complete container and allocating only selected record rows.");
    m.def("write_ksplat", &write_ksplat, "cloud"_a,
          "compression_level"_a = 1, "block_size"_a = 5.0f,
          "bucket_size"_a = 256,
          "Encode one deterministic KSplat v0.1 section. Degree-3 SH and "
          "values outside the chosen compression representation are refused.");
    m.def("_inspect_ksplat_metadata", &inspect_ksplat_metadata, "header"_a,
          "file_size"_a,
          "Validate KSplat headers against the file extent and return compact "
          "metadata without decoding point records.");
}
