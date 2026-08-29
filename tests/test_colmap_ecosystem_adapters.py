from __future__ import annotations

import gc
import json
import struct
import tracemalloc
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from sceneio import _core
from sceneio.colmap import (
    UINT32_MAX,
    CharucoBoard,
    CharucoCalibration,
    ColmapAdapterError,
    ExtendedSparseModel,
    IdTags,
    MappingCamera,
    MappingImage,
    MappingInput,
    MappingMatch,
    MegaLocArtifacts,
    MegaLocImage,
    MegaLocPair,
    NamedMatches,
    RigConfigCamera,
    RigConfiguration,
    SiftFeatures,
    SimilarityTransform,
    SparseExtensions,
    inspect_mapping_input,
    inspect_megaloc_artifacts,
    read_extended_sparse_model,
    read_feature_matches,
    read_image_pairs,
    read_mapping_input,
    read_megaloc_artifacts,
    read_rig_config,
    read_sift_features,
    read_similarity_transform,
    read_sparse_extensions,
    read_stock_image_pairs,
    write_extended_sparse_model,
    write_feature_matches,
    write_image_pairs,
    write_mapping_input,
    write_megaloc_artifacts,
    write_rig_config,
    write_sift_features,
    write_similarity_transform,
)
from sceneio.colmap import mapping_input as mapping_input_module
from sceneio.colmap import megaloc as megaloc_module


def _mapping_bytes(version: int) -> bytes:
    parts = [struct.pack("<8sII", b"PCMAPIN\0", version, 1)]
    parts.extend(
        [
            struct.pack("<IIQQI", 7, 1, 640, 480, 4),
            struct.pack("<4d", 500.0, 501.0, 320.0, 240.0),
            struct.pack("<B", 1),
            struct.pack("<I", 2),
        ]
    )
    for image_id, time_id, name, points in (
        (11, 21, "left/é.png", ((1.0, 2.0), (3.0, 4.0))),
        (12, 22, "right.png", ((5.0, 6.0), (7.0, 8.0))),
    ):
        encoded = name.encode()
        parts.append(struct.pack("<II", image_id, 7))
        if version == 2:
            parts.append(struct.pack("<I", time_id))
        parts.append(struct.pack("<I", len(encoded)) + encoded)
        parts.append(struct.pack("<I4f", 2, *sum(points, ())))
    parts.extend(
        [
            struct.pack("<I", 1),
            struct.pack("<IIiB", 11, 12, 2, 1),
            struct.pack("<7d", 0.0, 0.0, 0.0, 1.0, 1.0, 2.0, 3.0),
            struct.pack("<I4I", 2, 0, 1, 1, 0),
        ]
    )
    return b"".join(parts)


@pytest.mark.parametrize("version", [1, 2])
def test_mapping_input_independent_wire_roundtrip_and_lifetime(tmp_path, version):
    source = tmp_path / f"mapping-v{version}.pcmapin"
    source.write_bytes(_mapping_bytes(version))
    value = read_mapping_input(source)
    assert value.version == version
    assert value.images[0].time_id == (UINT32_MAX if version == 1 else 21)
    np.testing.assert_array_equal(
        value.matches[0].matches,
        np.array([[0, 1], [1, 0]], dtype=np.uint32),
    )
    assert not value.images[0].keypoints.flags.writeable
    keypoints = value.images[0].keypoints
    del value
    gc.collect()
    np.testing.assert_array_equal(
        keypoints,
        np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
    )
    decoded = read_mapping_input(source)
    output = tmp_path / "out.pcmapin"
    write_mapping_input(decoded, output)
    assert output.read_bytes() == source.read_bytes()
    assert inspect_mapping_input(output) == {
        "version": version,
        "num_cameras": 1,
        "num_images": 2,
        "num_matches": 1,
        "num_keypoints": 4,
        "num_correspondences": 2,
    }
    del decoded
    del keypoints
    gc.collect()
    source.unlink()


def _mapping_with_unknown_endpoint(data: bytes) -> bytes:
    needle = struct.pack("<IIiB", 11, 12, 2, 1)
    offset = data.index(needle)
    return data[: offset + 4] + struct.pack("<I", 99) + data[offset + 8 :]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data[:7] + b"X" + data[8:], "magic"),
        (lambda data: data[:-1], "truncated"),
        (lambda data: data + b"x", "trailing"),
        (_mapping_with_unknown_endpoint, "declared images"),
    ],
)
def test_mapping_input_rejects_malformed(tmp_path, mutation, message):
    path = tmp_path / "bad.pcmapin"
    path.write_bytes(mutation(_mapping_bytes(2)))
    with pytest.raises(ColmapAdapterError, match=message) as caught:
        read_mapping_input(path)
    path.unlink()
    assert caught.value


def test_mapping_input_constructed_records_guard_match_indices():
    camera = MappingCamera(1, 1, 10, 10, np.ones(4, np.float64))
    images = (
        MappingImage(1, 1, 2, "a", np.zeros((1, 2), np.float32)),
        MappingImage(2, 1, 2, "b", np.zeros((1, 2), np.float32)),
    )
    match = MappingMatch(1, 2, 1, np.array([[1, 0]], np.uint32))
    with pytest.raises(ColmapAdapterError, match="exceeds"):
        MappingInput(2, (camera,), images, (match,))
    with pytest.raises(ColmapAdapterError, match="positive"):
        MappingCamera(0, 1, 10, 10, np.ones(4, np.float64))
    with pytest.raises(ColmapAdapterError, match="positive"):
        MappingImage(0, 1, 2, "a", np.zeros((0, 2), np.float32))
    with pytest.raises(ColmapAdapterError, match=r"0\.\.9"):
        MappingMatch(1, 2, 10, np.empty((0, 2), np.uint32))


def test_mapping_input_empty_arrays_and_v1_time_guard(
    tmp_path,
    monkeypatch,
):
    camera = MappingCamera(1, 1, 10, 10, np.ones(4, np.float64))
    images = (
        MappingImage(
            1,
            1,
            UINT32_MAX,
            "empty-left.png",
            np.empty((0, 2), np.float32),
        ),
        MappingImage(
            2,
            1,
            UINT32_MAX,
            "empty-right.png",
            np.empty((0, 2), np.float32),
        ),
    )
    matches = (
        MappingMatch(
            1,
            2,
            0,
            np.empty((0, 2), np.uint32),
        ),
    )
    value = MappingInput(1, (camera,), images, matches)
    path = tmp_path / "empty-v1.pcmapin"
    write_mapping_input(value, path)
    decoded = read_mapping_input(path)
    assert decoded.images[0].keypoints.shape == (0, 2)
    assert decoded.matches[0].matches.shape == (0, 2)

    lossy = MappingInput(
        1,
        (camera,),
        (
            MappingImage(
                1,
                1,
                7,
                "timed.png",
                np.empty((0, 2), np.float32),
            ),
        ),
        (),
    )
    with pytest.raises(ColmapAdapterError, match="v1 cannot represent"):
        write_mapping_input(lossy, tmp_path / "lossy-v1.pcmapin")

    monkeypatch.setattr(mapping_input_module, "_MAX_TEXT_BYTES", 3)
    oversized_name = MappingInput(
        1,
        (camera,),
        (
            MappingImage(
                1,
                1,
                UINT32_MAX,
                "éé",
                np.empty((0, 2), np.float32),
            ),
        ),
        (),
    )
    oversized_path = tmp_path / "oversized-name.pcmapin"
    with pytest.raises(ColmapAdapterError, match="name exceeds"):
        write_mapping_input(oversized_name, oversized_path)
    assert not oversized_path.exists()


def test_mapping_input_mapped_read_avoids_file_sized_python_copy(tmp_path):
    path = tmp_path / "large.pcmapin"
    keypoint_count = 1_000_000
    with path.open("wb") as stream:
        stream.write(struct.pack("<8sII", b"PCMAPIN\0", 2, 1))
        stream.write(struct.pack("<IIQQI", 1, 1, 640, 480, 4))
        stream.write(struct.pack("<4dB", 500, 500, 320, 240, 0))
        stream.write(struct.pack("<I", 1))
        stream.write(struct.pack("<III", 1, 1, 2))
        stream.write(struct.pack("<I", 1) + b"a")
        stream.write(struct.pack("<I", keypoint_count))
        zero_chunk = b"\0" * (1 << 20)
        remaining = keypoint_count * 2 * 4
        while remaining >= len(zero_chunk):
            stream.write(zero_chunk)
            remaining -= len(zero_chunk)
        stream.write(zero_chunk[:remaining])
        stream.write(struct.pack("<I", 0))
    tracemalloc.start()
    value = read_mapping_input(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert value.images[0].keypoints.shape == (keypoint_count, 2)
    assert peak < path.stat().st_size // 2


def _megaloc_fixture(root: Path) -> np.ndarray:
    descriptors = np.array([[1.0, 2.0], [3.5, 4.5]], dtype="<f4")
    descriptors[0, 0] = np.nan
    (root / "descriptors.f32").write_bytes(descriptors.tobytes())
    (root / "pairs.txt").write_text("a.png b.png\n", encoding="utf-8")
    (root / "pairs.tsv").write_text(
        "image_id1\timage_id2\tscore\tis_retrieval\tis_sequential\t"
        "image_name1\timage_name2\n"
        "1\t2\t0.75\t1\t0\ta.png\tb.png\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "colmap.megaloc.artifacts",
        "schema_version": 1,
        "image_root": "images",
        "images": [
            {"image_id": 1, "image_name": "a.png", "image_path": "images/a.png"},
            {"image_id": 2, "image_name": "b.png", "image_path": "images/b.png"},
        ],
        "descriptors": {
            "file": "descriptors.f32",
            "dtype": "float32_le",
            "layout": "row_major",
            "rows": 2,
            "cols": 2,
            "normalized": False,
        },
        "pairs": {
            "colmap_file": "pairs.txt",
            "scores_file": "pairs.tsv",
            "count": 1,
            "scores_columns": [
                "image_id1",
                "image_id2",
                "score",
                "is_retrieval",
                "is_sequential",
                "image_name1",
                "image_name2",
            ],
        },
        "model": {"onnx_path": None, "engine_path": "engine.plan"},
        "metadata": {"producer": "independent-fixture"},
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return descriptors


def test_megaloc_independent_directory_roundtrip_and_mapped_lifetime(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    expected = _megaloc_fixture(source)
    value = read_megaloc_artifacts(source)
    np.testing.assert_array_equal(value.descriptors, expected)
    assert not value.descriptors.flags.writeable
    descriptors = value.descriptors
    del value
    gc.collect()
    np.testing.assert_array_equal(descriptors, expected)
    loaded = read_megaloc_artifacts(source)
    target = tmp_path / "target"
    write_megaloc_artifacts(loaded, target)
    actual = read_megaloc_artifacts(target)
    np.testing.assert_array_equal(actual.descriptors, expected)
    assert (target / "descriptors.f32").read_bytes() == (
        source / "descriptors.f32"
    ).read_bytes()
    assert actual.images == loaded.images
    assert actual.pairs == loaded.pairs
    assert inspect_megaloc_artifacts(target) == {
        "num_images": 2,
        "num_pairs": 1,
        "has_descriptors": True,
        "descriptor_rows": 2,
        "descriptor_columns": 2,
    }
    del descriptors
    del loaded
    gc.collect()
    (source / "descriptors.f32").unlink()


def test_megaloc_descriptor_mapping_avoids_file_sized_python_copy(tmp_path):
    columns = 2_000_000
    (tmp_path / "descriptors.f32").write_bytes(b"\0" * (columns * 4))
    (tmp_path / "pairs.txt").write_bytes(b"")
    (tmp_path / "pairs.tsv").write_text(
        "image_id1\timage_id2\tscore\tis_retrieval\tis_sequential\timage_name1\timage_name2\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "colmap.megaloc.artifacts",
                "schema_version": 1,
                "images": [{"image_id": 1, "image_name": "a", "image_path": "a"}],
                "descriptors": {
                    "file": "descriptors.f32",
                    "dtype": "float32_le",
                    "layout": "row_major",
                    "rows": 1,
                    "cols": columns,
                    "normalized": False,
                },
                "pairs": {
                    "colmap_file": "pairs.txt",
                    "scores_file": "pairs.tsv",
                    "count": 0,
                    "scores_columns": [
                        "image_id1",
                        "image_id2",
                        "score",
                        "is_retrieval",
                        "is_sequential",
                        "image_name1",
                        "image_name2",
                    ],
                },
                "metadata": {},
                "model": {},
            }
        ),
        encoding="utf-8",
    )
    tracemalloc.start()
    value = read_megaloc_artifacts(tmp_path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert value.descriptors.shape == (1, columns)
    assert peak < (tmp_path / "descriptors.f32").stat().st_size // 2
    target = tmp_path / "write-output"
    tracemalloc.start()
    write_megaloc_artifacts(value, target)
    _, write_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert write_peak < (tmp_path / "descriptors.f32").stat().st_size // 2


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 2, "schema/version"),
        ("descriptors.file", "../escape.f32", "stay within"),
        ("descriptors.file", "pairs.tsv", "paths must be distinct"),
        ("descriptors.rows", 3, "dimensions"),
        ("descriptors.normalized", "bad", "normalized flag"),
        ("unknown", 1, "unknown fields"),
        (
            "images",
            [
                {"image_id": 1, "image_name": "a.png", "image_path": "a.png"},
                {"image_id": 1, "image_name": "b.png", "image_path": "b.png"},
            ],
            "image ids must be unique",
        ),
    ],
)
def test_megaloc_rejects_manifest_disagreement(tmp_path, field, value, message):
    _megaloc_fixture(tmp_path)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if "." in field:
        parent, child = field.split(".")
        manifest[parent][child] = value
    else:
        manifest[field] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ColmapAdapterError, match=message) as caught:
        read_megaloc_artifacts(tmp_path)
    (tmp_path / "descriptors.f32").unlink()
    assert caught.value


def test_megaloc_empty_descriptor_and_default_overwrite_guard(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    (root / "descriptors.f32").write_bytes(b"")
    (root / "pairs.txt").write_bytes(b"")
    (root / "pairs.tsv").write_text(
        "image_id1\timage_id2\tscore\tis_retrieval\tis_sequential\timage_name1\timage_name2\n",
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "colmap.megaloc.artifacts",
                "schema_version": 1,
                "images": [],
                "descriptors": {
                    "file": "descriptors.f32",
                    "dtype": "float32_le",
                    "layout": "row_major",
                    "rows": 0,
                    "cols": 0,
                    "normalized": False,
                },
                "pairs": {
                    "colmap_file": "pairs.txt",
                    "scores_file": "pairs.tsv",
                    "count": 0,
                    "scores_columns": [
                        "image_id1",
                        "image_id2",
                        "score",
                        "is_retrieval",
                        "is_sequential",
                        "image_name1",
                        "image_name2",
                    ],
                },
                "metadata": {},
                "model": {},
            }
        ),
        encoding="utf-8",
    )
    value = read_megaloc_artifacts(root)
    assert value.descriptors.shape == (0, 0)
    output = tmp_path / "empty-output"
    write_megaloc_artifacts(value, output)
    assert read_megaloc_artifacts(output).descriptors.shape == (0, 0)
    assert inspect_megaloc_artifacts(output)["descriptor_columns"] == 0
    with pytest.raises(ColmapAdapterError, match="already exist"):
        write_megaloc_artifacts(value, output)

    zero_width = MegaLocArtifacts(
        tmp_path,
        (MegaLocImage(1, "one.png", "images/one.png"),),
        (),
        np.empty((1, 0), np.float32),
        False,
        {},
    )
    zero_width_output = tmp_path / "zero-width-output"
    write_megaloc_artifacts(zero_width, zero_width_output)
    assert read_megaloc_artifacts(zero_width_output).descriptors.shape == (1, 0)
    with pytest.raises(ColmapAdapterError, match="dimensions"):
        MegaLocArtifacts(
            tmp_path,
            (),
            (),
            np.empty((0, 1_000_000_001), np.float32),
            False,
            {},
        )
    header = (root / "pairs.tsv").read_text(encoding="utf-8")
    (root / "pairs.tsv").write_text(
        header + "x" * ((1 << 20) + 1),
        encoding="utf-8",
    )
    with pytest.raises(ColmapAdapterError, match="exceeds its bound"):
        read_megaloc_artifacts(root)
    (root / "pairs.tsv").write_text(header, encoding="utf-8")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["descriptors"]["cols"] = 1_000_000_001
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ColmapAdapterError, match="dimensions"):
        read_megaloc_artifacts(root)


def _pack_string(value: str) -> bytes:
    encoded = value.encode()
    return struct.pack("<Q", len(encoded)) + encoded


def test_sparse_binary_sidecars_match_hand_packed_wire(tmp_path):
    (tmp_path / "markers.bin").write_bytes(
        struct.pack("<QIBB", 1, 3, 2, 1)
        + _pack_string("GCP é")
        + struct.pack("<12dQ", *range(1, 13), 9)
    )
    (tmp_path / "marker_projections.bin").write_bytes(
        struct.pack("<QII3dBI", 1, 3, 11, 10.5, 20.5, 4.0, 1, 7)
    )
    (tmp_path / "points3D_frames.bin").write_bytes(
        struct.pack("<8sIQ2Q", b"PT3DFRM\0", 1, 1, 9, 31)
    )
    (tmp_path / "image_times.bin").write_bytes(struct.pack("<8sIQ2Q", b"IMGTIMS\0", 1, 1, 11, 41))
    (tmp_path / "time_frames.bin").write_bytes(
        struct.pack("<8sIQQd", b"TIMFRMS\0", 1, 1, 41, 12.5)
        + _pack_string("sync")
        + _pack_string("take one")
    )
    board = _pack_string("board") + struct.pack("<iii2d", 0, 7, 5, 0.04, 0.02)
    (tmp_path / "charuco_boards.bin").write_bytes(struct.pack("<8sIQ", b"CHBORDS\0", 1, 1) + board)
    calibration = (
        _pack_string("session")
        + board
        + struct.pack("<iiiQ4ddQ", 1, 640, 480, 4, 500, 501, 320, 240, 0.25, 1)
        + _pack_string("left/é.png")
        + struct.pack("<8d", 0.3, 1, 0, 0, 0, 1, 2, 3)
    )
    (tmp_path / "charuco_calibrations.bin").write_bytes(
        struct.pack("<8sIQ", b"CHCALIB\0", 1, 1) + calibration
    )
    value = read_sparse_extensions(tmp_path, encoding="binary")
    assert value.markers[0].label == "GCP é"
    assert value.marker_projections[0].point2D_idx == 7
    assert value.image_times.tags.tolist() == [41]
    assert value.point3D_frames.ids.tolist() == [9]
    assert value.time_frames[0].label == "take one"
    assert value.charuco_boards[0] == CharucoBoard("board", 0, 7, 5, 0.04, 0.02)
    assert value.charuco_calibrations[0].image_names == ("left/é.png",)

    expected = {path.name: path.read_bytes() for path in tmp_path.glob("*.bin")}
    base = tmp_path / "base"
    base.mkdir()
    _write_text_sparse_base(base)
    (base / "images.txt").write_text(
        "11 1 0 0 0 0 0 0 1 left.png\n"
        + " ".join(["0 0 -1"] * 7 + ["10 20 9"])
        + "\n",
        encoding="utf-8",
    )
    (base / "points3D.txt").write_text(
        "9 1 2 3 4 5 6 0.1 11 7\n",
        encoding="utf-8",
    )
    reconstruction = _core.read_colmap_txt(str(base))
    target = tmp_path / "模型-binary-output"
    write_extended_sparse_model(
        ExtendedSparseModel(reconstruction, value, "binary"),
        target,
    )
    for name, payload in expected.items():
        assert (target / name).read_bytes() == payload


def test_sparse_tag_mapping_has_only_owned_array_peak(tmp_path):
    count = 500_000
    path = tmp_path / "image_times.bin"
    with path.open("wb") as stream:
        stream.write(struct.pack("<8sIQ", b"IMGTIMS\0", 1, count))
        block = np.empty((65_536, 2), dtype="<u8")
        emitted = 0
        while emitted < count:
            size = min(block.shape[0], count - emitted)
            block[:size, 0] = np.arange(emitted, emitted + size, dtype=np.uint64)
            block[:size, 1] = 7
            stream.write(memoryview(block[:size]).cast("B"))
            emitted += size
    tracemalloc.start()
    value = read_sparse_extensions(tmp_path, encoding="binary")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert value.image_times.ids.shape == (count,)
    assert peak < int(path.stat().st_size * 1.75)


def _write_text_sparse_base(root: Path) -> None:
    (root / "cameras.txt").write_text("1 PINHOLE 640 480 500 501 320 240\n", encoding="utf-8")
    (root / "images.txt").write_text("11 1 0 0 0 0 0 0 1 left.png\n10 20 9\n", encoding="utf-8")
    (root / "points3D.txt").write_text("9 1 2 3 4 5 6 0.1 11 0\n", encoding="utf-8")


def _write_text_sparse(root: Path) -> None:
    _write_text_sparse_base(root)
    (root / "markers.txt").write_text(
        '3 2 1 "GCP one" 1 2 3 1 0 0 0 1 0 0 0 1 9\n',
        encoding="utf-8",
    )
    (root / "marker_projections.txt").write_text("3 11 10.5 20.5 4 1 0\n", encoding="utf-8")
    (root / "points3D_frames.txt").write_text("9 31\n", encoding="utf-8")
    (root / "image_times.txt").write_text("11 41\n", encoding="utf-8")
    (root / "time_frames.txt").write_text('41 12.5 "sync group" "take one"\n', encoding="utf-8")
    (root / "charuco_boards.txt").write_text('"board" 0 7 5 0.04 0.02\n', encoding="utf-8")
    (root / "charuco_calibrations.txt").write_text(
        '"session" "board" 0 7 5 0.04 0.02 1 640 480 4 '
        '500 501 320 240 0.25 1 "left.png" 0.3 1 0 0 0 1 2 3\n',
        encoding="utf-8",
    )


def test_extended_sparse_text_roundtrip_and_default_guard(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_text_sparse(source)
    with pytest.raises(ValueError, match="sidecar"):
        _core.read_colmap_txt(str(source))
    value = read_extended_sparse_model(source)
    assert value.encoding == "text"
    assert value.extensions.markers[0].point3D_id == 9
    target = tmp_path / "模型-target"
    write_extended_sparse_model(value, target)
    reread = read_extended_sparse_model(target)
    assert reread.extensions.markers[0].label == "GCP one"
    assert reread.extensions.image_times.tags.tolist() == [41]
    assert sorted(path.name for path in target.iterdir()) == sorted(
        path.name for path in source.iterdir()
    )
    with pytest.raises(ColmapAdapterError, match="already contains"):
        write_extended_sparse_model(value, target)

    invalid_projection = replace(
        value.extensions.marker_projections[0],
        point2D_idx=1,
    )
    invalid_extensions = replace(
        value.extensions,
        marker_projections=(invalid_projection,),
    )
    with pytest.raises(ColmapAdapterError, match="exceeds sparse image"):
        write_extended_sparse_model(
            ExtendedSparseModel(
                value.reconstruction,
                invalid_extensions,
                "text",
            ),
            tmp_path / "bad-projection",
        )
    invalid_marker = replace(
        value.extensions.markers[0],
        label="bad\nlabel",
    )
    invalid_extensions = replace(
        value.extensions,
        markers=(invalid_marker,),
    )
    partial_target = tmp_path / "no-partial-target"
    with pytest.raises(ColmapAdapterError, match="line breaks"):
        write_extended_sparse_model(
            ExtendedSparseModel(
                value.reconstruction,
                invalid_extensions,
                "text",
            ),
            partial_target,
        )
    assert not partial_target.exists()


def test_extended_sparse_rejects_mixed_inventory_and_point_disagreement(
    tmp_path,
):
    source = tmp_path / "source"
    source.mkdir()
    _write_text_sparse(source)
    (source / "points3D.txt").write_text(
        (source / "points3D.txt").read_text(encoding="utf-8")
        + "10 2 3 4 4 5 6 0.2\n",
        encoding="utf-8",
    )
    value = read_extended_sparse_model(source)
    marker = replace(value.extensions.markers[0], point3D_id=10)
    invalid_extensions = replace(value.extensions, markers=(marker,))
    with pytest.raises(ColmapAdapterError, match="point3D ids disagree"):
        write_extended_sparse_model(
            ExtendedSparseModel(
                value.reconstruction,
                invalid_extensions,
                "text",
            ),
            tmp_path / "point-disagreement",
        )

    (source / "image_times.bin").write_bytes(b"opposite")
    with pytest.raises(ColmapAdapterError, match="opposite-encoding sidecars"):
        read_extended_sparse_model(source)
    (source / "image_times.bin").unlink()
    (source / "images.bin").write_bytes(b"opposite")
    with pytest.raises(ColmapAdapterError, match="opposite-encoding base"):
        read_extended_sparse_model(source)


@pytest.mark.parametrize(
    ("filename", "payload", "message"),
    [
        ("image_times.bin", b"IMGTIMS\0" + struct.pack("<IQ", 2, 0), "version"),
        ("markers.bin", struct.pack("<Q", 1), "count exceeds"),
        ("marker_projections.bin", struct.pack("<Q", 1) + b"\0" * 36, "count exceeds"),
    ],
)
def test_sparse_sidecars_reject_bad_version_and_truncation(tmp_path, filename, payload, message):
    (tmp_path / filename).write_bytes(payload)
    with pytest.raises(ColmapAdapterError, match=message) as caught:
        read_sparse_extensions(
            tmp_path,
            encoding="binary",
        )
    (tmp_path / filename).unlink()
    assert caught.value


def test_sparse_rejected_record_releases_mapped_file(tmp_path):
    path = tmp_path / "markers.bin"
    path.write_bytes(
        struct.pack("<QIBB", 1, 3, 4, 1)
        + _pack_string("bad")
        + struct.pack("<12dQ", *range(1, 13), 9)
    )
    with pytest.raises(ColmapAdapterError, match="marker_type") as caught:
        read_sparse_extensions(tmp_path, encoding="binary")
    path.unlink()
    assert caught.value


def test_sim3_sift_pairs_caps_and_match_blocks(tmp_path):
    sim3_path = tmp_path / "sim3.txt"
    sim3_path.write_text("2 1 0 0 0 3 4 5\n", encoding="utf-8")
    sim3 = read_similarity_transform(sim3_path)
    output = tmp_path / "sim3-out.txt"
    write_similarity_transform(sim3, output)
    expected_sim3 = SimilarityTransform(
        2.0, np.array([1, 0, 0, 0], np.float64), np.array([3, 4, 5], np.float64)
    )
    actual_sim3 = read_similarity_transform(output)
    assert actual_sim3.scale == expected_sim3.scale
    np.testing.assert_array_equal(actual_sim3.quaternion_wxyz, expected_sim3.quaternion_wxyz)
    np.testing.assert_array_equal(actual_sim3.translation, expected_sim3.translation)

    sift_path = tmp_path / "sift.txt"
    sift_path.write_text(
        "1 128\n1.5 2.5 3.5 4.5 " + " ".join(["1.9", *map(str, range(1, 128))]) + "\n",
        encoding="utf-8",
    )
    sift = read_sift_features(sift_path)
    assert sift.descriptors.dtype == np.uint8
    assert sift.descriptors[0, 0] == 1
    sift_output = tmp_path / "sift-out.txt"
    write_sift_features(sift, sift_output)
    reread = read_sift_features(sift_output)
    np.testing.assert_array_equal(reread.keypoints, sift.keypoints)
    np.testing.assert_array_equal(reread.descriptors, sift.descriptors)

    pair_path = tmp_path / "pairs.txt"
    cap_path = tmp_path / "caps.txt"
    pair_path.write_text("# pairs\na.png b.png\nb.png c.png\n", encoding="utf-8")
    cap_path.write_text("# caps\n100\n50\n", encoding="utf-8")
    pairs, caps = read_image_pairs(pair_path, cap_path=cap_path)
    assert pairs == (("a.png", "b.png"), ("b.png", "c.png"))
    assert read_stock_image_pairs(pair_path) == pairs
    np.testing.assert_array_equal(caps, np.array([100, 50], np.uint32))
    write_image_pairs(
        pairs,
        tmp_path / "pairs-out.txt",
        caps=caps,
        cap_path=tmp_path / "caps-out.txt",
    )

    matches_path = tmp_path / "matches.txt"
    matches_path.write_text("a.png b.png\n0 1\n2 3\n\n", encoding="utf-8")
    matches = read_feature_matches(matches_path)
    expected_matches = NamedMatches(
        "a.png",
        "b.png",
        np.array([[0, 1], [2, 3]], dtype=np.uint32),
    )
    assert (matches[0].image_name1, matches[0].image_name2) == ("a.png", "b.png")
    np.testing.assert_array_equal(matches[0].matches, expected_matches.matches)
    match_output = tmp_path / "matches-out.txt"
    write_feature_matches(matches, match_output)
    np.testing.assert_array_equal(
        read_feature_matches(match_output)[0].matches,
        matches[0].matches,
    )


def test_text_writers_prevalidate_multifile_and_pair_contracts(tmp_path):
    pairs_path = tmp_path / "pairs.txt"
    caps_path = tmp_path / "caps.txt"
    pairs_path.write_text("preserve-pairs\n", encoding="utf-8")
    caps_path.write_text("preserve-caps\n", encoding="utf-8")
    with pytest.raises(ColmapAdapterError, match="int32-range"):
        write_image_pairs(
            (("a", "b"),),
            pairs_path,
            caps=np.array([1 << 31], np.uint32),
            cap_path=caps_path,
        )
    assert pairs_path.read_text(encoding="utf-8") == "preserve-pairs\n"
    assert caps_path.read_text(encoding="utf-8") == "preserve-caps\n"
    with pytest.raises(ColmapAdapterError, match="distinct"):
        write_image_pairs(
            (("a", "b"),),
            pairs_path,
            caps=np.array([1], np.uint32),
            cap_path=pairs_path,
        )

    duplicate_blocks = (
        NamedMatches("a", "b", np.empty((0, 2), np.uint32)),
        NamedMatches("b", "a", np.empty((0, 2), np.uint32)),
    )
    with pytest.raises(ColmapAdapterError, match="duplicate"):
        write_feature_matches(duplicate_blocks, tmp_path / "matches.txt")


@pytest.mark.parametrize(
    ("payload", "reader", "message"),
    [
        ("1 1 0 0 0 0 0 0 0\n", read_similarity_transform, "8 values"),
        ("1 127\n", read_sift_features, "128"),
        ("a a\n", read_image_pairs, "self-pair"),
        ("a b\n1\n", read_feature_matches, "two indices"),
    ],
)
def test_text_adapters_reject_malformed(tmp_path, payload, reader, message):
    path = tmp_path / "bad.txt"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ColmapAdapterError, match=message) as caught:
        reader(path)
    path.unlink()
    assert caught.value


def test_sift_count_is_payload_bounded_and_releases_rejected_file(tmp_path):
    path = tmp_path / "huge-header.txt"
    path.write_text("100000000 128\n", encoding="utf-8")
    with pytest.raises(ColmapAdapterError, match="exceeds the text payload") as caught:
        read_sift_features(path)
    path.unlink()
    assert caught.value


def test_stock_pair_spacing_is_distinct_from_dense_whitespace(tmp_path):
    path = tmp_path / "pairs.txt"
    path.write_text("a.png\tb.png\n", encoding="utf-8")
    assert read_image_pairs(path)[0] == (("a.png", "b.png"),)
    with pytest.raises(ColmapAdapterError, match="ASCII-space"):
        read_stock_image_pairs(path)


def test_rig_config_independent_json_and_guards(tmp_path):
    source = tmp_path / "rig.json"
    source.write_text(
        json.dumps(
            [
                {
                    "cameras": [
                        {"image_prefix": "left/", "ref_sensor": True},
                        {
                            "image_prefix": "right/",
                            "cam_from_rig_rotation": [1, 0, 0, 0],
                            "cam_from_rig_translation": [1, 2, 3],
                            "camera_model_name": "PINHOLE",
                            "camera_params": [500, 501, 320, 240],
                        },
                    ]
                }
            ]
        ),
        encoding="utf-8",
    )
    rigs = read_rig_config(source)
    assert rigs[0].cameras[0].ref_sensor
    output = tmp_path / "rig-out.json"
    write_rig_config(rigs, output)
    reread = read_rig_config(output)
    assert reread[0].cameras[0] == rigs[0].cameras[0]
    assert reread[0].cameras[1].image_prefix == "right/"
    np.testing.assert_array_equal(
        reread[0].cameras[1].cam_from_rig,
        rigs[0].cameras[1].cam_from_rig,
    )

    invalid = (
        RigConfigCamera("left/", True),
        RigConfigCamera("right/", True),
    )
    with pytest.raises(ColmapAdapterError, match="exactly one"):
        RigConfiguration(invalid)


def test_constructed_megaloc_and_sift_types_enforce_wire_dtypes(
    tmp_path,
    monkeypatch,
):
    images = (
        MegaLocImage(1, "a", "a"),
        MegaLocImage(2, "b", "b"),
    )
    pairs = (MegaLocPair(1, 2, 0.5, True, False, "a", "b"),)
    assert np.isnan(MegaLocPair(1, 2, float("nan"), True, False, "a", "b").score)
    with pytest.raises(ColmapAdapterError, match="dtype"):
        MegaLocArtifacts(
            tmp_path,
            images,
            pairs,
            np.ones((2, 2), np.float64),
            False,
            {},
        )
    valid = MegaLocArtifacts(
        tmp_path,
        images,
        pairs,
        np.ones((2, 2), np.float32),
        False,
        {},
    )
    json_bound = megaloc_module._MAX_JSON_BYTES
    monkeypatch.setattr(megaloc_module, "_MAX_JSON_BYTES", 20)
    manifest_bound_root = tmp_path / "manifest-bound"
    with pytest.raises(ColmapAdapterError, match="manifest exceeds"):
        write_megaloc_artifacts(valid, manifest_bound_root)
    assert not manifest_bound_root.exists()
    monkeypatch.setattr(megaloc_module, "_MAX_JSON_BYTES", json_bound)

    line_bound = megaloc_module._MAX_TEXT_LINE
    monkeypatch.setattr(megaloc_module, "_MAX_TEXT_LINE", 100)
    long_name1 = "a" * 60
    long_name2 = "b" * 60
    long_lines = MegaLocArtifacts(
        tmp_path,
        (
            MegaLocImage(1, long_name1, long_name1),
            MegaLocImage(2, long_name2, long_name2),
        ),
        (
            MegaLocPair(
                1,
                2,
                0.5,
                True,
                False,
                long_name1,
                long_name2,
            ),
        ),
        np.ones((2, 2), np.float32),
        False,
        {},
    )
    line_bound_root = tmp_path / "line-bound"
    with pytest.raises(ColmapAdapterError, match="row 0 exceeds"):
        write_megaloc_artifacts(long_lines, line_bound_root)
    assert not line_bound_root.exists()
    monkeypatch.setattr(megaloc_module, "_MAX_TEXT_LINE", line_bound)
    with pytest.raises(ColmapAdapterError, match="paths must be distinct"):
        write_megaloc_artifacts(
            valid,
            tmp_path / "collision",
            descriptor_file="pairs.txt",
        )
    with pytest.raises(ColmapAdapterError, match="keys must be text"):
        MegaLocArtifacts(
            tmp_path,
            images,
            pairs,
            np.ones((2, 2), np.float32),
            False,
            {1: "not-lossless"},
        )
    with pytest.raises(ColmapAdapterError, match="finite JSON"):
        MegaLocArtifacts(
            tmp_path,
            images,
            pairs,
            np.ones((2, 2), np.float32),
            False,
            {"tuple": (1, 2)},
        )
    with pytest.raises(ColmapAdapterError, match="finite-float32"):
        MegaLocPair(1, 2, 1e300, True, False, "a", "b")
    symlink_root = tmp_path / "symlink-root"
    symlink_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (symlink_root / "linked").symlink_to(
            outside,
            target_is_directory=True,
        )
    except (NotImplementedError, OSError):
        pass
    else:
        with pytest.raises(ColmapAdapterError, match="stay within"):
            write_megaloc_artifacts(
                valid,
                symlink_root,
                descriptor_file="linked/descriptors.f32",
            )
        alias_root = tmp_path / "alias-root"
        alias_root.mkdir()
        (alias_root / "real").mkdir()
        (alias_root / "alias").symlink_to(
            alias_root / "real",
            target_is_directory=True,
        )
        with pytest.raises(ColmapAdapterError, match="paths must be distinct"):
            write_megaloc_artifacts(
                valid,
                alias_root,
                descriptor_file="real/shared",
                pair_list_file="alias/shared",
            )
    with pytest.raises(ColmapAdapterError, match="dtype"):
        SiftFeatures(
            np.zeros((1, 4), np.float64),
            np.zeros((1, 128), np.uint8),
        )
    with pytest.raises(ColmapAdapterError, match="model/parameter"):
        RigConfigCamera(
            "camera/",
            camera_model_name="PINHOLE",
            camera_params=np.ones(3, np.float64),
        )


def test_sparse_constructed_wire_domain_guards():
    with pytest.raises(ColmapAdapterError, match="valid uint32"):
        IdTags(
            np.array([1], np.uint64),
            np.array([UINT32_MAX], np.uint64),
        )
    with pytest.raises(ColmapAdapterError, match="at least 2"):
        CharucoBoard("thin", 0, 1, 5, 0.04, 0.02)

    board = CharucoBoard("board", 0, 7, 5, 0.04, 0.02)
    calibration_args = (
        "session",
        board,
        1,
        640,
        480,
        np.array([500, 501, 320, 240], np.float64),
        0.2,
        ("image.png",),
        np.array([0.3], np.float64),
    )
    with pytest.raises(ColmapAdapterError, match="unit length"):
        CharucoCalibration(
            *calibration_args,
            np.zeros((1, 7), np.float64),
        )

    mismatched_board = CharucoBoard("board", 0, 8, 5, 0.04, 0.02)
    calibration = CharucoCalibration(
        "session",
        mismatched_board,
        1,
        640,
        480,
        np.array([500, 501, 320, 240], np.float64),
        0.2,
        ("image.png",),
        np.array([0.3], np.float64),
        np.array([[1, 0, 0, 0, 0, 0, 0]], np.float64),
    )
    with pytest.raises(ColmapAdapterError, match="geometry disagrees"):
        SparseExtensions(
            charuco_boards=(board,),
            charuco_calibrations=(calibration,),
        )
