// Retained JPEG implementation via vendored stb_image/stb_image_write.
#include <climits>

#include "codecs/images/jpeg_backend.hpp"
#include "stb_config.h"
#include "stb_image.h"
#include "stb_image_write.h"

namespace sio::jpeg_backend {

Image decode_with_stb(const uint8_t *data, size_t size) {
    const int length = static_cast<int>(size);
    int width = 0;
    int height = 0;
    int components = 0;
    if (!stbi_info_from_memory(
            data, length, &width, &height, &components))
        throw std::invalid_argument(
            std::string("jpeg: ") + stbi_failure_reason());
    guard_dimensions(
        static_cast<size_t>(width), static_cast<size_t>(height));

    int channels = 0;
    stbi_uc *pixels = stbi_load_from_memory(
        data, length, &width, &height, &channels, 0);
    struct PixelGuard {
        stbi_uc *pixels;
        ~PixelGuard() { stbi_image_free(pixels); }
    } guard{pixels};
    if (!pixels)
        throw std::invalid_argument(
            std::string("jpeg: ") + stbi_failure_reason());
    if (channels != 1 && channels != 3)
        throw std::invalid_argument(
            "jpeg: only grayscale or RGB JPEG is supported (got " +
            std::to_string(channels) + " channels)");

    Image image;
    image.height = static_cast<size_t>(height);
    image.width = static_cast<size_t>(width);
    image.channels = static_cast<size_t>(channels);
    image.dtype = PixelType::U8;
    image.color_space = channels == 1 ? "gray" : "srgb";
    image.alpha_mode = "none";
    image.maxval = 255;
    const size_t count =
        static_cast<size_t>(width) * height * channels;
    image.u8.assign(pixels, pixels + count);
    return image;
}

#ifndef SCENEIO_USE_LIBJPEG_TURBO

Image decode(const uint8_t *data, size_t size) {
    return decode_with_stb(data, size);
}

std::string encode(const Image &image, int quality) {
    std::string output;
    output.reserve(image.u8.size());
    auto callback = [](void *context, void *bytes, int size) {
        static_cast<std::string *>(context)->append(
            static_cast<const char *>(bytes), static_cast<size_t>(size));
    };
    if (!stbi_write_jpg_to_func(
            callback, &output, static_cast<int>(image.width),
            static_cast<int>(image.height),
            static_cast<int>(image.channels), image.u8.data(), quality))
        throw std::invalid_argument("jpeg: encode failed");
    return output;
}

#endif

}  // namespace sio::jpeg_backend
