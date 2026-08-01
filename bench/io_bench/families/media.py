"""Path-native benchmark specifications for royalty-free media providers."""

from __future__ import annotations

import numpy as np

import sceneio
from bench.io_bench.fixtures.media import (
    _animated_avif_fixture,
    _avif_fixture,
)
from bench.io_bench.model import PathSpec
from bench.io_bench.oracles.media import (
    AVIF_AVAILABLE,
    _animated_avif_oracle_read,
    _animated_avif_oracle_write,
    _avif_oracle_read,
    _avif_oracle_write,
)


def _assert_lossy_pixels(actual, expected) -> None:
    difference = np.abs(
        np.asarray(actual, np.int16) - np.asarray(expected, np.int16)
    )
    assert difference.max(initial=0) <= 48
    assert difference.mean() <= 7


def _assert_avif(actual, expected) -> None:
    _assert_lossy_pixels(actual.pixels, expected)


def _assert_avif_payload(actual, expected) -> None:
    _assert_lossy_pixels(actual, expected)


def _assert_animated_avif(actual, expected) -> None:
    _assert_lossy_pixels(actual.pixels, expected["frames"])
    np.testing.assert_array_equal(actual.timestamps_ns, expected["timestamps_ns"])
    np.testing.assert_array_equal(actual.durations_ns, expected["durations_ns"])


def _assert_animated_payload(actual, expected) -> None:
    _assert_lossy_pixels(actual["frames"], expected["frames"])
    np.testing.assert_array_equal(actual["timestamps_ns"], expected["timestamps_ns"])
    np.testing.assert_array_equal(actual["durations_ns"], expected["durations_ns"])


def _partial_animated_avif(path):
    return sceneio.read_partial(path, frames=(1, 3), format="animated_avif")


def _assert_partial_animated_avif(actual, expected) -> None:
    subset = {
        "frames": expected["frames"][1:3],
        "timestamps_ns": expected["timestamps_ns"][1:3],
        "durations_ns": expected["durations_ns"][1:3],
    }
    _assert_animated_avif(actual, subset)


def build_media_path_specs(scale):
    if not AVIF_AVAILABLE:
        return []
    side = max(1, int(1024 * scale**0.5))
    return [
        PathSpec(
            "avif",
            ".avif",
            lambda: _avif_fixture(side),
            lambda value, path: sceneio.write(value, path, format="avif"),
            lambda path: sceneio.read(path, format="avif"),
            _avif_oracle_write,
            _avif_oracle_read,
            lambda _record, payload: payload.nbytes,
            _assert_avif,
            _assert_avif_payload,
        ),
        PathSpec(
            "animated_avif",
            ".avif",
            lambda: _animated_avif_fixture(side),
            lambda value, path: sceneio.write(
                value, path, format="animated_avif"
            ),
            lambda path: sceneio.read(path, format="animated_avif"),
            _animated_avif_oracle_write,
            _animated_avif_oracle_read,
            lambda _record, payload: payload["frames"].nbytes,
            _assert_animated_avif,
            _assert_animated_payload,
            _partial_animated_avif,
            _assert_partial_animated_avif,
        ),
    ]


__all__ = ["build_media_path_specs"]
