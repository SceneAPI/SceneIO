// codecs/reconstruction/g2o.cpp -- bounded g2o SE3:QUAT pose-graph text codec.
//
// Supported records:
//   VERTEX_SE3:QUAT id tx ty tz qx qy qz qw
//   EDGE_SE3:QUAT from to tx ty tz qx qy qz qw I00 I01 ... I55
//   FIX id
//
// The 21 information coefficients are g2o's row-major upper triangle in the
// (tx,ty,tz,qx,qy,qz) error order. Unknown vertex/edge/parameter records are
// rejected rather than discarded. Parsing accepts a read-only contiguous
// buffer exporter and releases the GIL; the deterministic writer streams
// bounded line chunks through SceneIO's native sink.
#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "fast_float/fast_float.h"
#include "records/pose_graph.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

constexpr size_t kLineLimit = 1024 * 1024;
constexpr size_t kChunkRows = 2048;
constexpr std::string_view kHeader =
    "# g2o pose graph (SceneIO)\n";

bool token_space(char value) {
    return value == ' ' || value == '\t' ||
           value == '\r' || value == '\v' ||
           value == '\f';
}

template <typename Callback>
void for_each_line(
    const uint8_t *bytes, size_t size, Callback callback) {
    const char *cursor =
        reinterpret_cast<const char *>(bytes);
    const char *const end = cursor + size;
    size_t line_number = 0;
    while (cursor < end) {
        ++line_number;
        const size_t remaining =
            static_cast<size_t>(end - cursor);
        const size_t search =
            std::min(remaining, kLineLimit + 1);
        const void *newline =
            std::memchr(cursor, '\n', search);
        if (!newline && remaining > kLineLimit)
            throw std::invalid_argument(
                "g2o: line exceeds 1 MiB");
        const char *line_end =
            newline ? static_cast<const char *>(newline) : end;
        const size_t line_size =
            static_cast<size_t>(line_end - cursor);
        if (line_size > kLineLimit)
            throw std::invalid_argument(
                "g2o: line exceeds 1 MiB");
        if (std::memchr(cursor, '\0', line_size))
            throw std::invalid_argument(
                "g2o: NUL byte in text input");
        callback(
            std::string_view(cursor, line_size),
            line_number);
        cursor = newline ? line_end + 1 : end;
    }
}

std::vector<std::string_view> tokens(
    std::string_view line) {
    const size_t comment = line.find('#');
    if (comment != std::string_view::npos)
        line = line.substr(0, comment);
    std::vector<std::string_view> result;
    result.reserve(32);
    size_t cursor = 0;
    while (cursor < line.size()) {
        while (cursor < line.size() &&
               token_space(line[cursor]))
            ++cursor;
        if (cursor == line.size()) break;
        const size_t begin = cursor;
        while (cursor < line.size() &&
               !token_space(line[cursor]))
            ++cursor;
        result.push_back(line.substr(begin, cursor - begin));
    }
    return result;
}

int64_t parse_id(
    std::string_view token, size_t line_number) {
    int64_t value = 0;
    const auto result = std::from_chars(
        token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size() ||
        value < 0 ||
        value > std::numeric_limits<int32_t>::max())
        throw std::invalid_argument(
            "g2o: line " + std::to_string(line_number) +
            " has an invalid nonnegative 32-bit vertex id");
    return value;
}

double parse_number(
    std::string_view token, size_t line_number) {
    double value = 0.0;
    const auto result = fast_float::from_chars(
        token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} ||
        result.ptr != token.data() + token.size() ||
        !std::isfinite(value))
        throw std::invalid_argument(
            "g2o: line " + std::to_string(line_number) +
            " has an invalid or non-finite numeric value");
    return value;
}

void validate_unit_quaternion(
    const std::array<double, 4> &q,
    size_t line_number) {
    double norm_squared = 0.0;
    for (double value : q)
        norm_squared += value * value;
    if (!std::isfinite(norm_squared) ||
        std::abs(norm_squared - 1.0) > 1e-3)
        throw std::invalid_argument(
            "g2o: line " + std::to_string(line_number) +
            " quaternion must be unit length within 1e-3");
}

struct ScanResult {
    PoseGraph graph;
    size_t node_count = 0;
    size_t edge_count = 0;
    size_t fixed_count = 0;
};

ScanResult decode(
    const uint8_t *bytes, size_t size, bool collect) {
    ScanResult result;
    PoseGraph &graph = result.graph;
    if (size == 0) {
        if (collect) validate_pose_graph(graph, "g2o");
        return result;
    }
    std::unordered_map<int64_t, size_t> node_rows;
    std::unordered_set<int64_t> fixed_ids;
    std::vector<int64_t> endpoints_for_validation;

    // Even the shortest supported vertex record occupies at least 30 bytes;
    // valid FIX ids cannot outnumber vertices, and two endpoint ids per edge
    // still fit this conservative aggregate bound. Avoid reserving from a
    // much smaller per-token estimate: comment-heavy files would otherwise
    // allocate a large empty hash table before the first record is parsed.
    const size_t possible_records = size / 30 + 1;
    node_rows.reserve(possible_records);
    fixed_ids.reserve(possible_records);
    endpoints_for_validation.reserve(possible_records);

    for_each_line(
        bytes, size,
        [&](std::string_view line, size_t line_number) {
            const auto fields = tokens(line);
            if (fields.empty()) return;
            const std::string_view tag = fields[0];
            if (tag == "VERTEX_SE3:QUAT") {
                if (fields.size() != 9)
                    throw std::invalid_argument(
                        "g2o: line " +
                        std::to_string(line_number) +
                        " VERTEX_SE3:QUAT requires id plus "
                        "7 numeric values");
                const int64_t id =
                    parse_id(fields[1], line_number);
                if (!node_rows.emplace(
                        id, result.node_count).second)
                    throw std::invalid_argument(
                        "g2o: duplicate vertex id " +
                        std::to_string(id));
                std::array<double, 3> translation;
                std::array<double, 4> quaternion;
                for (size_t component = 0;
                     component < 3; ++component)
                    translation[component] = parse_number(
                        fields[2 + component], line_number);
                for (size_t component = 0;
                     component < 4; ++component)
                    quaternion[component] = parse_number(
                        fields[5 + component], line_number);
                validate_unit_quaternion(
                    quaternion, line_number);
                if (collect) {
                    graph.node_ids.push_back(id);
                    graph.node_translations.insert(
                        graph.node_translations.end(),
                        translation.begin(), translation.end());
                    graph.node_quaternions.insert(
                        graph.node_quaternions.end(),
                        quaternion.begin(), quaternion.end());
                    graph.fixed.push_back(0);
                    graph.node_types.emplace_back("se3");
                }
                ++result.node_count;
                return;
            }
            if (tag == "EDGE_SE3:QUAT") {
                if (fields.size() != 31)
                    throw std::invalid_argument(
                        "g2o: line " +
                        std::to_string(line_number) +
                        " EDGE_SE3:QUAT requires 2 ids, "
                        "7 pose values, and 21 information values");
                const int64_t source =
                    parse_id(fields[1], line_number);
                const int64_t target =
                    parse_id(fields[2], line_number);
                endpoints_for_validation.push_back(source);
                endpoints_for_validation.push_back(target);
                std::array<double, 3> translation;
                std::array<double, 4> quaternion;
                for (size_t component = 0;
                     component < 3; ++component)
                    translation[component] = parse_number(
                        fields[3 + component], line_number);
                for (size_t component = 0;
                     component < 4; ++component)
                    quaternion[component] = parse_number(
                        fields[6 + component], line_number);
                validate_unit_quaternion(
                    quaternion, line_number);
                std::array<double, 36> information{};
                size_t field = 10;
                for (size_t row = 0; row < 6; ++row) {
                    for (size_t column = row;
                         column < 6; ++column) {
                        const double value =
                            parse_number(
                                fields[field++], line_number);
                        information[row * 6 + column] = value;
                        information[column * 6 + row] = value;
                    }
                }
                if (collect) {
                    graph.edge_endpoints.push_back(source);
                    graph.edge_endpoints.push_back(target);
                    graph.edge_translations.insert(
                        graph.edge_translations.end(),
                        translation.begin(), translation.end());
                    graph.edge_quaternions.insert(
                        graph.edge_quaternions.end(),
                        quaternion.begin(), quaternion.end());
                    graph.information_matrices.insert(
                        graph.information_matrices.end(),
                        information.begin(), information.end());
                    graph.edge_types.emplace_back("se3");
                }
                ++result.edge_count;
                return;
            }
            if (tag == "FIX") {
                if (fields.size() != 2)
                    throw std::invalid_argument(
                        "g2o: line " +
                        std::to_string(line_number) +
                        " FIX requires exactly one vertex id");
                const int64_t id =
                    parse_id(fields[1], line_number);
                if (!fixed_ids.insert(id).second)
                    throw std::invalid_argument(
                        "g2o: duplicate FIX for vertex id " +
                        std::to_string(id));
                return;
            }
            throw std::invalid_argument(
                "g2o: unsupported record type '" +
                std::string(tag) + "' on line " +
                std::to_string(line_number));
        });

    for (int64_t id : fixed_ids) {
        const auto found = node_rows.find(id);
        if (found == node_rows.end())
            throw std::invalid_argument(
                "g2o: FIX references missing vertex id " +
                std::to_string(id));
        if (collect) graph.fixed[found->second] = 1;
    }
    result.fixed_count = fixed_ids.size();
    for (size_t index = 0;
         index < endpoints_for_validation.size();
         index += 2) {
        if (!node_rows.count(endpoints_for_validation[index]) ||
            !node_rows.count(
                endpoints_for_validation[index + 1]))
            throw std::invalid_argument(
                "g2o: edge references a missing vertex id");
    }

    if (collect) {
        graph.n = result.node_count;
        graph.m = result.edge_count;
        validate_pose_graph(graph, "g2o");
    }
    return result;
}

PoseGraph read_g2o(nb::handle source) {
    ByteView view(source);
    PoseGraph graph;
    {
        nb::gil_scoped_release release;
        graph = std::move(
            decode(view.data(), view.size(), true).graph);
    }
    return graph;
}

nb::tuple inspect_g2o(nb::handle source) {
    ByteView view(source);
    ScanResult result;
    {
        nb::gil_scoped_release release;
        result = decode(
            view.data(), view.size(), false);
    }
    return nb::make_tuple(
        result.node_count, result.edge_count,
        result.fixed_count);
}

void validate_write(const PoseGraph &graph) {
    validate_pose_graph(graph, "g2o");
    if (graph.quaternion_order != "xyzw" ||
        graph.quaternion_sign != "preserved" ||
        graph.node_transform_convention !=
            "node_to_reference" ||
        graph.edge_transform_convention !=
            "source_inverse_times_target" ||
        graph.translation_unit != "unspecified" ||
        graph.information_variable_order !=
            "tx_ty_tz_qx_qy_qz")
        throw std::invalid_argument(
            "g2o: PoseGraph conventions are not representable by "
            "SE3:QUAT");
    for (size_t row = 0; row < graph.n; ++row) {
        const int64_t id = graph.node_ids[row];
        if (id < 0 ||
            id > std::numeric_limits<int32_t>::max())
            throw std::invalid_argument(
                "g2o: node ids must fit the nonnegative "
                "32-bit g2o id domain");
        if (graph.node_types[row] != "se3")
            throw std::invalid_argument(
                "g2o: only se3 node types are representable");
    }
    for (const std::string &type : graph.edge_types)
        if (type != "se3")
            throw std::invalid_argument(
                "g2o: only se3 edge types are representable");
}

void append_number(std::string &output, double value) {
    char buffer[64];
    const int length =
        std::snprintf(buffer, sizeof(buffer), "%.17g", value);
    if (length <= 0 ||
        static_cast<size_t>(length) >= sizeof(buffer))
        throw std::runtime_error(
            "g2o: numeric formatting failed");
    output.append(buffer, static_cast<size_t>(length));
}

void append_node(
    std::string &output, const PoseGraph &graph,
    size_t row) {
    output += "VERTEX_SE3:QUAT ";
    output += std::to_string(graph.node_ids[row]);
    for (size_t component = 0; component < 3; ++component) {
        output += ' ';
        append_number(
            output,
            graph.node_translations[row * 3 + component]);
    }
    for (size_t component = 0; component < 4; ++component) {
        output += ' ';
        append_number(
            output,
            graph.node_quaternions[row * 4 + component]);
    }
    output += '\n';
}

void append_fixed(
    std::string &output, const PoseGraph &graph,
    size_t row) {
    if (!graph.fixed[row]) return;
    output += "FIX ";
    output += std::to_string(graph.node_ids[row]);
    output += '\n';
}

void append_edge(
    std::string &output, const PoseGraph &graph,
    size_t row) {
    output += "EDGE_SE3:QUAT ";
    output += std::to_string(
        graph.edge_endpoints[row * 2]);
    output += ' ';
    output += std::to_string(
        graph.edge_endpoints[row * 2 + 1]);
    for (size_t component = 0; component < 3; ++component) {
        output += ' ';
        append_number(
            output,
            graph.edge_translations[row * 3 + component]);
    }
    for (size_t component = 0; component < 4; ++component) {
        output += ' ';
        append_number(
            output,
            graph.edge_quaternions[row * 4 + component]);
    }
    const double *information =
        graph.information_matrices.data() + row * 36;
    for (size_t matrix_row = 0;
         matrix_row < 6; ++matrix_row)
        for (size_t column = matrix_row;
             column < 6; ++column) {
            output += ' ';
            append_number(
                output,
                information[matrix_row * 6 + column]);
        }
    output += '\n';
}

template <typename Append>
void emit_rows(
    const PoseGraph &graph, size_t count, Append append) {
    for (size_t begin = 0; begin < count;
         begin += kChunkRows) {
        const size_t end =
            std::min(count, begin + kChunkRows);
        std::string chunk;
        {
            nb::gil_scoped_release release;
            for (size_t row = begin; row < end; ++row)
                append(chunk, graph, row);
        }
        if (!chunk.empty())
            emit_file_chunk(chunk.data(), chunk.size());
    }
}

nb::bytes write_g2o(const PoseGraph &graph) {
    {
        nb::gil_scoped_release release;
        validate_write(graph);
    }
    if (!emit_file_chunk(kHeader.data(), kHeader.size())) {
        std::string output(kHeader);
        {
            nb::gil_scoped_release release;
            for (size_t row = 0; row < graph.n; ++row)
                append_node(output, graph, row);
            for (size_t row = 0; row < graph.n; ++row)
                append_fixed(output, graph, row);
            for (size_t row = 0; row < graph.m; ++row)
                append_edge(output, graph, row);
        }
        return nb::bytes(output.data(), output.size());
    }
    emit_rows(graph, graph.n, append_node);
    emit_rows(graph, graph.n, append_fixed);
    emit_rows(graph, graph.m, append_edge);
    return nb::bytes("", 0);
}

}  // namespace

void register_g2o(nb::module_ &module) {
    module.def(
        "_inspect_g2o", &inspect_g2o, "data"_a,
        "Validate a g2o SE3:QUAT graph and return node, edge, "
        "and fixed-node counts without constructing record arrays.");
    module.def(
        "read_g2o", &read_g2o, "data"_a,
        "Decode a bounded g2o VERTEX_SE3:QUAT / EDGE_SE3:QUAT "
        "graph into a PoseGraph.");
    module.def(
        "write_g2o", &write_g2o, "graph"_a,
        "Encode a convention-compatible PoseGraph as deterministic "
        "g2o SE3:QUAT text.");
}
