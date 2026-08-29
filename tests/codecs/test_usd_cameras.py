"""OpenUSD 26.08 camera/render-product mapping and refusal contract."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io._usd import stage as usd_stage

tinyusdz = pytest.importorskip("tinyusdz")


_CAMERA_STAGE = '''#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 0.01
    upAxis = "Z"
)
def Xform "World"
{
    def Camera "Perspective"
    {
        matrix4d xformOp:transform = (
            (0, 0, 1, 1),
            (0, 1, 0, 2),
            (-1, 0, 0, 3),
            (0, 0, 0, 1)
        )
        uniform token[] xformOpOrder = ["xformOp:transform"]
        token projection = "perspective"
        float horizontalAperture = 36
        float verticalAperture = 24
        float horizontalApertureOffset = 1.8
        float verticalApertureOffset = -1.2
        float focalLength = 50
    }

    def Camera "Orthographic"
    {
        token projection = "orthographic"
        float horizontalAperture = 20
        float verticalAperture = 10
        float horizontalApertureOffset = 2
        float verticalApertureOffset = 1
    }
}
def RenderProduct "PerspectiveProduct"
{
    rel camera = </World/Perspective>
    uniform int2 resolution = (1000, 500)
    uniform float pixelAspectRatio = 1.2
    uniform token aspectRatioConformPolicy = "adjustApertureHeight"
}
def RenderProduct "OrthographicProduct"
{
    rel camera = </World/Orthographic>
    uniform int2 resolution = (800, 600)
    uniform token aspectRatioConformPolicy = "adjustPixelAspectRatio"
}
'''


def _write(path: Path, text: str = _CAMERA_STAGE) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _assert_projection(rig) -> None:
    assert rig.num_cameras == 2
    assert rig.camera_ids.tolist() == [0, 1]
    assert rig.names == ["/World/Perspective", "/World/Orthographic"]
    assert rig.projection_models == ["pinhole", "orthographic"]
    assert rig.distortion_models == ["none", "none"]
    np.testing.assert_array_equal(rig.resolutions, [[1000, 500], [800, 600]])
    target_aspect = 1000 * float(np.float32(1.2)) / 500
    conformed_vertical = 36 / target_aspect
    horizontal_offset = float(np.float32(1.8))
    vertical_offset = float(np.float32(-1.2))
    np.testing.assert_allclose(
        rig.intrinsics[:4],
        [
            50 * 1000 / 36,
            50 * 500 / conformed_vertical,
            1000 * (0.5 - horizontal_offset / 36),
            500 * (0.5 + vertical_offset / conformed_vertical),
        ],
        rtol=0,
        atol=1e-11,
    )
    np.testing.assert_allclose(
        rig.intrinsics[4:], [400, 600, 320, 360], rtol=0, atol=1e-11
    )
    assert rig.intrinsic_offsets.tolist() == [0, 4, 8]
    assert rig.distortion_offsets.tolist() == [0, 0, 0]
    assert rig.distortion_coefficients.shape == (0,)
    for index in range(2):
        fx, fy, cx, cy = rig.intrinsics[index * 4 : index * 4 + 4]
        np.testing.assert_array_equal(
            rig.camera_matrices[index],
            [[fx, 0, cx], [0, fy, cy], [0, 0, 1]],
        )
    assert rig.has_camera_matrix.tolist() == [1, 1]
    assert rig.has_extrinsics.tolist() == [1, 1]
    assert rig.quaternion_order == "wxyz"
    assert rig.quaternion_sign == "canonical_positive_w"
    assert rig.transform_convention == "camera_to_reference"
    assert rig.axis_frame == "opengl"
    assert rig.reference_frame == "unknown"
    assert rig.scale_to_meters == 0.01
    np.testing.assert_allclose(
        rig.quaternions[0], [np.sqrt(0.5), 0, np.sqrt(0.5), 0], atol=1e-15
    )
    np.testing.assert_array_equal(rig.translations[0], [1, 2, 3])
    np.testing.assert_array_equal(rig.quaternions[1], [1, 0, 0, 0])
    np.testing.assert_array_equal(rig.translations[1], [0, 0, 0])


def test_literal_camera_stage_maps_projection_pose_and_resources(tmp_path):
    path = _write(tmp_path / "cameras.usda")

    scene = sceneio.read_scene(path)

    assert scene.node_names == ["World", "Perspective", "Orthographic"]
    assert scene.node_payload_kinds == ["none", "camera", "camera"]
    np.testing.assert_array_equal(
        scene.node_payload_indices,
        [np.iinfo(np.uint64).max, 0, 1],
    )
    assert scene.num_cameras == 2
    assert scene.has_cameras
    _assert_projection(scene.cameras)


def test_inspection_reports_camera_profile_without_records(tmp_path):
    path = _write(tmp_path / "cameras.usda")

    info = sceneio.inspect(path)

    assert info.datatype == "scene_graph"
    assert info.metadata["num_cameras"] == 2
    assert info.metadata["num_render_products"] == 2
    assert info.metadata["camera_resolutions"] == (
        "/World/Perspective=1000x500:pinhole",
        "/World/Orthographic=800x600:orthographic",
    )
    assert info.metadata["unsupported_features"] == ()


def test_selected_camera_omits_unrelated_payload_and_products(tmp_path):
    path = _write(tmp_path / "cameras.usda")

    scene = sceneio.read_scene(path, prims="/World/Perspective")

    assert scene.node_names == ["World", "Perspective"]
    assert scene.node_payload_kinds == ["none", "camera"]
    assert scene.num_cameras == 1
    assert scene.cameras.names == ["/World/Perspective"]
    np.testing.assert_array_equal(scene.cameras.resolutions, [[1000, 500]])


def test_selected_camera_does_not_enter_unrelated_geometry_adapter(
    tmp_path, monkeypatch
):
    path = _write(
        tmp_path / "selected.usda",
        _CAMERA_STAGE
        + '''def Mesh "Unrelated"
{
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0, 1, 2]
    point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
}
''',
    )

    def fail(*args, **kwargs):
        raise AssertionError("unrelated geometry adapter was entered")

    monkeypatch.setattr(usd_stage.geometry, "mesh_from_prim", fail)

    scene = sceneio.read_scene(path, prims="/World/Perspective")

    assert scene.node_names == ["World", "Perspective"]
    assert scene.num_cameras == 1


def test_load_payloads_false_builds_only_camera_shells(tmp_path):
    path = _write(tmp_path / "cameras.usda")

    scene = sceneio.read_scene(path, load_payloads=False)

    assert scene.node_names == ["World", "Perspective", "Orthographic"]
    assert scene.node_payload_kinds == ["none", "none", "none"]
    assert not scene.has_cameras
    assert scene.num_cameras == 0


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
def test_camera_scene_writes_cross_reads_and_roundtrips(tmp_path, suffix):
    source = sceneio.read_scene(_write(tmp_path / "source.usda"))
    destination = tmp_path / f"written{suffix}"

    sceneio.write_scene(source, destination)

    stage = tinyusdz.load(str(destination))
    prims = {}

    def visit(prim, parent=""):
        path = f"{parent}/{prim.name}"
        prims[path] = prim
        for child in prim.children():
            visit(child, path)

    for root in stage.root_prims():
        visit(root)
    assert prims["/World/Perspective"].type_name == "Camera"
    assert 'token projection = "perspective"' in prims[
        "/World/Perspective"
    ].to_string()
    products = [
        prim for prim in prims.values() if prim.type_name == "RenderProduct"
    ]
    assert len(products) == 2
    assert {
        item.get_attribute("resolution").value.as_scalar() for item in products
    } == {"(1000, 500)", "(800, 600)"}
    actual = sceneio.read_scene(destination)
    assert actual.node_names == source.node_names
    assert actual.node_payload_kinds == source.node_payload_kinds
    np.testing.assert_allclose(
        actual.node_local_transforms,
        source.node_local_transforms,
        rtol=0,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        actual.cameras.intrinsics,
        source.cameras.intrinsics,
        rtol=2e-7,
        atol=2e-7,
    )
    np.testing.assert_allclose(
        actual.cameras.quaternions,
        source.cameras.quaternions,
        rtol=0,
        atol=1e-15,
    )


def test_camera_arrays_outlive_source_and_provider(tmp_path):
    path = _write(tmp_path / "cameras.usda")
    scene = sceneio.read_scene(path)
    intrinsics = scene.cameras.intrinsics
    quaternions = scene.cameras.quaternions
    expected_intrinsics = intrinsics.copy()
    expected_quaternions = quaternions.copy()

    del scene
    path.unlink()
    gc.collect()

    np.testing.assert_array_equal(intrinsics, expected_intrinsics)
    np.testing.assert_array_equal(quaternions, expected_quaternions)


def _single_camera_stage(camera_fields: str = "", product_fields: str = "") -> str:
    resolution = (
        ""
        if "resolution =" in product_fields
        else "    uniform int2 resolution = (640, 480)\n"
    )
    return f'''#usda 1.0
def Camera "Camera"
{{
{camera_fields}
}}
def RenderProduct "Product"
{{
    rel camera = </Camera>
{resolution}
{product_fields}
}}
'''


@pytest.mark.parametrize(
    ("camera_fields", "match"),
    [
        ("    float2 clippingRange = (0.1, 1000)", "clippingRange"),
        ("    float4[] clippingPlanes = [(0, 0, 1, 0)]", "clippingPlanes"),
        ("    float fStop = 2.8", "fStop"),
        ("    float focusDistance = 10", "focusDistance"),
        ('    uniform token stereoRole = "left"', "stereoRole"),
        ("    double shutter:close = 0.5", "shutter:close"),
        ("    float exposure = 1", "exposure"),
        ("    float exposure:iso = 200", "exposure:iso"),
        ("    float exposure:time = 0.5", "exposure:time"),
        ("    float exposure:fStop = 2", "exposure:fStop"),
        ("    float exposure:responsivity = 2", "exposure:responsivity"),
    ],
)
def test_unrepresented_camera_fields_are_refused(
    tmp_path, camera_fields, match
):
    path = _write(
        tmp_path / "unsupported.usda",
        _single_camera_stage(camera_fields=camera_fields),
    )

    with pytest.raises(sceneio.FormatError, match=match):
        sceneio.read_scene(path)


@pytest.mark.parametrize(
    ("product_fields", "match"),
    [
        ("    uniform int2 resolution = (0, 480)", "positive"),
        ("    uniform float pixelAspectRatio = 0", "pixelAspectRatio"),
        (
            '    uniform token aspectRatioConformPolicy = "unknown"',
            "aspectRatioConformPolicy",
        ),
        ("    uniform float4 dataWindowNDC = (0, 0, 0.5, 1)", "dataWindowNDC"),
        ("    uniform bool disableDepthOfField = true", "disableDepthOfField"),
        ("    uniform bool disableMotionBlur = true", "disableMotionBlur"),
        ("    uniform bool instantaneousShutter = true", "instantaneousShutter"),
        ('    uniform token productType = "deepRaster"', "productType"),
        ('    token productName = "image.exr"', "productName"),
    ],
)
def test_unrepresented_render_product_fields_are_refused(
    tmp_path, product_fields, match
):
    path = _write(
        tmp_path / "unsupported.usda",
        _single_camera_stage(product_fields=product_fields),
    )

    with pytest.raises(sceneio.FormatError, match=match):
        sceneio.read_scene(path)


def test_missing_and_ambiguous_render_products_are_refused(tmp_path):
    missing = _write(
        tmp_path / "missing.usda",
        '#usda 1.0\ndef Camera "Camera" {}\n',
    )
    with pytest.raises(sceneio.FormatError, match="exactly one associated"):
        sceneio.read_scene(missing)

    ambiguous = _write(
        tmp_path / "ambiguous.usda",
        _single_camera_stage()
        + '''def RenderProduct "Other"
{
    rel camera = </Camera>
    uniform int2 resolution = (800, 600)
}
''',
    )
    with pytest.raises(sceneio.FormatError, match="multiple RenderProducts"):
        sceneio.read_scene(ambiguous)


def test_nonrigid_camera_transform_is_refused(tmp_path):
    path = _write(
        tmp_path / "scaled.usda",
        _single_camera_stage(
            camera_fields='''    float3 xformOp:scale = (2, 1, 1)
    uniform token[] xformOpOrder = ["xformOp:scale"]'''
        ),
    )

    with pytest.raises(sceneio.FormatError, match="proper rigid rotation"):
        sceneio.read_scene(path)


def test_writer_pose_guard_preserves_existing_destination(tmp_path):
    scene = sceneio.read_scene(_write(tmp_path / "source.usda"))
    scene.cameras.translations[0, 0] += 1
    destination = tmp_path / "keep.usda"
    destination.write_bytes(b"keep")

    with pytest.raises(sceneio.FormatError, match="pose must match"):
        sceneio.write_scene(scene, destination)

    assert destination.read_bytes() == b"keep"


def test_wrong_attribute_types_and_time_samples_are_refused(tmp_path):
    wrong_type = _write(
        tmp_path / "wrong.usda",
        _single_camera_stage(camera_fields="    double focalLength = 50"),
    )
    with pytest.raises(sceneio.FormatError, match="expects type `float`"):
        sceneio.read_scene(wrong_type)

    sampled = _write(
        tmp_path / "sampled.usda",
        _single_camera_stage(
            camera_fields="    float focalLength.timeSamples = { 1: 50, 2: 60 }"
        ),
    )
    with pytest.raises(sceneio.FormatError, match="selected-time"):
        sceneio.read_scene(sampled)


def test_render_product_schema_fallbacks_are_usable(tmp_path):
    path = _write(
        tmp_path / "fallback.usda",
        '''#usda 1.0
def Camera "Camera" {}
def RenderProduct "Product"
{
    rel camera = </Camera>
}
''',
    )

    scene = sceneio.read_scene(path)

    np.testing.assert_array_equal(scene.cameras.resolutions, [[2048, 1080]])
    assert scene.cameras.projection_models == ["pinhole"]


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("expandAperture", (250.0, 250.0)),
        ("cropAperture", (500.0, 500.0)),
        ("adjustApertureWidth", (500.0, 500.0)),
        ("adjustApertureHeight", (250.0, 250.0)),
        ("adjustPixelAspectRatio", (250.0, 500.0)),
    ],
)
def test_all_standard_aspect_conform_policies_are_projection_equivalent(
    tmp_path, policy, expected
):
    path = _write(
        tmp_path / f"{policy}.usda",
        _single_camera_stage(
            camera_fields="""    float horizontalAperture = 20
    float verticalAperture = 10""",
            product_fields=(
                "    uniform int2 resolution = (100, 100)\n"
                f'    uniform token aspectRatioConformPolicy = "{policy}"'
            ),
        ),
    )

    rig = sceneio.read_scene(path).cameras

    np.testing.assert_allclose(rig.intrinsics[:2], expected, rtol=0, atol=0)
    np.testing.assert_array_equal(rig.intrinsics[2:], [50, 50])


def test_pose_direction_and_opengl_to_opencv_axes_are_explicit(tmp_path):
    rig = sceneio.read_scene(_write(tmp_path / "pose.usda")).cameras
    w, x, y, z = rig.quaternions[0]
    camera_to_parent = np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    center = np.asarray(rig.translations[0])
    gl_to_cv = np.diag([1.0, -1.0, -1.0])
    parent_to_opencv = gl_to_cv @ camera_to_parent.T
    translation = -parent_to_opencv @ center
    point_two_units_forward = center + camera_to_parent @ [0.0, 0.0, -2.0]

    np.testing.assert_allclose(
        camera_to_parent,
        [[0, 0, 1], [0, 1, 0], [-1, 0, 0]],
        rtol=0,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        parent_to_opencv @ point_two_units_forward + translation,
        [0, 0, 2],
        rtol=0,
        atol=1e-15,
    )


@pytest.mark.parametrize(
    ("extra", "match"),
    [
        ("    rel orderedVars = </Camera>", "orderedVars"),
        ("    custom string extra = \"value\"", "unsupported properties"),
    ],
)
def test_render_product_relationship_and_extension_fields_are_refused(
    tmp_path, extra, match
):
    path = _write(
        tmp_path / "product.usda",
        _single_camera_stage(product_fields=extra),
    )

    with pytest.raises(sceneio.FormatError, match=match):
        sceneio.read_scene(path)


def test_unknown_camera_property_is_refused(tmp_path):
    path = _write(
        tmp_path / "camera.usda",
        _single_camera_stage(camera_fields="    custom float distortion = 0.1"),
    )

    with pytest.raises(sceneio.FormatError, match="unsupported properties"):
        sceneio.read_scene(path)


def test_camera_rig_record_is_owned_and_mutation_isolated(tmp_path):
    scene = sceneio.read_scene(_write(tmp_path / "source.usda"))
    before = np.array(scene.cameras.intrinsics, copy=True)
    source = np.asarray(scene.cameras.intrinsics)

    rebuilt = _core.camera_rig(
        np.asarray(scene.cameras.camera_ids),
        np.asarray(scene.cameras.resolutions),
        scene.cameras.projection_models,
        np.asarray(scene.cameras.intrinsic_offsets),
        source,
        scene.cameras.distortion_models,
        np.asarray(scene.cameras.distortion_offsets),
        np.asarray(scene.cameras.distortion_coefficients),
        np.asarray(scene.cameras.quaternions),
        np.asarray(scene.cameras.translations),
        has_extrinsics=np.asarray(scene.cameras.has_extrinsics),
        names=scene.cameras.names,
        camera_matrices=np.asarray(scene.cameras.camera_matrices),
        has_camera_matrix=np.asarray(scene.cameras.has_camera_matrix),
        quaternion_sign="canonical_positive_w",
        transform_convention="camera_to_reference",
        axis_frame="opengl",
        scale_to_meters=0.01,
    )
    source[0] += 1

    np.testing.assert_array_equal(rebuilt.intrinsics, before)
