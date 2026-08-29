// records/image.hpp — raster image memory representation. Pixels are stored
// interleaved HxWxC, top-to-bottom rows, in canonical RGB(A) channel order,
// in exactly one of three typed vectors (u8/u16/f32) selected by a PixelType
// tag — no std::variant, no byte-blob reinterpret casts, so codecs write
// type-safe bulk copies and the binding branches trivially. Backs PGM/PPM
// now, PNG/JPEG/TIFF/WebP/EXR later without ABI breaks (the enum has room for
// F16; optional white-level/EXIF extras are additive).
//
// Reconciles the two Phase-1a Image designs: the richer PixelType /
// color_space / alpha_mode record and the netpbm record's `maxval` sample-
// range field. Conventions are metadata the codec RECORDED (color_space,
// alpha_mode, maxval); channel_order and row_order are fixed canonical tags.
// Nothing here is ever baked into the pixel values.
#pragma once

#include "io/common.hpp"

// The three sample dtypes an Image can hold. Values are explicit so F16=3 can
// be added later (PNG 16-bit, EXR) without renumbering.
enum class PixelType : uint8_t { U8 = 0, U16 = 1, F32 = 2 };

struct Image {
    size_t height = 0, width = 0, channels = 0;  // channels in {1,3,4}
    PixelType dtype = PixelType::U8;
    // Exactly one vector holds height*width*channels interleaved samples
    // (row-major, top-to-bottom rows, RGB(A) order); the other two stay empty.
    std::vector<uint8_t> u8;
    std::vector<uint16_t> u16;
    std::vector<float> f32;
    // Conventions the codec RECORDED (metadata, never encoded in the pixels):
    std::string color_space = "srgb";  // "srgb" | "linear" | "gray" | "unknown"
    std::string alpha_mode = "none";   // "none" (C!=4) | "straight" | "premultiplied" (C==4)
    uint32_t maxval = 255;             // netpbm sample range 0..maxval — metadata, arrays never rescaled

    size_t count() const { return height * width * channels; }
    size_t num_samples() const { return height * width * channels; }  // alias for the netpbm codec
};

inline const char *image_dtype_name(PixelType t) {
    switch (t) {
        case PixelType::U8: return "uint8";
        case PixelType::U16: return "uint16";
        default: return "float32";
    }
}
inline bool image_valid_channels(size_t c) { return c == 1 || c == 3 || c == 4; }
inline bool image_valid_color_space(const std::string &s) {
    return s == "srgb" || s == "linear" || s == "gray" || s == "unknown";
}
