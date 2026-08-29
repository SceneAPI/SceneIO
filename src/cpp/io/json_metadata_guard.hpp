#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace sio {

// nlohmann/json includes the current token in parse diagnostics. Rejecting an
// implausibly large metadata token before DOM parsing keeps malformed JSON from
// constructing an input-sized exception and also bounds per-token DOM scratch.
inline void guard_json_metadata_tokens(const uint8_t *data, size_t size,
                                       const char *format) {
    constexpr size_t kTokenLimit = 1024 * 1024;
    bool in_string = false;
    bool escaped = false;
    size_t token_size = 0;
    size_t depth = 0;
    for (size_t i = 0; i < size; ++i) {
        const uint8_t c = data[i];
        if (in_string) {
            if (escaped) {
                escaped = false;
                ++token_size;
            } else if (c == '\\') {
                escaped = true;
                ++token_size;
            } else if (c == '"') {
                in_string = false;
                token_size = 0;
                continue;
            } else {
                ++token_size;
            }
        } else if (c == '"') {
            in_string = true;
            token_size = 0;
            continue;
        } else if (c == '{' || c == '[') {
            if (++depth > 256)
                throw std::invalid_argument(
                    std::string(format) +
                    ": metadata nesting exceeds 256 levels");
            token_size = 0;
            continue;
        } else if (c == '}' || c == ']') {
            if (depth != 0) --depth;
            token_size = 0;
            continue;
        } else if (c == ' ' || c == '\t' || c == '\r' || c == '\n' ||
                   c == ':' || c == ',') {
            token_size = 0;
            continue;
        } else {
            ++token_size;
        }
        if (token_size > kTokenLimit)
            throw std::invalid_argument(std::string(format) +
                                        ": metadata token exceeds 1 MiB");
    }
}

}  // namespace sio
