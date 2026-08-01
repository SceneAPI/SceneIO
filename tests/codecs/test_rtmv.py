"""Parity and boundary tests for the lazy RTMV directory adapter.

The fixture is independently authored from the public RTMV layout: OpenEXR's
Python bindings write every image layer, while NumPy constructs the camera
matrices and expected poses.  No RTMV dataset payload or loader code is used.
"""

from __future__ import annotations

import json
import math
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core

OpenEXR = pytest.importorskip("OpenEXR")


def _write_exr(path: Path, value: float, channels: int = 4) -> np.ndarray:
    height, width = 3, 4
    pixels = np.empty((height, width, channels), np.float32)
    for channel in range(channels):
        pixels[:, :, channel] = value + channel + np.arange(
            height * width,
            dtype=np.float32,
        ).reshape(height, width) / 100.0
    names = "RGBA"[:channels] if channels > 1 else "Y"
    channel_map = {
        name: np.ascontiguousarray(pixels[:, :, index])
        for index, name in enumerate(names)
    }
    header = {
        "compression": OpenEXR.ZIP_COMPRESSION,
        "type": OpenEXR.scanlineimage,
    }
    with OpenEXR.File(header, channel_map) as output:
        output.write(str(path))
    return pixels


def _metadata(index: int) -> dict[str, object]:
    angle = index * 0.2
    cosine, sine = math.cos(angle), math.sin(angle)
    rotation = np.asarray(
        [[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    translation = np.asarray([index + 0.25, -0.5, 2.0], dtype=np.float64)
    c2w = np.eye(4, dtype=np.float64)
    c2w[:3, :3] = rotation
    c2w[:3, 3] = translation
    eye = translation
    target = eye + rotation @ np.asarray([0.0, 0.0, -1.0])
    up = rotation @ np.asarray([0.0, 1.0, 0.0])
    return {
        "camera_data": {
            # RTMV serializes its transform matrices in row-vector form.
            "cam2world": c2w.T.tolist(),
            "camera_view_matrix": np.linalg.inv(c2w).T.tolist(),
            "camera_look_at": {
                "at": target.tolist(),
                "eye": eye.tolist(),
                "up": up.tolist(),
            },
            "width": 4,
            "height": 3,
            "intrinsics": {
                "cx": 2.0,
                "cy": 1.5,
                "fx": 5.0 + index,
                "fy": 5.5 + index,
            },
            "location_world": translation.tolist(),
            "quaternion_world_xyzw": [
                0.0,
                0.0,
                math.sin(angle / 2.0),
                math.cos(angle / 2.0),
            ],
            "scene_center_3d_box": [0.0, 0.0, 0.0],
            "scene_min_3d_box": [-1.0, -2.0, -3.0],
            "scene_max_3d_box": [1.0, 2.0, 3.0],
        },
        "objects": [{"segmentation_id": item + 1} for item in range(index)],
    }


def _fixture(
    root: Path,
    *,
    frames: int = 3,
    segmentation: bool = True,
) -> tuple[Path, dict[str, np.ndarray]]:
    directory = root / "rtmv"
    directory.mkdir()
    expected = {}
    for index in range(frames):
        stem = f"{index:05d}"
        (directory / f"{stem}.json").write_text(
            json.dumps(_metadata(index), separators=(",", ":")),
            encoding="utf-8",
        )
        expected[f"{stem}.exr"] = _write_exr(
            directory / f"{stem}.exr",
            index * 10.0,
        )
        expected[f"{stem}.depth.exr"] = _write_exr(
            directory / f"{stem}.depth.exr",
            index * 10.0 + 100.0,
        )
        if segmentation:
            expected[f"{stem}.seg.exr"] = _write_exr(
                directory / f"{stem}.seg.exr",
                index * 10.0 + 200.0,
            )
    return directory, expected


def _oracle_read(path: Path) -> np.ndarray:
    with OpenEXR.File(str(path)) as source:
        key = next(iter(source.parts[0].channels))
        return np.asarray(source.parts[0].channels[key].pixels)


def test_reads_independent_rtmv_layout_and_preserves_lazy_layers(tmp_path):
    directory, expected = _fixture(tmp_path)
    assert sceneio.detect(directory) == "rtmv"

    dataset = sceneio.read(directory)
    assert isinstance(dataset, sceneio.RtmvDataset)
    assert dataset.root == str(directory.resolve())
    assert dataset.frame_ids == ("00000", "00001", "00002")
    assert dataset.object_counts == (0, 1, 2)
    assert dataset.num_frames == 3 and dataset.has_segmentation
    assert (dataset.height, dataset.width) == (3, 4)
    assert (
        dataset.rgb_channels,
        dataset.depth_channels,
        dataset.segmentation_channels,
    ) == (4, 4, 4)
    assert all(Path(path).is_absolute() for path in dataset.rgb_paths)
    assert dataset.views.pose_convention == "camera_to_world"
    assert dataset.views.axis_frame == "opengl"
    np.testing.assert_allclose(
        np.asarray(dataset.views.translations),
        [[0.25, -0.5, 2.0], [1.25, -0.5, 2.0], [2.25, -0.5, 2.0]],
        atol=1e-12,
    )
    for index, camera in enumerate(dataset.views.cameras):
        assert camera.model == "PINHOLE"
        assert (camera.width, camera.height) == (4, 3)
        np.testing.assert_allclose(
            np.asarray(camera.params),
            [5.0 + index, 5.5 + index, 2.0, 1.5],
        )

    for name, pixels in expected.items():
        np.testing.assert_array_equal(_oracle_read(directory / name), pixels)


def test_inspect_matches_read_without_decoding_pixels(tmp_path, monkeypatch):
    directory, _ = _fixture(tmp_path, frames=2)

    def fail_decode(_source):
        raise AssertionError("RTMV inspection/read must not decode EXR pixels")

    monkeypatch.setattr(_core, "read_exr", fail_decode)
    info = sceneio.inspect(directory)
    dataset = sceneio.read(directory)
    assert info.format == "rtmv"
    assert info.datatype == "rtmv_dataset"
    assert info.shape == (2, 3, 4, 4)
    assert info.dtype == "float32" and info.channels == 4
    assert info.count == dataset.num_frames == 2
    assert info.byte_size == sum(path.stat().st_size for path in directory.iterdir())
    assert dict(info.metadata) == {
        "storage_mode": "encoded_paths",
        "pose_convention": "camera_to_world",
        "axis_frame": "opengl",
        "depth_channels": 4,
        "segmentation_channels": 4,
        "has_segmentation": True,
        "frame_ids": ("00000", "00001"),
        "object_counts": (0, 1),
    }


def test_partial_read_is_exact_slice_of_full_read(tmp_path):
    directory, _ = _fixture(tmp_path, frames=4)
    full = sceneio.read(directory)
    selected = sceneio.read_partial(directory, frames=(1, 3))
    assert selected.frame_ids == full.frame_ids[1:3]
    assert selected.metadata_paths == full.metadata_paths[1:3]
    assert selected.rgb_paths == full.rgb_paths[1:3]
    assert selected.depth_paths == full.depth_paths[1:3]
    assert selected.segmentation_paths == full.segmentation_paths[1:3]
    assert selected.object_counts == full.object_counts[1:3]
    np.testing.assert_array_equal(
        np.asarray(selected.views.quaternions),
        np.asarray(full.views.quaternions)[1:3],
    )
    np.testing.assert_array_equal(
        np.asarray(selected.views.translations),
        np.asarray(full.views.translations)[1:3],
    )
    assert [tuple(camera.params) for camera in selected.views.cameras] == [
        tuple(camera.params) for camera in full.views.cameras[1:3]
    ]


def test_optional_segmentation_is_all_or_none(tmp_path):
    directory, _ = _fixture(tmp_path, frames=2, segmentation=False)
    dataset = sceneio.read(directory)
    assert not dataset.has_segmentation
    assert dataset.segmentation_paths == ()
    assert dataset.segmentation_channels == 0

    _write_exr(directory / "00000.seg.exr", 200.0)
    with pytest.raises(sceneio.FormatError, match="segmentation must be present"):
        sceneio.read(directory)


def test_large_encoded_layers_are_not_materialized(tmp_path):
    directory, _ = _fixture(tmp_path, frames=1)
    target_size = 16 * 1024 * 1024
    for path in directory.glob("*.exr"):
        with path.open("r+b") as stream:
            stream.seek(target_size - 1)
            stream.write(b"\0")
    encoded_size = sum(path.stat().st_size for path in directory.glob("*.exr"))
    assert encoded_size == 3 * target_size

    tracemalloc.start()
    dataset = sceneio.read(directory)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert dataset.num_frames == 1
    assert peak < 2 * 1024 * 1024
    assert peak < encoded_size / 20


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("width", 0, "positive integer"),
        ("intrinsics.fx", 0.0, "focal lengths"),
        ("intrinsics.cx", 9.0, "principal point"),
        ("quaternion_world_xyzw", [0.0, 0.0, 0.0, 2.0], "normalized"),
        ("location_world", [9.0, 0.0, 0.0], "location_world disagrees"),
    ],
)
def test_rejects_inconsistent_camera_metadata(tmp_path, field, value, message):
    directory, _ = _fixture(tmp_path, frames=1)
    path = directory / "00000.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    camera = document["camera_data"]
    if field.startswith("intrinsics."):
        camera["intrinsics"][field.split(".")[1]] = value
    else:
        camera[field] = value
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read(directory)


def test_rejects_duplicate_json_keys_and_unexpected_layout_entries(tmp_path):
    directory, _ = _fixture(tmp_path, frames=1)
    metadata = directory / "00000.json"
    payload = metadata.read_text(encoding="utf-8")
    metadata.write_text(
        payload.replace('"width":4', '"width":4,"width":4'),
        encoding="utf-8",
    )
    with pytest.raises(sceneio.FormatError, match="duplicate JSON key 'width'"):
        sceneio.read(directory)

    document = _metadata(0)
    document["camera_data"]["camera_look_at"]["at"] = [1.0, 0.0, 0.0]
    metadata.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="look direction disagrees"):
        sceneio.read(directory)

    document = _metadata(0)
    document["camera_data"]["camera_look_at"]["up"] = [1.0, 0.0, 0.0]
    metadata.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="up direction disagrees"):
        sceneio.read(directory)

    metadata.write_text(json.dumps(_metadata(0)), encoding="utf-8")
    (directory / "notes.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="unexpected file"):
        sceneio.read(directory)


def test_rejects_missing_and_noncontiguous_frames(tmp_path):
    directory, _ = _fixture(tmp_path, frames=2)
    (directory / "00001.depth.exr").unlink()
    with pytest.raises(sceneio.FormatError, match="missing required layer"):
        sceneio.read(directory)

    for path in tuple(directory.glob("00001*")):
        path.rename(path.with_name(path.name.replace("00001", "00002")))
    with pytest.raises(sceneio.FormatError, match="contiguous from 00000"):
        sceneio.read(directory)


def test_partial_bounds_and_read_only_contract(tmp_path):
    directory, _ = _fixture(tmp_path, frames=2)
    with pytest.raises(sceneio.FormatError, match="range is out of bounds"):
        sceneio.read_partial(directory, frames=(1, 3))
    dataset = sceneio.read(directory)
    with pytest.raises(sceneio.FormatError, match="read-only"):
        sceneio.write(dataset, tmp_path / "copy", format="rtmv")
