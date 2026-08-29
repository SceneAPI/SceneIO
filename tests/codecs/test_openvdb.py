from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pytest
import tinyvdb

import sceneio
from sceneio import _core
from sceneio.io import _openvdb


def _sample():
    coords = np.array(
        [
            [0, 0, 0],
            [-17, 4, 2],
            [130, -9, 31],
            [2, 7, -11],
        ],
        dtype=np.int32,
    )
    bits = np.array(
        [0x3FA00000, 0xC0200000, 0x00000001, 0x80000000],
        dtype=np.uint32,
    )
    values = bits.view(np.float32)
    record = _core.tensor_dict(
        {"coords": coords, "values": values},
        attrs={"name": "tsdf"},
    )
    return record, coords, values


def _as_mapping(coords, values):
    return {
        tuple(int(value) for value in coord): np.float32(sample).view(np.uint32)
        for coord, sample in zip(coords, values, strict=True)
    }


def _oracle_sparse(path):
    file = tinyvdb.open(str(path))
    try:
        assert file.grid_count == 1
        assert file.grid_type_name(0) == "Tree_float_5_4_3"
        file.read_grids()
        grid = file.grid(0)
        sparse = grid.to_sparse()
        count = int(sparse["count"])
        coords = np.frombuffer(sparse["coords"], dtype=np.int32).reshape(
            count, 3
        )
        values = np.frombuffer(sparse["values"], dtype=np.float32)
        return grid.name, coords.copy(), values.copy()
    finally:
        file.close()


def test_openvdb_sceneio_write_is_exact_for_upstream_reader(tmp_path):
    record, coords, values = _sample()
    path = tmp_path / "sceneio.vdb"

    sceneio.write_openvdb(record, path)

    assert sceneio.detect(path) == "openvdb"
    name, actual_coords, actual_values = _oracle_sparse(path)
    assert name == "tsdf"
    assert _as_mapping(actual_coords, actual_values) == _as_mapping(
        coords, values
    )


def test_openvdb_sceneio_reads_upstream_fixture_exactly():
    path = (
        Path(_openvdb.__file__).with_name("_assets")
        / "openvdb_float_template.vdb"
    )
    _name, expected_coords, expected_values = _oracle_sparse(path)

    decoded = sceneio.read(path)

    assert decoded.attrs == {
        "sceneio.schema": "sceneio.sparse_scalar_grid.v1",
        "name": "density",
        "background": "0",
        "index_to_world": "identity",
    }
    assert _as_mapping(decoded["coords"], decoded["values"]) == _as_mapping(
        expected_coords, expected_values
    )


def test_openvdb_registry_roundtrip_is_bit_exact(tmp_path):
    record, coords, values = _sample()
    path = tmp_path / "roundtrip.vdb"

    sceneio.write(record, path)
    decoded = sceneio.read(path)

    assert isinstance(decoded, _core.TensorDict)
    assert _as_mapping(decoded["coords"], decoded["values"]) == _as_mapping(
        coords, values
    )
    assert decoded.attrs["name"] == "tsdf"


def test_tinyvdb_provider_authoring_surface_is_qualified():
    file = tinyvdb.open(str(_openvdb._TEMPLATE))
    try:
        assert file.grid_count == 1
        assert not hasattr(file, "add_grid")
        assert callable(file.replace_grid_from_sparse)
        assert callable(file.extend_grid_from_sparse)
        file.read_grids()
        grid = file.grid(0)
        transform = dict(grid.transform)
        assert np.asarray(transform["matrix"]).shape == (4, 4)
        with pytest.raises(AttributeError, match="not writable"):
            grid.transform = transform
    finally:
        file.close()


def test_openvdb_record_outlives_closed_and_removed_source(tmp_path):
    record, coords, values = _sample()
    path = tmp_path / "lifetime.vdb"
    sceneio.write(record, path)

    decoded = sceneio.read(path)
    path.unlink()
    gc.collect()

    assert _as_mapping(decoded["coords"], decoded["values"]) == _as_mapping(
        coords, values
    )


def test_openvdb_inspect_does_not_materialize_sparse_voxels(
    tmp_path, monkeypatch
):
    record, _coords, _values = _sample()
    path = tmp_path / "inspect.vdb"
    sceneio.write(record, path)

    class GridProxy:
        def __init__(self, grid):
            self._grid = grid

        def __getattr__(self, name):
            if name == "to_sparse":
                raise AssertionError("inspect decoded the sparse voxel payload")
            return getattr(self._grid, name)

    original = _openvdb._open_single_grid

    def proxied(source):
        file, grid, metadata = original(source)
        return file, GridProxy(grid), metadata

    monkeypatch.setattr(_openvdb, "_open_single_grid", proxied)
    result = sceneio.inspect(path)

    assert result.format == "openvdb"
    assert result.datatype == "sparse_volume"
    assert result.count == 4
    assert result.byte_size == path.stat().st_size
    assert [(item.name, item.shape, item.dtype) for item in result.arrays] == [
        ("coords", (4, 3), "int32"),
        ("values", (4,), "float32"),
    ]
    assert result.metadata["name"] == "tsdf"
    assert result.metadata["background"] == 0.0


@pytest.mark.parametrize(
    ("arrays", "message"),
    [
        (
            {
                "coords": np.zeros((2, 3), dtype=np.int64),
                "values": np.zeros(2, dtype=np.float32),
            },
            "coords must have dtype int32",
        ),
        (
            {
                "coords": np.zeros((2, 3), dtype=np.int32),
                "values": np.zeros(2, dtype=np.float64),
            },
            "values must have dtype float32",
        ),
        (
            {
                "coords": np.zeros((2, 3), dtype=np.int32),
                "values": np.zeros(3, dtype=np.float32),
            },
            "equal length",
        ),
        (
            {
                "coords": np.zeros((2, 3), dtype=np.int32),
                "values": np.zeros(2, dtype=np.float32),
            },
            "duplicate voxel coordinates",
        ),
    ],
)
def test_openvdb_writer_refuses_unrepresentable_records(
    tmp_path, arrays, message
):
    record = _core.tensor_dict(arrays)
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.write(record, tmp_path / "invalid.vdb")


def test_openvdb_writer_refuses_nonfinite_values(tmp_path):
    record = _core.tensor_dict(
        {
            "coords": np.array([[0, 0, 0]], dtype=np.int32),
            "values": np.array([np.nan], dtype=np.float32),
        }
    )
    with pytest.raises(sceneio.FormatError, match="values must be finite"):
        sceneio.write(record, tmp_path / "nonfinite.vdb")


def test_openvdb_writer_refuses_empty_grid_before_destination_access(tmp_path):
    record = _core.tensor_dict(
        {
            "coords": np.empty((0, 3), dtype=np.int32),
            "values": np.empty(0, dtype=np.float32),
        }
    )
    destination = tmp_path / "empty.vdb"
    with pytest.raises(sceneio.FormatError, match="empty sparse grids"):
        sceneio.write(record, destination)
    assert not destination.exists()


def test_openvdb_existing_destination_survives_provider_failure(
    tmp_path, monkeypatch
):
    record, _coords, _values = _sample()
    path = tmp_path / "preserved.vdb"
    path.write_bytes(b"keep")
    real_provider = tinyvdb

    class FileProxy:
        def __init__(self, file):
            self._file = file

        def __getattr__(self, name):
            return getattr(self._file, name)

        def save(self, path, **kwargs):
            Path(path).write_bytes(b"partial")
            raise RuntimeError("injected failure")

    class ProviderProxy:
        COMPRESS_NONE = real_provider.COMPRESS_NONE
        COMPRESS_ZIP = real_provider.COMPRESS_ZIP
        COMPRESS_ACTIVE_MASK = real_provider.COMPRESS_ACTIVE_MASK

        @staticmethod
        def open(path):
            return FileProxy(real_provider.open(path))

    monkeypatch.setattr(_openvdb, "_require_tinyvdb", ProviderProxy)
    with pytest.raises(RuntimeError, match="injected failure"):
        sceneio.write_openvdb(record, path)

    assert path.read_bytes() == b"keep"
    assert list(tmp_path.iterdir()) == [path]


def test_openvdb_writer_refuses_provider_voxel_loss(tmp_path, monkeypatch):
    record, _coords, _values = _sample()
    path = tmp_path / "preserved.vdb"
    path.write_bytes(b"keep")
    real_provider = tinyvdb

    class GridProxy:
        def active_voxel_count(self):
            return 3

    class FileProxy:
        def __init__(self, file):
            self._file = file

        def __getattr__(self, name):
            return getattr(self._file, name)

        def grid(self, _index):
            return GridProxy()

    class ProviderProxy:
        COMPRESS_NONE = real_provider.COMPRESS_NONE
        COMPRESS_ZIP = real_provider.COMPRESS_ZIP
        COMPRESS_ACTIVE_MASK = real_provider.COMPRESS_ACTIVE_MASK

        @staticmethod
        def open(source):
            return FileProxy(real_provider.open(source))

    monkeypatch.setattr(_openvdb, "_require_tinyvdb", ProviderProxy)
    with pytest.raises(RuntimeError, match=r"preserve every active voxel.*3 of 4"):
        sceneio.write_openvdb(record, path)

    assert path.read_bytes() == b"keep"
    assert list(tmp_path.iterdir()) == [path]


def test_openvdb_license_and_template_provenance_are_distributed():
    root = Path(__file__).parents[2]
    license_text = (root / "LICENSES" / "tinyvdb.txt").read_text(
        encoding="utf-8"
    )
    provenance = (
        root
        / "src"
        / "sceneio"
        / "io"
        / "_assets"
        / "openvdb_float_template.PROVENANCE.txt"
    ).read_text(encoding="utf-8")

    assert "Apache License" in license_text
    assert "f3527f394d09f574fca650ba99648abd1f5b07f7" in provenance
    assert "3ed9464dd24336f9b9589b75267b00297" in provenance
