"""Bounded sparse scalar-volume I/O through the optional TinyVDB provider."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.model import ArrayInspection, Inspection

_TREE_TYPE = "Tree_float_5_4_3"
_SCHEMA = "sceneio.sparse_scalar_grid.v1"
_TEMPLATE = Path(__file__).with_name("_assets") / "openvdb_float_template.vdb"
_IDENTITY_MATRIX = np.eye(4, dtype=np.float64)


def _require_tinyvdb():
    try:
        import tinyvdb
    except ModuleNotFoundError:
        raise RuntimeError(
            "OpenVDB support requires the optional dependency; "
            "install sceneio[openvdb]"
        ) from None
    return tinyvdb


def _close(file) -> None:
    with suppress(Exception):
        file.close()


def _open_single_grid(path: str | os.PathLike[str]):
    tinyvdb = _require_tinyvdb()
    file = tinyvdb.open(os.fspath(path))
    try:
        if file.grid_count != 1:
            raise ValueError(
                "OpenVDB: the bounded profile requires exactly one grid"
            )
        if file.grid_type_name(0) != _TREE_TYPE:
            raise ValueError(
                "OpenVDB: only float32 scalar Tree_float_5_4_3 grids "
                "are supported"
            )
        file.read_grids()
        grid = file.grid(0)
        if int(grid.active_voxel_count()) == 0:
            raise ValueError(
                "OpenVDB: empty grids are unsupported because TinyVDB 0.9 "
                "does not preserve their authored transform"
            )
        transform = grid.transform
        matrix = np.asarray(transform.get("matrix"), dtype=np.float64)
        if matrix.shape != (4, 4) or not np.array_equal(
            matrix, _IDENTITY_MATRIX
        ):
            raise ValueError(
                "OpenVDB: only an identity index-to-world transform is "
                "supported"
            )
        if float(grid.float_background()) != 0.0:
            raise ValueError(
                "OpenVDB: only a zero-background scalar grid is supported"
            )
        metadata = dict(grid.metadata)
        grid_class = str(metadata.get("class", "unknown"))
        if grid_class not in {"unknown", "fog volume"}:
            raise ValueError(
                "OpenVDB: only unclassified or 'fog volume' scalar grids "
                "are supported"
            )
        return file, grid, metadata
    except Exception:
        _close(file)
        raise


def _attrs(name: str) -> dict[str, str]:
    return {
        "sceneio.schema": _SCHEMA,
        "name": name,
        "background": "0",
        "index_to_world": "identity",
    }


def _validate_record(record) -> tuple[np.ndarray, np.ndarray, str]:
    if not isinstance(record, _core.TensorDict):
        raise TypeError("OpenVDB: expected a TensorDict")
    if record.keys() != ["coords", "values"]:
        raise ValueError(
            "OpenVDB: expected exactly 'coords' and 'values' tensors"
        )
    coords = np.asarray(record["coords"])
    values = np.asarray(record["values"])
    if coords.dtype != np.int32 or coords.ndim != 2 or coords.shape[1:] != (3,):
        raise ValueError("OpenVDB: coords must have dtype int32 and shape (N, 3)")
    if values.dtype != np.float32 or values.ndim != 1:
        raise ValueError("OpenVDB: values must have dtype float32 and shape (N,)")
    if len(coords) != len(values):
        raise ValueError("OpenVDB: coords and values must have equal length")
    if len(coords) == 0:
        raise ValueError("OpenVDB: empty sparse grids are unsupported")
    if values.size and not np.isfinite(values).all():
        raise ValueError("OpenVDB: values must be finite")
    if len(coords) and len(np.unique(coords, axis=0)) != len(coords):
        raise ValueError("OpenVDB: duplicate voxel coordinates are ambiguous")

    attrs = dict(record.attrs)
    allowed = {
        "sceneio.schema",
        "name",
        "background",
        "index_to_world",
    }
    unknown = sorted(set(attrs) - allowed)
    if unknown:
        raise ValueError(
            "OpenVDB: unsupported attributes: " + ", ".join(unknown)
        )
    expected = {
        "sceneio.schema": _SCHEMA,
        "background": "0",
        "index_to_world": "identity",
    }
    for key, expected_value in expected.items():
        if attrs.get(key, expected_value) != expected_value:
            raise ValueError(
                f"OpenVDB: attribute {key!r} must be {expected_value!r}"
            )
    name = attrs.get("name", "density")
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError(
            "OpenVDB: grid name must be a non-empty string without NUL"
        )
    return (
        np.ascontiguousarray(coords),
        np.ascontiguousarray(values),
        name,
    )


def read_openvdb(path: str | os.PathLike[str]):
    """Read one identity-transform float32 fog grid as a sparse TensorDict."""

    file, grid, _metadata = _open_single_grid(path)
    try:
        sparse = grid.to_sparse()
        count = int(sparse["count"])
        coords = np.frombuffer(sparse["coords"], dtype=np.int32).copy()
        values = np.frombuffer(sparse["values"], dtype=np.float32).copy()
        if coords.size != count * 3 or values.size != count:
            raise ValueError("OpenVDB: inconsistent sparse payload lengths")
        return _core.tensor_dict(
            {
                "coords": coords.reshape(count, 3),
                "values": values,
            },
            attrs=_attrs(str(grid.name)),
        )
    finally:
        _close(file)


def inspect_openvdb(path: str | os.PathLike[str]) -> Inspection:
    """Inspect one supported VDB grid without materializing its voxels."""

    file, grid, metadata = _open_single_grid(path)
    try:
        count = int(grid.active_voxel_count())
        bbox = grid.active_bbox()
        bbox_min = tuple(int(value) for value in bbox[0]) if count else ()
        bbox_max = tuple(int(value) for value in bbox[1]) if count else ()
        return Inspection(
            format="openvdb",
            payload_kind="sparse_volume",
            byte_size=Path(path).stat().st_size,
            count=count,
            arrays=(
                ArrayInspection("coords", (count, 3), "int32"),
                ArrayInspection("values", (count,), "float32"),
            ),
            metadata={
                "name": str(grid.name),
                "grid_class": str(metadata.get("class", "unknown")),
                "background": float(grid.float_background()),
                "bbox_min": bbox_min,
                "bbox_max": bbox_max,
            },
        )
    finally:
        _close(file)


def write_openvdb(
    record,
    path: str | os.PathLike[str],
    *,
    compression: str = "zip_active_mask",
) -> None:
    """Write a bounded sparse float32 fog grid transactionally."""

    coords, values, name = _validate_record(record)
    tinyvdb = _require_tinyvdb()
    compression_flags = {
        "none": tinyvdb.COMPRESS_NONE,
        "zip": tinyvdb.COMPRESS_ZIP,
        "zip_active_mask": (
            tinyvdb.COMPRESS_ZIP | tinyvdb.COMPRESS_ACTIVE_MASK
        ),
    }
    try:
        selected = compression_flags[compression]
    except KeyError:
        raise ValueError(
            "OpenVDB: compression must be 'none', 'zip', or "
            "'zip_active_mask'"
        ) from None
    if not _TEMPLATE.is_file():
        raise RuntimeError("OpenVDB: packaged float-grid template is missing")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(fd)
    temporary = Path(temporary_name)
    file = tinyvdb.open(os.fspath(_TEMPLATE))
    try:
        file.read_grids()
        file.replace_grid_from_sparse(
            0,
            coords,
            values,
            name,
            0.0,
        )
        rebuilt_count = int(file.grid(0).active_voxel_count())
        if rebuilt_count != len(coords):
            raise RuntimeError(
                "OpenVDB: provider did not preserve every active voxel "
                f"({rebuilt_count} of {len(coords)})"
            )
        file.save(os.fspath(temporary), compression=selected)
        os.replace(temporary, destination)
    finally:
        _close(file)
        with suppress(FileNotFoundError):
            temporary.unlink()


__all__ = ["inspect_openvdb", "read_openvdb", "write_openvdb"]
