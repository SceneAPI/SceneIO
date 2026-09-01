// Copyright (c), ETH Zurich and UNC Chapel Hill.
// All rights reserved.

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace sio::av1 {

// CICP (ITU-T H.273) colour description, in the shape a `colr`/'nclx' box and
// a WebM Colour element both need. The defaults are the CICP "unspecified"
// code points with limited range, which is what a stream that declines to
// describe its colour means, so absence needs no separate flag.
struct Av1ColorDescription {
  uint16_t primaries = 2;
  uint16_t transfer = 2;
  uint16_t matrix = 2;
  bool full_range = false;
};

// Information needed to carry an AV1 low-overhead temporal unit in WebM.
// This intentionally exposes no libaom or NVENC types so packet muxing stays
// independent of the encoder implementation.
struct Av1WebmPacketInfo {
  bool has_sequence_header = false;
  bool has_frame_obu = false;
  int max_frame_width = 0;
  int max_frame_height = 0;
  std::vector<uint8_t> sequence_header_obu;
  std::vector<uint8_t> codec_private;
  // The colour description exactly as the sequence header declares it. The
  // AV1CodecConfigurationRecord does not carry colour, so this is the only
  // in-band source for a container that must repeat it - AVIF requires a
  // `colr` box, and MIAF gives that box precedence over the bitstream, which
  // makes agreement with the bitstream mandatory rather than merely
  // desirable.
  //
  // `full_range` is always meaningful because AV1 has no unspecified range:
  // it is either coded explicitly or implied by the sRGB/identity
  // combination (AV1 spec 5.5.2).
  Av1ColorDescription color;
};

// Parses one AV1 low-overhead temporal unit. When a sequence-header OBU is
// present, codec_private contains the matching AV1CodecConfigurationRecord.
// Annex-B input and malformed/truncated OBUs fail closed.
bool ParseAv1WebmPacket(const uint8_t* data,
                        size_t size,
                        Av1WebmPacketInfo* info,
                        std::string* error = nullptr);

}  // namespace sio::av1
