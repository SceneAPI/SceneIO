"""OpenCV, ROS CameraInfo, and Kalibr calibration codec verification."""

from __future__ import annotations

import gc
import mmap
import tracemalloc
import xml.etree.ElementTree as et
from dataclasses import replace

import numpy as np
import pytest
import yaml

import sceneio
from sceneio import _core

K = np.array(
    [[500.0, 0.0, 320.0], [0.0, 510.0, 240.0], [0.0, 0.0, 1.0]]
)
D = np.array([0.1, -0.2, 0.01, 0.02, -0.001])
R = np.eye(3)
P = np.array(
    [[500.0, 0.0, 320.0, 1.25], [0.0, 510.0, 240.0, -2.5], [0.0, 0.0, 1.0, 0.0]]
)

OPENCV_YAML = b"""%YAML:1.0
---
image_width: 640
image_height: 480
camera_name: 'front''left'
distortion_model: plumb_bob
camera_matrix: !!opencv-matrix
  rows: 3
  cols: 3
  dt: d
  data: [ 500., 0., 320.,
          0., 510., 240., 0., 0., 1. ]
distortion_coefficients: !!opencv-matrix
  rows: 1
  cols: 5
  dt: d
  data: [ 0.1, -0.2, 0.01, 0.02, -0.001 ]
rectification_matrix: !!opencv-matrix
  rows: 3
  cols: 3
  dt: d
  data: [ 1., 0., 0., 0., 1., 0., 0., 0., 1. ]
projection_matrix: !!opencv-matrix
  rows: 3
  cols: 4
  dt: d
  data: [ 500., 0., 320., 1.25, 0., 510., 240., -2.5, 0., 0., 1., 0. ]
"""

OPENCV_XML = b"""<?xml version="1.0"?>
<opencv_storage>
<image_width>640</image_width>
<image_height>480</image_height>
<camera_name>front&amp;left</camera_name>
<distortion_model>plumb_bob</distortion_model>
<camera_matrix type_id="opencv-matrix">
  <rows>3</rows><cols>3</cols><dt>d</dt>
  <data>500 0 320 0 510 240 0 0 1</data>
</camera_matrix>
<distortion_coefficients type_id="opencv-matrix">
  <rows>1</rows><cols>5</cols><dt>d</dt>
  <data>0.1 -0.2 0.01 0.02 -0.001</data>
</distortion_coefficients>
<rectification_matrix type_id="opencv-matrix">
  <rows>3</rows><cols>3</cols><dt>d</dt>
  <data>1 0 0 0 1 0 0 0 1</data>
</rectification_matrix>
<projection_matrix type_id="opencv-matrix">
  <rows>3</rows><cols>4</cols><dt>d</dt>
  <data>500 0 320 1.25 0 510 240 -2.5 0 0 1 0</data>
</projection_matrix>
</opencv_storage>
"""

ROS_YAML = b"""image_width: 640
image_height: 480
camera_name: front
camera_matrix:
  rows: 3
  cols: 3
  data: [500, 0, 320, 0, 510, 240, 0, 0, 1]
distortion_model: plumb_bob
distortion_coefficients:
  rows: 1
  cols: 5
  data: [0.1, -0.2, 0.01, 0.02, -0.001]
rectification_matrix:
  rows: 3
  cols: 3
  data: [1, 0, 0, 0, 1, 0, 0, 0, 1]
projection_matrix:
  rows: 3
  cols: 4
  data: [500, 0, 320, 1.25, 0, 510, 240, -2.5, 0, 0, 1, 0]
binning_x: 2
binning_y: 3
roi:
  x_offset: 10
  y_offset: 20
  height: 200
  width: 300
  do_rectify: true
"""

KALIBR_YAML = b"""cam0:
  camera_model: pinhole
  intrinsics: [500, 510, 320, 240]
  distortion_model: radtan
  distortion_coeffs: [0.1, -0.2, 0.01, 0.02]
  resolution: [640, 480]
  rostopic: /cam0/image_raw
  T_cam_imu:
  - [1, 0, 0, 0.1]
  - [0, 1, 0, 0.2]
  - [0, 0, 1, 0.3]
  - [0, 0, 0, 1]
  timeshift_cam_imu: -0.002
cam1:
  camera_model: omni
  intrinsics: [1.1, 505, 515, 321, 241]
  distortion_model: equidistant
  distortion_coeffs: [0.01, 0.02, 0.03, 0.04]
  resolution: [800, 600]
  rostopic: /cam1/image_raw
  T_cn_cnm1:
  - [0, -1, 0, 0.2]
  - [1, 0, 0, 0]
  - [0, 0, 1, 0]
  - [0, 0, 0, 1]
  timeshift_cam_imu: 0.001
"""


ARRAY_FIELDS = (
    "camera_ids",
    "resolutions",
    "intrinsic_offsets",
    "intrinsics",
    "distortion_offsets",
    "distortion_coefficients",
    "quaternions",
    "translations",
    "has_extrinsics",
    "camera_matrices",
    "has_camera_matrix",
    "rectification_matrices",
    "has_rectification",
    "projection_matrices",
    "has_projection_matrix",
    "binning",
    "roi",
    "roi_do_rectify",
    "has_operational",
    "time_offsets",
    "has_time_offset",
)


def _assert_rig_equal(actual, expected, *, transforms_exact=True):
    assert actual.num_cameras == expected.num_cameras
    assert actual.names == expected.names
    assert actual.projection_models == expected.projection_models
    assert actual.distortion_models == expected.distortion_models
    assert actual.topics == expected.topics
    for field in ARRAY_FIELDS:
        left = np.asarray(getattr(actual, field))
        right = np.asarray(getattr(expected, field))
        if not transforms_exact and field in {"quaternions", "translations"}:
            np.testing.assert_allclose(left, right, rtol=0, atol=2e-15)
        else:
            np.testing.assert_array_equal(left, right)
            if left.dtype == np.float64:
                np.testing.assert_array_equal(left.view(np.uint64), right.view(np.uint64))
    assert (
        actual.quaternion_order,
        actual.quaternion_sign,
        actual.transform_convention,
        actual.axis_frame,
        actual.reference_frame,
        actual.scale_to_meters,
    ) == (
        expected.quaternion_order,
        expected.quaternion_sign,
        expected.transform_convention,
        expected.axis_frame,
        expected.reference_frame,
        expected.scale_to_meters,
    )


def _single_rig(*, ros=False, name="front"):
    kwargs = {
        "names": [name],
        "camera_matrices": K[None],
        "has_camera_matrix": np.ones(1, np.uint8),
    }
    if ros:
        kwargs.update(
            rectification_matrices=R[None],
            has_rectification=np.ones(1, np.uint8),
            projection_matrices=P[None],
            has_projection_matrix=np.ones(1, np.uint8),
            binning=np.array([[2, 3]], np.uint32),
            roi=np.array([[10, 20, 300, 200]], np.uint32),
            roi_do_rectify=np.ones(1, np.uint8),
            has_operational=np.ones(1, np.uint8),
        )
    return _core.camera_rig(
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500.0, 510.0, 320.0, 240.0]),
        ["plumb_bob"],
        np.array([0, 5], np.uint64),
        D,
        np.array([[1.0, 0.0, 0.0, 0.0]]),
        np.zeros((1, 3)),
        has_extrinsics=np.zeros(1, np.uint8),
        **kwargs,
    )


def _opencv_yaml_oracle(data: bytes):
    text = data.decode().replace("%YAML:1.0", "").replace("!!opencv-matrix", "")
    return yaml.safe_load(text)


def test_opencv_yaml_golden_matches_independent_pyyaml_oracle():
    oracle = _opencv_yaml_oracle(OPENCV_YAML)
    rig = _core.read_opencv_yaml(OPENCV_YAML)
    assert rig.names == ["front'left"]
    assert rig.resolutions.tolist() == [[oracle["image_width"], oracle["image_height"]]]
    np.testing.assert_array_equal(
        rig.camera_matrices[0],
        np.asarray(oracle["camera_matrix"]["data"]).reshape(3, 3),
    )
    np.testing.assert_array_equal(
        rig.distortion_coefficients,
        oracle["distortion_coefficients"]["data"],
    )
    np.testing.assert_array_equal(rig.rectification_matrices[0], R)
    np.testing.assert_array_equal(rig.projection_matrices[0], P)


def test_opencv_xml_golden_matches_stdlib_elementtree_oracle():
    root = et.fromstring(OPENCV_XML)
    rig = _core.read_opencv_xml(OPENCV_XML)
    assert rig.names == [root.findtext("camera_name")]
    assert rig.names == ["front&left"]
    np.testing.assert_array_equal(
        rig.camera_matrices[0],
        np.fromstring(root.findtext("camera_matrix/data"), sep=" ").reshape(3, 3),
    )
    np.testing.assert_array_equal(
        rig.distortion_coefficients,
        np.fromstring(root.findtext("distortion_coefficients/data"), sep=" "),
    )


def test_ros_golden_matches_independent_pyyaml_oracle():
    oracle = yaml.safe_load(ROS_YAML)
    rig = _core.read_ros_camera_info(ROS_YAML)
    np.testing.assert_array_equal(
        rig.camera_matrices[0],
        np.asarray(oracle["camera_matrix"]["data"]).reshape(3, 3),
    )
    np.testing.assert_array_equal(
        rig.projection_matrices[0],
        np.asarray(oracle["projection_matrix"]["data"]).reshape(3, 4),
    )
    assert rig.binning.tolist() == [[2, 3]]
    assert rig.roi.tolist() == [[10, 20, 300, 200]]
    assert rig.roi_do_rectify.tolist() == [1]


def test_kalibr_golden_chain_and_time_convention_match_oracle():
    oracle = yaml.safe_load(KALIBR_YAML)
    rig = _core.read_kalibr(KALIBR_YAML)
    assert rig.num_cameras == 2
    assert rig.names == ["cam0", "cam1"]
    assert rig.projection_models == ["pinhole", "omni"]
    assert rig.distortion_models == ["radtan", "equidistant"]
    assert rig.reference_frame == "imu"
    assert rig.quaternion_sign == "canonical_positive_w"
    assert rig.time_offset_convention.endswith("camera_time + time_offset_seconds")
    np.testing.assert_array_equal(rig.time_offsets, [-0.002, 0.001])
    np.testing.assert_array_equal(rig.has_time_offset, [1, 1])

    first = np.asarray(oracle["cam0"]["T_cam_imu"], np.float64)
    relative = np.asarray(oracle["cam1"]["T_cn_cnm1"], np.float64)
    expected_second = relative @ first
    np.testing.assert_allclose(rig.translations[0], first[:3, 3], atol=1e-15)
    np.testing.assert_allclose(rig.translations[1], expected_second[:3, 3], atol=1e-15)
    root_half = np.sqrt(0.5)
    np.testing.assert_allclose(
        rig.quaternions[1], [root_half, 0.0, 0.0, root_half], atol=1e-15
    )


@pytest.mark.parametrize(
    ("reader", "writer", "data", "transforms_exact"),
    [
        (_core.read_opencv_yaml, _core.write_opencv_yaml, OPENCV_YAML, True),
        (_core.read_opencv_xml, _core.write_opencv_xml, OPENCV_XML, True),
        (_core.read_ros_camera_info, _core.write_ros_camera_info, ROS_YAML, True),
        (_core.read_kalibr, _core.write_kalibr, KALIBR_YAML, False),
    ],
)
def test_buffer_roundtrip_preserves_complete_record(
    reader, writer, data, transforms_exact
):
    expected = reader(data)
    encoded = bytes(writer(expected))
    actual = reader(encoded)
    _assert_rig_equal(actual, expected, transforms_exact=transforms_exact)


def test_opencv_yaml_and_xml_cross_syntax_preserve_semantics():
    expected = _core.read_opencv_yaml(OPENCV_YAML)
    actual = _core.read_opencv_xml(_core.write_opencv_xml(expected))
    _assert_rig_equal(actual, expected)


def test_opencv_and_ros_writers_match_independent_oracles():
    yaml_output = bytes(_core.write_opencv_yaml(_single_rig()))
    yaml_oracle = _opencv_yaml_oracle(yaml_output)
    assert yaml_oracle["camera_matrix"]["data"] == K.ravel().tolist()
    assert yaml_oracle["distortion_coefficients"]["data"] == D.tolist()

    xml_output = bytes(_core.write_opencv_xml(_single_rig(name="front&left")))
    root = et.fromstring(xml_output)
    assert root.findtext("camera_name") == "front&left"
    np.testing.assert_array_equal(
        np.fromstring(root.findtext("camera_matrix/data"), sep=" "), K.ravel()
    )

    ros_output = bytes(_core.write_ros_camera_info(_single_rig(ros=True)))
    ros_oracle = yaml.safe_load(ros_output)
    assert ros_oracle["roi"] == {
        "x_offset": 10,
        "y_offset": 20,
        "height": 200,
        "width": 300,
        "do_rectify": True,
    }


def test_kalibr_writer_matches_independent_pyyaml_oracle():
    expected = _core.read_kalibr(KALIBR_YAML)
    source_oracle = yaml.safe_load(KALIBR_YAML)
    oracle = yaml.safe_load(bytes(_core.write_kalibr(expected)))

    assert list(oracle) == ["cam0", "cam1"]
    assert oracle["cam0"]["camera_model"] == "pinhole"
    assert oracle["cam0"]["intrinsics"] == [500.0, 510.0, 320.0, 240.0]
    assert oracle["cam0"]["resolution"] == [640, 480]
    assert oracle["cam0"]["timeshift_cam_imu"] == -0.002
    np.testing.assert_allclose(
        np.asarray(oracle["cam0"]["T_cam_imu"], np.float64),
        np.asarray(source_oracle["cam0"]["T_cam_imu"], np.float64),
        rtol=0.0,
        atol=1e-15,
    )

    assert oracle["cam1"]["camera_model"] == "omni"
    assert oracle["cam1"]["intrinsics"] == [1.1, 505.0, 515.0, 321.0, 241.0]
    assert oracle["cam1"]["distortion_model"] == "equidistant"
    assert oracle["cam1"]["distortion_coeffs"] == [0.01, 0.02, 0.03, 0.04]
    assert oracle["cam1"]["resolution"] == [800, 600]
    assert oracle["cam1"]["timeshift_cam_imu"] == 0.001

    np.testing.assert_allclose(
        np.asarray(oracle["cam1"]["T_cn_cnm1"], np.float64),
        np.asarray(source_oracle["cam1"]["T_cn_cnm1"], np.float64),
        rtol=0.0,
        atol=1e-15,
    )


@pytest.mark.parametrize(
    ("format_id", "reader", "writer", "value"),
    [
        ("opencv_yaml", _core.read_opencv_yaml, _core.write_opencv_yaml, None),
        ("opencv_xml", _core.read_opencv_xml, _core.write_opencv_xml, None),
        (
            "ros_camera_info",
            _core.read_ros_camera_info,
            _core.write_ros_camera_info,
            "ros",
        ),
        ("kalibr", _core.read_kalibr, _core.write_kalibr, "kalibr"),
    ],
)
def test_buffer_protocol_mmap_public_dispatch_sink_and_inspection(
    tmp_path, format_id, reader, writer, value
):
    expected = (
        _core.read_kalibr(KALIBR_YAML)
        if value == "kalibr"
        else _single_rig(ros=value == "ros")
    )
    data = bytes(writer(expected))
    path = tmp_path / f"{format_id}.data"
    path.write_bytes(data)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        actual = reader(mapped)
        assert _core._buffer_address(mapped) == np.frombuffer(
            mapped, np.uint8
        ).ctypes.data
    gc.collect()
    _assert_rig_equal(actual, expected, transforms_exact=format_id != "kalibr")

    assert sceneio.detect(path) == format_id
    _assert_rig_equal(
        sceneio.read(path),
        expected,
        transforms_exact=format_id != "kalibr",
    )
    info = sceneio.inspect(path)
    assert (info.format, info.datatype, info.count) == (
        format_id,
        "camera_rig",
        expected.num_cameras,
    )
    assert info.metadata["resolutions"] == tuple(
        np.asarray(expected.resolutions).ravel()
    )
    caps = sceneio.capabilities(format_id)
    assert caps.record_type == "CameraRig"
    assert caps.streams_read and caps.streams_write

    sink = tmp_path / "sink.data"
    calls = _core._write_to_file(writer, expected, sink, _max_chunk=17)
    assert calls > 1
    assert sink.read_bytes() == data


@pytest.mark.parametrize(
    ("format_id", "data", "count"),
    [
        ("opencv_yaml", OPENCV_YAML, 1),
        ("opencv_xml", OPENCV_XML, 1),
        ("ros_camera_info", ROS_YAML, 1),
        ("kalibr", KALIBR_YAML, 2),
    ],
)
def test_public_inspection_does_not_call_full_decoder(
    tmp_path,
    monkeypatch,
    format_id,
    data,
    count,
):
    path = tmp_path / format_id
    path.write_bytes(data)
    codec = sceneio.io.registry.REGISTRY[format_id]

    def forbidden_decode(_path):
        raise AssertionError("metadata inspection called the full decoder")

    monkeypatch.setitem(
        sceneio.io.registry.REGISTRY,
        format_id,
        replace(codec, read=forbidden_decode),
    )
    info = sceneio.inspect(path, format=format_id)
    assert info.count == count
    assert info.metadata["resolutions"] == (
        (640, 480, 800, 600) if format_id == "kalibr" else (640, 480)
    )


def test_public_inspection_is_memory_bounded_and_releases_file(tmp_path):
    path = tmp_path / "large-opencv-yaml"
    path.write_bytes(
        OPENCV_YAML + b"# calibration provenance padding\n" * 50_000
    )
    size = path.stat().st_size
    assert size > 1_000_000
    sceneio.inspect(path, format="opencv_yaml")
    gc.collect()

    tracemalloc.start()
    info = sceneio.inspect(path, format="opencv_yaml")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak < size * 0.1
    assert info.count == 1
    renamed = path.with_name("released-opencv-yaml")
    path.rename(renamed)
    renamed.unlink()
    assert info.metadata["resolutions"] == (640, 480)


@pytest.mark.parametrize(
    ("format_id", "native_inspector", "data"),
    [
        (
            "opencv_yaml",
            _core._inspect_opencv_yaml,
            b"image_width: 640\n",
        ),
        (
            "opencv_xml",
            _core._inspect_opencv_xml,
            b"<opencv_storage>",
        ),
        (
            "ros_camera_info",
            _core._inspect_ros_camera_info,
            ROS_YAML.replace(
                b"projection_matrix:",
                b"missing_projection:",
            ),
        ),
        (
            "kalibr",
            _core._inspect_kalibr,
            KALIBR_YAML.replace(b"cam1:", b"cam2:"),
        ),
    ],
)
def test_public_malformed_inspection_preserves_native_cause(
    tmp_path,
    format_id,
    native_inspector,
    data,
):
    with pytest.raises(ValueError) as native_error:
        native_inspector(data)
    path = tmp_path / format_id
    path.write_bytes(data)

    with pytest.raises(sceneio.FormatError) as public_error:
        sceneio.inspect(path, format=format_id)

    cause = public_error.value.__cause__
    assert type(cause) is type(native_error.value)
    assert str(cause) == str(native_error.value)


def test_view_outlives_temporary_mmap_and_record(tmp_path):
    path = tmp_path / "calibration"
    path.write_bytes(OPENCV_YAML)
    rig = sceneio.read(path)
    matrix = rig.camera_matrices
    del rig
    gc.collect()
    np.testing.assert_array_equal(matrix[0], K)


@pytest.mark.parametrize(
    ("reader", "data"),
    [
        (_core.read_opencv_yaml, b""),
        (_core.read_opencv_yaml, b"image_width: 640\n"),
        (
            _core.read_opencv_yaml,
            OPENCV_YAML.replace(b"rows: 3", b"rows: 4", 1),
        ),
        (
            _core.read_opencv_yaml,
            OPENCV_YAML.replace(b"500.", b".nan", 1),
        ),
        (
            _core.read_opencv_yaml,
            OPENCV_YAML + b"alias: &x [1]\n",
        ),
        (
            _core.read_opencv_yaml,
            OPENCV_YAML + b"image_width: 320\n",
        ),
        (
            _core.read_opencv_yaml,
            OPENCV_YAML.replace(
                b"rectification_matrix: !!opencv-matrix",
                b"rectification_matrix:",
            ),
        ),
        (_core.read_opencv_xml, b"<opencv_storage>"),
        (
            _core.read_opencv_xml,
            b"<wrapper>" + OPENCV_XML + b"</wrapper>",
        ),
        (
            _core.read_opencv_xml,
            OPENCV_XML + b"<trailing/>",
        ),
        (
            _core.read_opencv_xml,
            OPENCV_XML.replace(
                b' type_id="opencv-matrix"', b"", 1
            ),
        ),
        (
            _core.read_opencv_xml,
            OPENCV_XML.replace(b"<cols>3</cols>", b"<cols>4</cols>", 1),
        ),
        (
            _core.read_opencv_xml,
            OPENCV_XML.replace(b"500 0 320", b"nan 0 320", 1),
        ),
        (
            _core.read_ros_camera_info,
            ROS_YAML.replace(b"projection_matrix:", b"missing_projection:"),
        ),
        (
            _core.read_ros_camera_info,
            ROS_YAML.replace(b"width: 300", b"width: 700"),
        ),
        (
            _core.read_kalibr,
            KALIBR_YAML.replace(b"cam1:", b"cam2:"),
        ),
        (
            _core.read_kalibr,
            KALIBR_YAML.replace(
                b"- [0, -1, 0, 0.2]", b"- [2, -1, 0, 0.2]"
            ),
        ),
    ],
)
def test_malformed_documents_are_rejected(reader, data):
    with pytest.raises(ValueError):
        reader(data)


@pytest.mark.parametrize(
    "reader",
    [
        _core.read_opencv_yaml,
        _core.read_opencv_xml,
        _core.read_ros_camera_info,
        _core.read_kalibr,
    ],
)
def test_nul_and_oversized_documents_are_rejected(reader):
    with pytest.raises(ValueError, match="NUL"):
        reader(b"x\0y")
    with pytest.raises(ValueError, match="16 MiB"):
        reader(b"x" * (16 * 1024 * 1024 + 1))


@pytest.mark.parametrize(
    ("reader", "data"),
    [
        (_core.read_opencv_yaml, OPENCV_YAML),
        (_core.read_opencv_xml, OPENCV_XML),
        (_core.read_ros_camera_info, ROS_YAML),
        (_core.read_kalibr, KALIBR_YAML),
    ],
    ids=("opencv-yaml", "opencv-xml", "ros-camera-info", "kalibr"),
)
def test_calibration_text_documents_require_valid_utf8(reader, data):
    with pytest.raises(ValueError, match="valid UTF-8"):
        reader(data + b"\n# invalid: \x8b\n")


def test_opencv_yaml_accepts_valid_multibyte_camera_names():
    data = OPENCV_YAML.replace(b"front''left", "frønt".encode())
    assert _core.read_opencv_yaml(data).names == ["frønt"]


def test_line_limit_is_enforced():
    with pytest.raises(ValueError, match="1 MiB"):
        _core.read_opencv_yaml(b"%YAML:1.0\n" + b"x" * (1024 * 1024 + 1))


def test_generic_yaml_and_xml_are_not_claimed(tmp_path):
    yaml_path = tmp_path / "arbitrary.yaml"
    yaml_path.write_text("hello: world\n", encoding="ascii")
    xml_path = tmp_path / "arbitrary.xml"
    xml_path.write_text("<root/>\n", encoding="ascii")
    with pytest.raises(sceneio.FormatError):
        sceneio.detect(yaml_path)
    with pytest.raises(sceneio.FormatError):
        sceneio.detect(xml_path)


def test_writer_guards_do_not_truncate_existing_destination(tmp_path):
    values = [
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500.0, 510.0, 320.0, 240.0]),
        ["plumb_bob"],
        np.array([0, 5], np.uint64),
        D,
        np.array([[1.0, 0.0, 0.0, 0.0]]),
        np.zeros((1, 3)),
    ]
    foreign = _core.camera_rig(
        *values,
        camera_matrices=K[None],
        axis_frame="opengl",
    )
    path = tmp_path / "keep"
    path.write_bytes(b"keep")
    with pytest.raises(sceneio.FormatError, match="not representable"):
        sceneio.write(foreign, path, format="opencv_yaml")
    assert path.read_bytes() == b"keep"


def test_writer_revalidates_mutable_record_views():
    rig = _single_rig()
    rig.camera_matrices[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        _core.write_opencv_yaml(rig)

    rig = _single_rig()
    rig.intrinsics[0] += 1
    with pytest.raises(ValueError, match="exactly match"):
        _core.write_opencv_xml(rig)

    rig = _core.read_kalibr(KALIBR_YAML)
    rig.quaternions[1] *= 2
    with pytest.raises(ValueError, match="unit length"):
        _core.write_kalibr(rig)


def test_ros_empty_distortion_model_and_coefficients_roundtrip():
    data = ROS_YAML.replace(b"plumb_bob", b"''").replace(
        b"rows: 1\n  cols: 5\n  data: [0.1, -0.2, 0.01, 0.02, -0.001]",
        b"rows: 0\n  cols: 0\n  data: []",
    )
    rig = _core.read_ros_camera_info(data)
    assert rig.distortion_models == [""]
    assert rig.distortion_coefficients.size == 0
    actual = _core.read_ros_camera_info(_core.write_ros_camera_info(rig))
    _assert_rig_equal(actual, rig)


def test_kalibr_without_imu_uses_camera0_reference():
    data = KALIBR_YAML.replace(
        b"  T_cam_imu:\n"
        b"  - [1, 0, 0, 0.1]\n"
        b"  - [0, 1, 0, 0.2]\n"
        b"  - [0, 0, 1, 0.3]\n"
        b"  - [0, 0, 0, 1]\n"
        b"  timeshift_cam_imu: -0.002\n",
        b"",
    ).replace(b"  timeshift_cam_imu: 0.001\n", b"")
    rig = _core.read_kalibr(data)
    assert rig.reference_frame == "camera0"
    np.testing.assert_array_equal(rig.quaternions[0], [1, 0, 0, 0])
    np.testing.assert_array_equal(rig.translations[0], [0, 0, 0])
    actual = _core.read_kalibr(_core.write_kalibr(rig))
    _assert_rig_equal(actual, rig, transforms_exact=False)


def test_randomized_coefficients_are_bit_exact_through_text_roundtrip():
    rng = np.random.default_rng(20260724)
    for _ in range(40):
        coefficients = rng.standard_normal(int(rng.integers(1, 17)))
        rig = _core.camera_rig(
            np.array([0], np.uint32),
            np.array([[1920, 1080]], np.uint64),
            ["pinhole"],
            np.array([0, 4], np.uint64),
            np.array([700.0, 701.0, 960.0, 540.0]),
            ["opencv"],
            np.array([0, len(coefficients)], np.uint64),
            coefficients,
            np.array([[1.0, 0.0, 0.0, 0.0]]),
            np.zeros((1, 3)),
            has_extrinsics=np.zeros(1, np.uint8),
            camera_matrices=np.array(
                [[[700.0, 0.0, 960.0], [0.0, 701.0, 540.0], [0.0, 0.0, 1.0]]]
            ),
        )
        for reader, writer in (
            (_core.read_opencv_yaml, _core.write_opencv_yaml),
            (_core.read_opencv_xml, _core.write_opencv_xml),
        ):
            actual = reader(writer(rig))
            _assert_rig_equal(actual, rig)


def test_mmap_path_avoids_whole_file_python_bytes(tmp_path):
    rig = _single_rig()
    path = tmp_path / "large"
    # YAML comments are schema-neutral and let this test isolate the input
    # transport allocation without inventing an implausibly huge D vector.
    path.write_bytes(
        bytes(_core.write_opencv_yaml(rig))
        + b"# calibration provenance padding\n" * 50_000
    )
    size = path.stat().st_size
    assert size > 1_000_000
    # Keep import/registry initialization outside the allocation windows.
    sceneio.read(path)
    gc.collect()

    tracemalloc.start()
    data = path.read_bytes()
    _core.read_opencv_yaml(data)
    _, bytes_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del data

    tracemalloc.start()
    sceneio.read(path)
    _, mmap_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert bytes_peak >= size * 0.8
    assert mmap_peak < size * 0.1
