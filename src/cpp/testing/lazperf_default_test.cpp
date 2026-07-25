#include <lazperf/decompressor.hpp>

#include <cstring>
#include <cstdint>

namespace {

struct ControlledDecoder {
    template <typename Model>
    uint32_t decodeSymbol(Model &) {
        return calls++ == 0 ? 31u : 255u;
    }

    uint32_t readBits(uint32_t bits) {
        return bits == 23 ? ((uint32_t{1} << 23) - 1) : 0;
    }

    template <typename Model>
    uint32_t decodeBit(Model &) {
        return 0;
    }

    uint32_t calls = 0;
};

}  // namespace

bool sceneio_test_lazperf_default_corrector_rejects() {
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
