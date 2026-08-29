"""Executable FC5 provider gate for broader OpenVDB support."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import numpy as np
import pytest
import tinyvdb

import sceneio
from sceneio.io import _openvdb

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/openvdb_provider_limits_v1.toml").read_text(encoding="utf-8")
)
AFFINE_MATRIX = np.array(
    (
        (0.5, 0.125, 0.0, 0.0),
        (0.0, 1.5, 0.25, 0.0),
        (0.0, 0.0, 2.0, 0.0),
        (10.0, -2.0, 3.0, 1.0),
    ),
    dtype=np.float64,
)


def _vector_root() -> Path:
    configured = os.environ.get("SCENEIO_OPENVDB_VECTOR_DIR")
    if not configured:
        pytest.skip("set SCENEIO_OPENVDB_VECTOR_DIR to official-OpenVDB generated vectors")
    root = Path(configured)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "openvdb-provider-vectors-v1"
    assert manifest["oracle"] == "pyopenvdb 10.0.1"
    return root


def _open(path: Path):
    file = tinyvdb.open(str(path))
    return file


def _sparse(grid) -> dict[tuple[int, int, int], np.float32]:
    payload = grid.to_sparse()
    count = int(payload["count"])
    coordinates = np.frombuffer(payload["coords"], dtype=np.int32).reshape(count, 3)
    values = np.frombuffer(payload["values"], dtype=np.float32)
    return {
        tuple(int(component) for component in coordinate): np.float32(value)
        for coordinate, value in zip(coordinates, values, strict=True)
    }


def test_tinyvdb_selection_and_authoring_surface_forces_fc5_exclusion():
    assert tinyvdb.__version__ == "0.9.0"
    file = _open(_openvdb._TEMPLATE)
    try:
        assert file.read_grids.__doc__ == "Read and decompress all grids"
        with pytest.raises(TypeError, match="takes no arguments"):
            file.read_grids(0)
        assert not hasattr(file, "add_grid")
        assert callable(file.replace_grid_from_sparse)

        grid = file.grid(0)
        assert dict(grid.metadata) == {}
        np.testing.assert_array_equal(
            np.asarray(grid.transform["matrix"]),
            np.zeros((4, 4)),
        )
        with pytest.raises(tinyvdb.VDBError, match="grid_to_sparse failed"):
            grid.to_sparse()

        file.read_grids()
        with pytest.raises(AttributeError, match="not writable"):
            file.grid(0).transform = dict(file.grid(0).transform)
    finally:
        file.close()

    assert CONTRACT["decision"] == "exclusion"
    assert CONTRACT["selection"]["bounded_selected_grid"] is False
    for symbol in CONTRACT["provisional_symbols"]:
        assert not hasattr(sceneio, symbol)
        assert not hasattr(sceneio.data, symbol)
    for name in CONTRACT["provisional_apis"]:
        assert not hasattr(sceneio, name)
        assert not hasattr(sceneio.io, name)


def test_official_openvdb_multi_scalar_vector_and_empty_observations():
    root = _vector_root()
    multi = _open(root / "multi_scalar_transformed.vdb")
    try:
        assert multi.grid_count == 3
        assert [multi.grid_name(index) for index in range(3)] == [
            "density",
            "temperature",
            "empty",
        ]
        assert [multi.grid_type_name(index) for index in range(3)] == [
            "Tree_float_5_4_3",
            "Tree_float_5_4_3",
            "Tree_float_5_4_3",
        ]
        multi.read_grids()
        assert _sparse(multi.grid(0)) == {
            (-17, 4, 2): np.float32(1.25),
            (0, 0, 0): np.float32(-2.5),
            (130, -9, 31): np.float32(3.75),
        }
        assert _sparse(multi.grid(1)) == {
            (-8, -7, -6): np.float32(12.5),
            (5, 4, 3): np.float32(99.0),
        }
        np.testing.assert_array_equal(
            np.asarray(multi.grid(1).transform["matrix"]),
            AFFINE_MATRIX,
        )
        assert multi.grid(1).float_background() == pytest.approx(np.float32(-273.15))
        assert multi.grid(2).active_voxel_count() == 0
        # Official OpenVDB authored scale 2.0; TinyVDB returns identity.
        np.testing.assert_array_equal(
            np.asarray(multi.grid(2).transform["matrix"]),
            np.eye(4),
        )
    finally:
        multi.close()

    vector = _open(root / "vector_velocity.vdb")
    try:
        assert vector.grid_type_name(0) == "Tree_vec3s_5_4_3"
        vector.read_grids()
        grid = vector.grid(0)
        # Official OpenVDB authored two values, a nonzero vector background,
        # and scale 0.25. TinyVDB exposes none of them faithfully.
        assert grid.active_voxel_count() == 0
        assert grid.float_background() == 0.0
        np.testing.assert_array_equal(
            np.asarray(grid.transform["matrix"]),
            np.eye(4),
        )
        with pytest.raises(tinyvdb.VDBError, match="grid_to_sparse failed"):
            grid.to_sparse()
    finally:
        vector.close()


def test_sceneio_cleanly_refuses_every_provider_limit_vector():
    root = _vector_root()
    cases = {
        "multi_scalar_transformed.vdb": "requires exactly one grid",
        "scalar_transformed.vdb": "identity index-to-world transform",
        "empty_transformed_zero_background.vdb": "empty grids are unsupported",
        "level_set.vdb": "zero-background scalar grid",
        "vector_velocity.vdb": "only float32 scalar",
        "mixed_types.vdb": "requires exactly one grid",
        "duplicate_names.vdb": "requires exactly one grid",
    }
    for filename, message in cases.items():
        path = root / filename
        with pytest.raises(sceneio.FormatError, match=message):
            sceneio.inspect(path)
        with pytest.raises(sceneio.FormatError, match=message):
            sceneio.read(path)


def test_openvdb_provider_limit_contract_and_generator_are_live():
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["status"] == "qualified_provider_exclusion"
    assert CONTRACT["observed_types"]["vec3s_tree"].endswith("background_and_transform_lost")
    generator = ROOT / CONTRACT["generator"]
    source = generator.read_text(encoding="utf-8")
    for marker in (
        "Vec3SGrid",
        "BoolGrid",
        "multi_scalar_transformed.vdb",
        "empty_transformed_zero_background.vdb",
        "duplicate_names.vdb",
    ):
        assert marker in source
    for reference in CONTRACT["evidence"]:
        assert (ROOT / reference).is_file()
