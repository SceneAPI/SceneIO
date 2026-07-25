#define COMPRESS_ONLY_K
#include <lazperf/decompressor.hpp>

#include <cstring>
#include <cstdint>

namespace {

struct ControlledDecoder {
    template <typename Model>
    uint32_t decodeSymbol(Model &) {
        return 31;
    }

    uint32_t readBits(uint32_t bits) {
        return bits == 31 ? (uint32_t{1} << 31) - 1 : 0;
    }

    uint32_t readBit() {
        return 0;
    }
};

}  // namespace

bool sceneio_test_lazperf_compact_corrector_rejects() {
    lazperf::decompressors::integer decompressor(32, 1, 8);
    decompressor.init();
    ControlledDecoder decoder;
    try {
        (void)decompressor.decompress(decoder, 0, 0);
    } catch (const lazperf::error &error) {
        return std::strcmp(
                   error.what(),
                   "LAZperf integer corrector is out of range") == 0;
    }
    return false;
}
