// Windows BMP and Truevision TGA <-> Image via the existing vendored stb
// implementation (public domain / MIT).
//
// Both readers first validate the format-specific header and payload bounds
// before calling stb. This is necessary because these legacy formats have no
// checksum/end marker and some stb fast paths otherwise synthesize zero bytes
// for truncated input. Decoded rows are top-to-bottom and channels are
// canonical gray/RGB/RGBA, matching Image.
//
// BMP read subset:
//   Windows DIB headers 40/56/108/124, BI_RGB or BI_BITFIELDS, 1/4/8-bit
//   palettes and 16/24/32-bit direct color, bottom-up or top-down. RLE,
//   embedded JPEG/PNG, OS/2 headers, and BI_ALPHABITFIELDS are refused.
//   BI_RGB 32-bit's unused high byte is ignored; explicit V4/V5 alpha masks
//   decode to straight RGBA.
// BMP write subset:
//   uint8 sRGB RGB -> deterministic 24-bit BI_RGB, or straight RGBA ->
//   deterministic 32-bit V4 BI_BITFIELDS. Grayscale is refused because stb
//   would silently expand it to RGB.
//
// TGA read subset:
//   uncompressed/RLE truecolor, grayscale, and zero-origin palettes; 15/16-bit
//   packed color is expanded exactly to RGB8. Right-to-left/interleaved images,
//   nonzero palette origins, and grayscale+alpha are refused because stb/Image
//   cannot represent them losslessly.
// TGA write subset:
//   uint8 gray/RGB/straight-RGBA using stb's deterministic RLE writer.
#include <algorithm>
#include <climits>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>

#include "records/image.hpp"
#include "stb_config.h"
#include "stb_image.h"
#include "stb_image_write.h"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr uint64_t kStbPixelCap = 250000000ull;
constexpr size_t kSinkChunk = 256 * 1024;

uint16_t read_u16_le(const uint8_t *data) {
    return static_cast<uint16_t>(
        static_cast<uint16_t>(data[0]) |
        (static_cast<uint16_t>(data[1]) << 8));
}

uint32_t read_u32_le(const uint8_t *data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
}

int64_t signed_u32(uint32_t value) {
    if ((value & 0x80000000u) == 0)
        return static_cast<int64_t>(value);
    return static_cast<int64_t>(value) - (int64_t{1} << 32);
}

void require_range(size_t offset, uint64_t count, size_t size,
                   const char *message) {
    if (offset > size || count > static_cast<uint64_t>(size - offset))
        throw std::invalid_argument(message);
}

void guard_stb_dims(uint64_t width, uint64_t height, uint64_t axis_cap,
                    const char *format) {
    if (width == 0 || height == 0)
        throw std::invalid_argument(
            std::string(format) + ": zero-dimension image");
    if (width > axis_cap || height > axis_cap ||
        width > kStbPixelCap / height)
        throw std::invalid_argument(
            std::string(format) +
            ": image dimensions exceed the supported limit");
}

struct BmpHeader {
    size_t width;
    size_t height;
    size_t channels;
    uint16_t bits_per_pixel;
    uint32_t compression;
    bool palette;
    bool top_down;
    size_t pixel_offset;
    uint64_t row_bytes;
    size_t palette_count;
};

bool contiguous_mask(uint32_t mask) {
    if (mask == 0) return false;
    while ((mask & 1u) == 0) mask >>= 1;
    return (mask & (mask + 1u)) == 0;
}

unsigned mask_bits(uint32_t mask) {
    unsigned count = 0;
    while (mask != 0) {
        count += mask & 1u;
        mask >>= 1;
    }
    return count;
}

void validate_bmp_masks(uint32_t red, uint32_t green, uint32_t blue,
                        uint32_t alpha, uint16_t bits_per_pixel) {
    const uint32_t permitted =
        bits_per_pixel == 32
            ? std::numeric_limits<uint32_t>::max()
            : (uint32_t{1} << bits_per_pixel) - 1;
    if (!contiguous_mask(red) || !contiguous_mask(green) ||
        !contiguous_mask(blue) ||
        mask_bits(red) > 8 || mask_bits(green) > 8 ||
        mask_bits(blue) > 8 ||
        ((red | green | blue) & ~permitted) != 0 ||
        (red & green) != 0 || (red & blue) != 0 ||
        (green & blue) != 0)
        throw std::invalid_argument(
            "bmp: invalid BI_BITFIELDS color masks");
    if (alpha != 0 &&
        (!contiguous_mask(alpha) || mask_bits(alpha) > 8 ||
         (alpha & ~permitted) != 0 ||
         (alpha & (red | green | blue)) != 0))
        throw std::invalid_argument(
            "bmp: invalid BI_BITFIELDS alpha mask");
}

BmpHeader parse_bmp(const uint8_t *data, size_t size,
                    bool validate_payload) {
    if (size < 54 || data[0] != 'B' || data[1] != 'M')
        throw std::invalid_argument(
            "bmp: not a Windows BMP stream (missing BM header)");
    const uint32_t declared_size = read_u32_le(data + 2);
    const uint32_t pixel_offset_u32 = read_u32_le(data + 10);
    const uint32_t dib_size = read_u32_le(data + 14);
    if (dib_size != 40 && dib_size != 56 &&
        dib_size != 108 && dib_size != 124)
        throw std::invalid_argument(
            "bmp: only Windows DIB headers 40/56/108/124 are supported");
    require_range(14, dib_size, size, "bmp: truncated DIB header");

    const int64_t signed_width = signed_u32(read_u32_le(data + 18));
    const int64_t signed_height = signed_u32(read_u32_le(data + 22));
    if (signed_width <= 0 || signed_height == 0)
        throw std::invalid_argument(
            "bmp: width must be positive and height must be nonzero");
    const uint64_t width = static_cast<uint64_t>(signed_width);
    const uint64_t height = static_cast<uint64_t>(
        signed_height < 0 ? -signed_height : signed_height);
    guard_stb_dims(width, height, static_cast<uint64_t>(INT_MAX), "bmp");
    if (read_u16_le(data + 26) != 1)
        throw std::invalid_argument("bmp: plane count must be one");

    const uint16_t bits_per_pixel = read_u16_le(data + 28);
    if (bits_per_pixel != 1 && bits_per_pixel != 4 &&
        bits_per_pixel != 8 && bits_per_pixel != 16 &&
        bits_per_pixel != 24 && bits_per_pixel != 32)
        throw std::invalid_argument(
            "bmp: unsupported bits-per-pixel (expected 1/4/8/16/24/32)");
    const uint32_t compression = read_u32_le(data + 30);
    if (compression == 1 || compression == 2)
        throw std::invalid_argument(
            "bmp: BI_RLE4/BI_RLE8 compression is unsupported");
    if (compression != 0 && compression != 3)
        throw std::invalid_argument(
            "bmp: only BI_RGB and BI_BITFIELDS are supported");
    if (compression == 3 &&
        bits_per_pixel != 16 && bits_per_pixel != 32)
        throw std::invalid_argument(
            "bmp: BI_BITFIELDS requires 16 or 32 bits per pixel");
    if (signed_height < 0 && compression != 0 && compression != 3)
        throw std::invalid_argument(
            "bmp: top-down compressed DIB is unsupported");

    uint64_t header_end = 14ull + dib_size;
    uint32_t alpha_mask = 0;
    // Match the pinned stb parser exactly. BITMAPINFOHEADER and its 56-byte
    // sibling read three external masks in BI_BITFIELDS mode; V4/V5 carry
    // masks within the DIB header.
    if (compression == 3 && (dib_size == 40 || dib_size == 56)) {
        require_range(
            static_cast<size_t>(header_end), 12, size,
            "bmp: truncated BI_BITFIELDS masks");
        const uint32_t red =
            read_u32_le(data + static_cast<size_t>(header_end));
        const uint32_t green =
            read_u32_le(data + static_cast<size_t>(header_end) + 4);
        const uint32_t blue =
            read_u32_le(data + static_cast<size_t>(header_end) + 8);
        validate_bmp_masks(
            red, green, blue, 0, bits_per_pixel);
        header_end += 12;
    } else if (compression == 3 &&
               (dib_size == 108 || dib_size == 124)) {
        const uint32_t red = read_u32_le(data + 54);
        const uint32_t green = read_u32_le(data + 58);
        const uint32_t blue = read_u32_le(data + 62);
        alpha_mask = read_u32_le(data + 66);
        validate_bmp_masks(
            red, green, blue, alpha_mask, bits_per_pixel);
    }

    const uint64_t pixel_offset = pixel_offset_u32;
    if (pixel_offset < header_end || pixel_offset > size)
        throw std::invalid_argument("bmp: invalid pixel-data offset");
    const bool palette = bits_per_pixel < 16;
    size_t palette_count = 0;
    if (palette) {
        const uint32_t used = read_u32_le(data + 46);
        const uint32_t maximum = uint32_t{1} << bits_per_pixel;
        const uint32_t declared_palette = used == 0 ? maximum : used;
        if (declared_palette == 0 || declared_palette > maximum)
            throw std::invalid_argument(
                "bmp: invalid palette entry count");
        const uint64_t expected_offset =
            header_end + static_cast<uint64_t>(declared_palette) * 4;
        if (pixel_offset != expected_offset)
            throw std::invalid_argument(
                "bmp: palette size disagrees with pixel-data offset");
        palette_count = declared_palette;
    }

    const uint64_t row_bits = width * bits_per_pixel;
    const uint64_t row_bytes = ((row_bits + 31) / 32) * 4;
    const uint64_t payload_bytes = row_bytes * height;
    const uint64_t required_end = pixel_offset + payload_bytes;
    if (required_end < pixel_offset)
        throw std::invalid_argument("bmp: pixel payload size overflows");
    if (declared_size != 0 &&
        (declared_size < required_end || declared_size > size))
        throw std::invalid_argument(
            "bmp: declared file size is inconsistent");
    if (validate_payload && required_end > size)
        throw std::invalid_argument("bmp: truncated pixel payload");

    if (validate_payload && palette) {
        for (uint64_t row = 0; row < height; ++row) {
            const uint8_t *source =
                data + static_cast<size_t>(pixel_offset + row * row_bytes);
            for (uint64_t column = 0; column < width; ++column) {
                uint8_t index;
                if (bits_per_pixel == 8) {
                    index = source[column];
                } else if (bits_per_pixel == 4) {
                    const uint8_t packed = source[column / 2];
                    index = (column & 1) != 0 ? packed & 0x0f : packed >> 4;
                } else {
                    const uint8_t packed = source[column / 8];
                    index = static_cast<uint8_t>(
                        (packed >> (7 - (column & 7))) & 1);
                }
                if (index >= palette_count)
                    throw std::invalid_argument(
                        "bmp: pixel index exceeds the palette");
            }
        }
    }

    size_t channels = 3;
    if (bits_per_pixel == 32 && compression == 3 &&
        (dib_size == 108 || dib_size == 124) && alpha_mask != 0)
        channels = 4;
    return {
        static_cast<size_t>(width),
        static_cast<size_t>(height),
        channels,
        bits_per_pixel,
        compression,
        palette,
        signed_height < 0,
        static_cast<size_t>(pixel_offset),
        row_bytes,
        palette_count,
    };
}

struct TgaHeader {
    size_t width;
    size_t height;
    size_t channels;
    uint8_t bits_per_pixel;
    bool rle;
    bool palette;
    bool top_origin;
    size_t pixel_offset;
    size_t pixel_bytes;
    size_t palette_count;
};

uint32_t tga_index(const uint8_t *data, size_t bytes) {
    return bytes == 1 ? data[0] : read_u16_le(data);
}

TgaHeader parse_tga(const uint8_t *data, size_t size,
                    bool validate_payload) {
    if (size < 18)
        throw std::invalid_argument("tga: truncated 18-byte header");
    const uint8_t id_length = data[0];
    const uint8_t color_map_type = data[1];
    const uint8_t image_type = data[2];
    const bool rle = image_type >= 8;
    const uint8_t base_type =
        static_cast<uint8_t>(rle ? image_type - 8 : image_type);
    if (base_type != 1 && base_type != 2 && base_type != 3)
        throw std::invalid_argument(
            "tga: only color-mapped, truecolor, and grayscale images are "
            "supported");
    const bool palette = base_type == 1;
    if ((palette && color_map_type != 1) ||
        (!palette && color_map_type != 0))
        throw std::invalid_argument(
            "tga: color-map flag disagrees with image type");

    const uint16_t palette_first = read_u16_le(data + 3);
    const uint16_t palette_length = read_u16_le(data + 5);
    const uint8_t palette_bits = data[7];
    const uint16_t width = read_u16_le(data + 12);
    const uint16_t height = read_u16_le(data + 14);
    const uint8_t bits_per_pixel = data[16];
    const uint8_t descriptor = data[17];
    guard_stb_dims(width, height, 65535, "tga");
    if ((descriptor & 0xc0) != 0)
        throw std::invalid_argument(
            "tga: interleaved row storage is unsupported");
    if ((descriptor & 0x10) != 0)
        throw std::invalid_argument(
            "tga: right-to-left pixel order is unsupported");
    const uint8_t alpha_bits = descriptor & 0x0f;

    size_t channels;
    size_t pixel_bytes;
    size_t palette_count = 0;
    uint64_t palette_bytes = 0;
    if (palette) {
        if (palette_first != 0)
            throw std::invalid_argument(
                "tga: nonzero palette origins are unsupported");
        if (palette_length == 0)
            throw std::invalid_argument("tga: palette is empty");
        if (bits_per_pixel != 8 && bits_per_pixel != 16)
            throw std::invalid_argument(
                "tga: palette indices must be 8 or 16 bits");
        if (palette_bits == 8) {
            channels = 1;
            pixel_bytes = bits_per_pixel / 8;
        } else if (palette_bits == 15 || palette_bits == 16 ||
                   palette_bits == 24) {
            channels = 3;
            pixel_bytes = bits_per_pixel / 8;
        } else if (palette_bits == 32) {
            channels = 4;
            pixel_bytes = bits_per_pixel / 8;
        } else {
            throw std::invalid_argument(
                "tga: palette entries must be 8/15/16/24/32 bits");
        }
        palette_count = palette_length;
        palette_bytes = static_cast<uint64_t>(palette_length) *
                        ((palette_bits + 7) / 8);
    } else if (base_type == 3) {
        if (bits_per_pixel == 16)
            throw std::invalid_argument(
                "tga: grayscale+alpha cannot map to Image's 1/3/4 channels");
        if (bits_per_pixel != 8)
            throw std::invalid_argument(
                "tga: grayscale samples must be 8 bits");
        channels = 1;
        pixel_bytes = 1;
    } else {
        if (bits_per_pixel == 15 || bits_per_pixel == 16) {
            channels = 3;
            pixel_bytes = 2;
        } else if (bits_per_pixel == 24) {
            channels = 3;
            pixel_bytes = 3;
        } else if (bits_per_pixel == 32) {
            channels = 4;
            pixel_bytes = 4;
        } else {
            throw std::invalid_argument(
                "tga: truecolor pixels must be 15/16/24/32 bits");
        }
    }
    if ((channels == 4 && alpha_bits != 8) ||
        (channels != 4 && alpha_bits != 0))
        throw std::invalid_argument(
            "tga: descriptor alpha bits disagree with the pixel format");

    const uint64_t pixel_offset_u64 =
        18ull + id_length + palette_bytes;
    if (pixel_offset_u64 > size)
        throw std::invalid_argument(
            "tga: truncated id or palette data");
    const size_t pixel_offset = static_cast<size_t>(pixel_offset_u64);
    if (validate_payload) {
        uint64_t remaining =
            static_cast<uint64_t>(width) * height;
        size_t cursor = pixel_offset;
        auto validate_indices = [&](const uint8_t *values, uint64_t count) {
            if (!palette) return;
            for (uint64_t index = 0; index < count; ++index) {
                const uint32_t value =
                    tga_index(values + index * pixel_bytes, pixel_bytes);
                if (value >= palette_count)
                    throw std::invalid_argument(
                        "tga: pixel index exceeds the palette");
            }
        };
        if (!rle) {
            const uint64_t bytes = remaining * pixel_bytes;
            require_range(
                cursor, bytes, size, "tga: truncated pixel payload");
            validate_indices(data + cursor, remaining);
        } else {
            while (remaining != 0) {
                require_range(
                    cursor, 1, size, "tga: truncated RLE packet header");
                const uint8_t packet = data[cursor++];
                const uint64_t count =
                    static_cast<uint64_t>(packet & 0x7f) + 1;
                if (count > remaining)
                    throw std::invalid_argument(
                        "tga: RLE packet exceeds the declared raster");
                if ((packet & 0x80) != 0) {
                    require_range(
                        cursor, pixel_bytes, size,
                        "tga: truncated RLE pixel");
                    validate_indices(data + cursor, 1);
                    cursor += pixel_bytes;
                } else {
                    const uint64_t bytes = count * pixel_bytes;
                    require_range(
                        cursor, bytes, size,
                        "tga: truncated raw RLE packet");
                    validate_indices(data + cursor, count);
                    cursor += static_cast<size_t>(bytes);
                }
                remaining -= count;
            }
        }
    }
    return {
        width,
        height,
        channels,
        bits_per_pixel,
        rle,
        palette,
        (descriptor & 0x20) != 0,
        pixel_offset,
        pixel_bytes,
        palette_count,
    };
}

Image decode_stb_image(nb::handle source, bool bmp) {
    ByteView bytes(source);
    if (bytes.size() > static_cast<size_t>(INT_MAX))
        throw std::invalid_argument(
            std::string(bmp ? "bmp" : "tga") +
            ": input larger than 2 GiB is unsupported");
    const uint8_t *data = bytes.data();
    size_t expected_width;
    size_t expected_height;
    size_t expected_channels;
    if (bmp) {
        const BmpHeader header =
            parse_bmp(data, bytes.size(), true);
        expected_width = header.width;
        expected_height = header.height;
        expected_channels = header.channels;
    } else {
        const TgaHeader header =
            parse_tga(data, bytes.size(), true);
        expected_width = header.width;
        expected_height = header.height;
        expected_channels = header.channels;
    }

    Image result;
    {
        nb::gil_scoped_release release;
        int width = 0;
        int height = 0;
        int source_channels = 0;
        const int length = static_cast<int>(bytes.size());
        if (!stbi_info_from_memory(
                data, length, &width, &height, &source_channels))
            throw std::invalid_argument(
                std::string(bmp ? "bmp: " : "tga: ") +
                stbi_failure_reason());
        const int64_t info_height =
            height < 0 ? -static_cast<int64_t>(height) : height;
        if (width <= 0 || info_height <= 0 ||
            static_cast<size_t>(width) != expected_width ||
            static_cast<size_t>(info_height) != expected_height ||
            source_channels < 1 || source_channels > 4)
            throw std::invalid_argument(
                std::string(bmp ? "bmp" : "tga") +
                ": decoder metadata disagrees with the validated header");
        int decoded_width = 0;
        int decoded_height = 0;
        int decoded_source_channels = 0;
        stbi_uc *pixels = stbi_load_from_memory(
            data, length, &decoded_width, &decoded_height,
            &decoded_source_channels, static_cast<int>(expected_channels));
        struct Guard {
            stbi_uc *pixels;
            ~Guard() { stbi_image_free(pixels); }
        } guard{pixels};
        if (!pixels)
            throw std::invalid_argument(
                std::string(bmp ? "bmp: " : "tga: ") +
                stbi_failure_reason());
        if (decoded_source_channels < 1 ||
            decoded_source_channels > 4)
            throw std::invalid_argument(
                std::string(bmp ? "bmp" : "tga") +
                ": decoder reported an invalid source channel count");
        if (decoded_width <= 0 || decoded_height <= 0 ||
            static_cast<size_t>(decoded_width) != expected_width ||
            static_cast<size_t>(decoded_height) != expected_height)
            throw std::invalid_argument(
                std::string(bmp ? "bmp" : "tga") +
                ": decoder dimensions disagree with the header");

        result.width = static_cast<size_t>(decoded_width);
        result.height = static_cast<size_t>(decoded_height);
        result.channels = expected_channels;
        result.dtype = PixelType::U8;
        result.color_space =
            expected_channels == 1 ? "gray" : "srgb";
        result.alpha_mode =
            expected_channels == 4 ? "straight" : "none";
        result.maxval = 255;
        const size_t count =
            result.width * result.height * result.channels;
        result.u8.assign(pixels, pixels + count);
    }
    return result;
}

class StbOutput {
public:
    StbOutput()
        : streaming_(active_file_sink != nullptr) {
        if (streaming_) staging_.reserve(kSinkChunk);
    }

    void append(const void *data, size_t size) {
        if (!streaming_) {
            output_.append(
                static_cast<const char *>(data), size);
            return;
        }
        staging_.append(static_cast<const char *>(data), size);
        if (staging_.size() >= kSinkChunk) flush();
    }

    nb::bytes finish() {
        if (streaming_) {
            if (!staging_.empty())
                emit_file_chunk(staging_.data(), staging_.size());
            return nb::bytes("", 0);
        }
        return nb::bytes(output_.data(), output_.size());
    }

private:
    void flush() {
        nb::gil_scoped_acquire acquire;
        if (!emit_file_chunk(staging_.data(), staging_.size()))
            throw std::runtime_error(
                "image file sink disappeared during encode");
        staging_.clear();
    }

    bool streaming_;
    std::string output_;
    std::string staging_;
};

void stb_output_callback(void *context, void *data, int size) {
    if (size < 0)
        throw std::runtime_error("stb emitted a negative output size");
    static_cast<StbOutput *>(context)->append(
        data, static_cast<size_t>(size));
}

void validate_write_image(const Image &image, size_t min_channels,
                          size_t max_channels, uint64_t axis_cap,
                          const char *format) {
    if (image.dtype != PixelType::U8)
        throw std::invalid_argument(
            std::string(format) +
            ": only uint8 samples are representable");
    if (image.maxval != 255)
        throw std::invalid_argument(
            std::string(format) + ": requires maxval 255");
    if (image.channels < min_channels || image.channels > max_channels ||
        image.channels == 2)
        throw std::invalid_argument(
            std::string(format) +
            ": unsupported channel count");
    if (image.channels == 1) {
        if (image.color_space != "gray" ||
            image.alpha_mode != "none")
            throw std::invalid_argument(
                std::string(format) +
                ": grayscale requires color_space 'gray' and no alpha");
    } else {
        if (image.color_space != "srgb")
            throw std::invalid_argument(
                std::string(format) +
                ": RGB(A) requires color_space 'srgb'");
        const char *required =
            image.channels == 4 ? "straight" : "none";
        if (image.alpha_mode != required)
            throw std::invalid_argument(
                std::string(format) + ": " +
                (image.channels == 4
                     ? "RGBA requires straight alpha"
                     : "RGB cannot carry alpha"));
    }
    guard_stb_dims(image.width, image.height, axis_cap, format);
    const size_t expected =
        image.width * image.height * image.channels;
    if (image.u8.size() != expected)
        throw std::invalid_argument(
            std::string(format) +
            ": pixel storage disagrees with dimensions");
}

nb::bytes write_bmp(const Image &image) {
    validate_write_image(image, 3, 4, INT_MAX, "bmp");
    StbOutput output;
    {
        nb::gil_scoped_release release;
        if (!stbi_write_bmp_to_func(
                stb_output_callback, &output,
                static_cast<int>(image.width),
                static_cast<int>(image.height),
                static_cast<int>(image.channels), image.u8.data()))
            throw std::invalid_argument("bmp: encode failed");
    }
    return output.finish();
}

nb::bytes write_tga(const Image &image) {
    validate_write_image(image, 1, 4, 65535, "tga");
    StbOutput output;
    {
        nb::gil_scoped_release release;
        if (!stbi_write_tga_to_func(
                stb_output_callback, &output,
                static_cast<int>(image.width),
                static_cast<int>(image.height),
                static_cast<int>(image.channels), image.u8.data()))
            throw std::invalid_argument("tga: encode failed");
    }
    return output.finish();
}

nb::tuple inspect_bmp(nb::handle source) {
    ByteView bytes(source);
    const BmpHeader header =
        parse_bmp(bytes.data(), bytes.size(), false);
    return nb::make_tuple(
        header.height, header.width, header.channels,
        header.bits_per_pixel, header.compression,
        header.palette, header.top_down);
}

nb::tuple inspect_tga(nb::handle source) {
    ByteView bytes(source);
    const TgaHeader header =
        parse_tga(bytes.data(), bytes.size(), false);
    return nb::make_tuple(
        header.height, header.width, header.channels,
        header.bits_per_pixel, header.rle,
        header.palette, header.top_origin);
}

}  // namespace

void register_bmp_tga(nb::module_ &module) {
    module.def(
        "_inspect_bmp", &inspect_bmp, "data"_a,
        "Return BMP dimensions, channels, bit depth, compression, palette, "
        "and orientation from its header.");
    module.def(
        "read_bmp",
        [](nb::handle source) { return decode_stb_image(source, true); },
        "data"_a,
        "Decode supported Windows BMP bytes into a top-down uint8 "
        "gray/RGB/straight-RGBA Image.");
    module.def(
        "write_bmp", &write_bmp, "img"_a,
        "Encode uint8 sRGB RGB or straight-RGBA as deterministic Windows BMP. "
        "Grayscale is refused because the encoder would expand it.");

    module.def(
        "_inspect_tga", &inspect_tga, "data"_a,
        "Return TGA dimensions, channels, bit depth, RLE, palette, and "
        "orientation from its header.");
    module.def(
        "read_tga",
        [](nb::handle source) { return decode_stb_image(source, false); },
        "data"_a,
        "Decode supported Truevision TGA bytes into a top-down uint8 "
        "gray/RGB/straight-RGBA Image.");
    module.def(
        "write_tga", &write_tga, "img"_a,
        "Encode uint8 gray/RGB/straight-RGBA using deterministic TGA RLE.");
}
