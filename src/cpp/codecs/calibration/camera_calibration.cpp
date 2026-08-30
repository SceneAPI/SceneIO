// codecs/calibration/camera_calibration.cpp -- OpenCV, ROS CameraInfo, and Kalibr.
//
// These formats share YAML-shaped data but not a common schema.  The parser
// below intentionally implements only the bounded mapping/list subset used by
// those schemas (plus OpenCV's !!opencv-matrix tag).  It is not a general YAML
// parser: aliases, arbitrary tags, flow mappings, and implicit type coercion
// are rejected instead of being guessed.
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "fast_float/fast_float.h"
#include "records/camera_rig.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kDocumentLimit = 16 * 1024 * 1024;
constexpr size_t kLineLimit = 1024 * 1024;
constexpr size_t kNodeLimit = 10000;
constexpr size_t kCameraLimit = 4096;

std::string_view trim(std::string_view value) {
    while (!value.empty() &&
           (value.front() == ' ' || value.front() == '\t' ||
            value.front() == '\r' || value.front() == '\n'))
        value.remove_prefix(1);
    while (!value.empty() &&
           (value.back() == ' ' || value.back() == '\t' ||
            value.back() == '\r' || value.back() == '\n'))
        value.remove_suffix(1);
    return value;
}

void reject_bad_document(
    const uint8_t *bytes, size_t size, const char *format) {
    if (size == 0)
        throw std::invalid_argument(
            std::string(format) + ": empty document");
    if (size > kDocumentLimit)
        throw std::invalid_argument(
            std::string(format) + ": document exceeds 16 MiB");
    if (std::memchr(bytes, '\0', size))
        throw std::invalid_argument(
            std::string(format) + ": NUL byte in text document");
    const std::string_view text(
        reinterpret_cast<const char *>(bytes), size);
    if (!sio::valid_utf8(text))
        throw std::invalid_argument(
            std::string(format) +
            ": text document is not valid UTF-8");
}

std::vector<std::string_view> split_lines(
    const uint8_t *bytes, size_t size, const char *format) {
    std::vector<std::string_view> lines;
    const char *cursor = reinterpret_cast<const char *>(bytes);
    const char *const end = cursor + size;
    while (cursor < end) {
        const size_t remaining = static_cast<size_t>(end - cursor);
        const size_t search = std::min(remaining, kLineLimit + 1);
        const void *found = std::memchr(cursor, '\n', search);
        if (!found && remaining > kLineLimit)
            throw std::invalid_argument(
                std::string(format) + ": line exceeds 1 MiB");
        const char *line_end =
            found ? static_cast<const char *>(found) : end;
        if (static_cast<size_t>(line_end - cursor) > kLineLimit)
            throw std::invalid_argument(
                std::string(format) + ": line exceeds 1 MiB");
        lines.emplace_back(
            cursor, static_cast<size_t>(line_end - cursor));
        cursor = found ? line_end + 1 : end;
    }
    return lines;
}

int bracket_balance(std::string_view value) {
    int balance = 0;
    char quote = '\0';
    for (size_t index = 0; index < value.size(); ++index) {
        const char c = value[index];
        if (quote != '\0') {
            if (c == quote) {
                if (quote == '\'' && index + 1 < value.size() &&
                    value[index + 1] == '\'') {
                    ++index;
                } else if (
                    quote != '"' || index == 0 ||
                    value[index - 1] != '\\') {
                    quote = '\0';
                }
            }
            continue;
        }
        if (c == '\'' || c == '"')
            quote = c;
        else if (c == '[')
            ++balance;
        else if (c == ']')
            --balance;
        if (balance < 0)
            throw std::invalid_argument(
                "calibration YAML: unmatched closing bracket");
    }
    return balance;
}

std::string_view strip_yaml_comment(std::string_view value) {
    char quote = '\0';
    int brackets = 0;
    for (size_t index = 0; index < value.size(); ++index) {
        const char c = value[index];
        if (quote != '\0') {
            if (c == quote) {
                if (quote == '\'' && index + 1 < value.size() &&
                    value[index + 1] == '\'') {
                    ++index;
                } else if (
                    quote != '"' || index == 0 ||
                    value[index - 1] != '\\') {
                    quote = '\0';
                }
            }
            continue;
        }
        if (c == '\'' || c == '"') {
            quote = c;
        } else if (c == '[') {
            ++brackets;
        } else if (c == ']') {
            --brackets;
        } else if (c == '#' && brackets == 0) {
            return value.substr(0, index);
        }
    }
    return value;
}

size_t mapping_colon(std::string_view value) {
    char quote = '\0';
    int brackets = 0;
    for (size_t index = 0; index < value.size(); ++index) {
        const char c = value[index];
        if (quote != '\0') {
            if (c == quote) {
                if (quote == '\'' && index + 1 < value.size() &&
                    value[index + 1] == '\'') {
                    ++index;
                } else if (
                    quote != '"' || index == 0 ||
                    value[index - 1] != '\\') {
                    quote = '\0';
                }
            }
            continue;
        }
        if (c == '\'' || c == '"')
            quote = c;
        else if (c == '[')
            ++brackets;
        else if (c == ']')
            --brackets;
        else if (c == ':' && brackets == 0)
            return index;
    }
    return std::string_view::npos;
}

bool valid_key(std::string_view key) {
    if (key.empty()) return false;
    for (char c : key)
        if (!((c >= 'a' && c <= 'z') ||
              (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_'))
            return false;
    return true;
}

struct FlatYaml {
    std::unordered_map<std::string, std::string> scalars;
    std::unordered_map<std::string, std::vector<std::string>>
        sequences;
    std::unordered_set<std::string> opencv_matrices;
    std::unordered_set<std::string> declared;
    std::vector<std::string> top_level;
};

template <typename Container, typename Key>
bool has_key(const Container &container, const Key &key) {
    return container.find(key) != container.end();
}

FlatYaml parse_yaml(
    const uint8_t *bytes, size_t size, const char *format,
    bool require_opencv_header = false) {
    reject_bad_document(bytes, size, format);
    const auto lines = split_lines(bytes, size, format);
    struct Parent {
        size_t indent;
        std::string path;
    };
    std::vector<Parent> parents;
    FlatYaml result;
    size_t nodes = 0;
    bool saw_opencv_header = false;

    for (size_t line_index = 0; line_index < lines.size();
         ++line_index) {
        std::string_view raw_line = lines[line_index];
        if (!raw_line.empty() && raw_line.back() == '\r')
            raw_line.remove_suffix(1);
        size_t indent = 0;
        while (indent < raw_line.size() &&
               raw_line[indent] == ' ')
            ++indent;
        if (indent < raw_line.size() &&
            raw_line[indent] == '\t')
            throw std::invalid_argument(
                std::string(format) +
                ": tab indentation is not supported");
        std::string_view line =
            trim(strip_yaml_comment(raw_line.substr(indent)));
        if (line.empty() || line == "---" || line == "...")
            continue;
        if (line == "%YAML:1.0" || line == "%YAML 1.0") {
            saw_opencv_header = true;
            continue;
        }
        if (!line.empty() && line.front() == '%')
            throw std::invalid_argument(
                std::string(format) +
                ": unsupported YAML directive");

        if (line.front() == '-') {
            if (line.size() == 1 || line[1] != ' ' ||
                parents.empty())
                throw std::invalid_argument(
                    std::string(format) +
                    ": unsupported YAML sequence");
            std::string value(trim(line.substr(2)));
            if (value.empty())
                throw std::invalid_argument(
                    std::string(format) +
                    ": empty YAML sequence item");
            if (bracket_balance(value) != 0)
                throw std::invalid_argument(
                    std::string(format) +
                    ": multiline sequence rows are not supported");
            auto &sequence =
                result.sequences[parents.back().path];
            if (has_key(result.scalars, parents.back().path))
                throw std::invalid_argument(
                    std::string(format) +
                    ": node is both scalar and sequence");
            sequence.push_back(std::move(value));
            if (++nodes > kNodeLimit)
                throw std::invalid_argument(
                    std::string(format) +
                    ": document has too many nodes");
            continue;
        }

        while (!parents.empty() &&
               indent <= parents.back().indent)
            parents.pop_back();
        const size_t colon = mapping_colon(line);
        if (colon == std::string_view::npos)
            throw std::invalid_argument(
                std::string(format) +
                ": expected a mapping key");
        const std::string_view key = trim(line.substr(0, colon));
        if (!valid_key(key))
            throw std::invalid_argument(
                std::string(format) +
                ": invalid or unsupported mapping key");
        const std::string path =
            parents.empty()
                ? std::string(key)
                : parents.back().path + "." + std::string(key);
        if (!result.declared.insert(path).second)
            throw std::invalid_argument(
                std::string(format) +
                ": duplicate mapping key " + path);
        if (indent == 0)
            result.top_level.emplace_back(key);

        std::string value(
            trim(strip_yaml_comment(line.substr(colon + 1))));
        int balance = bracket_balance(value);
        while (balance > 0) {
            if (++line_index >= lines.size())
                throw std::invalid_argument(
                    std::string(format) +
                    ": unterminated inline list");
            std::string_view continuation =
                trim(strip_yaml_comment(lines[line_index]));
            value += ' ';
            value.append(continuation);
            balance = bracket_balance(value);
        }
        if (balance != 0)
            throw std::invalid_argument(
                std::string(format) +
                ": malformed inline list");

        if (value.empty() || value == "!!opencv-matrix") {
            if (value == "!!opencv-matrix")
                result.opencv_matrices.insert(path);
            parents.push_back({indent, path});
        } else {
            if (value.find("!!") != std::string::npos ||
                value.front() == '&' || value.front() == '*')
                throw std::invalid_argument(
                    std::string(format) +
                    ": unsupported YAML tag or alias");
            result.scalars.emplace(path, std::move(value));
        }
        if (++nodes > kNodeLimit)
            throw std::invalid_argument(
                std::string(format) +
                ": document has too many nodes");
    }
    if (require_opencv_header && !saw_opencv_header)
        throw std::invalid_argument(
            std::string(format) +
            ": missing %YAML:1.0 header");
    return result;
}

const std::string &required(
    const FlatYaml &document, const std::string &path,
    const char *format) {
    const auto found = document.scalars.find(path);
    if (found == document.scalars.end())
        throw std::invalid_argument(
            std::string(format) + ": missing " + path);
    return found->second;
}

const std::string *optional(
    const FlatYaml &document, const std::string &path) {
    const auto found = document.scalars.find(path);
    return found == document.scalars.end() ? nullptr : &found->second;
}

uint64_t parse_uint(
    std::string_view value, const std::string &what,
    const char *format) {
    value = trim(value);
    uint64_t parsed = 0;
    const auto result = std::from_chars(
        value.data(), value.data() + value.size(), parsed);
    if (value.empty() || result.ec != std::errc{} ||
        result.ptr != value.data() + value.size())
        throw std::invalid_argument(
            std::string(format) + ": invalid unsigned integer " +
            what);
    return parsed;
}

double parse_double(
    std::string_view value, const std::string &what,
    const char *format) {
    value = trim(value);
    double parsed = 0.0;
    const auto result = fast_float::from_chars(
        value.data(), value.data() + value.size(), parsed);
    if (value.empty() || result.ec != std::errc{} ||
        result.ptr != value.data() + value.size() ||
        !std::isfinite(parsed))
        throw std::invalid_argument(
            std::string(format) +
            ": invalid or non-finite numeric value in " + what);
    return parsed;
}

std::string parse_string(
    std::string_view value, const std::string &what,
    const char *format) {
    value = trim(value);
    if (value.empty())
        throw std::invalid_argument(
            std::string(format) + ": empty scalar " + what);
    std::string output;
    if (value.front() == '\'' || value.front() == '"') {
        const char quote = value.front();
        if (value.size() < 2 || value.back() != quote)
            throw std::invalid_argument(
                std::string(format) +
                ": unterminated quoted scalar " + what);
        for (size_t index = 1; index + 1 < value.size(); ++index) {
            const char c = value[index];
            if (quote == '\'' && c == '\'' &&
                index + 2 < value.size() &&
                value[index + 1] == '\'') {
                output += '\'';
                ++index;
            } else if (
                quote == '"' && c == '\\' &&
                index + 2 < value.size()) {
                const char escaped = value[++index];
                if (escaped == '"' || escaped == '\\')
                    output += escaped;
                else if (escaped == 'n')
                    output += '\n';
                else
                    throw std::invalid_argument(
                        std::string(format) +
                        ": unsupported quoted escape in " + what);
            } else {
                output += c;
            }
        }
    } else {
        output.assign(value);
    }
    for (unsigned char c : output)
        if (c < 0x20)
            throw std::invalid_argument(
                std::string(format) +
                ": control character in " + what);
    return output;
}

bool parse_bool(
    std::string_view value, const std::string &what,
    const char *format) {
    value = trim(value);
    if (value == "true" || value == "True" || value == "1")
        return true;
    if (value == "false" || value == "False" || value == "0")
        return false;
    throw std::invalid_argument(
        std::string(format) + ": invalid boolean " + what);
}

std::vector<std::string_view> list_tokens(
    std::string_view value, const std::string &what,
    const char *format, bool require_brackets = true) {
    value = trim(value);
    if (require_brackets) {
        if (value.size() < 2 || value.front() != '[' ||
            value.back() != ']')
            throw std::invalid_argument(
                std::string(format) +
                ": expected inline list in " + what);
        value = trim(value.substr(1, value.size() - 2));
    }
    std::vector<std::string_view> tokens;
    if (value.empty()) return tokens;
    size_t start = 0;
    while (start <= value.size()) {
        const size_t comma = value.find(',', start);
        const size_t end =
            comma == std::string_view::npos ? value.size() : comma;
        const std::string_view token =
            trim(value.substr(start, end - start));
        if (token.empty())
            throw std::invalid_argument(
                std::string(format) +
                ": empty list element in " + what);
        tokens.push_back(token);
        if (comma == std::string_view::npos) break;
        start = comma + 1;
    }
    return tokens;
}

std::vector<double> parse_numeric_list(
    std::string_view value, const std::string &what,
    const char *format, bool require_brackets = true) {
    const auto tokens =
        list_tokens(value, what, format, require_brackets);
    std::vector<double> values;
    values.reserve(tokens.size());
    for (std::string_view token : tokens)
        values.push_back(parse_double(token, what, format));
    return values;
}

std::vector<double> yaml_numbers(
    const FlatYaml &document, const std::string &path,
    const char *format) {
    if (const std::string *value = optional(document, path))
        return parse_numeric_list(*value, path, format);
    const auto sequence = document.sequences.find(path);
    if (sequence == document.sequences.end())
        throw std::invalid_argument(
            std::string(format) + ": missing " + path);
    std::vector<double> values;
    for (const std::string &row : sequence->second) {
        auto parsed = parse_numeric_list(row, path, format);
        values.insert(values.end(), parsed.begin(), parsed.end());
    }
    return values;
}

std::vector<double> yaml_matrix(
    const FlatYaml &document, const std::string &path,
    size_t expected_rows, size_t expected_columns,
    const char *format, bool require_opencv_tag) {
    if (require_opencv_tag &&
        !has_key(document.opencv_matrices, path))
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " must be !!opencv-matrix");
    const uint64_t rows = parse_uint(
        required(document, path + ".rows", format),
        path + ".rows", format);
    const uint64_t columns = parse_uint(
        required(document, path + ".cols", format),
        path + ".cols", format);
    if (rows != expected_rows || columns != expected_columns)
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " has the wrong matrix shape");
    if (require_opencv_tag) {
        const std::string dt = parse_string(
            required(document, path + ".dt", format),
            path + ".dt", format);
        if (dt != "d" && dt != "f")
            throw std::invalid_argument(
                std::string(format) + ": " + path +
                " supports only scalar float/double matrices");
    }
    auto values = yaml_numbers(document, path + ".data", format);
    if (values.size() != expected_rows * expected_columns)
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " data length does not match its shape");
    return values;
}

std::vector<double> yaml_dynamic_matrix(
    const FlatYaml &document, const std::string &path,
    const char *format, bool require_opencv_tag) {
    if (require_opencv_tag &&
        !has_key(document.opencv_matrices, path))
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " must be !!opencv-matrix");
    const uint64_t rows = parse_uint(
        required(document, path + ".rows", format),
        path + ".rows", format);
    const uint64_t columns = parse_uint(
        required(document, path + ".cols", format),
        path + ".cols", format);
    if (rows > kNodeLimit || columns > kNodeLimit ||
        (rows != 0 &&
         columns > std::numeric_limits<size_t>::max() / rows))
        throw std::invalid_argument(
            std::string(format) + ": matrix extent is too large");
    if (require_opencv_tag) {
        const std::string dt = parse_string(
            required(document, path + ".dt", format),
            path + ".dt", format);
        if (dt != "d" && dt != "f")
            throw std::invalid_argument(
                std::string(format) + ": " + path +
                " supports only scalar float/double matrices");
    }
    auto values = yaml_numbers(document, path + ".data", format);
    if (values.size() != rows * columns)
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " data length does not match its shape");
    return values;
}

CameraRig empty_rig(size_t count) {
    if (count > kCameraLimit)
        throw std::invalid_argument(
            "camera calibration: camera count exceeds 4096");
    CameraRig rig;
    rig.n = count;
    rig.camera_ids.resize(count);
    rig.resolutions.assign(count * 2, 0);
    rig.names.resize(count);
    rig.projection_models.resize(count);
    rig.intrinsic_offsets.assign(count + 1, 0);
    rig.distortion_models.resize(count);
    rig.distortion_offsets.assign(count + 1, 0);
    rig.quaternions.assign(count * 4, 0.0);
    rig.translations.assign(count * 3, 0.0);
    rig.has_extrinsics.assign(count, 0);
    rig.camera_matrices.assign(count * 9, 0.0);
    rig.has_camera_matrix.assign(count, 0);
    rig.rectification_matrices.assign(count * 9, 0.0);
    rig.has_rectification.assign(count, 0);
    rig.projection_matrices.assign(count * 12, 0.0);
    rig.has_projection_matrix.assign(count, 0);
    rig.binning.assign(count * 2, 0);
    rig.roi.assign(count * 4, 0);
    rig.roi_do_rectify.assign(count, 0);
    rig.has_operational.assign(count, 0);
    rig.topics.resize(count);
    rig.time_offsets.assign(count, 0.0);
    rig.has_time_offset.assign(count, 0);
    for (size_t index = 0; index < count; ++index) {
        rig.camera_ids[index] = static_cast<uint32_t>(index);
        rig.names[index] = "camera" + std::to_string(index);
        rig.quaternions[index * 4] = 1.0;
    }
    return rig;
}

void append_ragged(
    std::vector<uint64_t> &offsets, std::vector<double> &target,
    size_t index, const std::vector<double> &values) {
    target.insert(target.end(), values.begin(), values.end());
    offsets[index + 1] = static_cast<uint64_t>(target.size());
}

void set_matrix(
    std::vector<double> &target, std::vector<uint8_t> &mask,
    size_t index, size_t extent, const std::vector<double> &values) {
    if (values.size() != extent)
        throw std::logic_error("calibration matrix extent mismatch");
    std::copy(
        values.begin(), values.end(),
        target.begin() + static_cast<std::ptrdiff_t>(index * extent));
    mask[index] = 1;
}

std::vector<double> pinhole_intrinsics(
    const std::vector<double> &matrix) {
    return {matrix[0], matrix[4], matrix[2], matrix[5]};
}

CameraRig decode_opencv_yaml(
    const uint8_t *bytes, size_t size) {
    constexpr const char *format = "OpenCV YAML";
    const FlatYaml document =
        parse_yaml(bytes, size, format, true);
    CameraRig rig = empty_rig(1);
    rig.resolutions[0] = parse_uint(
        required(document, "image_width", format),
        "image_width", format);
    rig.resolutions[1] = parse_uint(
        required(document, "image_height", format),
        "image_height", format);
    if (const std::string *name =
            optional(document, "camera_name"))
        rig.names[0] = parse_string(*name, "camera_name", format);
    rig.projection_models[0] = "pinhole";
    const auto camera_matrix = yaml_matrix(
        document, "camera_matrix", 3, 3, format, true);
    append_ragged(
        rig.intrinsic_offsets, rig.intrinsics, 0,
        pinhole_intrinsics(camera_matrix));
    set_matrix(
        rig.camera_matrices, rig.has_camera_matrix, 0, 9,
        camera_matrix);
    rig.distortion_models[0] =
        optional(document, "distortion_model")
            ? parse_string(
                  *optional(document, "distortion_model"),
                  "distortion_model", format)
            : "opencv";
    append_ragged(
        rig.distortion_offsets, rig.distortion_coefficients, 0,
        yaml_dynamic_matrix(
            document, "distortion_coefficients", format, true));
    if (has_key(document.declared, "rectification_matrix"))
        set_matrix(
            rig.rectification_matrices, rig.has_rectification,
            0, 9,
            yaml_matrix(
                document, "rectification_matrix", 3, 3,
                format, true));
    if (has_key(document.declared, "projection_matrix"))
        set_matrix(
            rig.projection_matrices,
            rig.has_projection_matrix, 0, 12,
            yaml_matrix(
                document, "projection_matrix", 3, 4,
                format, true));
    validate_camera_rig(rig, format);
    return rig;
}

std::string_view xml_element(
    std::string_view scope, std::string_view tag,
    const char *format, bool required_value = true) {
    const std::string opening = "<" + std::string(tag);
    const std::string closing = "</" + std::string(tag) + ">";
    size_t start = scope.find(opening);
    while (start != std::string_view::npos) {
        const size_t delimiter = start + opening.size();
        if (delimiter < scope.size() &&
            (scope[delimiter] == '>' ||
             scope[delimiter] == ' ' ||
             scope[delimiter] == '\t' ||
             scope[delimiter] == '\r' ||
             scope[delimiter] == '\n'))
            break;
        start = scope.find(opening, start + 1);
    }
    if (start == std::string_view::npos) {
        if (!required_value) return {};
        throw std::invalid_argument(
            std::string(format) + ": missing XML element " +
            std::string(tag));
    }
    const size_t open_end = scope.find('>', start + opening.size());
    if (open_end == std::string_view::npos ||
        (open_end > start && scope[open_end - 1] == '/'))
        throw std::invalid_argument(
            std::string(format) + ": malformed XML element " +
            std::string(tag));
    const size_t end = scope.find(closing, open_end + 1);
    if (end == std::string_view::npos)
        throw std::invalid_argument(
            std::string(format) + ": unterminated XML element " +
            std::string(tag));
    if (scope.find(opening, end + closing.size()) !=
        std::string_view::npos)
        throw std::invalid_argument(
            std::string(format) + ": duplicate XML element " +
            std::string(tag));
    return scope.substr(open_end + 1, end - open_end - 1);
}

bool has_xml_element(
    std::string_view scope, std::string_view tag) {
    const std::string opening = "<" + std::string(tag);
    size_t start = scope.find(opening);
    while (start != std::string_view::npos) {
        const size_t delimiter = start + opening.size();
        if (delimiter < scope.size() &&
            (scope[delimiter] == '>' ||
             scope[delimiter] == ' ' ||
             scope[delimiter] == '\t' ||
             scope[delimiter] == '\r' ||
             scope[delimiter] == '\n'))
            return true;
        start = scope.find(opening, start + 1);
    }
    return false;
}

std::string_view xml_opening_header(
    std::string_view scope, std::string_view tag,
    const char *format) {
    const std::string opening = "<" + std::string(tag);
    size_t start = scope.find(opening);
    while (start != std::string_view::npos) {
        const size_t delimiter = start + opening.size();
        if (delimiter < scope.size() &&
            (scope[delimiter] == '>' ||
             scope[delimiter] == ' ' ||
             scope[delimiter] == '\t' ||
             scope[delimiter] == '\r' ||
             scope[delimiter] == '\n'))
            break;
        start = scope.find(opening, start + 1);
    }
    if (start == std::string_view::npos)
        throw std::invalid_argument(
            std::string(format) + ": missing XML element " +
            std::string(tag));
    const size_t end = scope.find('>', start + opening.size());
    if (end == std::string_view::npos)
        throw std::invalid_argument(
            std::string(format) + ": malformed XML element " +
            std::string(tag));
    return scope.substr(start, end - start + 1);
}

std::string_view xml_document_root(
    const uint8_t *bytes, size_t size, const char *format) {
    std::string_view document(
        reinterpret_cast<const char *>(bytes), size);
    if (document.size() >= 3 &&
        static_cast<uint8_t>(document[0]) == 0xef &&
        static_cast<uint8_t>(document[1]) == 0xbb &&
        static_cast<uint8_t>(document[2]) == 0xbf)
        document.remove_prefix(3);
    document = trim(document);
    if (document.substr(0, 5) == "<?xml") {
        const size_t end = document.find("?>");
        if (end == std::string_view::npos)
            throw std::invalid_argument(
                std::string(format) +
                ": unterminated XML declaration");
        document = trim(document.substr(end + 2));
    }
    if (document.find("<!DOCTYPE") != std::string_view::npos ||
        document.find("<![CDATA[") != std::string_view::npos ||
        document.find("<!--") != std::string_view::npos ||
        document.find("<?") != std::string_view::npos)
        throw std::invalid_argument(
            std::string(format) +
            ": unsupported XML declaration or node");
    constexpr std::string_view opening = "<opencv_storage";
    if (document.substr(0, opening.size()) != opening ||
        (document.size() > opening.size() &&
         document[opening.size()] != '>' &&
         document[opening.size()] != ' ' &&
         document[opening.size()] != '\t' &&
         document[opening.size()] != '\r' &&
         document[opening.size()] != '\n'))
        throw std::invalid_argument(
            std::string(format) +
            ": opencv_storage must be the document root");
    constexpr std::string_view closing = "</opencv_storage>";
    const size_t close = document.rfind(closing);
    if (close == std::string_view::npos ||
        !trim(document.substr(close + closing.size())).empty())
        throw std::invalid_argument(
            std::string(format) +
            ": trailing content after opencv_storage");
    return xml_element(document, "opencv_storage", format);
}

std::string xml_unescape(
    std::string_view value, const std::string &what,
    const char *format) {
    value = trim(value);
    std::string output;
    output.reserve(value.size());
    for (size_t index = 0; index < value.size(); ++index) {
        if (value[index] != '&') {
            output += value[index];
            continue;
        }
        const size_t semicolon = value.find(';', index + 1);
        if (semicolon == std::string_view::npos)
            throw std::invalid_argument(
                std::string(format) +
                ": malformed XML entity in " + what);
        const std::string_view entity =
            value.substr(index, semicolon - index + 1);
        if (entity == "&amp;")
            output += '&';
        else if (entity == "&lt;")
            output += '<';
        else if (entity == "&gt;")
            output += '>';
        else if (entity == "&quot;")
            output += '"';
        else if (entity == "&apos;")
            output += '\'';
        else
            throw std::invalid_argument(
                std::string(format) +
                ": unsupported XML entity in " + what);
        index = semicolon;
    }
    if (output.empty())
        throw std::invalid_argument(
            std::string(format) + ": empty XML scalar " + what);
    for (unsigned char character : output)
        if (character < 0x20)
            throw std::invalid_argument(
                std::string(format) +
                ": control character in " + what);
    return output;
}

std::vector<double> xml_number_list(
    std::string_view value, const std::string &what,
    const char *format) {
    value = trim(value);
    std::vector<double> output;
    size_t start = 0;
    while (start < value.size()) {
        while (start < value.size() &&
               (value[start] == ' ' || value[start] == '\t' ||
                value[start] == '\r' || value[start] == '\n' ||
                value[start] == ','))
            ++start;
        if (start == value.size()) break;
        size_t end = start;
        while (end < value.size() &&
               value[end] != ' ' && value[end] != '\t' &&
               value[end] != '\r' && value[end] != '\n' &&
               value[end] != ',')
            ++end;
        output.push_back(
            parse_double(value.substr(start, end - start), what, format));
        start = end;
    }
    return output;
}

std::vector<double> xml_matrix(
    std::string_view root, const std::string &path,
    size_t expected_rows, size_t expected_columns,
    const char *format) {
    const std::string_view header =
        xml_opening_header(root, path, format);
    if (header.find("type_id=\"opencv-matrix\"") ==
            std::string_view::npos &&
        header.find("type_id='opencv-matrix'") ==
            std::string_view::npos)
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " must have type_id=\"opencv-matrix\"");
    const std::string_view node =
        xml_element(root, path, format);
    const uint64_t rows = parse_uint(
        xml_element(node, "rows", format),
        path + ".rows", format);
    const uint64_t columns = parse_uint(
        xml_element(node, "cols", format),
        path + ".cols", format);
    const std::string dt = xml_unescape(
        xml_element(node, "dt", format), path + ".dt", format);
    if (rows != expected_rows || columns != expected_columns)
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " has the wrong matrix shape");
    if (dt != "d" && dt != "f")
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " supports only scalar float/double matrices");
    auto values = xml_number_list(
        xml_element(node, "data", format), path + ".data", format);
    if (values.size() != rows * columns)
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " data length does not match its shape");
    return values;
}

std::vector<double> xml_dynamic_matrix(
    std::string_view root, const std::string &path,
    const char *format) {
    const std::string_view header =
        xml_opening_header(root, path, format);
    if (header.find("type_id=\"opencv-matrix\"") ==
            std::string_view::npos &&
        header.find("type_id='opencv-matrix'") ==
            std::string_view::npos)
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " must have type_id=\"opencv-matrix\"");
    const std::string_view node =
        xml_element(root, path, format);
    const uint64_t rows = parse_uint(
        xml_element(node, "rows", format),
        path + ".rows", format);
    const uint64_t columns = parse_uint(
        xml_element(node, "cols", format),
        path + ".cols", format);
    const std::string dt = xml_unescape(
        xml_element(node, "dt", format), path + ".dt", format);
    if (rows > kNodeLimit || columns > kNodeLimit ||
        (rows != 0 &&
         columns > std::numeric_limits<size_t>::max() / rows))
        throw std::invalid_argument(
            std::string(format) + ": matrix extent is too large");
    if (dt != "d" && dt != "f")
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " supports only scalar float/double matrices");
    auto values = xml_number_list(
        xml_element(node, "data", format), path + ".data", format);
    if (values.size() != rows * columns)
        throw std::invalid_argument(
            std::string(format) + ": " + path +
            " data length does not match its shape");
    return values;
}

CameraRig decode_opencv_xml(
    const uint8_t *bytes, size_t size) {
    constexpr const char *format = "OpenCV XML";
    reject_bad_document(bytes, size, format);
    const std::string_view root =
        xml_document_root(bytes, size, format);
    CameraRig rig = empty_rig(1);
    rig.resolutions[0] = parse_uint(
        xml_element(root, "image_width", format),
        "image_width", format);
    rig.resolutions[1] = parse_uint(
        xml_element(root, "image_height", format),
        "image_height", format);
    if (has_xml_element(root, "camera_name"))
        rig.names[0] = xml_unescape(
            xml_element(root, "camera_name", format),
            "camera_name", format);
    rig.projection_models[0] = "pinhole";
    const auto camera_matrix =
        xml_matrix(root, "camera_matrix", 3, 3, format);
    append_ragged(
        rig.intrinsic_offsets, rig.intrinsics, 0,
        pinhole_intrinsics(camera_matrix));
    set_matrix(
        rig.camera_matrices, rig.has_camera_matrix, 0, 9,
        camera_matrix);
    rig.distortion_models[0] =
        has_xml_element(root, "distortion_model")
            ? xml_unescape(
                  xml_element(root, "distortion_model", format),
                  "distortion_model", format)
            : "opencv";
    append_ragged(
        rig.distortion_offsets, rig.distortion_coefficients, 0,
        xml_dynamic_matrix(
            root, "distortion_coefficients", format));
    if (has_xml_element(root, "rectification_matrix"))
        set_matrix(
            rig.rectification_matrices, rig.has_rectification,
            0, 9,
            xml_matrix(
                root, "rectification_matrix", 3, 3, format));
    if (has_xml_element(root, "projection_matrix"))
        set_matrix(
            rig.projection_matrices,
            rig.has_projection_matrix, 0, 12,
            xml_matrix(
                root, "projection_matrix", 3, 4, format));
    validate_camera_rig(rig, format);
    return rig;
}

CameraRig decode_ros_camera_info(
    const uint8_t *bytes, size_t size) {
    constexpr const char *format = "ROS camera_info";
    const FlatYaml document =
        parse_yaml(bytes, size, format);
    CameraRig rig = empty_rig(1);
    rig.resolutions[0] = parse_uint(
        required(document, "image_width", format),
        "image_width", format);
    rig.resolutions[1] = parse_uint(
        required(document, "image_height", format),
        "image_height", format);
    if (const std::string *name =
            optional(document, "camera_name"))
        rig.names[0] = parse_string(*name, "camera_name", format);
    rig.projection_models[0] = "pinhole";
    const auto camera_matrix = yaml_matrix(
        document, "camera_matrix", 3, 3, format, false);
    append_ragged(
        rig.intrinsic_offsets, rig.intrinsics, 0,
        pinhole_intrinsics(camera_matrix));
    set_matrix(
        rig.camera_matrices, rig.has_camera_matrix, 0, 9,
        camera_matrix);
    rig.distortion_models[0] = parse_string(
        required(document, "distortion_model", format),
        "distortion_model", format);
    append_ragged(
        rig.distortion_offsets, rig.distortion_coefficients, 0,
        yaml_dynamic_matrix(
            document, "distortion_coefficients", format, false));
    set_matrix(
        rig.rectification_matrices, rig.has_rectification, 0, 9,
        yaml_matrix(
            document, "rectification_matrix", 3, 3,
            format, false));
    set_matrix(
        rig.projection_matrices, rig.has_projection_matrix, 0, 12,
        yaml_matrix(
            document, "projection_matrix", 3, 4,
            format, false));
    rig.has_operational[0] = 1;
    if (const std::string *value =
            optional(document, "binning_x")) {
        const uint64_t parsed =
            parse_uint(*value, "binning_x", format);
        if (parsed > std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                std::string(format) +
                ": binning_x exceeds uint32");
        rig.binning[0] = static_cast<uint32_t>(parsed);
    }
    if (const std::string *value =
            optional(document, "binning_y")) {
        const uint64_t parsed =
            parse_uint(*value, "binning_y", format);
        if (parsed > std::numeric_limits<uint32_t>::max())
            throw std::invalid_argument(
                std::string(format) +
                ": binning_y exceeds uint32");
        rig.binning[1] = static_cast<uint32_t>(parsed);
    }
    const std::array<std::string, 4> roi_names = {
        "roi.x_offset", "roi.y_offset",
        "roi.width", "roi.height"};
    for (size_t index = 0; index < roi_names.size(); ++index)
        if (const std::string *value =
                optional(document, roi_names[index])) {
            const uint64_t parsed =
                parse_uint(*value, roi_names[index], format);
            if (parsed > std::numeric_limits<uint32_t>::max())
                throw std::invalid_argument(
                    std::string(format) +
                    ": ROI value exceeds uint32");
            rig.roi[index] = static_cast<uint32_t>(parsed);
        }
    if (const std::string *value =
            optional(document, "roi.do_rectify"))
        rig.roi_do_rectify[0] = static_cast<uint8_t>(
            parse_bool(*value, "roi.do_rectify", format));
    validate_camera_rig(rig, format);
    return rig;
}

struct RigidTransform {
    std::array<double, 9> rotation{};
    std::array<double, 3> translation{};
};

RigidTransform parse_transform(
    const std::vector<double> &values, const std::string &what,
    const char *format) {
    if (values.size() != 16)
        throw std::invalid_argument(
            std::string(format) + ": " + what +
            " must be a 4x4 matrix");
    const double tolerance = 1e-8;
    if (std::abs(values[12]) > tolerance ||
        std::abs(values[13]) > tolerance ||
        std::abs(values[14]) > tolerance ||
        std::abs(values[15] - 1.0) > tolerance)
        throw std::invalid_argument(
            std::string(format) + ": " + what +
            " has a non-homogeneous final row");
    RigidTransform transform;
    for (size_t row = 0; row < 3; ++row) {
        for (size_t column = 0; column < 3; ++column)
            transform.rotation[row * 3 + column] =
                values[row * 4 + column];
        transform.translation[row] = values[row * 4 + 3];
    }
    for (size_t row = 0; row < 3; ++row)
        for (size_t column = 0; column < 3; ++column) {
            double dot = 0.0;
            for (size_t k = 0; k < 3; ++k)
                dot += transform.rotation[row * 3 + k] *
                       transform.rotation[column * 3 + k];
            const double expected = row == column ? 1.0 : 0.0;
            if (std::abs(dot - expected) > 1e-6)
                throw std::invalid_argument(
                    std::string(format) + ": " + what +
                    " rotation is not orthonormal");
        }
    const auto &r = transform.rotation;
    const double determinant =
        r[0] * (r[4] * r[8] - r[5] * r[7]) -
        r[1] * (r[3] * r[8] - r[5] * r[6]) +
        r[2] * (r[3] * r[7] - r[4] * r[6]);
    if (std::abs(determinant - 1.0) > 1e-6)
        throw std::invalid_argument(
            std::string(format) + ": " + what +
            " rotation determinant is not +1");
    return transform;
}

RigidTransform compose(
    const RigidTransform &left,
    const RigidTransform &right) {
    RigidTransform result;
    for (size_t row = 0; row < 3; ++row) {
        for (size_t column = 0; column < 3; ++column) {
            result.rotation[row * 3 + column] = 0.0;
            for (size_t k = 0; k < 3; ++k)
                result.rotation[row * 3 + column] +=
                    left.rotation[row * 3 + k] *
                    right.rotation[k * 3 + column];
        }
        result.translation[row] = left.translation[row];
        for (size_t k = 0; k < 3; ++k)
            result.translation[row] +=
                left.rotation[row * 3 + k] *
                right.translation[k];
    }
    return result;
}

RigidTransform inverse(const RigidTransform &value) {
    RigidTransform result;
    for (size_t row = 0; row < 3; ++row)
        for (size_t column = 0; column < 3; ++column)
            result.rotation[row * 3 + column] =
                value.rotation[column * 3 + row];
    for (size_t row = 0; row < 3; ++row) {
        result.translation[row] = 0.0;
        for (size_t k = 0; k < 3; ++k)
            result.translation[row] -=
                result.rotation[row * 3 + k] *
                value.translation[k];
    }
    return result;
}

std::array<double, 4> matrix_to_quaternion(
    const std::array<double, 9> &matrix) {
    std::array<double, 4> q{};
    const double trace = matrix[0] + matrix[4] + matrix[8];
    if (trace > 0.0) {
        const double s = std::sqrt(trace + 1.0) * 2.0;
        q[0] = 0.25 * s;
        q[1] = (matrix[7] - matrix[5]) / s;
        q[2] = (matrix[2] - matrix[6]) / s;
        q[3] = (matrix[3] - matrix[1]) / s;
    } else if (
        matrix[0] > matrix[4] && matrix[0] > matrix[8]) {
        const double s =
            std::sqrt(1.0 + matrix[0] - matrix[4] - matrix[8]) *
            2.0;
        q[0] = (matrix[7] - matrix[5]) / s;
        q[1] = 0.25 * s;
        q[2] = (matrix[1] + matrix[3]) / s;
        q[3] = (matrix[2] + matrix[6]) / s;
    } else if (matrix[4] > matrix[8]) {
        const double s =
            std::sqrt(1.0 + matrix[4] - matrix[0] - matrix[8]) *
            2.0;
        q[0] = (matrix[2] - matrix[6]) / s;
        q[1] = (matrix[1] + matrix[3]) / s;
        q[2] = 0.25 * s;
        q[3] = (matrix[5] + matrix[7]) / s;
    } else {
        const double s =
            std::sqrt(1.0 + matrix[8] - matrix[0] - matrix[4]) *
            2.0;
        q[0] = (matrix[3] - matrix[1]) / s;
        q[1] = (matrix[2] + matrix[6]) / s;
        q[2] = (matrix[5] + matrix[7]) / s;
        q[3] = 0.25 * s;
    }
    double norm = 0.0;
    for (double value : q) norm += value * value;
    norm = std::sqrt(norm);
    for (double &value : q) value /= norm;
    if (q[0] < 0.0)
        for (double &value : q) value = -value;
    return q;
}

std::array<double, 9> quaternion_to_matrix(
    const double *q, const char *format) {
    double norm = 0.0;
    for (size_t index = 0; index < 4; ++index)
        norm += q[index] * q[index];
    if (!std::isfinite(norm) ||
        std::abs(norm - 1.0) > 1e-9)
        throw std::invalid_argument(
            std::string(format) +
            ": extrinsic quaternions must be unit length");
    const double w = q[0];
    const double x = q[1];
    const double y = q[2];
    const double z = q[3];
    return {
        1 - 2 * (y * y + z * z),
        2 * (x * y - z * w),
        2 * (x * z + y * w),
        2 * (x * y + z * w),
        1 - 2 * (x * x + z * z),
        2 * (y * z - x * w),
        2 * (x * z - y * w),
        2 * (y * z + x * w),
        1 - 2 * (x * x + y * y),
    };
}

RigidTransform rig_transform(
    const CameraRig &rig, size_t index,
    const char *format) {
    RigidTransform result;
    result.rotation = quaternion_to_matrix(
        rig.quaternions.data() + index * 4, format);
    for (size_t component = 0; component < 3; ++component)
        result.translation[component] =
            rig.translations[index * 3 + component];
    return result;
}

void set_transform(
    CameraRig &rig, size_t index,
    const RigidTransform &transform) {
    const auto quaternion =
        matrix_to_quaternion(transform.rotation);
    std::copy(
        quaternion.begin(), quaternion.end(),
        rig.quaternions.begin() +
            static_cast<std::ptrdiff_t>(index * 4));
    std::copy(
        transform.translation.begin(), transform.translation.end(),
        rig.translations.begin() +
            static_cast<std::ptrdiff_t>(index * 3));
    rig.has_extrinsics[index] = 1;
}

bool camera_key(std::string_view key, size_t &index) {
    if (key.size() < 4 || key.substr(0, 3) != "cam")
        return false;
    const std::string_view suffix = key.substr(3);
    if (suffix.empty() ||
        (suffix.size() > 1 && suffix.front() == '0'))
        return false;
    uint64_t parsed = 0;
    const auto result = std::from_chars(
        suffix.data(), suffix.data() + suffix.size(), parsed);
    if (result.ec != std::errc{} ||
        result.ptr != suffix.data() + suffix.size() ||
        parsed > std::numeric_limits<size_t>::max())
        return false;
    index = static_cast<size_t>(parsed);
    return true;
}

CameraRig decode_kalibr(
    const uint8_t *bytes, size_t size) {
    constexpr const char *format = "Kalibr YAML";
    const FlatYaml document =
        parse_yaml(bytes, size, format);
    std::vector<std::pair<size_t, std::string>> cameras;
    std::unordered_set<std::string> seen_roots;
    for (const std::string &root : document.top_level) {
        if (!seen_roots.insert(root).second) continue;
        size_t index = 0;
        if (!camera_key(root, index))
            throw std::invalid_argument(
                std::string(format) +
                ": top-level keys must be cam0..camN");
        cameras.emplace_back(index, root);
    }
    std::sort(cameras.begin(), cameras.end());
    if (cameras.empty() || cameras.size() > kCameraLimit)
        throw std::invalid_argument(
            std::string(format) +
            ": expected 1..4096 cameras");
    for (size_t index = 0; index < cameras.size(); ++index)
        if (cameras[index].first != index)
            throw std::invalid_argument(
                std::string(format) +
                ": camera keys must be contiguous from cam0");

    CameraRig rig = empty_rig(cameras.size());
    rig.reference_frame =
        has_key(document.scalars, "cam0.T_cam_imu") ||
                has_key(document.sequences, "cam0.T_cam_imu")
            ? "imu"
            : "camera0";
    rig.quaternion_sign = "canonical_positive_w";
    std::vector<RigidTransform> absolute(cameras.size());
    for (size_t index = 0; index < cameras.size(); ++index) {
        const std::string &root = cameras[index].second;
        rig.camera_ids[index] = static_cast<uint32_t>(index);
        rig.names[index] = root;
        rig.projection_models[index] = parse_string(
            required(document, root + ".camera_model", format),
            root + ".camera_model", format);
        const auto intrinsics =
            yaml_numbers(document, root + ".intrinsics", format);
        if (intrinsics.empty())
            throw std::invalid_argument(
                std::string(format) +
                ": camera intrinsics must be nonempty");
        append_ragged(
            rig.intrinsic_offsets, rig.intrinsics, index,
            intrinsics);
        rig.distortion_models[index] = parse_string(
            required(
                document, root + ".distortion_model", format),
            root + ".distortion_model", format);
        append_ragged(
            rig.distortion_offsets,
            rig.distortion_coefficients, index,
            yaml_numbers(
                document, root + ".distortion_coeffs", format));
        const auto resolution =
            yaml_numbers(document, root + ".resolution", format);
        if (resolution.size() != 2)
            throw std::invalid_argument(
                std::string(format) +
                ": resolution must contain width,height");
        for (size_t component = 0; component < 2; ++component) {
            if (resolution[component] < 1.0 ||
                resolution[component] >
                    static_cast<double>(
                        std::numeric_limits<uint32_t>::max()) ||
                std::floor(resolution[component]) !=
                    resolution[component])
                throw std::invalid_argument(
                    std::string(format) +
                    ": resolution values must be positive integers");
            rig.resolutions[index * 2 + component] =
                static_cast<uint64_t>(resolution[component]);
        }
        rig.topics[index] = parse_string(
            required(document, root + ".rostopic", format),
            root + ".rostopic", format);
        if (const std::string *offset = optional(
                document, root + ".timeshift_cam_imu")) {
            rig.time_offsets[index] = parse_double(
                *offset, root + ".timeshift_cam_imu", format);
            rig.has_time_offset[index] = 1;
        }

        if (rig.projection_models[index] == "pinhole") {
            if (intrinsics.size() != 4)
                throw std::invalid_argument(
                    std::string(format) +
                    ": pinhole intrinsics must contain fu,fv,pu,pv");
            set_matrix(
                rig.camera_matrices, rig.has_camera_matrix,
                index, 9,
                {intrinsics[0], 0.0, intrinsics[2],
                 0.0, intrinsics[1], intrinsics[3],
                 0.0, 0.0, 1.0});
        } else if (rig.projection_models[index] == "omni") {
            if (intrinsics.size() != 5)
                throw std::invalid_argument(
                    std::string(format) +
                    ": omni intrinsics must contain xi,fu,fv,pu,pv");
            set_matrix(
                rig.camera_matrices, rig.has_camera_matrix,
                index, 9,
                {intrinsics[1], 0.0, intrinsics[3],
                 0.0, intrinsics[2], intrinsics[4],
                 0.0, 0.0, 1.0});
        }

        const bool has_direct =
            has_key(document.scalars, root + ".T_cam_imu") ||
            has_key(document.sequences, root + ".T_cam_imu");
        const bool has_chain =
            has_key(document.scalars, root + ".T_cn_cnm1") ||
            has_key(document.sequences, root + ".T_cn_cnm1");
        if (has_direct && has_chain)
            throw std::invalid_argument(
                std::string(format) +
                ": a camera cannot define both T_cam_imu and "
                "T_cn_cnm1");
        if (index == 0) {
            if (has_chain)
                throw std::invalid_argument(
                    std::string(format) +
                    ": cam0 cannot define T_cn_cnm1");
            if (rig.reference_frame == "imu") {
                if (!has_direct)
                    throw std::invalid_argument(
                        std::string(format) +
                        ": cam0 is missing T_cam_imu");
                absolute[index] = parse_transform(
                    yaml_numbers(
                        document, root + ".T_cam_imu", format),
                    root + ".T_cam_imu", format);
            } else {
                absolute[index].rotation = {
                    1, 0, 0, 0, 1, 0, 0, 0, 1};
                absolute[index].translation = {0, 0, 0};
            }
        } else if (has_direct) {
            if (rig.reference_frame != "imu")
                throw std::invalid_argument(
                    std::string(format) +
                    ": T_cam_imu requires cam0.T_cam_imu");
            absolute[index] = parse_transform(
                yaml_numbers(
                    document, root + ".T_cam_imu", format),
                root + ".T_cam_imu", format);
        } else {
            if (!has_chain)
                throw std::invalid_argument(
                    std::string(format) + ": " + root +
                    " is missing T_cn_cnm1");
            absolute[index] = compose(
                parse_transform(
                    yaml_numbers(
                        document, root + ".T_cn_cnm1",
                        format),
                    root + ".T_cn_cnm1", format),
                absolute[index - 1]);
        }
        set_transform(rig, index, absolute[index]);
    }
    if (rig.reference_frame != "imu")
        for (uint8_t present : rig.has_time_offset)
            if (present)
                throw std::invalid_argument(
                    std::string(format) +
                    ": timeshift_cam_imu requires T_cam_imu");
    validate_camera_rig(rig, format);
    return rig;
}

template <typename Decode>
CameraRig read_calibration(
    nb::handle source, Decode decode) {
    ByteView view(source);
    CameraRig result;
    {
        nb::gil_scoped_release release;
        result = decode(view.data(), view.size());
    }
    return result;
}

void append_number(std::string &output, double value) {
    char buffer[64];
    const int length =
        std::snprintf(buffer, sizeof(buffer), "%.17g", value);
    if (length <= 0 ||
        static_cast<size_t>(length) >= sizeof(buffer))
        throw std::runtime_error(
            "camera calibration: numeric formatting failed");
    output.append(buffer, static_cast<size_t>(length));
}

void append_yaml_string(
    std::string &output, const std::string &value) {
    output += '\'';
    for (char c : value) {
        if (c == '\'') output += '\'';
        output += c;
    }
    output += '\'';
}

std::string xml_escape(const std::string &value) {
    std::string output;
    for (char c : value) {
        if (c == '&')
            output += "&amp;";
        else if (c == '<')
            output += "&lt;";
        else if (c == '>')
            output += "&gt;";
        else if (c == '"')
            output += "&quot;";
        else if (c == '\'')
            output += "&apos;";
        else
            output += c;
    }
    return output;
}

void append_inline_values(
    std::string &output, const double *values, size_t count) {
    output += "[";
    for (size_t index = 0; index < count; ++index) {
        if (index != 0) output += ", ";
        if (index != 0 && index % 256 == 0)
            output += "\n    ";
        append_number(output, values[index]);
    }
    output += "]";
}

void append_yaml_matrix(
    std::string &output, const char *name,
    size_t rows, size_t columns, const double *values,
    bool opencv) {
    output += name;
    output += opencv ? ": !!opencv-matrix\n" : ":\n";
    output += "  rows: " + std::to_string(rows) + "\n";
    output += "  cols: " + std::to_string(columns) + "\n";
    if (opencv) output += "  dt: d\n";
    output += "  data: ";
    append_inline_values(output, values, rows * columns);
    output += '\n';
}

void append_xml_matrix(
    std::string &output, const char *name,
    size_t rows, size_t columns, const double *values) {
    output += "<";
    output += name;
    output += " type_id=\"opencv-matrix\">\n<rows>";
    output += std::to_string(rows);
    output += "</rows>\n<cols>";
    output += std::to_string(columns);
    output += "</cols>\n<dt>d</dt>\n<data>";
    for (size_t index = 0; index < rows * columns; ++index) {
        if (index != 0) output += ' ';
        append_number(output, values[index]);
    }
    output += "</data>\n</";
    output += name;
    output += ">\n";
}

std::pair<const double *, size_t> ragged(
    const std::vector<uint64_t> &offsets,
    const std::vector<double> &values, size_t index) {
    const size_t start = static_cast<size_t>(offsets[index]);
    const size_t stop = static_cast<size_t>(offsets[index + 1]);
    static const double sentinel = 0.0;
    return {
        values.empty()
            ? &sentinel
            : values.data() + static_cast<std::ptrdiff_t>(start),
        stop - start};
}

void validate_single_common(
    const CameraRig &rig, const char *format) {
    validate_camera_rig(rig, format);
    if (rig.n != 1 || rig.camera_ids[0] != 0)
        throw std::invalid_argument(
            std::string(format) +
            ": requires exactly camera id 0");
    if (rig.quaternion_order != "wxyz" ||
        rig.quaternion_sign != "preserved" ||
        rig.transform_convention != "reference_to_camera" ||
        rig.axis_frame != "opencv" ||
        rig.reference_frame != "unknown" ||
        rig.scale_to_meters != 1.0)
        throw std::invalid_argument(
            std::string(format) +
            ": record conventions are not representable");
    if (rig.projection_models[0] != "pinhole" ||
        !rig.has_camera_matrix[0])
        throw std::invalid_argument(
            std::string(format) +
            ": requires pinhole intrinsics and an exact K matrix");
    const auto intrinsics =
        ragged(rig.intrinsic_offsets, rig.intrinsics, 0);
    const double *matrix = rig.camera_matrices.data();
    if (intrinsics.second != 4 ||
        intrinsics.first[0] != matrix[0] ||
        intrinsics.first[1] != matrix[4] ||
        intrinsics.first[2] != matrix[2] ||
        intrinsics.first[3] != matrix[5])
        throw std::invalid_argument(
            std::string(format) +
            ": intrinsics must exactly match fx,fy,cx,cy in K");
    if (rig.has_extrinsics[0] || rig.has_time_offset[0] ||
        !rig.topics[0].empty())
        throw std::invalid_argument(
            std::string(format) +
            ": extrinsics, time offsets, and topics are not "
            "representable");
}

void validate_opencv_write(
    const CameraRig &rig, const char *format) {
    validate_single_common(rig, format);
    if (rig.has_operational[0])
        throw std::invalid_argument(
            std::string(format) +
            ": ROS operational fields are not representable");
}

void validate_ros_write(const CameraRig &rig) {
    constexpr const char *format = "ROS camera_info";
    validate_single_common(rig, format);
    if (!rig.has_rectification[0] ||
        !rig.has_projection_matrix[0] ||
        !rig.has_operational[0])
        throw std::invalid_argument(
            std::string(format) +
            ": requires exact K, R, P, binning, and ROI fields");
}

std::string encode_opencv_yaml(const CameraRig &rig) {
    constexpr const char *format = "OpenCV YAML";
    validate_opencv_write(rig, format);
    std::string output = "%YAML:1.0\n---\nimage_width: ";
    output += std::to_string(rig.resolutions[0]);
    output += "\nimage_height: ";
    output += std::to_string(rig.resolutions[1]);
    output += "\ncamera_name: ";
    append_yaml_string(output, rig.names[0]);
    output += "\ndistortion_model: ";
    append_yaml_string(output, rig.distortion_models[0]);
    output += '\n';
    append_yaml_matrix(
        output, "camera_matrix", 3, 3,
        rig.camera_matrices.data(), true);
    const auto distortion = ragged(
        rig.distortion_offsets,
        rig.distortion_coefficients, 0);
    append_yaml_matrix(
        output, "distortion_coefficients",
        distortion.second == 0 ? 0 : 1, distortion.second,
        distortion.first, true);
    if (rig.has_rectification[0])
        append_yaml_matrix(
            output, "rectification_matrix", 3, 3,
            rig.rectification_matrices.data(), true);
    if (rig.has_projection_matrix[0])
        append_yaml_matrix(
            output, "projection_matrix", 3, 4,
            rig.projection_matrices.data(), true);
    return output;
}

std::string encode_opencv_xml(const CameraRig &rig) {
    constexpr const char *format = "OpenCV XML";
    validate_opencv_write(rig, format);
    std::string output = "<opencv_storage>\n<image_width>";
    output += std::to_string(rig.resolutions[0]);
    output += "</image_width>\n<image_height>";
    output += std::to_string(rig.resolutions[1]);
    output += "</image_height>\n<camera_name>";
    output += xml_escape(rig.names[0]);
    output += "</camera_name>\n<distortion_model>";
    output += xml_escape(rig.distortion_models[0]);
    output += "</distortion_model>\n";
    append_xml_matrix(
        output, "camera_matrix", 3, 3,
        rig.camera_matrices.data());
    const auto distortion = ragged(
        rig.distortion_offsets,
        rig.distortion_coefficients, 0);
    append_xml_matrix(
        output, "distortion_coefficients",
        distortion.second == 0 ? 0 : 1, distortion.second,
        distortion.first);
    if (rig.has_rectification[0])
        append_xml_matrix(
            output, "rectification_matrix", 3, 3,
            rig.rectification_matrices.data());
    if (rig.has_projection_matrix[0])
        append_xml_matrix(
            output, "projection_matrix", 3, 4,
            rig.projection_matrices.data());
    output += "</opencv_storage>\n";
    return output;
}

std::string encode_ros_camera_info(const CameraRig &rig) {
    validate_ros_write(rig);
    std::string output = "image_width: ";
    output += std::to_string(rig.resolutions[0]);
    output += "\nimage_height: ";
    output += std::to_string(rig.resolutions[1]);
    output += "\ncamera_name: ";
    append_yaml_string(output, rig.names[0]);
    output += "\ncamera_matrix:\n  rows: 3\n  cols: 3\n  data: ";
    append_inline_values(output, rig.camera_matrices.data(), 9);
    output += "\ndistortion_model: ";
    append_yaml_string(output, rig.distortion_models[0]);
    const auto distortion = ragged(
        rig.distortion_offsets,
        rig.distortion_coefficients, 0);
    output += "\ndistortion_coefficients:\n  rows: ";
    output += std::to_string(distortion.second == 0 ? 0 : 1);
    output += "\n  cols: " + std::to_string(distortion.second);
    output += "\n  data: ";
    append_inline_values(
        output, distortion.first, distortion.second);
    output += '\n';
    append_yaml_matrix(
        output, "rectification_matrix", 3, 3,
        rig.rectification_matrices.data(), false);
    append_yaml_matrix(
        output, "projection_matrix", 3, 4,
        rig.projection_matrices.data(), false);
    output += "binning_x: " + std::to_string(rig.binning[0]);
    output += "\nbinning_y: " + std::to_string(rig.binning[1]);
    output += "\nroi:\n  x_offset: " +
              std::to_string(rig.roi[0]);
    output += "\n  y_offset: " + std::to_string(rig.roi[1]);
    output += "\n  height: " + std::to_string(rig.roi[3]);
    output += "\n  width: " + std::to_string(rig.roi[2]);
    output += "\n  do_rectify: ";
    output += rig.roi_do_rectify[0] ? "true\n" : "false\n";
    return output;
}

void validate_kalibr_write(const CameraRig &rig) {
    constexpr const char *format = "Kalibr YAML";
    validate_camera_rig(rig, format);
    if (rig.n == 0 || rig.n > kCameraLimit ||
        rig.quaternion_order != "wxyz" ||
        rig.quaternion_sign != "canonical_positive_w" ||
        rig.transform_convention != "reference_to_camera" ||
        rig.axis_frame != "opencv" ||
        (rig.reference_frame != "imu" &&
         rig.reference_frame != "camera0") ||
        rig.scale_to_meters != 1.0)
        throw std::invalid_argument(
            std::string(format) +
            ": record conventions are not representable");
    for (size_t index = 0; index < rig.n; ++index) {
        const std::string expected_name =
            "cam" + std::to_string(index);
        if (rig.camera_ids[index] != index ||
            rig.names[index] != expected_name ||
            rig.projection_models[index].empty() ||
            rig.distortion_models[index].empty() ||
            rig.topics[index].empty() ||
            !rig.has_extrinsics[index] ||
            rig.has_rectification[index] ||
            rig.has_projection_matrix[index] ||
            rig.has_operational[index])
            throw std::invalid_argument(
                std::string(format) +
                ": camera ids/names or fields are not representable");
        const auto intrinsics =
            ragged(rig.intrinsic_offsets, rig.intrinsics, index);
        if (intrinsics.second == 0)
            throw std::invalid_argument(
                std::string(format) +
                ": intrinsics must be nonempty");
        if (rig.projection_models[index] == "pinhole") {
            if (intrinsics.second != 4 ||
                !rig.has_camera_matrix[index])
                throw std::invalid_argument(
                    std::string(format) +
                    ": pinhole requires four intrinsics and K");
            const double *matrix =
                rig.camera_matrices.data() + index * 9;
            if (intrinsics.first[0] != matrix[0] ||
                intrinsics.first[1] != matrix[4] ||
                intrinsics.first[2] != matrix[2] ||
                intrinsics.first[3] != matrix[5])
                throw std::invalid_argument(
                    std::string(format) +
                    ": pinhole intrinsics do not match K");
        } else if (rig.projection_models[index] == "omni") {
            if (intrinsics.second != 5 ||
                !rig.has_camera_matrix[index])
                throw std::invalid_argument(
                    std::string(format) +
                    ": omni requires five intrinsics and K");
            const double *matrix =
                rig.camera_matrices.data() + index * 9;
            if (intrinsics.first[1] != matrix[0] ||
                intrinsics.first[2] != matrix[4] ||
                intrinsics.first[3] != matrix[2] ||
                intrinsics.first[4] != matrix[5])
                throw std::invalid_argument(
                    std::string(format) +
                    ": omni intrinsics do not match K");
        } else if (rig.has_camera_matrix[index]) {
            throw std::invalid_argument(
                std::string(format) +
                ": unknown camera models cannot carry a derived K");
        }
        if (rig.has_time_offset[index] &&
            rig.reference_frame != "imu")
            throw std::invalid_argument(
                std::string(format) +
                ": time offsets require an IMU reference");
        (void) rig_transform(rig, index, format);
    }
    if (rig.reference_frame == "camera0") {
        const double *q = rig.quaternions.data();
        const double *t = rig.translations.data();
        if (q[0] != 1.0 || q[1] != 0.0 || q[2] != 0.0 ||
            q[3] != 0.0 || t[0] != 0.0 || t[1] != 0.0 ||
            t[2] != 0.0)
            throw std::invalid_argument(
                std::string(format) +
                ": camera0 reference requires identity cam0 pose");
    }
}

void append_transform(
    std::string &output, const char *name,
    const RigidTransform &transform) {
    output += "  ";
    output += name;
    output += ":\n";
    for (size_t row = 0; row < 4; ++row) {
        output += "  - [";
        for (size_t column = 0; column < 4; ++column) {
            if (column != 0) output += ", ";
            if (row < 3 && column < 3)
                append_number(
                    output,
                    transform.rotation[row * 3 + column]);
            else if (row < 3 && column == 3)
                append_number(output, transform.translation[row]);
            else
                output += column == 3 ? "1" : "0";
        }
        output += "]\n";
    }
}

std::string encode_kalibr(const CameraRig &rig) {
    constexpr const char *format = "Kalibr YAML";
    validate_kalibr_write(rig);
    std::vector<RigidTransform> transforms;
    transforms.reserve(rig.n);
    for (size_t index = 0; index < rig.n; ++index)
        transforms.push_back(rig_transform(rig, index, format));
    std::string output;
    for (size_t index = 0; index < rig.n; ++index) {
        output += "cam" + std::to_string(index) + ":\n";
        output += "  camera_model: ";
        append_yaml_string(output, rig.projection_models[index]);
        output += "\n  intrinsics: ";
        const auto intrinsics =
            ragged(rig.intrinsic_offsets, rig.intrinsics, index);
        append_inline_values(
            output, intrinsics.first, intrinsics.second);
        output += "\n  distortion_model: ";
        append_yaml_string(output, rig.distortion_models[index]);
        output += "\n  distortion_coeffs: ";
        const auto distortion = ragged(
            rig.distortion_offsets,
            rig.distortion_coefficients, index);
        append_inline_values(
            output, distortion.first, distortion.second);
        output += "\n  resolution: [";
        output += std::to_string(rig.resolutions[index * 2]);
        output += ", ";
        output += std::to_string(rig.resolutions[index * 2 + 1]);
        output += "]\n  rostopic: ";
        append_yaml_string(output, rig.topics[index]);
        output += '\n';
        if (rig.reference_frame == "imu" && index == 0)
            append_transform(
                output, "T_cam_imu", transforms[index]);
        else if (index != 0)
            append_transform(
                output, "T_cn_cnm1",
                compose(
                    transforms[index],
                    inverse(transforms[index - 1])));
        if (rig.has_time_offset[index]) {
            output += "  timeshift_cam_imu: ";
            append_number(output, rig.time_offsets[index]);
            output += '\n';
        }
    }
    return output;
}

template <typename Encode>
nb::bytes write_calibration(
    const CameraRig &rig, Encode encode) {
    std::string output;
    {
        nb::gil_scoped_release release;
        output = encode(rig);
    }
    return emit_bytes(output.data(), output.size());
}

template <typename Decode>
nb::tuple inspect_calibration(
    nb::handle source, Decode decode) {
    const CameraRig rig =
        read_calibration(source, decode);
    std::vector<uint64_t> resolutions = rig.resolutions;
    return nb::make_tuple(rig.n, resolutions);
}

}  // namespace

void register_camera_calibration(nb::module_ &module) {
    module.def(
        "read_opencv_yaml",
        [](nb::handle data) {
            return read_calibration(data, decode_opencv_yaml);
        },
        "data"_a);
    module.def(
        "write_opencv_yaml",
        [](const CameraRig &rig) {
            return write_calibration(rig, encode_opencv_yaml);
        },
        "rig"_a);
    module.def(
        "_inspect_opencv_yaml",
        [](nb::handle data) {
            return inspect_calibration(data, decode_opencv_yaml);
        },
        "data"_a);

    module.def(
        "read_opencv_xml",
        [](nb::handle data) {
            return read_calibration(data, decode_opencv_xml);
        },
        "data"_a);
    module.def(
        "write_opencv_xml",
        [](const CameraRig &rig) {
            return write_calibration(rig, encode_opencv_xml);
        },
        "rig"_a);
    module.def(
        "_inspect_opencv_xml",
        [](nb::handle data) {
            return inspect_calibration(data, decode_opencv_xml);
        },
        "data"_a);

    module.def(
        "read_ros_camera_info",
        [](nb::handle data) {
            return read_calibration(data, decode_ros_camera_info);
        },
        "data"_a);
    module.def(
        "write_ros_camera_info",
        [](const CameraRig &rig) {
            return write_calibration(rig, encode_ros_camera_info);
        },
        "rig"_a);
    module.def(
        "_inspect_ros_camera_info",
        [](nb::handle data) {
            return inspect_calibration(data, decode_ros_camera_info);
        },
        "data"_a);

    module.def(
        "read_kalibr",
        [](nb::handle data) {
            return read_calibration(data, decode_kalibr);
        },
        "data"_a);
    module.def(
        "write_kalibr",
        [](const CameraRig &rig) {
            return write_calibration(rig, encode_kalibr);
        },
        "rig"_a);
    module.def(
        "_inspect_kalibr",
        [](nb::handle data) {
            return inspect_calibration(data, decode_kalibr);
        },
        "data"_a);
}
