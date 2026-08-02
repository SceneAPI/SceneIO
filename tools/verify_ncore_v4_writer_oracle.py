"""Validate and time SceneIO NCore V4 output with pinned upstream NCore."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import sceneio

ROOT = Path(__file__).resolve().parents[1]
REVISION = "12f4429522c98356c5a46eee1d84f29bd846e367"
FIXTURE = ROOT / "tests/fixtures/ncore_v4_standard_v1.ncore4.zarr.itar"

_ORACLE_PROGRAM = r"""
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, sys.argv[1])
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
)

manifest = Path(sys.argv[2])
runs = int(sys.argv[3])
declared_manifest = json.loads(manifest.read_text(encoding="utf-8"))


def open_reader():
    return SequenceComponentGroupsReader([manifest])


def consume():
    reader = open_reader()
    poses = reader.open_component_readers(PosesComponent.Reader)["rig"]
    static = tuple(poses.get_static_poses())
    dynamic = tuple(poses.get_dynamic_poses())
    intrinsics = reader.open_component_readers(IntrinsicsComponent.Reader)["default"]
    camera_model = intrinsics.get_camera_model_parameters("front")
    lidar_model = intrinsics.get_lidar_model_parameters("top")
    masks = reader.open_component_readers(MasksComponent.Reader)["default"]
    mask = np.asarray(masks.get_camera_mask_image("front", "valid"))
    camera = reader.open_component_readers(CameraSensorComponent.Reader)["front"]
    image = np.asarray(camera.get_frame_image(120))
    lidar = reader.open_component_readers(LidarSensorComponent.Reader)["top"]
    lidar_direction = lidar.get_frame_ray_bundle_data(120, "direction")
    lidar_distance = lidar.get_frame_ray_bundle_return_data(120, "distance_m", None)
    radar = reader.open_component_readers(RadarSensorComponent.Reader)["radar"]
    radar_distance = radar.get_frame_ray_bundle_return_data(120, "distance_m", None)
    cuboids = reader.open_component_readers(CuboidsComponent.Reader)["default"]
    observations = tuple(cuboids.get_observations())
    points = reader.open_component_readers(PointCloudsComponent.Reader)["native"]
    xyz = tuple(points.get_pc_xyz(index) for index in range(points.pcs_count))
    labels = reader.open_component_readers(CameraLabelsComponent.Reader)["depth@front"]
    label = labels.get_label(160).get_data()
    assert reader.sequence_id == "sceneio-oracle-v1"
    assert len(static) == len(dynamic) == 1
    assert camera_model is not None and lidar_model is not None
    assert mask.shape == (2, 2) and image.shape == (2, 3, 3)
    assert lidar_direction.shape == (2, 3)
    assert lidar_distance.shape == (2, 2)
    assert radar_distance.shape == (2, 2)
    assert len(observations) == 1 and len(xyz) == 3
    assert label.shape == (2, 3)
    upstream_manifest = reader.get_sequence_meta().to_dict()
    declared_checksums = {
        item["path"]: item["md5"]
        for item in declared_manifest["component_stores"]
    }
    upstream_checksums = {
        item["path"]: item["md5"]
        for item in upstream_manifest["component_stores"]
    }
    assert declared_checksums == upstream_checksums
    return sum(value.nbytes for value in xyz) + image.nbytes + label.nbytes


def median_ms(operation):
    operation()
    values = []
    for _ in range(runs):
        start = time.perf_counter()
        operation()
        values.append((time.perf_counter() - start) * 1000)
    return statistics.median(values)


print(json.dumps({
    "catalog_ms": median_ms(open_reader),
    "typed_full_ms": median_ms(consume),
    "validated_payload_bytes": consume(),
}))
"""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--oracle-python", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _median_ms(operation, runs: int) -> float:
    operation()
    values = []
    for _ in range(runs):
        start = time.perf_counter()
        operation()
        values.append((time.perf_counter() - start) * 1000)
    return statistics.median(values)


def _verify_revision(upstream: Path) -> None:
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=upstream,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual != REVISION:
        raise RuntimeError(f"expected NCore {REVISION}, found {actual}")


def main() -> None:
    args = _arguments()
    if args.runs <= 0:
        raise ValueError("--runs must be positive")
    upstream = args.upstream.resolve()
    oracle_python = args.oracle_python.resolve()
    _verify_revision(upstream)
    source = sceneio.materialize_ncore_v4(FIXTURE)
    results = []
    with tempfile.TemporaryDirectory(prefix="sceneio-ncore-oracle-") as raw:
        root = Path(raw)
        for storage in ("directory", "itar"):
            destination = root / storage
            write_ms = _median_ms(
                lambda destination=destination, storage=storage: sceneio.write_ncore_v4(
                    source,
                    destination,
                    storage=storage,
                ),
                args.runs,
            )
            full_ms = _median_ms(
                lambda destination=destination: sceneio.materialize_ncore_v4(
                    destination
                ),
                args.runs,
            )
            selected_ms = _median_ms(
                lambda destination=destination: sceneio.read_ncore_component(
                    destination,
                    sceneio.NCoreSelection(
                        "point_clouds",
                        "native",
                        frames=(1, 2),
                    ),
                ),
                args.runs,
            )
            oracle = json.loads(
                subprocess.run(
                    [
                        str(oracle_python),
                        "-c",
                        _ORACLE_PROGRAM,
                        str(upstream),
                        str(destination / "dataset.ncore4.json"),
                        str(args.runs),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            )
            results.append(
                {
                    "storage": storage,
                    "sceneio_write_ms": write_ms,
                    "sceneio_typed_full_ms": full_ms,
                    "sceneio_selected_ms": selected_ms,
                    "upstream_catalog_ms": oracle["catalog_ms"],
                    "upstream_typed_full_ms": oracle["typed_full_ms"],
                    "upstream_validated_payload_bytes": oracle[
                        "validated_payload_bytes"
                    ],
                }
            )
    document = {
        "upstream_revision": REVISION,
        "fixture": FIXTURE.name,
        "runs": args.runs,
        "results": results,
    }
    rendered = json.dumps(document, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
