// io/gzip.hpp — gzip inflate via miniz, for compressed codecs (SPZ, and any
// future gzip-wrapped format). Reader-only for now.
#pragma once

#include <miniz.h>

#include <cstdint>
#include <stdexcept>
#include <vector>

namespace sio {

// Inflate a gzip stream: skip the gzip header (honoring FLG optional fields)
// then raw-deflate-decompress the body via miniz's tinfl.
inline std::vector<uint8_t> gunzip(const uint8_t *p, size_t n) {
    if (n < 18 || p[0] != 0x1f || p[1] != 0x8b || p[2] != 0x08)
        throw std::invalid_argument("gzip: not a gzip stream");
    const uint8_t flg = p[3];
    size_t off = 10;
    if (flg & 4) {  // FEXTRA
        if (off + 2 > n) throw std::invalid_argument("gzip: truncated FEXTRA");
        off += 2 + (static_cast<size_t>(p[off]) | (static_cast<size_t>(p[off + 1]) << 8));
    }
    if (flg & 8) { while (off < n && p[off] != 0) off++; off++; }   // FNAME
    if (flg & 16) { while (off < n && p[off] != 0) off++; off++; }  // FCOMMENT
    if (flg & 2) off += 2;                                          // FHCRC
    if (off + 8 > n) throw std::invalid_argument("gzip: truncated body");
    size_t out_len = 0;
    void *out = tinfl_decompress_mem_to_heap(p + off, n - off - 8, &out_len, 0);
    if (!out) throw std::invalid_argument("gzip: inflate failed (corrupt stream?)");
    std::vector<uint8_t> res(static_cast<uint8_t *>(out), static_cast<uint8_t *>(out) + out_len);
    mz_free(out);
    return res;
}

}  // namespace sio
