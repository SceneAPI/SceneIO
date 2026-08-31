"""Benchmark specifications for buffer-backed reconstruction codecs."""

from __future__ import annotations

from functools import partial

from bench.io_bench.families.common import _record_nbytes
from bench.io_bench.fixtures.reconstruction import (
    _bal_fixture,
    _euroc_fixture,
    _g2o_fixture,
    _poses_and_reconstruction,
)
from bench.io_bench.model import Spec
from bench.io_bench.oracles.reconstruction import (
    _bal_oracle_read,
    _bal_oracle_write,
    _euroc_oracle_read,
    _euroc_oracle_write,
    _g2o_oracle_read,
    _g2o_oracle_write,
)
from sceneio import _core
from sceneio._posed_views import posed_view_storage, posed_views_from_storage


def _write_transforms_json(value):
    return _core.write_transforms_json(
        posed_view_storage(value, profile="transforms_json")
    )


def _read_transforms_json(data):
    return posed_views_from_storage(
        _core.read_transforms_json(data),
        source_profile="transforms_json",
    )


def _write_tum(value):
    return _core.write_tum(posed_view_storage(value, profile="tum"))


def _read_tum(data):
    return posed_views_from_storage(_core.read_tum(data), source_profile="tum")


def _write_kitti(value):
    return _core.write_kitti(posed_view_storage(value, profile="kitti"))


def _read_kitti(data):
    return posed_views_from_storage(_core.read_kitti(data), source_profile="kitti")


def _posed_view_nbytes(value, profile):
    return _record_nbytes(posed_view_storage(value, profile=profile))


def _euroc_payload_nbytes(payload):
    return sum(value.nbytes for value in payload.values())


def _g2o_payload_nbytes(payload):
    return sum(value.nbytes for value in payload.values())


def _bal_payload_nbytes(payload):
    return sum(value.nbytes for value in payload.values())


def build_reconstruction_specs(scale, pose_bundle=None):
    reconstruction, transforms, tum, kitti = (
        pose_bundle or _poses_and_reconstruction(scale)
    )
    return [
        Spec(
            "transforms_json",
            lambda: (transforms, transforms),
            _write_transforms_json,
            _read_transforms_json,
            None,
            None,
            lambda rec, p: _posed_view_nbytes(rec, "transforms_json"),
        ),
        Spec(
            "tum",
            lambda: (tum, tum),
            _write_tum,
            _read_tum,
            None,
            None,
            lambda rec, p: _posed_view_nbytes(rec, "tum"),
        ),
        Spec(
            "kitti",
            lambda: (kitti, kitti),
            _write_kitti,
            _read_kitti,
            None,
            None,
            lambda rec, p: _posed_view_nbytes(rec, "kitti"),
        ),
        Spec(
            "euroc_state",
            lambda: _euroc_fixture(scale),
            _core.write_euroc_state,
            _core.read_euroc_state,
            _euroc_oracle_write,
            _euroc_oracle_read,
            lambda rec, payload: _euroc_payload_nbytes(payload),
        ),
        Spec(
            "g2o",
            partial(_g2o_fixture, scale),
            _core.write_g2o,
            _core.read_g2o,
            _g2o_oracle_write,
            _g2o_oracle_read,
            lambda rec, payload: _g2o_payload_nbytes(payload),
        ),
        Spec(
            "bundler",
            lambda: (reconstruction, reconstruction),
            _core.write_bundler,
            _core.read_bundler,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "bal",
            lambda: _bal_fixture(scale),
            _core.write_bal,
            _core.read_bal,
            _bal_oracle_write,
            _bal_oracle_read,
            lambda rec, p: _bal_payload_nbytes(p),
        ),
        Spec(
            "nvm",
            lambda: (reconstruction, reconstruction),
            _core.write_nvm,
            _core.read_nvm,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "openmvg",
            lambda: (reconstruction, reconstruction),
            _core.write_openmvg,
            _core.read_openmvg,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
    ]


__all__ = [
    "_bal_payload_nbytes",
    "_euroc_payload_nbytes",
    "_g2o_payload_nbytes",
    "build_reconstruction_specs",
]
