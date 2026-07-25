// codecs/las.cpp — ASPRS LAS point cloud <-> PointCloud. LAS is a documented
// little-endian binary (a public header block + fixed-size point records), so
// this is a hand parser like colmap.cpp / bundler.cpp — no third-party library.
//
// Reader: LAS 1.1-1.4, point formats 0-10. Generic format-8 NIR is not exposed;
// format-10 NIR and all non-generic fields are retained in the raw sidecar.
// Waveform formats 4/5/9/10 retain an opaque lossless sidecar containing raw
// point records, descriptor VLRs, and the internal waveform packet EVLR.
// External .wdp packets and unrelated VLR/EVLR metadata reject explicitly.
// Positions come from i32 X,Y,Z * scale and are stored RELATIVE to the header
// offset, which is
// recorded as PointCloud.origin (double) so a large georef offset (UTM easting
// ~1e6) never crushes the f32 xyz precision. Intensity (u16) -> intensity with
// intensity_range="u16"; RGB (u16, formats 2/3/7/8) -> rgb16. Compressed LAZ
// (format high bit) and non-LASF files are refused rather than mis-decoded.
// GPS time/classification/returns remain outside the generic PointCloud fields;
// waveform records preserve them bit-for-bit in the opaque sidecar.
//
// Writer: generic clouds use LAS 1.2 point format 0 (no color) or 2 (16-bit
// color). Waveform-sidecar clouds retain formats 4/5/9/10 and all opaque fields.
// X = round(xyz / scale) as i32 with a range guard; the header offset is
// PointCloud.origin. LAS has no normals (refused) and stores 16-bit color
// (u8-only `rgb` is refused with a pointer to `colors16`). Decode/encode run
// with the GIL released.
#include <algorithm>
#include <array>
#include <cmath>

#include "records/point_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {
constexpr uint64_t kLasMaxPoints = 4000000000ull;  // ~4e9; bounds a crafted count
constexpr double kI32Max = 2147483647.0;

template <typename T>
void put_native(char *&dst, T value) {
    static_assert(std::is_trivially_copyable_v<T>);
    std::memcpy(dst, &value, sizeof(T));
    dst += sizeof(T);
}

size_t las_header_size(uint8_t version_minor) {
    if (version_minor >= 4) return 375;
    if (version_minor >= 3) return 235;
    return 227;
}

std::shared_ptr<LasWaveformSidecar> read_waveform_sidecar(
    const uint8_t *buf, size_t size,
    uint8_t point_format, uint8_t version_minor,
    uint16_t global_encoding, uint16_t header_size,
    uint32_t offset_to_points, uint32_t vlr_count,
    uint16_t record_length, uint64_t count,
    uint64_t points_end, uint64_t start_waveform,
    uint64_t first_evlr, uint32_t evlr_count,
    size_t start, size_t stop) {
    const size_t required_header =
        las_header_size(version_minor);
    if (header_size != required_header)
        throw std::invalid_argument(
            "las: waveform files with extended public headers "
            "are not representable");
    if (offset_to_points < header_size)
        throw std::invalid_argument(
            "las: waveform point data overlaps the public header");

    size_t cursor = header_size;
    for (uint32_t index = 0; index < vlr_count; ++index) {
        if (cursor > offset_to_points ||
            offset_to_points - cursor < 54)
            throw std::invalid_argument(
                "las: truncated waveform descriptor VLR header");
        LeReader vlr(buf + cursor, offset_to_points - cursor);
        vlr.pos = 18;
        const uint16_t record_id = vlr.get<uint16_t>();
        const uint16_t length = vlr.get<uint16_t>();
        if (record_id < 100 || record_id > 354 ||
            length != 26 ||
            cursor > offset_to_points - 54 - length)
            throw std::invalid_argument(
                "las: waveform files may contain only 26-byte "
                "LASF_Spec descriptor VLRs");
        cursor += 54 + length;
    }
    if (cursor != offset_to_points)
        throw std::invalid_argument(
            "las: waveform VLR padding or unindexed metadata "
            "is not representable");
    if (vlr_count == 0)
        throw std::invalid_argument(
            "las: waveform point formats require descriptor VLRs");

    if ((global_encoding & 0x0002U) == 0 ||
        (global_encoding & 0x0004U) != 0)
        throw std::invalid_argument(
            "las: only internally stored waveform packets are supported");
    if (start_waveform != points_end ||
        start_waveform > size)
        throw std::invalid_argument(
            "las: internal waveform packet record must immediately "
            "follow point data");
    if (version_minor >= 4 &&
        (first_evlr != start_waveform || evlr_count != 1))
        throw std::invalid_argument(
            "las: waveform files may contain only the waveform EVLR");

    auto sidecar = std::make_shared<LasWaveformSidecar>();
    sidecar->n = stop - start;
    sidecar->point_format = point_format;
    sidecar->version_minor = version_minor;
    sidecar->global_encoding = global_encoding;
    sidecar->point_record_length = record_length;
    const size_t selected_bytes =
        sidecar->n * static_cast<size_t>(record_length);
    sidecar->point_records.resize(selected_bytes);
    if (selected_bytes != 0)
        std::memcpy(
            sidecar->point_records.data(),
            buf + offset_to_points +
                start * static_cast<size_t>(record_length),
            selected_bytes);
    sidecar->descriptor_vlrs.assign(
        buf + header_size, buf + offset_to_points);
    sidecar->waveform_packet_record.assign(
        buf + static_cast<size_t>(start_waveform),
        buf + size);
    validate_las_waveform_sidecar(
        *sidecar, "las waveform decode");
    return sidecar;
}

PointCloud read_las_impl(nb::handle source, size_t lanes, bool partial,
                         size_t start, size_t stop) {
    sio::ByteView data(source);
    const uint8_t *buf = data.data();
    const size_t size = data.size();
    PointCloud pc;
    {
        nb::gil_scoped_release rel;  // pure-C++ decode; no Python objects touched
        if (size < 227) throw std::invalid_argument("las: file smaller than the LAS public header");
        if (buf[0] != 'L' || buf[1] != 'A' || buf[2] != 'S' || buf[3] != 'F')
            throw std::invalid_argument("las: bad signature (expected 'LASF')");

        LeReader r(buf, size);
        r.pos = 6;
        const uint16_t global_encoding = r.get<uint16_t>();
        r.pos = 24;
        const uint8_t ver_major = r.get<uint8_t>();
        const uint8_t ver_minor = r.get<uint8_t>();
        if (ver_major != 1 || ver_minor < 1 || ver_minor > 4)
            throw std::invalid_argument(
                "las: supported versions are 1.1 through 1.4");
        const size_t required_header = las_header_size(ver_minor);
        if (size < required_header)
            throw std::invalid_argument(
                "las: truncated public header");
        r.pos = 94;
        const uint16_t header_size = r.get<uint16_t>();
        r.pos = 96;
        const uint32_t offset_to_points = r.get<uint32_t>();
        const uint32_t vlr_count = r.get<uint32_t>();
        r.pos = 104;
        const uint8_t point_format = r.get<uint8_t>();
        const uint16_t record_length = r.get<uint16_t>();
        const uint32_t legacy_count = r.get<uint32_t>();
        r.pos = 131;
        const double sx = r.get<double>(), sy = r.get<double>(), sz = r.get<double>();
        const double ox = r.get<double>(), oy = r.get<double>(), oz = r.get<double>();
        if (!(sx > 0.0) || !(sy > 0.0) || !(sz > 0.0) ||
            !std::isfinite(sx) || !std::isfinite(sy) ||
            !std::isfinite(sz))
            throw std::invalid_argument(
                "las: coordinate scales must be finite and positive");
        if (!std::isfinite(ox) || !std::isfinite(oy) ||
            !std::isfinite(oz))
            throw std::invalid_argument(
                "las: coordinate offsets must be finite");

        uint64_t start_waveform = 0;
        uint64_t first_evlr = 0;
        uint32_t evlr_count = 0;
        if (ver_minor >= 3) {
            r.pos = 227;
            start_waveform = r.get<uint64_t>();
        }
        if (ver_minor >= 4) {
            first_evlr = r.get<uint64_t>();
            evlr_count = r.get<uint32_t>();
        }
        uint64_t count = legacy_count;  // LAS 1.4 carries a u64 count at offset 247
        if (ver_major == 1 && ver_minor >= 4) {
            r.pos = 247;
            count = r.get<uint64_t>();
        }

        if (point_format & 0xc0)
            throw std::invalid_argument("las: compressed LAZ is not supported (deferred)");
        const int fmt = point_format;
        int rgb_off;
        int wave_off;
        switch (fmt) {
            case 0: case 1: case 6:
                rgb_off = -1; wave_off = -1; break;
            case 2:
                rgb_off = 20; wave_off = -1; break;
            case 3:
                rgb_off = 28; wave_off = -1; break;
            case 4:
                rgb_off = -1; wave_off = 28; break;
            case 5:
                rgb_off = 28; wave_off = 34; break;
            case 7: case 8:
                rgb_off = 30; wave_off = -1; break;
            case 9:
                rgb_off = -1; wave_off = 30; break;
            case 10:
                rgb_off = 30; wave_off = 38; break;
            default:
                throw std::invalid_argument("las: point format " + std::to_string(fmt) +
                                            " is not supported");
        }
        if ((fmt == 4 || fmt == 5) && ver_minor < 3)
            throw std::invalid_argument(
                "las: point formats 4/5 require LAS 1.3 or newer");
        if (fmt >= 6 && ver_minor < 4)
            throw std::invalid_argument(
                "las: point formats 6-10 require LAS 1.4");
        // X,Y,Z,Intensity occupy the first 14 bytes of every format; color needs rgb_off+6
        const size_t min_len =
            wave_off >= 0
                ? static_cast<size_t>(wave_off) + 29
                : (rgb_off >= 0
                       ? static_cast<size_t>(rgb_off) + 6
                       : 14);
        if (record_length < min_len)
            throw std::invalid_argument("las: point record length too short for its format");
        if (count > kLasMaxPoints)
            throw std::invalid_argument("las: point count exceeds the supported limit");
        if (count != 0 &&
            record_length >
                (std::numeric_limits<uint64_t>::max() -
                 offset_to_points) /
                    count)
            throw std::invalid_argument(
                "las: point-data extent overflows uint64");
        const uint64_t need =
            static_cast<uint64_t>(offset_to_points) +
            count * static_cast<uint64_t>(record_length);
        if (offset_to_points < required_header || need > size)
            throw std::invalid_argument("las: truncated or malformed point data");

        const size_t total = static_cast<size_t>(count);
        if (!partial) {
            start = 0;
            stop = total;
        } else {
            checked_half_open_range(start, stop, total, "las point range");
        }
        const size_t n = stop - start;
        pc.n = n;
        pc.xyz.resize(n * 3);
        pc.intensity.resize(n);
        pc.intensity_range = "u16";

        // Rebase the georef anchor onto the FIRST point's integer grid, so the
        // stored LOCAL coords are extent-sized (f32-precise) no matter how the
        // producer split magnitude between the point ints and the header offset.
        // A file with offset=(0,0,0) carries the full UTM coordinate in X, which
        // would otherwise land in f32 and lose ~0.1 m; the offset stays in double.
        int32_t ax = 0, ay = 0, az = 0;
        if (total > 0) {
            LeReader a0(buf + offset_to_points, record_length);
            ax = a0.get<int32_t>(); ay = a0.get<int32_t>(); az = a0.get<int32_t>();
        }
        pc.origin[0] = ox + static_cast<double>(ax) * sx;
        pc.origin[1] = oy + static_cast<double>(ay) * sy;
        pc.origin[2] = oz + static_cast<double>(az) * sz;

        const bool color = rgb_off >= 0;
        if (color) pc.rgb16.resize(n * 3);
        parallel_for_blocks(n, lanes, 65536,
                            [&](size_t begin, size_t end, size_t) {
            for (size_t i = begin; i < end; ++i) {
                const uint8_t *rec =
                    buf + offset_to_points + (start + i) * record_length;
                LeReader pr(rec, record_length);
                const int32_t X = pr.get<int32_t>();
                const int32_t Y = pr.get<int32_t>();
                const int32_t Z = pr.get<int32_t>();
                pc.intensity[i] = static_cast<float>(pr.get<uint16_t>());
                // (X - anchor) in int64 (can't overflow) -> local coord
                // relative to origin.
                pc.xyz[i * 3] =
                    static_cast<float>((static_cast<int64_t>(X) - ax) * sx);
                pc.xyz[i * 3 + 1] =
                    static_cast<float>((static_cast<int64_t>(Y) - ay) * sy);
                pc.xyz[i * 3 + 2] =
                    static_cast<float>((static_cast<int64_t>(Z) - az) * sz);
                if (color) {
                    pr.pos = static_cast<size_t>(rgb_off);
                    pc.rgb16[i * 3] = pr.get<uint16_t>();
                    pc.rgb16[i * 3 + 1] = pr.get<uint16_t>();
                    pc.rgb16[i * 3 + 2] = pr.get<uint16_t>();
                }
            }
        });
        if (wave_off >= 0)
            pc.las_waveform = read_waveform_sidecar(
                buf, size, static_cast<uint8_t>(fmt),
                ver_minor, global_encoding, header_size,
                offset_to_points, vlr_count, record_length,
                count, need, start_waveform, first_evlr,
                evlr_count, start, stop);
    }
    return pc;
}

PointCloud read_las(nb::handle source, size_t lanes) {
    return read_las_impl(source, lanes, false, 0, 0);
}

PointCloud read_las_points(nb::handle source, size_t start, size_t stop,
                           size_t lanes) {
    return read_las_impl(source, lanes, true, start, stop);
}

struct Bounds {
    bool set = false;
    double minx = 0;
    double miny = 0;
    double minz = 0;
    double maxx = 0;
    double maxy = 0;
    double maxz = 0;
};

Bounds quantized_bounds(
    const PointCloud &pc, double scale, size_t lanes) {
    std::vector<Bounds> lane_bounds(kMaxParallelLanes);
    const size_t active_lanes = parallel_for_blocks(
        pc.n, lanes, 65536,
        [&](size_t begin, size_t end, size_t lane) {
            Bounds local;
            for (size_t i = begin; i < end; ++i) {
                const double lx = pc.xyz[i * 3];
                const double ly = pc.xyz[i * 3 + 1];
                const double lz = pc.xyz[i * 3 + 2];
                if (!(std::fabs(lx / scale) <= kI32Max) ||
                    !(std::fabs(ly / scale) <= kI32Max) ||
                    !(std::fabs(lz / scale) <= kI32Max))
                    throw std::invalid_argument(
                        "las: a coordinate is non-finite or does not fit "
                        "LAS's 32-bit grid at this scale");
                const double tx =
                    std::lround(lx / scale) * scale + pc.origin[0];
                const double ty =
                    std::lround(ly / scale) * scale + pc.origin[1];
                const double tz =
                    std::lround(lz / scale) * scale + pc.origin[2];
                if (!local.set) {
                    local.set = true;
                    local.minx = local.maxx = tx;
                    local.miny = local.maxy = ty;
                    local.minz = local.maxz = tz;
                } else {
                    local.minx = std::min(local.minx, tx);
                    local.maxx = std::max(local.maxx, tx);
                    local.miny = std::min(local.miny, ty);
                    local.maxy = std::max(local.maxy, ty);
                    local.minz = std::min(local.minz, tz);
                    local.maxz = std::max(local.maxz, tz);
                }
            }
            lane_bounds[lane] = local;
        });
    Bounds bounds;
    for (size_t lane = 0; lane < active_lanes; ++lane) {
        const Bounds &local = lane_bounds[lane];
        if (!local.set) continue;
        if (!bounds.set) {
            bounds = local;
        } else {
            bounds.minx = std::min(bounds.minx, local.minx);
            bounds.maxx = std::max(bounds.maxx, local.maxx);
            bounds.miny = std::min(bounds.miny, local.miny);
            bounds.maxy = std::max(bounds.maxy, local.maxy);
            bounds.minz = std::min(bounds.minz, local.minz);
            bounds.maxz = std::max(bounds.maxz, local.maxz);
        }
    }
    return bounds;
}

std::string encode_waveform_las(
    const PointCloud &pc, double scale, size_t lanes) {
    const LasWaveformSidecar &sidecar = *pc.las_waveform;
    validate_las_waveform_sidecar(
        sidecar, "las waveform writer");
    if (sidecar.n != pc.n)
        throw std::invalid_argument(
            "las: waveform sidecar point count disagrees with cloud");
    const bool color =
        sidecar.point_format == 5 ||
        sidecar.point_format == 10;
    if (pc.n != 0 && color != pc.has_rgb16())
        throw std::invalid_argument(
            color
                ? "las: waveform point format requires colors16"
                : "las: waveform point format cannot store colors16");
    if (sidecar.point_format < 6 &&
        pc.n > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "las: legacy waveform point formats use a 32-bit count");

    const size_t header_size =
        las_header_size(sidecar.version_minor);
    if (sidecar.descriptor_vlrs.size() >
        std::numeric_limits<uint32_t>::max() - header_size)
        throw std::length_error(
            "las: waveform VLR region exceeds the format limit");
    const uint32_t offset_to_points =
        static_cast<uint32_t>(
            header_size + sidecar.descriptor_vlrs.size());
    if (pc.n != 0 &&
        sidecar.point_record_length >
            (std::numeric_limits<size_t>::max() -
             offset_to_points) /
                pc.n)
        throw std::length_error(
            "las: waveform point data is too large");
    const size_t points_end =
        static_cast<size_t>(offset_to_points) +
        pc.n * sidecar.point_record_length;
    if (sidecar.waveform_packet_record.size() >
        std::numeric_limits<size_t>::max() - points_end)
        throw std::length_error(
            "las: waveform packet record is too large");

    const Bounds bounds =
        quantized_bounds(pc, scale, lanes);
    std::array<uint64_t, 15> returns{};
    for (size_t row = 0; row < pc.n; ++row) {
        const uint8_t flags =
            sidecar.point_records[
                row * sidecar.point_record_length + 14];
        const uint8_t number =
            sidecar.point_format < 6
                ? static_cast<uint8_t>(flags & 0x07U)
                : static_cast<uint8_t>(flags & 0x0fU);
        if (number != 0 && number <= returns.size())
            ++returns[number - 1];
    }

    LeWriter writer;
    writer.out.reserve(
        points_end + sidecar.waveform_packet_record.size());
    writer.out.append("LASF", 4);
    writer.put<uint16_t>(0);
    writer.put<uint16_t>(sidecar.global_encoding);
    for (size_t index = 0; index < 16; ++index)
        writer.put<uint8_t>(0);
    writer.put<uint8_t>(1);
    writer.put<uint8_t>(sidecar.version_minor);
    for (size_t index = 0; index < 32; ++index)
        writer.put<uint8_t>(0);
    std::string software = "sceneio";
    software.resize(32, '\0');
    writer.out.append(software.data(), software.size());
    writer.put<uint16_t>(0);
    writer.put<uint16_t>(0);
    writer.put<uint16_t>(static_cast<uint16_t>(header_size));
    writer.put<uint32_t>(offset_to_points);
    writer.put<uint32_t>(
        static_cast<uint32_t>(
            sidecar.descriptor_vlrs.size() / 80));
    writer.put<uint8_t>(sidecar.point_format);
    writer.put<uint16_t>(sidecar.point_record_length);
    writer.put<uint32_t>(
        sidecar.point_format < 6
            ? static_cast<uint32_t>(pc.n)
            : 0);
    for (size_t index = 0; index < 5; ++index)
        writer.put<uint32_t>(
            sidecar.point_format < 6
                ? static_cast<uint32_t>(returns[index])
                : 0);
    writer.put<double>(scale);
    writer.put<double>(scale);
    writer.put<double>(scale);
    writer.put<double>(pc.origin[0]);
    writer.put<double>(pc.origin[1]);
    writer.put<double>(pc.origin[2]);
    writer.put<double>(bounds.maxx);
    writer.put<double>(bounds.minx);
    writer.put<double>(bounds.maxy);
    writer.put<double>(bounds.miny);
    writer.put<double>(bounds.maxz);
    writer.put<double>(bounds.minz);
    writer.put<uint64_t>(points_end);
    if (sidecar.version_minor >= 4) {
        writer.put<uint64_t>(points_end);
        writer.put<uint32_t>(1);
        writer.put<uint64_t>(pc.n);
        for (uint64_t count : returns)
            writer.put<uint64_t>(count);
    }
    if (writer.out.size() != header_size)
        throw std::logic_error(
            "las: internal waveform header size mismatch");

    writer.out.append(
        reinterpret_cast<const char *>(
            sidecar.descriptor_vlrs.data()),
        sidecar.descriptor_vlrs.size());
    const size_t raw_begin = writer.out.size();
    if (!sidecar.point_records.empty())
        writer.out.append(
            reinterpret_cast<const char *>(
                sidecar.point_records.data()),
            sidecar.point_records.size());
    const bool have_intensity = pc.has_intensity();
    const size_t color_offset =
        sidecar.point_format == 5 ? 28 : 30;
    parallel_for_blocks(
        pc.n, lanes, 65536,
        [&](size_t begin, size_t end, size_t) {
            for (size_t row = begin; row < end; ++row) {
                char *record =
                    writer.out.data() + raw_begin +
                    row * sidecar.point_record_length;
                char *position = record;
                put_native<int32_t>(
                    position,
                    static_cast<int32_t>(std::lround(
                        pc.xyz[row * 3] / scale)));
                put_native<int32_t>(
                    position,
                    static_cast<int32_t>(std::lround(
                        pc.xyz[row * 3 + 1] / scale)));
                put_native<int32_t>(
                    position,
                    static_cast<int32_t>(std::lround(
                        pc.xyz[row * 3 + 2] / scale)));
                if (have_intensity) {
                    double value = pc.intensity[row];
                    if (!std::isfinite(value)) value = 0.0;
                    char *intensity =
                        record + 12;
                    put_native<uint16_t>(
                        intensity,
                        static_cast<uint16_t>(std::lround(
                            std::min(
                                std::max(value, 0.0),
                                65535.0))));
                }
                if (color) {
                    char *rgb = record + color_offset;
                    put_native<uint16_t>(
                        rgb, pc.rgb16[row * 3]);
                    put_native<uint16_t>(
                        rgb, pc.rgb16[row * 3 + 1]);
                    put_native<uint16_t>(
                        rgb, pc.rgb16[row * 3 + 2]);
                }
            }
        });
    writer.out.append(
        reinterpret_cast<const char *>(
            sidecar.waveform_packet_record.data()),
        sidecar.waveform_packet_record.size());
    return std::move(writer.out);
}

nb::bytes write_las(const PointCloud &pc, double scale, size_t lanes) {
    // --- guards: refuse what LAS cannot represent (never convert) ---
    if (pc.has_normals())
        throw std::invalid_argument("las: LAS cannot store normals");
    if (pc.has_rgb() && !pc.has_rgb16())
        throw std::invalid_argument(
            "las: LAS stores 16-bit color; provide colors16 (a normalizer upconverts u8->u16 on request)");
    if (pc.has_intensity() && pc.intensity_range != "u16" && pc.intensity_range != "unknown")
        throw std::invalid_argument(
            "las: LAS intensity is 16-bit; a '" + pc.intensity_range +
            "'-ranged intensity must be rescaled to u16 first");
    if (!pc.has_default_organization() || !pc.has_default_viewpoint())
        throw std::invalid_argument(
            "las: organized shape and acquisition viewpoint metadata are not representable");
    if (!(scale > 0.0) || !std::isfinite(scale))
        throw std::invalid_argument(
            "las: scale must be finite and positive");
    if (!std::isfinite(pc.origin[0]) ||
        !std::isfinite(pc.origin[1]) ||
        !std::isfinite(pc.origin[2]))
        throw std::invalid_argument(
            "las: origin values must be finite");
    if (!pc.has_las_waveform() &&
        pc.n > 0xFFFFFFFFull)
        throw std::invalid_argument("las: too many points for LAS 1.2 (32-bit count)");

    std::string out;
    {
        nb::gil_scoped_release rel;  // nb::bytes built after the scope, under the GIL
        if (pc.has_las_waveform()) {
            out = encode_waveform_las(pc, scale, lanes);
        } else {
        const size_t n = pc.n;
        const bool color = pc.has_rgb16();
        const uint8_t fmt = color ? 2 : 0;
        const uint16_t rec_len = color ? 26 : 20;
        const bool have_i = pc.has_intensity();

        // Pre-pass: quantize-range guard plus bounds from the quantized true
        // coordinates, so no emitted point lies outside the public header.
        const Bounds bounds =
            quantized_bounds(pc, scale, lanes);
        const double minx = bounds.minx, miny = bounds.miny;
        const double minz = bounds.minz, maxx = bounds.maxx;
        const double maxy = bounds.maxy, maxz = bounds.maxz;

        LeWriter w;
        w.out.append("LASF", 4);
        w.put<uint16_t>(0);              // file source ID
        w.put<uint16_t>(0);              // global encoding
        for (int i = 0; i < 16; i++) w.put<uint8_t>(0);  // project GUID
        w.put<uint8_t>(1); w.put<uint8_t>(2);            // version 1.2
        for (int i = 0; i < 32; i++) w.put<uint8_t>(0);  // system identifier
        std::string sw = "sceneio";
        sw.resize(32, '\0');
        w.out.append(sw.data(), 32);     // generating software
        w.put<uint16_t>(0);              // file creation day
        w.put<uint16_t>(0);              // file creation year
        w.put<uint16_t>(227);            // header size (LAS 1.2)
        w.put<uint32_t>(227);            // offset to point data (no VLRs)
        w.put<uint32_t>(0);              // number of VLRs
        w.put<uint8_t>(fmt);             // point data record format
        w.put<uint16_t>(rec_len);        // point data record length
        w.put<uint32_t>(static_cast<uint32_t>(n));  // legacy number of point records
        w.put<uint32_t>(static_cast<uint32_t>(n));  // legacy points by return[0] (all "return 1 of 1")
        for (int i = 0; i < 4; i++) w.put<uint32_t>(0);
        w.put<double>(scale); w.put<double>(scale); w.put<double>(scale);  // x/y/z scale
        w.put<double>(pc.origin[0]); w.put<double>(pc.origin[1]); w.put<double>(pc.origin[2]);  // offset
        w.put<double>(maxx); w.put<double>(minx);  // max/min X
        w.put<double>(maxy); w.put<double>(miny);  // max/min Y
        w.put<double>(maxz); w.put<double>(minz);  // max/min Z

        if (w.out.size() != 227)
            throw std::logic_error("las: internal header size mismatch");
        if (n > (w.out.max_size() - 227) / rec_len)
            throw std::length_error("las: encoded point data is too large");
        w.out.resize(227 + n * rec_len);
        parallel_for_blocks(n, lanes, 65536,
                            [&](size_t begin, size_t end, size_t) {
            for (size_t i = begin; i < end; ++i) {
                char *dst = w.out.data() + 227 + i * rec_len;
                char *const record_begin = dst;
                put_native<int32_t>(
                    dst, static_cast<int32_t>(
                             std::lround(pc.xyz[i * 3] / scale)));
                put_native<int32_t>(
                    dst, static_cast<int32_t>(
                             std::lround(pc.xyz[i * 3 + 1] / scale)));
                put_native<int32_t>(
                    dst, static_cast<int32_t>(
                             std::lround(pc.xyz[i * 3 + 2] / scale)));
                double iv = have_i ? pc.intensity[i] : 0.0;
                if (!std::isfinite(iv)) iv = 0.0;
                put_native<uint16_t>(
                    dst, static_cast<uint16_t>(std::lround(
                             std::min(std::max(iv, 0.0), 65535.0))));
                put_native<uint8_t>(dst, 0x09);
                put_native<uint8_t>(dst, 0);
                put_native<int8_t>(dst, 0);
                put_native<uint8_t>(dst, 0);
                put_native<uint16_t>(dst, 0);
                if (color) {
                    put_native<uint16_t>(dst, pc.rgb16[i * 3]);
                    put_native<uint16_t>(dst, pc.rgb16[i * 3 + 1]);
                    put_native<uint16_t>(dst, pc.rgb16[i * 3 + 2]);
                }
                if (static_cast<size_t>(dst - record_begin) != rec_len)
                    throw std::logic_error(
                        "las: internal point-record size mismatch");
            }
        });
        out = std::move(w.out);
        }
    }
    return emit_bytes(out.data(), out.size());
}

}  // namespace

void register_las(nb::module_ &m) {
    m.def("read_las", &read_las, "data"_a, "_lanes"_a = 0,
          "Decode ASPRS LAS bytes into a PointCloud: XYZ (i32*scale, relative to the header offset "
          "kept as .origin), intensity (u16, intensity_range='u16'), and RGB (u16 -> colors16, "
          "formats 2/3/5/7/8/10). Point formats 0-10 are supported; formats 4/5/9/10 "
          "retain internal waveform packets and opaque point fields in .las_waveform. LAZ raises.");
    m.def("read_las_points", &read_las_points, "data"_a, "start"_a,
          "stop"_a, "_lanes"_a = 0,
          "Decode a non-empty half-open LAS point range while retaining the "
          "full file's georeference anchor.");
    m.def("write_las", &write_las, "cloud"_a, "scale"_a = 0.001,
          "_lanes"_a = 0,
          "Encode a PointCloud to LAS 1.2 bytes (point format 0, or 2 when colors16 is present). "
          "A cloud carrying .las_waveform retains its original waveform point format and packets. "
          "X = round(xyz/scale) as i32 with a range guard; the header offset is .origin. Large "
          "point transforms use bounded parallel lanes. Refuses normals and u8-only color "
          "(provide colors16).");
}
