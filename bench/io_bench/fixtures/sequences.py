"""Deterministic fixtures for sequence benchmark codecs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from sceneio import _core


def _y4m_fixture(side):
    frames = 4
    rng = np.random.default_rng(31)
    y = rng.integers(
        0, 256, (frames, side, side), dtype=np.uint8
    )
    chroma_side = (side + 1) // 2
    u = rng.integers(
        0, 256, (frames, chroma_side, chroma_side), dtype=np.uint8
    )
    v = rng.integers(
        0, 256, (frames, chroma_side, chroma_side), dtype=np.uint8
    )
    empty = np.empty(0, np.int64)
    record = _core.image_sequence_yuv(
        y,
        u,
        v,
        empty,
        empty,
        "420",
        "jpeg",
        "limited",
        "bt709",
        "progressive",
        25,
        1,
        1,
        1,
    )
    return record, {"y": y, "u": u, "v": v}


def _animated_webp_fixture(side):
    frame_count = 4
    rng = np.random.default_rng(41)
    frames = rng.integers(
        0, 256, (frame_count, side, side, 4), dtype=np.uint8
    )
    frames[..., 3] = rng.integers(
        1, 256, (frame_count, side, side), dtype=np.uint8
    )
    durations_ms = np.array([25, 40, 55, 70], np.int64)
    durations_ns = durations_ms * 1_000_000
    timestamps_ns = np.concatenate(
        [np.zeros(1, np.int64), np.cumsum(durations_ns[:-1])]
    )
    background = np.array([7, 11, 13, 17], np.uint8)
    record = _core.image_sequence_packed(
        frames,
        timestamps_ns,
        durations_ns,
        "srgb",
        "straight",
        None,
        2,
        background,
    )
    return record, {
        "frames": frames,
        "durations_ms": durations_ms,
        "loop_count": 2,
    }


def _webm_fixture(side):
    frame_count = 4
    rng = np.random.default_rng(47)
    frames = rng.integers(
        0, 256, (frame_count, side, side, 3), dtype=np.uint8
    )
    durations_ms = np.full(frame_count, 40, np.int64)
    durations_ns = durations_ms * 1_000_000
    timestamps_ns = np.arange(frame_count, dtype=np.int64) * 40_000_000
    record = _core.image_sequence_packed(
        frames,
        timestamps_ns,
        durations_ns,
        "srgb",
        "none",
        None,
        None,
        None,
    )
    return record, {
        "frames": frames,
        "durations_ms": durations_ms,
    }


def _apng_fixture(side):
    frame_count = 4
    rng = np.random.default_rng(43)
    frames = rng.integers(
        0, 256, (frame_count, side, side, 4), dtype=np.uint8
    )
    frames[..., 3] = rng.integers(
        1, 256, (frame_count, side, side), dtype=np.uint8
    )
    durations_ms = np.array([20, 35, 50, 65], np.int64)
    durations_ns = durations_ms * 1_000_000
    timestamps_ns = np.concatenate(
        [np.zeros(1, np.int64), np.cumsum(durations_ns[:-1])]
    )
    record = _core.image_sequence_packed(
        frames,
        timestamps_ns,
        durations_ns,
        "srgb",
        "straight",
        None,
        3,
    )
    return record, {
        "frames": frames,
        "durations_ms": durations_ms,
        "loop_count": 3,
    }


def _image_sequence_directory_fixture(root, scale):
    source = Path(root) / "_image_sequence_input"
    source.mkdir()
    frame_count = 32
    side = max(8, int(256 * scale**0.5))
    rng = np.random.default_rng(37)
    paths = []
    names = []
    for index in range(frame_count):
        name = f"frame{index:04d}.ppm"
        path = source / name
        pixels = rng.integers(
            0, 256, (side, side, 3), dtype=np.uint8
        )
        path.write_bytes(
            f"P6\n{side} {side}\n255\n".encode("ascii")
            + pixels.tobytes()
        )
        paths.append(str(path))
        names.append(name)
    duration = 40_000_000
    timestamps = (
        np.arange(frame_count, dtype=np.int64) * duration
    )
    durations = np.full(frame_count, duration, np.int64)
    record = _core.image_sequence_paths(
        paths,
        names,
        timestamps,
        durations,
        side,
        side,
        3,
        "uint8",
        "unknown",
        "none",
    )
    return record, frame_count * side * side * 3


def _rtmv_directory_fixture(root, scale):
    source = Path(root) / "_rtmv_input"
    source.mkdir()
    frame_count = 8
    side = max(8, int(256 * scale**0.5))
    rng = np.random.default_rng(53)
    pixels = rng.random((side, side, 4), dtype=np.float32)
    encoded = bytes(
        _core.write_exr(
            _core.image(
                pixels,
                color_space="linear",
                alpha_mode="premultiplied",
            )
        )
    )
    for index in range(frame_count):
        stem = f"{index:05d}"
        translation = [index * 0.1, -0.5, 2.0]
        c2w = np.eye(4, dtype=np.float64)
        c2w[:3, 3] = translation
        metadata = {
            "camera_data": {
                "cam2world": c2w.T.tolist(),
                "camera_view_matrix": np.linalg.inv(c2w).T.tolist(),
                "camera_look_at": {
                    "at": [translation[0], translation[1], 1.0],
                    "eye": translation,
                    "up": [0.0, 1.0, 0.0],
                },
                "width": side,
                "height": side,
                "intrinsics": {
                    "cx": side / 2.0,
                    "cy": side / 2.0,
                    "fx": side * 1.2,
                    "fy": side * 1.2,
                },
                "location_world": translation,
                "quaternion_world_xyzw": [0.0, 0.0, 0.0, 1.0],
                "scene_center_3d_box": [0.0, 0.0, 0.0],
                "scene_min_3d_box": [-1.0, -1.0, -1.0],
                "scene_max_3d_box": [1.0, 1.0, 1.0],
            },
            "objects": [
                {"segmentation_id": object_id + 1}
                for object_id in range(16)
            ],
        }
        (source / f"{stem}.json").write_text(
            json.dumps(metadata, separators=(",", ":")),
            encoding="utf-8",
        )
        for suffix in (".exr", ".depth.exr", ".seg.exr"):
            (source / f"{stem}{suffix}").write_bytes(encoded)
    logical_bytes = frame_count * side * side * 12 * 4
    return source, logical_bytes


__all__ = [
    "_animated_webp_fixture",
    "_apng_fixture",
    "_image_sequence_directory_fixture",
    "_rtmv_directory_fixture",
    "_webm_fixture",
    "_y4m_fixture",
]
