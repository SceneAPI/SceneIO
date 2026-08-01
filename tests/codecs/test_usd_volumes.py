from __future__ import annotations

import gc
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core

tinyusdz = pytest.importorskip("tinyusdz")


def _volume_stage(uri: str = "density.vdb") -> str:
    return f'''#usda 1.0
def Xform "Root"
{{
    def Volume "FogA"
    {{
        rel field:density = </Fields/Density>
    }}
    def Volume "FogB"
    {{
        rel field:smoke = </Fields/Density>
    }}
}}
def Scope "Fields"
{{
    def OpenVDBAsset "Density"
    {{
        token fieldClass = "unknown"
        token fieldDataType = "float"
        token fieldName = "density"
        asset filePath = @{uri}@
        token vectorDataRoleHint = "None"
    }}
}}
'''


def _volume_scene(source: Path):
    return _core.scene_graph(
        ["Fog"],
        node_payload_kinds=["volume"],
        node_payload_indices=np.array([0], np.uint64),
        volumes=[_core.volume_asset("density.vdb", "density", "density")],
        external_asset_uris=["density.vdb"],
        external_asset_kinds=["openvdb"],
        external_asset_sources=[str(source)],
    )


def test_shared_openvdb_dependency_is_not_decoded(tmp_path):
    vdb = tmp_path / "density.vdb"
    vdb.write_bytes(b"deliberately not a VDB payload")
    path = tmp_path / "volumes.usda"
    path.write_text(_volume_stage(), encoding="utf-8")

    scene = sceneio.read_scene(path)

    assert scene.node_payload_kinds == ["none", "volume", "volume", "none"]
    assert scene.num_volumes == 2
    assert scene.volume_at(0).field_name == "density"
    assert scene.volume_at(1).field_name == "smoke"
    assert scene.external_asset_uris == ["density.vdb"]
    assert scene.external_asset_kinds == ["openvdb"]
    assert Path(scene.external_asset_sources[0]).samefile(vdb)

    first = scene.volume_at(0)
    del scene
    gc.collect()
    assert first.grid_name == "density"


def test_large_openvdb_dependency_does_not_allocate_its_file_size(tmp_path):
    logical_size = 32 * 1024 * 1024
    vdb = tmp_path / "density.vdb"
    with vdb.open("wb") as stream:
        stream.seek(logical_size - 1)
        stream.write(b"\0")
    path = tmp_path / "large-volume.usda"
    path.write_text(_volume_stage(), encoding="utf-8")

    tracemalloc.start()
    try:
        scene = sceneio.read_scene(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert scene.num_volumes == 2
    assert peak < logical_size // 8


def test_missing_vdb_is_reported_on_read_but_not_structural_inspection(tmp_path):
    path = tmp_path / "missing.usda"
    path.write_text(_volume_stage("missing.vdb"), encoding="utf-8")

    inspected = sceneio.inspect(path)
    assert inspected.metadata["dependencies"] == ("missing.vdb",)
    assert inspected.metadata["num_volumes"] == 2
    with pytest.raises(sceneio.FormatError, match="source file is missing"):
        sceneio.read_scene(path)


def test_selected_sibling_does_not_resolve_unselected_volume(tmp_path):
    path = tmp_path / "selected.usda"
    path.write_text(
        _volume_stage("missing.vdb").replace(
            'def Xform "Root"\n{',
            'def Xform "Good" {}\ndef Xform "Root"\n{',
        ),
        encoding="utf-8",
    )

    scene = sceneio.read_scene(path, prims="/Good")

    assert scene.node_names == ["Good"]
    assert scene.num_volumes == 0


def test_volume_writer_roundtrips_literal_relationship_and_asset(tmp_path):
    source = tmp_path / "density.vdb"
    source.write_bytes(b"external-grid-bytes")
    destination = tmp_path / "volume.usda"

    sceneio.write_scene(
        _volume_scene(source),
        destination,
        package_assets=False,
    )

    text = destination.read_text(encoding="utf-8")
    assert "rel field:density" in text
    assert "def OpenVDBAsset" in text
    assert "asset filePath = @density.vdb@" in text
    oracle = tinyusdz.load(str(destination))
    assert [prim.type_name for prim in tinyusdz.traverse(oracle)].count(
        "OpenVDBAsset"
    ) == 1
    decoded = sceneio.read_scene(destination)
    assert decoded.volume_at(0).uri == "density.vdb"
    assert decoded.volume_at(0).grid_name == "density"


def test_volume_usdz_and_unrepresented_field_class_preserve_destination(tmp_path):
    source = tmp_path / "density.vdb"
    source.write_bytes(b"grid")
    destination = tmp_path / "keep.usdz"
    destination.write_bytes(b"keep")

    with pytest.raises(sceneio.FormatError, match=r"outside USDZ 1.3"):
        sceneio.write_scene(_volume_scene(source), destination)
    assert destination.read_bytes() == b"keep"

    unsupported = tmp_path / "fog-class.usda"
    unsupported.write_text(
        _volume_stage().replace('fieldClass = "unknown"', 'fieldClass = "fogVolume"'),
        encoding="utf-8",
    )
    with pytest.raises(sceneio.FormatError, match="fieldClass must be 'unknown'"):
        sceneio.read_scene(unsupported)
