"""Benchmark specifications for the complete array codec family."""

from __future__ import annotations

import numpy as np

from bench.io_bench.fixtures.arrays import _depth_map
from bench.io_bench.model import Spec
from bench.io_bench.oracles.arrays import (
    _dmb_oracle_read,
    _dmb_oracle_write,
    _load_npz_oracle,
    _np_r,
    _np_w,
    _save_npz_oracle,
    safetensors_load,
    safetensors_save,
)
from sceneio import _core


def _array_fixture_values(scale):
    side = max(1, int(1024 * scale**0.5))
    tensor_side = max(1, int(512 * scale**0.5))
    flow = (
        np.random.default_rng(4)
        .standard_normal((side, side, 2))
        .astype(np.float32)
    )
    pfm = (
        np.random.default_rng(5)
        .standard_normal((side, side))
        .astype(np.float32)
    )
    npz_arrays = {
        "a": np.random.default_rng(6)
        .standard_normal((tensor_side, tensor_side))
        .astype(np.float32),
        "b": np.arange(max(1, tensor_side), dtype=np.int32),
    }
    return side, tensor_side, flow, pfm, npz_arrays, _core.tensor_dict(
        npz_arrays
    )


def build_array_specs(scale):
    side, tensor_side, flow, pfm, npz_arrays, tensors = (
        _array_fixture_values(scale)
    )
    return [
        Spec(
            "npy",
            lambda: (lambda a: (a, a))(
                np.ascontiguousarray(
                    np.random.default_rng(0).random(
                        (tensor_side, tensor_side, 8),
                        dtype=np.float32,
                    )
                )
            ),
            _core.write_npy,
            _core.read_npy,
            _np_w,
            _np_r,
            lambda rec, p: rec.nbytes,
        ),
        Spec(
            "pfm",
            lambda: (pfm, pfm),
            _core.write_pfm,
            _core.read_pfm,
            None,
            None,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "flo",
            lambda: (flow, flow),
            _core.write_flo,
            _core.read_flo,
            None,
            None,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "dmb",
            lambda: _depth_map(side, side),
            _core.write_dmb,
            _core.read_dmb,
            _dmb_oracle_write,
            _dmb_oracle_read,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "npz",
            lambda: (tensors, npz_arrays),
            _core.write_npz,
            _core.read_npz,
            lambda arrays: _save_npz_oracle(arrays),
            _load_npz_oracle,
            lambda rec, p: sum(array.nbytes for array in p.values()),
        ),
        Spec(
            "safetensors",
            lambda: (tensors, npz_arrays),
            _core.write_safetensors,
            _core.read_safetensors,
            (
                (lambda arrays: safetensors_save(arrays))
                if safetensors_save
                else None
            ),
            safetensors_load,
            lambda rec, p: sum(array.nbytes for array in p.values()),
        ),
    ]


__all__ = ["build_array_specs"]
