from __future__ import annotations

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _cloud(
    *,
    scales: np.ndarray | None = None,
    opacities: np.ndarray | None = None,
    quaternion_order: str = "wxyz",
    scale_space: str = "log",
    opacity_space: str = "logit",
    sh_layout: str = "channel_grouped",
    source_precision: str = "float32",
    projection_mode_hint: str = "perspective",
    sorting_mode_hint: str = "zDepth",
):
    means = np.array([[1, 2, 3], [4, 5, 6]], np.float32)
    quaternions = np.array(
        [[1, 0.25, 0.5, 0.75], [0.5, -0.25, -0.5, -0.75]],
        np.float32,
    )
    sh_dc = np.arange(6, dtype=np.float32).reshape(2, 3)
    sh_rest = np.arange(18, dtype=np.float32).reshape(2, 9)
    return _core.gaussian_cloud(
        means,
        (
            np.array([[0, 1, -1], [2, -2, 0.5]], np.float32)
            if scales is None
            else scales
        ),
        quaternions,
        (
            np.array([-2, 2], np.float32)
            if opacities is None
            else opacities
        ),
        sh_dc,
        sh_rest,
        quaternion_order=quaternion_order,
        scale_space=scale_space,
        opacity_space=opacity_space,
        sh_layout=sh_layout,
        source_precision=source_precision,
        projection_mode_hint=projection_mode_hint,
        sorting_mode_hint=sorting_mode_hint,
    )


def test_gaussian_cloud_legacy_conventions_remain_the_defaults():
    cloud = _cloud()

    assert (
        cloud.quaternion_order,
        cloud.scale_space,
        cloud.opacity_space,
        cloud.sh_layout,
        cloud.source_precision,
        cloud.projection_mode_hint,
        cloud.sorting_mode_hint,
    ) == (
        "wxyz",
        "log",
        "logit",
        "channel_grouped",
        "float32",
        "perspective",
        "zDepth",
    )


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        ("quaternion_order", "real_first", "quaternion_order"),
        ("scale_space", "activated", "scale_space"),
        ("opacity_space", "alpha", "opacity_space"),
        ("sh_layout", "rgb_planar", "sh_layout"),
        ("source_precision", "float64", "source_precision"),
        ("projection_mode_hint", "fisheye", "projection_mode_hint"),
        ("sorting_mode_hint", "none", "sorting_mode_hint"),
    ],
)
def test_gaussian_cloud_rejects_unknown_conventions(keyword, value, message):
    with pytest.raises(ValueError, match=message):
        _cloud(**{keyword: value})


def test_explicit_gaussian_conversion_maps_activation_and_layout():
    source = _cloud()

    converted = sceneio.convert_gaussian_conventions(
        source,
        quaternion_order="xyzw",
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
    )

    np.testing.assert_allclose(
        np.asarray(converted.scales),
        np.exp(np.asarray(source.scales)),
        rtol=1e-6,
    )
    np.testing.assert_allclose(
        np.asarray(converted.opacities),
        1.0 / (1.0 + np.exp(-np.asarray(source.opacities))),
        rtol=1e-6,
    )
    np.testing.assert_array_equal(
        np.asarray(converted.quaternions),
        np.asarray(source.quaternions)[:, [1, 2, 3, 0]],
    )
    expected_sh = (
        np.asarray(source.sh_rest)
        .reshape(source.num_gaussians, 3, source.num_rest // 3)
        .transpose(0, 2, 1)
        .reshape(source.num_gaussians, source.num_rest)
    )
    assert np.asarray(converted.sh_rest).tobytes() == expected_sh.tobytes()
    assert converted.source_precision == "float32"
    assert converted.projection_mode_hint == "perspective"
    assert converted.sorting_mode_hint == "zDepth"

    # Conversion returns independent record storage and does not retag input.
    assert source.quaternion_order == "wxyz"
    assert source.scale_space == "log"
    assert source.opacity_space == "logit"
    assert source.sh_layout == "channel_grouped"


def test_gaussian_layout_and_quaternion_conversion_are_bit_exact_roundtrip():
    source = _cloud()
    changed = sceneio.convert_gaussian_conventions(
        source,
        quaternion_order="xyzw",
        sh_layout="coefficient_rgb",
    )
    restored = sceneio.convert_gaussian_conventions(
        changed,
        quaternion_order="wxyz",
        sh_layout="channel_grouped",
    )

    assert (
        np.asarray(restored.quaternions).tobytes()
        == np.asarray(source.quaternions).tobytes()
    )
    assert (
        np.asarray(restored.sh_rest).tobytes()
        == np.asarray(source.sh_rest).tobytes()
    )


def test_gaussian_linear_to_raw_conversion_checks_domains():
    nonpositive_scale = _cloud(
        scales=np.array([[1, 0, 2], [1, 2, 3]], np.float32),
        scale_space="linear",
        opacity_space="linear",
        opacities=np.full(2, 0.5, np.float32),
    )
    with pytest.raises(ValueError, match="linear scales must be positive"):
        sceneio.convert_gaussian_conventions(
            nonpositive_scale, scale_space="log"
        )

    endpoint_opacity = _cloud(
        scales=np.ones((2, 3), np.float32),
        scale_space="linear",
        opacity_space="linear",
        opacities=np.array([0, 1], np.float32),
    )
    with pytest.raises(ValueError, match="strictly between zero and one"):
        sceneio.convert_gaussian_conventions(
            endpoint_opacity, opacity_space="logit"
        )


@pytest.mark.parametrize(
    ("format_id", "suffix"),
    [
        ("gaussian_ply", ".ply"),
        ("spz", ".spz"),
        ("compressed_ply", ".compressed.ply"),
        ("sog", ".sog"),
        ("ksplat", ".ksplat"),
        ("splat", ".splat"),
    ],
)
def test_legacy_splat_writers_refuse_usd_conventions(
    tmp_path, format_id, suffix
):
    cloud = _cloud(
        scales=np.ones((2, 3), np.float32),
        opacities=np.full(2, 0.5, np.float32),
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
        source_precision="float16",
    )

    with pytest.raises(
        sceneio.FormatError, match="convert explicitly before writing"
    ):
        sceneio.write(
            cloud,
            tmp_path / f"cloud{suffix}",
            format=format_id,
        )


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("projection_mode_hint", "tangential"),
        ("sorting_mode_hint", "cameraDistance"),
    ],
)
def test_legacy_splat_writers_refuse_nondefault_usd_hints(
    tmp_path, keyword, value
):
    cloud = _cloud(**{keyword: value})

    with pytest.raises(
        sceneio.FormatError, match="default USD rendering hints"
    ):
        sceneio.write(
            cloud,
            tmp_path / "cloud.ply",
            format="gaussian_ply",
        )
