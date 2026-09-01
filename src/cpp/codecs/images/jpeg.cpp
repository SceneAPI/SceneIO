// codecs/images/jpeg.cpp -- common JPEG contract and nanobind entry points.
//
// The retained stb backend and qualification-only libjpeg-turbo candidate use
// these same guards, records, GIL boundaries, and public function signatures.
#include <climits>
#include <charconv>
#include <string_view>

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

constexpr char kXmpIdentifier[] =
    "http://ns.adobe.com/xap/1.0/\0";

struct GpanoMetadata {
    std::optional<size_t> full_width;
    std::optional<size_t> full_height;
    std::optional<size_t> cropped_width;
    std::optional<size_t> cropped_height;
    std::optional<size_t> crop_left;
    std::optional<size_t> crop_top;
};

bool ascii_space(char value) {
    return value == ' ' || value == '\t' ||
           value == '\r' || value == '\n';
}

std::string_view trim_ascii(std::string_view value) {
    while (!value.empty() && ascii_space(value.front()))
        value.remove_prefix(1);
    while (!value.empty() && ascii_space(value.back()))
        value.remove_suffix(1);
    return value;
}

std::optional<std::string_view> xmp_value(
    std::string_view xml, std::string_view key) {
    size_t search = 0;
    while (true) {
        const size_t found = xml.find(key, search);
        if (found == std::string_view::npos) return std::nullopt;
        size_t position = found + key.size();
        while (position < xml.size() && ascii_space(xml[position]))
            ++position;
        if (position < xml.size() && xml[position] == '=') {
            ++position;
            while (position < xml.size() && ascii_space(xml[position]))
                ++position;
            if (position >= xml.size() ||
                (xml[position] != '\'' && xml[position] != '"'))
                throw std::invalid_argument(
                    "jpeg: malformed GPano XMP attribute");
            const char quote = xml[position++];
            const size_t end = xml.find(quote, position);
            if (end == std::string_view::npos)
                throw std::invalid_argument(
                    "jpeg: unterminated GPano XMP attribute");
            return trim_ascii(xml.substr(position, end - position));
        }
        if (position < xml.size() && xml[position] == '>' &&
            (found == 0 || xml[found - 1] != '/')) {
            ++position;
            const size_t end = xml.find("</", position);
            if (end == std::string_view::npos)
                throw std::invalid_argument(
                    "jpeg: unterminated GPano XMP element");
            return trim_ascii(xml.substr(position, end - position));
        }
        search = found + key.size();
    }
}

std::optional<size_t> xmp_size(
    std::string_view xml, std::string_view key, bool positive) {
    const auto raw = xmp_value(xml, key);
    if (!raw) return std::nullopt;
    size_t value = 0;
    const auto parsed = std::from_chars(
        raw->data(), raw->data() + raw->size(), value);
    if (parsed.ec != std::errc() ||
        parsed.ptr != raw->data() + raw->size() ||
        (positive && value == 0))
        throw std::invalid_argument(
            "jpeg: malformed GPano XMP integer " +
            std::string(key));
    return value;
}

std::optional<GpanoMetadata> parse_gpano_xmp(
    const uint8_t *data, size_t size) {
    const std::string_view identifier(
        kXmpIdentifier, sizeof(kXmpIdentifier) - 1);
    std::optional<GpanoMetadata> result;
    size_t position = 2;
    while (position < size) {
        if (data[position] != 0xff)
            throw std::invalid_argument(
                "jpeg: malformed marker stream before scan data");
        while (position < size && data[position] == 0xff) ++position;
        if (position >= size)
            throw std::invalid_argument("jpeg: truncated marker stream");
        const uint8_t marker = data[position++];
        if (marker == 0xda || marker == 0xd9) break;
        if (marker == 0x00)
            throw std::invalid_argument(
                "jpeg: stuffed marker byte appears before scan data");
        if (marker == 0xd8 || marker == 0x01 ||
            (marker >= 0xd0 && marker <= 0xd7))
            continue;
        if (size - position < 2)
            throw std::invalid_argument("jpeg: truncated segment length");
        const size_t segment_length =
            (static_cast<size_t>(data[position]) << 8) |
            static_cast<size_t>(data[position + 1]);
        if (segment_length < 2 || segment_length > size - position)
            throw std::invalid_argument("jpeg: invalid segment length");
        const uint8_t *payload = data + position + 2;
        const size_t payload_size = segment_length - 2;
        if (marker == 0xe1 && payload_size >= identifier.size() &&
            std::string_view(
                reinterpret_cast<const char *>(payload),
                identifier.size()) == identifier) {
            const std::string_view xml(
                reinterpret_cast<const char *>(
                    payload + identifier.size()),
                payload_size - identifier.size());
            const auto projection =
                xmp_value(xml, "GPano:ProjectionType");
            if (projection) {
                if (*projection != "equirectangular")
                    throw std::invalid_argument(
                        "jpeg: unsupported GPano ProjectionType '" +
                        std::string(*projection) + "'");
                GpanoMetadata metadata;
                metadata.full_width = xmp_size(
                    xml, "GPano:FullPanoWidthPixels", true);
                metadata.full_height = xmp_size(
                    xml, "GPano:FullPanoHeightPixels", true);
                metadata.cropped_width = xmp_size(
                    xml, "GPano:CroppedAreaImageWidthPixels", true);
                metadata.cropped_height = xmp_size(
                    xml, "GPano:CroppedAreaImageHeightPixels", true);
                metadata.crop_left = xmp_size(
                    xml, "GPano:CroppedAreaLeftPixels", false);
                metadata.crop_top = xmp_size(
                    xml, "GPano:CroppedAreaTopPixels", false);
                if (result)
                    throw std::invalid_argument(
                        "jpeg: duplicate GPano projection metadata");
                result = metadata;
            }
        }
        position += segment_length;
    }
    return result;
}

void apply_gpano_metadata(
    Image &image, const std::optional<GpanoMetadata> &metadata) {
    if (!metadata) return;
    if ((metadata->cropped_width &&
         *metadata->cropped_width != image.width) ||
        (metadata->cropped_height &&
         *metadata->cropped_height != image.height))
        throw std::invalid_argument(
            "jpeg: GPano cropped dimensions disagree with JPEG dimensions");
    assign_image_projection(
        image, "equirectangular",
        metadata->full_width.value_or(image.width),
        metadata->full_height.value_or(image.height),
        metadata->crop_left.value_or(0),
        metadata->crop_top.value_or(0), "jpeg");
}

std::string gpano_xmp(const Image &image) {
    return
        "<x:xmpmeta xmlns:x=\"adobe:ns:meta/\">"
        "<rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">"
        "<rdf:Description xmlns:GPano=\"http://ns.google.com/photos/1.0/panorama/\" "
        "GPano:UsePanoramaViewer=\"True\" "
        "GPano:ProjectionType=\"equirectangular\" "
        "GPano:FullPanoWidthPixels=\"" +
        std::to_string(image.projection_metadata.canvas_width) +
        "\" GPano:FullPanoHeightPixels=\"" +
        std::to_string(image.projection_metadata.canvas_height) +
        "\" GPano:CroppedAreaImageWidthPixels=\"" +
        std::to_string(image.width) +
        "\" GPano:CroppedAreaImageHeightPixels=\"" +
        std::to_string(image.height) +
        "\" GPano:CroppedAreaLeftPixels=\"" +
        std::to_string(image.projection_metadata.crop_left) +
        "\" GPano:CroppedAreaTopPixels=\"" +
        std::to_string(image.projection_metadata.crop_top) +
        "\"/></rdf:RDF></x:xmpmeta>";
}

std::string add_gpano_xmp(std::string jpeg, const Image &image) {
    if (image.projection_metadata.kind == "unknown") return jpeg;
    const std::string xml = gpano_xmp(image);
    const size_t payload_size = sizeof(kXmpIdentifier) - 1 + xml.size();
    if (payload_size > 65533)
        throw std::invalid_argument("jpeg: GPano XMP exceeds APP1 limit");
    const uint16_t segment_length =
        static_cast<uint16_t>(payload_size + 2);
    std::string result;
    result.reserve(jpeg.size() + payload_size + 4);
    result.append(jpeg.data(), 2);
    result.push_back(static_cast<char>(0xff));
    result.push_back(static_cast<char>(0xe1));
    result.push_back(static_cast<char>(segment_length >> 8));
    result.push_back(static_cast<char>(segment_length & 0xff));
    result.append(kXmpIdentifier, sizeof(kXmpIdentifier) - 1);
    result.append(xml);
    result.append(jpeg.data() + 2, jpeg.size() - 2);
    return result;
}

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
    const auto gpano = parse_gpano_xmp(data.data(), data.size());
    Image image;
    {
        nb::gil_scoped_release release;
        image = sio::jpeg_backend::decode(data.data(), data.size());
    }
    apply_gpano_metadata(image, gpano);
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
        output = add_gpano_xmp(std::move(output), image);
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
