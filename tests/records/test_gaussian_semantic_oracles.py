"""Independent checks for the qualified GaussianCloud operations.

The record deliberately carries storage conventions (activation spaces,
quaternion component order, and SH memory layout), but it does not carry a
universal quaternion state, SH basis/phase, color-space, or coordinate-frame
contract.  These tests therefore exercise only the transformations SceneIO
claims. SciPy independently checks rotations and opacity activations; Python
scalar math and index-addressed arrays check scale activation and SH storage
without duplicating the C++ conversion loops.
"""

from __future__ import annotations

import math
from itertools import product

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from scipy.special import expit, logit

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


def test_gaussian_cloud_keeps_unqualified_semantics_absent_and_refuses_coordinate_conversion():
    cloud = _cloud()
    forbidden_fields = (
        "quaternion_state",
        "quaternion_unit_state",
        "is_unit_quaternion",
        "sh_basis",
        "sh_phase",
        "sh_basis_phase",
        "color_space",
        "coordinate_frame",
        "world_frame",
        "up_axis",
        "scale_to_meters",
    )
    assert all(not hasattr(cloud, field) for field in forbidden_fields)
    assert sceneio.coordinate_convention(cloud) == sceneio.UNKNOWN_COORDINATES

    for keyword in (
        "quaternion_state",
        "sh_basis",
        "sh_phase",
        "color_space",
        "coordinate_frame",
    ):
        with pytest.raises(TypeError):
            sceneio.convert_gaussian_conventions(cloud, **{keyword: "unqualified"})

    with pytest.raises(TypeError, match="not qualified"):
        sceneio.convert_coordinates(cloud, target=sceneio.COLMAP_COORDINATES)
