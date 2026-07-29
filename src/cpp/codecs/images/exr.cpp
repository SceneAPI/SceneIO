// codecs/images/exr.cpp -- OpenEXR (.exr) <-> Image (float32, linear) via vendored tinyexr
// (BSD, src/cpp/third_party/tinyexr; reuses our miniz for ZIP). EXR is the linear
// HDR raster with named channels; we map the common single-part scanline sets to
// Image{F32, C in {1,3,4}, color_space="linear"}: {R,G,B,A}->RGBA (premultiplied
// alpha, EXR's associated-alpha convention), {R,G,B}->RGB, a single channel->C=1.
// HALF channels widen to FLOAT losslessly on read.
//
// REJECTED (clear error, never a silent lossy conversion): multipart, deep, and
// tiled EXR; UINT (integer) channels; and channel sets that aren't one of the
// three above (multi-layer AOVs). The reader bounds dimensions from the header's
// data window before LoadEXRImage allocates. The writer is FLOAT + ZIP, names
// channels in the (A)BGR order EXR viewers expect, and guards float32/linear/
// premultiplied. Decode/encode run GIL-released; tinyexr allocations are freed
// via RAII (with a subtlety on write: the header/image point at OUR stack vectors,
// so tinyexr must NOT free them).
#include <climits>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <string>
#include <utility>
#include <vector>

#include "records/depth_map.hpp"
#include "records/image.hpp"
#include "tinyexr.h"

using namespace nb::literals;
using namespace sio;

namespace {
constexpr uint64_t kExrPixelCap = 250000000ull;  // 250 MP; worst-case f32 RGBA buffer ~4 GB
constexpr int64_t kExrAxisCap = 1 << 20;          // 1M per axis

void require_exr_depth_encoding(const std::string &unit,
                                double scale_to_meters,
                                const std::string &invalid_policy) {
    if (!depth_map_valid_unit(unit))
        throw std::invalid_argument(
            "EXR depth: unit must be "
            "meters|millimeters|custom|unitless|unknown");
    if (!depth_map_unit_scale_consistent(unit, scale_to_meters))
        throw std::invalid_argument(
            "EXR depth: unit/scale_to_meters mismatch");
    if (!depth_map_valid_invalid_policy(invalid_policy))
        throw std::invalid_argument(
            "EXR depth: invalid_policy must be "
            "none|zero|nonfinite|negative");
}

void require_exr_channel_name(const std::string &channel_name) {
    if (channel_name.empty())
        throw std::invalid_argument(
            "EXR depth: channel_name must be non-empty");
    if (channel_name.find('\0') != std::string::npos)
        throw std::invalid_argument(
            "EXR depth: channel_name must contain no NUL");
    if (channel_name.size() > 255)
        throw std::invalid_argument(
            "EXR depth: channel_name must be at most 255 UTF-8 bytes");
}

Image read_exr_impl(nb::handle source, size_t lanes,
                    const std::string *required_scalar_channel) {
    sio::ByteView data(source);
    const unsigned char *in = data.data();
    const size_t size = data.size();
    Image im;
    {
        nb::gil_scoped_release rel;  // pure-C++ decode; no Python objects touched
        EXRVersion version;
        if (ParseEXRVersionFromMemory(&version, in, size) != TINYEXR_SUCCESS)
            throw std::invalid_argument("exr: not an OpenEXR stream");
        if (version.multipart) throw std::invalid_argument("exr: multipart EXR is not supported");
        if (version.non_image) throw std::invalid_argument("exr: deep EXR is not supported");
        if (version.tiled) throw std::invalid_argument("exr: tiled EXR is not supported");

        EXRHeader header;
        InitEXRHeader(&header);
        struct HGuard {
            EXRHeader *h;
            ~HGuard() { FreeEXRHeader(h); }
        } hg{&header};
        const char *err = nullptr;
        if (ParseEXRHeaderFromMemory(&header, &version, in, size, &err) != TINYEXR_SUCCESS) {
            std::string m = err ? err : "header parse error";
            FreeEXRErrorMessage(err);
            throw std::invalid_argument("exr: " + m);
        }
        if (header.tiled) throw std::invalid_argument("exr: tiled EXR is not supported");
        if (header.non_image)  // a deep file whose version bits were clear still parses
            throw std::invalid_argument("exr: deep EXR is not supported");

        // bound dimensions from the data window BEFORE LoadEXRImage allocates pixels
        const int64_t W = static_cast<int64_t>(header.data_window.max_x) - header.data_window.min_x + 1;
        const int64_t H = static_cast<int64_t>(header.data_window.max_y) - header.data_window.min_y + 1;
        if (W <= 0 || H <= 0) throw std::invalid_argument("exr: empty or invalid data window");
        if (W > kExrAxisCap || H > kExrAxisCap ||
            static_cast<uint64_t>(W) * static_cast<uint64_t>(H) > kExrPixelCap)
            throw std::invalid_argument("exr: image dimensions exceed the supported limit");

        if (header.num_channels <= 0 || !header.channels ||
            !header.pixel_types || !header.requested_pixel_types)
            throw std::invalid_argument("exr: malformed channel table");
        if (required_scalar_channel) {
            if (header.num_channels != 1)
                throw std::invalid_argument(
                    "EXR depth: expected exactly one scalar channel");
            const char *name = header.channels[0].name;
            const void *terminator = std::memchr(name, '\0', 256);
            if (!terminator)
                throw std::invalid_argument(
                    "EXR depth: channel name is not NUL-terminated");
            const size_t name_size =
                static_cast<const char *>(terminator) - name;
            if (name_size == 0)
                throw std::invalid_argument(
                    "EXR depth: channel name must be non-empty");
            if (std::string(name, name_size) != *required_scalar_channel)
                throw std::invalid_argument(
                    "EXR depth: stored channel does not match requested "
                    "channel");
        }

        for (int c = 0; c < header.num_channels; c++) {
            if (header.pixel_types[c] == TINYEXR_PIXELTYPE_UINT)
                throw std::invalid_argument("exr: integer (UINT) channels are not supported");
            header.requested_pixel_types[c] = TINYEXR_PIXELTYPE_FLOAT;  // widen HALF -> FLOAT (lossless)
        }

        EXRImage image;
        InitEXRImage(&image);
        struct IGuard {
            EXRImage *i;
            ~IGuard() { FreeEXRImage(i); }
        } ig{&image};
        err = nullptr;
        if (LoadEXRImageFromMemory(&image, &header, in, size, &err) != TINYEXR_SUCCESS) {
            std::string m = err ? err : "image load error";
            FreeEXRErrorMessage(err);
            throw std::invalid_argument("exr: " + m);
        }

        // resolve the channel set by name (EXR stores channels alphabetically)
        int iR = -1, iG = -1, iB = -1, iA = -1;
        for (int c = 0; c < header.num_channels; c++) {
            const char *nm = header.channels[c].name;
            if (!std::strcmp(nm, "R")) iR = c;
            else if (!std::strcmp(nm, "G")) iG = c;
            else if (!std::strcmp(nm, "B")) iB = c;
            else if (!std::strcmp(nm, "A")) iA = c;
        }
        // Require the EXACT channel set — extra channels (a Z/depth or an AOV layer
        // alongside R,G,B) must be rejected, not silently dropped. The num_channels
        // check is what makes {R,G,B,Z} raise instead of decoding as 3-channel.
        int C, planes[4];
        if (iR >= 0 && iG >= 0 && iB >= 0 && iA >= 0 && header.num_channels == 4) {
            C = 4; planes[0] = iR; planes[1] = iG; planes[2] = iB; planes[3] = iA;
            im.alpha_mode = "premultiplied";
        } else if (iR >= 0 && iG >= 0 && iB >= 0 && iA < 0 && header.num_channels == 3) {
            C = 3; planes[0] = iR; planes[1] = iG; planes[2] = iB;
            im.alpha_mode = "none";
        } else if (header.num_channels == 1) {
            C = 1; planes[0] = 0; im.alpha_mode = "none";
        } else {
            throw std::invalid_argument(
                "exr: unsupported channel set (need exactly a single channel, {R,G,B}, or {R,G,B,A}; "
                "extra/AOV/Z channels are not supported)");
        }

        const size_t w = static_cast<size_t>(image.width), h = static_cast<size_t>(image.height);
        const size_t n = w * h;
        im.height = h; im.width = w; im.channels = static_cast<size_t>(C);
        im.dtype = PixelType::F32; im.color_space = "linear"; im.maxval = 0;
        im.f32.resize(n * static_cast<size_t>(C));
        float **planar = reinterpret_cast<float **>(image.images);
        if (C == 1) {
            std::memcpy(im.f32.data(), planar[planes[0]], n * sizeof(float));
        } else {
            parallel_for_blocks(n, lanes, 131072,
                                [&](size_t begin, size_t end, size_t) {
                for (size_t p = begin; p < end; ++p)
                    for (int c = 0; c < C; ++c)
                        im.f32[p * C + static_cast<size_t>(c)] =
                            planar[planes[c]][p];
            });
        }
    }
    return im;
}

Image read_exr(nb::handle source, size_t lanes) {
    return read_exr_impl(source, lanes, nullptr);
}

DepthMap read_exr_depth(nb::handle source, const std::string &unit,
                        double scale_to_meters,
                        const std::string &invalid_policy,
                        const std::string &channel_name, size_t lanes) {
    require_exr_depth_encoding(unit, scale_to_meters, invalid_policy);
    require_exr_channel_name(channel_name);

    Image image = read_exr_impl(source, lanes, &channel_name);
    if (image.channels != 1 || image.dtype != PixelType::F32 ||
        image.color_space != "linear")
        throw std::invalid_argument(
            "EXR depth: decoded image is not scalar float32 linear data");

    DepthMap result;
    result.height = image.height;
    result.width = image.width;
    result.depth = std::move(image.f32);
    result.unit = unit;
    result.scale_to_meters = scale_to_meters;
    result.invalid_policy = invalid_policy;
    return result;
}

nb::bytes write_exr_impl(const Image &img, size_t lanes,
                         const std::string &single_channel_name) {
    // --- guards: refuse what this EXR mapping cannot represent (never convert) ---
    if (img.dtype != PixelType::F32)
        throw std::invalid_argument("exr: OpenEXR here stores float32 pixels (got " +
                                    std::string(image_dtype_name(img.dtype)) + ")");
    const size_t C = img.channels;
    if (C != 1 && C != 3 && C != 4)
        throw std::invalid_argument("exr: only 1/3/4-channel images are supported");
    if (img.color_space != "linear")
        throw std::invalid_argument("exr: requires color_space 'linear' (got '" + img.color_space + "')");
    if (C == 4 && img.alpha_mode != "premultiplied")
        throw std::invalid_argument(
            "exr: RGBA EXR requires alpha_mode 'premultiplied' (EXR uses associated alpha)");
    if (img.width == 0 || img.height == 0)
        throw std::invalid_argument("exr: cannot write a zero-dimension image");
    if (img.width > static_cast<size_t>(kExrAxisCap) ||
        img.height > static_cast<size_t>(kExrAxisCap) ||
        static_cast<uint64_t>(img.width) * img.height > kExrPixelCap)
        throw std::invalid_argument("exr: image dimensions exceed the supported limit");

    std::string out;
    {
        nb::gil_scoped_release rel;  // nb::bytes built after the scope, under the GIL
        const size_t W = img.width, H = img.height, n = W * H;
        // deinterleave RGBA... -> planar per-channel buffers (planar[0]=R, [1]=G, ...)
        std::vector<std::vector<float>> planar(C, std::vector<float>(n));
        if (C == 1) {
            std::memcpy(planar[0].data(), img.f32.data(), n * sizeof(float));
        } else {
            parallel_for_blocks(n, lanes, 131072,
                                [&](size_t begin, size_t end, size_t) {
                for (size_t p = begin; p < end; ++p)
                    for (size_t c = 0; c < C; ++c)
                        planar[c][p] = img.f32[p * C + c];
            });
        }

        // header/image reference OUR stack vectors; tinyexr only READS them and must
        // NOT free them, so we never call FreeEXRHeader/FreeEXRImage on this path.
        EXRHeader header;
        InitEXRHeader(&header);
        EXRImage image;
        InitEXRImage(&image);
        image.num_channels = static_cast<int>(C);
        image.width = static_cast<int>(W);
        image.height = static_cast<int>(H);

        std::vector<float *> ptrs(C);
        std::vector<EXRChannelInfo> chans(C);
        std::vector<int> ptypes(C, TINYEXR_PIXELTYPE_FLOAT), rtypes(C, TINYEXR_PIXELTYPE_FLOAT);
        auto set_channel = [&](size_t slot, size_t plane, const char *nm) {
            ptrs[slot] = planar[plane].data();
            std::memset(chans[slot].name, 0, 256);
            std::strncpy(chans[slot].name, nm, 255);
        };
        // (A)BGR order — what EXR viewers expect (mirrors tinyexr's SaveEXRToMemory)
        if (C == 1) {
            set_channel(0, 0, single_channel_name.c_str());
        } else if (C == 3) {
            set_channel(0, 2, "B"); set_channel(1, 1, "G"); set_channel(2, 0, "R");
        } else {
            set_channel(0, 3, "A"); set_channel(1, 2, "B"); set_channel(2, 1, "G"); set_channel(3, 0, "R");
        }
        image.images = reinterpret_cast<unsigned char **>(ptrs.data());
        header.num_channels = static_cast<int>(C);
        header.channels = chans.data();
        header.pixel_types = ptypes.data();
        header.requested_pixel_types = rtypes.data();
        header.compression_type = TINYEXR_COMPRESSIONTYPE_ZIP;

        unsigned char *mem = nullptr;
        const char *err = nullptr;
        // SaveEXRImageToMemory returns the byte count, but tinyexr can also return a
        // negative TINYEXR_ERROR_* code that wraps to a huge size_t; treat it as signed.
        const std::ptrdiff_t rc =
            static_cast<std::ptrdiff_t>(SaveEXRImageToMemory(&image, &header, &mem, &err));
        struct MGuard {
            unsigned char *m;
            ~MGuard() { free(m); }
        } mg{mem};
        if (rc <= 0 || !mem) {
            std::string m = err ? err : "encode error";
            FreeEXRErrorMessage(err);
            throw std::invalid_argument("exr: " + m);
        }
        out.assign(reinterpret_cast<char *>(mem), static_cast<size_t>(rc));
    }
    return emit_bytes(out.data(), out.size());
}

nb::bytes write_exr(const Image &img, size_t lanes) {
    return write_exr_impl(img, lanes, "Y");
}

nb::bytes write_exr_depth(const DepthMap &depth, const std::string &unit,
                          double scale_to_meters,
                          const std::string &invalid_policy,
                          const std::string &channel_name, size_t lanes) {
    require_exr_depth_encoding(unit, scale_to_meters, invalid_policy);
    require_exr_channel_name(channel_name);
    if (depth.unit != unit ||
        depth.scale_to_meters != scale_to_meters ||
        depth.invalid_policy != invalid_policy)
        throw std::invalid_argument(
            "EXR depth: DepthMap metadata does not match DepthEncoding");
    if (depth.has_confidence())
        throw std::invalid_argument(
            "EXR depth: confidence cannot be represented");
    if (depth.depth_convention != "unspecified")
        throw std::invalid_argument(
            "EXR depth: depth convention metadata is not representable");
    if (depth.width == 0 || depth.height == 0)
        throw std::invalid_argument(
            "EXR depth: cannot write a zero-dimension image");
    if (depth.width > static_cast<size_t>(kExrAxisCap) ||
        depth.height > static_cast<size_t>(kExrAxisCap) ||
        static_cast<uint64_t>(depth.width) * depth.height > kExrPixelCap)
        throw std::invalid_argument(
            "EXR depth: image dimensions exceed the supported limit");
    const size_t count = depth.width * depth.height;
    if (depth.depth.size() != count)
        throw std::invalid_argument(
            "EXR depth: DepthMap storage disagrees with its dimensions");

    Image image;
    image.height = depth.height;
    image.width = depth.width;
    image.channels = 1;
    image.dtype = PixelType::F32;
    image.color_space = "linear";
    image.alpha_mode = "none";
    image.maxval = 0;
    {
        nb::gil_scoped_release release;
        image.f32 = depth.depth;
    }
    return write_exr_impl(image, lanes, channel_name);
}

nb::bytes write_exr_depth_request(nb::tuple request) {
    if (request.size() != 5)
        throw std::invalid_argument(
            "EXR depth: internal write request must contain five values");
    return write_exr_depth(
        nb::cast<const DepthMap &>(request[0]),
        nb::cast<std::string>(request[1]),
        nb::cast<double>(request[2]),
        nb::cast<std::string>(request[3]),
        nb::cast<std::string>(request[4]),
        0);
}

}  // namespace

void register_exr(nb::module_ &m) {
    m.def("read_exr", &read_exr, "data"_a, "_lanes"_a = 0,
          "Decode single-part scanline OpenEXR bytes into an Image (float32, color_space='linear'): "
          "{R,G,B,A}->RGBA (premultiplied), {R,G,B}->RGB, a single channel->1-channel; HALF widens "
          "to FLOAT. Multipart/deep/tiled EXR, UINT channels, and multi-layer sets raise.");
    m.def("read_exr_depth", &read_exr_depth, "data"_a, "unit"_a,
          "scale_to_meters"_a, "invalid_policy"_a, "channel_name"_a,
          "_lanes"_a = 0,
          "Decode exactly one explicitly named HALF/FLOAT EXR channel into an "
          "owning DepthMap using the caller-supplied external depth encoding.");
    m.def("write_exr", &write_exr, "img"_a, "_lanes"_a = 0,
          "Encode a float32 linear Image to OpenEXR bytes (scanline, FLOAT, ZIP). Channels are "
          "written in (A)BGR order. Independent ZIP scanline blocks and large planar transforms "
          "use bounded worker lanes. Refuses non-float32 / non-linear records and RGBA whose "
          "alpha_mode isn't 'premultiplied' rather than converting.");
    m.def("write_exr_depth", &write_exr_depth, "depth"_a, "unit"_a,
          "scale_to_meters"_a, "invalid_policy"_a, "channel_name"_a,
          "_lanes"_a = 0,
          "Encode a scalar DepthMap to FLOAT+ZIP EXR under the explicitly "
          "requested channel after verifying its external depth encoding.");
    m.def("_write_exr_depth_request", &write_exr_depth_request, "request"_a,
          "Encode the private "
          "(DepthMap, unit, scale, invalid_policy, channel_name) sink request.");
}
