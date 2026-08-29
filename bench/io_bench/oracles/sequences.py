"""Independent parser and writer for the sequence benchmark codec."""

from __future__ import annotations

import io
import struct

import numpy as np


def _apng_oracle_write(payload):
    from PIL import Image

    frames = np.asarray(payload["frames"], np.uint8)
    images = [Image.fromarray(frame, "RGBA") for frame in frames]
    output = io.BytesIO()
    images[0].save(
        output,
        format="PNG",
        save_all=True,
        append_images=images[1:],
        duration=np.asarray(payload["durations_ms"]).tolist(),
        loop=int(payload["loop_count"]),
        disposal=[0] * len(images),
        blend=[0] * len(images),
    )
    return output.getvalue()


def _apng_oracle_read(data):
    from PIL import Image

    image = Image.open(io.BytesIO(bytes(data)))
    frames = []
    durations_ms = []
    loop_count = int(image.info["loop"])
    for index in range(image.n_frames):
        image.seek(index)
        frames.append(np.asarray(image.convert("RGBA")).copy())
        durations_ms.append(int(image.info["duration"]))
    return {
        "frames": np.stack(frames),
        "durations_ms": np.asarray(durations_ms, np.int64),
        "loop_count": loop_count,
    }


def _animated_webp_oracle_write(payload):
    from PIL import Image

    frames = np.asarray(payload["frames"], np.uint8)
    images = [Image.fromarray(frame, "RGBA") for frame in frames]
    output = io.BytesIO()
    images[0].save(
        output,
        format="WEBP",
        save_all=True,
        append_images=images[1:],
        duration=np.asarray(payload["durations_ms"]).tolist(),
        loop=int(payload["loop_count"]),
        lossless=True,
        exact=True,
        minimize_size=True,
    )
    return output.getvalue()


def _animated_webp_oracle_read(data):
    from PIL import Image

    image = Image.open(io.BytesIO(bytes(data)))
    frames = []
    durations_ms = []
    loop_count = int(image.info["loop"])
    for index in range(image.n_frames):
        image.seek(index)
        frames.append(np.asarray(image.convert("RGBA")).copy())
        durations_ms.append(int(image.info["duration"]))
    return {
        "frames": np.stack(frames),
        "durations_ms": np.asarray(durations_ms, np.int64),
        "loop_count": loop_count,
    }


def _y4m_oracle_write(payload):
    """Independent serializer for the benchmark's fixed raw 4:2:0 fixture."""

    y = np.asarray(payload["y"], np.uint8)
    u = np.asarray(payload["u"], np.uint8)
    v = np.asarray(payload["v"], np.uint8)
    frames, height, width = y.shape
    expected_chroma = (frames, (height + 1) // 2, (width + 1) // 2)
    if u.shape != expected_chroma or v.shape != expected_chroma:
        raise ValueError("benchmark Y4M oracle: chroma shape mismatch")
    output = bytearray(
        (
            f"YUV4MPEG2 W{width} H{height} F25:1 Ip A1:1 "
            "C420jpeg XYSCSS=420JPEG XCOLORRANGE=LIMITED "
            "XCOLORSPACE=BT709\n"
        ).encode("ascii")
    )
    for index in range(frames):
        output += b"FRAME\n"
        output += y[index].tobytes()
        output += u[index].tobytes()
        output += v[index].tobytes()
    return bytes(output)


def _y4m_oracle_read(data):
    """Independent parser for the benchmark's fixed raw 4:2:0 fixture."""

    header, payload = bytes(data).split(b"\n", 1)
    fields = header.decode("ascii").split()
    if not fields or fields[0] != "YUV4MPEG2":
        raise ValueError("benchmark Y4M oracle: bad magic")
    tokens = {
        field[0]: field[1:]
        for field in fields[1:]
        if not field.startswith("X")
    }
    extensions = {
        key: value
        for field in fields[1:]
        if field.startswith("X") and "=" in field
        for key, value in (field.split("=", 1),)
    }
    width = int(tokens["W"])
    height = int(tokens["H"])
    if (
        tokens["F"] != "25:1"
        or tokens["I"] != "p"
        or tokens["A"] != "1:1"
        or tokens["C"] != "420jpeg"
        or extensions
        != {
            "XYSCSS": "420JPEG",
            "XCOLORRANGE": "LIMITED",
            "XCOLORSPACE": "BT709",
        }
    ):
        raise ValueError("benchmark Y4M oracle: unexpected metadata")
    y_bytes = height * width
    chroma_height = (height + 1) // 2
    chroma_width = (width + 1) // 2
    chroma_bytes = chroma_height * chroma_width
    frame_bytes = y_bytes + 2 * chroma_bytes
    y_planes = []
    u_planes = []
    v_planes = []
    while payload:
        if not payload.startswith(b"FRAME\n"):
            raise ValueError("benchmark Y4M oracle: bad frame marker")
        frame = payload[6 : 6 + frame_bytes]
        if len(frame) != frame_bytes:
            raise ValueError("benchmark Y4M oracle: truncated frame")
        payload = payload[6 + frame_bytes :]
        y_planes.append(
            np.frombuffer(frame[:y_bytes], np.uint8).reshape(height, width)
        )
        u_planes.append(
            np.frombuffer(
                frame[y_bytes : y_bytes + chroma_bytes], np.uint8
            ).reshape(chroma_height, chroma_width)
        )
        v_planes.append(
            np.frombuffer(frame[y_bytes + chroma_bytes :], np.uint8).reshape(
                chroma_height, chroma_width
            )
        )
    return {
        "y": np.asarray(y_planes),
        "u": np.asarray(u_planes),
        "v": np.asarray(v_planes),
        "width": width,
        "height": height,
        "frame_rate": (25, 1),
        "pixel_aspect": (1, 1),
        "chroma_subsampling": "420",
        "chroma_siting": "jpeg",
        "color_range": "limited",
        "matrix": "bt709",
        "interlace": "progressive",
    }


def _webm_id(value):
    return value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")


def _webm_size(value):
    width = 1
    while value > (1 << (7 * width)) - 2:
        width += 1
    return (value | (1 << (7 * width))).to_bytes(width, "big")


def _webm_element(element_id, payload):
    return _webm_id(element_id) + _webm_size(len(payload)) + payload


def _webm_uint(element_id, value):
    width = max(1, (value.bit_length() + 7) // 8)
    return _webm_element(element_id, value.to_bytes(width, "big"))


def _webm_text(element_id, value):
    return _webm_element(element_id, value.encode("ascii"))


def _webm_vp8_from_webp(payload):
    if payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        raise ValueError("benchmark WebM oracle: invalid WebP frame")
    position = 12
    packet = None
    while position < len(payload):
        fourcc = payload[position : position + 4]
        size = int.from_bytes(payload[position + 4 : position + 8], "little")
        position += 8
        chunk = payload[position : position + size]
        position += size + (size & 1)
        if fourcc == b"VP8 ":
            if packet is not None:
                raise ValueError("benchmark WebM oracle: duplicate VP8 frame")
            packet = chunk
    if packet is None:
        raise ValueError("benchmark WebM oracle: missing VP8 frame")
    return packet


def _webm_webp_from_vp8(packet):
    chunk = b"VP8 " + len(packet).to_bytes(4, "little") + packet
    if len(packet) & 1:
        chunk += b"\0"
    return b"RIFF" + (len(chunk) + 4).to_bytes(4, "little") + b"WEBP" + chunk


def _webm_oracle_write(payload):
    """Independent SimpleBlock mux using Pillow's public VP8 encoder."""

    from PIL import Image

    frames = np.asarray(payload["frames"], np.uint8)
    durations = np.asarray(payload["durations_ms"], np.int64)
    if len(frames) == 0 or np.any(durations != durations[0]):
        raise ValueError("benchmark WebM oracle requires constant timing")
    packets = []
    for frame in frames:
        output = io.BytesIO()
        Image.fromarray(frame, "RGB").save(
            output,
            format="WEBP",
            lossless=False,
            quality=90,
            method=4,
        )
        packets.append(_webm_vp8_from_webp(output.getvalue()))
    height, width = frames.shape[1:3]
    duration_ms = int(durations[0])
    ebml = b"".join(
        (
            _webm_uint(0x4286, 1),
            _webm_uint(0x42F7, 1),
            _webm_uint(0x42F2, 4),
            _webm_uint(0x42F3, 8),
            _webm_text(0x4282, "webm"),
            _webm_uint(0x4287, 2),
            _webm_uint(0x4285, 2),
        )
    )
    info = b"".join(
        (
            _webm_uint(0x2AD7B1, 1_000_000),
            _webm_text(0x4D80, "oracle"),
            _webm_text(0x5741, "oracle"),
        )
    )
    video = b"".join(
        (
            _webm_uint(0x9A, 2),
            _webm_uint(0xB0, width),
            _webm_uint(0xBA, height),
        )
    )
    track = b"".join(
        (
            _webm_uint(0xD7, 1),
            _webm_uint(0x73C5, 1),
            _webm_uint(0x83, 1),
            _webm_uint(0x9C, 0),
            _webm_uint(0x23E383, duration_ms * 1_000_000),
            _webm_text(0x86, "V_VP8"),
            _webm_element(0xE0, video),
        )
    )
    blocks = []
    for index, packet in enumerate(packets):
        header = b"\x81" + struct.pack(">hB", index * duration_ms, 0x80)
        blocks.append(_webm_element(0xA3, header + packet))
    cluster = _webm_uint(0xE7, 0) + b"".join(blocks)
    segment = b"".join(
        (
            _webm_element(0x1549A966, info),
            _webm_element(0x1654AE6B, _webm_element(0xAE, track)),
            _webm_element(0x1F43B675, cluster),
        )
    )
    return _webm_element(0x1A45DFA3, ebml) + _webm_element(0x18538067, segment)


def _webm_read_vint(data, position, keep_marker):
    first = data[position]
    marker = 0x80
    width = 1
    while not first & marker:
        marker >>= 1
        width += 1
    raw = int.from_bytes(data[position : position + width], "big")
    if keep_marker:
        return raw, width, False
    value = first & (0xFF >> width)
    for byte in data[position + 1 : position + width]:
        value = (value << 8) | byte
    return value, width, value == (1 << (7 * width)) - 1


def _webm_elements(data, start, stop):
    position = start
    while position < stop:
        element_id, id_width, _ = _webm_read_vint(data, position, True)
        size, size_width, unknown = _webm_read_vint(
            data, position + id_width, False
        )
        body = position + id_width + size_width
        end = stop if unknown else body + size
        if not body <= end <= stop:
            raise ValueError("benchmark WebM oracle: bad EBML extent")
        yield element_id, body, end
        position = end


def _webm_oracle_read(data):
    """Independent EBML demux followed by Pillow's public VP8 decoder."""

    from PIL import Image

    encoded = bytes(data)
    roots = list(_webm_elements(encoded, 0, len(encoded)))
    if [item[0] for item in roots] != [0x1A45DFA3, 0x18538067]:
        raise ValueError("benchmark WebM oracle: bad root elements")
    packets = []
    default_duration_ms = None
    _, segment_start, segment_stop = roots[1]
    for element_id, start, stop in _webm_elements(
        encoded, segment_start, segment_stop
    ):
        if element_id == 0x1654AE6B:
            for track_id, track_start, track_stop in _webm_elements(
                encoded, start, stop
            ):
                if track_id != 0xAE:
                    continue
                for field_id, field_start, field_stop in _webm_elements(
                    encoded, track_start, track_stop
                ):
                    if field_id == 0x23E383:
                        duration_ns = int.from_bytes(
                            encoded[field_start:field_stop], "big"
                        )
                        if duration_ns % 1_000_000:
                            raise ValueError(
                                "benchmark WebM oracle: fractional-ms timing"
                            )
                        default_duration_ms = duration_ns // 1_000_000
        if element_id != 0x1F43B675:
            continue
        cluster_timestamp = None
        for cluster_id, cluster_start, cluster_stop in _webm_elements(
            encoded, start, stop
        ):
            if cluster_id == 0xE7:
                cluster_timestamp = int.from_bytes(
                    encoded[cluster_start:cluster_stop], "big"
                )
            elif cluster_id == 0xA3:
                if cluster_timestamp is None:
                    raise ValueError(
                        "benchmark WebM oracle: block before timestamp"
                    )
                block = encoded[cluster_start:cluster_stop]
                relative = int.from_bytes(block[1:3], "big", signed=True)
                packets.append(
                    (cluster_timestamp + relative, None, block[4:])
                )
            elif cluster_id == 0xA0:
                block = None
                duration = None
                for group_id, group_start, group_stop in _webm_elements(
                    encoded, cluster_start, cluster_stop
                ):
                    if group_id == 0xA1:
                        block = encoded[group_start:group_stop]
                    elif group_id == 0x9B:
                        duration = int.from_bytes(
                            encoded[group_start:group_stop], "big"
                        )
                if cluster_timestamp is None or block is None or duration is None:
                    raise ValueError("benchmark WebM oracle: incomplete frame")
                relative = int.from_bytes(block[1:3], "big", signed=True)
                packets.append((cluster_timestamp + relative, duration, block[4:]))
    for index, (timestamp, duration, packet) in enumerate(packets):
        if duration is not None:
            continue
        if index + 1 < len(packets):
            duration = packets[index + 1][0] - timestamp
        else:
            duration = default_duration_ms
        if duration is None or duration <= 0:
            raise ValueError("benchmark WebM oracle: missing frame duration")
        packets[index] = (timestamp, duration, packet)
    frames = []
    for _, _, packet in packets:
        with Image.open(io.BytesIO(_webm_webp_from_vp8(packet))) as image:
            frames.append(np.asarray(image.convert("RGB")).copy())
    return {
        "frames": np.stack(frames),
        "timestamps_ms": np.asarray([item[0] for item in packets], np.int64),
        "durations_ms": np.asarray([item[1] for item in packets], np.int64),
    }


__all__ = [
    "_animated_webp_oracle_read",
    "_animated_webp_oracle_write",
    "_apng_oracle_read",
    "_apng_oracle_write",
    "_webm_oracle_read",
    "_webm_oracle_write",
    "_y4m_oracle_read",
    "_y4m_oracle_write",
]
