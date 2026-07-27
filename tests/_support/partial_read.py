"""Shared assertions for partial-read behavior suites."""

from __future__ import annotations

import numpy as np

from sceneio import _core


def _pixels(value):
    return np.asarray(value.pixels if isinstance(value, _core.Image) else value)


def _assert_image_window(partial, full, window):
    row_start, row_stop, col_start, col_stop = window
    np.testing.assert_array_equal(
        _pixels(partial),
        _pixels(full)[row_start:row_stop, col_start:col_stop, ...],
    )
    if isinstance(full, _core.Image):
        assert isinstance(partial, _core.Image)
        assert (
            partial.dtype,
            partial.color_space,
            partial.alpha_mode,
            partial.maxval,
            partial.channels,
            partial.channel_order,
            partial.row_order,
        ) == (
            full.dtype,
            full.color_space,
            full.alpha_mode,
            full.maxval,
            full.channels,
            full.channel_order,
            full.row_order,
        )


__all__ = ["_assert_image_window", "_pixels"]
