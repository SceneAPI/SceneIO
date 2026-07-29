// codecs/splats/sog.cpp -- PlayCanvas SOG v2 reader/writer.
//
// SOG stores Morton-ordered Gaussian attributes in lossless WebP textures,
// described by meta.json.  The same members may live at the root of a stored
// or deflated ZIP (.sog), or next to an unbundled meta.json.  The texture
// transport is lossless; positions, quaternions, opacity, scales, DC, and SH
// palettes are explicitly quantized by the format.
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <webp/decode.h>
#include <webp/encode.h>

#include <miniz.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <functional>
#include <limits>
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "io/json_metadata_guard.hpp"
#include "records/gaussian_cloud.hpp"
#include "third_party/musl/log1p.hpp"

using namespace nb::literals;
using namespace sio;
using json = nlohmann::ordered_json;
namespace fs = std::filesystem;

namespace {

constexpr size_t kMetadataLimit = 1024 * 1024;
constexpr size_t kCodebookSize = 256;
constexpr size_t kMaxPalette = 65536;
constexpr double kSqrt2 = 1.4142135623730950488;
constexpr std::array<size_t, 4> kShCoefficients{0, 3, 8, 15};
constexpr std::array<std::array<size_t, 3>, 4> kQuaternionIndices{{
    {{1, 2, 3}},
    {{0, 2, 3}},
    {{0, 1, 3}},
    {{0, 1, 2}},
}};

size_t checked_add(size_t a, size_t b, const char *what) {
    if (b > std::numeric_limits<size_t>::max() - a)
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " size overflows");
    return a + b;
}

size_t checked_mul(size_t a, size_t b, const char *what) {
    if (a != 0 && b > std::numeric_limits<size_t>::max() / a)
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " size overflows");
    return a * b;
}

size_t ceil_div(size_t value, size_t divisor) {
    return value / divisor + (value % divisor != 0);
}

size_t round_up_four(size_t value) {
    return checked_mul(ceil_div(value, 4), 4, "texture dimension");
}

struct TextureShape {
    size_t width = 0;
    size_t height = 0;

    size_t pixels() const {
        return checked_mul(width, height, "texture");
    }
};

TextureShape main_texture_shape(size_t count) {
    if (count == 0)
        throw std::invalid_argument(
            "sog: version 2 requires at least one Gaussian");
    size_t root =
        static_cast<size_t>(std::sqrt(static_cast<long double>(count)));
    while (root != 0 && root > count / root) --root;
    while (root < count / root ||
           (root <= count / root && root * root < count))
        ++root;
    const size_t width = round_up_four(root);
    const size_t height = round_up_four(ceil_div(count, width));
    if (width > 16383 || height > 16383)
        throw std::invalid_argument(
            "sog: WebP texture dimensions exceed 16383");
    return {width, height};
}

void reject_unknown_keys(const json &value,
                         std::initializer_list<std::string_view> allowed,
                         const char *what) {
    if (!value.is_object())
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " must be an object");
    for (auto it = value.begin(); it != value.end(); ++it) {
        const std::string_view key = it.key();
        if (std::find(allowed.begin(), allowed.end(), key) ==
            allowed.end())
            throw std::invalid_argument(std::string("sog: unsupported ") +
                                        what + " field '" + it.key() + "'");
    }
}

const json &required_member(const json &value, const char *name,
                            const char *what) {
    const auto it = value.find(name);
    if (it == value.end())
        throw std::invalid_argument(std::string("sog: missing ") + what +
                                    " field '" + name + "'");
    return *it;
}

uint64_t json_u64(const json &value, const char *what) {
    if (!(value.is_number_unsigned() || value.is_number_integer()))
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " must be a non-negative integer");
    if (value.is_number_integer() && value.get<int64_t>() < 0)
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " must be a non-negative integer");
    try {
        return value.get<uint64_t>();
    } catch (const std::exception &) {
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " exceeds uint64");
    }
}

std::vector<float> json_float_array(const json &value, size_t expected,
                                    const char *what) {
    if (!value.is_array() || value.size() != expected)
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " must contain exactly " +
                                    std::to_string(expected) + " values");
    std::vector<float> result;
    result.reserve(expected);
    for (const json &item : value) {
        if (!item.is_number())
            throw std::invalid_argument(std::string("sog: ") + what +
                                        " entries must be numbers");
        const double number = item.get<double>();
        if (!std::isfinite(number) ||
            std::abs(number) >
                static_cast<double>(std::numeric_limits<float>::max()))
            throw std::invalid_argument(std::string("sog: ") + what +
                                        " entries must be finite float32");
        result.push_back(static_cast<float>(number));
    }
    return result;
}

std::vector<double> json_double_array(const json &value, size_t expected,
                                      const char *what) {
    if (!value.is_array() || value.size() != expected)
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " must contain exactly " +
                                    std::to_string(expected) + " values");
    std::vector<double> result;
    result.reserve(expected);
    for (const json &item : value) {
        if (!item.is_number())
            throw std::invalid_argument(std::string("sog: ") + what +
                                        " entries must be numbers");
        const double number = item.get<double>();
        if (!std::isfinite(number))
            throw std::invalid_argument(std::string("sog: ") + what +
                                        " entries must be finite");
        result.push_back(number);
    }
    return result;
}

bool portable_layer_filename(std::string_view name) {
    if (name.empty() || name == "." || name == ".." ||
        !valid_utf8(name))
        return false;
    for (const unsigned char c : name) {
        if (c == 0 || c == '/' || c == '\\' || c == ':' || c == '<' ||
            c == '>' || c == '"' || c == '|' || c == '?' || c == '*')
            return false;
    }
    return true;
}

std::vector<std::string> json_filenames(const json &value, size_t expected,
                                        const char *what) {
    if (!value.is_array() || value.size() != expected)
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " files must contain exactly " +
                                    std::to_string(expected) + " names");
    std::vector<std::string> result;
    result.reserve(expected);
    for (const json &item : value) {
        if (!item.is_string())
            throw std::invalid_argument(std::string("sog: ") + what +
                                        " filenames must be strings");
        const std::string name = item.get<std::string>();
        if (!portable_layer_filename(name) || name == "meta.json")
            throw std::invalid_argument(std::string("sog: invalid ") +
                                        what + " layer filename");
        result.push_back(name);
    }
    return result;
}

struct SogMetadata {
    size_t count = 0;
    std::array<double, 3> means_min{};
    std::array<double, 3> means_max{};
    std::array<std::string, 2> means_files{};
    std::array<float, kCodebookSize> scales_codebook{};
    std::string scales_file;
    std::string quats_file;
    std::array<float, kCodebookSize> sh0_codebook{};
    std::string sh0_file;
    int bands = 0;
    size_t rest = 0;
    size_t palette_count = 0;
    std::array<float, kCodebookSize> shn_codebook{};
    std::array<std::string, 2> shn_files{};

    std::set<std::string> member_names() const {
        std::set<std::string> result{
            "meta.json", means_files[0], means_files[1], scales_file,
            quats_file, sh0_file};
        if (bands != 0) {
            result.insert(shn_files[0]);
            result.insert(shn_files[1]);
        }
        return result;
    }
};

SogMetadata parse_metadata(const uint8_t *data, size_t size) {
    if (size == 0)
        throw std::invalid_argument("sog: empty meta.json");
    if (size > kMetadataLimit)
        throw std::invalid_argument("sog: meta.json exceeds 1 MiB");
    guard_json_metadata_tokens(data, size, "sog");
    json root;
    try {
        root = json::parse(data, data + size);
    } catch (const std::exception &error) {
        throw std::invalid_argument(std::string("sog: invalid meta.json: ") +
                                    error.what());
    }
    reject_unknown_keys(
        root,
        {"version", "asset", "count", "means", "scales", "quats",
         "sh0", "shN"},
        "root");
    const uint64_t version =
        json_u64(required_member(root, "version", "root"), "version");
    if (version != 2)
        throw std::invalid_argument(
            "sog: only version 2 is supported");
    const uint64_t count_u =
        json_u64(required_member(root, "count", "root"), "count");
    if (count_u > std::numeric_limits<size_t>::max() ||
        count_u > std::numeric_limits<uint32_t>::max())
        throw std::invalid_argument(
            "sog: Gaussian count exceeds the supported limit");

    SogMetadata meta;
    meta.count = static_cast<size_t>(count_u);
    (void)main_texture_shape(meta.count);

    const json &means = required_member(root, "means", "root");
    reject_unknown_keys(means, {"mins", "maxs", "files"}, "means");
    const std::vector<double> mins =
        json_double_array(required_member(means, "mins", "means"), 3,
                          "means.mins");
    const std::vector<double> maxs =
        json_double_array(required_member(means, "maxs", "means"), 3,
                          "means.maxs");
    const std::vector<std::string> means_files =
        json_filenames(required_member(means, "files", "means"), 2,
                       "means");
    for (size_t axis = 0; axis < 3; ++axis) {
        if (mins[axis] > maxs[axis])
            throw std::invalid_argument(
                "sog: means minima exceed maxima");
        meta.means_min[axis] = mins[axis];
        meta.means_max[axis] = maxs[axis];
    }
    meta.means_files = {means_files[0], means_files[1]};

    const json &scales = required_member(root, "scales", "root");
    reject_unknown_keys(scales, {"codebook", "files"}, "scales");
    const std::vector<float> scales_codebook = json_float_array(
        required_member(scales, "codebook", "scales"), kCodebookSize,
        "scales.codebook");
    std::copy(scales_codebook.begin(), scales_codebook.end(),
              meta.scales_codebook.begin());
    meta.scales_file =
        json_filenames(required_member(scales, "files", "scales"), 1,
                       "scales")[0];

    const json &quats = required_member(root, "quats", "root");
    reject_unknown_keys(quats, {"files"}, "quats");
    meta.quats_file =
        json_filenames(required_member(quats, "files", "quats"), 1,
                       "quats")[0];

    const json &sh0 = required_member(root, "sh0", "root");
    reject_unknown_keys(sh0, {"codebook", "files"}, "sh0");
    const std::vector<float> sh0_codebook =
        json_float_array(required_member(sh0, "codebook", "sh0"),
                         kCodebookSize, "sh0.codebook");
    std::copy(sh0_codebook.begin(), sh0_codebook.end(),
              meta.sh0_codebook.begin());
    meta.sh0_file =
        json_filenames(required_member(sh0, "files", "sh0"), 1,
                       "sh0")[0];

    const auto shn_it = root.find("shN");
    if (shn_it != root.end()) {
        const json &shn = *shn_it;
        reject_unknown_keys(shn, {"count", "bands", "codebook", "files"},
                            "shN");
        const uint64_t bands =
            json_u64(required_member(shn, "bands", "shN"), "shN.bands");
        if (bands < 1 || bands > 3)
            throw std::invalid_argument(
                "sog: shN.bands must be 1, 2, or 3");
        const uint64_t palette = json_u64(
            required_member(shn, "count", "shN"), "shN.count");
        if (palette == 0 || palette > kMaxPalette ||
            palette > meta.count)
            throw std::invalid_argument(
                "sog: shN.count must be in 1..min(count, 65536)");
        meta.bands = static_cast<int>(bands);
        meta.rest = kShCoefficients[meta.bands] * 3;
        meta.palette_count = static_cast<size_t>(palette);
        const std::vector<float> shn_codebook =
            json_float_array(required_member(shn, "codebook", "shN"),
                             kCodebookSize, "shN.codebook");
        std::copy(shn_codebook.begin(), shn_codebook.end(),
                  meta.shn_codebook.begin());
        const std::vector<std::string> files =
            json_filenames(required_member(shn, "files", "shN"), 2,
                           "shN");
        meta.shn_files = {files[0], files[1]};
    }

    const std::set<std::string> names = meta.member_names();
    const size_t expected_names = meta.bands == 0 ? 6 : 8;
    if (names.size() != expected_names)
        throw std::invalid_argument(
            "sog: layer filenames must be unique");
    return meta;
}

std::vector<uint8_t> read_file_bounded(const fs::path &path, size_t limit,
                                       const char *what) {
    std::error_code error;
    const uintmax_t raw_size = fs::file_size(path, error);
    if (error)
        throw std::invalid_argument(std::string("sog: cannot size ") +
                                    what);
    if (raw_size > limit || raw_size > std::numeric_limits<size_t>::max())
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " exceeds its size limit");
    const size_t size = static_cast<size_t>(raw_size);
    if (size >
        static_cast<size_t>(
            std::numeric_limits<std::streamsize>::max()))
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " exceeds stream addressability");
    std::ifstream input(path, std::ios::binary);
    if (!input)
        throw std::invalid_argument(std::string("sog: cannot open ") +
                                    what);
    std::vector<uint8_t> result(size);
    if (size != 0) {
        input.read(reinterpret_cast<char *>(result.data()),
                   static_cast<std::streamsize>(size));
        if (!input)
            throw std::invalid_argument(std::string("sog: truncated ") +
                                        what);
    }
    if (input.peek() != std::char_traits<char>::eof())
        throw std::invalid_argument(std::string("sog: ") + what +
                                    " changed while reading");
    return result;
}

class ZipReader {
public:
    ZipReader(const uint8_t *data, size_t size) : data_(data), size_(size) {
        validate_extent();
        std::memset(&archive_, 0, sizeof(archive_));
        if (!mz_zip_reader_init_mem(&archive_, data, size, 0))
            throw std::invalid_argument(
                std::string("sog: not a ZIP archive: ") +
                mz_zip_get_error_string(mz_zip_get_last_error(&archive_)));
        initialized_ = true;
        index_members();
    }

    ZipReader(const ZipReader &) = delete;
    ZipReader &operator=(const ZipReader &) = delete;

    ~ZipReader() {
        if (initialized_) mz_zip_end(&archive_);
    }

    const std::set<std::string> &names() const { return names_; }

    std::vector<uint8_t> extract(const std::string &name, size_t limit) {
        const auto found = indices_.find(name);
        if (found == indices_.end())
            throw std::invalid_argument("sog: missing ZIP member '" + name +
                                        "'");
        mz_zip_archive_file_stat stat;
        if (!mz_zip_reader_file_stat(&archive_, found->second, &stat))
            throw std::invalid_argument(
                "sog: could not read ZIP member header");
        if (stat.m_uncomp_size > limit ||
            stat.m_uncomp_size > std::numeric_limits<size_t>::max())
            throw std::invalid_argument("sog: ZIP member '" + name +
                                        "' exceeds its size limit");
        size_t output_size = 0;
        void *raw = mz_zip_reader_extract_to_heap(
            &archive_, found->second, &output_size, 0);
        struct HeapGuard {
            void *value;
            ~HeapGuard() { mz_free(value); }
        } guard{raw};
        if (!raw)
            throw std::invalid_argument("sog: could not extract ZIP member '" +
                                        name + "'");
        if (output_size != static_cast<size_t>(stat.m_uncomp_size))
            throw std::invalid_argument("sog: ZIP member '" + name +
                                        "' size changed during extraction");
        const auto *bytes = static_cast<const uint8_t *>(raw);
        return std::vector<uint8_t>(bytes, bytes + output_size);
    }

private:
    static uint16_t read_u16(const uint8_t *data) {
        return static_cast<uint16_t>(
            data[0] | (static_cast<uint16_t>(data[1]) << 8));
    }

    static uint32_t read_u32(const uint8_t *data) {
        return static_cast<uint32_t>(
            data[0] | (static_cast<uint32_t>(data[1]) << 8) |
            (static_cast<uint32_t>(data[2]) << 16) |
            (static_cast<uint32_t>(data[3]) << 24));
    }

    void validate_extent() const {
        if (size_ < 22 || std::memcmp(data_, "PK\003\004", 4) != 0)
            throw std::invalid_argument(
                "sog: malformed or empty ZIP archive");
        const size_t search_begin =
            size_ > 22 + 65535 ? size_ - (22 + 65535) : 0;
        size_t eocd = std::numeric_limits<size_t>::max();
        for (size_t candidate = size_ - 22;; --candidate) {
            if (std::memcmp(data_ + candidate, "PK\005\006", 4) == 0 &&
                candidate + 22 +
                        static_cast<size_t>(
                            read_u16(data_ + candidate + 20)) ==
                    size_) {
                eocd = candidate;
                break;
            }
            if (candidate == search_begin) break;
        }
        if (eocd == std::numeric_limits<size_t>::max())
            throw std::invalid_argument(
                "sog: ZIP end record is missing or has trailing bytes");
        if (read_u16(data_ + eocd + 4) != 0 ||
            read_u16(data_ + eocd + 6) != 0)
            throw std::invalid_argument(
                "sog: multi-disk ZIP archives are unsupported");
        const uint16_t disk_entries = read_u16(data_ + eocd + 8);
        const uint16_t total_entries = read_u16(data_ + eocd + 10);
        const uint32_t directory_size = read_u32(data_ + eocd + 12);
        const uint32_t directory_offset = read_u32(data_ + eocd + 16);
        if (disk_entries == 0xffff || total_entries == 0xffff ||
            directory_size == 0xffffffffu ||
            directory_offset == 0xffffffffu)
            throw std::invalid_argument(
                "sog: ZIP64 archives are unsupported");
        if (disk_entries != total_entries ||
            static_cast<uint64_t>(directory_offset) + directory_size !=
                eocd)
            throw std::invalid_argument(
                "sog: inconsistent ZIP central-directory extent");
    }

    void index_members() {
        const mz_uint count = mz_zip_reader_get_num_files(&archive_);
        for (mz_uint index = 0; index < count; ++index) {
            mz_zip_archive_file_stat stat;
            if (!mz_zip_reader_file_stat(&archive_, index, &stat))
                throw std::invalid_argument(
                    "sog: could not read ZIP member header");
            std::vector<char> filename(65536);
            const mz_uint filename_size = mz_zip_reader_get_filename(
                &archive_, index, filename.data(), filename.size());
            if (filename_size == 0 ||
                filename_size > filename.size())
                throw std::invalid_argument(
                    "sog: incomplete ZIP member filename");
            if (stat.m_local_header_ofs > size_ ||
                size_ - static_cast<size_t>(stat.m_local_header_ofs) < 30)
                throw std::invalid_argument(
                    "sog: truncated local ZIP member header");
            const uint8_t *local =
                data_ + static_cast<size_t>(stat.m_local_header_ofs);
            if (std::memcmp(local, "PK\003\004", 4) != 0)
                throw std::invalid_argument(
                    "sog: malformed local ZIP member header");
            const uint16_t local_flags = read_u16(local + 6);
            const uint16_t local_method = read_u16(local + 8);
            const uint16_t local_name_size = read_u16(local + 26);
            const size_t local_offset =
                static_cast<size_t>(stat.m_local_header_ofs);
            if (local_name_size != filename_size - 1 ||
                size_ - local_offset - 30 < local_name_size ||
                std::memcmp(local + 30, filename.data(),
                            local_name_size) != 0)
                throw std::invalid_argument(
                    "sog: local and central ZIP filenames disagree");
            if (local_flags != stat.m_bit_flag ||
                local_method != stat.m_method)
                throw std::invalid_argument(
                    "sog: local and central ZIP metadata disagree");
            if (stat.m_bit_flag & 1)
                throw std::invalid_argument(
                    "sog: encrypted ZIP members are unsupported");
            if (stat.m_method != 0 && stat.m_method != 8)
                throw std::invalid_argument(
                    "sog: only stored and deflated ZIP members are supported");
            if (mz_zip_reader_is_file_a_directory(&archive_, index))
                throw std::invalid_argument(
                    "sog: directory entries are unsupported");
            const std::string name(filename.data(), filename_size - 1);
            if (name.find('\0') != std::string::npos ||
                !valid_utf8(name))
                throw std::invalid_argument(
                    "sog: ZIP member filename is not valid UTF-8");
            if (!indices_.emplace(name, index).second)
                throw std::invalid_argument(
                    "sog: duplicate ZIP member '" + name + "'");
            names_.insert(name);
        }
    }

    const uint8_t *data_;
    size_t size_;
    mz_zip_archive archive_{};
    bool initialized_ = false;
    std::unordered_map<std::string, mz_uint> indices_;
    std::set<std::string> names_;
};

struct Texture {
    size_t width = 0;
    size_t height = 0;
    std::vector<uint8_t> rgba;
};

Texture decode_lossless_webp(const std::vector<uint8_t> &encoded,
                             TextureShape expected,
                             const std::string &name) {
    if (encoded.empty())
        throw std::invalid_argument("sog: empty WebP layer '" + name + "'");
    WebPBitstreamFeatures features;
    if (WebPGetFeatures(encoded.data(), encoded.size(), &features) !=
        VP8_STATUS_OK)
        throw std::invalid_argument("sog: invalid WebP layer '" + name + "'");
    if (features.has_animation)
        throw std::invalid_argument(
            "sog: animated WebP layers are unsupported");
    if (features.format != 2)
        throw std::invalid_argument(
            "sog: WebP layer '" + name + "' must be lossless VP8L");
    if (features.width <= 0 || features.height <= 0 ||
        static_cast<size_t>(features.width) != expected.width ||
        static_cast<size_t>(features.height) != expected.height)
        throw std::invalid_argument(
            "sog: WebP layer '" + name +
            "' dimensions do not match metadata");
    int width = 0;
    int height = 0;
    uint8_t *raw =
        WebPDecodeRGBA(encoded.data(), encoded.size(), &width, &height);
    struct WebPGuard {
        uint8_t *value;
        ~WebPGuard() { WebPFree(value); }
    } guard{raw};
    if (!raw)
        throw std::invalid_argument("sog: could not decode WebP layer '" +
                                    name + "'");
    const size_t bytes =
        checked_mul(expected.pixels(), 4, "decoded WebP layer");
    Texture result;
    result.width = expected.width;
    result.height = expected.height;
    result.rgba.assign(raw, raw + bytes);
    return result;
}

size_t webp_member_limit(TextureShape shape) {
    return checked_add(checked_mul(shape.pixels(), 4, "WebP member"),
                       kMetadataLimit, "WebP member");
}

double inverse_log_transform(double value) {
    const double magnitude = std::expm1(std::abs(value));
    return value < 0.0 ? -magnitude : magnitude;
}

float checked_float(double value, const char *what) {
    if (!std::isfinite(value) ||
        std::abs(value) >
            static_cast<double>(std::numeric_limits<float>::max()))
        throw std::invalid_argument(std::string("sog: decoded ") + what +
                                    " is not finite float32");
    return static_cast<float>(value);
}

template <typename Load>
GaussianCloud decode_sog(const SogMetadata &meta, Load &&load,
                         bool partial, size_t start, size_t stop) {
    if (partial)
        checked_half_open_range(start, stop, meta.count,
                                "sog point range");
    else {
        start = 0;
        stop = meta.count;
    }
    const TextureShape main_shape = main_texture_shape(meta.count);
    const size_t main_limit = webp_member_limit(main_shape);
    const Texture means_low = decode_lossless_webp(
        load(meta.means_files[0], main_limit), main_shape,
        meta.means_files[0]);
    const Texture means_high = decode_lossless_webp(
        load(meta.means_files[1], main_limit), main_shape,
        meta.means_files[1]);
    const Texture scales = decode_lossless_webp(
        load(meta.scales_file, main_limit), main_shape,
        meta.scales_file);
    const Texture quats = decode_lossless_webp(
        load(meta.quats_file, main_limit), main_shape, meta.quats_file);
    const Texture sh0 = decode_lossless_webp(
        load(meta.sh0_file, main_limit), main_shape, meta.sh0_file);

    Texture centroids;
    Texture labels;
    if (meta.bands != 0) {
        const TextureShape centroid_shape{
            checked_mul(64, kShCoefficients[meta.bands],
                        "SH centroid width"),
            ceil_div(meta.palette_count, 64)};
        if (centroid_shape.width > 16383 ||
            centroid_shape.height > 16383)
            throw std::invalid_argument(
                "sog: SH centroid texture dimensions exceed WebP limits");
        centroids = decode_lossless_webp(
            load(meta.shn_files[0],
                 webp_member_limit(centroid_shape)),
            centroid_shape, meta.shn_files[0]);
        labels = decode_lossless_webp(
            load(meta.shn_files[1], main_limit), main_shape,
            meta.shn_files[1]);
    }

    GaussianCloud cloud;
    cloud.n = stop - start;
    cloud.sh_degree = meta.bands;
    cloud.num_rest = meta.rest;
    cloud.means.resize(checked_mul(cloud.n, 3, "means"));
    cloud.scales.resize(checked_mul(cloud.n, 3, "scales"));
    cloud.quats.resize(checked_mul(cloud.n, 4, "quaternions"));
    cloud.opacity.resize(cloud.n);
    cloud.sh_dc.resize(checked_mul(cloud.n, 3, "DC"));
    cloud.sh_rest.resize(checked_mul(cloud.n, meta.rest, "SH"));

    for (size_t output = 0; output < cloud.n; ++output) {
        const size_t row = start + output;
        const size_t pixel = row * 4;
        for (size_t axis = 0; axis < 3; ++axis) {
            const uint16_t quantized = static_cast<uint16_t>(
                means_low.rgba[pixel + axis] |
                (static_cast<uint16_t>(
                     means_high.rgba[pixel + axis])
                 << 8));
            const double minimum = meta.means_min[axis];
            double range = static_cast<double>(meta.means_max[axis]) -
                           minimum;
            if (range == 0.0) range = 1.0;
            const double transformed =
                minimum + range *
                              (static_cast<double>(quantized) / 65535.0);
            cloud.means[output * 3 + axis] = checked_float(
                inverse_log_transform(transformed), "position");
            cloud.scales[output * 3 + axis] =
                meta.scales_codebook[scales.rgba[pixel + axis]];
            cloud.sh_dc[output * 3 + axis] =
                meta.sh0_codebook[sh0.rgba[pixel + axis]];
        }

        const uint8_t tag = quats.rgba[pixel + 3];
        if (tag < 252 || tag > 255)
            throw std::invalid_argument(
                "sog: quaternion layer contains an invalid largest-component tag");
        const size_t largest = tag - 252;
        std::array<double, 4> quaternion{};
        double sum = 0.0;
        for (size_t packed = 0; packed < 3; ++packed) {
            const double value =
                ((static_cast<double>(quats.rgba[pixel + packed]) /
                      255.0) *
                     2.0 -
                 1.0) /
                kSqrt2;
            quaternion[kQuaternionIndices[largest][packed]] = value;
            sum += value * value;
        }
        quaternion[largest] =
            std::sqrt(std::max(0.0, 1.0 - sum));
        for (size_t component = 0; component < 4; ++component)
            cloud.quats[output * 4 + component] =
                static_cast<float>(quaternion[component]);

        const double alpha = std::clamp(
            static_cast<double>(sh0.rgba[pixel + 3]) / 255.0,
            1e-6, 1.0 - 1e-6);
        cloud.opacity[output] =
            static_cast<float>(std::log(alpha / (1.0 - alpha)));

        if (meta.rest != 0) {
            const size_t label =
                static_cast<size_t>(labels.rgba[pixel]) |
                (static_cast<size_t>(labels.rgba[pixel + 1]) << 8);
            if (label >= meta.palette_count)
                throw std::invalid_argument(
                    "sog: SH label exceeds shN.count");
            const size_t coefficients = kShCoefficients[meta.bands];
            const size_t centroid_row = label / 64;
            const size_t centroid_column = (label % 64) * coefficients;
            for (size_t coefficient = 0; coefficient < coefficients;
                 ++coefficient) {
                const size_t centroid_pixel =
                    (centroid_row * centroids.width + centroid_column +
                     coefficient) *
                    4;
                for (size_t channel = 0; channel < 3; ++channel) {
                    cloud.sh_rest[output * meta.rest +
                                  channel * coefficients +
                                  coefficient] =
                        meta.shn_codebook[
                            centroids.rgba[centroid_pixel + channel]];
                }
            }
        }
    }
    return cloud;
}

void validate_cloud(const GaussianCloud &cloud) {
    if (cloud.means.size() != checked_mul(cloud.n, 3, "means") ||
        cloud.scales.size() != checked_mul(cloud.n, 3, "scales") ||
        cloud.quats.size() != checked_mul(cloud.n, 4, "quaternions") ||
        cloud.opacity.size() != cloud.n ||
        cloud.sh_dc.size() != checked_mul(cloud.n, 3, "DC") ||
        cloud.sh_rest.size() !=
            checked_mul(cloud.n, cloud.num_rest, "SH") ||
        gc_deg_from_rest(cloud.num_rest) != cloud.sh_degree)
        throw std::invalid_argument(
            "sog: inconsistent GaussianCloud storage");
    (void)main_texture_shape(cloud.n);
    for (float value : cloud.means)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "sog: positions must be finite");
    for (float value : cloud.scales)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "sog: log scales must be finite");
    for (float value : cloud.opacity)
        if (std::isnan(value))
            throw std::invalid_argument(
                "sog: logit opacities must not be NaN");
    for (float value : cloud.sh_dc)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "sog: DC coefficients must be finite");
    for (float value : cloud.sh_rest)
        if (!std::isfinite(value))
            throw std::invalid_argument(
                "sog: SH coefficients must be finite");
    for (size_t row = 0; row < cloud.n; ++row) {
        double norm_squared = 0.0;
        for (size_t component = 0; component < 4; ++component) {
            const float value = cloud.quats[row * 4 + component];
            if (!std::isfinite(value))
                throw std::invalid_argument(
                    "sog: quaternions must be finite");
            norm_squared += static_cast<double>(value) * value;
        }
        if (!(norm_squared > 0.0) || !std::isfinite(norm_squared))
            throw std::invalid_argument(
                "sog: quaternions must have non-zero finite norm");
    }
}

uint32_t part1_by2(uint32_t value) {
    value &= 0x000003ffu;
    value = (value ^ (value << 16)) & 0xff0000ffu;
    value = (value ^ (value << 8)) & 0x0300f00fu;
    value = (value ^ (value << 4)) & 0x030c30c3u;
    value = (value ^ (value << 2)) & 0x09249249u;
    return value;
}

uint32_t morton3(uint32_t x, uint32_t y, uint32_t z) {
    return (part1_by2(z) << 2) + (part1_by2(y) << 1) +
           part1_by2(x);
}

void refine_morton(const GaussianCloud &cloud, std::vector<uint32_t> &order,
                   size_t begin, size_t end) {
    if (begin == end) return;
    std::array<float, 3> minimum{
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
    };
    std::array<float, 3> maximum{
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
    };
    for (size_t position = begin; position < end; ++position) {
        const size_t row = order[position];
        for (size_t axis = 0; axis < 3; ++axis) {
            const float value = cloud.means[row * 3 + axis];
            minimum[axis] = std::min(minimum[axis], value);
            maximum[axis] = std::max(maximum[axis], value);
        }
    }
    const std::array<double, 3> extent{
        static_cast<double>(maximum[0]) - minimum[0],
        static_cast<double>(maximum[1]) - minimum[1],
        static_cast<double>(maximum[2]) - minimum[2],
    };
    if (extent[0] == 0.0 && extent[1] == 0.0 && extent[2] == 0.0)
        return;

    struct Keyed {
        uint32_t code;
        uint32_t row;
    };
    std::vector<Keyed> keyed;
    keyed.reserve(end - begin);
    for (size_t position = begin; position < end; ++position) {
        const uint32_t row = order[position];
        std::array<uint32_t, 3> quantized{};
        for (size_t axis = 0; axis < 3; ++axis) {
            if (extent[axis] == 0.0) continue;
            const double scaled =
                (static_cast<double>(
                     cloud.means[static_cast<size_t>(row) * 3 + axis]) -
                 minimum[axis]) *
                (1024.0 / extent[axis]);
            quantized[axis] = static_cast<uint32_t>(
                std::clamp(std::floor(scaled), 0.0, 1023.0));
        }
        keyed.push_back(
            {morton3(quantized[0], quantized[1], quantized[2]), row});
    }
    std::stable_sort(
        keyed.begin(), keyed.end(),
        [](const Keyed &left, const Keyed &right) {
            return left.code < right.code;
        });
    for (size_t i = 0; i < keyed.size(); ++i)
        order[begin + i] = keyed[i].row;

    size_t group_begin = 0;
    while (group_begin < keyed.size()) {
        size_t group_end = group_begin + 1;
        while (group_end < keyed.size() &&
               keyed[group_end].code == keyed[group_begin].code)
            ++group_end;
        if (group_end - group_begin > 256)
            refine_morton(cloud, order, begin + group_begin,
                          begin + group_end);
        group_begin = group_end;
    }
}

uint8_t truncate_u8(double value) {
    if (!(value > 0.0)) return 0;
    if (value >= 255.0) return 255;
    return static_cast<uint8_t>(value);
}

double log_transform(double value) {
    const double transformed =
        sio::third_party::musl::deterministic_log1p_nonnegative(
            std::abs(value));
    return std::signbit(value) ? -transformed : transformed;
}

struct ScalarQuantization {
    std::array<float, kCodebookSize> codebook{};
    std::vector<uint8_t> labels;
};

size_t nearest_code(const std::array<float, kCodebookSize> &codebook,
                    float value) {
    const auto upper =
        std::lower_bound(codebook.begin(), codebook.end(), value);
    if (upper == codebook.begin()) return 0;
    if (upper == codebook.end()) return codebook.size() - 1;
    const size_t high =
        static_cast<size_t>(upper - codebook.begin());
    const size_t low = high - 1;
    const double low_distance =
        std::abs(static_cast<double>(value) - codebook[low]);
    const double high_distance =
        std::abs(static_cast<double>(codebook[high]) - value);
    return high_distance < low_distance ? high : low;
}

ScalarQuantization quantize_scalars(const std::vector<float> &values) {
    if (values.empty())
        throw std::invalid_argument(
            "sog: cannot quantize an empty scalar set");
    std::vector<float> sorted = values;
    std::sort(sorted.begin(), sorted.end());
    std::vector<float> unique;
    unique.reserve(std::min(sorted.size(), kCodebookSize));
    for (float value : sorted)
        if (unique.empty() || value != unique.back())
            unique.push_back(value);

    ScalarQuantization result;
    if (unique.size() <= kCodebookSize) {
        std::copy(unique.begin(), unique.end(), result.codebook.begin());
        std::fill(result.codebook.begin() +
                      static_cast<std::ptrdiff_t>(unique.size()),
                  result.codebook.end(), unique.back());
    } else {
        for (size_t centroid = 0; centroid < kCodebookSize; ++centroid) {
            const size_t index = std::min(
                sorted.size() - 1,
                ((centroid * 2 + 1) * sorted.size()) /
                    (kCodebookSize * 2));
            result.codebook[centroid] = sorted[index];
        }
        // Four deterministic one-dimensional Lloyd refinements.  Intervals
        // stay ordered, so the resulting codebook remains binary-searchable.
        for (size_t iteration = 0; iteration < 4; ++iteration) {
            std::array<double, kCodebookSize> sums{};
            std::array<size_t, kCodebookSize> counts{};
            for (float value : sorted) {
                const size_t label =
                    nearest_code(result.codebook, value);
                sums[label] += value;
                counts[label] += 1;
            }
            for (size_t centroid = 0; centroid < kCodebookSize;
                 ++centroid)
                if (counts[centroid] != 0)
                    result.codebook[centroid] = static_cast<float>(
                        sums[centroid] / counts[centroid]);
        }
    }

    result.labels.resize(values.size());
    for (size_t i = 0; i < values.size(); ++i)
        result.labels[i] = static_cast<uint8_t>(
            nearest_code(result.codebook, values[i]));
    return result;
}

std::vector<uint8_t> encode_lossless_webp(
    const std::vector<uint8_t> &rgba, TextureShape shape,
    const char *what) {
    const size_t expected =
        checked_mul(shape.pixels(), 4, "encoded WebP input");
    if (rgba.size() != expected)
        throw std::logic_error(
            "sog: internal WebP input size mismatch");
    uint8_t *raw = nullptr;
    const size_t size = WebPEncodeLosslessRGBA(
        rgba.data(), static_cast<int>(shape.width),
        static_cast<int>(shape.height),
        static_cast<int>(shape.width * 4), &raw);
    struct WebPGuard {
        uint8_t *value;
        ~WebPGuard() { WebPFree(value); }
    } guard{raw};
    if (size == 0 || !raw)
        throw std::runtime_error(std::string("sog: could not encode ") +
                                 what + " as lossless WebP");
    return std::vector<uint8_t>(raw, raw + size);
}

struct EncodedSog {
    std::vector<std::pair<std::string, std::vector<uint8_t>>> layers;
    std::string metadata;
};

json codebook_json(
    const std::array<float, kCodebookSize> &codebook) {
    json result = json::array();
    for (float value : codebook) result.push_back(value);
    return result;
}

EncodedSog encode_sog_layers(const GaussianCloud &cloud) {
    validate_cloud(cloud);
    const TextureShape shape = main_texture_shape(cloud.n);
    const size_t texture_bytes =
        checked_mul(shape.pixels(), 4, "SOG texture");
    std::vector<uint32_t> order(cloud.n);
    for (size_t i = 0; i < cloud.n; ++i)
        order[i] = static_cast<uint32_t>(i);
    refine_morton(cloud, order, 0, order.size());

    std::array<double, 3> transformed_min{
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
    };
    std::array<double, 3> transformed_max{
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
    };
    std::vector<double> transformed_means(
        checked_mul(cloud.n, 3, "transformed means"));
    for (size_t row = 0; row < cloud.n; ++row)
        for (size_t axis = 0; axis < 3; ++axis) {
            const double value =
                log_transform(
                    cloud.means[row * 3 + axis]);
            transformed_means[row * 3 + axis] = value;
            transformed_min[axis] =
                std::min(transformed_min[axis], value);
            transformed_max[axis] =
                std::max(transformed_max[axis], value);
        }

    std::vector<uint8_t> means_low(texture_bytes, 0);
    std::vector<uint8_t> means_high(texture_bytes, 0);
    for (size_t output = 0; output < cloud.n; ++output) {
        const size_t row = order[output];
        for (size_t axis = 0; axis < 3; ++axis) {
            const double range =
                transformed_max[axis] - transformed_min[axis];
            const double transformed =
                transformed_means[row * 3 + axis];
            const uint32_t quantized =
                range == 0.0
                    ? 0
                    : static_cast<uint32_t>(std::clamp(
                          (transformed - transformed_min[axis]) /
                              range *
                              65535.0,
                          0.0, 65535.0));
            means_low[output * 4 + axis] =
                static_cast<uint8_t>(quantized & 0xff);
            means_high[output * 4 + axis] =
                static_cast<uint8_t>((quantized >> 8) & 0xff);
        }
        means_low[output * 4 + 3] = 255;
        means_high[output * 4 + 3] = 255;
    }

    std::vector<uint8_t> quaternion_texture(texture_bytes, 0);
    for (size_t output = 0; output < cloud.n; ++output) {
        const size_t row = order[output];
        std::array<double, 4> quaternion{};
        double norm_squared = 0.0;
        for (size_t component = 0; component < 4; ++component) {
            quaternion[component] =
                cloud.quats[row * 4 + component];
            norm_squared += quaternion[component] *
                            quaternion[component];
        }
        const double inverse_norm = 1.0 / std::sqrt(norm_squared);
        for (double &value : quaternion) value *= inverse_norm;
        size_t largest = 0;
        for (size_t component = 1; component < 4; ++component)
            if (std::abs(quaternion[component]) >
                std::abs(quaternion[largest]))
                largest = component;
        const double multiplier =
            (quaternion[largest] < 0.0 ? -1.0 : 1.0) * kSqrt2;
        for (double &value : quaternion) value *= multiplier;
        for (size_t packed = 0; packed < 3; ++packed)
            quaternion_texture[output * 4 + packed] = truncate_u8(
                255.0 *
                (quaternion[kQuaternionIndices[largest][packed]] * 0.5 +
                 0.5));
        quaternion_texture[output * 4 + 3] =
            static_cast<uint8_t>(252 + largest);
    }

    std::vector<float> scale_values(
        checked_mul(cloud.n, 3, "scale quantizer"));
    for (size_t axis = 0; axis < 3; ++axis)
        for (size_t row = 0; row < cloud.n; ++row)
            scale_values[axis * cloud.n + row] =
                cloud.scales[row * 3 + axis];
    const ScalarQuantization scale_quantization =
        quantize_scalars(scale_values);
    std::vector<uint8_t> scale_texture(texture_bytes, 0);
    for (size_t output = 0; output < cloud.n; ++output) {
        const size_t row = order[output];
        for (size_t axis = 0; axis < 3; ++axis)
            scale_texture[output * 4 + axis] =
                scale_quantization.labels[axis * cloud.n + row];
        scale_texture[output * 4 + 3] = 255;
    }

    std::vector<float> dc_values(
        checked_mul(cloud.n, 3, "DC quantizer"));
    for (size_t channel = 0; channel < 3; ++channel)
        for (size_t row = 0; row < cloud.n; ++row)
            dc_values[channel * cloud.n + row] =
                cloud.sh_dc[row * 3 + channel];
    const ScalarQuantization dc_quantization =
        quantize_scalars(dc_values);
    std::vector<uint8_t> sh0_texture(texture_bytes, 0);
    for (size_t output = 0; output < cloud.n; ++output) {
        const size_t row = order[output];
        for (size_t channel = 0; channel < 3; ++channel)
            sh0_texture[output * 4 + channel] =
                dc_quantization.labels[channel * cloud.n + row];
        const double opacity = cloud.opacity[row];
        const double alpha =
            opacity >= 0.0
                ? 1.0 / (1.0 + std::exp(-opacity))
                : std::exp(opacity) / (1.0 + std::exp(opacity));
        sh0_texture[output * 4 + 3] =
            truncate_u8(std::clamp(alpha * 255.0, 0.0, 255.0));
    }

    EncodedSog encoded;
    encoded.layers.emplace_back(
        "means_l.webp",
        encode_lossless_webp(means_low, shape, "means_l.webp"));
    encoded.layers.emplace_back(
        "means_u.webp",
        encode_lossless_webp(means_high, shape, "means_u.webp"));
    encoded.layers.emplace_back(
        "quats.webp",
        encode_lossless_webp(quaternion_texture, shape, "quats.webp"));
    encoded.layers.emplace_back(
        "scales.webp",
        encode_lossless_webp(scale_texture, shape, "scales.webp"));
    encoded.layers.emplace_back(
        "sh0.webp",
        encode_lossless_webp(sh0_texture, shape, "sh0.webp"));

    size_t palette_count = 0;
    ScalarQuantization shn_quantization;
    if (cloud.sh_degree != 0) {
        palette_count = 1;
        while (palette_count <= cloud.n / 2 &&
               palette_count < kMaxPalette)
            palette_count *= 2;
        const size_t rest = cloud.num_rest;
        std::vector<double> sums(
            checked_mul(palette_count, rest, "SH palette"), 0.0);
        std::vector<size_t> counts(palette_count, 0);
        std::vector<uint16_t> palette_labels(cloud.n);
        for (size_t output = 0; output < cloud.n; ++output) {
            const size_t row = order[output];
            const size_t label = std::min(
                palette_count - 1,
                static_cast<size_t>(
                    (static_cast<uint64_t>(output) * palette_count) /
                    cloud.n));
            palette_labels[output] = static_cast<uint16_t>(label);
            counts[label] += 1;
            for (size_t coefficient = 0; coefficient < rest;
                 ++coefficient)
                sums[label * rest + coefficient] +=
                    cloud.sh_rest[row * rest + coefficient];
        }
        std::vector<float> palette(
            checked_mul(palette_count, rest, "SH palette"));
        for (size_t label = 0; label < palette_count; ++label) {
            if (counts[label] == 0)
                throw std::logic_error(
                    "sog: internal empty SH palette group");
            const double inverse =
                1.0 / static_cast<double>(counts[label]);
            for (size_t coefficient = 0; coefficient < rest;
                 ++coefficient)
                palette[label * rest + coefficient] =
                    static_cast<float>(
                        sums[label * rest + coefficient] * inverse);
        }

        std::vector<float> palette_columns(
            checked_mul(palette_count, rest, "SH codebook input"));
        for (size_t coefficient = 0; coefficient < rest; ++coefficient)
            for (size_t label = 0; label < palette_count; ++label)
                palette_columns[coefficient * palette_count + label] =
                    palette[label * rest + coefficient];
        shn_quantization = quantize_scalars(palette_columns);

        const size_t coefficients =
            kShCoefficients[cloud.sh_degree];
        const TextureShape centroid_shape{
            checked_mul(64, coefficients, "SH centroid width"),
            ceil_div(palette_count, 64)};
        std::vector<uint8_t> centroid_texture(
            checked_mul(centroid_shape.pixels(), 4,
                        "SH centroid texture"),
            0);
        for (size_t label = 0; label < palette_count; ++label)
            for (size_t coefficient = 0; coefficient < coefficients;
                 ++coefficient) {
                const size_t pixel =
                    (label * coefficients + coefficient) * 4;
                for (size_t channel = 0; channel < 3; ++channel)
                    centroid_texture[pixel + channel] =
                        shn_quantization.labels[
                            (channel * coefficients + coefficient) *
                                palette_count +
                            label];
                centroid_texture[pixel + 3] = 255;
            }

        std::vector<uint8_t> label_texture(texture_bytes, 0);
        for (size_t output = 0; output < cloud.n; ++output) {
            const uint16_t label = palette_labels[output];
            label_texture[output * 4] =
                static_cast<uint8_t>(label & 0xff);
            label_texture[output * 4 + 1] =
                static_cast<uint8_t>(label >> 8);
            label_texture[output * 4 + 3] = 255;
        }
        encoded.layers.emplace_back(
            "shN_centroids.webp",
            encode_lossless_webp(centroid_texture, centroid_shape,
                                  "shN_centroids.webp"));
        encoded.layers.emplace_back(
            "shN_labels.webp",
            encode_lossless_webp(label_texture, shape,
                                  "shN_labels.webp"));
    }

    json metadata;
    metadata["version"] = 2;
    metadata["asset"] = {{"generator", "SceneIO 0.2.0"}};
    metadata["count"] = cloud.n;
    metadata["means"] = {
        {"mins",
         {transformed_min[0], transformed_min[1],
          transformed_min[2]}},
        {"maxs",
         {transformed_max[0], transformed_max[1],
          transformed_max[2]}},
        {"files", {"means_l.webp", "means_u.webp"}},
    };
    metadata["scales"] = {
        {"codebook", codebook_json(scale_quantization.codebook)},
        {"files", {"scales.webp"}},
    };
    metadata["quats"] = {{"files", {"quats.webp"}}};
    metadata["sh0"] = {
        {"codebook", codebook_json(dc_quantization.codebook)},
        {"files", {"sh0.webp"}},
    };
    if (cloud.sh_degree != 0) {
        metadata["shN"] = {
            {"count", palette_count},
            {"bands", cloud.sh_degree},
            {"codebook", codebook_json(shn_quantization.codebook)},
            {"files",
             {"shN_centroids.webp", "shN_labels.webp"}},
        };
    }
    encoded.metadata = metadata.dump();
    if (encoded.metadata.size() > kMetadataLimit)
        throw std::runtime_error(
            "sog: generated meta.json exceeds 1 MiB");
    return encoded;
}

std::string bundle_sog(const EncodedSog &encoded) {
    mz_zip_archive archive;
    std::memset(&archive, 0, sizeof(archive));
    if (!mz_zip_writer_init_heap(&archive, 0, 1 << 16))
        throw std::runtime_error(
            "sog: could not initialize ZIP writer");
    struct ZipGuard {
        mz_zip_archive *archive;
        ~ZipGuard() { mz_zip_end(archive); }
    } guard{&archive};

    std::tm fixed_tm{};
    fixed_tm.tm_year = 80;
    fixed_tm.tm_mon = 0;
    fixed_tm.tm_mday = 1;
    fixed_tm.tm_isdst = -1;
    MZ_TIME_T fixed_time = std::mktime(&fixed_tm);
    if (fixed_time == static_cast<MZ_TIME_T>(-1))
        throw std::runtime_error(
            "sog: could not construct deterministic ZIP time");

    uint64_t aggregate = 22;  // end-of-central-directory record
    const auto add = [&](const std::string &name, const void *data,
                         size_t size) {
        if (size > std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "sog: ZIP member exceeds 4 GiB");
        aggregate += size + 76 + static_cast<uint64_t>(name.size()) * 2;
        if (aggregate >= std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                "sog: ZIP output exceeds 4 GiB; use unbundled output");
        if (!mz_zip_writer_add_mem_ex_v2(
                &archive, name.c_str(), data, size, nullptr, 0,
                static_cast<mz_uint>(MZ_NO_COMPRESSION), 0, 0,
                &fixed_time, nullptr, 0, nullptr, 0))
            throw std::runtime_error(
                "sog: could not add ZIP member '" + name + "'");
    };

    for (const auto &[name, data] : encoded.layers)
        add(name, data.data(), data.size());
    add("meta.json", encoded.metadata.data(), encoded.metadata.size());

    void *raw = nullptr;
    size_t size = 0;
    if (!mz_zip_writer_finalize_heap_archive(&archive, &raw, &size))
        throw std::runtime_error(
            "sog: could not finalize ZIP archive");
    struct HeapGuard {
        void *value;
        ~HeapGuard() { mz_free(value); }
    } heap_guard{raw};
    return std::string(static_cast<const char *>(raw), size);
}

void write_file_exact(const fs::path &path, const uint8_t *data,
                      size_t size, const char *what) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output)
        throw std::invalid_argument(std::string("sog: cannot write ") +
                                    what);
    if (size != 0) {
        output.write(reinterpret_cast<const char *>(data),
                     static_cast<std::streamsize>(size));
        if (!output)
            throw std::invalid_argument(std::string("sog: failed writing ") +
                                        what);
    }
    output.close();
    if (!output)
        throw std::invalid_argument(std::string("sog: failed closing ") +
                                    what);
}

fs::path temporary_peer(const fs::path &target, size_t ordinal) {
    static std::atomic<uint64_t> sequence{0};
    const uint64_t seed =
        static_cast<uint64_t>(
            std::chrono::steady_clock::now().time_since_epoch().count()) ^
        sequence.fetch_add(1, std::memory_order_relaxed);
    for (size_t attempt = 0; attempt < 128; ++attempt) {
        const std::string suffix =
            ".sceneio-sog-" + std::to_string(seed) + "-" +
            std::to_string(ordinal) + "-" + std::to_string(attempt);
        fs::path candidate = target;
        candidate += fs::u8path(suffix);
        std::error_code error;
        const bool exists = fs::exists(candidate, error);
        if (!error && !exists) return candidate;
    }
    throw std::runtime_error(
        "sog: could not allocate a temporary output filename");
}

struct PendingFile {
    fs::path target;
    fs::path temporary;
    fs::path backup;
    bool had_original = false;
    bool installed = false;
};

void write_unbundled_transaction(const EncodedSog &encoded,
                                 const fs::path &metadata_path) {
    if (metadata_path.filename() != fs::u8path("meta.json"))
        throw std::invalid_argument(
            "sog: unbundled output path must end in meta.json");
    const fs::path parent = metadata_path.parent_path().empty()
                                ? fs::path(".")
                                : metadata_path.parent_path();
    std::error_code error;
    if (!fs::exists(parent, error)) {
        error.clear();
        if (!fs::create_directories(parent, error) && error)
            throw std::invalid_argument(
                "sog: could not create output directory");
    } else if (error || !fs::is_directory(parent, error) || error) {
        throw std::invalid_argument(
            "sog: output parent is not a directory");
    }

    std::vector<PendingFile> files;
    files.reserve(encoded.layers.size() + 1);
    for (const auto &[name, data] : encoded.layers) {
        (void)data;
        PendingFile pending;
        pending.target = parent / fs::u8path(name);
        pending.temporary =
            temporary_peer(pending.target, files.size());
        pending.backup =
            temporary_peer(pending.target, files.size() + 1000);
        files.push_back(std::move(pending));
    }
    PendingFile metadata;
    metadata.target = metadata_path;
    metadata.temporary =
        temporary_peer(metadata.target, files.size());
    metadata.backup =
        temporary_peer(metadata.target, files.size() + 1000);
    files.push_back(std::move(metadata));

    const auto cleanup_temporaries = [&]() noexcept {
        for (PendingFile &file : files) {
            std::error_code ignored;
            fs::remove(file.temporary, ignored);
        }
    };
    try {
        for (const PendingFile &file : files) {
            error.clear();
            if (fs::exists(file.target, error) &&
                !fs::is_regular_file(file.target, error))
                throw std::invalid_argument(
                    "sog: an output layer target is not a regular file");
            if (error)
                throw std::invalid_argument(
                    "sog: could not inspect an output layer target");
        }
        for (size_t i = 0; i < encoded.layers.size(); ++i) {
            const auto &[name, data] = encoded.layers[i];
            write_file_exact(files[i].temporary, data.data(), data.size(),
                             name.c_str());
        }
        write_file_exact(
            files.back().temporary,
            reinterpret_cast<const uint8_t *>(encoded.metadata.data()),
            encoded.metadata.size(), "meta.json");

        // Move every old target aside first, then install layers and meta last.
        // On any failure, remove installed new files and restore every backup.
        for (PendingFile &file : files) {
            error.clear();
            file.had_original = fs::exists(file.target, error);
            if (error)
                throw std::invalid_argument(
                    "sog: could not inspect existing output");
            if (file.had_original) {
                error.clear();
                fs::rename(file.target, file.backup, error);
                if (error)
                    throw std::invalid_argument(
                        "sog: could not stage existing output");
            }
        }
        for (PendingFile &file : files) {
            error.clear();
            fs::rename(file.temporary, file.target, error);
            if (error)
                throw std::invalid_argument(
                    "sog: could not install output file");
            file.installed = true;
        }
    } catch (...) {
        for (auto it = files.rbegin(); it != files.rend(); ++it) {
            std::error_code ignored;
            if (it->installed) fs::remove(it->target, ignored);
            if (it->had_original) {
                ignored.clear();
                fs::rename(it->backup, it->target, ignored);
            }
            ignored.clear();
            fs::remove(it->temporary, ignored);
        }
        throw;
    }

    for (PendingFile &file : files) {
        if (!file.had_original) continue;
        std::error_code ignored;
        fs::remove(file.backup, ignored);
    }
    cleanup_temporaries();
}

GaussianCloud read_sog_archive(const uint8_t *data, size_t size,
                               bool partial, size_t start, size_t stop) {
    ZipReader archive(data, size);
    const std::vector<uint8_t> metadata_bytes =
        archive.extract("meta.json", kMetadataLimit);
    const SogMetadata metadata =
        parse_metadata(metadata_bytes.data(), metadata_bytes.size());
    if (archive.names() != metadata.member_names())
        throw std::invalid_argument(
            "sog: ZIP members do not exactly match declared layers");
    auto load = [&](const std::string &name, size_t limit) {
        return archive.extract(name, limit);
    };
    return decode_sog(metadata, load, partial, start, stop);
}

fs::path normalize_metadata_path(const std::string &path) {
    fs::path result = fs::u8path(path);
    if (result.filename() != fs::u8path("meta.json"))
        result /= fs::u8path("meta.json");
    return result;
}

GaussianCloud read_sog_unbundled(const std::string &path, bool partial,
                                 size_t start, size_t stop) {
    const fs::path metadata_path = normalize_metadata_path(path);
    const std::vector<uint8_t> metadata_bytes =
        read_file_bounded(metadata_path, kMetadataLimit, "meta.json");
    const SogMetadata metadata =
        parse_metadata(metadata_bytes.data(), metadata_bytes.size());
    const fs::path parent = metadata_path.parent_path().empty()
                                ? fs::path(".")
                                : metadata_path.parent_path();
    auto load = [&](const std::string &name, size_t limit) {
        return read_file_bounded(parent / fs::u8path(name), limit,
                                 name.c_str());
    };
    return decode_sog(metadata, load, partial, start, stop);
}

GaussianCloud read_sog(nb::handle source) {
    ByteView view(source);
    GaussianCloud result;
    {
        nb::gil_scoped_release release;
        result = read_sog_archive(view.data(), view.size(), false, 0, 0);
    }
    return result;
}

GaussianCloud read_sog_points(nb::handle source, size_t start,
                              size_t stop) {
    ByteView view(source);
    GaussianCloud result;
    {
        nb::gil_scoped_release release;
        result =
            read_sog_archive(view.data(), view.size(), true, start, stop);
    }
    return result;
}

GaussianCloud read_sog_directory(const std::string &path) {
    GaussianCloud result;
    {
        nb::gil_scoped_release release;
        result = read_sog_unbundled(path, false, 0, 0);
    }
    return result;
}

GaussianCloud read_sog_directory_points(const std::string &path,
                                        size_t start, size_t stop) {
    GaussianCloud result;
    {
        nb::gil_scoped_release release;
        result = read_sog_unbundled(path, true, start, stop);
    }
    return result;
}

nb::bytes write_sog(const GaussianCloud &cloud) {
    std::string output;
    {
        nb::gil_scoped_release release;
        output = bundle_sog(encode_sog_layers(cloud));
    }
    return emit_bytes(output.data(), output.size());
}

void write_sog_directory(const GaussianCloud &cloud,
                         const std::string &path) {
    nb::gil_scoped_release release;
    const EncodedSog encoded = encode_sog_layers(cloud);
    write_unbundled_transaction(encoded, normalize_metadata_path(path));
}

nb::tuple inspect_sog_metadata(nb::handle source) {
    ByteView view(source);
    SogMetadata metadata;
    {
        nb::gil_scoped_release release;
        metadata = parse_metadata(view.data(), view.size());
    }
    const std::set<std::string> names_set = metadata.member_names();
    std::vector<std::string> names(names_set.begin(), names_set.end());
    return nb::make_tuple(metadata.count, metadata.bands, metadata.rest,
                          metadata.palette_count, names);
}

}  // namespace

void register_sog(nb::module_ &module) {
    module.def(
        "_inspect_sog_metadata", &inspect_sog_metadata, "data"_a,
        "Validate SOG v2 meta.json and return count, SH layout, palette "
        "count, and declared member names without decoding WebP layers.");
    module.def(
        "read_sog", &read_sog, "data"_a,
        "Decode a bundled PlayCanvas SOG v2 ZIP into GaussianCloud. "
        "Every declared texture must be lossless WebP with exact dimensions.");
    module.def(
        "read_sog_points", &read_sog_points, "data"_a, "start"_a,
        "stop"_a,
        "Decode one non-empty half-open point range from a bundled SOG v2 "
        "archive while allocating only the selected GaussianCloud rows.");
    module.def(
        "read_sog_directory", &read_sog_directory, "path"_a,
        "Decode an unbundled SOG v2 directory or its meta.json.");
    module.def(
        "read_sog_directory_points", &read_sog_directory_points,
        "path"_a, "start"_a, "stop"_a,
        "Decode one point range from an unbundled SOG v2 directory.");
    module.def(
        "write_sog", &write_sog, "cloud"_a,
        "Encode GaussianCloud as a deterministic bundled PlayCanvas SOG v2 "
        "archive. SOG quantization and Morton reordering are lossy.");
    module.def(
        "write_sog_directory", &write_sog_directory, "cloud"_a,
        "path"_a,
        "Transactionally encode GaussianCloud as unbundled SOG v2 layers "
        "beside meta.json.");
}
