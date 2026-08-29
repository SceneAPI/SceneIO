from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tinyusdz

import sceneio
from sceneio.io._usd import animation, package, stage

_TIMES = np.array([-2.5, 1.0, 4.75], dtype=np.float64)
_MATRICES = np.array(
    [
        ((1, 0, 0, -2), (0, 1, 0, 1), (0, 0, 1, 3), (0, 0, 0, 1)),
        ((2, 0, 0, 5), (0, 3, 0, 8), (0, 0, 4, 11), (0, 0, 0, 1)),
        ((5, 0, 0, 20), (0, 7, 0, 12), (0, 0, 9, 17), (0, 0, 0, 1)),
    ],
    dtype=np.float64,
)

_ANIMATED_USDA = """#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Y"
    metersPerUnit = 0.5
    startTimeCode = -3
    endTimeCode = 6.25
    timeCodesPerSecond = 30
)
def Xform "World"
{
    token visibility.timeSamples = {
        -3: "inherited",
        0: "invisible",
        4.5: "inherited"
    }
    matrix4d xformOp:transform.timeSamples = {
        -2.5: ((1,0,0,-2),(0,1,0,1),(0,0,1,3),(0,0,0,1)),
        1: ((2,0,0,5),(0,3,0,8),(0,0,4,11),(0,0,0,1)),
        4.75: ((5,0,0,20),(0,7,0,12),(0,0,9,17),(0,0,0,1))
    }
    uniform token[] xformOpOrder = ["xformOp:transform"]

    def ParticleField3DGaussianSplat "Cloud"
    {
        point3f[] positions = [(1, 2, 3)]
        quatf[] orientations = [(1, 0, 0, 0)]
        float3[] scales = [(0.5, 1, 2)]
        float[] opacities = [0.75]
        uniform int radiance:sphericalHarmonicsDegree = 0
        float3[] radiance:sphericalHarmonicsCoefficients = [(0.1, 0.2, 0.3)]
        uniform token projectionModeHint = "perspective"
        uniform token sortingModeHint = "zDepth"
    }
}
"""


def _write_fixture(tmp_path: Path, suffix: str) -> Path:
    source = tmp_path / "animated.usda"
    source.write_text(_ANIMATED_USDA, encoding="utf-8")
    if suffix == ".usda":
        return source
    destination = tmp_path / "animated.usdz"
    package.write_usdz_archive(source, destination)
    return destination


def _expected_matrix(time: float) -> np.ndarray:
    index = int(np.searchsorted(_TIMES, time, side="left"))
    if index == 0:
        return _MATRICES[0]
    if index == len(_TIMES):
        return _MATRICES[-1]
    if _TIMES[index] == time:
        return _MATRICES[index]
    lower = index - 1
    alpha = (time - _TIMES[lower]) / (_TIMES[index] - _TIMES[lower])
    return _MATRICES[lower] + alpha * (_MATRICES[index] - _MATRICES[lower])


def _expected_visibility(time: float) -> str:
    if time < 0:
        return "inherited"
    if time < 4.5:
        return "invisible"
    return "inherited"


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
@pytest.mark.parametrize("time", [-7.25, -2.5, -0.25, 1.0, 2.125, 4.75, 9.5])
def test_selected_time_matrix_visibility_hierarchy_and_static_payload(
    tmp_path,
    suffix,
    time,
):
    path = _write_fixture(tmp_path, suffix)

    actual = sceneio.read_scene(path, time=time)

    assert actual.node_names == ["World", "Cloud"]
    np.testing.assert_array_equal(actual.node_parents, [-1, 0])
    np.testing.assert_allclose(
        actual.node_local_transforms[0],
        _expected_matrix(time),
        rtol=0,
        atol=1e-14,
    )
    np.testing.assert_array_equal(actual.node_local_transforms[1], np.eye(4))
    assert actual.node_visibility == [_expected_visibility(time), "inherited"]
    assert actual.selected_time == time
    assert actual.time_codes_per_second == 30.0
    assert actual.source_representation == suffix.removeprefix(".")
    assert actual.node_payload_kinds == ["none", "gaussian_cloud"]
    np.testing.assert_array_equal(
        actual.gaussian_cloud_at(0).means,
        [[1, 2, 3]],
    )


def test_selected_time_preserves_prim_selection_and_reset_stack(tmp_path):
    text = _ANIMATED_USDA.replace(
        '["xformOp:transform"]',
        '["!resetXformStack!", "xformOp:transform"]',
    )
    path = tmp_path / "reset.usda"
    path.write_text(text, encoding="utf-8")

    actual = sceneio.read_scene(path, time=2.125, prims="/World/Cloud")

    assert actual.node_names == ["World", "Cloud"]
    np.testing.assert_array_equal(actual.node_resets_transform_stack, [1, 0])
    np.testing.assert_allclose(actual.node_local_transforms[0], _expected_matrix(2.125))


def test_selected_time_animates_a_static_gaussian_payload_node(tmp_path):
    text = _ANIMATED_USDA.replace(
        '    def ParticleField3DGaussianSplat "Cloud"\n    {',
        """    def ParticleField3DGaussianSplat "Cloud"
    {
        matrix4d xformOp:transform.timeSamples = {
            -1: ((1,0,0,0),(0,1,0,1),(0,0,1,0),(0,0,0,1)),
            3: ((1,0,0,0),(0,1,0,5),(0,0,1,0),(0,0,0,1))
        }
        uniform token[] xformOpOrder = ["xformOp:transform"]""",
    )
    path = tmp_path / "animated-gaussian.usda"
    path.write_text(text, encoding="utf-8")

    actual = sceneio.read_scene(path, time=1.0)

    assert actual.node_payload_kinds == ["none", "gaussian_cloud"]
    np.testing.assert_array_equal(
        actual.node_local_transforms[1, :3, 3],
        [0, 3, 0],
    )
    np.testing.assert_array_equal(actual.gaussian_cloud_at(0).means, [[1, 2, 3]])


def test_authored_samples_require_selected_time_and_inspection_is_explicit(
    tmp_path,
    monkeypatch,
):
    path = _write_fixture(tmp_path, ".usda")
    assert stage._root_layer_has_time_samples(path) is True

    with pytest.raises(
        sceneio.FormatError,
        match=r"authored time samples require read_scene.*animation preservation",
    ):
        sceneio.read_scene(path)

    info = sceneio.inspect(path)
    assert info.metadata["provider_selected_time"] is True
    assert info.metadata["selected_time_profile"] == (
        "direct_usda_matrix_visibility_v1"
    )
    assert info.metadata["selected_time_representation_supported"] is True
    assert info.metadata["sampled_properties"] == (
        "/World:visibility",
        "/World:xformOp:transform",
    )
    assert info.metadata["sample_count"] == 6
    assert info.metadata["sample_time_range"] == (-3.0, 4.75)
    assert "/World: time_samples" in info.metadata["unsupported_features"]

    def unexpected_static_parse(*args, **kwargs):
        raise AssertionError("static prim inspection parsed declarations")

    monkeypatch.setattr(animation, "_direct_declarations", unexpected_static_parse)
    assert not animation.sampled_property_names(
        '    point3f[] points = [(0, 0, 0)]\n',
        context="static mesh",
    )
    static_path = tmp_path / "static.usda"
    static_path.write_text(
        '#usda 1.0\ndef Mesh "Static"\n{\n    point3f[] points = []\n}\n',
        encoding="utf-8",
    )
    assert stage._root_layer_has_time_samples(static_path) is False


def test_selected_snapshot_write_is_static_not_dynamic_preservation(tmp_path):
    source = _write_fixture(tmp_path, ".usda")
    selected = sceneio.read_scene(source, time=2.125)
    destination = tmp_path / "snapshot.usda"

    sceneio.write_scene(selected, destination)

    authored = destination.read_text(encoding="utf-8")
    assert ".timeSamples" not in authored
    reopened = sceneio.read_scene(destination)
    np.testing.assert_allclose(
        reopened.node_local_transforms,
        selected.node_local_transforms,
    )
    assert reopened.node_visibility == selected.node_visibility


def test_non_node_samples_and_arbitrary_xform_stacks_are_refused(tmp_path):
    points = tmp_path / "deforming.usda"
    points.write_text(
        """#usda 1.0
def Points "Samples"
{
    point3f[] points.timeSamples = {
        0: [(0, 0, 0)],
        1: [(1, 0, 0)]
    }
}
""",
        encoding="utf-8",
    )
    with pytest.raises(
        sceneio.FormatError,
        match=r"time-varying properties.*points",
    ):
        sceneio.read_scene(points, time=0.5)

    stacked = tmp_path / "stacked.usda"
    stacked.write_text(
        _ANIMATED_USDA.replace(
            'uniform token[] xformOpOrder = ["xformOp:transform"]',
            """double3 xformOp:translate = (1, 2, 3)
    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:transform"]""",
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        sceneio.FormatError,
        match="single matrix xformOp stack",
    ):
        sceneio.read_scene(stacked, time=0.5)


def test_selected_time_parser_refuses_malformed_and_bounded_values(monkeypatch):
    duplicate = """def Xform "World"
{
    token visibility.timeSamples = {
        0: "inherited",
        0: "invisible"
    }
}
"""
    with pytest.raises(ValueError, match="duplicate sample time"):
        animation.parse_prim_samples(duplicate, path="/World")

    invalid = duplicate.replace(
        '0: "inherited",\n        0: "invisible"',
        '0: "visible"',
    )
    with pytest.raises(ValueError, match="unsupported sampled visibility"):
        animation.parse_prim_samples(invalid, path="/World")

    nonfinite = duplicate.replace(
        '0: "inherited",\n        0: "invisible"',
        'nan: "inherited"',
    )
    with pytest.raises(ValueError, match="expected a finite numeric value"):
        animation.parse_prim_samples(nonfinite, path="/World")

    monkeypatch.setattr(animation, "_MAX_SAMPLES_PER_PROPERTY", 1)
    bounded = duplicate.replace('0: "invisible"', '1: "invisible"')
    with pytest.raises(ValueError, match="sample limit exceeded"):
        animation.parse_prim_samples(bounded, path="/World")


def test_selected_time_does_not_claim_usdc_support(tmp_path):
    provider_stage = tinyusdz.loads(_ANIMATED_USDA)
    source = tmp_path / "animated.usdc"
    source.write_bytes(b"PXR-USDC\x00\x0a")

    with pytest.raises(
        ValueError,
        match="limited to directly authored USDA root layers",
    ):
        stage.stage_to_scene_graph(
            provider_stage,
            source_path=source,
            source_representation="usdc",
            time=1.0,
        )
