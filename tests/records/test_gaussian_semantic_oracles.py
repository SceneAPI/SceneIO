"""Independent checks for the qualified GaussianCloud operations.

The record carries both storage conventions and the qualified semantic tags
frozen in ``gaussian_semantics_v1.toml``. SciPy independently checks rotations
and opacity activations; Python scalar math and index-addressed arrays check
scale activation and SH storage without duplicating the C++ conversion loops.
"""

from __future__ import annotations

import math
from itertools import product

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from scipy.special import expit, logit, sph_harm_y

import sceneio
from sceneio import _core


def _cloud(
    *,
    quaternions: np.ndarray | None = None,
    scales: np.ndarray | None = None,
    opacities: np.ndarray | None = None,
    sh_rest: np.ndarray | None = None,
    quaternion_order: str = "wxyz",
    scale_space: str = "log",
    opacity_space: str = "logit",
    sh_layout: str = "channel_grouped",
    quaternion_norm: str = "unconstrained",
    sh_basis: str = "3dgs_real",
    sh_phase: str = "3dgs",
    sh_coefficient_order: str = "degree_then_m_neg_to_pos",
    color_space: str = "unknown",
    coordinate_frame: str = "unknown",
    scale_to_meters: float | None = None,
    scale_to_meters_source: str = "unknown",
):
    if quaternions is None:
        if scales is not None:
            count = np.asarray(scales).shape[0]
        elif opacities is not None:
            count = np.asarray(opacities).shape[0]
        elif sh_rest is not None:
            count = np.asarray(sh_rest).shape[0]
        else:
            count = 2
        quaternions = np.tile(
            np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), (count, 1)
        )
    quaternions = np.asarray(quaternions, dtype=np.float32)
    count = quaternions.shape[0]
    if scales is None:
        scales = np.ones((count, 3), dtype=np.float32)
    if opacities is None:
        opacities = np.full(count, 0.5, dtype=np.float32)
    if sh_rest is not None:
        sh_rest = np.asarray(sh_rest, dtype=np.float32)
    return _core.gaussian_cloud(
        np.zeros((count, 3), dtype=np.float32),
        np.asarray(scales, dtype=np.float32),
        quaternions,
        np.asarray(opacities, dtype=np.float32),
        np.zeros((count, 3), dtype=np.float32),
        sh_rest,
        quaternion_order=quaternion_order,
        scale_space=scale_space,
        opacity_space=opacity_space,
        sh_layout=sh_layout,
        quaternion_norm=quaternion_norm,
        sh_basis=sh_basis,
        sh_phase=sh_phase,
        sh_coefficient_order=sh_coefficient_order,
        color_space=color_space,
        coordinate_frame=coordinate_frame,
        scale_to_meters=scale_to_meters,
        scale_to_meters_source=scale_to_meters_source,
    )


def _as_xyzw(quaternions: np.ndarray, order: str) -> np.ndarray:
    """Convert storage order for the independent SciPy Rotation oracle."""

    values = np.asarray(quaternions, dtype=np.float64)
    if order == "xyzw":
        return values
    assert order == "wxyz"
    return values[:, [1, 2, 3, 0]]


@pytest.mark.parametrize(
    ("source_order", "target_order"),
    tuple(product(("wxyz", "xyzw"), repeat=2)),
)
def test_scipy_quaternion_reorder_and_normalization_is_rotation_equivalent(
    source_order, target_order
):
    source_quaternions = np.array(
        [[2.0, 0.5, 1.0, 0.25], [-0.3, 0.2, 0.9, -1.1]],
        dtype=np.float32,
    )
    source = _cloud(
        quaternions=source_quaternions,
        quaternion_order=source_order,
    )
    converted = sceneio.convert_gaussian_conventions(
        source,
        quaternion_order=target_order,
        normalize_quaternions=True,
    )

    # Rotation.from_quat is SciPy's XYZW implementation and normalizes the
    # non-unit source independently.  Compare matrices, not quaternion signs.
    expected_matrix = Rotation.from_quat(
        _as_xyzw(source_quaternions, source_order)
    ).as_matrix()
    converted_quaternions = np.asarray(converted.quaternions)
    actual_matrix = Rotation.from_quat(
        _as_xyzw(converted_quaternions, target_order)
    ).as_matrix()
    np.testing.assert_allclose(actual_matrix, expected_matrix, atol=3e-6, rtol=0.0)
    np.testing.assert_allclose(
        np.linalg.norm(converted_quaternions, axis=1), 1.0, atol=2e-6, rtol=0.0
    )
    assert converted.quaternion_norm == "unit"


def test_independent_oracles_cover_scale_and_opacity_activation_both_directions():
    raw_scales = np.array(
        [[-3.0, -0.5, 0.0], [0.25, 1.0, 2.0], [2.25, -1.25, 3.0]],
        dtype=np.float32,
    )
    raw_logits = np.array([-7.25, -1.5, 0.0], dtype=np.float32)
    source = _cloud(scales=raw_scales, opacities=raw_logits)

    activated = sceneio.convert_gaussian_conventions(
        source,
        scale_space="linear",
        opacity_space="linear",
    )
    expected_scales = np.asarray(
        [[math.exp(float(value)) for value in row] for row in raw_scales],
        dtype=np.float32,
    )
    np.testing.assert_allclose(
        np.asarray(activated.scales), expected_scales, atol=2e-6, rtol=0.0
    )
    np.testing.assert_allclose(
        np.asarray(activated.opacities), expit(raw_logits), atol=2e-7, rtol=0.0
    )

    restored = sceneio.convert_gaussian_conventions(
        activated,
        scale_space="log",
        opacity_space="logit",
    )
    expected_logs = np.asarray(
        [
            [math.log(float(value)) for value in row]
            for row in np.asarray(activated.scales)
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(
        np.asarray(restored.scales), expected_logs, atol=2e-6, rtol=0.0
    )
    np.testing.assert_allclose(
        np.asarray(restored.opacities),
        logit(np.asarray(activated.opacities)),
        atol=2e-5,
        rtol=0.0,
    )


@pytest.mark.parametrize("degree", [0, 1, 2, 3])
def test_index_oracle_covers_sh_memory_permutation_for_every_degree(degree):
    coefficient_count = (degree + 1) ** 2 - 1
    count = 2
    source_rest = np.empty((count, coefficient_count * 3), dtype=np.float32)
    if coefficient_count:
        # Encode point, channel, and coefficient in every source slot.  The
        # expected permutation below uses these indices directly rather than
        # duplicating SceneIO's reshape/transpose expression.
        for point, channel, coefficient in product(
            range(count), range(3), range(coefficient_count)
        ):
            source_rest[point, channel * coefficient_count + coefficient] = (
                10000.0 * point + 100.0 * channel + coefficient
            )
    source = _cloud(sh_rest=source_rest)
    converted = sceneio.convert_gaussian_conventions(
        source, sh_layout="coefficient_rgb"
    )
    actual = np.asarray(converted.sh_rest)
    expected = np.empty_like(actual)
    if coefficient_count:
        for point, channel, coefficient in product(
            range(count), range(3), range(coefficient_count)
        ):
            expected[point, coefficient * 3 + channel] = source_rest[
                point, channel * coefficient_count + coefficient
            ]

    np.testing.assert_array_equal(actual, expected)
    assert converted.sh_layout == "coefficient_rgb"

    restored = sceneio.convert_gaussian_conventions(
        converted, sh_layout="channel_grouped"
    )
    np.testing.assert_array_equal(np.asarray(restored.sh_rest), source_rest)


def test_gaussian_cloud_exposes_qualified_semantics_and_refuses_unknown_coordinates():
    cloud = _cloud()
    assert (
        cloud.quaternion_norm,
        cloud.sh_basis,
        cloud.sh_phase,
        cloud.sh_coefficient_order,
        cloud.color_space,
        cloud.coordinate_frame,
        cloud.scale_to_meters,
        cloud.scale_to_meters_source,
    ) == (
        "unconstrained",
        "3dgs_real",
        "3dgs",
        "degree_then_m_neg_to_pos",
        "unknown",
        "unknown",
        None,
        "unknown",
    )
    assert sceneio.coordinate_convention(cloud) == sceneio.UNKNOWN_COORDINATES

    for keyword, value in (
        ("sh_basis", "complex"),
        ("sh_phase", "condon_shortley"),
        ("sh_coefficient_order", "m_then_degree"),
        ("color_space", "srgb"),
        ("coordinate_frame", "opengl"),
    ):
        message = (
            "convert_coordinates"
            if keyword == "coordinate_frame"
            else "not qualified"
        )
        with pytest.raises(ValueError, match=message):
            sceneio.convert_gaussian_conventions(cloud, **{keyword: value})

    with pytest.raises(ValueError, match="requires world_transform"):
        sceneio.convert_coordinates(cloud, target=sceneio.COLMAP_COORDINATES)


def _eval_3dgs_degree_one(coefficients: np.ndarray, direction) -> np.ndarray:
    """Independent degree-1 equations from the original 3DGS reference."""

    x, y, z = np.asarray(direction, dtype=np.float64)
    c0 = 0.28209479177387814
    c1 = 0.4886025119029199
    return (
        c0 * coefficients[0]
        - c1 * y * coefficients[1]
        + c1 * z * coefficients[2]
        - c1 * x * coefficients[3]
    )


@pytest.mark.parametrize(
    "direction",
    [
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        tuple(np.array([1.0, -2.0, 3.0]) / np.sqrt(14.0)),
    ],
)
def test_3dgs_degree_zero_one_basis_phase_and_order_are_hand_computable(direction):
    dc = np.array([[2.0, -3.0, 4.0]], dtype=np.float32)
    # Channel-grouped order: R[-1,0,+1], G[-1,0,+1], B[-1,0,+1].
    rest = np.array(
        [[1.0, 2.0, 3.0, -4.0, 5.0, -6.0, 7.0, -8.0, 9.0]],
        dtype=np.float32,
    )
    cloud = _core.gaussian_cloud(
        np.zeros((1, 3), np.float32),
        np.zeros((1, 3), np.float32),
        np.array([[1.0, 0.0, 0.0, 0.0]], np.float32),
        np.zeros(1, np.float32),
        dc,
        rest,
    )
    assert cloud.sh_basis == "3dgs_real"
    assert cloud.sh_phase == "3dgs"
    assert cloud.sh_coefficient_order == "degree_then_m_neg_to_pos"

    # Build [coefficient, RGB] without sharing SceneIO's layout-conversion code.
    coefficients = np.vstack((dc[0], rest.reshape(3, 3).T))
    expected = _eval_3dgs_degree_one(coefficients, direction)

    packed = sceneio.convert_gaussian_conventions(
        cloud, sh_layout="coefficient_rgb"
    )
    actual_coefficients = np.vstack(
        (
            np.asarray(packed.sh_dc)[0],
            np.asarray(packed.sh_rest)[0].reshape(3, 3),
        )
    )
    np.testing.assert_allclose(
        _eval_3dgs_degree_one(actual_coefficients, direction),
        expected,
        atol=1e-7,
        rtol=0.0,
    )


def test_3dgs_degree_one_basis_matches_independent_equations_at_seeded_directions():
    rng = np.random.default_rng(0x3D65)
    directions = rng.normal(size=(32, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    coefficients = rng.normal(size=(4, 3))

    expected = np.empty((len(directions), 3), dtype=np.float64)
    for index, (x, y, z) in enumerate(directions):
        polar = math.acos(z)
        azimuth = math.atan2(y, x)
        y00 = sph_harm_y(0, 0, polar, azimuth)
        y11 = sph_harm_y(1, 1, polar, azimuth)
        basis = np.array(
            [
                y00.real,
                math.sqrt(2.0) * y11.imag,
                sph_harm_y(1, 0, polar, azimuth).real,
                math.sqrt(2.0) * y11.real,
            ]
        )
        expected[index] = basis @ coefficients

    actual = np.vstack(
        [_eval_3dgs_degree_one(coefficients, direction) for direction in directions]
    )
    np.testing.assert_allclose(actual, expected, atol=1e-13, rtol=0.0)


def test_degree_zero_gaussian_coordinate_conversion_updates_mean_scale_and_rotation():
    source = _core.gaussian_cloud(
        np.array([[1.0, 2.0, 3.0]], np.float32),
        np.array([[0.0, math.log(2.0), math.log(3.0)]], np.float32),
        np.array([[1.0, 0.0, 0.0, 0.0]], np.float32),
        np.zeros(1, np.float32),
        np.zeros((1, 3), np.float32),
        coordinate_frame="opengl",
        scale_to_meters=0.01,
        scale_to_meters_source="file",
    )
    target = sceneio.CoordinateConvention(
        name="metric_opencv_mm",
        camera_axes="opencv",
        handedness="right_handed",
        quaternion_order="xyzw",
        quaternion_algebra="hamilton",
        world_frame="arbitrary",
        up_axis="unknown",
        scale_class="metric",
        scale_to_meters=0.001,
    )

    converted = sceneio.convert_coordinates(source, target=target)

    np.testing.assert_allclose(converted.means, [[10.0, -20.0, -30.0]])
    np.testing.assert_allclose(
        converted.scales,
        np.asarray(source.scales) + math.log(10.0),
        atol=1e-6,
    )
    expected_rotation = Rotation.from_euler("x", 180.0, degrees=True).as_matrix()
    actual_rotation = Rotation.from_quat(converted.quaternions).as_matrix()[0]
    np.testing.assert_allclose(actual_rotation, expected_rotation, atol=2e-6)
    assert converted.quaternion_order == "xyzw"
    assert converted.quaternion_norm == "unit"
    assert converted.coordinate_frame == "opencv"
    assert converted.scale_to_meters == 0.001
    assert converted.scale_to_meters_source == "caller"
    assert sceneio.coordinate_convention(converted) == target


def test_gaussian_coordinate_conversion_preserves_known_scale_for_arbitrary_target():
    source = _cloud(
        coordinate_frame="opengl",
        scale_to_meters=0.01,
        scale_to_meters_source="file",
    )
    target = sceneio.CoordinateConvention(
        name="arbitrary_opengl",
        camera_axes="opengl",
        handedness="right_handed",
        quaternion_order="wxyz",
        quaternion_algebra="hamilton",
        world_frame="arbitrary",
        up_axis="y",
        scale_class="arbitrary",
    )

    converted = sceneio.convert_coordinates(
        source,
        target=target,
        world_transform=np.array(
            [
                [1.0, 0.0, 0.0, 0.25],
                [0.0, 1.0, 0.0, -0.5],
                [0.0, 0.0, 1.0, 0.75],
                [0.0, 0.0, 0.0, 1.0],
            ]
        ),
    )
    assert converted.scale_to_meters == 0.01
    assert converted.scale_to_meters_source == "file"


@pytest.mark.parametrize(
    ("linear", "message"),
    [
        (np.diag([-1.0, 1.0, 1.0]), "orientation-preserving"),
        (np.diag([2.0, 1.0, 1.0]), "similarity world_transform"),
    ],
)
def test_gaussian_coordinate_conversion_refuses_reflection_and_nonsimilarity(
    linear, message
):
    source = _cloud(
        coordinate_frame="opengl",
        scale_to_meters=1.0,
        scale_to_meters_source="caller",
    )
    transform = np.eye(4)
    transform[:3, :3] = linear
    with pytest.raises(ValueError, match=message):
        sceneio.convert_coordinates(
            source,
            target=source.coordinates,
            world_transform=transform,
        )


def test_directional_sh_coordinate_rotation_requires_an_explicit_policy():
    source = _cloud(
        sh_rest=np.zeros((1, 9), np.float32),
        coordinate_frame="opengl",
        scale_to_meters=1.0,
        scale_to_meters_source="caller",
    )
    target = sceneio.CoordinateConvention(
        name="opencv",
        camera_axes="opencv",
        handedness="right_handed",
        world_frame="arbitrary",
        scale_class="metric",
        scale_to_meters=1.0,
    )
    with pytest.raises(ValueError, match="directional SH"):
        sceneio.convert_coordinates(source, target=target)
