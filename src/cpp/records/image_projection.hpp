// records/image_projection.hpp -- shared still/sequence raster projection metadata.
#pragma once

#include <cstddef>
#include <optional>
#include <stdexcept>
#include <string>

struct ImageProjectionMetadata {
    std::string kind = "unknown";
    size_t canvas_width = 0;
    size_t canvas_height = 0;
    size_t crop_left = 0;
    size_t crop_top = 0;

    bool is_full_sphere(size_t raster_width, size_t raster_height) const {
        return kind == "equirectangular" &&
               canvas_width == raster_width &&
               canvas_height == raster_height &&
               crop_left == 0 && crop_top == 0;
    }
};

inline void assign_image_projection_metadata(
    ImageProjectionMetadata &target,
    size_t raster_width,
    size_t raster_height,
    const std::string &projection,
    std::optional<size_t> canvas_width = std::nullopt,
    std::optional<size_t> canvas_height = std::nullopt,
    std::optional<size_t> crop_left = std::nullopt,
    std::optional<size_t> crop_top = std::nullopt,
    const char *context = "image") {
    if (projection == "unknown") {
        if (canvas_width || canvas_height || crop_left || crop_top)
            throw std::invalid_argument(
                std::string(context) +
                ": projection canvas/crop metadata requires "
                "projection='equirectangular'");
        target = ImageProjectionMetadata{};
        return;
    }
    if (projection != "equirectangular")
        throw std::invalid_argument(
            std::string(context) +
            ": projection must be unknown|equirectangular");

    const size_t full_width = canvas_width.value_or(raster_width);
    const size_t full_height = canvas_height.value_or(raster_height);
    const size_t left = crop_left.value_or(0);
    const size_t top = crop_top.value_or(0);
    if (full_width == 0 || full_height == 0)
        throw std::invalid_argument(
            std::string(context) +
            ": equirectangular canvas dimensions must be positive");
    if (left > full_width || raster_width > full_width - left ||
        top > full_height || raster_height > full_height - top)
        throw std::invalid_argument(
            std::string(context) +
            ": raster crop exceeds the equirectangular canvas");

    target.kind = projection;
    target.canvas_width = full_width;
    target.canvas_height = full_height;
    target.crop_left = left;
    target.crop_top = top;
}

inline void validate_image_projection_metadata(
    const ImageProjectionMetadata &value,
    size_t raster_width,
    size_t raster_height,
    const char *context = "image") {
    if (value.kind == "unknown") {
        if (value.canvas_width != 0 || value.canvas_height != 0 ||
            value.crop_left != 0 || value.crop_top != 0)
            throw std::invalid_argument(
                std::string(context) +
                ": unknown projection must not carry canvas/crop metadata");
        return;
    }
    ImageProjectionMetadata normalized;
    assign_image_projection_metadata(
        normalized, raster_width, raster_height, value.kind,
        value.canvas_width, value.canvas_height,
        value.crop_left, value.crop_top, context);
}
