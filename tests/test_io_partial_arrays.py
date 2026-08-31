"""Array-family O5 partial-read behavior coverage."""

from __future__ import annotations

import gc
import struct

import numpy as np

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


def test_partial_flo_window_returns_an_owning_flow_field(tmp_path):
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
    path.unlink()
    gc.collect()
    assert isinstance(window, _core.FlowField)
    np.testing.assert_array_equal(window.vectors, values[1:5, 2:6])
    assert window.vectors.flags.owndata is False
    assert (
        window.component_order,
        window.u_axis,
        window.v_axis,
        window.row_order,
        window.unit,
        window.invalid_policy,
    ) == (
        "uv",
        "right",
        "down",
        "top_to_bottom",
        "pixels",
        "component_abs_gt_1e9",
    )


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
