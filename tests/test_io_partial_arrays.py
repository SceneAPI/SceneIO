"""Array-family O5 partial-read behavior coverage."""

from __future__ import annotations

import gc
import struct

import numpy as np
import pytest

import sceneio
from sceneio import FormatError, _core


def test_dmb_pixel_windows_equal_full_depth_slices(tmp_path):
    values = np.arange(7 * 9, dtype=np.float32).reshape(7, 9)
    record = _core.depth_map(
        values,
        unit="unknown",
        invalid_policy="zero",
    )
    path = tmp_path / "window.dmb"
    sceneio.write(record, path)
    full = sceneio.read(path)
    for window in (
        (0, 1, 0, 1),
        (1, 6, 1, 8),
        (6, 7, 8, 9),
        (0, 7, 0, 9),
    ):
        row_start, row_stop, col_start, col_stop = window
        partial = sceneio.read_partial(path, window=window)
        assert isinstance(partial, _core.DepthMap)
        np.testing.assert_array_equal(
            partial.depth,
            full.depth[row_start:row_stop, col_start:col_stop],
        )
        assert (
            partial.unit,
            partial.scale_to_meters,
            partial.invalid_policy,
            partial.row_order,
            partial.has_confidence,
        ) == (
            full.unit,
            full.scale_to_meters,
            full.invalid_policy,
            full.row_order,
            False,
        )


def test_partial_flo_window_retains_mapping_and_is_read_only(tmp_path):
    path = tmp_path / "flow.flo"
    height, width = 6, 7
    values = np.arange(height * width * 2, dtype=np.float32).reshape(
        height, width, 2
    )
    path.write_bytes(
        b"PIEH" + struct.pack("<ii", width, height) + values.tobytes()
    )
    window = sceneio.read_partial(
        path, format="flo", window=(1, 5, 2, 6)
    )
    gc.collect()
    np.testing.assert_array_equal(window, values[1:5, 2:6])
    assert not window.flags.writeable
    with pytest.raises(ValueError):
        window[0, 0, 0] = 123.0


def test_invalid_flo_window_releases_mapping_with_retained_exception(
    tmp_path,
):
    path = tmp_path / "flow.flo"
    values = np.zeros((6, 7, 2), dtype=np.float32)
    path.write_bytes(b"PIEH" + struct.pack("<ii", 7, 6) + values.tobytes())
    retained = None
    try:
        sceneio.read_partial(
            path, format="flo", window=(0, 7, 0, 1)
        )
    except FormatError as error:
        retained = error
    assert retained is not None
    replacement = tmp_path / "flow-replaced.flo"
    path.replace(replacement)
    path.write_bytes(b"replacement")
