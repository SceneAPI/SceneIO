"""CV-oriented Zarr v2/v3 tensor-store adapter.

The storage engine is the optional, upstream-optimized ``zarr`` package.
SceneIO owns the supported schema, validation, record mapping, inspection,
partial reads, and path replacement. Importing SceneIO never imports zarr, so
the base package remains NumPy-only.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.model import ArrayInspection, Inspection

_SUPPORTED_TENSOR_KINDS = frozenset({"b", "i", "u", "f"})
_MAX_ARRAYS = 1_000_000
_MAX_RANK = 32


def _require_zarr():
    try:
        import zarr
    except ModuleNotFoundError:
        raise RuntimeError(
            "Zarr support requires the optional dependency; "
            "install sceneio[zarr]"
        ) from None
    return zarr


def _canonical_array(value: object, context: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim > _MAX_RANK:
        raise ValueError(f"{context}: rank exceeds {_MAX_RANK}")
    if array.dtype.fields is not None or array.dtype.subdtype is not None:
        raise ValueError(f"{context}: structured and subarray dtypes are unsupported")
    if array.dtype.kind not in _SUPPORTED_TENSOR_KINDS:
        raise ValueError(
            f"{context}: dtype {array.dtype.name!r} is unsupported; "
            "expected bool, integer, or real floating point"
        )
    if not array.dtype.isnative:
        array = array.byteswap().view(array.dtype.newbyteorder("="))
    # NumPy can expose platform/generic integer dtype classes whose public
    # kind, width, and name match a fixed-width dtype.  Zarr 3.3's data-type
    # inference requires the fixed-width class for some of those aliases.
    # Re-viewing through dtype.str normalizes the class without copying data.
    fixed_dtype = np.dtype(array.dtype.str)
    if type(array.dtype) is not type(fixed_dtype):
        array = array.view(fixed_dtype)
    if array.flags.c_contiguous:
        return array
    return np.array(array, copy=True, order="C", subok=False)


def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("Zarr: tensor names must be non-empty strings")
    path = Path(name)
    if (
        path.is_absolute()
        or "\\" in name
        or name.startswith("/")
        or name.endswith("/")
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError(
            f"Zarr: tensor name {name!r} must be a relative '/'-separated path"
        )
    return name


def _root_attrs(group) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, value in group.attrs.items():
        name = str(raw_name)
        if not isinstance(value, str):
            raise ValueError(
                f"Zarr root attribute {name!r}: expected a string value"
            )
        result[name] = value
    return result


def _array_items(group) -> tuple[tuple[str, object], ...]:
    zarr = _require_zarr()
    result = [
        (name, value)
        for name, value in group.members(max_depth=None)
        if isinstance(value, zarr.Array)
    ]
    if len(result) > _MAX_ARRAYS:
        raise ValueError(f"Zarr: array count exceeds {_MAX_ARRAYS}")
    result.sort(key=lambda item: item[0])
    for name, value in result:
        _validate_name(name)
        if len(value.shape) > _MAX_RANK:
            raise ValueError(f"Zarr array {name!r}: rank exceeds {_MAX_RANK}")
        dtype = np.dtype(value.dtype)
        if (
            dtype.fields is not None
            or dtype.subdtype is not None
            or dtype.kind not in _SUPPORTED_TENSOR_KINDS
        ):
            raise ValueError(
                f"Zarr array {name!r}: unsupported dtype {dtype.name!r}"
            )
    return tuple(result)


def _open_group(path: str | Path):
    zarr = _require_zarr()
    source = Path(path)
    if not source.is_dir():
        raise ValueError("Zarr: expected a directory store")
    return zarr.open_group(source, mode="r", use_consolidated=None)


def _to_tensor_dict(
    group,
    items: tuple[tuple[str, object], ...],
    *,
    slices: Mapping[str, tuple[int, int]] | None = None,
):
    arrays: dict[str, np.ndarray] = {}
    for name, value in items:
        if slices is None or name not in slices:
            decoded = value[...]
        else:
            if len(value.shape) == 0:
                raise ValueError(
                    f"Zarr array {name!r}: a scalar cannot be sliced "
                    "along a leading axis"
                )
            start, stop = slices[name]
            if start < 0 or start >= stop or stop > value.shape[0]:
                raise ValueError(
                    f"Zarr array {name!r}: slice {(start, stop)!r} is "
                    f"outside leading dimension {value.shape[0]}"
                )
            decoded = value[start:stop]
        arrays[name] = _canonical_array(decoded, f"Zarr array {name!r}")
    return _core.tensor_dict(arrays, attrs=_root_attrs(group))


def read_zarr(path: str | Path):
    """Read every supported array in a directory Zarr v2/v3 group."""

    group = _open_group(path)
    return _to_tensor_dict(group, _array_items(group))


def read_zarr_tensors(path: str | Path, names: tuple[str, ...]):
    """Read selected complete arrays without decoding unselected chunks."""

    group = _open_group(path)
    available = dict(_array_items(group))
    selected: list[tuple[str, object]] = []
    seen: set[str] = set()
    for raw_name in names:
        name = _validate_name(raw_name)
        if name in seen:
            raise ValueError(f"Zarr: duplicate tensor selector {name!r}")
        seen.add(name)
        try:
            selected.append((name, available[name]))
        except KeyError:
            raise ValueError(f"Zarr: tensor {name!r} does not exist") from None
    if not selected:
        raise ValueError("Zarr: tensor selection must not be empty")
    return _to_tensor_dict(group, tuple(selected))


def read_zarr_slices(
    path: str | Path,
    selectors: tuple[tuple[str, int, int], ...],
):
    """Read selected leading-axis ranges without decoding other chunks."""

    group = _open_group(path)
    available = dict(_array_items(group))
    selected: list[tuple[str, object]] = []
    slices: dict[str, tuple[int, int]] = {}
    for raw_name, start, stop in selectors:
        name = _validate_name(raw_name)
        if name in slices:
            raise ValueError(f"Zarr: duplicate tensor selector {name!r}")
        try:
            selected.append((name, available[name]))
        except KeyError:
            raise ValueError(f"Zarr: tensor {name!r} does not exist") from None
        slices[name] = (start, stop)
    if not selected:
        raise ValueError("Zarr: tensor slice selection must not be empty")
    return _to_tensor_dict(group, tuple(selected), slices=slices)


def _normalize_chunks(
    chunks: Mapping[str, tuple[int, ...]] | None,
    arrays: Mapping[str, np.ndarray],
) -> dict[str, tuple[int, ...]]:
    if chunks is None:
        return {}
    unknown = set(chunks) - set(arrays)
    if unknown:
        raise ValueError(
            "Zarr: chunk shapes name unknown tensors "
            + ", ".join(sorted(repr(name) for name in unknown))
        )
    result: dict[str, tuple[int, ...]] = {}
    for name, raw_shape in chunks.items():
        try:
            shape = tuple(int(value) for value in raw_shape)
        except (TypeError, ValueError):
            raise ValueError(
                f"Zarr tensor {name!r}: chunk shape must contain integers"
            ) from None
        if len(shape) != arrays[name].ndim or any(value <= 0 for value in shape):
            raise ValueError(
                f"Zarr tensor {name!r}: chunk shape must have "
                f"{arrays[name].ndim} positive dimensions"
            )
        result[name] = shape
    return result


def _replace_directory(temporary: Path, destination: Path) -> None:
    backup: Path | None = None
    if destination.exists():
        if not destination.is_dir():
            raise ValueError(
                f"Zarr: destination {str(destination)!r} exists and is not a directory"
            )
        backup = destination.with_name(
            f".{destination.name}.{os.getpid()}.previous"
        )
        if backup.exists():
            raise ValueError(
                f"Zarr: replacement staging path {str(backup)!r} already exists"
            )
        os.replace(destination, backup)
    try:
        os.replace(temporary, destination)
    except BaseException:
        if backup is not None and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def write_zarr(
    tensors,
    path: str | Path,
    *,
    zarr_format: int = 3,
    chunks: Mapping[str, tuple[int, ...]] | None = None,
) -> None:
    """Write a TensorDict to an optimized directory Zarr v2 or v3 store."""

    if zarr_format not in {2, 3}:
        raise ValueError("Zarr: zarr_format must be 2 or 3")
    if not isinstance(tensors, _core.TensorDict):
        raise TypeError("Zarr: expected a TensorDict")

    tensor_names = tensors.keys()
    arrays = {
        _validate_name(name): _canonical_array(
            tensors[name],
            f"Zarr tensor {name!r}",
        )
        for name in tensor_names
    }
    attrs = dict(tensors.attrs)
    for name, value in attrs.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Zarr: attribute names must be non-empty strings")
        if not isinstance(value, str):
            raise ValueError(f"Zarr: attribute {name!r} must be a string")
    chunk_shapes = _normalize_chunks(chunks, arrays)

    zarr = _require_zarr()
    destination = Path(path)
    destination.parent.mkdir(parents=False, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
    )
    try:
        group = zarr.open_group(
            temporary,
            mode="w",
            zarr_format=zarr_format,
            attributes=attrs,
        )
        for name, array in arrays.items():
            kwargs = {"data": array}
            if name in chunk_shapes:
                kwargs["chunks"] = chunk_shapes[name]
            group.create_array(name, **kwargs)
        _replace_directory(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            shutil.rmtree(temporary)


def inspect_zarr(path: str | Path) -> Inspection:
    """Inspect array metadata without decoding chunk payloads."""

    group = _open_group(path)
    items = _array_items(group)
    byte_size = sum(
        item.stat().st_size
        for item in Path(path).rglob("*")
        if item.is_file()
    )
    zarr_format = int(group.metadata.zarr_format)
    return Inspection(
        format="zarr",
        datatype="tensor_dict",
        byte_size=byte_size,
        count=len(items),
        arrays=tuple(
            ArrayInspection(
                name=name,
                shape=tuple(int(value) for value in array.shape),
                dtype=np.dtype(array.dtype).name,
            )
            for name, array in items
        ),
        metadata={
            "zarr_format": zarr_format,
            "root_attribute_count": len(_root_attrs(group)),
        },
    )


__all__ = [
    "inspect_zarr",
    "read_zarr",
    "read_zarr_slices",
    "read_zarr_tensors",
    "write_zarr",
]
