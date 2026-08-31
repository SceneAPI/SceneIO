"""Public canonical posed-view I/O across every pose codec."""

from __future__ import annotations

import json

import numpy as np
import pytest

import sceneio
from sceneio import FrameMeta


def _metric_frame() -> FrameMeta:
    return FrameMeta(world_frame="arbitrary", scale="metric")


def test_tum_public_io_is_canonical_and_reemits_unchanged_values(tmp_path) -> None:
    source = tmp_path / "trajectory.txt"
    source.write_bytes(b"1.25 1 2 3 0 0 0 1\n")
    views = sceneio.read(source, format="tum")
    assert isinstance(views, sceneio.PosedViewSet)
    assert type(views) is not sceneio._core.PoseStorage
    assert views.timestamps == (1.25,)
    assert views.poses[0].convention == "opencv_cam2world"
    np.testing.assert_array_equal(views.poses[0].translation, [1.0, 2.0, 3.0])

    output = tmp_path / "roundtrip.txt"
    sceneio.write(views, output, format="tum")
    assert output.read_bytes() == source.read_bytes()


def test_pose_mutation_invalidates_the_exact_source_cache(tmp_path) -> None:
    source = tmp_path / "trajectory.txt"
    source.write_bytes(b"1.25 1 2 3 0 0 0 1\n")
    views = sceneio.read(source, format="tum")
    views.poses[0].translation[0] = 9.0

    output = tmp_path / "updated.txt"
    sceneio.write(views, output, format="tum")

    assert output.read_bytes() != source.read_bytes()
    recovered = sceneio.read(output, format="tum")
    np.testing.assert_array_equal(
        recovered.poses[0].translation,
        [9.0, 2.0, 3.0],
    )


def test_kitti_public_io_is_canonical(tmp_path) -> None:
    source = tmp_path / "poses.txt"
    source.write_bytes(b"1 0 0 4 0 1 0 5 0 0 1 6\n")
    views = sceneio.read(source, format="kitti")
    assert views.names == (None,)
    assert views.timestamps == (None,)
    np.testing.assert_array_equal(views.poses[0].matrix[:3, 3], [4.0, 5.0, 6.0])

    output = tmp_path / "copy.txt"
    sceneio.write(views, output, format="kitti")
    recovered = sceneio.read(output, format="kitti")
    np.testing.assert_allclose(recovered.poses[0].matrix, views.poses[0].matrix)


def test_transforms_json_normalizes_axes_and_preserves_calibration(tmp_path) -> None:
    source = tmp_path / "transforms.json"
    source.write_text(
        json.dumps(
            {
                "camera_model": "PINHOLE",
                "fl_x": 500.0,
                "fl_y": 510.0,
                "cx": 320.0,
                "cy": 240.0,
                "w": 640,
                "h": 480,
                "frames": [
                    {
                        "file_path": "images/a.png",
                        "transform_matrix": np.eye(4).tolist(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    views = sceneio.read(source)
    assert views.names == ("images/a.png",)
    assert views.calibrations[0] is not None
    assert views.calibrations[0].intrinsics.model == "PINHOLE"
    np.testing.assert_array_equal(
        views.poses[0].rotation,
        np.diag([1.0, -1.0, -1.0]),
    )

    output = tmp_path / "copy.json"
    sceneio.write(views, output, format="transforms_json")
    recovered = sceneio.read(output, format="transforms_json")
    np.testing.assert_allclose(recovered.poses[0].matrix, views.poses[0].matrix)
    np.testing.assert_array_equal(
        recovered.calibrations[0].intrinsics.params,
        views.calibrations[0].intrinsics.params,
    )


def test_unchanged_duplicate_calibrations_preserve_per_frame_storage(tmp_path) -> None:
    identity = np.eye(4).tolist()
    calibration = {
        "camera_model": "PINHOLE",
        "fl_x": 500.0,
        "fl_y": 510.0,
        "cx": 320.0,
        "cy": 240.0,
        "w": 640,
        "h": 480,
    }
    source = tmp_path / "per-frame.json"
    source.write_text(
        json.dumps(
            {
                "frames": [
                    {
                        "file_path": f"images/{index}.png",
                        "transform_matrix": identity,
                        **calibration,
                    }
                    for index in range(2)
                ]
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "copy.json"
    sceneio.write(
        sceneio.read(source, format="transforms_json"),
        output,
        format="transforms_json",
    )

    encoded = json.loads(output.read_text(encoding="utf-8"))
    assert "fl_x" not in encoded
    assert [frame["fl_x"] for frame in encoded["frames"]] == [500.0, 500.0]


def test_new_canonical_pose_set_writes_tum_and_refuses_loss(tmp_path) -> None:
    views = sceneio.PosedViewSet(
        poses=(
            sceneio.SE3(
                np.eye(3),
                np.array([1.0, 2.0, 3.0]),
                convention="opencv_cam2world",
            ),
        ),
        frame=_metric_frame(),
        timestamps=(2.5,),
    )
    output = tmp_path / "new.txt"
    sceneio.write(views, output, format="tum")
    recovered = sceneio.read(output, format="tum")
    np.testing.assert_allclose(recovered.poses[0].matrix, views.poses[0].matrix)
    assert recovered.timestamps == (2.5,)

    named = sceneio.PosedViewSet(
        poses=views.poses,
        frame=views.frame,
        names=("image.png",),
    )
    with pytest.raises(sceneio.FormatError, match=r"cannot represent PosedViewSet\.names"):
        sceneio.write(named, tmp_path / "lossy.txt", format="tum")
