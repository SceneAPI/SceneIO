"""Deterministic fixtures for sequence benchmark codecs."""

from __future__ import annotations

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


__all__ = ["_image_sequence_directory_fixture", "_y4m_fixture"]
