// codecs/images/jpeg.cpp -- common JPEG contract and nanobind entry points.
//
// The retained stb backend and qualification-only libjpeg-turbo candidate use
// these same guards, records, GIL boundaries, and public function signatures.
#include <climits>

#include "codecs/images/jpeg_backend.hpp"

using namespace nb::literals;
using namespace sio;

namespace sio::jpeg_backend {

void guard_dimensions(size_t width, size_t height) {
    if (width == 0 || height == 0)
        throw std::invalid_argument("jpeg: zero-dimension image");
    if (width > static_cast<size_t>(INT_MAX) ||
        height > static_cast<size_t>(INT_MAX) ||
        static_cast<uint64_t>(width) * height > kPixelCap)
        throw std::invalid_argument(
            "jpeg: image dimensions exceed the supported limit");
}

}  // namespace sio::jpeg_backend

namespace {

void validate_stream(const uint8_t *data, size_t size) {
    if (size > static_cast<size_t>(INT_MAX))
        throw std::invalid_argument("jpeg: input larger than 2 GiB is not supported");
    if (size < 2 || data[0] != 0xFF || data[1] != 0xD8)
        throw std::invalid_argument("jpeg: not a JPEG stream (missing FF D8 SOI marker)");
    bool has_eoi = false;
    for (size_t i = 2; i < size; ++i) {
        if (data[i - 1] == 0xFF && data[i] == 0xD9) {
            has_eoi = true;
            break;
        }
    }
    if (!has_eoi)
        throw std::invalid_argument("jpeg: truncated stream (missing FF D9 EOI marker)");
}

Image read_jpeg(nb::handle source) {
    sio::ByteView data(source);
    validate_stream(data.data(), data.size());
    Image image;
    {
        nb::gil_scoped_release release;
        image = sio::jpeg_backend::decode(data.data(), data.size());
    }
    return image;
}

void validate_write(const Image &image, int quality) {
    if (image.dtype != PixelType::U8)
        throw std::invalid_argument("jpeg: JPEG stores 8-bit samples (got " +
                                    std::string(image_dtype_name(image.dtype)) +
                                    "; use png for 16-bit / exr for float)");
    if (image.maxval != 255)
        throw std::invalid_argument(
            "jpeg: requires maxval 255 (partial-range record -- convert first)");
    if (image.channels == 3) {
        if (image.color_space != "srgb")
            throw std::invalid_argument(
                "jpeg: 3-channel image requires color_space 'srgb' (got '" +
                image.color_space + "'; convert linear->srgb first)");
    } else if (image.channels == 1) {
        throw std::invalid_argument(
            "jpeg: cannot write a grayscale JPEG -- the encoder contract is "
            "RGB-only. Convert to 3-channel RGB, or use PNG.");
    } else {
        throw std::invalid_argument(
            "jpeg: only 3-channel RGB is writable "
            "(JPEG has no alpha; grayscale unsupported by the encoder)");
    }
    if (quality < 1 || quality > 100)
        throw std::invalid_argument("jpeg: quality must be in 1..100");
    if (image.width > 65535 || image.height > 65535)
        throw std::invalid_argument(
            "jpeg: JPEG stores 16-bit dimensions (max 65535 per axis)");
    sio::jpeg_backend::guard_dimensions(image.width, image.height);
}

nb::bytes write_jpeg(const Image &image, int quality) {
    validate_write(image, quality);
    std::string output;
    {
        nb::gil_scoped_release release;
        output = sio::jpeg_backend::encode(image, quality);
    }
    return emit_bytes(output.data(), output.size());
}

}  // namespace

void register_jpeg(nb::module_ &m) {
    m.def("read_jpeg", &read_jpeg, "data"_a,
          "Decode JPEG bytes into an Image (uint8; grayscale -> 1-channel "
          "'gray', color -> 3-channel 'srgb'). Baseline and progressive JPEG "
          "are supported. NOTE: CMYK/YCCK JPEGs are converted to approximate "
          "3-channel RGB (not color-managed).");
    m.def("write_jpeg", &write_jpeg, "img"_a, "quality"_a = 95,
          "Encode a uint8 3-channel sRGB Image to baseline JPEG bytes at the "
          "given quality (1..100, default 95). LOSSY (DCT quantization). "
          "RGB-only: refuses grayscale, uint16/float32, and RGBA.");
#ifdef SCENEIO_BUILD_BACKEND_QUALIFICATION
#ifdef SCENEIO_USE_LIBJPEG_TURBO
    m.def("_jpeg_backend_id", []() { return "libjpeg-turbo-3.2.0"; });
#else
    m.def("_jpeg_backend_id", []() { return "stb"; });
#endif
#endif
}
