// codecs/exr.cpp — OpenEXR (.exr) <-> Image (float32, linear) via vendored tinyexr
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
#include <vector>

#include "records/image.hpp"
#include "tinyexr.h"

using namespace nb::literals;
using namespace sio;

namespace {
constexpr uint64_t kExrPixelCap = 250000000ull;  // 250 MP; worst-case f32 RGBA buffer ~4 GB
constexpr int64_t kExrAxisCap = 1 << 20;          // 1M per axis

Image read_exr(nb::handle source) {
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
        for (size_t p = 0; p < n; p++)
            for (int c = 0; c < C; c++)
                im.f32[p * C + c] = planar[planes[c]][p];
    }
    return im;
}

nb::bytes write_exr(const Image &img) {
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
    if (static_cast<int64_t>(img.width) > kExrAxisCap || static_cast<int64_t>(img.height) > kExrAxisCap ||
        static_cast<uint64_t>(img.width) * img.height > kExrPixelCap)
        throw std::invalid_argument("exr: image dimensions exceed the supported limit");

    std::string out;
    {
        nb::gil_scoped_release rel;  // nb::bytes built after the scope, under the GIL
        const size_t W = img.width, H = img.height, n = W * H;
        // deinterleave RGBA... -> planar per-channel buffers (planar[0]=R, [1]=G, ...)
        std::vector<std::vector<float>> planar(C, std::vector<float>(n));
        for (size_t p = 0; p < n; p++)
            for (size_t c = 0; c < C; c++) planar[c][p] = img.f32[p * C + c];

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
            set_channel(0, 0, "Y");  // single luminance channel (not "A"): correct for depth/gray
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
    return nb::bytes(out.data(), out.size());
}

}  // namespace

void register_exr(nb::module_ &m) {
    m.def("read_exr", &read_exr, "data"_a,
          "Decode single-part scanline OpenEXR bytes into an Image (float32, color_space='linear'): "
          "{R,G,B,A}->RGBA (premultiplied), {R,G,B}->RGB, a single channel->1-channel; HALF widens "
          "to FLOAT. Multipart/deep/tiled EXR, UINT channels, and multi-layer sets raise.");
    m.def("write_exr", &write_exr, "img"_a,
          "Encode a float32 linear Image to OpenEXR bytes (scanline, FLOAT, ZIP). Channels are "
          "written in (A)BGR order. Refuses non-float32 / non-linear records and RGBA whose "
          "alpha_mode isn't 'premultiplied' rather than converting.");
}
