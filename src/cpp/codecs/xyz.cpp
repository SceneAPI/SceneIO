// codecs/xyz.cpp — the .xyz point-cloud TEXT codec into the shared PointCloud
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
// a 1-based line number. The 6-column form is ALWAYS rgb; a 6-column normals
// dialect is not auto-detected (there is no data-only way to tell them apart).
//
// Numbers are parsed with std::from_chars (MSVC C++17 supports float + int) --
// never std::istringstream. Values are stored verbatim: xyz/normals/intensity
// as float32, rgb as uint8; nothing is rescaled (the reader records, it does not
// judge -- the netpbm maxval-is-metadata precedent). Conventions the record
// carries (coordinate_frame/scale_to_meters/intensity_range) stay at their
// "unknown"/1.0 defaults because .xyz declares none.
//
// The writer emits exactly "x y z [r g b]" with %.17g doubles (parse-exact
// round-trip, the pose_text fmt() precedent) and GUARDS a record it cannot
// represent (normals or intensity present) rather than silently dropping fields
// (the netpbm refuse-not-convert rule). The pure-C++ decode/encode body runs
// with the GIL released (the npy_npz.cpp precedent); nb objects are only touched
// outside that scope.
#include <charconv>
#include <cmath>
#include <cstdio>
#include <system_error>

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
        const std::from_chars_result r = std::from_chars(tb, te, v);
        if (r.ec != std::errc{} || r.ptr != te)
            throw std::invalid_argument("xyz: line " + std::to_string(line_no) +
                                        ": could not parse number '" + std::string(tb, te) + "'");
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
                    ": r/g/b must be integers in 0..255 (float 0-1 color files are not supported)");
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
void decode_xyz(const char *p, size_t n, PointCloud &pc) {
    size_t newlines = 0;  // reserve capacity proportional to the input (not a header)
    for (size_t k = 0; k < n; ++k)
        if (p[k] == '\n') ++newlines;
    pc.xyz.reserve((newlines + 1) * 3);

    bool schema_set = false;
    Schema sch{};
    size_t line_no = 0;
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
            sch = schema_from_cols(count_tokens(ls, le));
            schema_set = true;
        }
        parse_row(ls, le, sch, line_no, pc);
    }
    pc.n = pc.xyz.size() / 3;
}

PointCloud read_xyz(nb::bytes data) {
    const char *p = data.c_str();   // grab the buffer while the GIL is held
    const size_t n = data.size();
    PointCloud pc;
    {
        nb::gil_scoped_release rel;  // pure C++ parse; `data` stays alive for the call
        decode_xyz(p, n, pc);
    }
    return pc;  // nanobind converts to the Python PointCloud with the GIL re-held
}

// Pure-C++ encode of "x y z [r g b]" rows.
void encode_xyz(const PointCloud &pc, std::string &out) {
    const bool rgb = pc.has_rgb();
    out.reserve(pc.n * (rgb ? 96 : 72));
    char buf[64];
    for (size_t i = 0; i < pc.n; ++i) {
        for (int k = 0; k < 3; ++k) {
            if (k) out.push_back(' ');
            // promote float32 -> double (exact) so %.17g reparses to the same float
            std::snprintf(buf, sizeof(buf), "%.17g", static_cast<double>(pc.xyz[3 * i + k]));
            out += buf;
        }
        if (rgb) {
            for (int k = 0; k < 3; ++k) {
                out.push_back(' ');
                out += std::to_string(static_cast<unsigned>(pc.rgb[3 * i + k]));
            }
        }
        out.push_back('\n');
    }
}

nb::bytes write_xyz(const PointCloud &pc) {
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
    std::string out;
    {
        nb::gil_scoped_release rel;  // pure C++ encode
        encode_xyz(pc, out);
    }
    return nb::bytes(out.data(), out.size());
}

}  // namespace

void register_xyz(nb::module_ &m) {
    m.def("read_xyz", &read_xyz, "data"_a,
          "Decode .xyz point-cloud text into a PointCloud. Columns are auto-detected from the "
          "first data line (3 = x y z; 4 = + intensity; 6 = + rgb; 7 = + intensity + rgb; "
          "9 = + rgb + normals); blank and '#'-comment lines are skipped; rgb is stored raw as "
          "uint8 0..255 and never rescaled.");
    m.def("write_xyz", &write_xyz, "pc"_a,
          "Encode a PointCloud as .xyz text: 'x y z' or 'x y z r g b' rows with %.17g doubles "
          "(parse-exact round-trip). Refuses a record carrying normals or intensity (which the "
          "'x y z [r g b]' layout cannot represent) rather than dropping them.");
}
