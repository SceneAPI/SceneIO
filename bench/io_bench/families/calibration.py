"""Benchmark specifications for the complete calibration codec family."""

from __future__ import annotations

from functools import partial

from bench.io_bench.families.common import _record_nbytes
from bench.io_bench.fixtures.calibration import (
    _kalibr_calibration,
    _single_calibration,
)
from bench.io_bench.model import Spec
from bench.io_bench.oracles.calibration import (
    _xml_oracle_read,
    _xml_oracle_write,
    _yaml_oracle_read,
    _yaml_oracle_write,
    yaml,
)
from sceneio import _core


def build_calibration_specs(scale):
    return [
        Spec(
            "opencv_yaml",
            _single_calibration,
            _core.write_opencv_yaml,
            _core.read_opencv_yaml,
            _yaml_oracle_write if yaml else None,
            _yaml_oracle_read if yaml else None,
            lambda rec, payload: _record_nbytes(rec),
        ),
        Spec(
            "opencv_xml",
            _single_calibration,
            _core.write_opencv_xml,
            _core.read_opencv_xml,
            _xml_oracle_write,
            _xml_oracle_read,
            lambda rec, payload: _record_nbytes(rec),
        ),
        Spec(
            "ros_camera_info",
            partial(_single_calibration, ros=True),
            _core.write_ros_camera_info,
            _core.read_ros_camera_info,
            _yaml_oracle_write if yaml else None,
            _yaml_oracle_read if yaml else None,
            lambda rec, payload: _record_nbytes(rec),
        ),
        Spec(
            "kalibr",
            partial(_kalibr_calibration, scale),
            _core.write_kalibr,
            _core.read_kalibr,
            _yaml_oracle_write if yaml else None,
            _yaml_oracle_read if yaml else None,
            lambda rec, payload: _record_nbytes(rec),
        ),
    ]


__all__ = ["build_calibration_specs"]
