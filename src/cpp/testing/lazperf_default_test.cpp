#include <lazperf/compressor.hpp>
#include <lazperf/decompressor.hpp>
#include <lazperf/utils.hpp>

#include <cstring>
#include <cstdint>
#include <limits>
#include <utility>
#include <vector>

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

struct ControlledEncoder {
    template <typename Model>
    void encodeSymbol(Model &, uint32_t symbol) {
        symbols.push_back(symbol);
    }

    template <typename Model>
    void encodeBit(Model &, uint32_t bit) {
        bits.push_back(bit);
    }

    void writeBits(uint32_t count, uint32_t value) {
        raw_bits.emplace_back(count, value);
    }

    std::vector<uint32_t> symbols;
    std::vector<uint32_t> bits;
    std::vector<std::pair<uint32_t, uint32_t>> raw_bits;
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

bool sceneio_test_lazperf_wrapped_coordinate_arithmetic() {
    constexpr int32_t minimum = (std::numeric_limits<int32_t>::min)();
    constexpr int32_t maximum = (std::numeric_limits<int32_t>::max)();
    return lazperf::utils::wrapAddInt32(maximum, 1) == minimum &&
           lazperf::utils::wrapAddInt32(minimum, -1) == maximum &&
           lazperf::utils::wrapAddInt32(minimum, minimum) == 0 &&
           lazperf::utils::wrapSubtractInt32(minimum, maximum) == 1 &&
           lazperf::utils::wrapSubtractInt32(maximum, minimum) == -1 &&
           lazperf::utils::wrapSubtractInt32(minimum, 1) == maximum;
}

bool sceneio_test_lazperf_compressor_full_range() {
    constexpr int32_t minimum = (std::numeric_limits<int32_t>::min)();
    constexpr int32_t maximum = (std::numeric_limits<int32_t>::max)();
    lazperf::compressors::integer compressor(32, 1);
    compressor.init();
    ControlledEncoder encoder;
    compressor.compress(encoder, maximum, minimum, 0);
    compressor.compress(encoder, minimum, maximum, 0);
    compressor.compress(encoder, 0, minimum, 0);
    compressor.compress(encoder, 0, -(int32_t{1} << 30), 0);
    return encoder.symbols ==
               std::vector<uint32_t>({0, 1, 0, 32, 31, 127}) &&
           encoder.bits == std::vector<uint32_t>({1}) &&
           encoder.raw_bits == std::vector<std::pair<uint32_t, uint32_t>>(
                                   {{23, (uint32_t{1} << 23) - 1}});
}
