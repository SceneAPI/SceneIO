"""Bounded USD PreviewSurface, binding, and texture-asset qualification."""

from __future__ import annotations

import gc
import io
import os
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
import tinyusdz

import sceneio
from sceneio import _core
from sceneio.io._usd import materials as usd_materials
from sceneio.io._usd import package, stage
from tests._support.memory_measurement import stable_traced_peak

PIL = pytest.importorskip("PIL.Image")


def _oracle_prim_index(oracle_stage) -> dict[str, object]:
    result: dict[str, object] = {}

    def collect(prim, parent: str) -> None:
        path = f"{parent}/{prim.name}"
        result[path] = prim
        for child in prim.children():
            collect(child, path)

    for root in oracle_stage.root_prims():
        collect(root, "")
    return result


def _oracle_scalar(prim, name: str):
    attribute = prim.get_attribute(name)
    assert attribute is not None
    return attribute.value.as_scalar()


def _triangle_mesh(
    assignments: list[int] | None = None,
):
    count = 1 if assignments is None else len(assignments)
    positions = np.empty((count * 3, 3), np.float32)
    for face in range(count):
        positions[face * 3 : face * 3 + 3] = (
            (face, 0, 0),
            (face + 0.75, 0, 0),
            (face, 0.75, 0),
        )
    kwargs = {}
    if assignments is not None:
        kwargs = {
            "primitive_offsets": np.arange(count + 1, dtype=np.uint64),
            "primitive_materials": np.asarray(assignments, np.int32),
        }
    return _core.mesh(
        positions,
        np.arange(0, count * 3 + 1, 3, dtype=np.uint64),
        np.arange(count * 3, dtype=np.uint64),
        coordinate_frame="opengl",
        scale_to_meters=1.0,
        **kwargs,
    )


def _material_scene(
    material_set,
    *,
    assignments: list[int] | None = None,
    assets: tuple[tuple[str, str], ...] = (),
):
    return _core.scene_graph(
        ["Surface"],
        node_child_offsets=np.array([0, 0], np.uint64),
        node_children=np.array([], np.uint64),
        node_payload_kinds=["mesh"],
        node_payload_indices=np.array([0], np.uint64),
        meshes=[_triangle_mesh(assignments)],
        materials=material_set,
        external_asset_uris=[uri for uri, _ in assets],
        external_asset_kinds=["texture"] * len(assets),
        external_asset_sources=[source for _, source in assets],
        up_axis="y",
        meters_per_unit=1.0,
        source_representation="usda",
    )


def _textured_material(path: str = "albedo.png"):
    return _core.material_set(
        ["Mat"],
        texture_materials=np.array([0], np.uint64),
        texture_semantics=["base_color"],
        texture_paths=[path],
    )


def _write_png(path: Path, *, size: tuple[int, int] = (2, 2)) -> None:
    PIL.fromarray(np.full((*size, 3), 127, np.uint8)).save(path)


def _mesh_usda(
    *,
    mesh_name: str = "Surface",
    binding: str = "/Materials/Mat",
    body: str = "",
) -> str:
    return f'''    def Mesh "{mesh_name}" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {{
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        uniform token subdivisionScheme = "none"
        rel material:binding = <{binding}>
{body}    }}
'''


def _constant_material(
    *,
    name: str = "Mat",
    preview_inputs: str = "",
    descendants: str = "",
) -> str:
    return f'''    def Material "{name}"
    {{
        token outputs:surface.connect = </Materials/{name}/Preview.outputs:surface>
        def Shader "Preview"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor = (0.2, 0.3, 0.4)
            color3f inputs:emissiveColor = (0.1, 0, 0)
            float inputs:metallic = 0.25
            float inputs:roughness = 0.75
            float inputs:opacity = 0.8
            float inputs:opacityThreshold = 0
{preview_inputs}            token outputs:surface
        }}
{descendants}    }}
'''


def _stage(*, meshes: str, materials: str) -> str:
    return f'''#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Xform "World"
{{
{meshes}}}
def Scope "Materials"
{{
{materials}}}
'''


def _assert_constant_material(scene) -> None:
    assert scene.materials.names == ["Mat"]
    np.testing.assert_array_equal(
        scene.materials.base_colors,
        np.array([[0.2, 0.3, 0.4, 0.8]], np.float32),
    )
    np.testing.assert_array_equal(
        scene.materials.emissive_colors,
        np.array([[0.1, 0, 0]], np.float32),
    )
    np.testing.assert_array_equal(scene.materials.metallic, [0.25])
    np.testing.assert_array_equal(scene.materials.roughness, [0.75])
    assert scene.materials.alpha_modes == ["blend"]
    np.testing.assert_array_equal(
        scene.mesh_at(0).primitive_materials,
        [0],
    )


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
def test_constant_material_ground_truth_cross_read_and_lifetime(
    tmp_path,
    suffix,
):
    source = tmp_path / "source.usda"
    source.write_text(
        _stage(
            meshes=_mesh_usda(),
            materials=_constant_material(),
        ),
        encoding="utf-8",
    )

    scene = sceneio.read_scene(source)
    _assert_constant_material(scene)
    factors = scene.materials.base_colors
    source.unlink()
    gc.collect()
    np.testing.assert_array_equal(
        factors[0],
        np.array([0.2, 0.3, 0.4, 0.8], np.float32),
    )

    output = tmp_path / f"roundtrip{suffix}"
    sceneio.write_scene(scene, output)
    oracle = tinyusdz.load(str(output))
    prims = _oracle_prim_index(oracle)
    assert prims["/World/Surface"].get_relationship_targets(
        "material:binding"
    ) == ["/SceneIOMaterials/Mat"]
    material = prims["/SceneIOMaterials/Mat"]
    assert material.get_attribute_connections("outputs:surface") == [
        "/SceneIOMaterials/Mat/PreviewSurface.outputs:surface"
    ]
    preview = prims["/SceneIOMaterials/Mat/PreviewSurface"]
    assert _oracle_scalar(preview, "info:id") == "UsdPreviewSurface"
    assert _oracle_scalar(preview, "inputs:diffuseColor") == "(0.2, 0.3, 0.4)"
    assert _oracle_scalar(preview, "inputs:emissiveColor") == "(0.1, 0, 0)"
    assert _oracle_scalar(preview, "inputs:metallic") == pytest.approx(0.25)
    assert _oracle_scalar(preview, "inputs:roughness") == pytest.approx(0.75)
    assert _oracle_scalar(preview, "inputs:opacity") == pytest.approx(0.8)
    assert _oracle_scalar(preview, "inputs:opacityThreshold") == 0.0
    _assert_constant_material(sceneio.read_scene(output))


@pytest.mark.parametrize(
    ("preview_inputs", "descendants", "message"),
    [
        ("            normal3f inputs:normal = (1, 0, 0)\n", "", "constant normal"),
        (
            "",
            '''        def Shader "Unused"
        {
            uniform token info:id = "Procedural"
            token outputs:result
        }
''',
            "unconsumed shading prims",
        ),
        (
            "",
            '''        def NodeGraph "Graph"
        {
        }
''',
            "NodeGraph",
        ),
        (
            "            color3f inputs:diffuseColor.connect = "
            "</Materials/Mat/Tex.outputs:rgb>\n",
            '''        def Shader "Primvar"
        {
            uniform token info:id = "UsdPrimvarReader_float2"
            string inputs:varname = "st"
            float2 outputs:result
        }
        def Shader "Tex"
        {
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @missing.png@
            float2 inputs:st.connect = </Materials/Mat/Primvar.outputs:result>
            token inputs:wrapS = "repeat"
            token inputs:wrapT = "repeat"
            token inputs:sourceColorSpace = "sRGB"
            float3 outputs:rgb
        }
''',
            "fallback value",
        ),
    ],
)
def test_material_reader_refuses_unrepresentable_shading(
    tmp_path,
    preview_inputs,
    descendants,
    message,
):
    path = tmp_path / "bad.usda"
    path.write_text(
        _stage(
            meshes=_mesh_usda(),
            materials=_constant_material(
                preview_inputs=preview_inputs,
                descendants=descendants,
            ),
        ),
        encoding="utf-8",
    )
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read_scene(path)


def test_selection_and_metadata_only_read_do_not_resolve_unreachable_texture(
    tmp_path,
    monkeypatch,
):
    materials = _constant_material(name="Good") + '''    def Material "Bad"
    {
        token outputs:surface.connect = </Materials/Bad/Preview.outputs:surface>
        def Shader "Preview"
        {
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect = </Materials/Bad/Tex.outputs:rgb>
            token outputs:surface
        }
        def Shader "Primvar"
        {
            uniform token info:id = "UsdPrimvarReader_float2"
            string inputs:varname = "st"
            float2 outputs:result
        }
        def Shader "Tex"
        {
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @missing.png@
            float2 inputs:st.connect = </Materials/Bad/Primvar.outputs:result>
            token inputs:wrapS = "repeat"
            token inputs:wrapT = "repeat"
            token inputs:sourceColorSpace = "sRGB"
            float3 outputs:rgb
        }
    }
'''
    meshes = _mesh_usda(mesh_name="GoodMesh", binding="/Materials/Good")
    meshes += _mesh_usda(mesh_name="BadMesh", binding="/Materials/Bad")
    path = tmp_path / "selection.usda"
    path.write_text(_stage(meshes=meshes, materials=materials), encoding="utf-8")

    def fail_asset_resolution(*_args, **_kwargs):
        raise AssertionError("metadata-only path resolved an asset")

    with monkeypatch.context() as guarded:
        guarded.setattr(package, "asset_source_for", fail_asset_resolution)
        selected = sceneio.read_scene(path, prims="/World/GoodMesh")
        assert selected.materials.names == ["Good"]
        assert selected.external_asset_uris == []

        metadata_only = sceneio.read_scene(path, load_payloads=False)
        assert not metadata_only.has_materials
        assert metadata_only.external_asset_uris == []
        report = sceneio.inspect(path)
        assert report.metadata["num_textures"] == 1, report.metadata[
            "unsupported_features"
        ]

    with pytest.raises(sceneio.FormatError, match="source file is missing"):
        sceneio.read_scene(path)


def test_duplicate_material_leaf_names_refuse_without_renaming(tmp_path):
    material_a = _constant_material().replace(
        "/Materials/Mat",
        "/Materials/A/Mat",
    )
    material_b = _constant_material().replace(
        "/Materials/Mat",
        "/Materials/B/Mat",
    )
    materials = (
        '    def Scope "A"\n    {\n'
        + material_a
        + "    }\n"
        + '    def Scope "B"\n    {\n'
        + material_b
        + "    }\n"
    )
    meshes = _mesh_usda(mesh_name="A", binding="/Materials/A/Mat")
    meshes += _mesh_usda(mesh_name="B", binding="/Materials/B/Mat")
    path = tmp_path / "duplicates.usda"
    path.write_text(_stage(meshes=meshes, materials=materials), encoding="utf-8")

    with pytest.raises(sceneio.FormatError, match="unique leaf names"):
        sceneio.read_scene(path)


def test_inherited_nested_mesh_binding_refuses_for_full_and_selected_reads(
    tmp_path,
):
    parent = '''    def Mesh "Parent" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        point3f[] points = []
        int[] faceVertexCounts = []
        int[] faceVertexIndices = []
        uniform token subdivisionScheme = "none"
        rel material:binding = </Materials/Mat>
        def Mesh "Child"
        {
            point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
            int[] faceVertexCounts = [3]
            int[] faceVertexIndices = [0,1,2]
            uniform token subdivisionScheme = "none"
        }
    }
'''
    source = tmp_path / "inherited.usda"
    source.write_text(
        _stage(meshes=parent, materials=_constant_material()),
        encoding="utf-8",
    )

    for selected in (None, "/World/Parent/Child"):
        with pytest.raises(
            sceneio.FormatError,
            match="inherited material bindings",
        ):
            sceneio.read_scene(source, prims=selected)
    assert any(
        "inherited material bindings" in value
        for value in sceneio.inspect(source).metadata["unsupported_features"]
    )


def test_subset_bindings_map_exact_runs_and_cross_write(tmp_path):
    mesh = '''    def Mesh "Surface" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        point3f[] points = [
            (0,0,0), (1,0,0), (0,1,0),
            (1,0,0), (2,0,0), (1,1,0),
            (2,0,0), (3,0,0), (2,1,0),
            (3,0,0), (4,0,0), (3,1,0)
        ]
        int[] faceVertexCounts = [3, 3, 3, 3]
        int[] faceVertexIndices = [0,1,2,3,4,5,6,7,8,9,10,11]
        uniform token subdivisionScheme = "none"
        uniform token subsetFamily:materialBind:familyType = "partition"
        def GeomSubset "A" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {
            uniform token elementType = "face"
            uniform token familyName = "materialBind"
            int[] indices = [0, 2]
            rel material:binding = </Materials/A>
        }
        def GeomSubset "B" (
            prepend apiSchemas = ["MaterialBindingAPI"]
        )
        {
            uniform token elementType = "face"
            uniform token familyName = "materialBind"
            int[] indices = [1, 3]
            rel material:binding = </Materials/B>
        }
    }
'''
    material_a = _constant_material(name="A")
    material_b = _constant_material(name="B").replace(
        "(0.2, 0.3, 0.4)", "(0.8, 0.7, 0.6)"
    )
    source = tmp_path / "subsets.usda"
    valid_usda = _stage(meshes=mesh, materials=material_a + material_b)
    source.write_text(valid_usda, encoding="utf-8")

    scene = sceneio.read_scene(source)
    np.testing.assert_array_equal(scene.mesh_at(0).primitive_offsets, [0, 1, 2, 3, 4])
    np.testing.assert_array_equal(scene.mesh_at(0).primitive_materials, [0, 1, 0, 1])

    output = tmp_path / "subsets.usdz"
    sceneio.write_scene(scene, output)
    oracle = tinyusdz.load(str(output))
    prims = _oracle_prim_index(oracle)
    surface_text = prims["/World/Surface"].to_string()
    assert 'subsetFamily:materialBind:familyType = "partition"' in surface_text
    subset_a = prims["/World/Surface/material_0"]
    subset_b = prims["/World/Surface/material_1"]
    assert subset_a.get_relationship_targets("material:binding") == [
        "/SceneIOMaterials/A"
    ]
    assert subset_b.get_relationship_targets("material:binding") == [
        "/SceneIOMaterials/B"
    ]
    assert "int[] indices = [0, 2]" in subset_a.to_string()
    assert "int[] indices = [1, 3]" in subset_b.to_string()
    actual = sceneio.read_scene(output).mesh_at(0)
    np.testing.assert_array_equal(actual.primitive_offsets, [0, 1, 2, 3, 4])
    np.testing.assert_array_equal(actual.primitive_materials, [0, 1, 0, 1])

    for index, (invalid, message) in enumerate(
        (
            (valid_usda.replace("[1, 3]", "[0, 3]"), "subsets overlap"),
            (
                valid_usda.replace("[1, 3]", "[1]"),
                "partition.*cover every face",
            ),
            (valid_usda.replace("[1, 3]", "[1, 4]"), "out of range"),
        )
    ):
        bad = tmp_path / f"bad-subset-{index}.usda"
        bad.write_text(invalid, encoding="utf-8")
        with pytest.raises(sceneio.FormatError, match=message):
            sceneio.read_scene(bad)


class _BindingPrim:
    def __init__(self, target: str | None):
        self.name = "Surface"
        self._target = target

    def property_names(self):
        return [] if self._target is None else ["material:binding"]

    def children(self):
        return []

    def get_relationship_targets(self, name):
        assert name == "material:binding"
        return None if self._target is None else [self._target]

    def api_schemas(self):
        return [] if self._target is None else ["MaterialBindingAPI"]

    def to_string(self):
        raise AssertionError("binding fast path normalized the complete mesh")


def test_unbound_and_direct_binding_fast_paths_do_not_normalize_mesh_text():
    assert usd_materials.binding_ranges_for_mesh(
        _BindingPrim(None),
        face_count=1_000_000,
        material_indices={},
    ) == {}
    direct = usd_materials.binding_ranges_for_mesh(
        _BindingPrim("/Materials/Mat"),
        face_count=1_000_000,
        material_indices={"/Materials/Mat": 3},
    )
    np.testing.assert_array_equal(direct["primitive_offsets"], [0, 1_000_000])
    np.testing.assert_array_equal(direct["primitive_materials"], [3])


def test_material_binding_strength_metadata_refuses_before_mapping(tmp_path):
    mesh = _mesh_usda().replace(
        "        rel material:binding = </Materials/Mat>",
        '''        rel material:binding = </Materials/Mat> (
            bindMaterialAs = "strongerThanDescendants"
        )''',
    )
    path = tmp_path / "binding-strength.usda"
    path.write_text(
        _stage(meshes=mesh, materials=_constant_material()),
        encoding="utf-8",
    )
    report = sceneio.inspect(path)
    assert "material_binding_strength" in report.metadata["unsupported_features"]
    with pytest.raises(sceneio.FormatError, match="binding strength metadata"):
        sceneio.read_scene(path)


def test_writer_refuses_indistinguishable_blend_and_bad_unpacked_relocation(
    tmp_path,
):
    blend = _core.material_set(
        ["Mat"],
        alpha_modes=["blend"],
    )
    destination = tmp_path / "blend.usda"
    destination.write_bytes(b"keep")
    with pytest.raises(sceneio.FormatError, match="blend materials require"):
        sceneio.write_scene(
            _material_scene(blend, assignments=[0]),
            destination,
        )
    assert destination.read_bytes() == b"keep"

    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()
    texture = source_dir / "albedo.png"
    PIL.fromarray(np.full((2, 2, 3), 127, np.uint8)).save(texture)
    textured = _core.material_set(
        ["Mat"],
        texture_materials=np.array([0], np.uint64),
        texture_semantics=["base_color"],
        texture_paths=["albedo.png"],
    )
    relocated = output_dir / "scene.usda"
    relocated.write_bytes(b"keep")
    with pytest.raises(sceneio.FormatError, match="source file is missing"):
        sceneio.write_scene(
            _material_scene(
                textured,
                assignments=[0],
                assets=(("albedo.png", str(texture)),),
            ),
            relocated,
            package_assets=False,
        )
    assert relocated.read_bytes() == b"keep"

    local = source_dir / "scene.usda"
    sceneio.write_scene(
        _material_scene(
            textured,
            assignments=[0],
            assets=(("albedo.png", str(texture)),),
        ),
        local,
        package_assets=False,
    )
    assert local.is_file()


def test_material_writer_refusal_matrix_preserves_destination(tmp_path):
    texture_a = tmp_path / "a.png"
    texture_b = tmp_path / "b.png"
    _write_png(texture_a)
    _write_png(texture_b)
    cases = (
        (
            _core.material_set(
                ["Mat"],
                texture_materials=np.array([0, 0], np.uint64),
                texture_semantics=["normal", "base_color"],
                texture_paths=["b.png", "a.png"],
            ),
            (("b.png", str(texture_b)), ("a.png", str(texture_a))),
            "rows must be grouped",
        ),
        (
            _core.material_set(
                ["Mat"],
                texture_materials=np.array([0], np.uint64),
                texture_semantics=["base_color"],
                texture_paths=["a.png"],
                texture_min_filters=["linear"],
            ),
            (("a.png", str(texture_a)),),
            "explicit min/mag filters",
        ),
        (
            _core.material_set(
                ["Mat"],
                alpha_modes=["opaque"],
                alpha_cutoffs=np.array([0.25], np.float32),
            ),
            (),
            "alpha cutoffs must retain 0.5",
        ),
    )
    for index, (material_set, assets, message) in enumerate(cases):
        destination = tmp_path / f"refusal-{index}.usda"
        destination.write_bytes(b"keep")
        with pytest.raises(sceneio.FormatError, match=message):
            sceneio.write_scene(
                _material_scene(
                    material_set,
                    assignments=[0],
                    assets=assets,
                ),
                destination,
            )
        assert destination.read_bytes() == b"keep"

    reversed_assets = _core.material_set(
        ["Mat"],
        texture_materials=np.array([0, 0], np.uint64),
        texture_semantics=["base_color", "emissive"],
        texture_paths=["a.png", "b.png"],
        emissive_colors=np.ones((1, 3), np.float32),
    )
    destination = tmp_path / "asset-order.usda"
    destination.write_bytes(b"keep")
    with pytest.raises(sceneio.FormatError, match="first material use"):
        sceneio.write_scene(
            _material_scene(
                reversed_assets,
                assignments=[0],
                assets=(
                    ("b.png", str(texture_b)),
                    ("a.png", str(texture_a)),
                ),
            ),
            destination,
        )
    assert destination.read_bytes() == b"keep"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            'token inputs:sourceColorSpace = "sRGB"',
            'token inputs:sourceColorSpace = "auto"',
            "sourceColorSpace",
        ),
        (
            'token inputs:wrapS = "repeat"',
            'token inputs:wrapS = "black"',
            "must be repeat, clamp, or mirror",
        ),
        (
            "float4 inputs:scale = (1, 1, 1, 1)",
            "float4 inputs:scale = (0.5, 1, 1, 1)",
            "outside the bounded material mapping",
        ),
        (
            'string inputs:varname = "st"',
            'string inputs:varname = "uv0"',
            "varname must be 'st'",
        ),
        (
            'uniform token info:id = "UsdUVTexture"',
            'uniform token info:id = "Procedural"',
            "connect directly to UsdUVTexture",
        ),
        (
            "asset inputs:file = @",
            "token inputs:minificationFilter = \"linear\"\n"
            "            asset inputs:file = @",
            "unsupported properties",
        ),
        (
            "asset inputs:file = @",
            "asset inputs:file = @C:/outside/",
            "normalized and may not escape",
        ),
    ],
)
def test_material_reader_refusal_matrix(tmp_path, old, new, message):
    texture = tmp_path / "albedo.png"
    _write_png(texture)
    source = tmp_path / "canonical.usda"
    sceneio.write_scene(
        _material_scene(
            _textured_material(),
            assignments=[0],
            assets=(("albedo.png", str(texture)),),
        ),
        source,
        package_assets=False,
    )
    text = source.read_text(encoding="utf-8")
    assert old in text
    invalid = tmp_path / "invalid.usda"
    invalid.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read_scene(invalid)


def test_usdz_duplicate_and_noncanonical_members_refuse_before_provider(
    tmp_path,
    monkeypatch,
):
    root = _stage(meshes=_mesh_usda(), materials=_constant_material())
    for name in ("duplicate.usdz", "alias.usdz"):
        path = tmp_path / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("root.usda", root)
            archive.writestr("textures/a.png", b"one")
            if name.startswith("duplicate"):
                with pytest.warns(UserWarning, match="Duplicate name"):
                    archive.writestr("textures/a.png", b"two")
            else:
                archive.writestr("textures/../a.png", b"two")

        def fail_provider(*_args, **_kwargs):
            raise AssertionError("invalid package reached the provider")

        monkeypatch.setattr(tinyusdz, "load", fail_provider)
        with pytest.raises(
            sceneio.FormatError,
            match=r"duplicate package entry|normalized",
        ):
            sceneio.read_scene(path)


def test_usdz_unaligned_members_refuse_before_provider(tmp_path, monkeypatch):
    path = tmp_path / "unaligned.usdz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "root.usda",
            _stage(meshes=_mesh_usda(), materials=_constant_material()),
        )

    def fail_provider(*_args, **_kwargs):
        raise AssertionError("unaligned package reached the provider")

    monkeypatch.setattr(tinyusdz, "load", fail_provider)
    with pytest.raises(sceneio.FormatError, match="64-byte aligned"):
        sceneio.read_scene(path)


@pytest.mark.parametrize("mutation", ["local_name", "local_method"])
def test_usdz_local_and_central_entry_disagreement_refuses(
    tmp_path,
    monkeypatch,
    mutation,
):
    canonical = tmp_path / "canonical.usdz"
    sceneio.write_scene(
        _material_scene(_core.material_set(["Mat"]), assignments=[0]),
        canonical,
    )
    payload = bytearray(canonical.read_bytes())
    if mutation == "local_name":
        payload[30] = ord("x")
    else:
        struct.pack_into("<H", payload, 8, zipfile.ZIP_DEFLATED)
    invalid = tmp_path / f"{mutation}.usdz"
    invalid.write_bytes(payload)

    def fail_provider(*_args, **_kwargs):
        raise AssertionError("disagreeing package reached the provider")

    monkeypatch.setattr(tinyusdz, "load", fail_provider)
    with pytest.raises(sceneio.FormatError, match="local and central"):
        sceneio.read_scene(invalid)


def test_usdz_entry_alignment_and_deterministic_subset_output(tmp_path):
    texture = tmp_path / "source.png"
    _write_png(texture)
    materials = _core.material_set(
        ["A", "B"],
        texture_materials=np.array([0], np.uint64),
        texture_semantics=["base_color"],
        texture_paths=["source.png"],
    )
    scene = _material_scene(
        materials,
        assignments=[0, 1, 0, 1],
        assets=(("source.png", str(texture)),),
    )
    left = tmp_path / "left.usdz"
    right = tmp_path / "right.usdz"
    sceneio.write_scene(scene, left)
    sceneio.write_scene(scene, right)
    assert left.read_bytes() == right.read_bytes()

    raw = left.read_bytes()
    with zipfile.ZipFile(left) as archive:
        assert archive.namelist() == [
            "root.usda",
            "textures/texture_0000.png",
        ]
        assert len(set(archive.namelist())) == len(archive.namelist())
        for info in archive.infolist():
            name_length, extra_length = struct.unpack_from(
                "<HH", raw, info.header_offset + 26
            )
            offset = info.header_offset + 30 + name_length + extra_length
            assert info.compress_type == zipfile.ZIP_STORED
            assert offset % 64 == 0


def test_texture_bytes_can_be_decoded_independently(tmp_path):
    texture = tmp_path / "albedo.png"
    pixels = np.array(
        [[[1, 2, 3], [4, 5, 6]], [[7, 8, 9], [10, 11, 12]]],
        np.uint8,
    )
    PIL.fromarray(pixels).save(texture)
    materials = _core.material_set(
        ["Mat"],
        texture_materials=np.array([0], np.uint64),
        texture_semantics=["base_color"],
        texture_paths=["nested/albedo.png"],
    )
    scene = _material_scene(
        materials,
        assignments=[0],
        assets=(("nested/albedo.png", str(texture)),),
    )
    output = tmp_path / "textured.usdz"
    sceneio.write_scene(scene, output)

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert names == ["root.usda", "textures/texture_0000.png"]
        encoded = archive.read(names[1])
    assert encoded == texture.read_bytes()
    np.testing.assert_array_equal(
        np.asarray(PIL.open(io.BytesIO(encoded))),
        pixels,
    )
    actual = sceneio.read_scene(output)
    assert actual.materials.texture_paths == ["textures/texture_0000.png"]
    assert actual.external_asset_uris == ["textures/texture_0000.png"]
    assert actual.external_asset_sources[0].startswith("sceneio-usdz:")

    oracle = tinyusdz.load(str(output))
    prims = _oracle_prim_index(oracle)
    assert prims["/Surface"].get_relationship_targets(
        "material:binding"
    ) == ["/SceneIOMaterials/Mat"]
    material = prims["/SceneIOMaterials/Mat"]
    assert material.get_attribute_connections("outputs:surface") == [
        "/SceneIOMaterials/Mat/PreviewSurface.outputs:surface"
    ]
    preview = prims["/SceneIOMaterials/Mat/PreviewSurface"]
    assert preview.get_attribute_connections("inputs:diffuseColor") == [
        "/SceneIOMaterials/Mat/Texture_base_color.outputs:rgb"
    ]
    primvar = prims["/SceneIOMaterials/Mat/Primvar_st"]
    assert _oracle_scalar(primvar, "info:id") == "UsdPrimvarReader_float2"
    assert _oracle_scalar(primvar, "inputs:varname") == "st"
    texture_prim = prims["/SceneIOMaterials/Mat/Texture_base_color"]
    assert _oracle_scalar(texture_prim, "info:id") == "UsdUVTexture"
    assert _oracle_scalar(texture_prim, "inputs:file") == (
        "@textures/texture_0000.png@"
    )
    assert texture_prim.get_attribute_connections("inputs:st") == [
        "/SceneIOMaterials/Mat/Primvar_st.outputs:result"
    ]
    assert _oracle_scalar(texture_prim, "inputs:sourceColorSpace") == "sRGB"
    assert _oracle_scalar(texture_prim, "inputs:wrapS") == "repeat"
    assert _oracle_scalar(texture_prim, "inputs:wrapT") == "repeat"
    assert _oracle_scalar(texture_prim, "inputs:scale") == "(1, 1, 1, 1)"
    assert _oracle_scalar(texture_prim, "inputs:bias") == "(0, 0, 0, 0)"


def test_all_texture_semantics_formats_wraps_and_normal_transform(tmp_path):
    OpenEXR = pytest.importorskip("OpenEXR")
    base = tmp_path / "base.png"
    emissive = tmp_path / "emissive.jpg"
    data = tmp_path / "data.png"
    normal = tmp_path / "normal.exr"
    PIL.fromarray(np.full((3, 4, 4), 128, np.uint8)).save(base)
    PIL.fromarray(np.full((3, 4, 3), 64, np.uint8)).save(
        emissive,
        quality=91,
    )
    PIL.fromarray(np.arange(12, dtype=np.uint8).reshape(3, 4)).save(data)
    channels = {
        name: np.full((3, 4), value, np.float32)
        for name, value in zip("RGB", (0.5, 0.5, 1.0), strict=True)
    }
    with OpenEXR.File(
        {
            "compression": OpenEXR.ZIP_COMPRESSION,
            "type": OpenEXR.scanlineimage,
        },
        channels,
    ) as output:
        output.write(str(normal))

    semantics = [
        "base_color",
        "emissive",
        "metallic",
        "roughness",
        "alpha",
        "normal",
    ]
    texture_paths = [
        "base.png",
        "emissive.jpg",
        "data.png",
        "data.png",
        "base.png",
        "normal.exr",
    ]
    wrap_s = [
        "repeat",
        "clamp",
        "mirrored_repeat",
        "repeat",
        "clamp",
        "mirrored_repeat",
    ]
    wrap_t = [
        "mirrored_repeat",
        "repeat",
        "clamp",
        "clamp",
        "repeat",
        "mirrored_repeat",
    ]
    material_set = _core.material_set(
        ["Mat"],
        base_colors=np.ones((1, 4), np.float32),
        emissive_colors=np.ones((1, 3), np.float32),
        metallic=np.ones(1, np.float32),
        roughness=np.ones(1, np.float32),
        alpha_modes=["mask"],
        alpha_cutoffs=np.array([0.4], np.float32),
        texture_materials=np.zeros(6, np.uint64),
        texture_semantics=semantics,
        texture_paths=texture_paths,
        texture_wrap_s=wrap_s,
        texture_wrap_t=wrap_t,
    )
    assets = (
        ("base.png", str(base)),
        ("emissive.jpg", str(emissive)),
        ("data.png", str(data)),
        ("normal.exr", str(normal)),
    )
    output = tmp_path / "all-textures.usdz"
    sceneio.write_scene(
        _material_scene(
            material_set,
            assignments=[0],
            assets=assets,
        ),
        output,
    )
    tinyusdz.load(str(output))

    expected_members = [
        "root.usda",
        "textures/texture_0000.png",
        "textures/texture_0001.jpg",
        "textures/texture_0002.png",
        "textures/texture_0003.exr",
    ]
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == expected_members
        root = archive.read("root.usda").decode("utf-8")
        packaged = {
            member: archive.read(member)
            for member in expected_members[1:]
        }
    assert packaged[expected_members[1]] == base.read_bytes()
    assert packaged[expected_members[2]] == emissive.read_bytes()
    assert packaged[expected_members[3]] == data.read_bytes()
    assert packaged[expected_members[4]] == normal.read_bytes()
    assert "float4 inputs:scale = (2, 2, 2, 1)" in root
    assert "float4 inputs:bias = (-1, -1, -1, 0)" in root
    assert root.count('token inputs:sourceColorSpace = "raw"') == 4
    assert root.count('token inputs:sourceColorSpace = "sRGB"') == 2

    np.testing.assert_array_equal(
        np.asarray(PIL.open(io.BytesIO(packaged[expected_members[1]]))),
        np.asarray(PIL.open(base)),
    )
    np.testing.assert_array_equal(
        np.asarray(PIL.open(io.BytesIO(packaged[expected_members[2]]))),
        np.asarray(PIL.open(emissive)),
    )
    extracted = tmp_path / "oracle.exr"
    extracted.write_bytes(packaged[expected_members[4]])
    with OpenEXR.File(str(extracted)) as oracle:
        actual_channels = {
            name: np.asarray(channel.pixels)
            for name, channel in oracle.parts[0].channels.items()
        }
    for name, values in channels.items():
        np.testing.assert_array_equal(actual_channels[name], values)

    actual = sceneio.read_scene(output).materials
    assert actual.texture_semantics == semantics
    assert actual.texture_paths == [
        "textures/texture_0000.png",
        "textures/texture_0001.jpg",
        "textures/texture_0002.png",
        "textures/texture_0002.png",
        "textures/texture_0000.png",
        "textures/texture_0003.exr",
    ]
    wrap_codes = {"repeat": 0, "clamp": 1, "mirrored_repeat": 2}
    np.testing.assert_array_equal(
        actual.texture_wrap_s_codes,
        [wrap_codes[value] for value in wrap_s],
    )
    np.testing.assert_array_equal(
        actual.texture_wrap_t_codes,
        [wrap_codes[value] for value in wrap_t],
    )
    assert actual.alpha_modes == ["mask"]
    np.testing.assert_array_equal(actual.alpha_cutoffs, [np.float32(0.4)])


def test_asset_source_lifetime_and_missing_source_preserve_destination(tmp_path):
    texture = tmp_path / "albedo.png"
    _write_png(texture)
    source = tmp_path / "source.usdz"
    sceneio.write_scene(
        _material_scene(
            _textured_material(),
            assignments=[0],
            assets=(("albedo.png", str(texture)),),
        ),
        source,
    )
    scene = sceneio.read_scene(source)
    factors = scene.materials.base_colors
    locator = scene.external_asset_sources[0]
    assert locator.startswith("sceneio-usdz:")
    source.unlink()
    gc.collect()
    np.testing.assert_array_equal(factors, np.ones((1, 4), np.float32))

    destination = tmp_path / "preserved.usdz"
    destination.write_bytes(b"keep")
    with pytest.raises(sceneio.FormatError, match="unavailable"):
        sceneio.write_scene(scene, destination)
    assert destination.read_bytes() == b"keep"
    assert sorted(item.name for item in tmp_path.iterdir()) == [
        "albedo.png",
        "preserved.usdz",
    ]


def test_sidecar_copy_and_final_replace_failures_leave_no_partial_state(
    tmp_path,
    monkeypatch,
):
    texture = tmp_path / "albedo.png"
    _write_png(texture)
    scene = _material_scene(
        _textured_material(),
        assignments=[0],
        assets=(("albedo.png", str(texture)),),
    )
    destination = tmp_path / "scene.usda"
    destination.write_bytes(b"keep")
    existing = tmp_path / "scene.assets-existing"
    existing.mkdir()
    (existing / "keep.txt").write_bytes(b"keep")

    def fail_copy(_source, output, *, relative_to):
        del relative_to
        output.write(b"partial")
        raise RuntimeError("injected asset copy failure")

    with monkeypatch.context() as injected:
        injected.setattr(package, "_copy_and_hash", fail_copy)
        with pytest.raises(sceneio.FormatError, match="asset copy failure"):
            sceneio.write_scene(scene, destination)
    assert destination.read_bytes() == b"keep"
    assert (existing / "keep.txt").read_bytes() == b"keep"
    assert sorted(item.name for item in tmp_path.iterdir()) == [
        "albedo.png",
        "scene.assets-existing",
        "scene.usda",
    ]

    real_replace = os.replace

    def fail_final_replace(source, target):
        if Path(target) == destination:
            raise RuntimeError("injected final replace failure")
        return real_replace(source, target)

    with monkeypatch.context() as injected:
        injected.setattr(stage.os, "replace", fail_final_replace)
        with pytest.raises(sceneio.FormatError, match="final replace failure"):
            sceneio.write_scene(scene, destination)
    assert destination.read_bytes() == b"keep"
    assert (existing / "keep.txt").read_bytes() == b"keep"
    assert sorted(item.name for item in tmp_path.iterdir()) == [
        "albedo.png",
        "scene.assets-existing",
        "scene.usda",
    ]


def test_usda_sidecars_handle_duplicate_basenames_reuse_and_conflict(
    tmp_path,
):
    left_directory = tmp_path / "left"
    right_directory = tmp_path / "right"
    left_directory.mkdir()
    right_directory.mkdir()
    left_pixels = np.array([[[1, 2, 3], [4, 5, 6]]], np.uint8)
    right_pixels = np.array([[[7, 8, 9], [10, 11, 12]]], np.uint8)
    left_source = left_directory / "shared.png"
    right_source = right_directory / "shared.png"
    PIL.fromarray(left_pixels).save(left_source)
    PIL.fromarray(right_pixels).save(right_source)
    material_set = _core.material_set(
        ["Left", "Right"],
        texture_materials=np.array([0, 1], np.uint64),
        texture_semantics=["base_color", "base_color"],
        texture_paths=["left/shared.png", "right/shared.png"],
    )
    scene = _material_scene(
        material_set,
        assignments=[0, 1],
        assets=(
            ("left/shared.png", str(left_source)),
            ("right/shared.png", str(right_source)),
        ),
    )
    destination = tmp_path / "scene.usda"

    sceneio.write_scene(scene, destination)
    sidecars = list(tmp_path.glob("scene.assets-*"))
    assert len(sidecars) == 1
    sidecar = sidecars[0]
    packaged = sorted(sidecar.iterdir())
    assert [item.name for item in packaged] == [
        "texture_0000.png",
        "texture_0001.png",
    ]
    np.testing.assert_array_equal(np.asarray(PIL.open(packaged[0])), left_pixels)
    np.testing.assert_array_equal(np.asarray(PIL.open(packaged[1])), right_pixels)
    first_layer = destination.read_bytes()
    first_assets = {item.name: item.read_bytes() for item in packaged}

    sceneio.write_scene(scene, destination)
    assert destination.read_bytes() == first_layer
    assert list(tmp_path.glob("scene.assets-*")) == [sidecar]
    assert {
        item.name: item.read_bytes() for item in sorted(sidecar.iterdir())
    } == first_assets

    packaged[0].write_bytes(b"conflicting existing sidecar")
    conflicting = packaged[0].read_bytes()
    with pytest.raises(sceneio.FormatError, match="contains different bytes"):
        sceneio.write_scene(scene, destination)
    assert destination.read_bytes() == first_layer
    assert packaged[0].read_bytes() == conflicting
    assert list(tmp_path.glob(".scene.usda.assets.*")) == []

def test_compressed_usdz_texture_is_refused(tmp_path):
    texture = tmp_path / "albedo.png"
    _write_png(texture)
    canonical = tmp_path / "canonical.usdz"
    sceneio.write_scene(
        _material_scene(
            _textured_material(),
            assignments=[0],
            assets=(("albedo.png", str(texture)),),
        ),
        canonical,
    )
    with zipfile.ZipFile(canonical) as source:
        root = source.read("root.usda")
        encoded = source.read("textures/texture_0000.png")
    compressed = tmp_path / "compressed.usdz"
    with zipfile.ZipFile(
        compressed,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr("root.usda", root, compress_type=zipfile.ZIP_STORED)
        archive.writestr("textures/texture_0000.png", encoded)
    with pytest.raises(sceneio.FormatError, match="must be stored"):
        sceneio.read_scene(compressed)


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
def test_large_texture_write_has_bounded_python_allocation(tmp_path, suffix):
    texture = tmp_path / "large.png"
    chunk = bytes(1024 * 1024)
    with texture.open("wb") as stream:
        for _ in range(16):
            stream.write(chunk)
    scene = _material_scene(
        _textured_material("large.png"),
        assignments=[0],
        assets=(("large.png", str(texture)),),
    )
    destination = tmp_path / f"large{suffix}"

    _, peak = stable_traced_peak(
        lambda: sceneio.write_scene(scene, destination)
    )

    if suffix == ".usda":
        sidecars = list(tmp_path.glob("large.assets-*"))
        assert len(sidecars) == 1
        packaged = list(sidecars[0].iterdir())
        assert len(packaged) == 1
        assert packaged[0].stat().st_size == texture.stat().st_size
    else:
        assert destination.stat().st_size >= texture.stat().st_size
    assert peak < texture.stat().st_size / 4


def test_direct_asset_symlink_cannot_leave_layer_directory(tmp_path):
    outside = tmp_path / "outside.png"
    PIL.fromarray(np.zeros((1, 1, 3), np.uint8)).save(outside)
    layer_dir = tmp_path / "layer"
    layer_dir.mkdir()
    link = layer_dir / "linked.png"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("local platform does not permit test symlink creation")
    material = '''    def Material "Mat"
    {
        token outputs:surface.connect = </Materials/Mat/Preview.outputs:surface>
        def Shader "Preview"
        {
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect = </Materials/Mat/Tex.outputs:rgb>
            token outputs:surface
        }
        def Shader "Primvar"
        {
            uniform token info:id = "UsdPrimvarReader_float2"
            string inputs:varname = "st"
            float2 outputs:result
        }
        def Shader "Tex"
        {
            uniform token info:id = "UsdUVTexture"
            asset inputs:file = @linked.png@
            float2 inputs:st.connect = </Materials/Mat/Primvar.outputs:result>
            token inputs:wrapS = "repeat"
            token inputs:wrapT = "repeat"
            token inputs:sourceColorSpace = "sRGB"
            float3 outputs:rgb
        }
    }
'''
    path = layer_dir / "scene.usda"
    path.write_text(
        _stage(meshes=_mesh_usda(), materials=material),
        encoding="utf-8",
    )
    with pytest.raises(sceneio.FormatError, match="leaves the root-layer"):
        sceneio.read_scene(path)
