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
    quaternion_norm: str = "unconstrained",
    sh_basis: str = "3dgs_real",
    sh_phase: str = "3dgs",
    sh_coefficient_order: str = "degree_then_m_neg_to_pos",
    color_space: str = "unknown",
    coordinate_frame: str = "unknown",
    scale_to_meters: float | None = None,
    scale_to_meters_source: str = "unknown",
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
        quaternion_norm=quaternion_norm,
        sh_basis=sh_basis,
        sh_phase=sh_phase,
        sh_coefficient_order=sh_coefficient_order,
        color_space=color_space,
        coordinate_frame=coordinate_frame,
        scale_to_meters=scale_to_meters,
        scale_to_meters_source=scale_to_meters_source,
    )


def test_gaussian_cloud_3dgs_conventions_are_the_defaults():
    cloud = _cloud()

    assert (
        cloud.quaternion_order,
        cloud.scale_space,
        cloud.opacity_space,
        cloud.sh_layout,
        cloud.source_precision,
        cloud.projection_mode_hint,
        cloud.sorting_mode_hint,
        cloud.quaternion_norm,
        cloud.sh_basis,
        cloud.sh_phase,
        cloud.sh_coefficient_order,
        cloud.color_space,
        cloud.coordinate_frame,
        cloud.scale_to_meters,
        cloud.scale_to_meters_source,
    ) == (
        "wxyz",
        "log",
        "logit",
        "channel_grouped",
        "float32",
        "perspective",
        "zDepth",
        "unconstrained",
        "3dgs_real",
        "3dgs",
        "degree_then_m_neg_to_pos",
        "unknown",
        "unknown",
        None,
        "unknown",
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
        ("quaternion_norm", "normalized", "quaternion_norm"),
        ("sh_basis", "complex", "sh_basis"),
        ("sh_phase", "none", "sh_phase"),
        ("sh_coefficient_order", "xyz", "sh_coefficient_order"),
        ("color_space", "display-p3", "color_space"),
        ("coordinate_frame", "rub", "coordinate_frame"),
        ("scale_to_meters_source", "header", "scale_to_meters_source"),
    ],
)
def test_gaussian_cloud_rejects_unknown_conventions(keyword, value, message):
    with pytest.raises(ValueError, match=message):
        _cloud(**{keyword: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("means", np.zeros((2, 3, 1), np.float32)),
        ("scales", np.zeros((2, 3, 1), np.float32)),
        ("quaternions", np.zeros((2, 4, 1), np.float32)),
        ("opacities", np.zeros((2, 1), np.float32)),
        ("opacities", np.zeros((2, 0), np.float32)),
        ("sh_dc", np.zeros((2, 3, 1), np.float32)),
        ("sh_rest", np.zeros((2, 9, 1), np.float32)),
    ],
)
def test_gaussian_cloud_factory_requires_exact_array_ranks(field, value):
    arrays = {
        "means": np.zeros((2, 3), np.float32),
        "scales": np.zeros((2, 3), np.float32),
        "quaternions": np.ones((2, 4), np.float32),
        "opacities": np.zeros(2, np.float32),
        "sh_dc": np.zeros((2, 3), np.float32),
        "sh_rest": np.zeros((2, 9), np.float32),
    }
    arrays[field] = value

    with pytest.raises(ValueError, match="shape"):
        _core.gaussian_cloud(
            arrays["means"],
            arrays["scales"],
            arrays["quaternions"],
            arrays["opacities"],
            arrays["sh_dc"],
            arrays["sh_rest"],
        )


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
    assert converted.quaternion_norm == "unconstrained"

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


def test_explicit_conversion_can_prepare_usd_cloud_for_3dgs_writers():
    source = _cloud(
        scales=np.ones((2, 3), np.float32),
        opacities=np.array([0.25, 0.75], np.float32),
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
        source_precision="float16",
        projection_mode_hint="tangential",
        sorting_mode_hint="cameraDistance",
    )

    converted = sceneio.convert_gaussian_conventions(
        source,
        scale_space="log",
        opacity_space="logit",
        sh_layout="channel_grouped",
        source_precision="float32",
        projection_mode_hint="perspective",
        sorting_mode_hint="zDepth",
        normalize_quaternions=True,
    )

    np.testing.assert_allclose(
        np.linalg.norm(converted.quaternions, axis=1),
        1.0,
        atol=1e-6,
    )
    assert converted.source_precision == "float32"
    assert converted.projection_mode_hint == "perspective"
    assert converted.sorting_mode_hint == "zDepth"
    assert converted.quaternion_norm == "unit"
    assert _core.read_gaussian_ply(
        _core.write_gaussian_ply(converted)
    ).num_gaussians == 2


def test_gaussian_metric_metadata_requires_a_positive_value_and_source():
    with pytest.raises(ValueError, match="known source"):
        _cloud(scale_to_meters=1.0)
    with pytest.raises(ValueError, match="requires scale_to_meters"):
        _cloud(scale_to_meters_source="caller")
    with pytest.raises(ValueError, match="finite and positive"):
        _cloud(scale_to_meters=0.0, scale_to_meters_source="caller")

    cloud = _cloud(
        coordinate_frame="opengl",
        scale_to_meters=0.01,
        scale_to_meters_source="caller",
    )
    assert cloud.scale_to_meters == 0.01
    assert cloud.scale_to_meters_source == "caller"


def test_unit_quaternion_metadata_is_checked_and_explicit_normalization_sets_it():
    with pytest.raises(ValueError, match="requires unit values"):
        _cloud(quaternion_norm="unit")

    converted = sceneio.convert_gaussian_conventions(
        _cloud(),
        normalize_quaternions=True,
    )
    assert converted.quaternion_norm == "unit"
    np.testing.assert_allclose(
        np.linalg.norm(converted.quaternions, axis=1),
        1.0,
        atol=1e-6,
    )

    with pytest.raises(ValueError, match="requires normalize_quaternions"):
        sceneio.convert_gaussian_conventions(
            _cloud(), quaternion_norm="unit"
        )


def test_new_semantic_factory_fields_are_keyword_only():
    cloud = _cloud()
    with pytest.raises(TypeError):
        _core.gaussian_cloud(
            cloud.means,
            cloud.scales,
            cloud.quaternions,
            cloud.opacities,
            cloud.sh_dc,
            cloud.sh_rest,
            "wxyz",
            "log",
            "logit",
            "channel_grouped",
            "float32",
            "perspective",
            "zDepth",
            "unit",
        )


def test_metadata_conversion_refuses_unperformed_float16_quantization():
    with pytest.raises(ValueError, match="numeric quantization"):
        sceneio.convert_gaussian_conventions(
            _cloud(), source_precision="float16"
        )


def test_float32_sigmoid_saturation_is_explicitly_one_way():
    source = _cloud(opacities=np.array([20.0, -200.0], np.float32))
    activated = sceneio.convert_gaussian_conventions(
        source, opacity_space="linear"
    )

    np.testing.assert_array_equal(activated.opacities, [1.0, 0.0])
    with pytest.raises(ValueError, match="strictly between zero and one"):
        sceneio.convert_gaussian_conventions(
            activated, opacity_space="logit"
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
def test_3dgs_writers_refuse_usd_conventions(
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
def test_3dgs_writers_refuse_nondefault_usd_hints(
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
