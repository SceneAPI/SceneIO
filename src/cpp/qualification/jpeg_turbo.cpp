// Candidate JPEG implementation via libjpeg-turbo's TurboJPEG API.
//
// This translation unit is added only when the effective JPEG backend is
// libjpeg-turbo.  An ordinary stb build does not compile it.
#include "codecs/images/jpeg_backend.hpp"

#ifndef SCENEIO_USE_LIBJPEG_TURBO
#error "jpeg_turbo.cpp requires SCENEIO_USE_LIBJPEG_TURBO"
#endif

#include <memory>
#include <string>

#include <turbojpeg.h>

namespace sio::jpeg_backend {
namespace {

class TurboHandle {
  public:
    explicit TurboHandle(int mode) : handle_(tj3Init(mode)) {
        if (!handle_)
            throw std::invalid_argument(
                std::string("jpeg: libjpeg-turbo initialization failed: ") +
                tj3GetErrorStr(nullptr));
    }
    TurboHandle(const TurboHandle &) = delete;
    TurboHandle &operator=(const TurboHandle &) = delete;
    ~TurboHandle() { tj3Destroy(handle_); }

    tjhandle get() const { return handle_; }

    void set(int parameter, int value) {
        if (tj3Set(handle_, parameter, value) < 0)
            fail("parameter setup");
    }

    [[noreturn]] void fail(const char *operation) const {
        throw std::invalid_argument(
            std::string("jpeg: libjpeg-turbo ") + operation +
            " failed: " + tj3GetErrorStr(handle_));
    }

  private:
    tjhandle handle_;
};

}  // namespace

Image decode(const uint8_t *data, size_t size) {
    TurboHandle decoder(TJINIT_DECOMPRESS);
    decoder.set(TJPARAM_STOPONWARNING, 1);
    decoder.set(TJPARAM_MAXPIXELS, static_cast<int>(kPixelCap));
    if (tj3DecompressHeader(decoder.get(), data, size) < 0)
        decoder.fail("header decode");

    const int width = tj3Get(decoder.get(), TJPARAM_JPEGWIDTH);
    const int height = tj3Get(decoder.get(), TJPARAM_JPEGHEIGHT);
    const int precision = tj3Get(decoder.get(), TJPARAM_PRECISION);
    const int color_space = tj3Get(decoder.get(), TJPARAM_COLORSPACE);
    if (width < 0 || height < 0 || precision < 0 || color_space < 0)
        decoder.fail("header query");
    guard_dimensions(
        static_cast<size_t>(width), static_cast<size_t>(height));
    if (precision != 8)
        throw std::invalid_argument(
            "jpeg: only 8-bit JPEG samples are supported");

    // Preserve the retained backend's documented approximate RGB conversion
    // for four-component JPEGs until that profile receives its own measured
    // compatibility decision.
    if (color_space == TJCS_CMYK || color_space == TJCS_YCCK)
        return decode_with_stb(data, size);

    int channels = 0;
    int pixel_format = 0;
    if (color_space == TJCS_GRAY) {
        channels = 1;
        pixel_format = TJPF_GRAY;
    } else if (color_space == TJCS_RGB ||
               color_space == TJCS_YCbCr) {
        channels = 3;
        pixel_format = TJPF_RGB;
    } else {
        throw std::invalid_argument(
            "jpeg: unsupported JPEG color space");
    }

    Image image;
    image.height = static_cast<size_t>(height);
    image.width = static_cast<size_t>(width);
    image.channels = static_cast<size_t>(channels);
    image.dtype = PixelType::U8;
    image.color_space = channels == 1 ? "gray" : "srgb";
    image.alpha_mode = "none";
    image.maxval = 255;
    image.u8.resize(
        static_cast<size_t>(width) * height * channels);
    if (tj3Decompress8(
            decoder.get(), data, size, image.u8.data(), 0,
            pixel_format) < 0)
        decoder.fail("pixel decode");
    return image;
}

std::string encode(const Image &image, int quality) {
    TurboHandle encoder(TJINIT_COMPRESS);
    encoder.set(TJPARAM_STOPONWARNING, 1);
    encoder.set(TJPARAM_QUALITY, quality);
    encoder.set(
        TJPARAM_SUBSAMP, quality <= 90 ? TJSAMP_420 : TJSAMP_444);
    encoder.set(TJPARAM_OPTIMIZE, 0);
    encoder.set(TJPARAM_PROGRESSIVE, 0);
    encoder.set(TJPARAM_FASTDCT, 0);

    unsigned char *encoded = nullptr;
    size_t encoded_size = 0;
    if (tj3Compress8(
            encoder.get(), image.u8.data(),
            static_cast<int>(image.width), 0,
            static_cast<int>(image.height), TJPF_RGB, &encoded,
            &encoded_size) < 0) {
        tj3Free(encoded);
        encoder.fail("encode");
    }
    if (!encoded || encoded_size == 0) {
        tj3Free(encoded);
        throw std::invalid_argument(
            "jpeg: libjpeg-turbo encode returned no output");
    }
    std::unique_ptr<unsigned char, decltype(&tj3Free)> guard(
        encoded, &tj3Free);
    return {
        reinterpret_cast<const char *>(encoded),
        encoded_size,
    };
}

}  // namespace sio::jpeg_backend
