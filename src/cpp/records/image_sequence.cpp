// records/image_sequence.cpp -- ImageSequence validation, factories, bindings.
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <limits>
#include <optional>
#include <string>
#include <unordered_set>
#include <utility>

#include "records/image_sequence.hpp"

using namespace nb::literals;

namespace {

constexpr size_t kSequenceStringLimit = 1024 * 1024;

using i64_array =
    nb::ndarray<const int64_t, nb::c_contig, nb::device::cpu>;
using u8_array =
    nb::ndarray<const uint8_t, nb::c_contig, nb::device::cpu>;
using any_array =
    nb::ndarray<nb::ro, nb::c_contig, nb::device::cpu>;

template <typename T>
nb::ndarray<nb::numpy, const T> sequence_view(
    const std::vector<T> &values, std::vector<size_t> shape) {
    static const T sentinel{};
    const T *data = values.empty() ? &sentinel : values.data();
    return nb::ndarray<nb::numpy, const T>(
        data, shape.size(), shape.data());
}

void validate_text(
    const std::string &value, const char *context) {
    if (value.empty())
        throw std::invalid_argument(
            std::string(context) + " must be non-empty");
    if (value.size() > kSequenceStringLimit)
        throw std::invalid_argument(
            std::string(context) + " exceeds 1 MiB");
    if (value.find('\0') != std::string::npos)
        throw std::invalid_argument(
            std::string(context) + " contains embedded NUL");
    if (!sio::valid_utf8(value))
        throw std::invalid_argument(
            std::string(context) + " must be valid UTF-8");
}

size_t checked_plane_size(
    size_t frames, size_t height, size_t width,
    const char *context) {
    if (height != 0 &&
        width > std::numeric_limits<size_t>::max() / height)
        throw std::length_error(
            std::string(context) + " plane shape overflows size_t");
    const size_t frame_size = height * width;
    if (frame_size != 0 &&
        frames > std::numeric_limits<size_t>::max() / frame_size)
        throw std::length_error(
            std::string(context) + " sequence extent overflows size_t");
    return frames * frame_size;
}

size_t checked_packed_size(
    size_t frames, size_t height, size_t width, size_t channels,
    const char *context) {
    const size_t plane =
        checked_plane_size(frames, height, width, context);
    if (plane != 0 &&
        channels > std::numeric_limits<size_t>::max() / plane)
        throw std::length_error(
            std::string(context) + " channel extent overflows size_t");
    return plane * channels;
}

void encode_strings(
    const std::vector<std::string> &values,
    std::vector<uint64_t> &offsets,
    std::vector<uint8_t> &utf8,
    const char *context) {
    offsets.clear();
    utf8.clear();
    offsets.reserve(values.size() + 1);
    offsets.push_back(0);
    for (const std::string &value : values) {
        validate_text(value, context);
        if (value.size() >
            std::numeric_limits<size_t>::max() - utf8.size())
            throw std::length_error(
                std::string(context) + " table is too large");
        utf8.insert(utf8.end(), value.begin(), value.end());
        offsets.push_back(static_cast<uint64_t>(utf8.size()));
    }
}

std::vector<std::string> decode_strings(
    const std::vector<uint64_t> &offsets,
    const std::vector<uint8_t> &utf8,
    const char *context) {
    if (offsets.empty()) return {};
    if (offsets.front() != 0 || offsets.back() != utf8.size())
        throw std::invalid_argument(
            std::string(context) + " string-table extent is malformed");
    const char *data = utf8.empty()
                           ? ""
                           : reinterpret_cast<const char *>(utf8.data());
    std::vector<std::string> values;
    values.reserve(offsets.size() - 1);
    for (size_t index = 0; index + 1 < offsets.size(); ++index) {
        const uint64_t begin = offsets[index];
        const uint64_t end = offsets[index + 1];
        if (begin > end || end > utf8.size())
            throw std::invalid_argument(
                std::string(context) +
                " string-table offsets are malformed");
        values.emplace_back(
            data + static_cast<size_t>(begin),
            static_cast<size_t>(end - begin));
    }
    return values;
}

void assign_timing(
    ImageSequence &sequence,
    const i64_array &timestamps,
    const i64_array &durations) {
    if (timestamps.ndim() != 1 || durations.ndim() != 1)
        throw std::invalid_argument(
            "image sequence: timing arrays must be one-dimensional int64");
    const size_t timestamp_count = timestamps.shape(0);
    const size_t duration_count = durations.shape(0);
    if (!((timestamp_count == 0 && duration_count == 0) ||
          (timestamp_count == sequence.n &&
           duration_count == sequence.n)))
        throw std::invalid_argument(
            "image sequence: timing arrays must both be empty or (N,)");
    if (sequence.n != 0 && timestamp_count != 0) {
        sequence.timestamps_ns.assign(
            timestamps.data(), timestamps.data() + sequence.n);
        sequence.durations_ns.assign(
            durations.data(), durations.data() + sequence.n);
    }
}

void assign_acquisition_timing(
    ImageSequence &sequence,
    const std::optional<i64_array> &exposure_durations_ns,
    const std::optional<i64_array> &readout_step_durations_ns,
    std::optional<std::vector<std::string>> readout_directions,
    const std::string &timestamp_reference) {
    const auto assign_optional = [&](
        const std::optional<i64_array> &source,
        std::vector<int64_t> &destination,
        const char *name) {
        if (!source) return;
        if (source->ndim() != 1)
            throw std::invalid_argument(
                std::string("image sequence: ") + name +
                " must be one-dimensional int64");
        const size_t count = source->shape(0);
        if (count != 0 && count != sequence.n)
            throw std::invalid_argument(
                std::string("image sequence: ") + name +
                " must be empty or (N,)");
        if (count != 0)
            destination.assign(source->data(), source->data() + count);
    };
    assign_optional(
        exposure_durations_ns, sequence.exposure_durations_ns,
        "exposure_durations_ns");
    assign_optional(
        readout_step_durations_ns,
        sequence.readout_step_durations_ns,
        "readout_step_durations_ns");
    if (readout_directions) {
        if (!readout_directions->empty() &&
            readout_directions->size() != sequence.n)
            throw std::invalid_argument(
                "image sequence: readout_directions must be empty or N");
        sequence.readout_directions = std::move(*readout_directions);
    }
    sequence.timestamp_reference = timestamp_reference;
}

ImageSequence make_path_sequence(
    const std::vector<std::string> &paths,
    const std::vector<std::string> &names,
    i64_array timestamps_ns,
    i64_array durations_ns,
    size_t height,
    size_t width,
    size_t channels,
    const std::string &frame_dtype,
    const std::string &color_space,
    const std::string &alpha_mode,
    std::optional<i64_array> exposure_durations_ns,
    std::optional<i64_array> readout_step_durations_ns,
    std::optional<std::vector<std::string>> readout_directions,
    const std::string &timestamp_reference) {
    if (paths.size() != names.size())
        throw std::invalid_argument(
            "image sequence: paths and names must have equal length");
    ImageSequence sequence;
    sequence.n = paths.size();
    sequence.height = height;
    sequence.width = width;
    sequence.channels = channels;
    sequence.frame_dtype = frame_dtype;
    sequence.color_space = color_space;
    sequence.alpha_mode = alpha_mode;
    assign_image_sequence_paths(sequence, paths);
    assign_image_sequence_names(sequence, names);
    assign_timing(sequence, timestamps_ns, durations_ns);
    assign_acquisition_timing(
        sequence, exposure_durations_ns, readout_step_durations_ns,
        std::move(readout_directions), timestamp_reference);
    validate_image_sequence(sequence);
    return sequence;
}

ImageSequence make_yuv_sequence(
    u8_array y,
    std::optional<u8_array> u,
    std::optional<u8_array> v,
    i64_array timestamps_ns,
    i64_array durations_ns,
    const std::string &chroma_subsampling,
    const std::string &chroma_siting,
    const std::string &color_range,
    const std::string &matrix,
    const std::string &interlace,
    uint32_t frame_rate_numerator,
    uint32_t frame_rate_denominator,
    uint32_t pixel_aspect_numerator,
    uint32_t pixel_aspect_denominator,
    std::optional<i64_array> exposure_durations_ns,
    std::optional<i64_array> readout_step_durations_ns,
    std::optional<std::vector<std::string>> readout_directions,
    const std::string &timestamp_reference) {
    if (y.ndim() != 3)
        throw std::invalid_argument(
            "image sequence: Y plane must be (N,H,W) uint8");
    ImageSequence sequence;
    sequence.storage_mode = "yuv_planar";
    sequence.n = y.shape(0);
    sequence.height = y.shape(1);
    sequence.width = y.shape(2);
    sequence.channels = chroma_subsampling == "mono" ? 1 : 3;
    sequence.frame_dtype = "uint8";
    sequence.color_space =
        chroma_subsampling == "mono" ? "gray" : "ycbcr";
    sequence.chroma_subsampling = chroma_subsampling;
    sequence.chroma_siting = chroma_siting;
    sequence.color_range = color_range;
    sequence.matrix = matrix;
    sequence.interlace = interlace;
    sequence.frame_rate_numerator = frame_rate_numerator;
    sequence.frame_rate_denominator = frame_rate_denominator;
    sequence.pixel_aspect_numerator = pixel_aspect_numerator;
    sequence.pixel_aspect_denominator = pixel_aspect_denominator;

    if (chroma_subsampling != "mono" &&
        chroma_subsampling != "420" &&
        chroma_subsampling != "422" &&
        chroma_subsampling != "444")
        throw std::invalid_argument(
            "image sequence: chroma_subsampling must be mono|420|422|444");
    const size_t y_count = checked_plane_size(
        sequence.n, sequence.height, sequence.width,
        "image sequence Y");
    if (y_count != 0)
        sequence.y.assign(
            y.data(), y.data() + y_count);
    if (chroma_subsampling == "mono") {
        if (u || v)
            throw std::invalid_argument(
                "image sequence: monochrome storage cannot carry U/V planes");
    } else {
        if (!u || !v || u->ndim() != 3 || v->ndim() != 3)
            throw std::invalid_argument(
                "image sequence: color YUV requires (N,Hc,Wc) U/V planes");
        sequence.chroma_width =
            chroma_subsampling == "444"
                ? sequence.width
                : (sequence.width + 1) / 2;
        sequence.chroma_height =
            chroma_subsampling == "420"
                ? (sequence.height + 1) / 2
                : sequence.height;
        const auto matches = [&](const u8_array &plane) {
            return plane.shape(0) == sequence.n &&
                   plane.shape(1) == sequence.chroma_height &&
                   plane.shape(2) == sequence.chroma_width;
        };
        if (!matches(*u) || !matches(*v))
            throw std::invalid_argument(
                "image sequence: U/V plane shapes disagree with chroma layout");
        const size_t count = checked_plane_size(
            sequence.n, sequence.chroma_height,
            sequence.chroma_width, "image sequence chroma");
        if (count != 0) {
            sequence.u.assign(u->data(), u->data() + count);
            sequence.v.assign(v->data(), v->data() + count);
        }
    }
    assign_timing(sequence, timestamps_ns, durations_ns);
    assign_acquisition_timing(
        sequence, exposure_durations_ns, readout_step_durations_ns,
        std::move(readout_directions), timestamp_reference);
    validate_image_sequence(sequence);
    return sequence;
}

ImageSequence make_packed_sequence(
    any_array pixels,
    i64_array timestamps_ns,
    i64_array durations_ns,
    const std::string &color_space,
    const std::string &alpha_mode,
    std::optional<uint32_t> maxval,
    std::optional<uint32_t> loop_count,
    std::optional<u8_array> background_rgba,
    std::optional<i64_array> exposure_durations_ns,
    std::optional<i64_array> readout_step_durations_ns,
    std::optional<std::vector<std::string>> readout_directions,
    const std::string &timestamp_reference) {
    if (pixels.ndim() != 3 && pixels.ndim() != 4)
        throw std::invalid_argument(
            "image sequence: packed pixels must be (N,H,W) or (N,H,W,C)");
    ImageSequence sequence;
    sequence.storage_mode = "packed";
    sequence.n = pixels.shape(0);
    sequence.height = pixels.shape(1);
    sequence.width = pixels.shape(2);
    sequence.channels = pixels.ndim() == 3 ? 1 : pixels.shape(3);
    sequence.color_space = color_space;
    sequence.alpha_mode = alpha_mode;
    const size_t count = checked_packed_size(
        sequence.n, sequence.height, sequence.width,
        sequence.channels, "image sequence packed pixels");

    if (pixels.dtype() == nb::dtype<uint8_t>()) {
        sequence.frame_dtype = "uint8";
        sequence.maxval = maxval.value_or(255);
        const auto *data =
            static_cast<const uint8_t *>(pixels.data());
        if (count != 0)
            sequence.pixels_u8.assign(data, data + count);
    } else if (pixels.dtype() == nb::dtype<uint16_t>()) {
        sequence.frame_dtype = "uint16";
        sequence.maxval = maxval.value_or(65535);
        const auto *data =
            static_cast<const uint16_t *>(pixels.data());
        if (count != 0)
            sequence.pixels_u16.assign(data, data + count);
    } else if (pixels.dtype() == nb::dtype<float>()) {
        sequence.frame_dtype = "float32";
        sequence.maxval = maxval.value_or(0);
        const auto *data =
            static_cast<const float *>(pixels.data());
        if (count != 0)
            sequence.pixels_f32.assign(data, data + count);
    } else {
        throw std::invalid_argument(
            "image sequence: packed dtype must be uint8, uint16, or float32");
    }
    if (loop_count) {
        sequence.loop_count_present = true;
        sequence.loop_count = *loop_count;
    }
    if (background_rgba) {
        if (background_rgba->ndim() != 1 ||
            background_rgba->shape(0) != 4)
            throw std::invalid_argument(
                "image sequence: background_rgba must be (4,) uint8");
        sequence.background_present = true;
        std::copy_n(
            background_rgba->data(), 4,
            sequence.background_rgba.begin());
    }
    assign_timing(sequence, timestamps_ns, durations_ns);
    assign_acquisition_timing(
        sequence, exposure_durations_ns, readout_step_durations_ns,
        std::move(readout_directions), timestamp_reference);
    validate_image_sequence(sequence);
    return sequence;
}

}  // namespace

std::vector<std::string> image_sequence_paths(
    const ImageSequence &sequence) {
    return decode_strings(
        sequence.path_offsets, sequence.path_utf8,
        "image sequence paths");
}

std::vector<std::string> image_sequence_names(
    const ImageSequence &sequence) {
    return decode_strings(
        sequence.name_offsets, sequence.name_utf8,
        "image sequence names");
}

void assign_image_sequence_paths(
    ImageSequence &sequence,
    const std::vector<std::string> &values) {
    encode_strings(
        values, sequence.path_offsets, sequence.path_utf8,
        "image sequence path");
}

void assign_image_sequence_names(
    ImageSequence &sequence,
    const std::vector<std::string> &values) {
    encode_strings(
        values, sequence.name_offsets, sequence.name_utf8,
        "image sequence name");
}

void validate_image_sequence(
    const ImageSequence &sequence, const char *context) {
    const std::string prefix = std::string(context) + ": ";
    if ((sequence.height == 0) != (sequence.width == 0))
        throw std::invalid_argument(
            prefix + "height and width must both be zero or both positive");
    if (sequence.n != 0 &&
        (sequence.height == 0 || sequence.width == 0))
        throw std::invalid_argument(
            prefix + "nonempty sequences require positive dimensions");
    if (sequence.frame_dtype != "uint8" &&
        sequence.frame_dtype != "uint16" &&
        sequence.frame_dtype != "float32")
        throw std::invalid_argument(
            prefix + "frame_dtype must be uint8|uint16|float32");
    if (sequence.color_space != "srgb" &&
        sequence.color_space != "linear" &&
        sequence.color_space != "gray" &&
        sequence.color_space != "ycbcr" &&
        sequence.color_space != "unknown")
        throw std::invalid_argument(
            prefix + "unsupported color_space");
    if (sequence.alpha_mode != "none" &&
        sequence.alpha_mode != "straight" &&
        sequence.alpha_mode != "premultiplied")
        throw std::invalid_argument(
            prefix + "unsupported alpha_mode");
    if ((sequence.alpha_mode == "none") !=
        (sequence.channels != 4))
        throw std::invalid_argument(
            prefix + "alpha_mode and channel count disagree");
    const bool timing_empty =
        sequence.timestamps_ns.empty() &&
        sequence.durations_ns.empty();
    if (!timing_empty &&
        (sequence.timestamps_ns.size() != sequence.n ||
         sequence.durations_ns.size() != sequence.n))
        throw std::invalid_argument(
            prefix + "timing arrays must both be empty or N");
    for (size_t index = 0;
         index < sequence.timestamps_ns.size(); ++index) {
        if (sequence.timestamps_ns[index] < 0 ||
            sequence.durations_ns[index] <= 0)
            throw std::invalid_argument(
                prefix + "timestamps must be nonnegative and durations positive");
        if (index != 0 &&
            sequence.timestamps_ns[index] <=
                sequence.timestamps_ns[index - 1])
            throw std::invalid_argument(
                prefix + "timestamps must be strictly increasing");
    }

    if (sequence.timestamp_reference != "unknown" &&
        sequence.timestamp_reference != "exposure_start" &&
        sequence.timestamp_reference != "exposure_midpoint" &&
        sequence.timestamp_reference != "exposure_end")
        throw std::invalid_argument(
            prefix + "timestamp_reference must be unknown|exposure_start|"
                     "exposure_midpoint|exposure_end");
    if (!sequence.has_timing() &&
        sequence.timestamp_reference != "unknown")
        throw std::invalid_argument(
            prefix + "timestamp_reference requires frame timing");
    if (!sequence.exposure_durations_ns.empty() &&
        sequence.exposure_durations_ns.size() != sequence.n)
        throw std::invalid_argument(
            prefix + "exposure_durations_ns must be empty or N");
    for (int64_t duration : sequence.exposure_durations_ns)
        if (duration < 0)
            throw std::invalid_argument(
                prefix + "exposure durations must be nonnegative");

    const bool acquisition_arrays =
        !sequence.exposure_durations_ns.empty() ||
        !sequence.readout_step_durations_ns.empty() ||
        !sequence.readout_directions.empty();
    if (acquisition_arrays &&
        (!sequence.has_timing() ||
         sequence.timestamp_reference == "unknown"))
        throw std::invalid_argument(
            prefix + "acquisition timing requires frame timing and a "
                     "declared timestamp_reference");
    for (int64_t duration : sequence.readout_step_durations_ns)
        if (duration < 0)
            throw std::invalid_argument(
                prefix + "readout step durations must be nonnegative");
    if (sequence.readout_directions.empty()) {
        if (!sequence.readout_step_durations_ns.empty())
            throw std::invalid_argument(
                prefix + "readout step durations require directions");
    } else {
        if (sequence.readout_directions.size() != sequence.n)
            throw std::invalid_argument(
                prefix + "readout_directions must be empty or N");
        bool has_global = false;
        bool has_rolling = false;
        for (const std::string &direction :
             sequence.readout_directions) {
            if (direction == "global") {
                has_global = true;
            } else if (
                direction == "top_to_bottom" ||
                direction == "bottom_to_top" ||
                direction == "left_to_right" ||
                direction == "right_to_left") {
                has_rolling = true;
            } else {
                throw std::invalid_argument(
                    prefix + "readout direction must be global|"
                             "top_to_bottom|bottom_to_top|left_to_right|"
                             "right_to_left");
            }
        }
        if (has_global && has_rolling)
            throw std::invalid_argument(
                prefix + "mixed global/rolling acquisition requires "
                         "separate ImageSequence records");
        if (has_global && !sequence.readout_step_durations_ns.empty())
            throw std::invalid_argument(
                prefix + "global readout must omit step durations");
        if (has_rolling &&
            sequence.readout_step_durations_ns.size() != sequence.n)
            throw std::invalid_argument(
                prefix + "rolling readout requires N step durations");
        if (has_rolling) {
            for (size_t index = 0; index < sequence.n; ++index) {
                const std::string &direction =
                    sequence.readout_directions[index];
                const bool vertical =
                    direction == "top_to_bottom" ||
                    direction == "bottom_to_top";
                const uint64_t steps = static_cast<uint64_t>(
                    (vertical ? sequence.height : sequence.width) - 1);
                const uint64_t step_duration = static_cast<uint64_t>(
                    sequence.readout_step_durations_ns[index]);
                if (step_duration != 0 &&
                    steps > std::numeric_limits<uint64_t>::max() /
                                step_duration)
                    throw std::invalid_argument(
                        prefix + "readout timing equation overflows int64 "
                                 "nanoseconds");
                const uint64_t delta = steps * step_duration;
                const int64_t timestamp = sequence.timestamps_ns[index];
                const bool positive =
                    direction == "top_to_bottom" ||
                    direction == "left_to_right";
                const uint64_t capacity = positive
                    ? static_cast<uint64_t>(
                          std::numeric_limits<int64_t>::max() - timestamp)
                    : static_cast<uint64_t>(timestamp) +
                          static_cast<uint64_t>(
                              std::numeric_limits<int64_t>::max()) +
                          uint64_t{1};
                if (delta > capacity)
                    throw std::invalid_argument(
                        prefix + "readout timing equation overflows int64 "
                                 "nanoseconds");
            }
        }
    }

    if (sequence.storage_mode == "encoded_paths") {
        if (sequence.channels != 1 &&
            sequence.channels != 3 &&
            sequence.channels != 4)
            throw std::invalid_argument(
                prefix + "encoded frames require 1, 3, or 4 channels");
        if (sequence.path_offsets.size() != sequence.n + 1 ||
            sequence.name_offsets.size() != sequence.n + 1)
            throw std::invalid_argument(
                prefix + "path/name tables must contain N strings");
        const auto paths = image_sequence_paths(sequence);
        const auto names = image_sequence_names(sequence);
        std::unordered_set<std::string> unique_names;
        for (const std::string &value : paths)
            validate_text(value, "image sequence path");
        for (const std::string &value : names) {
            validate_text(value, "image sequence name");
            if (!unique_names.insert(value).second)
                throw std::invalid_argument(
                    prefix + "frame names must be unique");
        }
        if (!sequence.pixels_u8.empty() ||
            !sequence.pixels_u16.empty() ||
            !sequence.pixels_f32.empty() ||
            !sequence.y.empty() || !sequence.u.empty() ||
            !sequence.v.empty())
            throw std::invalid_argument(
                prefix + "encoded-path storage cannot carry pixel planes");
        if (sequence.chroma_subsampling != "none" ||
            sequence.chroma_siting != "none")
            throw std::invalid_argument(
                prefix + "encoded-path storage has no planar chroma layout");
        if (sequence.loop_count_present ||
            sequence.background_present)
            throw std::invalid_argument(
                prefix + "encoded-path storage cannot carry animation controls");
        return;
    }
    if (sequence.storage_mode == "packed") {
        if (!sequence.path_offsets.empty() ||
            !sequence.name_offsets.empty() ||
            !sequence.path_utf8.empty() ||
            !sequence.name_utf8.empty() ||
            !sequence.y.empty() || !sequence.u.empty() ||
            !sequence.v.empty())
            throw std::invalid_argument(
                prefix + "packed storage cannot carry paths or YUV planes");
        if (sequence.channels != 1 &&
            sequence.channels != 3 &&
            sequence.channels != 4)
            throw std::invalid_argument(
                prefix + "packed frames require 1, 3, or 4 channels");
        if (sequence.chroma_width != 0 ||
            sequence.chroma_height != 0 ||
            sequence.chroma_subsampling != "none" ||
            sequence.chroma_siting != "none")
            throw std::invalid_argument(
                prefix + "packed storage has no planar chroma layout");
        const size_t expected = checked_packed_size(
            sequence.n, sequence.height, sequence.width,
            sequence.channels, "image sequence packed pixels");
        const bool u8 =
            sequence.frame_dtype == "uint8" &&
            sequence.pixels_u8.size() == expected &&
            sequence.pixels_u16.empty() &&
            sequence.pixels_f32.empty();
        const bool u16 =
            sequence.frame_dtype == "uint16" &&
            sequence.pixels_u8.empty() &&
            sequence.pixels_u16.size() == expected &&
            sequence.pixels_f32.empty();
        const bool f32 =
            sequence.frame_dtype == "float32" &&
            sequence.pixels_u8.empty() &&
            sequence.pixels_u16.empty() &&
            sequence.pixels_f32.size() == expected;
        if (!u8 && !u16 && !f32)
            throw std::invalid_argument(
                prefix + "packed pixel extent disagrees with dtype/shape");
        if ((u8 && (sequence.maxval < 1 || sequence.maxval > 255)) ||
            (u16 &&
             (sequence.maxval < 1 || sequence.maxval > 65535)) ||
            (f32 && sequence.maxval != 0))
            throw std::invalid_argument(
                prefix + "packed maxval disagrees with frame dtype");
        return;
    }
    if (sequence.storage_mode != "yuv_planar")
        throw std::invalid_argument(
            prefix + "storage_mode must be encoded_paths|packed|yuv_planar");
    if (!sequence.path_offsets.empty() ||
        !sequence.name_offsets.empty() ||
        !sequence.path_utf8.empty() ||
        !sequence.name_utf8.empty())
        throw std::invalid_argument(
            prefix + "planar storage cannot carry frame paths");
    if (sequence.frame_dtype != "uint8")
        throw std::invalid_argument(
            prefix + "the supported planar tier is uint8");
    if (!sequence.pixels_u8.empty() ||
        !sequence.pixels_u16.empty() ||
        !sequence.pixels_f32.empty())
        throw std::invalid_argument(
            prefix + "planar storage cannot carry packed pixels");
    if (sequence.maxval != 255)
        throw std::invalid_argument(
            prefix + "uint8 planar storage requires maxval 255");
    if (sequence.loop_count_present ||
        sequence.background_present)
        throw std::invalid_argument(
            prefix + "planar storage cannot carry animation controls");
    if (sequence.y.size() != checked_plane_size(
            sequence.n, sequence.height, sequence.width,
            "image sequence Y"))
        throw std::invalid_argument(
            prefix + "Y plane extent disagrees with sequence shape");
    if (sequence.chroma_subsampling == "mono") {
        if (sequence.channels != 1 ||
            sequence.chroma_width != 0 ||
            sequence.chroma_height != 0 ||
            !sequence.u.empty() || !sequence.v.empty() ||
            sequence.chroma_siting != "none")
            throw std::invalid_argument(
                prefix + "monochrome planar metadata is inconsistent");
    } else {
        if (sequence.chroma_subsampling != "420" &&
            sequence.chroma_subsampling != "422" &&
            sequence.chroma_subsampling != "444")
            throw std::invalid_argument(
                prefix + "chroma_subsampling must be mono|420|422|444");
        const size_t expected_width =
            sequence.chroma_subsampling == "444"
                ? sequence.width
                : (sequence.width + 1) / 2;
        const size_t expected_height =
            sequence.chroma_subsampling == "420"
                ? (sequence.height + 1) / 2
                : sequence.height;
        const size_t expected = checked_plane_size(
            sequence.n, expected_height, expected_width,
            "image sequence chroma");
        if (sequence.channels != 3 ||
            sequence.chroma_width != expected_width ||
            sequence.chroma_height != expected_height ||
            sequence.u.size() != expected ||
            sequence.v.size() != expected)
            throw std::invalid_argument(
                prefix + "color planar extents disagree with chroma layout");
        if (sequence.chroma_siting != "jpeg" &&
            sequence.chroma_siting != "mpeg2" &&
            sequence.chroma_siting != "paldv" &&
            sequence.chroma_siting != "unspecified")
            throw std::invalid_argument(
                prefix + "unsupported chroma_siting");
    }
    if (sequence.color_range != "unknown" &&
        sequence.color_range != "limited" &&
        sequence.color_range != "full")
        throw std::invalid_argument(
            prefix + "color_range must be unknown|limited|full");
    if (sequence.matrix != "unknown" &&
        sequence.matrix != "bt601" &&
        sequence.matrix != "bt709" &&
        sequence.matrix != "bt2020")
        throw std::invalid_argument(
            prefix + "matrix must be unknown|bt601|bt709|bt2020");
    if (sequence.interlace != "progressive" &&
        sequence.interlace != "top_field_first" &&
        sequence.interlace != "bottom_field_first" &&
        sequence.interlace != "unknown")
        throw std::invalid_argument(
            prefix + "unsupported interlace mode");
    if (sequence.frame_rate_denominator == 0 ||
        (sequence.frame_rate_numerator == 0 &&
         sequence.frame_rate_denominator != 1))
        throw std::invalid_argument(
            prefix + "frame-rate rational is malformed");
    if ((sequence.pixel_aspect_numerator == 0) !=
        (sequence.pixel_aspect_denominator == 0))
        throw std::invalid_argument(
            prefix + "pixel-aspect rational must be 0:0 or positive");
}

void require_no_image_sequence_acquisition(
    const ImageSequence &sequence, const char *context) {
    if (sequence.has_acquisition_timing())
        throw std::invalid_argument(
            std::string(context) +
            ": acquisition timing metadata is not representable");
}

void register_image_sequence(nb::module_ &module) {
    const auto internal = nb::rv_policy::reference_internal;
    nb::class_<ImageSequence>(module, "ImageSequence")
        .def_prop_ro("num_frames", [](const ImageSequence &v) { return v.n; })
        .def_ro("height", &ImageSequence::height)
        .def_ro("width", &ImageSequence::width)
        .def_ro("channels", &ImageSequence::channels)
        .def_ro("chroma_height", &ImageSequence::chroma_height)
        .def_ro("chroma_width", &ImageSequence::chroma_width)
        .def_ro("storage_mode", &ImageSequence::storage_mode)
        .def_ro("frame_dtype", &ImageSequence::frame_dtype)
        .def_ro("color_space", &ImageSequence::color_space)
        .def_ro("alpha_mode", &ImageSequence::alpha_mode)
        .def_ro("chroma_subsampling", &ImageSequence::chroma_subsampling)
        .def_ro("chroma_siting", &ImageSequence::chroma_siting)
        .def_ro("color_range", &ImageSequence::color_range)
        .def_ro("matrix", &ImageSequence::matrix)
        .def_ro("interlace", &ImageSequence::interlace)
        .def_ro("maxval", &ImageSequence::maxval)
        .def_ro("frame_rate_numerator", &ImageSequence::frame_rate_numerator)
        .def_ro("frame_rate_denominator", &ImageSequence::frame_rate_denominator)
        .def_ro("pixel_aspect_numerator", &ImageSequence::pixel_aspect_numerator)
        .def_ro("pixel_aspect_denominator", &ImageSequence::pixel_aspect_denominator)
        .def_prop_ro("has_timing", [](const ImageSequence &v) {
            return v.has_timing();
        })
        .def_prop_ro("has_exposure_timing", [](const ImageSequence &v) {
            return v.has_exposure_timing();
        })
        .def_prop_ro("has_readout_timing", [](const ImageSequence &v) {
            return v.has_readout_timing();
        })
        .def_prop_ro("has_acquisition_timing", [](const ImageSequence &v) {
            return v.has_acquisition_timing();
        })
        .def_prop_ro("has_paths", [](const ImageSequence &v) {
            return v.has_paths();
        })
        .def_prop_ro("has_pixels", [](const ImageSequence &v) {
            return v.has_pixels();
        })
        .def_prop_ro("has_chroma", [](const ImageSequence &v) {
            return v.has_chroma();
        })
        .def_prop_ro("has_loop_count", [](const ImageSequence &v) {
            return v.loop_count_present;
        })
        .def_ro("loop_count", &ImageSequence::loop_count)
        .def_prop_ro("has_background", [](const ImageSequence &v) {
            return v.background_present;
        })
        .def_prop_ro(
            "background_rgba",
            [](nb::handle_t<ImageSequence> self) {
                const ImageSequence &v =
                    nb::cast<const ImageSequence &>(self);
                return sio::view<const uint8_t>(
                    self, v.background_rgba.data(),
                    std::vector<size_t>{4});
            })
        .def_prop_ro("frame_paths", &image_sequence_paths)
        .def_prop_ro("frame_names", &image_sequence_names)
        .def_prop_ro(
            "timestamps_ns",
            [](const ImageSequence &v) {
                return sequence_view(v.timestamps_ns, {v.timestamps_ns.size()});
            },
            internal)
        .def_prop_ro(
            "durations_ns",
            [](const ImageSequence &v) {
                return sequence_view(v.durations_ns, {v.durations_ns.size()});
            },
            internal)
        .def_prop_ro(
            "exposure_durations_ns",
            [](const ImageSequence &v) {
                return sequence_view(
                    v.exposure_durations_ns,
                    {v.exposure_durations_ns.size()});
            },
            internal)
        .def_prop_ro(
            "readout_step_durations_ns",
            [](const ImageSequence &v) {
                return sequence_view(
                    v.readout_step_durations_ns,
                    {v.readout_step_durations_ns.size()});
            },
            internal)
        .def_prop_ro(
            "readout_directions",
            [](const ImageSequence &v) {
                return v.readout_directions;
            })
        .def_ro(
            "timestamp_reference",
            &ImageSequence::timestamp_reference)
        .def_prop_ro(
            "acquisition_timing_convention",
            [](const ImageSequence &) {
                return "coordinate_reference_ns = frame_timestamp_ns + "
                       "direction_sign * step_index * "
                       "readout_step_duration_ns";
            })
        .def_prop_ro(
            "pixels",
            [](nb::handle_t<ImageSequence> self) -> nb::object {
                const ImageSequence &v =
                    nb::cast<const ImageSequence &>(self);
                if (v.storage_mode != "packed")
                    return nb::cast(sequence_view<uint8_t>(
                        v.pixels_u8, {0, 0, 0}));
                std::vector<size_t> shape =
                    v.channels == 1
                        ? std::vector<size_t>{
                              v.n, v.height, v.width}
                        : std::vector<size_t>{
                              v.n, v.height, v.width, v.channels};
                if (v.frame_dtype == "uint8")
                    return nb::cast(sio::view<const uint8_t>(
                        self, v.pixels_u8.data(), shape));
                if (v.frame_dtype == "uint16")
                    return nb::cast(sio::view<const uint16_t>(
                        self, v.pixels_u16.data(), shape));
                return nb::cast(sio::view<const float>(
                    self, v.pixels_f32.data(), shape));
            })
        .def_prop_ro(
            "y",
            [](const ImageSequence &v) {
                return v.storage_mode == "yuv_planar"
                           ? sequence_view(
                                 v.y, {v.n, v.height, v.width})
                           : sequence_view<uint8_t>(
                                 v.y, {0, 0, 0});
            },
            internal)
        .def_prop_ro(
            "u",
            [](const ImageSequence &v) {
                return v.storage_mode == "yuv_planar"
                           ? sequence_view(
                                 v.u,
                                 {v.n, v.chroma_height, v.chroma_width})
                           : sequence_view<uint8_t>(
                                 v.u, {0, 0, 0});
            },
            internal)
        .def_prop_ro(
            "v",
            [](const ImageSequence &value) {
                return value.storage_mode == "yuv_planar"
                           ? sequence_view(
                                 value.v,
                                 {value.n, value.chroma_height,
                                  value.chroma_width})
                           : sequence_view<uint8_t>(
                                 value.v, {0, 0, 0});
            },
            internal)
        .def(
            "__repr__",
            [](const ImageSequence &v) {
                return "<ImageSequence n=" + std::to_string(v.n) +
                       " shape=(" + std::to_string(v.height) + "," +
                       std::to_string(v.width) + ") " +
                       v.storage_mode + ">";
            });

    module.def(
        "image_sequence_paths", &make_path_sequence,
        "paths"_a, "names"_a, "timestamps_ns"_a, "durations_ns"_a,
        "height"_a, "width"_a, "channels"_a,
        "frame_dtype"_a = "uint8",
        "color_space"_a = "unknown",
        "alpha_mode"_a = "none",
        nb::kw_only(),
        "exposure_durations_ns"_a = nb::none(),
        "readout_step_durations_ns"_a = nb::none(),
        "readout_directions"_a = nb::none(),
        "timestamp_reference"_a = "unknown",
        "Build a lazy ImageSequence from owned UTF-8 frame references and "
        "optional exact int64 nanosecond timing.");
    module.def(
        "image_sequence_packed", &make_packed_sequence,
        "pixels"_a, "timestamps_ns"_a, "durations_ns"_a,
        "color_space"_a = "srgb",
        "alpha_mode"_a = "none",
        "maxval"_a = nb::none(),
        "loop_count"_a = nb::none(),
        "background_rgba"_a = nb::none(),
        nb::kw_only(),
        "exposure_durations_ns"_a = nb::none(),
        "readout_step_durations_ns"_a = nb::none(),
        "readout_directions"_a = nb::none(),
        "timestamp_reference"_a = "unknown",
        "Build an owned packed gray/RGB/RGBA ImageSequence from "
        "(N,H,W)/(N,H,W,C) uint8/uint16/float32 samples, with exact "
        "timing and optional APNG/WebP loop/background metadata.");
    module.def(
        "image_sequence_yuv", &make_yuv_sequence,
        "y"_a, "u"_a = nb::none(), "v"_a = nb::none(),
        "timestamps_ns"_a, "durations_ns"_a,
        "chroma_subsampling"_a = "420",
        "chroma_siting"_a = "jpeg",
        "color_range"_a = "unknown",
        "matrix"_a = "unknown",
        "interlace"_a = "progressive",
        "frame_rate_numerator"_a = 0,
        "frame_rate_denominator"_a = 1,
        "pixel_aspect_numerator"_a = 0,
        "pixel_aspect_denominator"_a = 0,
        nb::kw_only(),
        "exposure_durations_ns"_a = nb::none(),
        "readout_step_durations_ns"_a = nb::none(),
        "readout_directions"_a = nb::none(),
        "timestamp_reference"_a = "unknown",
        "Build an owned uint8 planar-YUV ImageSequence without converting "
        "to RGB.");
}
