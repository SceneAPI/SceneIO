// codecs/points/xyz.cpp -- the .xyz point-cloud TEXT codec into the shared PointCloud
// record (records/point_cloud.hpp).
//
// Grammar: one point per line, whitespace/comma separated; blank lines and
// '#'-comment lines (leading whitespace allowed) are skipped anywhere. The
// FIRST data line fixes the column count C for the whole file and thereby the
// schema:
//     3  ->  x y z
//     4  ->  x y z intensity
//     6  ->  x y z r g b               (rgb: integers 0..255, stored RAW)
//     7  ->  x y z intensity r g b
//     9  ->  x y z r g b nx ny nz      (CloudCompare column order)
// Any other column count -- or a later line that does not match C -- raises with
// a 1-based line number. The 6-column form auto-detects as rgb; the ambiguous
// 6-column normals dialect (x y z nx ny nz) has no data-only tell, so it is
// reachable only via the read_xyz(layout="xyzn") override (see schema_from_name).
//
// Floating-point numbers are parsed with fast_float::from_chars -- a vendored,
// portable drop-in for std::from_chars<double>, whose FP overload is missing on
// manylinux2014 (GCC 10) and older libc++, so the wheels would not build with
// std::from_chars. Values are stored verbatim: xyz/normals/intensity as float32,
// rgb as uint8; nothing is rescaled (the reader records, it does not judge -- the
// netpbm maxval-is-metadata precedent). Conventions the record carries
// (coordinate_frame/scale_to_meters/intensity_range) stay at their "unknown"/1.0
// defaults because .xyz declares none.
//
// The writer emits exactly "x y z [r g b]" with %.17g doubles (parse-exact
// round-trip, the pose_text fmt() precedent); non-finite coordinates are written
// as canonical "nan"/"inf"/"-inf" (never the platform CRT "-nan(ind)"/"1.#INF"
// spellings) so the output stays float()/loadtxt-parseable. It GUARDS a record it
// cannot represent (normals or intensity present) rather than silently dropping
// fields (the netpbm refuse-not-convert rule). The pure-C++ decode/encode body
// runs with the GIL released (the npy_npz.cpp precedent); nb objects are only
// touched outside that scope.
#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <system_error>

#include <nanobind/stl/filesystem.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>

#include "fast_float/fast_float.h"
#include "records/point_cloud.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

// Token separators inside one line. '\r' is a separator so a CRLF file (split on
// '\n') drops its trailing carriage return; ',' lets comma-delimited files
// through (a decimal-comma locale then fails the column-count check -- a loud
// error, never silent corruption).
inline bool is_sep(char c) { return c == ' ' || c == '\t' || c == ',' || c == '\r'; }

// Iterate whitespace/comma-separated tokens within a single line range. Runs of
// separators collapse; no std::string or istringstream is allocated per line.
struct LineToks {
    const char *p;
    const char *end;
    bool next(const char *&tb, const char *&te) {
        while (p < end && is_sep(*p)) ++p;
        if (p >= end) return false;
        tb = p;
        while (p < end && !is_sep(*p)) ++p;
        te = p;
        return true;
    }
};

size_t count_tokens(const char *b, const char *e) {
    LineToks lt{b, e};
    const char *tb, *te;
    size_t c = 0;
    while (lt.next(tb, te)) ++c;
    return c;
}

// Column count -> field schema (canonical parse order x y z [i] [rgb] [n]).
// Throws on an unsupported count.
struct Schema {
    size_t cols;
    bool has_i, has_rgb, has_nrm;
};
Schema schema_from_cols(size_t c) {
    switch (c) {
        case 3: return {3, false, false, false};  // xyz
        case 4: return {4, true, false, false};   // xyz + intensity
        case 6: return {6, false, true, false};   // xyz + rgb
        case 7: return {7, true, true, false};    // xyz + intensity + rgb
        case 9: return {9, false, true, true};    // xyz + rgb + normals
        default:
            throw std::invalid_argument("xyz: unsupported column count " + std::to_string(c) +
                                        " (supported: 3, 4, 6, 7, 9)");
    }
}

// Layout name -> field schema, for the read_xyz(layout=...) override. The name
// disambiguates the two 6-column dialects no data-only rule can tell apart:
// "xyzrgb" (6 = r g b, the auto-detect default) vs "xyzn" (6 = nx ny nz). The
// other names simply force what auto-detection would already pick, letting a
// caller assert a file's layout and get a column-count mismatch raised loudly.
Schema schema_from_name(const std::string &name) {
    if (name == "xyz") return {3, false, false, false};
    if (name == "xyzi") return {4, true, false, false};
    if (name == "xyzrgb") return {6, false, true, false};
    if (name == "xyzn") return {6, false, false, true};  // 6 cols -> NORMALS, not rgb
    if (name == "xyzirgb") return {7, true, true, false};
    if (name == "xyzrgbn") return {9, false, true, true};
    throw std::invalid_argument(
        "xyz: unknown layout '" + name +
        "' (supported: xyz, xyzi, xyzrgb, xyzn, xyzirgb, xyzrgbn)");
}

// Parse exactly `sch.cols` numbers from one line into the record. Raises with a
// 1-based line number on a non-numeric token, a wrong token count, or an rgb
// value that is not an integer in 0..255.
void parse_row(const char *ls, const char *le, const Schema &sch, size_t line_no, PointCloud &pc) {
    LineToks lt{ls, le};
    const char *tb, *te;
    auto num = [&]() -> double {
        if (!lt.next(tb, te))
            throw std::invalid_argument("xyz: line " + std::to_string(line_no) + ": expected " +
                                        std::to_string(sch.cols) + " numbers");
        double v;
        // fast_float::from_chars is the portable drop-in for std::from_chars<double>
        // (whose FP overload is missing on manylinux2014 GCC-10 / older libc++). It
        // accepts the same grammar plus "nan"/"inf" and does a full-consume check.
        const auto r = fast_float::from_chars(tb, te, v);
        if (r.ec != std::errc{} || r.ptr != te) {
            // Bound the echoed token: a hostile multi-hundred-MB "number" must not
            // multiply into the exception message (siblings never echo unbounded
            // input in error text).
            const size_t tok = static_cast<size_t>(te - tb);
            const size_t len = std::min<size_t>(tok, 40);
            std::string shown(tb, tb + len);
            if (tok > len) shown += "...";
            throw std::invalid_argument("xyz: line " + std::to_string(line_no) +
                                        ": could not parse number '" + shown + "'");
        }
        return v;
    };
    pc.xyz.push_back(static_cast<float>(num()));  // x
    pc.xyz.push_back(static_cast<float>(num()));  // y
    pc.xyz.push_back(static_cast<float>(num()));  // z
    if (sch.has_i) pc.intensity.push_back(static_cast<float>(num()));
    if (sch.has_rgb) {
        for (int k = 0; k < 3; ++k) {
            const double v = num();
            if (v != std::floor(v) || v < 0.0 || v > 255.0)
                throw std::invalid_argument(
                    "xyz: line " + std::to_string(line_no) +
                    ": r/g/b must be integers in 0..255 (float 0-1 color files are not "
                    "supported; for a 6-column normals file pass layout=\"xyzn\")");
            pc.rgb.push_back(static_cast<uint8_t>(v));
        }
    }
    if (sch.has_nrm)
        for (int k = 0; k < 3; ++k) pc.normals.push_back(static_cast<float>(num()));
    if (lt.next(tb, te))  // a token beyond the schema's column count
        throw std::invalid_argument("xyz: line " + std::to_string(line_no) + ": expected " +
                                    std::to_string(sch.cols) + " numbers");
}

// Pure-C++ decode (no Python objects touched) so it runs with the GIL released.
// `forced` (with its `forced_name` for messages) is the read_xyz(layout=...)
// override: when set, it fixes the schema and the first data line's column count
// must equal it (else raise) instead of being auto-detected.
size_t decode_xyz(const char *p, size_t n, PointCloud &pc,
                  const std::optional<Schema> &forced,
                  const std::string &forced_name, bool partial = false,
                  size_t start = 0, size_t stop = 0) {
    if (partial && start >= stop)
        throw std::invalid_argument(
            "xyz point range must be a non-empty half-open range");
    size_t newlines = 0;  // reserve capacity proportional to the input (not a header)
    for (size_t k = 0; k < n; ++k)
        if (p[k] == '\n') ++newlines;
    // Cap the reservation by the byte budget: a minimal data row ("0 0 0\n") is
    // 6 bytes, so n/6 bounds the possible data rows -- a newline/comment bomb then
    // cannot force an ~12x-input up-front allocation before a single row is parsed.
    const size_t possible_rows = std::min<size_t>(newlines + 1, n / 6 + 1);
    const size_t reserved_rows =
        partial ? std::min(stop - start, possible_rows) : possible_rows;
    pc.xyz.reserve(3 * reserved_rows);

    bool schema_set = false;
    Schema sch{};
    size_t line_no = 0;
    size_t data_row = 0;
    size_t i = 0;
    while (i < n) {
        const char *ls = p + i;
        while (i < n && p[i] != '\n') ++i;
        const char *le = p + i;
        if (i < n) ++i;  // consume the '\n'
        ++line_no;

        // blank / comment: skip leading space/tab/\r, then test for '#' or end.
        const char *c = ls;
        while (c < le && (*c == ' ' || *c == '\t' || *c == '\r')) ++c;
        if (c >= le || *c == '#') continue;
        // A separator-only remainder (e.g. a run of commas) carries no token and
        // is treated as blank rather than a zero-column row.
        {
            LineToks peek{ls, le};
            const char *tb, *te;
            if (!peek.next(tb, te)) continue;
        }
        if (!schema_set) {
            const size_t ncol = count_tokens(ls, le);
            if (forced) {
                if (ncol != forced->cols)
                    throw std::invalid_argument(
                        "xyz: layout \"" + forced_name + "\" expects " +
                        std::to_string(forced->cols) + " columns but the first data line has " +
                        std::to_string(ncol));
                sch = *forced;
            } else {
                sch = schema_from_cols(ncol);
            }
            schema_set = true;
        }
        if (!partial || (data_row >= start && data_row < stop)) {
            parse_row(ls, le, sch, line_no, pc);
        } else if (count_tokens(ls, le) != sch.cols) {
            throw std::invalid_argument(
                "xyz: line " + std::to_string(line_no) + ": expected " +
                std::to_string(sch.cols) + " numbers");
        }
        ++data_row;
    }
    if (partial && stop > data_row)
        throw std::invalid_argument("xyz point range exceeds the available extent");
    pc.n = pc.xyz.size() / 3;
    return data_row;
}

struct PtsHeader {
    size_t declared_count = 0;
    size_t body_offset = 0;
};

PtsHeader parse_pts_header(const char *p, size_t n) {
    size_t i = 0;
    size_t line_no = 0;
    while (i < n) {
        const char *line = p + i;
        while (i < n && p[i] != '\n') ++i;
        const char *end = p + i;
        if (i < n) ++i;
        ++line_no;

        const char *cursor = line;
        while (cursor < end &&
               (*cursor == ' ' || *cursor == '\t' || *cursor == '\r'))
            ++cursor;
        if (cursor >= end || *cursor == '#') continue;

        const char *begin = cursor;
        while (cursor < end &&
               *cursor != ' ' && *cursor != '\t' && *cursor != '\r')
            ++cursor;
        const char *token_end = cursor;
        while (cursor < end &&
               (*cursor == ' ' || *cursor == '\t' || *cursor == '\r'))
            ++cursor;
        if (cursor != end)
            throw std::invalid_argument(
                "pts: count header on line " + std::to_string(line_no) +
                " must contain exactly one unsigned integer");
        uint64_t declared = 0;
        const auto parsed = std::from_chars(begin, token_end, declared);
        if (parsed.ec != std::errc{} || parsed.ptr != token_end)
            throw std::invalid_argument(
                "pts: count header on line " + std::to_string(line_no) +
                " must contain exactly one unsigned integer");
        if (declared > static_cast<uint64_t>(SIZE_MAX))
            throw std::invalid_argument(
                "pts: declared point count exceeds size_t");
        return {static_cast<size_t>(declared), i};
    }
    throw std::invalid_argument(
        "pts: missing mandatory leading point-count line");
}

[[noreturn]] void rethrow_pts_error(const std::invalid_argument &error) {
    std::string message = error.what();
    if (message.rfind("xyz:", 0) == 0)
        message.replace(0, 3, "pts");
    else if (message.rfind("xyz ", 0) == 0)
        message.replace(0, 3, "pts");
    throw std::invalid_argument(std::move(message));
}

void decode_pts(const char *p, size_t n, PointCloud &pc,
                bool partial = false, size_t start = 0, size_t stop = 0) {
    const PtsHeader header = parse_pts_header(p, n);
    if (partial) {
        if (start >= stop)
            throw std::invalid_argument(
                "pts point range must be a non-empty half-open range");
        if (stop > header.declared_count)
            throw std::invalid_argument(
                "pts point range exceeds the declared point count");
    }
    size_t actual = 0;
    try {
        actual = decode_xyz(
            p + header.body_offset, n - header.body_offset, pc, {},
            "", partial, start, stop);
    } catch (const std::invalid_argument &error) {
        rethrow_pts_error(error);
    }
    if (pc.has_normals())
        throw std::invalid_argument(
            "pts: 9-column normal rows are unsupported; supported layouts are "
            "XYZ, XYZI, XYZRGB, and XYZIRGB");
    if (actual != header.declared_count)
        throw std::invalid_argument(
            "pts: declared point count " +
            std::to_string(header.declared_count) +
            " does not match " + std::to_string(actual) + " data rows");
}

size_t inspect_pts(nb::handle source) {
    sio::ByteView data(source);
    size_t count;
    {
        nb::gil_scoped_release rel;
        count = parse_pts_header(
                    reinterpret_cast<const char *>(data.data()), data.size())
                    .declared_count;
    }
    return count;
}

std::pair<size_t, size_t> inspect_xyz(nb::handle source) {
    sio::ByteView data(source);
    const char *p = reinterpret_cast<const char *>(data.data());
    const size_t n = data.size();
    size_t rows = 0;
    size_t columns = 0;
    {
        nb::gil_scoped_release rel;
        size_t i = 0;
        while (i < n) {
            const char *ls = p + i;
            while (i < n && p[i] != '\n') ++i;
            const char *le = p + i;
            if (i < n) ++i;
            const char *cursor = ls;
            while (cursor < le &&
                   (*cursor == ' ' || *cursor == '\t' || *cursor == '\r'))
                ++cursor;
            if (cursor >= le || *cursor == '#') continue;
            LineToks peek{ls, le};
            const char *tb, *te;
            if (!peek.next(tb, te)) continue;
            const size_t current = count_tokens(ls, le);
            if (columns == 0) {
                schema_from_cols(current);
                columns = current;
            } else if (current != columns) {
                throw std::invalid_argument(
                    "xyz: inconsistent column count in metadata scan");
            }
            ++rows;
        }
    }
    return {rows, columns == 0 ? 3 : columns};
}

std::pair<size_t, size_t> inspect_xyz_file(
    const std::filesystem::path &path) {
    size_t rows = 0;
    size_t columns = 0;
    {
        nb::gil_scoped_release rel;
        std::ifstream file(path, std::ios::binary);
        if (!file) throw std::invalid_argument("xyz: cannot open file");
        char block[65536];
        size_t current = 0;
        bool prefix = true;
        bool comment = false;
        bool in_token = false;
        auto finish_line = [&]() {
            if (!comment && current != 0) {
                if (columns == 0) {
                    schema_from_cols(current);
                    columns = current;
                } else if (current != columns) {
                    throw std::invalid_argument(
                        "xyz: inconsistent column count in metadata scan");
                }
                ++rows;
            }
            current = 0;
            prefix = true;
            comment = false;
            in_token = false;
        };
        while (file) {
            file.read(block, sizeof(block));
            const std::streamsize got = file.gcount();
            for (std::streamsize i = 0; i < got; ++i) {
                const char c = block[i];
                if (c == '\n') {
                    finish_line();
                    continue;
                }
                if (comment) continue;
                if (prefix) {
                    if (c == ' ' || c == '\t' || c == '\r') continue;
                    if (c == '#') {
                        comment = true;
                        continue;
                    }
                    prefix = false;
                }
                if (is_sep(c)) {
                    in_token = false;
                } else if (!in_token) {
                    ++current;
                    in_token = true;
                }
            }
        }
        if (file.bad()) throw std::invalid_argument("xyz: file read failed");
        if (!prefix || comment || current != 0) finish_line();
    }
    return {rows, columns == 0 ? 3 : columns};
}

PointCloud read_xyz(nb::handle source, std::optional<std::string> layout) {
    sio::ByteView data(source);
    const char *p = reinterpret_cast<const char *>(data.data());
    const size_t n = data.size();
    // Resolve the layout override (string work + vocabulary check) before the GIL
    // is released; decode_xyz then runs pure-C++ with the forced schema.
    std::optional<Schema> forced;
    std::string forced_name;
    if (layout.has_value()) {
        forced = schema_from_name(*layout);
        forced_name = *layout;
    }
    PointCloud pc;
    {
        nb::gil_scoped_release rel;  // pure C++ parse; `data` stays alive for the call
        decode_xyz(p, n, pc, forced, forced_name);
    }
    return pc;  // nanobind converts to the Python PointCloud with the GIL re-held
}

PointCloud read_xyz_points(nb::handle source, size_t start, size_t stop,
                           std::optional<std::string> layout) {
    sio::ByteView data(source);
    const char *p = reinterpret_cast<const char *>(data.data());
    const size_t n = data.size();
    std::optional<Schema> forced;
    std::string forced_name;
    if (layout.has_value()) {
        forced = schema_from_name(*layout);
        forced_name = *layout;
    }
    PointCloud pc;
    {
        nb::gil_scoped_release rel;
        decode_xyz(p, n, pc, forced, forced_name, true, start, stop);
    }
    return pc;
}

PointCloud read_pts(nb::handle source) {
    sio::ByteView data(source);
    PointCloud pc;
    {
        nb::gil_scoped_release rel;
        decode_pts(
            reinterpret_cast<const char *>(data.data()), data.size(), pc);
    }
    return pc;
}

PointCloud read_pts_points(nb::handle source, size_t start, size_t stop) {
    sio::ByteView data(source);
    PointCloud pc;
    {
        nb::gil_scoped_release rel;
        decode_pts(
            reinterpret_cast<const char *>(data.data()), data.size(), pc, true,
            start, stop);
    }
    return pc;
}

// Append one coordinate as canonical text. Finite values use %.17g (a float
// promoted to double is exact, so %.17g reparses to the identical float32).
// Non-finite values are written as canonical "nan"/"-nan"/"inf"/"-inf" -- NEVER
// the platform CRT spellings (MSVC/UCRT "-nan(ind)" / "1.#INF"), which
// float()/np.loadtxt and other external readers reject; the canonical tokens
// keep the output parseable everywhere and re-read through our fast_float reader.
void append_coord(char *&out, float f) {
    if (std::isnan(f)) {
        const char *token = std::signbit(f) ? "-nan" : "nan";
        const size_t size = std::signbit(f) ? 4 : 3;
        std::memcpy(out, token, size);
        out += size;
    } else if (std::isinf(f)) {
        const char *token = std::signbit(f) ? "-inf" : "inf";
        const size_t size = std::signbit(f) ? 4 : 3;
        std::memcpy(out, token, size);
        out += size;
    } else {
        char buf[64];
        const int size =
            std::snprintf(buf, sizeof(buf), "%.17g", static_cast<double>(f));
        if (size < 0 || static_cast<size_t>(size) >= sizeof(buf))
            throw std::runtime_error("xyz: float formatter failed");
        std::memcpy(out, buf, static_cast<size_t>(size));
        out += size;
    }
}

void append_u8(char *&out, uint8_t value) {
    const unsigned v = value;
    if (v >= 100) {
        *out++ = static_cast<char>('0' + v / 100);
        *out++ = static_cast<char>('0' + (v / 10) % 10);
    } else if (v >= 10) {
        *out++ = static_cast<char>('0' + v / 10);
    }
    *out++ = static_cast<char>('0' + v % 10);
}

// Pure-C++ encode of "x y z [intensity] [r g b]" rows. XYZ disables the
// intensity branch; PTS enables it when the record carries that field.
void encode_xyz(const PointCloud &pc, std::string &out,
                size_t requested_lanes, bool include_intensity = false) {
    const bool rgb = pc.has_rgb();
    const size_t row_capacity =
        include_intensity ? (rgb ? 128 : 104) : (rgb ? 96 : 72);
    if (pc.n > out.max_size() / row_capacity)
        throw std::length_error("xyz: encoded text is too large");
    out.resize(pc.n * row_capacity);
    std::vector<size_t> starts(kMaxParallelLanes);
    std::vector<size_t> used(kMaxParallelLanes);
    const size_t lanes = parallel_for_blocks(
        pc.n, requested_lanes, 32768,
        [&](size_t begin, size_t end, size_t lane) {
            char *dst = out.data() + begin * row_capacity;
            starts[lane] = begin * row_capacity;
            char *const block_begin = dst;
            for (size_t i = begin; i < end; ++i) {
                char row[128];
                char *cursor = row;
                for (int k = 0; k < 3; ++k) {
                    if (k) *cursor++ = ' ';
                    append_coord(cursor, pc.xyz[3 * i + k]);
                }
                if (include_intensity) {
                    *cursor++ = ' ';
                    append_coord(cursor, pc.intensity[i]);
                }
                if (rgb) {
                    for (int k = 0; k < 3; ++k) {
                        *cursor++ = ' ';
                        append_u8(cursor, pc.rgb[3 * i + k]);
                    }
                }
                *cursor++ = '\n';
                const size_t row_size = static_cast<size_t>(cursor - row);
                if (row_size > row_capacity)
                    throw std::logic_error("xyz: formatted row exceeded its bound");
                std::memcpy(dst, row, row_size);
                dst += row_size;
            }
            used[lane] = static_cast<size_t>(dst - block_begin);
        });

    size_t compacted = 0;
    for (size_t lane = 0; lane < lanes; ++lane) {
        std::memmove(out.data() + compacted, out.data() + starts[lane],
                     used[lane]);
        compacted += used[lane];
    }
    out.resize(compacted);
}

nb::bytes write_xyz(const PointCloud &pc, size_t lanes) {
    require_no_extended_point_fields(pc, "xyz");
    // Guards: the .xyz row is exactly "x y z [r g b]"; refuse a record whose
    // normals/intensity it cannot carry rather than silently dropping them (the
    // netpbm refuse-not-convert rule -- a normalizer converts, on request).
    if (pc.has_normals())
        throw std::invalid_argument(
            "xyz: writer emits 'x y z [r g b]'; a record with normals cannot round-trip -- "
            "drop normals first");
    if (pc.has_intensity())
        throw std::invalid_argument(
            "xyz: writer emits 'x y z [r g b]'; a record with intensity cannot round-trip -- "
            "drop intensity first");
    if (pc.has_rgb16())
        throw std::invalid_argument(
            "xyz: writer emits 8-bit 'x y z [r g b]'; a record with 16-bit colors16 cannot "
            "round-trip -- narrow to 8-bit rgb first");
    if (pc.origin[0] != 0.0 || pc.origin[1] != 0.0 || pc.origin[2] != 0.0)
        throw std::invalid_argument(
            "xyz: writer emits local coordinates; a georeferenced record (origin != 0) would lose "
            "its anchor -- bake origin into positions first");
    if (!pc.has_default_organization() || !pc.has_default_viewpoint())
        throw std::invalid_argument(
            "xyz: organized shape and acquisition viewpoint metadata are not representable");
    std::string out;
    {
        nb::gil_scoped_release rel;  // pure C++ encode
        encode_xyz(pc, out, lanes);
    }
    return emit_bytes(out.data(), out.size());
}

nb::bytes write_pts(const PointCloud &pc, size_t lanes) {
    require_no_extended_point_fields(pc, "pts");
    if (pc.has_normals())
        throw std::invalid_argument(
            "pts: supported rows are XYZ, XYZI, XYZRGB, or XYZIRGB; a record "
            "with normals cannot round-trip");
    if (pc.has_rgb16())
        throw std::invalid_argument(
            "pts: colors are 8-bit integers; a record with 16-bit colors16 "
            "cannot round-trip");
    if (pc.origin[0] != 0.0 || pc.origin[1] != 0.0 || pc.origin[2] != 0.0)
        throw std::invalid_argument(
            "pts: georeferenced origin metadata is not representable; bake "
            "the origin into positions first");
    if (pc.coordinate_frame != "unknown" || pc.scale_to_meters != 1.0)
        throw std::invalid_argument(
            "pts: coordinate frame and scale metadata are not representable");
    if (!pc.has_default_organization() || !pc.has_default_viewpoint())
        throw std::invalid_argument(
            "pts: organized shape and acquisition viewpoint metadata are not representable");
    if (pc.intensity_range != "unknown")
        throw std::invalid_argument(
            "pts: intensity range metadata is not representable");
    std::string out;
    {
        nb::gil_scoped_release rel;
        encode_xyz(pc, out, lanes, pc.has_intensity());
        out.insert(0, std::to_string(pc.n) + "\n");
    }
    return emit_bytes(out.data(), out.size());
}

}  // namespace

void register_xyz(nb::module_ &m) {
    m.def("_inspect_xyz", &inspect_xyz, "data"_a,
          "Return (point_count, column_count) without parsing numeric samples.");
    m.def("_inspect_xyz_file", &inspect_xyz_file, "path"_a,
          "Stream a file and return (point_count, column_count) without parsing "
          "numeric samples.");
    m.def("read_xyz", &read_xyz, "data"_a, "layout"_a = nb::none(),
          "Decode .xyz point-cloud text into a PointCloud. Columns are auto-detected from the "
          "first data line (3 = x y z; 4 = + intensity; 6 = + rgb; 7 = + intensity + rgb; "
          "9 = + rgb + normals); blank and '#'-comment lines are skipped; rgb is stored raw as "
          "uint8 0..255 and never rescaled. Pass layout= to force a schema and assert the file's "
          "columns -- one of \"xyz\", \"xyzi\", \"xyzrgb\", \"xyzn\", \"xyzirgb\", \"xyzrgbn\"; "
          "\"xyzn\" reads the ambiguous 6-column form as normals (nx ny nz) instead of rgb. A "
          "declared layout whose column count differs from the first data line raises.");
    m.def("read_xyz_points", &read_xyz_points, "data"_a, "start"_a,
          "stop"_a, "layout"_a = nb::none(),
          "Decode one non-empty half-open point range from .xyz text while "
          "allocating only the selected records.");
    m.def("write_xyz", &write_xyz, "pc"_a, "_lanes"_a = 0,
          "Encode a PointCloud as .xyz text: 'x y z' or 'x y z r g b' rows with %.17g doubles "
          "(parse-exact round-trip; non-finite values emitted as canonical nan/inf/-inf). "
          "Large clouds use bounded parallel formatting. "
          "Refuses a record carrying normals or intensity (which the 'x y z [r g b]' layout "
          "cannot represent) rather than dropping them.");
    m.def("_inspect_pts", &inspect_pts, "data"_a,
          "Return the declared PTS point count after parsing only its leading "
          "count header.");
    m.def("read_pts", &read_pts, "data"_a,
          "Decode count-prefixed PTS text into a PointCloud. The mandatory "
          "first data line is an unsigned point count; supported point rows "
          "are XYZ, XYZI, XYZRGB, and XYZIRGB.");
    m.def("read_pts_points", &read_pts_points, "data"_a, "start"_a,
          "stop"_a,
          "Decode one non-empty half-open point range from count-prefixed PTS "
          "while allocating only the selected rows.");
    m.def("write_pts", &write_pts, "pc"_a, "_lanes"_a = 0,
          "Encode a PointCloud as deterministic count-prefixed PTS text using "
          "XYZ, XYZI, XYZRGB, or XYZIRGB rows. Refuses normals, 16-bit colors, "
          "georeferencing, and non-default convention tags.");
}
