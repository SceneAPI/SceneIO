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


def _assert_point_range(partial, full, start, stop):
    if isinstance(full, _core.PointCloud):
        assert isinstance(partial, _core.PointCloud)
        assert partial.num_points == stop - start
        assert (
            partial.coordinate_frame,
            partial.scale_to_meters,
            partial.intensity_range,
            partial.origin,
            partial.viewpoint,
        ) == (
            full.coordinate_frame,
            full.scale_to_meters,
            full.intensity_range,
            full.origin,
            full.viewpoint,
        )
        for name in (
            "positions",
            "colors",
            "colors16",
            "normals",
            "intensities",
        ):
            expected = np.asarray(getattr(full, name))
            actual = np.asarray(getattr(partial, name))
            if expected.shape[0] == 0:
                assert actual.shape == expected.shape
            else:
                np.testing.assert_array_equal(actual, expected[start:stop])
    else:
        assert isinstance(partial, _core.GaussianCloud)
        assert partial.num_gaussians == stop - start
        assert (partial.sh_degree, partial.num_rest) == (
            full.sh_degree,
            full.num_rest,
        )
        assert (
            partial.quaternion_order,
            partial.scale_space,
            partial.opacity_space,
            partial.sh_layout,
        ) == (
            full.quaternion_order,
            full.scale_space,
            full.opacity_space,
            full.sh_layout,
        )
        for name in (
            "means",
            "scales",
            "quaternions",
            "opacities",
            "sh_dc",
            "sh_rest",
        ):
            np.testing.assert_array_equal(
                np.asarray(getattr(partial, name)),
                np.asarray(getattr(full, name))[start:stop],
            )


__all__ = ["_assert_image_window", "_assert_point_range", "_pixels"]
