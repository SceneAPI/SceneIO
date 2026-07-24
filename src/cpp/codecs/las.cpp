// codecs/las.cpp — ASPRS LAS point cloud <-> PointCloud. LAS is a documented
// little-endian binary (a public header block + fixed-size point records), so
// this is a hand parser like colmap.cpp / bundler.cpp — no third-party library.
//
// Reader: LAS 1.1-1.4, point formats 0-3 (legacy) and 6-8 (1.4). Positions come
// from i32 X,Y,Z * scale and are stored RELATIVE to the header offset, which is
// recorded as PointCloud.origin (double) so a large georef offset (UTM easting
// ~1e6) never crushes the f32 xyz precision. Intensity (u16) -> intensity with
// intensity_range="u16"; RGB (u16, formats 2/3/7/8) -> rgb16. Compressed LAZ
// (format high bit), waveform formats (4/5/9/10), and non-LASF files are refused
// rather than mis-decoded; gps_time/classification/returns are intentionally
// dropped (documented partial fidelity, the .splat SH-drop precedent).
//
// Writer: LAS 1.2, point format 0 (no color) or 2 (16-bit color). X = round(xyz /
// scale) as i32 with a range guard; the header offset is PointCloud.origin. LAS
// has no normals (refused) and stores 16-bit color (u8-only `rgb` is refused with
// a pointer to `colors16`). Decode/encode run with the GIL released.
#include <algorithm>
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

PointCloud read_las(nb::handle source, size_t lanes) {
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
        r.pos = 24;
        const uint8_t ver_major = r.get<uint8_t>();
        const uint8_t ver_minor = r.get<uint8_t>();
        r.pos = 96;
        const uint32_t offset_to_points = r.get<uint32_t>();
        r.pos = 104;
        const uint8_t point_format = r.get<uint8_t>();
        const uint16_t record_length = r.get<uint16_t>();
        const uint32_t legacy_count = r.get<uint32_t>();
        r.pos = 131;
        const double sx = r.get<double>(), sy = r.get<double>(), sz = r.get<double>();
        const double ox = r.get<double>(), oy = r.get<double>(), oz = r.get<double>();

        uint64_t count = legacy_count;  // LAS 1.4 carries a u64 count at offset 247
        if (ver_major == 1 && ver_minor >= 4) {
            r.pos = 247;
            count = r.get<uint64_t>();
        }

        if (point_format & 0x80)
            throw std::invalid_argument("las: compressed LAZ is not supported (deferred)");
        const int fmt = point_format & 0x7f;  // strip only the LAZ bit so an invalid id (e.g. 66) is rejected, not aliased
        int rgb_off;  // byte offset of RGB within a record, or -1 when the format has no color
        switch (fmt) {
            case 0: case 1: case 6: rgb_off = -1; break;
            case 2: rgb_off = 20; break;
            case 3: rgb_off = 28; break;
            case 7: case 8: rgb_off = 30; break;
            default:
                throw std::invalid_argument("las: point format " + std::to_string(fmt) +
                                            " (waveform/unsupported) is not supported");
        }
        // X,Y,Z,Intensity occupy the first 14 bytes of every format; color needs rgb_off+6
        const size_t min_len = rgb_off >= 0 ? static_cast<size_t>(rgb_off) + 6 : 14;
        if (record_length < min_len)
            throw std::invalid_argument("las: point record length too short for its format");
        if (count > kLasMaxPoints)
            throw std::invalid_argument("las: point count exceeds the supported limit");
        const uint64_t need =
            static_cast<uint64_t>(offset_to_points) + count * static_cast<uint64_t>(record_length);
        if (offset_to_points < 227 || need > size)
            throw std::invalid_argument("las: truncated or malformed point data");

        const size_t n = static_cast<size_t>(count);
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
        if (n > 0) {
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
                    buf + offset_to_points + i * record_length;
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
    }
    return pc;
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
    if (!(scale > 0.0))
        throw std::invalid_argument("las: scale must be positive");
    if (pc.n > 0xFFFFFFFFull)
        throw std::invalid_argument("las: too many points for LAS 1.2 (32-bit count)");

    std::string out;
    {
        nb::gil_scoped_release rel;  // nb::bytes built after the scope, under the GIL
        const size_t n = pc.n;
        const bool color = pc.has_rgb16();
        const uint8_t fmt = color ? 2 : 0;
        const uint16_t rec_len = color ? 26 : 20;
        const bool have_i = pc.has_intensity();

        // pre-pass: quantize-range guard (the negated form also rejects NaN) + the
        // header bounding box computed from the QUANTIZED true coords, so no written
        // point can fall outside the declared min/max.
        struct Bounds {
            bool set = false;
            double minx = 0, miny = 0, minz = 0;
            double maxx = 0, maxy = 0, maxz = 0;
        };
        std::vector<Bounds> lane_bounds(kMaxParallelLanes);
        const size_t active_lanes = parallel_for_blocks(
            n, lanes, 65536,
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
    return emit_bytes(out.data(), out.size());
}

}  // namespace

void register_las(nb::module_ &m) {
    m.def("read_las", &read_las, "data"_a, "_lanes"_a = 0,
          "Decode ASPRS LAS bytes into a PointCloud: XYZ (i32*scale, relative to the header offset "
          "kept as .origin), intensity (u16, intensity_range='u16'), and RGB (u16 -> colors16, "
          "formats 2/3/7/8). Point formats 0-3 and 6-8; LAZ / waveform formats raise.");
    m.def("write_las", &write_las, "cloud"_a, "scale"_a = 0.001,
          "_lanes"_a = 0,
          "Encode a PointCloud to LAS 1.2 bytes (point format 0, or 2 when colors16 is present). "
          "X = round(xyz/scale) as i32 with a range guard; the header offset is .origin. Large "
          "point transforms use bounded parallel lanes. Refuses normals and u8-only color "
          "(provide colors16).");
}
