"""Image-family O5 partial-read behavior coverage."""

from __future__ import annotations

import numpy as np
import pytest
from _support.partial_read import _assert_image_window

import sceneio
from sceneio import _core
from sceneio.io import FormatError


@pytest.mark.parametrize("channels", [1, 3])
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_binary_netpbm_window_branch_matrix(tmp_path, channels, dtype):
    rng = np.random.default_rng(510 + channels + np.dtype(dtype).itemsize)
    shape = (7, 9) if channels == 1 else (7, 9, channels)
    high = 256 if dtype == np.uint8 else 65536
    values = rng.integers(0, high, shape, dtype=dtype)
    path = tmp_path / f"binary-{channels}-{np.dtype(dtype).name}.pnm"
    path.write_bytes(
        bytes(_core.write_netpbm(_core.image(values), False))
    )
    full = sceneio.read(path, format="netpbm")
    for window in ((0, 3, 0, 4), (1, 6, 1, 8), (2, 7, 3, 9)):
        _assert_image_window(
            sceneio.read_partial(
                path, format="netpbm", window=window
            ),
            full,
            window,
        )


@pytest.mark.parametrize("channels", [1, 3])
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_ascii_netpbm_windows_reject_complete_payload_decode(
    tmp_path, channels, dtype
):
    shape = (3, 4) if channels == 1 else (3, 4, channels)
    values = np.arange(np.prod(shape), dtype=dtype).reshape(shape)
    path = tmp_path / f"ascii-{channels}-{np.dtype(dtype).name}.pnm"
    path.write_bytes(bytes(_core.write_netpbm(_core.image(values), True)))
    with pytest.raises(FormatError, match="binary P5/P6"):
        sceneio.read_partial(
            path, format="netpbm", window=(0, 2, 1, 4)
        )


@pytest.mark.parametrize("channels", [3, 4])
def test_lossy_webp_windows_reject_non_slice_exact_decode(
    tmp_path, channels
):
    rng = np.random.default_rng(520 + channels)
    values = rng.integers(0, 256, (31, 37, channels), dtype=np.uint8)
    if channels == 4:
        values[..., 3] = rng.integers(0, 255, (31, 37), dtype=np.uint8)
    image = _core.image(
        values,
        color_space="srgb",
        alpha_mode="straight" if channels == 4 else None,
    )
    path = tmp_path / f"lossy-{channels}.webp"
    path.write_bytes(bytes(_core.write_webp(image, False, 50.0)))
    with pytest.raises(FormatError, match="lossless VP8L"):
        sceneio.read_partial(
            path, format="webp", window=(3, 26, 5, 30)
        )
