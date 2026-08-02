"""Generate the compact standard-profile fixture with pinned upstream NCore."""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

UPSTREAM_REVISION = "12f4429522c98356c5a46eee1d84f29bd846e367"
OUTPUT_STEM = "ncore_v4_standard_v1"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    return parser.parse_args()


def _verify_revision(upstream: Path) -> None:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=upstream,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != UPSTREAM_REVISION:
        raise RuntimeError(
            f"expected NCore {UPSTREAM_REVISION}, found {revision}"
        )


def _generate(upstream: Path, output_directory: Path) -> Path:
    sys.path.insert(0, str(upstream.resolve()))
    from ncore.impl.common.transformations import (
        HalfClosedInterval,
    )
    from ncore.impl.data.types import (
        BBox3,
        CameraLabelDescriptor,
        CuboidTrackObservation,
        IdealPinholeCameraModelParameters,
        LabelEncoding,
        LabelSchema,
        LabelSource,
        LabelType,
        PointCloud,
        QuantizationParams,
        RowOffsetStructuredSpinningLidarModelParameters,
        ShutterType,
    )
    from ncore.impl.data.v4.components import (
        CameraLabelsComponent,
        CameraSensorComponent,
        CuboidsComponent,
        IntrinsicsComponent,
        LidarSensorComponent,
        MasksComponent,
        PointCloudsComponent,
        PosesComponent,
        RadarSensorComponent,
        SequenceComponentGroupsReader,
        SequenceComponentGroupsWriter,
    )
    from upath import UPath

    output_directory.mkdir(parents=True, exist_ok=True)
    target = output_directory / f"{OUTPUT_STEM}.ncore4.zarr.itar"
    if target.exists():
        raise FileExistsError(f"refusing to replace existing fixture {target}")
    writer = SequenceComponentGroupsWriter(
        UPath(output_directory.resolve()),
        OUTPUT_STEM,
        "sceneio-oracle-v1",
        HalfClosedInterval(100, 200),
        {"source": "pinned-upstream-ncore"},
        store_type="itar",
    )

    poses = writer.register_component_writer(PosesComponent.Writer, "rig")
    static = np.eye(4, dtype=np.float32)
    static[0, 3] = 2
    trajectory = np.stack((np.eye(4), np.eye(4))).astype(np.float64)
    trajectory[1, 1, 3] = 3
    poses.store_static_pose("camera", "rig", static).store_dynamic_pose(
        "rig",
        "world",
        trajectory,
        np.array([100, 199], dtype=np.uint64),
    )

    intrinsics = writer.register_component_writer(
        IntrinsicsComponent.Writer, "default"
    )
    intrinsics.store_camera_intrinsics(
        "front",
        IdealPinholeCameraModelParameters(
            resolution=np.array([3, 2], dtype=np.uint64),
            shutter_type=ShutterType.GLOBAL,
            principal_point=np.array([1.5, 1], dtype=np.float32),
            focal_length=np.array([4, 4], dtype=np.float32),
        ),
    )
    intrinsics.store_lidar_intrinsics(
        "top",
        RowOffsetStructuredSpinningLidarModelParameters(
            spinning_frequency_hz=10.0,
            spinning_direction="ccw",
            n_rows=2,
            n_columns=3,
            row_elevations_rad=np.array([0.2, -0.2], dtype=np.float32),
            column_azimuths_rad=np.array([-1, 0, 1], dtype=np.float32),
            row_azimuth_offsets_rad=np.array([0, 0.01], dtype=np.float32),
        ),
    )

    masks = writer.register_component_writer(MasksComponent.Writer, "default")
    masks.store_camera_masks(
        "front",
        {
            "valid": Image.fromarray(
                np.array([[0, 255], [255, 0]], dtype=np.uint8)
            )
        },
    )
    with io.BytesIO() as buffer:
        Image.fromarray(np.full((2, 3, 3), 64, dtype=np.uint8)).save(
            buffer, format="PNG"
        )
        encoded_image = buffer.getvalue()
    camera = writer.register_component_writer(
        CameraSensorComponent.Writer, "front"
    )
    camera.store_frame(
        encoded_image,
        "png",
        np.array([100, 120], dtype=np.uint64),
        {"gain": np.array([2], dtype=np.int16)},
        {"exposure": 10},
    )

    direction = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    timestamps = np.array([105, 118], dtype=np.uint64)
    distance = np.array([[1, 2], [3, np.nan]], dtype=np.float32)
    intensity = np.array([[0.1, 0.2], [0.3, np.nan]], dtype=np.float32)
    lidar = writer.register_component_writer(LidarSensorComponent.Writer, "top")
    lidar.store_frame(
        direction,
        timestamps,
        np.array([[0, 1], [1, 1]], dtype=np.uint16),
        distance,
        intensity,
        np.array([100, 120], dtype=np.uint64),
        {},
        {},
    )
    radar = writer.register_component_writer(
        RadarSensorComponent.Writer, "radar"
    )
    radar.store_frame(
        direction,
        timestamps,
        distance,
        np.array([100, 120], dtype=np.uint64),
        {},
        {},
    )

    cuboids = writer.register_component_writer(CuboidsComponent.Writer, "default")
    cuboids.store_observations(
        [
            CuboidTrackObservation(
                "car-7",
                "vehicle",
                130,
                "rig",
                125,
                BBox3(
                    (1.0, 2.0, 3.0),
                    (4.0, 2.0, 1.5),
                    (0.0, 0.0, 0.2),
                ),
                LabelSource.GT_ANNOTATION,
                "v2",
            )
        ]
    )
    attribute_schemas = {
        "confidence": PointCloudsComponent.AttributeSchema(
            PointCloud.AttributeTransformType.INVARIANT,
            np.dtype("float32"),
            (),
        )
    }
    point_clouds = writer.register_component_writer(
        PointCloudsComponent.Writer,
        "native",
        None,
        None,
        PointCloud.CoordinateUnit.METERS,
        attribute_schemas,
    )
    for index, timestamp in enumerate((150, 120, 150)):
        point_clouds.store_pc(
            np.array(
                [[index, 0, 1], [index, 2, 3]],
                dtype=np.float32,
            ),
            "rig",
            timestamp,
            {"confidence": np.array([0.5, 0.75], dtype=np.float32)},
            {"extra": np.array([index], dtype=np.int16)},
            {"index": index},
        )

    descriptor = CameraLabelDescriptor(
        "front",
        LabelType.DEPTH_Z_M,
        LabelSchema(
            np.dtype("float32"),
            (),
            LabelEncoding.RAW,
            None,
            QuantizationParams(np.dtype("uint16"), 0.01, 0.0),
        ),
        LabelSource.GT_SYNTHETIC,
    )
    labels = writer.register_component_writer(
        CameraLabelsComponent.Writer,
        "depth@front",
        None,
        None,
        descriptor,
    )
    labels.store_label(
        np.full((2, 3), 1.0, dtype=np.float32), 120, {"frame": 120}
    )
    labels.store_label(
        np.full((2, 3), 2.5, dtype=np.float32), 160, {"frame": 160}
    )

    paths = writer.finalize()
    if paths != [UPath(target.resolve())]:
        raise RuntimeError(f"upstream writer returned unexpected paths: {paths}")
    reader = SequenceComponentGroupsReader(paths)
    if reader.sequence_id != "sceneio-oracle-v1":
        raise RuntimeError("upstream reader did not accept the generated sequence")
    pose_reader = reader.open_component_readers(PosesComponent.Reader)["rig"]
    if len(tuple(pose_reader.get_static_poses())) != 1:
        raise RuntimeError("upstream pose reader disagrees with the fixture")
    intrinsic_reader = reader.open_component_readers(IntrinsicsComponent.Reader)[
        "default"
    ]
    if intrinsic_reader.get_camera_model_parameters("front").resolution.tolist() != [
        3,
        2,
    ]:
        raise RuntimeError("upstream intrinsic reader disagrees with the fixture")
    mask_reader = reader.open_component_readers(MasksComponent.Reader)["default"]
    if mask_reader.get_camera_mask_names("front") != ["valid"]:
        raise RuntimeError("upstream mask reader disagrees with the fixture")
    camera_reader = reader.open_component_readers(CameraSensorComponent.Reader)[
        "front"
    ]
    if camera_reader.frames_count != 1:
        raise RuntimeError("upstream camera reader disagrees with the fixture")
    lidar_reader = reader.open_component_readers(LidarSensorComponent.Reader)["top"]
    if lidar_reader.get_frame_ray_bundle_count(120) != 2:
        raise RuntimeError("upstream lidar reader disagrees with the fixture")
    radar_reader = reader.open_component_readers(RadarSensorComponent.Reader)[
        "radar"
    ]
    if radar_reader.get_frame_ray_bundle_return_count(120) != 2:
        raise RuntimeError("upstream radar reader disagrees with the fixture")
    cuboid_reader = reader.open_component_readers(CuboidsComponent.Reader)["default"]
    if len(tuple(cuboid_reader.get_observations())) != 1:
        raise RuntimeError("upstream cuboid reader disagrees with the fixture")
    point_reader = reader.open_component_readers(PointCloudsComponent.Reader)["native"]
    if point_reader.pc_timestamps_us.tolist() != [150, 120, 150]:
        raise RuntimeError("upstream point-cloud reader disagrees with the fixture")
    label_reader = reader.open_component_readers(CameraLabelsComponent.Reader)[
        "depth@front"
    ]
    if label_reader.timestamps_us.tolist() != [120, 160]:
        raise RuntimeError("upstream camera-label reader disagrees with the fixture")
    return target


def main() -> int:
    arguments = _arguments()
    upstream = arguments.upstream.resolve()
    _verify_revision(upstream)
    print(_generate(upstream, arguments.output_directory.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
