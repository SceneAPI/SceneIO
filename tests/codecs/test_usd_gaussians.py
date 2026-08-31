from __future__ import annotations

import gc

import numpy as np
import pytest
import tinyusdz

import sceneio
from sceneio import _core
from sceneio.io._usd import gaussians

_FLOAT_FIXTURE = '''#usda 1.0
(
    defaultPrim = "Cloud"
    upAxis = "Y"
    metersPerUnit = 1
)
def ParticleField3DGaussianSplat "Cloud"
{
    matrix4d xformOp:transform = (
        (1, 0, 0, 2), (0, 1, 0, 3),
        (0, 0, 1, 4), (0, 0, 0, 1)
    )
    uniform token[] xformOpOrder = ["xformOp:transform"]
    uniform token purpose = "render"
    token visibility = "invisible"
    point3f[] positions = [(1, 2, 3), (4, 5, 6)]
    quatf[] orientations = [
        (0.5, 0.5, 0.5, 0.5), (0.5, -0.5, -0.5, -0.5)
    ]
    float3[] scales = [(1, 2, 3), (4, 5, 6)]
    float[] opacities = [0.25, 0.75]
    uniform int radiance:sphericalHarmonicsDegree = 1
    float3[] radiance:sphericalHarmonicsCoefficients = [
        (0, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11),
        (12, 13, 14), (15, 16, 17), (18, 19, 20), (21, 22, 23)
    ] (
        interpolation = "vertex"
        elementSize = 4
    )
    uniform token projectionModeHint = "tangential"
    uniform token sortingModeHint = "rayHitDistance"
    float3[] extent = [(0, 0, 0), (10, 10, 10)]
}
'''


def _rest_width(degree: int) -> int:
    return ((degree + 1) ** 2 - 1) * 3


def _cloud(
    *,
    degree: int = 1,
    precision: str = "float32",
    positions: np.ndarray | None = None,
    projection: str = "tangential",
    sorting: str = "rayHitDistance",
):
    means = (
        np.array([[1, 2, 3], [-4, 5, -6]], np.float32)
        if positions is None
        else np.asarray(positions, np.float32)
    )
    count = len(means)
    scales = np.resize(
        np.array([[1, 0.5, 2], [0.25, 4, 1]], np.float32),
        (count, 3),
    )
    quaternions = np.resize(
        np.array([[1, 0, 0, 0], [0.5, 0.5, 0.5, 0.5]], np.float32),
        (count, 4),
    )
    opacities = np.resize(np.array([0.25, 0.75], np.float32), count)
    sh_dc = np.resize(
        np.array([[-0.5, 0, 0.5], [0.25, -0.25, 0.75]], np.float32),
        (count, 3),
    )
    width = _rest_width(degree)
    sh_rest = (
        np.empty((count, 0), np.float32)
        if width == 0
        else (
            np.arange(count * width, dtype=np.float32).reshape(count, width)
            / 16
            - 1
        )
    )
    if precision == "float16":
        values = (means, scales, quaternions, opacities, sh_dc, sh_rest)
        means, scales, quaternions, opacities, sh_dc, sh_rest = (
            value.astype(np.float16).astype(np.float32) for value in values
        )
    return _core.gaussian_cloud(
        means,
        scales,
        quaternions,
        opacities,
        sh_dc,
        sh_rest,
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
        source_precision=precision,
        projection_mode_hint=projection,
        sorting_mode_hint=sorting,
    )


def _scene(cloud):
    return _core.scene_graph(
        ["Cloud"],
        node_payload_kinds=["gaussian_cloud"],
        node_payload_indices=np.array([0], np.uint64),
        gaussian_clouds=[cloud],
        up_axis="y",
        meters_per_unit=1.0,
        source_representation="usda",
        default_prim=0,
    )


def _assert_cloud_bits(actual, expected) -> None:
    for name in (
        "means",
        "scales",
        "quaternions",
        "opacities",
        "sh_dc",
        "sh_rest",
    ):
        assert (
            np.asarray(getattr(actual, name)).tobytes()
            == np.asarray(getattr(expected, name)).tobytes()
        ), name
    assert actual.sh_degree == expected.sh_degree
    assert actual.source_precision == expected.source_precision
    assert actual.projection_mode_hint == expected.projection_mode_hint
    assert actual.sorting_mode_hint == expected.sorting_mode_hint


def test_read_standards_derived_float_fixture_maps_raw_layout(tmp_path):
    path = tmp_path / "float.usda"
    path.write_text(_FLOAT_FIXTURE, encoding="utf-8")

    scene = sceneio.read_scene(path)
    cloud = scene.gaussian_cloud_at(0)

    assert scene.node_payload_kinds == ["gaussian_cloud"]
    assert scene.node_visibility == ["invisible"]
    assert scene.node_purpose == ["render"]
    np.testing.assert_array_equal(
        scene.node_local_transforms[0, :3, 3], [2, 3, 4]
    )
    assert (
        cloud.quaternion_order,
        cloud.scale_space,
        cloud.opacity_space,
        cloud.sh_layout,
        cloud.source_precision,
    ) == ("wxyz", "linear", "linear", "coefficient_rgb", "float32")
    assert cloud.projection_mode_hint == "tangential"
    assert cloud.sorting_mode_hint == "rayHitDistance"
    np.testing.assert_array_equal(cloud.means, [[1, 2, 3], [4, 5, 6]])
    np.testing.assert_array_equal(
        cloud.quaternions,
        [[0.5, 0.5, 0.5, 0.5], [0.5, -0.5, -0.5, -0.5]],
    )
    expected = np.arange(24, dtype=np.float32).reshape(2, 4, 3)
    assert np.asarray(cloud.sh_dc).tobytes() == expected[:, 0].tobytes()
    assert (
        np.asarray(cloud.sh_rest).tobytes()
        == expected[:, 1:].reshape(2, 9).tobytes()
    )


def test_gaussian_transform_stack_matches_xform_provider_result(tmp_path):
    xform = '''
    double3 xformOp:translate = (1, 2, 3)
    float3 xformOp:rotateXYZ = (10, 20, 30)
    float3 xformOp:scale = (2, 3, 4)
    uniform token[] xformOpOrder = [
        "!resetXformStack!",
        "xformOp:translate",
        "xformOp:rotateXYZ",
        "xformOp:scale"
    ]
'''
    path = tmp_path / "transform.usda"
    path.write_text(
        '''#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Xform "Reference"
{'''
        + xform
        + '''}
def ParticleField3DGaussianSplat "Cloud"
{'''
        + xform
        + '''    point3f[] positions = [(0, 0, 0)]
}
def ParticleField3DGaussianSplat "SecondCloud"
{
    matrix4d xformOp:transform = (
        (1, 0, 0, -7), (0, 1, 0, 11),
        (0, 0, 1, 13), (0, 0, 0, 1)
    )
    uniform token[] xformOpOrder = ["xformOp:transform"]
    point3f[] positions = [(1, 2, 3)]
}
''',
        encoding="utf-8",
    )

    scene = sceneio.read_scene(path)

    np.testing.assert_array_equal(
        scene.node_local_transforms[1], scene.node_local_transforms[0]
    )
    np.testing.assert_array_equal(
        scene.node_local_transforms[2, :3, 3], [-7, 11, 13]
    )
    np.testing.assert_array_equal(
        scene.node_resets_transform_stack, [1, 1, 0]
    )


def test_schema_defaults_follow_particle_field_contract(tmp_path):
    path = tmp_path / "defaults.usda"
    path.write_text(
        '''#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def ParticleField3DGaussianSplat "Cloud"
{
    point3h[] positionsh = [(1, 2, 3), (4, 5, 6)]
}
''',
        encoding="utf-8",
    )

    cloud = sceneio.read_scene(path).gaussian_cloud_at(0)

    assert cloud.source_precision == "float16"
    assert cloud.sh_degree == 0
    np.testing.assert_array_equal(cloud.scales, np.ones((2, 3), np.float32))
    np.testing.assert_array_equal(cloud.opacities, np.ones(2, np.float32))
    np.testing.assert_array_equal(
        cloud.quaternions,
        [[1, 0, 0, 0], [1, 0, 0, 0]],
    )
    np.testing.assert_array_equal(cloud.sh_dc, np.zeros((2, 3), np.float32))
    assert np.asarray(cloud.sh_rest).shape == (2, 0)
    assert cloud.projection_mode_hint == "perspective"
    assert cloud.sorting_mode_hint == "zDepth"


def test_half_precision_unit_tolerance_accepts_quantized_orientation(tmp_path):
    path = tmp_path / "half-unit.usda"
    path.write_text(
        '''#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def ParticleField3DGaussianSplat "Cloud"
{
    point3h[] positionsh = [(0, 0, 0)]
    quath[] orientationsh = [(0.70703125, 0.70703125, 0, 0)]
}
''',
        encoding="utf-8",
    )

    cloud = sceneio.read_scene(path).gaussian_cloud_at(0)

    assert cloud.source_precision == "float16"
    np.testing.assert_array_equal(
        cloud.quaternions,
        [[0.70703125, 0.70703125, 0, 0]],
    )


def test_float_attributes_win_over_authored_half_variants(tmp_path):
    path = tmp_path / "precedence.usda"
    path.write_text(
        '''#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def ParticleField3DGaussianSplat "Cloud"
{
    point3f[] positions = [(1, 2, 3)]
    point3h[] positionsh = [(9, 9, 9), (8, 8, 8)]
    quatf[] orientations = [(1, 0, 0, 0)]
    quath[] orientationsh = [(0, 1, 0, 0), (0, 0, 1, 0)]
    float3[] scales = [(1, 2, 3)]
    half3[] scalesh = [(9, 9, 9), (8, 8, 8)]
    float[] opacities = [0.25]
    half[] opacitiesh = [0.5, 0.75]
    uniform int radiance:sphericalHarmonicsDegree = 0
    float3[] radiance:sphericalHarmonicsCoefficients = [(1, 2, 3)]
    half3[] radiance:sphericalHarmonicsCoefficientsh = [(9, 9, 9), (8, 8, 8)]
}
''',
        encoding="utf-8",
    )

    cloud = sceneio.read_scene(path).gaussian_cloud_at(0)

    assert cloud.source_precision == "float32"
    np.testing.assert_array_equal(cloud.means, [[1, 2, 3]])
    np.testing.assert_array_equal(cloud.scales, [[1, 2, 3]])
    np.testing.assert_array_equal(cloud.opacities, [0.25])
    np.testing.assert_array_equal(cloud.sh_dc, [[1, 2, 3]])


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
@pytest.mark.parametrize("precision", ["float32", "float16"])
@pytest.mark.parametrize("degree", [0, 1, 2, 3])
def test_write_cross_reads_and_roundtrips_every_degree_and_precision(
    tmp_path, suffix, precision, degree
):
    expected = _cloud(degree=degree, precision=precision)
    path = tmp_path / f"cloud-{degree}-{precision}{suffix}"

    sceneio.write_scene(_scene(expected), path)

    oracle = tinyusdz.load(str(path))
    prim = oracle.root_prims()[0]
    half = precision == "float16"
    names = set(prim.property_names())
    position_name = "positionsh" if half else "positions"
    orientation_name = "orientationsh" if half else "orientations"
    coefficient_name = (
        "radiance:sphericalHarmonicsCoefficientsh"
        if half
        else "radiance:sphericalHarmonicsCoefficients"
    )
    assert {position_name, orientation_name, coefficient_name} <= names
    dtype = np.float16 if half else np.float32
    np.testing.assert_array_equal(
        np.asarray(prim.get_attribute(position_name).value),
        np.asarray(expected.means).astype(dtype),
    )
    np.testing.assert_array_equal(
        np.asarray(prim.get_attribute(orientation_name).value),
        np.asarray(expected.quaternions)[:, [1, 2, 3, 0]].astype(dtype),
    )
    coefficient_count = (degree + 1) ** 2
    coefficients = np.empty(
        (expected.num_gaussians, coefficient_count, 3), np.float32
    )
    coefficients[:, 0] = expected.sh_dc
    if coefficient_count > 1:
        coefficients[:, 1:] = np.asarray(expected.sh_rest).reshape(
            expected.num_gaussians, coefficient_count - 1, 3
        )
    np.testing.assert_array_equal(
        np.asarray(prim.get_attribute(coefficient_name).value),
        coefficients.reshape(-1, 3).astype(dtype),
    )
    assert (
        prim.get_attribute_metadata(coefficient_name, "interpolation")
        == "vertex"
    )
    assert f"elementSize = {coefficient_count}" in prim.to_string()
    assert (
        prim.get_attribute("projectionModeHint").value.as_scalar()
        == "tangential"
    )
    assert (
        prim.get_attribute("sortingModeHint").value.as_scalar()
        == "rayHitDistance"
    )
    _assert_cloud_bits(sceneio.read_scene(path).gaussian_cloud_at(0), expected)


def test_writer_extent_tracks_rotated_three_sigma_support(tmp_path):
    position = np.array([[1, 2, 3]], np.float32)
    cloud = _core.gaussian_cloud(
        position,
        np.array([[1, 2, 3]], np.float32),
        np.array([[np.sqrt(0.5), 0, 0, np.sqrt(0.5)]], np.float32),
        np.array([1], np.float32),
        np.zeros((1, 3), np.float32),
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
    )
    path = tmp_path / "extent.usda"

    sceneio.write_scene(_scene(cloud), path)

    prim = tinyusdz.load(str(path)).root_prims()[0]
    extent = np.asarray(prim.get_attribute("extent").value)
    expected_radius = np.array([6, 3, 9], np.float32)
    assert np.all(extent[0] <= position[0] - expected_radius)
    assert np.all(extent[1] >= position[0] + expected_radius)
    np.testing.assert_allclose(
        extent,
        np.stack((position[0] - expected_radius, position[0] + expected_radius)),
        atol=2e-6,
        rtol=0,
    )


def test_chunked_extent_matches_vectorized_reference_across_boundary():
    count = gaussians._EXTENT_CHUNK_ROWS + 1
    rng = np.random.default_rng(427)
    positions = rng.normal(size=(count, 3)).astype(np.float32)
    scales = rng.uniform(0.01, 3.0, size=(count, 3)).astype(np.float32)
    quaternions = rng.normal(size=(count, 4)).astype(np.float32)

    actual = gaussians._gaussian_extent(positions, scales, quaternions)

    q = quaternions.astype(np.float64)
    q /= np.linalg.norm(q, axis=1)[:, None]
    w, x, y, z = q.T
    rotation = np.empty((count, 3, 3), np.float64)
    rotation[:, 0, 0] = 1 - 2 * (y * y + z * z)
    rotation[:, 0, 1] = 2 * (x * y - z * w)
    rotation[:, 0, 2] = 2 * (x * z + y * w)
    rotation[:, 1, 0] = 2 * (x * y + z * w)
    rotation[:, 1, 1] = 1 - 2 * (x * x + z * z)
    rotation[:, 1, 2] = 2 * (y * z - x * w)
    rotation[:, 2, 0] = 2 * (x * z - y * w)
    rotation[:, 2, 1] = 2 * (y * z + x * w)
    rotation[:, 2, 2] = 1 - 2 * (x * x + y * y)
    radii = 3 * np.sqrt(
        np.sum(
            (rotation * scales.astype(np.float64)[:, None, :]) ** 2,
            axis=2,
        )
    )
    expected = np.stack(
        (
            np.min(positions.astype(np.float64) - radii, axis=0),
            np.max(positions.astype(np.float64) + radii, axis=0),
        )
    ).astype(np.float32)
    expected[0] = np.nextafter(expected[0], -np.inf, dtype=np.float32)
    expected[1] = np.nextafter(expected[1], np.inf, dtype=np.float32)

    np.testing.assert_array_equal(actual, expected)


def test_float16_validation_does_not_join_sh_arrays(monkeypatch):
    cloud = _cloud(degree=3, precision="float16")

    monkeypatch.setattr(
        gaussians.np,
        "concatenate",
        lambda *args, **kwargs: pytest.fail("SH arrays must remain separate"),
    )

    arrays = gaussians.validate_writable_gaussian(cloud, context="test")

    assert arrays[4].shape == (2, 3)
    assert arrays[5].shape == (2, 45)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    half3[] scalesh = [(1,1,1)]",
            "precision",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    quatf[] orientations = []",
            "orientation count",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    float3[] scales = [(0,1,1)]",
            "scales must be positive",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    float[] opacities = [1.5]",
            r"opacities must be in \[0, 1\]",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    quatf[] orientations = [(0,0,0,0)]",
            "orientations must be unit quaternions",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    quatf[] orientations = [(2,0,0,0)]",
            "orientations must be unit quaternions",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    uniform int radiance:sphericalHarmonicsDegree = 4\n"
            "    float3[] radiance:sphericalHarmonicsCoefficients = [(0,0,0)]",
            r"degree must be in \[0, 3\]",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    uniform int radiance:sphericalHarmonicsDegree = 1\n"
            "    float3[] radiance:sphericalHarmonicsCoefficients = [(0,0,0)]",
            "coefficient count must be 4",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            '    uniform token projectionModeHint = "fisheye"',
            "projectionModeHint",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            '    uniform token sortingModeHint = "none"',
            "sortingModeHint",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    float3[] velocities = [(1,2,3)]",
            "velocities",
        ),
        (
            "point3f[] positions = [(0,0,0)]\n"
            "    float3[] extent = [(1,1,1),(2,2,2)]",
            "extent does not enclose positions",
        ),
    ],
)
def test_invalid_gaussian_inputs_refuse_exactly(tmp_path, body, message):
    path = tmp_path / "invalid.usda"
    path.write_text(
        "#usda 1.0\n(\n    upAxis = \"Y\"\n"
        "    metersPerUnit = 1\n)\n"
        'def ParticleField3DGaussianSplat "Cloud"\n{\n    '
        + body
        + "\n}\n",
        encoding="utf-8",
    )

    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read_scene(path)


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ("elementSize = 9", "elementSize must be 4"),
        ('interpolation = "constant"', "interpolation must be vertex"),
    ],
)
def test_coefficient_metadata_must_match_schema_layout(
    tmp_path, metadata, message
):
    path = tmp_path / "metadata.usda"
    path.write_text(
        '''#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def ParticleField3DGaussianSplat "Cloud"
{
    point3f[] positions = [(0,0,0)]
    uniform int radiance:sphericalHarmonicsDegree = 1
    float3[] radiance:sphericalHarmonicsCoefficients = [
        (0,0,0), (0,0,0), (0,0,0), (0,0,0)
    ] (
        '''
        + metadata
        + '''
    )
}
''',
        encoding="utf-8",
    )

    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read_scene(path)


def test_prim_selection_skips_unselected_gaussian_payload(tmp_path, monkeypatch):
    path = tmp_path / "selection.usda"
    path.write_text(
        _FLOAT_FIXTURE + '\ndef Xform "Keep"\n{\n}\n',
        encoding="utf-8",
    )

    def fail(*args, **kwargs):
        raise AssertionError("unselected Gaussian payload was constructed")

    monkeypatch.setattr(gaussians, "gaussian_cloud_from_prim", fail)
    selected = sceneio.read_scene(path, prims="/Keep")

    assert selected.node_names == ["Keep"]
    assert selected.num_gaussian_clouds == 0


def test_inspection_validates_without_constructing_record(tmp_path, monkeypatch):
    path = tmp_path / "inspect.usda"
    path.write_text(_FLOAT_FIXTURE, encoding="utf-8")

    monkeypatch.setattr(
        gaussians,
        "gaussian_cloud_from_prim",
        lambda *args, **kwargs: pytest.fail("record construction is forbidden"),
    )
    info = sceneio.inspect(path)

    assert info.datatype == "scene_graph"
    assert info.shape == (2, 3)
    assert info.count == 1
    assert info.metadata["num_gaussian_clouds"] == 1
    assert info.metadata["unsupported_features"] == ()


def test_returned_views_outlive_stage_scene_and_source(tmp_path):
    path = tmp_path / "lifetime.usda"
    path.write_text(_FLOAT_FIXTURE, encoding="utf-8")
    scene = sceneio.read_scene(path)
    cloud = scene.gaussian_cloud_at(0)
    values = cloud.sh_rest
    expected = np.array(values, copy=True)

    del cloud, scene
    path.unlink()
    gc.collect()

    np.testing.assert_array_equal(values, expected)


def test_float16_write_refuses_loss_and_preserves_destination(tmp_path):
    cloud = _cloud(
        degree=0,
        precision="float32",
        positions=np.array([[0.1, 0, 0]], np.float32),
    )
    cloud = _core.gaussian_cloud(
        cloud.means,
        cloud.scales,
        cloud.quaternions,
        cloud.opacities,
        cloud.sh_dc,
        cloud.sh_rest,
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
        source_precision="float16",
        projection_mode_hint=cloud.projection_mode_hint,
        sorting_mode_hint=cloud.sorting_mode_hint,
    )
    destination = tmp_path / "existing.usda"
    destination.write_bytes(b"old destination")

    with pytest.raises(
        sceneio.FormatError, match="exactly representable as float16"
    ):
        sceneio.write_scene(_scene(cloud), destination)

    assert destination.read_bytes() == b"old destination"


def test_write_refuses_nonunit_gaussian_orientation(tmp_path):
    source = _cloud(degree=0)
    cloud = _core.gaussian_cloud(
        source.means,
        source.scales,
        np.array([[2, 0, 0, 0], [1, 0, 0, 0]], np.float32),
        source.opacities,
        source.sh_dc,
        source.sh_rest,
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
        projection_mode_hint=source.projection_mode_hint,
        sorting_mode_hint=source.sorting_mode_hint,
    )

    with pytest.raises(sceneio.FormatError, match="unit quaternions"):
        sceneio.write_scene(_scene(cloud), tmp_path / "nonunit.usda")


def test_write_requires_explicit_usd_convention_conversion(tmp_path):
    raw = _core.gaussian_cloud(
        np.zeros((1, 3), np.float32),
        np.zeros((1, 3), np.float32),
        np.array([[1, 0, 0, 0]], np.float32),
        np.zeros(1, np.float32),
        np.zeros((1, 3), np.float32),
    )

    with pytest.raises(sceneio.FormatError, match="convert explicitly"):
        sceneio.write_scene(_scene(raw), tmp_path / "raw.usda")


def test_generic_read_preserves_gaussian_payload(tmp_path):
    path = tmp_path / "rich.usda"
    path.write_text(_FLOAT_FIXTURE, encoding="utf-8")

    scene = sceneio.read(path)
    assert isinstance(scene, sceneio.SceneGraph)
    assert scene.num_gaussian_clouds == 1


def test_empty_particle_field_roundtrips(tmp_path):
    cloud = _cloud(degree=3, positions=np.empty((0, 3), np.float32))
    path = tmp_path / "empty.usda"

    sceneio.write_scene(_scene(cloud), path)
    actual = sceneio.read_scene(path).gaussian_cloud_at(0)

    assert actual.num_gaussians == 0
    assert actual.sh_degree == 3
    assert np.asarray(actual.sh_rest).shape == (0, 45)
    assert "extent" not in tinyusdz.load(str(path)).root_prims()[0].property_names()
