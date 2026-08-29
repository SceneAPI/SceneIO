"""Numeric CV tables in Apache Parquet and Arrow IPC file containers."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.model import ArrayInspection, Inspection

_SUPPORTED_KINDS = frozenset({"b", "i", "u", "f"})
_SCHEMA_MARKER = b"sceneio.numeric_table.v1"
_ATTR_PREFIX = b"sceneio.attr."


def _require_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.ipc as ipc
        import pyarrow.parquet as pq
    except ModuleNotFoundError:
        raise RuntimeError(
            "Arrow/Parquet support requires the optional dependency; "
            "install sceneio[arrow]"
        ) from None
    return pa, ipc, pq


def _validate_name(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(
            "Arrow table: column names must be non-empty strings without NUL"
        )
    return value


def _canonical_column(value: object, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim not in {1, 2}:
        raise ValueError(
            f"Arrow table column {name!r}: expected rank 1 or 2"
        )
    if array.ndim == 2 and array.shape[1] < 1:
        raise ValueError(
            f"Arrow table column {name!r}: vector width must be positive"
        )
    if (
        array.dtype.fields is not None
        or array.dtype.subdtype is not None
        or array.dtype.kind not in _SUPPORTED_KINDS
    ):
        raise ValueError(
            f"Arrow table column {name!r}: unsupported dtype "
            f"{array.dtype.name!r}"
        )
    if array.dtype.kind == "f" and array.dtype.itemsize not in {4, 8}:
        raise ValueError(
            f"Arrow table column {name!r}: only float32/float64 are supported"
        )
    if not array.dtype.isnative:
        array = array.byteswap().view(array.dtype.newbyteorder("="))
    result = np.ascontiguousarray(array)
    if not result.flags.writeable:
        result = np.array(result, copy=True, order="C")
    return result


def _table_from_tensor_dict(tensors):
    if not isinstance(tensors, _core.TensorDict):
        raise TypeError("Arrow table: expected a TensorDict")
    pa, _ipc, _pq = _require_pyarrow()
    arrays: dict[str, np.ndarray] = {}
    row_count: int | None = None
    for raw_name in tensors:
        name = _validate_name(raw_name)
        array = _canonical_column(tensors[name], name)
        if row_count is None:
            row_count = int(array.shape[0])
        elif array.shape[0] != row_count:
            raise ValueError("Arrow table: all columns must have equal row count")
        arrays[name] = array
    if not arrays:
        raise ValueError("Arrow table: at least one column is required")

    columns = {}
    for name, array in arrays.items():
        if array.ndim == 1:
            columns[name] = pa.array(array)
        else:
            values = pa.array(array.reshape(-1))
            columns[name] = pa.FixedSizeListArray.from_arrays(
                values,
                int(array.shape[1]),
            )
    metadata = {b"sceneio.schema": _SCHEMA_MARKER}
    for name, value in dict(tensors.attrs).items():
        if not isinstance(name, str) or not name or "\x00" in name:
            raise ValueError(
                "Arrow table: attribute names must be non-empty strings "
                "without NUL"
            )
        if not isinstance(value, str):
            raise ValueError(
                f"Arrow table attribute {name!r}: expected a string"
            )
        metadata[_ATTR_PREFIX + name.encode("utf-8")] = value.encode("utf-8")
    return pa.table(columns).replace_schema_metadata(metadata)


def _attrs_from_schema(schema) -> dict[str, str]:
    metadata = schema.metadata or {}
    marker = metadata.get(b"sceneio.schema")
    if marker not in {None, _SCHEMA_MARKER}:
        raise ValueError("Arrow table: unsupported SceneIO schema marker")
    attrs = {}
    for key, value in metadata.items():
        if key.startswith(_ATTR_PREFIX):
            try:
                name = key[len(_ATTR_PREFIX) :].decode("utf-8")
                attrs[name] = value.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(
                    "Arrow table: attribute metadata must be UTF-8"
                ) from None
    return attrs


def _numpy_columns(table) -> dict[str, np.ndarray]:
    pa, _ipc, _pq = _require_pyarrow()
    result: dict[str, np.ndarray] = {}
    for index, field in enumerate(table.schema):
        name = _validate_name(field.name)
        column = table.column(index).combine_chunks()
        field_type = field.type
        if column.null_count:
            raise ValueError(
                f"Arrow table column {name!r}: null values are unsupported"
            )
        if pa.types.is_fixed_size_list(field_type):
            width = int(field_type.list_size)
            values = column.values.to_numpy(zero_copy_only=False)
            array = values.reshape(len(column), width)
        elif (
            pa.types.is_boolean(field_type)
            or pa.types.is_integer(field_type)
            or pa.types.is_floating(field_type)
        ):
            array = column.to_numpy(zero_copy_only=False)
        else:
            raise ValueError(
                f"Arrow table column {name!r}: unsupported type {field_type}"
            )
        result[name] = _canonical_column(array, name)
    return result


def _to_tensor_dict(table):
    return _core.tensor_dict(
        _numpy_columns(table),
        attrs=_attrs_from_schema(table.schema),
    )


def read_parquet(path: str | Path):
    """Read a numeric Parquet table into a TensorDict."""

    _pa, _ipc, pq = _require_pyarrow()
    return _to_tensor_dict(pq.read_table(path, memory_map=True, use_threads=True))


def read_parquet_tensors(path: str | Path, names: tuple[str, ...]):
    """Read selected Parquet columns without decoding other columns."""

    _pa, _ipc, pq = _require_pyarrow()
    selected = tuple(_validate_name(name) for name in names)
    if not selected:
        raise ValueError("Parquet: column selection must not be empty")
    if len(selected) != len(set(selected)):
        raise ValueError("Parquet: duplicate column selector")
    try:
        table = pq.read_table(
            path,
            columns=list(selected),
            memory_map=True,
            use_threads=True,
        )
    except Exception as exc:
        if "No match for FieldRef" in str(exc):
            raise ValueError("Parquet: selected column does not exist") from exc
        raise
    return _to_tensor_dict(table)


def read_arrow_ipc(path: str | Path):
    """Read an Arrow IPC file into a TensorDict."""

    pa, ipc, _pq = _require_pyarrow()
    with pa.memory_map(str(path), "r") as source:
        table = ipc.open_file(source).read_all()
        return _to_tensor_dict(table)


def _temporary_path(destination: Path, suffix: str) -> Path:
    destination.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=suffix,
        dir=destination.parent,
    )
    os.close(descriptor)
    return Path(temporary_name)


def write_parquet(
    tensors,
    path: str | Path,
    *,
    compression: str = "zstd",
) -> None:
    """Write a numeric TensorDict using the optimized Arrow Parquet engine."""

    if compression not in {"none", "snappy", "zstd"}:
        raise ValueError("Parquet: compression must be none, snappy, or zstd")
    table = _table_from_tensor_dict(tensors)
    _pa, _ipc, pq = _require_pyarrow()
    destination = Path(path)
    temporary = _temporary_path(destination, ".parquet.tmp")
    try:
        pq.write_table(
            table,
            temporary,
            compression=None if compression == "none" else compression,
            use_dictionary=False,
            write_statistics=True,
        )
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def write_arrow_ipc(tensors, path: str | Path) -> None:
    """Write an uncompressed random-access Arrow IPC file."""

    table = _table_from_tensor_dict(tensors)
    pa, ipc, _pq = _require_pyarrow()
    destination = Path(path)
    temporary = _temporary_path(destination, ".arrow.tmp")
    try:
        with (
            pa.OSFile(str(temporary), "wb") as sink,
            ipc.new_file(sink, table.schema) as writer,
        ):
            writer.write_table(table)
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _inspection_from_schema(
    path: Path,
    *,
    format_id: str,
    schema,
    row_count: int,
    metadata: dict[str, int | str],
) -> Inspection:
    pa, _ipc, _pq = _require_pyarrow()
    arrays = []
    for field in schema:
        if pa.types.is_fixed_size_list(field.type):
            value_type = field.type.value_type
            shape = (row_count, int(field.type.list_size))
        else:
            value_type = field.type
            shape = (row_count,)
        if not (
            pa.types.is_boolean(value_type)
            or pa.types.is_integer(value_type)
            or pa.types.is_floating(value_type)
        ):
            raise ValueError(
                f"Arrow table column {field.name!r}: unsupported type {field.type}"
            )
        arrays.append(
            ArrayInspection(
                _validate_name(field.name),
                shape,
                str(value_type),
            )
        )
    _attrs_from_schema(schema)
    return Inspection(
        format=format_id,
        datatype="numeric_table",
        byte_size=path.stat().st_size,
        shape=(row_count, len(arrays)),
        count=row_count,
        arrays=tuple(arrays),
        metadata=metadata,
    )


def inspect_parquet(path: str | Path) -> Inspection:
    """Inspect Parquet footer/schema metadata without reading columns."""

    _pa, _ipc, pq = _require_pyarrow()
    source = Path(path)
    parquet = pq.ParquetFile(source)
    try:
        return _inspection_from_schema(
            source,
            format_id="parquet",
            schema=parquet.schema_arrow,
            row_count=int(parquet.metadata.num_rows),
            metadata={
                "column_count": parquet.metadata.num_columns,
                "row_group_count": parquet.metadata.num_row_groups,
            },
        )
    finally:
        parquet.close()


def inspect_arrow_ipc(path: str | Path) -> Inspection:
    """Inspect Arrow IPC schema and batch headers without materializing columns."""

    pa, ipc, _pq = _require_pyarrow()
    source_path = Path(path)
    with pa.memory_map(str(source_path), "r") as source:
        reader = ipc.open_file(source)
        row_count = sum(
            int(reader.get_batch(index).num_rows)
            for index in range(reader.num_record_batches)
        )
        schema = reader.schema
        batch_count = reader.num_record_batches
    return _inspection_from_schema(
        source_path,
        format_id="arrow_ipc",
        schema=schema,
        row_count=row_count,
        metadata={
            "column_count": len(schema),
            "record_batch_count": batch_count,
        },
    )


__all__ = [
    "inspect_arrow_ipc",
    "inspect_parquet",
    "read_arrow_ipc",
    "read_parquet",
    "read_parquet_tensors",
    "write_arrow_ipc",
    "write_parquet",
]
