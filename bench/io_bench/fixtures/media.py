"""Deterministic path-native still/sequence media fixtures."""

from __future__ import annotations

import numpy as np

from sceneio import _core


def _avif_fixture(side: int):
    rng = np.random.default_rng(47)
    pixels = rng.integers(0, 256, (side, side, 3), dtype=np.uint8)
    return _core.image(pixels, color_space="srgb"), pixels


def _animated_avif_fixture(side: int):
    frame_count = 4
    rng = np.random.default_rng(53)
    frames = rng.integers(
        0, 256, (frame_count, side, side, 4), dtype=np.uint8
    )
    frames[..., 3] = rng.integers(
        32, 256, (frame_count, side, side), dtype=np.uint8
    )
    durations_ms = np.array([25, 40, 55, 70], np.int64)
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
    )
    return record, {
        "frames": frames,
        "timestamps_ns": timestamps_ns,
        "durations_ns": durations_ns,
    }


__all__ = ["_animated_avif_fixture", "_avif_fixture"]
