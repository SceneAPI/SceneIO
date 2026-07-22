// netpbm codec — PGM (P5 binary / P2 ascii) and PPM (P6 binary / P3 ascii)
// into the shared Image record (records/image.hpp). The reader is whitespace/
// comment tolerant, stores RAW samples (never rescaled), records `maxval` and
// `color_space` as metadata, and reads 16-bit samples as big-endian-on-disk ->
// native uint16. The writer emits binary P5/P6 by default (ascii=true -> P2/P3
// with 70-column wrap) and GUARDS foreign conventions (dtype/maxval pairing,
// channel/color_space pairing, samples <= maxval; refuses float32 and RGBA)
// rather than silently converting. PBM (P1/P4) and PAM (P7) are refused.
//
// Rows are top-to-bottom (the opposite of PFM). Endianness is resolved here so
// Python always sees a native-endian array. All malformed input raises
// std::invalid_argument (mapped to FormatError by the io layer); the per-axis
// dimension cap plus a bounds check *before* every allocation mean a crafted
// tiny header can never trigger a large/OOM allocation. Like pfm/spz this holds
// the GIL through decode/encode — no Python objects are touched in the hot
// loops, so a later GIL-release retrofit (roadmap §1.3) is safe but is deferred
// here to keep parity with the rest of the tree.
#include "records/image.hpp"

using namespace nb::literals;
using namespace sio;

namespace {

// 1e9 per axis: keeps width*height*channels*bytes-per-sample well inside uint64
// and rejects absurd headers up front. A genuinely larger raster is refused, not
// a real-world concern for a debug/interchange format.
constexpr uint64_t kDimCap = 1000000000ull;

inline bool is_ws(uint8_t c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f';
}
inline bool is_digit(uint8_t c) { return c >= '0' && c <= '9'; }

// Skip runs of whitespace and '#'..end-of-line comments (the netpbm header
// grammar allows comments before/between any header token). The comment's
// terminating newline is left in place for the whitespace pass to consume.
void skip_ws_comments(const uint8_t *p, size_t n, size_t &pos) {
    for (;;) {
        while (pos < n && is_ws(p[pos])) pos++;
        if (pos < n && p[pos] == '#') {
            while (pos < n && p[pos] != '\n' && p[pos] != '\r') pos++;
        } else {
            break;
        }
    }
}

// Parse one unsigned decimal token (after skipping leading ws/comments). Raises
// on a missing number and on any value exceeding `cap`. `cap` is always far
// below UINT64_MAX, so the running accumulator can never overflow before the
// guard fires (crafted-header DoS protection).
uint64_t next_uint(const uint8_t *p, size_t n, size_t &pos, uint64_t cap, const char *what) {
    skip_ws_comments(p, n, pos);
    if (pos >= n || !is_digit(p[pos]))
        throw std::invalid_argument(std::string("netpbm: expected a number for ") + what);
    uint64_t v = 0;
    while (pos < n && is_digit(p[pos])) {
        v = v * 10 + static_cast<uint64_t>(p[pos] - '0');
        if (v > cap) throw std::invalid_argument(std::string("netpbm: ") + what + " out of range");
        pos++;
    }
    return v;
}

Image read_netpbm(nb::bytes data) {
    const uint8_t *p = reinterpret_cast<const uint8_t *>(data.c_str());
    const size_t n = data.size();
    if (n < 2 || p[0] != 'P')
        throw std::invalid_argument("netpbm: bad magic (expected P2/P3/P5/P6)");

    bool ascii;
    size_t C;
    switch (p[1]) {
        case '5': ascii = false; C = 1; break;  // PGM binary
        case '6': ascii = false; C = 3; break;  // PPM binary
        case '2': ascii = true;  C = 1; break;  // PGM ascii
        case '3': ascii = true;  C = 3; break;  // PPM ascii
        case '1':
        case '4':
            throw std::invalid_argument("netpbm: PBM (P1/P4) 1-bit images are not supported");
        case '7':
            throw std::invalid_argument("netpbm: PAM (P7) is not supported");
        default:
            throw std::invalid_argument("netpbm: bad magic (expected P2/P3/P5/P6)");
    }

    size_t pos = 2;
    const uint64_t W = next_uint(p, n, pos, kDimCap, "width");
    const uint64_t H = next_uint(p, n, pos, kDimCap, "height");
    const uint64_t maxval = next_uint(p, n, pos, 65535ull, "maxval");
    if (W == 0 || H == 0) throw std::invalid_argument("netpbm: non-positive dimensions");
    if (maxval < 1) throw std::invalid_argument("netpbm: maxval must be >= 1");

    const bool wide = maxval > 255;  // 2 bytes/sample, big-endian on disk
    const uint64_t count = W * H * static_cast<uint64_t>(C);  // <= 3e18, no overflow (dims capped)

    Image im;
    im.height = static_cast<size_t>(H);
    im.width = static_cast<size_t>(W);
    im.channels = C;
    im.dtype = wide ? PixelType::U16 : PixelType::U8;
    im.color_space = (C == 1) ? "gray" : "srgb";  // reconciled Image vocabulary
    im.alpha_mode = "none";                        // C is 1 or 3, never 4
    im.maxval = static_cast<uint32_t>(maxval);

    if (!ascii) {
        // Binary: consume EXACTLY ONE delimiter byte after the maxval digits.
        // A comment glued directly to maxval is consumed through its terminating
        // newline, which then serves as that single delimiter (the libnetpbm
        // pm_getuint rule). Raster bytes that look like whitespace are DATA and
        // must survive, so we never skip more than one delimiter byte here.
        if (pos < n && p[pos] == '#') {
            while (pos < n && p[pos] != '\n' && p[pos] != '\r') pos++;
            if (pos >= n) throw std::invalid_argument("netpbm: truncated header (missing raster)");
            pos++;  // the newline is the single delimiter
        } else if (pos < n && is_ws(p[pos])) {
            pos++;  // exactly one whitespace delimiter
        } else {
            throw std::invalid_argument("netpbm: expected whitespace before binary raster");
        }
        const uint64_t bps = wide ? 2 : 1;
        const uint64_t nbytes = count * bps;  // <= 6e18, no overflow
        // Bounds-check BEFORE allocating so a 30-byte file cannot request GiB.
        if (nbytes > static_cast<uint64_t>(n - pos))
            throw std::invalid_argument("netpbm: truncated raster");
        const uint8_t *src = p + pos;
        const size_t cnt = static_cast<size_t>(count);
        if (!wide) {
            im.u8.assign(src, src + cnt);  // zero-transform bulk copy
        } else {
            im.u16.resize(cnt);
            for (size_t i = 0; i < cnt; i++)  // big-endian on disk -> native
                im.u16[i] = static_cast<uint16_t>((static_cast<uint16_t>(src[2 * i]) << 8) |
                                                  static_cast<uint16_t>(src[2 * i + 1]));
        }
    } else {
        // ASCII: pre-guard against an OOM alloc from a tiny file (each sample
        // needs >= 1 byte), then parse `count` whitespace/comment-separated
        // decimals. A sample may exceed maxval (reader records, does not judge)
        // but must fit the dtype; an overflowing token raises.
        if (count > static_cast<uint64_t>(n - pos))
            throw std::invalid_argument("netpbm: truncated raster");
        const uint64_t cap = wide ? 65535ull : 255ull;  // dtype max, not maxval
        const size_t cnt = static_cast<size_t>(count);
        if (!wide) {
            im.u8.resize(cnt);
            for (size_t i = 0; i < cnt; i++)
                im.u8[i] = static_cast<uint8_t>(next_uint(p, n, pos, cap, "sample"));
        } else {
            im.u16.resize(cnt);
            for (size_t i = 0; i < cnt; i++)
                im.u16[i] = static_cast<uint16_t>(next_uint(p, n, pos, cap, "sample"));
        }
    }
    // Trailing bytes after the raster are ignored (PFM precedent).
    return im;
}

nb::bytes write_netpbm(const Image &img, bool ascii) {
    // --- guards: refuse conventions netpbm cannot represent (never convert) ---
    if (img.dtype == PixelType::F32)
        throw std::invalid_argument(
            "netpbm: cannot store float32 pixels (PGM/PPM are integer formats)");
    if (img.channels == 4)
        throw std::invalid_argument(
            "netpbm: RGBA (4-channel) images are not representable in PGM/PPM");

    const char *magic;
    if (img.channels == 1) {
        if (img.color_space != "gray")
            throw std::invalid_argument(
                "netpbm: PGM (1 channel) requires color_space 'gray' (got '" + img.color_space + "')");
        magic = ascii ? "P2" : "P5";
    } else if (img.channels == 3) {
        if (img.color_space != "srgb")
            throw std::invalid_argument(
                "netpbm: PPM (3 channels) requires color_space 'srgb' (got '" + img.color_space +
                "'; convert linear->srgb first)");
        magic = ascii ? "P3" : "P6";
    } else {
        throw std::invalid_argument(
            "netpbm: only 1-channel (PGM) or 3-channel (PPM) images are supported");
    }

    const uint32_t maxval = img.maxval;
    const bool wide = (img.dtype == PixelType::U16);
    if (!wide) {  // U8 <-> maxval 1..255
        if (maxval < 1 || maxval > 255)
            throw std::invalid_argument(
                "netpbm: dtype/maxval mismatch (uint8 needs maxval in 1..255) — convert the record first");
    } else {  // U16 <-> maxval 256..65535 (a u16 buffer with maxval<=255 is foreign, not auto-narrowed)
        if (maxval < 256 || maxval > 65535)
            throw std::invalid_argument(
                "netpbm: dtype/maxval mismatch (uint16 needs maxval in 256..65535) — convert the record first");
    }

    const size_t count = img.num_samples();
    // Every sample must fit the declared maxval. O(N) extra pass — negligible for
    // a debug/interchange format, flagged so a future profile doesn't mistake it
    // for accidental work.
    if (!wide) {
        for (size_t i = 0; i < count; i++)
            if (static_cast<uint32_t>(img.u8[i]) > maxval)
                throw std::invalid_argument("netpbm: pixel value exceeds declared maxval");
    } else {
        for (size_t i = 0; i < count; i++)
            if (static_cast<uint32_t>(img.u16[i]) > maxval)
                throw std::invalid_argument("netpbm: pixel value exceeds declared maxval");
    }

    // --- header: magic, WIDTH HEIGHT, MAXVAL; the trailing '\n' is the single delimiter ---
    std::string out;
    out += magic;
    out += '\n';
    out += std::to_string(img.width);
    out += ' ';
    out += std::to_string(img.height);
    out += '\n';
    out += std::to_string(maxval);
    out += '\n';

    if (!ascii) {
        if (!wide) {
            out.reserve(out.size() + count);
            out.append(reinterpret_cast<const char *>(img.u8.data()), count);
        } else {
            out.reserve(out.size() + count * 2);
            for (size_t i = 0; i < count; i++) {
                const uint16_t v = img.u16[i];
                out.push_back(static_cast<char>((v >> 8) & 0xff));  // big-endian: hi byte first
                out.push_back(static_cast<char>(v & 0xff));
            }
        }
    } else {
        // Plain P2/P3: decimal tokens, a newline at each image-row boundary AND
        // wrapped so no line exceeds 70 chars (the plain-format line limit;
        // strict readers reject longer lines). Trailing newline.
        const size_t row_samples = img.width * img.channels;
        size_t line_len = 0;
        for (size_t y = 0; y < img.height; y++) {
            for (size_t x = 0; x < row_samples; x++) {
                const uint32_t v =
                    wide ? static_cast<uint32_t>(img.u16[y * row_samples + x])
                         : static_cast<uint32_t>(img.u8[y * row_samples + x]);
                const std::string tok = std::to_string(v);
                if (line_len != 0 && line_len + 1 + tok.size() > 70) {
                    out += '\n';
                    line_len = 0;
                }
                if (line_len != 0) {
                    out += ' ';
                    line_len += 1;
                }
                out += tok;
                line_len += tok.size();
            }
            out += '\n';  // end of image row
            line_len = 0;
        }
    }
    return nb::bytes(out.data(), out.size());
}

}  // namespace

void register_netpbm(nb::module_ &m) {
    m.def("read_netpbm", &read_netpbm, "data"_a,
          "Decode PGM (P5/P2) or PPM (P6/P3) bytes into an Image: top-to-bottom rows, "
          "raw samples (no rescale), 16-bit read big-endian-on-disk -> native uint16; "
          "maxval and color_space (gray/srgb) recorded as metadata.");
    m.def("write_netpbm", &write_netpbm, "img"_a, "ascii"_a = false,
          "Encode an Image to PGM/PPM bytes: binary P5/P6 by default, ASCII P2/P3 when "
          "ascii=True (70-column wrap). Guards dtype/maxval and channel/color_space "
          "pairings and refuses float32/RGBA (netpbm stores integer gray/rgb only).");
}
