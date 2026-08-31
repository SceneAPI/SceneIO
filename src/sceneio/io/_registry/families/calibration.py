"""Built-in camera-calibration codec definitions."""

from __future__ import annotations

from sceneio import _core
from sceneio.io._registry.adapters import _file_sink_writer, _mmap_reader
from sceneio.io._registry.model import Codec

# Calibration carriers deliberately avoid claiming generic .yaml/.yml/.xml
# extensions. Their canonical writers begin with schema-specific signatures,
# while noncanonical documents remain available through explicit format=.
CALIBRATION_CODECS: tuple[Codec, ...] = (
    Codec(
        "opencv_yaml",
        (),
        _mmap_reader(_core.read_opencv_yaml),
        _file_sink_writer(_core.write_opencv_yaml),
        record=_core.CameraRig,
        payload_kind="camera_rig",
        magic=(b"%YAML:1.0",),
        supported_features=(
            "camera_matrix",
            "distortion_coefficients",
            "rectification_matrix",
            "projection_matrix",
        ),
        unsupported_features=("stereo_extrinsics",),
    ),
    Codec(
        "opencv_xml",
        (),
        _mmap_reader(_core.read_opencv_xml),
        _file_sink_writer(_core.write_opencv_xml),
        record=_core.CameraRig,
        payload_kind="camera_rig",
        magic=(b"<opencv_storage",),
        supported_features=(
            "camera_matrix",
            "distortion_coefficients",
            "rectification_matrix",
            "projection_matrix",
        ),
        unsupported_features=("stereo_extrinsics",),
    ),
    Codec(
        "ros_camera_info",
        (),
        _mmap_reader(_core.read_ros_camera_info),
        _file_sink_writer(_core.write_ros_camera_info),
        record=_core.CameraRig,
        payload_kind="camera_rig",
        magic=(b"image_width:",),
        supported_features=(
            "camera_matrix",
            "distortion_coefficients",
            "rectification_matrix",
            "projection_matrix",
            "binning",
            "roi",
        ),
    ),
    Codec(
        "kalibr",
        (),
        _mmap_reader(_core.read_kalibr),
        _file_sink_writer(_core.write_kalibr),
        record=_core.CameraRig,
        payload_kind="camera_rig",
        magic=(b"cam0:",),
        supported_features=(
            "multi_camera",
            "pinhole",
            "omni",
            "chained_extrinsics",
            "imu_extrinsics",
            "camera_imu_time_offsets",
            "topics",
        ),
    ),
)
