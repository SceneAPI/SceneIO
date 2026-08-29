// origin: FreeBSD /usr/src/lib/msun/src/s_log1p.c
/*
 * ====================================================
 * Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
 *
 * Developed at SunPro, a Sun Microsystems, Inc. business.
 * Permission to use, copy, modify, and distribute this
 * software is freely granted, provided that this notice
 * is preserved.
 * ====================================================
 */
// Adapted from musl 1.2.5's src/math/log1p.c for deterministic SOG
// serialization. See COMMIT.txt in this directory for the exact source and
// the local changes.
#pragma once

#include <cstdint>
#include <cstring>

namespace sio::third_party::musl {
namespace detail {

inline uint64_t bits_from_double(double value) noexcept {
    uint64_t bits = 0;
    static_assert(sizeof(bits) == sizeof(value));
    std::memcpy(&bits, &value, sizeof(bits));
    return bits;
}

inline double double_from_bits(uint64_t bits) noexcept {
    double value = 0.0;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

// The supported x86-64 and ARM64 targets evaluate these double operations at
// binary64 precision. Materializing multiplication results is the additional
// step needed to prevent a compiler from contracting a later addition into a
// fused multiply-add.
inline double add(double left, double right) noexcept {
    return left + right;
}

inline double subtract(double left, double right) noexcept {
    return left - right;
}

inline double multiply(double left, double right) noexcept {
    volatile double result = left * right;
    return result;
}

inline double divide(double left, double right) noexcept {
    return left / right;
}

}  // namespace detail

// Return log(1 + x) for finite x >= 0 using the fdlibm reduction and
// polynomial carried by musl. SceneIO only needs this deliberately narrower
// domain because SOG applies it to abs(float32_position).
inline double deterministic_log1p_nonnegative(double x) noexcept {
    constexpr double kLn2High = 6.93147180369123816490e-01;
    constexpr double kLn2Low = 1.90821492927058770002e-10;
    constexpr double kLg1 = 6.666666666666735130e-01;
    constexpr double kLg2 = 3.999999999940941908e-01;
    constexpr double kLg3 = 2.857142874366239149e-01;
    constexpr double kLg4 = 2.222219843214978396e-01;
    constexpr double kLg5 = 1.818357216161805012e-01;
    constexpr double kLg6 = 1.531383769920937332e-01;
    constexpr double kLg7 = 1.479819860511658591e-01;

    using detail::add;
    using detail::bits_from_double;
    using detail::divide;
    using detail::double_from_bits;
    using detail::multiply;
    using detail::subtract;

    uint64_t bits = bits_from_double(x);
    uint32_t high = static_cast<uint32_t>(bits >> 32);
    int exponent = 1;
    double correction = 0.0;
    double reduced = 0.0;

    if (high < 0x3fda827aU) {
        if (high < 0x3ca00000U)
            return x;
        exponent = 0;
        reduced = x;
    } else if (high >= 0x7ff00000U) {
        return x;
    }

    if (exponent != 0) {
        const double sum = add(1.0, x);
        bits = bits_from_double(sum);
        high = static_cast<uint32_t>(bits >> 32);
        high += 0x3ff00000U - 0x3fe6a09eU;
        exponent = static_cast<int>(high >> 20) - 0x3ff;

        if (exponent < 54) {
            correction =
                exponent >= 2
                    ? subtract(1.0, subtract(sum, x))
                    : subtract(x, subtract(sum, 1.0));
            correction = divide(correction, sum);
        }

        high = (high & 0x000fffffU) + 0x3fe6a09eU;
        bits = (static_cast<uint64_t>(high) << 32) |
               (bits & 0xffffffffULL);
        reduced = subtract(double_from_bits(bits), 1.0);
    }

    const double half_square =
        multiply(multiply(0.5, reduced), reduced);
    const double ratio = divide(reduced, add(2.0, reduced));
    const double ratio_square = multiply(ratio, ratio);
    const double ratio_fourth = multiply(ratio_square, ratio_square);

    double even = add(kLg4, multiply(ratio_fourth, kLg6));
    even = add(kLg2, multiply(ratio_fourth, even));
    even = multiply(ratio_fourth, even);

    double odd = add(kLg5, multiply(ratio_fourth, kLg7));
    odd = add(kLg3, multiply(ratio_fourth, odd));
    odd = add(kLg1, multiply(ratio_fourth, odd));
    odd = multiply(ratio_square, odd);

    const double polynomial = add(odd, even);
    const double scale = static_cast<double>(exponent);
    double result =
        multiply(ratio, add(half_square, polynomial));
    result = add(
        result,
        add(multiply(scale, kLn2Low), correction));
    result = subtract(result, half_square);
    result = add(result, reduced);
    result = add(result, multiply(scale, kLn2High));
    return result;
}

}  // namespace sio::third_party::musl
