from __future__ import annotations

import base64
import hashlib
import json
import locale
import os
import struct
import tracemalloc

import numpy as np
import pytest
import trimesh
from pygltflib import GLTF2

import sceneio
from sceneio import _core


def _append(payload: bytearray, values: bytes, *, alignment: int = 4) -> tuple[int, int]:
    while len(payload) % alignment:
        payload.append(0)
    offset = len(payload)
    payload.extend(values)
    return offset, len(values)


def _fixture(*, data_uri: bool = False) -> tuple[bytes, bytes]:
    payload = bytearray()
    views: list[dict] = []

    def view(values: bytes, **kwargs) -> int:
        offset, size = _append(payload, values)
        views.append(
            {"buffer": 0, "byteOffset": offset, "byteLength": size, **kwargs}
        )
        return len(views) - 1

    interleaved = b"".join(
        struct.pack("<fffI", *position, 0xDEADBEEF)
        for position in ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0))
    )
    position_view = view(interleaved, byteStride=16, target=34962)
    normal_view = view(struct.pack("<9f", *(0.0, 0.0, 1.0) * 3), target=34962)
    uv_view = view(struct.pack("<6H", 0, 0, 65535, 0, 0, 65535), target=34962)
    color_view = view(bytes([255, 0, 0, 0, 255, 0, 0, 0, 255]), target=34962)
    index_view = view(struct.pack("<3H", 0, 1, 2), target=34963)
    sparse_index_view = view(bytes([0, 1, 2]))
    sparse_value_view = view(
        struct.pack(
            "<9f",
            0.0,
            0.0,
            1.0,
            1.0,
            0.0,
            1.0,
            0.0,
            1.0,
            1.0,
        )
    )
    accessors = [
        {
            "bufferView": position_view,
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
            "min": [0, 0, 0],
            "max": [2, 2, 0],
        },
        {
            "bufferView": normal_view,
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
        },
        {
            "bufferView": uv_view,
            "componentType": 5123,
            "normalized": True,
            "count": 3,
            "type": "VEC2",
        },
        {
            "bufferView": color_view,
            "componentType": 5121,
            "normalized": True,
            "count": 3,
            "type": "VEC3",
        },
        {
            "bufferView": index_view,
            "componentType": 5123,
            "count": 3,
            "type": "SCALAR",
        },
        {
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
            "min": [0, 0, 1],
            "max": [1, 1, 1],
            "sparse": {
                "count": 3,
                "indices": {
                    "bufferView": sparse_index_view,
                    "componentType": 5121,
                },
                "values": {"bufferView": sparse_value_view},
            },
        },
    ]
    uri = (
        "data:application/octet-stream;base64,"
        + base64.b64encode(payload).decode("ascii")
        if data_uri
        else "mesh%20data.bin"
    )
    document = {
        "asset": {"version": "2.0", "generator": "independent-test-fixture"},
        "buffers": [{"uri": uri, "byteLength": len(payload)}],
        "bufferViews": views,
        "accessors": accessors,
        "images": [
            {
                "uri": "data:image/png;base64,"
                + base64.b64encode(b"independent-image-reference").decode("ascii")
            }
        ],
        "samplers": [
            {
                "magFilter": 9729,
                "minFilter": 9987,
                "wrapS": 33071,
                "wrapT": 33648,
            }
        ],
        "textures": [{"sampler": 0, "source": 0}],
        "materials": [
            {
                "name": "",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.25, 0.5, 0.75, 1.0],
                    "metallicFactor": 0.3,
                    "roughnessFactor": 0.7,
                    "baseColorTexture": {"index": 0, "texCoord": 0},
                },
                "emissiveFactor": [0.1, 0.2, 0.3],
                "alphaMode": "MASK",
                "alphaCutoff": 0.4,
            },
            {"name": ""},
        ],
        "meshes": [
            {
                "name": "surface",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "NORMAL": 1,
                            "TEXCOORD_0": 2,
                            "COLOR_0": 3,
                        },
                        "indices": 4,
                        "material": 0,
                        "mode": 4,
                    }
                ],
            },
            {
                "name": "sparse",
                "primitives": [
                    {
                        "attributes": {"POSITION": 5},
                        "material": 1,
                    }
                ],
            },
        ],
        "nodes": [
            {"name": "root", "mesh": 0, "children": [1], "translation": [1, 2, 3]},
            {"name": "child", "mesh": 1, "scale": [2, 2, 2]},
        ],
        "scenes": [{"name": "main", "nodes": [0]}],
        "scene": 0,
    }
    return (
        json.dumps(document, separators=(",", ":")).encode(),
        bytes(payload),
    )


def _glb(json_bytes: bytes, binary: bytes) -> bytes:
    document = json.loads(json_bytes)
    document["buffers"][0].pop("uri", None)
    json_chunk = json.dumps(document, separators=(",", ":")).encode()
    json_chunk += b" " * (-len(json_chunk) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary)
    return b"".join(
        [
            struct.pack("<III", 0x46546C67, 2, total),
            struct.pack("<II", len(json_chunk), 0x4E4F534A),
            json_chunk,
            struct.pack("<II", len(binary), 0x004E4942),
            binary,
        ]
    )


def _assert_mesh(actual, expected):
    for name in (
        "positions",
        "face_offsets",
        "face_indices",
        "vertex_normals",
        "vertex_uvs",
        "vertex_colors",
        "primitive_offsets",
        "primitive_materials",
    ):
        np.testing.assert_array_equal(getattr(actual, name), getattr(expected, name))


def _assert_scene(actual, expected):
    assert actual.mesh_names == expected.mesh_names
    assert actual.node_names == expected.node_names
    assert actual.scene_names == expected.scene_names
    assert actual.default_scene == expected.default_scene
    np.testing.assert_array_equal(
        actual.mesh_primitive_offsets, expected.mesh_primitive_offsets
    )
    assert actual.node_payload_kinds == expected.node_payload_kinds
    np.testing.assert_array_equal(
        actual.node_payload_indices, expected.node_payload_indices
    )
    np.testing.assert_array_equal(
        actual.node_child_offsets, expected.node_child_offsets
    )
    np.testing.assert_array_equal(actual.node_children, expected.node_children)
    np.testing.assert_array_equal(
        actual.node_local_transforms, expected.node_local_transforms
    )
    np.testing.assert_array_equal(
        actual.scene_root_offsets, expected.scene_root_offsets
    )
    np.testing.assert_array_equal(actual.scene_roots, expected.scene_roots)
    assert actual.has_materials == expected.has_materials
    if actual.has_materials:
        assert actual.materials.names == expected.materials.names
        assert actual.materials.texture_paths == expected.materials.texture_paths
        assert (
            actual.materials.texture_semantics
            == expected.materials.texture_semantics
        )
        for name in (
            "base_colors",
            "emissive_colors",
            "metallic",
            "roughness",
            "alpha_cutoffs",
            "texture_materials",
            "texture_uv_sets",
        ):
            np.testing.assert_array_equal(
                getattr(actual.materials, name),
                getattr(expected.materials, name),
            )
    assert actual.num_mesh_primitives == expected.num_mesh_primitives
    for index in range(actual.num_mesh_primitives):
        _assert_mesh(
            actual.mesh_primitive_at(index),
            expected.mesh_primitive_at(index),
        )


@pytest.mark.parametrize("data_uri", [False, True])
def test_independent_json_fixture_external_and_data_uri(data_uri):
    document, binary = _fixture(data_uri=data_uri)
    resources = {} if data_uri else {"mesh%20data.bin": binary}

    scene = _core.read_gltf(document, resources)

    assert scene.mesh_names == ["surface", "sparse"]
    assert scene.node_names == ["root", "child"]
    assert scene.scene_names == ["main"]
    assert scene.default_scene == 0
    np.testing.assert_array_equal(
        scene.node_local_transforms[0],
        np.array(
            [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]],
            np.float64,
        ),
    )
    np.testing.assert_array_equal(
        scene.node_local_transforms[1], np.diag([2, 2, 2, 1])
    )
    first = scene.mesh_primitive_at(0)
    np.testing.assert_array_equal(
        first.positions, [[0, 0, 0], [2, 0, 0], [0, 2, 0]]
    )
    np.testing.assert_array_equal(first.vertex_uvs, [[0, 0], [1, 0], [0, 1]])
    np.testing.assert_array_equal(
        first.vertex_colors,
        [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]],
    )
    np.testing.assert_array_equal(
        scene.mesh_primitive_at(1).positions,
        [[0, 0, 1], [1, 0, 1], [0, 1, 1]],
    )
    assert scene.materials.names == ["", ""]
    np.testing.assert_allclose(
        scene.materials.base_colors[0], [0.25, 0.5, 0.75, 1]
    )
    assert scene.materials.texture_semantics == ["base_color"]
    np.testing.assert_array_equal(scene.materials.texture_wrap_s_codes, [1])
    np.testing.assert_array_equal(scene.materials.texture_wrap_t_codes, [2])
    np.testing.assert_array_equal(scene.materials.texture_min_filter_codes, [6])
    np.testing.assert_array_equal(scene.materials.texture_mag_filter_codes, [2])


def test_independent_glb_fixture_and_buffer_differential():
    document, binary = _fixture()
    encoded = _glb(document, binary)

    from_bytes = _core.read_glb(encoded)
    from_view = _core.read_glb(memoryview(encoded))

    _assert_scene(from_bytes, from_view)
    assert _core._buffer_address(encoded) == np.frombuffer(encoded, np.uint8).ctypes.data


def test_compiled_writer_roundtrip_and_independent_oracles(tmp_path):
    document, binary = _fixture()
    source = _core.read_gltf(document, {"mesh%20data.bin": binary})

    glb_bytes = _core.write_glb(source)
    assert glb_bytes == _core.write_glb(source)
    decoded = _core.read_glb(glb_bytes)
    _assert_scene(decoded, source)

    json_bytes, bin_bytes = _core.write_gltf(source, "model.bin")
    decoded_json = _core.read_gltf(json_bytes, {"model.bin": bin_bytes})
    _assert_scene(decoded_json, source)

    glb_path = tmp_path / "model.glb"
    gltf_path = tmp_path / "model.gltf"
    glb_path.write_bytes(glb_bytes)
    gltf_path.write_bytes(json_bytes)
    (tmp_path / "model.bin").write_bytes(bin_bytes)
    glb_oracle = GLTF2().load(str(glb_path))
    json_oracle = GLTF2().load(str(gltf_path))
    assert len(glb_oracle.meshes) == len(json_oracle.meshes) == 2
    assert sum(len(mesh.primitives) for mesh in glb_oracle.meshes) == 2
    assert len(glb_oracle.nodes) == 2
    assert glb_oracle.scene == 0

    trimesh_glb = trimesh.load(glb_path, force="scene")
    trimesh_json = trimesh.load(gltf_path, force="scene")
    assert len(trimesh_glb.geometry) == len(trimesh_json.geometry) == 2
    assert sum(len(mesh.faces) for mesh in trimesh_glb.geometry.values()) == 2


def test_compiled_writer_golden_hashes_pin_deterministic_layout():
    document, binary = _fixture()
    source = _core.read_gltf(document, {"mesh%20data.bin": binary})
    json_bytes, bin_bytes = _core.write_gltf(source, "model.bin")

    assert hashlib.sha256(json_bytes).hexdigest() == (
        "56ef7425d4c7eecbcaa19030c0eb306472f8fbd26d6c03c81d0c1b565db1e2d5"
    )
    assert hashlib.sha256(bin_bytes).hexdigest() == (
        "3f13708e70bc3908951a8fe9eab4158209fc9f3b9de8fbaff3db939809447df0"
    )
    assert hashlib.sha256(_core.write_glb(source)).hexdigest() == (
        "3b701a86a19c36cb62cb03c4030b0bb9d0203899bd9503778837e18e24af33c0"
    )


def test_writer_is_independent_of_process_numeric_locale():
    document, binary = _fixture()
    source = _core.read_gltf(document, {"mesh%20data.bin": binary})
    expected_json, expected_bin = _core.write_gltf(source, "model.bin")
    expected_glb = _core.write_glb(source)
    previous = locale.setlocale(locale.LC_NUMERIC)
    candidates = (
        "German_Germany.1252",
        "de-DE",
        "de_DE.UTF-8",
        "de_DE.utf8",
        "French_France.1252",
        "fr-FR",
        "fr_FR.UTF-8",
    )
    try:
        for candidate in candidates:
            try:
                locale.setlocale(locale.LC_NUMERIC, candidate)
            except locale.Error:
                continue
            if locale.localeconv()["decimal_point"] != ".":
                break
        else:
            pytest.skip("no comma-decimal numeric locale is installed")

        actual_json, actual_bin = _core.write_gltf(source, "model.bin")
        actual_glb = _core.write_glb(source)
    finally:
        locale.setlocale(locale.LC_NUMERIC, previous)

    assert actual_json == expected_json
    assert actual_bin == expected_bin
    assert actual_glb == expected_glb
    _assert_scene(
        _core.read_gltf(actual_json, {"model.bin": actual_bin}),
        source,
    )
    _assert_scene(_core.read_glb(actual_glb), source)


@pytest.mark.parametrize("suffix", [".gltf", ".glb"])
def test_public_api_e2e_sink_inspect_partial_and_lifetime(tmp_path, suffix):
    document, binary = _fixture()
    source = _core.read_gltf(document, {"mesh%20data.bin": binary})
    path = tmp_path / f"scene{suffix}"

    sceneio.write(source, path)
    assert sceneio.detect(path) == suffix[1:]
    decoded = sceneio.read(path)
    _assert_scene(decoded, source)
    inspected = sceneio.inspect(path)
    assert inspected.payload_kind == "scene_graph"
    assert inspected.shape == (6, 3)
    assert inspected.metadata["num_meshes"] == 2
    assert inspected.metadata["num_primitives"] == 2
    selected_mesh = sceneio.read_partial(path, mesh_id=1)
    selected_primitive = sceneio.read_partial(path, primitive_id=0)
    assert selected_mesh.mesh_names == ["sparse"]
    assert selected_primitive.mesh_names == ["surface"]
    _assert_mesh(
        selected_mesh.mesh_primitive_at(0),
        source.mesh_primitive_at(1),
    )
    _assert_mesh(
        selected_primitive.mesh_primitive_at(0),
        source.mesh_primitive_at(0),
    )

    positions = decoded.mesh_primitive_at(1).positions
    if suffix == ".gltf":
        path.with_suffix(".bin").unlink()
    path.unlink()
    np.testing.assert_array_equal(
        positions, [[0, 0, 1], [1, 0, 1], [0, 1, 1]]
    )


def test_gltf_sink_matches_buffer_writer_byte_for_byte(tmp_path):
    document, binary = _fixture()
    scene = _core.read_gltf(document, {"mesh%20data.bin": binary})
    path = tmp_path / "same.gltf"

    sceneio.write(scene, path)
    expected_json, expected_bin = _core.write_gltf(scene, "same.bin")

    assert path.read_bytes() == expected_json
    assert path.with_suffix(".bin").read_bytes() == expected_bin


def test_glb_sink_matches_buffer_writer_byte_for_byte(tmp_path):
    document, binary = _fixture()
    scene = _core.read_gltf(document, {"mesh%20data.bin": binary})
    path = tmp_path / "same.glb"

    sceneio.write(scene, path)

    assert path.read_bytes() == _core.write_glb(scene)


@pytest.mark.parametrize("suffix", [".gltf", ".glb"])
def test_empty_scene_roundtrip(tmp_path, suffix):
    source = _core.scene_graph([])
    path = tmp_path / f"empty{suffix}"

    sceneio.write(source, path)
    actual = sceneio.read(path)

    assert actual.num_meshes == actual.num_mesh_primitives == 0
    assert sceneio.inspect(path).shape == (0, 3)


def test_inspect_gltf_does_not_require_external_payload(tmp_path):
    document, _ = _fixture()
    path = tmp_path / "scene.gltf"
    path.write_bytes(document)

    inspected = sceneio.inspect(path)

    assert inspected.shape == (6, 3)
    assert inspected.metadata["num_external_buffers"] == 1
    assert inspected.byte_size > len(document)


def test_inspector_enforces_the_same_attribute_schema_as_decoder():
    document, _ = _fixture(data_uri=True)
    value = json.loads(document)
    value["accessors"][3]["normalized"] = False
    encoded = json.dumps(value, separators=(",", ":")).encode()

    for operation in (_core.inspect_gltf, _core.read_gltf):
        with pytest.raises(ValueError, match=r"COLOR_0|normalized"):
            operation(encoded)


def test_sparse_index_accessor_requires_strictly_increasing_destinations():
    document, binary = _fixture()
    value = json.loads(document)
    payload = bytearray(binary)
    while len(payload) % 4:
        payload.append(0)
    sparse_indices_offset = len(payload)
    payload.extend(b"\x00\x00")
    while len(payload) % 4:
        payload.append(0)
    sparse_values_offset = len(payload)
    payload.extend(struct.pack("<2H", 0, 1))
    sparse_indices_view = len(value["bufferViews"])
    value["bufferViews"].append(
        {
            "buffer": 0,
            "byteOffset": sparse_indices_offset,
            "byteLength": 2,
        }
    )
    sparse_values_view = len(value["bufferViews"])
    value["bufferViews"].append(
        {
            "buffer": 0,
            "byteOffset": sparse_values_offset,
            "byteLength": 4,
        }
    )
    value["accessors"][4]["sparse"] = {
        "count": 2,
        "indices": {
            "bufferView": sparse_indices_view,
            "componentType": 5121,
        },
        "values": {"bufferView": sparse_values_view},
    }
    value["buffers"][0]["byteLength"] = len(payload)
    encoded = json.dumps(value, separators=(",", ":")).encode()

    with pytest.raises(ValueError, match=r"validation|strictly increasing"):
        _core.read_gltf(encoded, {"mesh%20data.bin": bytes(payload)})


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["meshes"][0]["primitives"][0].update(mode=1),
            "TRIANGLES",
        ),
        (
            lambda value: value.update(
                extensionsUsed=["KHR_draco_mesh_compression"]
            ),
            "extensions",
        ),
        (
            lambda value: value.update(
                cameras=[
                    {
                        "type": "perspective",
                        "perspective": {"yfov": 1, "znear": 0.1},
                    }
                ]
            ),
            "cameras",
        ),
        (
            lambda value: value["materials"][0].update(doubleSided=True),
            "double-sided",
        ),
        (
            lambda value: value["nodes"][1].update(children=[0]),
            "validation|cyclic|invalid",
        ),
        (
            lambda value: value["bufferViews"][0].update(byteOffset=10**9),
            "validation|invalid",
        ),
    ],
)
def test_unsupported_or_malformed_documents_fail_clearly(mutate, message):
    document, binary = _fixture(data_uri=True)
    value = json.loads(document)
    mutate(value)
    encoded = json.dumps(value, separators=(",", ":")).encode()

    with pytest.raises(ValueError, match=message):
        _core.read_gltf(encoded)


@pytest.mark.parametrize("size", [0, 1, 11, 12, 19, 31])
def test_truncated_glb_is_rejected(size):
    document, binary = _fixture()
    encoded = _glb(document, binary)

    with pytest.raises(ValueError):
        _core.read_glb(encoded[:size])


def test_reader_rejects_writable_or_wrong_container_buffers():
    document, binary = _fixture()
    encoded = _glb(document, binary)

    with pytest.raises(ValueError, match="read-only"):
        _core.read_glb(bytearray(encoded))
    with pytest.raises(ValueError, match="binary"):
        _core.read_glb(document)
    with pytest.raises(ValueError, match="JSON"):
        _core.read_gltf(encoded)


def test_public_gltf_read_does_not_allocate_whole_file_python_bytes(tmp_path):
    count = 300_000
    positions = np.arange(count * 3, dtype=np.float32).reshape(count, 3)
    binary = positions.tobytes()
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "large.bin", "byteLength": len(binary)}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(binary),
                "target": 34962,
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": count,
                "type": "VEC3",
                "min": positions.min(axis=0).tolist(),
                "max": positions.max(axis=0).tolist(),
            }
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
    }
    path = tmp_path / "large.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.with_suffix(".bin").write_bytes(binary)

    tracemalloc.start()
    scene = sceneio.read(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert scene.mesh_primitive_at(0).num_vertices == count
    assert peak < len(binary) // 3


def test_random_truncations_never_escape_as_non_python_fault():
    document, binary = _fixture()
    encoded = _glb(document, binary)
    rng = np.random.default_rng(20260725)

    for stop in rng.integers(0, len(encoded), size=40):
        with pytest.raises((ValueError, MemoryError)):
            _core.read_glb(encoded[: int(stop)])


def test_public_capabilities_include_exact_subset_and_selectors():
    for format_id in ("gltf", "glb"):
        capabilities = sceneio.capabilities(format_id)
        assert capabilities.record_type == "SceneGraph"
        assert capabilities.partial_selectors == ("mesh_id", "primitive_id")
        assert "sparse_accessors" in capabilities.supported_features
        assert "draco" in capabilities.unsupported_features
        assert capabilities.streams_read
        assert capabilities.streams_write


def test_external_uri_percent_decoding(tmp_path):
    document, binary = _fixture()
    path = tmp_path / "scene.gltf"
    path.write_bytes(document)
    (tmp_path / "mesh data.bin").write_bytes(binary)

    scene = sceneio.read(path)

    assert scene.num_mesh_primitives == 2


def test_missing_external_buffer_is_clear(tmp_path):
    document, _ = _fixture()
    path = tmp_path / "scene.gltf"
    path.write_bytes(document)

    with pytest.raises(sceneio.FormatError, match=r"mesh data\.bin|not find"):
        sceneio.read(path)


def test_writer_guards_unrepresentable_mesh_conventions():
    positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
    mesh = _core.mesh(
        positions,
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        corner_uvs=np.array([[0, 0], [1, 0], [0, 1]], np.float32),
        coordinate_frame="opengl",
    )
    scene = _core.scene_graph(
        [],
        meshes=[mesh],
        mesh_primitive_offsets=np.array([0, 1], np.uint64),
    )

    with pytest.raises(ValueError, match="corner-domain"):
        _core.write_glb(scene)


def test_public_write_is_rollback_safe_for_gltf_pair(tmp_path, monkeypatch):
    document, binary = _fixture()
    scene = _core.read_gltf(document, {"mesh%20data.bin": binary})
    path = tmp_path / "scene.gltf"
    peer = path.with_suffix(".bin")
    path.write_bytes(b"old-json")
    peer.write_bytes(b"old-bin")

    original = os.replace
    calls = 0

    def fail_second_publish(source, target):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected publication failure")
        return original(source, target)

    monkeypatch.setattr(os, "replace", fail_second_publish)
    with pytest.raises(sceneio.FormatError, match="injected"):
        sceneio.write(scene, path)

    assert path.read_bytes() == b"old-json"
    assert peer.read_bytes() == b"old-bin"
    assert not list(tmp_path.glob("*.sceneio-*"))
