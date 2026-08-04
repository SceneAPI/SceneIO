"""Built-in multi-sensor dataset codec definitions."""

from __future__ import annotations

from functools import partial

from sceneio.io._euroc_dataset import codec as _euroc_adapter
from sceneio.io._euroc_dataset.model import VisualInertialDataset
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._ncore import (
    NCoreDataset,
    inspect_ncore_v4,
    is_ncore_v4_directory,
    is_ncore_v4_file,
    read_ncore_v4,
    write_ncore_v4,
)
from sceneio.io._registry.model import Codec


def build_dataset_codecs(
    frame_access: ImageFrameAccess,
) -> tuple[Codec, ...]:
    """Return multi-sensor dataset codecs bound to image metadata access."""

    return (
        Codec(
            "ncore_v4",
            (),
            read_ncore_v4,
            write_ncore_v4,
            record=NCoreDataset,
            datatype="ncore_dataset",
            is_directory=True,
            container_kind="multi_file",
            dir_marker=".zattrs",
            directory_markers=(".zattrs", ".zgroup"),
            file_probe=is_ncore_v4_file,
            directory_probe=is_ncore_v4_directory,
            inspect=inspect_ncore_v4,
            streams_write=True,
            requires_features=("zarr", "cbor2"),
            supported_features=(
                "v4",
                "local_directory_stores",
                "local_indexed_tar_stores",
                "sequence_manifests",
                "grouped_component_stores",
                "lazy_component_catalog",
                "metadata_only_inspect",
                "standard_component_enumeration",
                "custom_component_enumeration",
                "component_materialization",
                "standard_semantic_profiles",
                "generic_component_interpretation",
                "deterministic_directory_write",
                "deterministic_indexed_tar_write",
                "sequence_manifest_write",
                "transactional_path_write",
            ),
            unsupported_features=(
                "remote_stores",
                "legacy_versions",
            ),
        ),
        Codec(
            "euroc_dataset",
            (),
            partial(_euroc_adapter.read_euroc_dataset, frame_access),
            partial(_euroc_adapter.write_euroc_dataset, frame_access),
            record=VisualInertialDataset,
            datatype="visual_inertial_dataset",
            is_directory=True,
            container_kind="multi_file",
            dir_marker="mav0",
            directory_probe=_euroc_adapter.is_euroc_dataset_directory,
            inspect=partial(
                _euroc_adapter.inspect_euroc_dataset,
                frame_access,
            ),
            supported_features=(
                "asl_directory_profile",
                "multi_camera",
                "multi_imu",
                "lazy_encoded_images",
                "exact_int64_nanosecond_timestamps",
                "camera_intrinsics_and_distortion",
                "sensor_to_body_extrinsics",
                "imu_noise_calibration",
                "optional_ground_truth_states",
                "typed_sensor_and_time_selection",
                "metadata_only_inspect",
                "direct_streaming_csv_write",
                "transactional_directory_write",
            ),
            unsupported_features=(
                "implicit_clock_alignment",
                "image_transcoding",
                "non_camera_or_imu_sensors",
                "arbitrary_yaml",
            ),
        ),
    )


__all__ = ["build_dataset_codecs"]
