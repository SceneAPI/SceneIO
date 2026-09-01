// Copyright (c), ETH Zurich and UNC Chapel Hill.
// All rights reserved.

#include "codecs/sequences/av1_obu.hpp"

#include <algorithm>
#include <limits>
#include <string>
#include <utility>

namespace sio::av1 {
namespace {

bool Fail(std::string* error, std::string message) {
  if (error != nullptr) {
    *error = std::move(message);
  }
  return false;
}

class BitReader {
 public:
  BitReader(const uint8_t* data, const size_t size)
      : data_(data), num_bits_(size * 8) {}

  bool ReadBits(const int count, uint64_t* value) {
    if (value == nullptr || count < 0 || count > 64 ||
        static_cast<size_t>(count) > num_bits_ - bit_offset_) {
      return false;
    }
    uint64_t result = 0;
    for (int i = 0; i < count; ++i) {
      const size_t offset = bit_offset_++;
      result = (result << 1) | ((data_[offset / 8] >> (7 - offset % 8)) & 1u);
    }
    *value = result;
    return true;
  }

  bool ReadBit(bool* value) {
    uint64_t bit = 0;
    if (value == nullptr || !ReadBits(1, &bit)) {
      return false;
    }
    *value = bit != 0;
    return true;
  }

  bool SkipBits(const size_t count) {
    if (count > num_bits_ - bit_offset_) {
      return false;
    }
    bit_offset_ += count;
    return true;
  }

  bool SkipUnsignedExpGolomb() {
    size_t leading_zeroes = 0;
    bool bit = false;
    while (true) {
      if (!ReadBit(&bit)) {
        return false;
      }
      if (bit) {
        break;
      }
      if (++leading_zeroes >= 32) {
        return false;
      }
    }
    return SkipBits(leading_zeroes);
  }

 private:
  const uint8_t* data_ = nullptr;
  size_t num_bits_ = 0;
  size_t bit_offset_ = 0;
};

struct SequenceHeader {
  uint8_t profile = 0;
  uint8_t level = 0;
  bool tier = false;
  bool high_bitdepth = false;
  bool twelve_bit = false;
  bool monochrome = false;
  bool subsampling_x = false;
  bool subsampling_y = false;
  uint8_t chroma_sample_position = 0;
  Av1ColorDescription color;
  bool initial_presentation_delay_present = false;
  uint8_t initial_presentation_delay_minus_one = 0;
  int max_frame_width = 0;
  int max_frame_height = 0;
};

bool SkipTimingInfo(BitReader* reader) {
  bool equal_picture_interval = false;
  return reader->SkipBits(64) && reader->ReadBit(&equal_picture_interval) &&
         (!equal_picture_interval || reader->SkipUnsignedExpGolomb());
}

bool ParseColorConfig(BitReader* reader, SequenceHeader* header) {
  if (!reader->ReadBit(&header->high_bitdepth)) {
    return false;
  }
  if (header->profile == 2 && header->high_bitdepth) {
    if (!reader->ReadBit(&header->twelve_bit)) {
      return false;
    }
  }
  const int bit_depth =
      header->twelve_bit ? 12 : (header->high_bitdepth ? 10 : 8);
  if (header->profile == 1) {
    header->monochrome = false;
  } else if (!reader->ReadBit(&header->monochrome)) {
    return false;
  }

  bool color_description_present = false;
  if (!reader->ReadBit(&color_description_present)) {
    return false;
  }
  uint64_t color_primaries = 2;
  uint64_t transfer_characteristics = 2;
  uint64_t matrix_coefficients = 2;
  if (color_description_present &&
      (!reader->ReadBits(8, &color_primaries) ||
       !reader->ReadBits(8, &transfer_characteristics) ||
       !reader->ReadBits(8, &matrix_coefficients))) {
    return false;
  }
  header->color.primaries = static_cast<uint16_t>(color_primaries);
  header->color.transfer = static_cast<uint16_t>(transfer_characteristics);
  header->color.matrix = static_cast<uint16_t>(matrix_coefficients);

  bool color_range = false;
  if (header->monochrome) {
    if (!reader->ReadBit(&color_range)) {
      return false;
    }
    header->color.full_range = color_range;
    header->subsampling_x = true;
    header->subsampling_y = true;
    header->chroma_sample_position = 0;
    return true;
  }

  if (color_primaries == 1 && transfer_characteristics == 13 &&
      matrix_coefficients == 0) {
    // AV1 spec 5.5.2: the sRGB/identity combination codes no range bit and
    // implies full range.
    header->color.full_range = true;
    header->subsampling_x = false;
    header->subsampling_y = false;
  } else {
    if (!reader->ReadBit(&color_range)) {
      return false;
    }
    header->color.full_range = color_range;
    if (header->profile == 0) {
      header->subsampling_x = true;
      header->subsampling_y = true;
    } else if (header->profile == 1) {
      header->subsampling_x = false;
      header->subsampling_y = false;
    } else if (bit_depth == 12) {
      if (!reader->ReadBit(&header->subsampling_x)) {
        return false;
      }
      if (header->subsampling_x && !reader->ReadBit(&header->subsampling_y)) {
        return false;
      }
    } else {
      header->subsampling_x = true;
      header->subsampling_y = false;
    }
    if (header->subsampling_x && header->subsampling_y) {
      uint64_t position = 0;
      if (!reader->ReadBits(2, &position)) {
        return false;
      }
      header->chroma_sample_position = static_cast<uint8_t>(position);
    }
  }
  bool separate_uv_delta_q = false;
  return reader->ReadBit(&separate_uv_delta_q);
}

bool ParseSequenceHeader(const uint8_t* data,
                         const size_t size,
                         SequenceHeader* header) {
  if (data == nullptr || size == 0 ||
      size > std::numeric_limits<size_t>::max() / 8 || header == nullptr) {
    return false;
  }
  BitReader reader(data, size);
  uint64_t value = 0;
  bool still_picture = false;
  bool reduced_still_picture_header = false;
  if (!reader.ReadBits(3, &value) || value > 2 ||
      !reader.ReadBit(&still_picture) ||
      !reader.ReadBit(&reduced_still_picture_header)) {
    return false;
  }
  header->profile = static_cast<uint8_t>(value);
  if (reduced_still_picture_header && !still_picture) {
    return false;
  }

  bool decoder_model_info_present = false;
  bool initial_display_delay_present = false;
  uint64_t buffer_delay_length = 0;
  uint64_t operating_points_minus_one = 0;
  if (reduced_still_picture_header) {
    if (!reader.ReadBits(5, &value)) {
      return false;
    }
    header->level = static_cast<uint8_t>(value);
  } else {
    bool timing_info_present = false;
    if (!reader.ReadBit(&timing_info_present)) {
      return false;
    }
    if (timing_info_present) {
      if (!SkipTimingInfo(&reader) ||
          !reader.ReadBit(&decoder_model_info_present)) {
        return false;
      }
      if (decoder_model_info_present) {
        if (!reader.ReadBits(5, &buffer_delay_length) ||
            !reader.SkipBits(32 + 5 + 5)) {
          return false;
        }
        ++buffer_delay_length;
      }
    }
    if (!reader.ReadBit(&initial_display_delay_present) ||
        !reader.ReadBits(5, &operating_points_minus_one)) {
      return false;
    }
    for (uint64_t i = 0; i <= operating_points_minus_one; ++i) {
      uint64_t level = 0;
      if (!reader.SkipBits(12) || !reader.ReadBits(5, &level)) {
        return false;
      }
      bool tier = false;
      if (level > 7 && !reader.ReadBit(&tier)) {
        return false;
      }
      if (i == 0) {
        header->level = static_cast<uint8_t>(level);
        header->tier = tier;
      }
      if (decoder_model_info_present) {
        bool decoder_model_present_for_op = false;
        if (!reader.ReadBit(&decoder_model_present_for_op)) {
          return false;
        }
        if (decoder_model_present_for_op &&
            !reader.SkipBits(
                static_cast<size_t>(2 * buffer_delay_length + 1))) {
          return false;
        }
      }
      if (initial_display_delay_present) {
        bool delay_present_for_op = false;
        if (!reader.ReadBit(&delay_present_for_op)) {
          return false;
        }
        uint64_t delay = 0;
        if (delay_present_for_op && !reader.ReadBits(4, &delay)) {
          return false;
        }
        if (i == 0 && delay_present_for_op) {
          header->initial_presentation_delay_present = true;
          header->initial_presentation_delay_minus_one =
              static_cast<uint8_t>(delay);
        }
      }
    }
  }

  uint64_t width_bits_minus_one = 0;
  uint64_t height_bits_minus_one = 0;
  uint64_t width_minus_one = 0;
  uint64_t height_minus_one = 0;
  if (!reader.ReadBits(4, &width_bits_minus_one) ||
      !reader.ReadBits(4, &height_bits_minus_one) ||
      !reader.ReadBits(static_cast<int>(width_bits_minus_one + 1),
                       &width_minus_one) ||
      !reader.ReadBits(static_cast<int>(height_bits_minus_one + 1),
                       &height_minus_one) ||
      width_minus_one >=
          static_cast<uint64_t>(std::numeric_limits<int>::max()) ||
      height_minus_one >=
          static_cast<uint64_t>(std::numeric_limits<int>::max())) {
    return false;
  }
  header->max_frame_width = static_cast<int>(width_minus_one + 1);
  header->max_frame_height = static_cast<int>(height_minus_one + 1);

  if (!reduced_still_picture_header) {
    bool frame_id_numbers_present = false;
    if (!reader.ReadBit(&frame_id_numbers_present) ||
        (frame_id_numbers_present && !reader.SkipBits(7))) {
      return false;
    }
  }
  if (!reader.SkipBits(3)) {
    return false;
  }
  bool enable_order_hint = false;
  bool force_screen_content_tools = true;
  if (!reduced_still_picture_header) {
    if (!reader.SkipBits(4) || !reader.ReadBit(&enable_order_hint) ||
        (enable_order_hint && !reader.SkipBits(2))) {
      return false;
    }
    bool choose_screen_content_tools = false;
    if (!reader.ReadBit(&choose_screen_content_tools)) {
      return false;
    }
    if (!choose_screen_content_tools &&
        !reader.ReadBit(&force_screen_content_tools)) {
      return false;
    }
    if (force_screen_content_tools) {
      bool choose_integer_mv = false;
      if (!reader.ReadBit(&choose_integer_mv) ||
          (!choose_integer_mv && !reader.SkipBits(1))) {
        return false;
      }
    }
    if (enable_order_hint && !reader.SkipBits(3)) {
      return false;
    }
  }
  if (!reader.SkipBits(3) || !ParseColorConfig(&reader, header) ||
      !reader.SkipBits(1)) {
    return false;
  }
  return true;
}

bool ReadLeb128(const uint8_t* data,
                const size_t size,
                size_t* offset,
                size_t* value) {
  if (data == nullptr || offset == nullptr || value == nullptr) {
    return false;
  }
  uint64_t result = 0;
  for (int i = 0; i < 8; ++i) {
    if (*offset >= size) {
      return false;
    }
    const uint8_t byte = data[(*offset)++];
    result |= static_cast<uint64_t>(byte & 0x7f) << (7 * i);
    if ((byte & 0x80) == 0) {
      if (result > std::numeric_limits<size_t>::max()) {
        return false;
      }
      *value = static_cast<size_t>(result);
      return true;
    }
  }
  return false;
}

std::vector<uint8_t> MakeCodecPrivate(
    const SequenceHeader& header,
    const std::vector<uint8_t>& sequence_header_obu) {
  std::vector<uint8_t> result;
  result.reserve(4 + sequence_header_obu.size());
  result.push_back(0x81);  // marker=1, version=1
  result.push_back(
      static_cast<uint8_t>((header.profile << 5) | (header.level & 0x1f)));
  result.push_back(static_cast<uint8_t>(
      (header.tier ? 0x80 : 0) | (header.high_bitdepth ? 0x40 : 0) |
      (header.twelve_bit ? 0x20 : 0) | (header.monochrome ? 0x10 : 0) |
      (header.subsampling_x ? 0x08 : 0) | (header.subsampling_y ? 0x04 : 0) |
      (header.chroma_sample_position & 0x03)));
  // Byte 3 is reserved(3) + initial_presentation_delay_present(1) +
  // (delay_minus_one(4) | reserved(4)); every reserved bit must be zero or
  // validating parsers (Chrome's libavif) reject the stream outright.
  result.push_back(static_cast<uint8_t>(
      header.initial_presentation_delay_present
          ? 0x10 | (header.initial_presentation_delay_minus_one & 0x0f)
          : 0x00));
  result.insert(
      result.end(), sequence_header_obu.begin(), sequence_header_obu.end());
  return result;
}

}  // namespace

bool ParseAv1WebmPacket(const uint8_t* data,
                        const size_t size,
                        Av1WebmPacketInfo* info,
                        std::string* error) {
  if (info == nullptr) {
    return Fail(error, "AV1 packet-info output is null");
  }
  *info = {};
  if (data == nullptr || size == 0) {
    return Fail(error, "AV1 temporal unit is empty");
  }

  size_t offset = 0;
  while (offset < size) {
    const size_t obu_begin = offset;
    const uint8_t header_byte = data[offset++];
    const bool forbidden = (header_byte & 0x80) != 0;
    const uint8_t type = static_cast<uint8_t>((header_byte >> 3) & 0x0f);
    const bool extension = (header_byte & 0x04) != 0;
    const bool has_size_field = (header_byte & 0x02) != 0;
    const bool reserved = (header_byte & 0x01) != 0;
    if (forbidden || reserved || type == 0 || (type >= 9 && type <= 14)) {
      return Fail(error, "AV1 temporal unit has an invalid OBU header");
    }
    if (extension) {
      if (offset >= size || (data[offset] & 0x07) != 0) {
        return Fail(error, "AV1 OBU extension is truncated or reserved");
      }
      if (type == 1 && (data[offset] & 0xf8) != 0) {
        return Fail(error,
                    "AV1 sequence header must use temporal/spatial layer 0");
      }
      ++offset;
    }

    size_t payload_size = 0;
    if (has_size_field) {
      if (!ReadLeb128(data, size, &offset, &payload_size) ||
          payload_size > size - offset) {
        return Fail(error, "AV1 OBU payload size is malformed");
      }
    } else {
      payload_size = size - offset;
    }
    const size_t payload_begin = offset;
    const size_t obu_end = payload_begin + payload_size;
    if (type == 1) {
      if (info->has_sequence_header || !has_size_field) {
        return Fail(error,
                    "AV1 packet has duplicate or unbounded sequence headers");
      }
      SequenceHeader sequence;
      if (!ParseSequenceHeader(data + payload_begin, payload_size, &sequence)) {
        return Fail(error, "AV1 sequence header is malformed");
      }
      info->has_sequence_header = true;
      info->max_frame_width = sequence.max_frame_width;
      info->max_frame_height = sequence.max_frame_height;
      info->color = sequence.color;
      info->sequence_header_obu.assign(data + obu_begin, data + obu_end);
      info->codec_private =
          MakeCodecPrivate(sequence, info->sequence_header_obu);
    } else if (type == 6) {
      info->has_frame_obu = true;
    }
    offset = obu_end;
    if (!has_size_field && offset != size) {
      return Fail(error, "unbounded AV1 OBU is not last in the packet");
    }
  }
  return true;
}

}  // namespace sio::av1
