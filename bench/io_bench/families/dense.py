"""Benchmark specifications for the COLMAP dense-MVS family."""

from __future__ import annotations

import numpy as np

from bench.io_bench.fixtures.dense import dense_fixtures
from bench.io_bench.model import Spec
from bench.io_bench.oracles import dense as oracle
from sceneio import _core

_DENSE_IDS = {
    "colmap_fused_visibility",
    "colmap_mvs_consistency",
    "colmap_mvs_depth",
    "colmap_mvs_normal",
}


def _assert_bits_equal(left, right) -> None:
    left_array = np.asarray(left)
    right_array = np.asarray(right)
    assert left_array.shape == right_array.shape
    assert left_array.dtype == right_array.dtype
    assert left_array.tobytes() == right_array.tobytes()


def validate_dense_oracle_parity(
    spec,
    record,
    payload,
    native_encoded: bytes,
) -> None:
    """Cross-check native and independent dense wires before timing."""

    if spec.ow is None or spec.orr is None:
        raise AssertionError(f"{spec.id} has no independent dense oracle")
    oracle_encoded = bytes(spec.ow(payload))
    assert native_encoded == oracle_encoded
    native_decoded = spec.r(oracle_encoded)
    oracle_decoded = spec.orr(native_encoded)

    if spec.id == "colmap_mvs_depth":
        _assert_bits_equal(record.depth, payload)
        _assert_bits_equal(native_decoded.depth, payload)
        _assert_bits_equal(oracle_decoded, payload)
    elif spec.id == "colmap_mvs_normal":
        _assert_bits_equal(record.normals, payload)
        _assert_bits_equal(native_decoded.normals, payload)
        _assert_bits_equal(oracle_decoded, payload)
    elif spec.id == "colmap_mvs_consistency":
        width, height, rows, columns, offsets, indices = payload
        assert (native_decoded.width, native_decoded.height) == (
            width,
            height,
        )
        for observed, expected in (
            (native_decoded.rows, rows),
            (native_decoded.columns, columns),
            (native_decoded.offsets, offsets),
            (native_decoded.image_indices, indices),
        ):
            np.testing.assert_array_equal(observed, expected)
        oracle_width, oracle_height, oracle_entries = oracle_decoded
        assert (oracle_width, oracle_height) == (width, height)
        assert len(oracle_entries) == rows.size
        for entry, observed in enumerate(oracle_entries):
            assert observed[0] == int(columns[entry])
            assert observed[1] == int(rows[entry])
            np.testing.assert_array_equal(
                observed[2],
                indices[
                    int(offsets[entry]) : int(offsets[entry + 1])
                ],
            )
    elif spec.id == "colmap_fused_visibility":
        offsets, indices = payload
        np.testing.assert_array_equal(native_decoded.offsets, offsets)
        np.testing.assert_array_equal(native_decoded.image_indices, indices)
        assert len(oracle_decoded) == offsets.size - 1
        for point, observed in enumerate(oracle_decoded):
            np.testing.assert_array_equal(
                observed,
                indices[
                    int(offsets[point]) : int(offsets[point + 1])
                ],
            )
    else:
        raise AssertionError(f"unsupported dense oracle id {spec.id!r}")


def build_dense_specs(scale):
    fixtures = dense_fixtures(scale)
    return [
        Spec(
            "colmap_mvs_depth",
            lambda: fixtures["depth"],
            _core.write_colmap_mvs_depth,
            _core.read_colmap_mvs_depth,
            oracle.depth_write,
            oracle.depth_read,
            lambda record, payload: payload.nbytes,
        ),
        Spec(
            "colmap_mvs_normal",
            lambda: fixtures["normal"],
            _core.write_colmap_mvs_normal,
            _core.read_colmap_mvs_normal,
            oracle.normal_write,
            oracle.normal_read,
            lambda record, payload: payload.nbytes,
        ),
        Spec(
            "colmap_mvs_consistency",
            lambda: fixtures["consistency"],
            _core.write_colmap_mvs_consistency,
            _core.read_colmap_mvs_consistency,
            oracle.consistency_write,
            oracle.consistency_read,
            lambda record, payload: (
                payload[2].nbytes
                + payload[3].nbytes
                + payload[4].nbytes
                + payload[5].nbytes
            ),
        ),
        Spec(
            "colmap_fused_visibility",
            lambda: fixtures["visibility"],
            _core.write_colmap_fused_visibility,
            _core.read_colmap_fused_visibility,
            oracle.visibility_write,
            oracle.visibility_read,
            lambda record, payload: payload[0].nbytes + payload[1].nbytes,
        ),
    ]


__all__ = ["build_dense_specs", "validate_dense_oracle_parity"]
