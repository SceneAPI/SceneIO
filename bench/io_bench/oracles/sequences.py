"""Independent parser and writer for the sequence benchmark codec."""

from __future__ import annotations

import io

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


__all__ = [
    "_animated_webp_oracle_read",
    "_animated_webp_oracle_write",
    "_apng_oracle_read",
    "_apng_oracle_write",
    "_y4m_oracle_read",
    "_y4m_oracle_write",
]
