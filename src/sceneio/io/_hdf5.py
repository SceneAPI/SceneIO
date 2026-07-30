"""Repository-owned HDF5 and hloc schema adapters.

The storage engine is the optional, upstream-optimized ``h5py`` package.
SceneIO owns the supported schema, validation, model mapping, partial reads,
inspection, and transactional path replacement. Importing SceneIO never
imports h5py, so the base package remains NumPy-only.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.model import ArrayInspection, Inspection

HDF5_AVAILABLE = importlib.util.find_spec("h5py") is not None
HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
_SCENEIO_FORMAT_ATTR = "sceneio_format"
_SCENEIO_SCHEMA_ATTR = "sceneio_schema_version"
_RESERVED_ROOT_ATTRS = frozenset({_SCENEIO_FORMAT_ATTR, _SCENEIO_SCHEMA_ATTR})
_SUPPORTED_FEATURE_DATASETS = frozenset(
    {"keypoints", "descriptors", "scores", "image_size"}
)
_SUPPORTED_MATCH_DATASETS = frozenset({"matches0", "matching_scores0"})
_SUPPORTED_DESCRIPTOR_DTYPES = frozenset(
    {"uint8", "int8", "float16", "float32", "float64"}
)
_SUPPORTED_TENSOR_KINDS = frozenset({"b", "i", "u", "f"})
_MAX_DATASETS = 1_000_000
_MAX_RANK = 32


def _require_h5py():
    try:
        import h5py
    except ModuleNotFoundError:
        raise RuntimeError(
            "HDF5 support requires the optional dependency; "
            "install sceneio[hdf5]"
        ) from None
    return h5py


def _text_attr(value: object, context: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{context}: expected UTF-8 text") from exc
    if isinstance(value, np.str_):
        return str(value)
    if isinstance(value, np.bytes_):
        return _text_attr(bytes(value), context)
    raise ValueError(f"{context}: expected a string attribute")


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
    if array.flags.c_contiguous:
        return array
    return np.array(array, copy=True, order="C", subok=False)


def _has_duplicate_indices(values: np.ndarray) -> bool:
    if len(values) < 2:
        return False
    if np.all(values[1:] > values[:-1]):
        return False
    ordered = np.sort(values)
    return bool(np.any(ordered[1:] == ordered[:-1]))


def _unsupported_link(name: str) -> None:
    raise ValueError(
        f"HDF5 link {name!r}: soft, external, and aliased "
        "hard links are unsupported"
    )


def _validate_dataset_storage(dataset, context: str) -> None:
    if dataset.is_virtual:
        raise ValueError(f"{context}: virtual datasets are unsupported")


def _validate_generic_dataset_metadata(dataset, context: str) -> None:
    _validate_dataset_storage(dataset, context)
    _validate_dataset_attrs(dataset, context=context)
    if len(dataset.shape) > _MAX_RANK:
        raise ValueError(f"{context}: rank exceeds {_MAX_RANK}")
    if (
        dataset.dtype.fields is not None
        or dataset.dtype.subdtype is not None
        or dataset.dtype.kind not in _SUPPORTED_TENSOR_KINDS
    ):
        raise ValueError(
            f"{context}: unsupported dtype {dataset.dtype.name!r}"
        )


def _dataset_items(
    handle,
    *,
    generic: bool = False,
) -> tuple[tuple[str, Any], ...]:
    h5py = _require_h5py()
    result: list[tuple[str, Any]] = []
    too_many = False
    virtual: list[str] = []
    attributed_groups: list[str] = []
    hard_targets: dict[int, str] = {}
    failure: Exception | None = None

    def visit(name: str, link: object) -> bool | None:
        nonlocal failure, too_many
        try:
            if isinstance(link, (h5py.SoftLink, h5py.ExternalLink)):
                _unsupported_link(name)
            value = handle[name]
            address = int(h5py.h5o.get_info(value.id).addr)
            if address in hard_targets:
                _unsupported_link(name)
            hard_targets[address] = name
            if (
                generic
                and isinstance(value, h5py.Group)
                and set(value.attrs)
            ):
                attributed_groups.append(name)
                return True
            if isinstance(value, h5py.Dataset):
                if value.is_virtual:
                    virtual.append(name)
                    return True
                if generic:
                    _validate_generic_dataset_metadata(
                        value,
                        f"HDF5 dataset {name!r}",
                    )
                result.append((name, value))
                if len(result) > _MAX_DATASETS:
                    too_many = True
                    return True
            return None
        except Exception as exc:
            failure = exc
            return True

    handle.visititems_links(visit)
    if failure is not None:
        raise failure
    if virtual:
        raise ValueError(
            f"HDF5 dataset {virtual[0]!r}: virtual datasets are unsupported"
        )
    if attributed_groups:
        raise ValueError(
            f"HDF5 group {attributed_groups[0]!r}: attributes outside the "
            "file root are unsupported"
        )
    if too_many:
        raise ValueError(f"HDF5: dataset count exceeds {_MAX_DATASETS}")
    return tuple(result)


def _root_attrs(handle, *, expected_format: str | None = None) -> dict[str, str]:
    if _SCENEIO_SCHEMA_ATTR in handle.attrs:
        schema = np.asarray(handle.attrs[_SCENEIO_SCHEMA_ATTR])
        if (
            schema.shape != ()
            or schema.dtype.kind not in {"i", "u"}
            or int(schema) != 1
        ):
            raise ValueError(
                "HDF5: sceneio_schema_version must be the integer 1"
            )
    result: dict[str, str] = {}
    for raw_name, value in handle.attrs.items():
        name = str(raw_name)
        if name in _RESERVED_ROOT_ATTRS:
            continue
        result[name] = _text_attr(value, f"HDF5 root attribute {name!r}")
    if expected_format is not None and _SCENEIO_FORMAT_ATTR in handle.attrs:
        declared = _text_attr(
            handle.attrs[_SCENEIO_FORMAT_ATTR],
            f"HDF5 root attribute {_SCENEIO_FORMAT_ATTR!r}",
        )
        if declared != expected_format:
            raise ValueError(
                f"HDF5: file declares format {declared!r}, "
                f"not {expected_format!r}"
            )
    return result


def _validate_hloc_root(handle, format_id: str) -> None:
    attrs = _root_attrs(handle, expected_format=format_id)
    if attrs:
        raise ValueError(
            f"{format_id}: unsupported HDF5 root attributes "
            + ", ".join(sorted(repr(name) for name in attrs))
        )


def _validate_dataset_attrs(
    dataset,
    *,
    allowed: frozenset[str] = frozenset(),
    context: str,
) -> None:
    unknown = set(dataset.attrs) - allowed
    if unknown:
        raise ValueError(
            f"{context}: unsupported attributes "
            + ", ".join(sorted(repr(str(name)) for name in unknown))
        )


def _write_root_attrs(handle, attrs: Mapping[str, str], format_id: str) -> None:
    handle.attrs[_SCENEIO_FORMAT_ATTR] = format_id
    handle.attrs[_SCENEIO_SCHEMA_ATTR] = np.uint32(1)
    for name, value in attrs.items():
        if not isinstance(name, str) or not name:
            raise ValueError("HDF5: TensorDict attribute names must be non-empty strings")
        if name in _RESERVED_ROOT_ATTRS:
            raise ValueError(f"HDF5: attribute name {name!r} is reserved")
        if not isinstance(value, str):
            raise ValueError(f"HDF5: attribute {name!r} must be a string")
        handle.attrs[name] = value


def _atomic_hdf5_write(path: str | Path, callback, *, libver: str | None = None) -> None:
    h5py = _require_h5py()
    destination = Path(path)
    parent = destination.parent
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        kwargs = {"mode": "w", "track_order": True}
        if libver is not None:
            kwargs["libver"] = libver
        with h5py.File(temporary, **kwargs) as handle:
            callback(handle)
            handle.flush()
        os.replace(temporary, destination)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _validate_dataset_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("HDF5: tensor names must be non-empty strings")
    if name.startswith("/") or name.endswith("/") or "//" in name:
        raise ValueError(
            f"HDF5: tensor name {name!r} must be a normalized relative path"
        )
    if any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError(f"HDF5: tensor name {name!r} contains an invalid component")
    return name


def _selected_datasets(
    handle,
    names: tuple[str, ...],
) -> tuple[tuple[str, Any], ...]:
    h5py = _require_h5py()
    result: list[tuple[str, Any]] = []
    hard_targets: dict[int, str] = {}
    for raw_name in names:
        name = _validate_dataset_name(raw_name)
        value = handle
        parts = name.split("/")
        for index, part in enumerate(parts):
            link = value.get(part, getlink=True)
            selected_path = "/".join(parts[: index + 1])
            if link is None:
                raise ValueError(f"HDF5: no dataset named {name!r}")
            if isinstance(link, (h5py.SoftLink, h5py.ExternalLink)):
                _unsupported_link(selected_path)
            value = value[part]
            if index != len(parts) - 1:
                if not isinstance(value, h5py.Group):
                    raise ValueError(f"HDF5: no dataset named {name!r}")
                if set(value.attrs):
                    raise ValueError(
                        f"HDF5 group {selected_path!r}: attributes outside "
                        "the file root are unsupported"
                    )
        if not isinstance(value, h5py.Dataset):
            raise ValueError(f"HDF5: no dataset named {name!r}")
        _validate_generic_dataset_metadata(value, f"HDF5 dataset {name!r}")
        address = int(h5py.h5o.get_info(value.id).addr)
        previous = hard_targets.get(address)
        if previous is not None and previous != name:
            _unsupported_link(name)
        hard_targets[address] = name
        result.append((name, value))
    return tuple(result)


def read_hdf5(path: str | Path):
    """Read supported numeric HDF5 datasets into a native ``TensorDict``."""

    h5py = _require_h5py()
    arrays: dict[str, np.ndarray] = {}
    with h5py.File(path, "r") as handle:
        attrs = _root_attrs(handle, expected_format="hdf5")
        for name, dataset in _dataset_items(handle, generic=True):
            arrays[name] = _canonical_array(dataset[...], f"HDF5 dataset {name!r}")
    return _core.tensor_dict(arrays, attrs)


def read_hdf5_tensors(path: str | Path, names: tuple[str, ...]):
    """Read complete selected datasets without loading unselected datasets."""

    h5py = _require_h5py()
    arrays: dict[str, np.ndarray] = {}
    with h5py.File(path, "r") as handle:
        attrs = _root_attrs(handle, expected_format="hdf5")
        for name, dataset in _selected_datasets(handle, names):
            arrays[name] = _canonical_array(
                dataset[...],
                f"HDF5 dataset {name!r}",
            )
    return _core.tensor_dict(arrays, attrs)


def read_hdf5_slices(
    path: str | Path,
    selections: tuple[tuple[str, int, int], ...],
):
    """Read selected leading-axis ranges directly through HDF5 hyperslabs."""

    h5py = _require_h5py()
    arrays: dict[str, np.ndarray] = {}
    with h5py.File(path, "r") as handle:
        attrs = _root_attrs(handle, expected_format="hdf5")
        names = tuple(raw_name for raw_name, _, _ in selections)
        datasets = _selected_datasets(handle, names)
        for (name, dataset), (_, start, stop) in zip(
            datasets,
            selections,
            strict=True,
        ):
            if dataset.ndim == 0:
                raise ValueError(f"HDF5: scalar dataset {name!r} cannot be sliced")
            if stop > dataset.shape[0]:
                raise ValueError(
                    f"HDF5: slice [{start}:{stop}] exceeds dataset "
                    f"{name!r} leading extent {dataset.shape[0]}"
                )
            arrays[name] = _canonical_array(
                dataset[start:stop],
                f"HDF5 dataset {name!r}",
            )
    return _core.tensor_dict(arrays, attrs)


def write_hdf5(value, path: str | Path) -> None:
    """Write a native ``TensorDict`` as flat numeric datasets and text attrs."""

    if not isinstance(value, _core.TensorDict):
        if not isinstance(value, Mapping):
            raise TypeError("HDF5 writer expects TensorDict or a mapping of arrays")
        value = _core.tensor_dict(
            {
                _validate_dataset_name(name): _canonical_array(
                    array,
                    f"HDF5 tensor {name!r}",
                )
                for name, array in value.items()
            }
        )

    names = tuple(value.keys())
    if len(names) > _MAX_DATASETS:
        raise ValueError(f"HDF5: dataset count exceeds {_MAX_DATASETS}")
    normalized = tuple(_validate_dataset_name(name) for name in names)
    if len(normalized) != len(set(normalized)):
        raise ValueError("HDF5: tensor names must be unique")

    def emit(handle) -> None:
        _write_root_attrs(handle, value.attrs, "hdf5")
        for name in normalized:
            array = _canonical_array(value[name], f"HDF5 tensor {name!r}")
            handle.create_dataset(name, data=array)

    _atomic_hdf5_write(path, emit)


def inspect_hdf5(path: str | Path) -> Inspection:
    """Inspect HDF5 dataset metadata without reading dataset payloads."""

    h5py = _require_h5py()
    arrays: list[ArrayInspection] = []
    with h5py.File(path, "r") as handle:
        attrs = _root_attrs(handle, expected_format="hdf5")
        for name, dataset in _dataset_items(handle, generic=True):
            arrays.append(
                ArrayInspection(name, tuple(int(v) for v in dataset.shape), dataset.dtype.name)
            )
    return Inspection(
        format="hdf5",
        datatype="tensor_dict",
        byte_size=Path(path).stat().st_size,
        count=len(arrays),
        arrays=tuple(arrays),
        metadata={"attribute_count": len(attrs)},
    )


@dataclass(frozen=True, slots=True)
class HlocFeatureStore(Mapping[str, _core.FeatureSet]):
    """Ordered hloc image names mapped to native ``FeatureSet`` records."""

    features: Mapping[str, _core.FeatureSet]
    uncertainties: Mapping[str, float | None] | None = None

    def __post_init__(self) -> None:
        features = dict(self.features)
        if not features:
            raise ValueError("hloc features: at least one image group is required")
        for name, feature in features.items():
            _validate_hloc_image_name(name)
            if not isinstance(feature, _core.FeatureSet):
                raise TypeError(
                    f"hloc features: {name!r} must map to FeatureSet, "
                    f"got {type(feature).__name__}"
                )
        raw_uncertainties = (
            {name: None for name in features}
            if self.uncertainties is None
            else dict(self.uncertainties)
        )
        if set(raw_uncertainties) != set(features):
            raise ValueError(
                "hloc features: uncertainty keys must match feature image names"
            )
        uncertainties: dict[str, float | None] = {}
        for name, value in raw_uncertainties.items():
            if value is None:
                uncertainties[name] = None
                continue
            number = float(value)
            if not np.isfinite(number) or number < 0:
                raise ValueError(
                    f"hloc features: uncertainty for {name!r} must be finite "
                    "and non-negative"
                )
            uncertainties[name] = number
        object.__setattr__(self, "features", MappingProxyType(features))
        object.__setattr__(
            self,
            "uncertainties",
            MappingProxyType(uncertainties),
        )

    def __getitem__(self, name: str) -> _core.FeatureSet:
        return self.features[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self.features)

    def __len__(self) -> int:
        return len(self.features)


@dataclass(frozen=True, slots=True)
class HlocMatchStore:
    """Native ``MatchGraph`` plus lossless hloc endpoint and dense-row metadata."""

    image_names: tuple[str, ...]
    pair_names: tuple[tuple[str, str], ...]
    source_keypoint_counts: tuple[int, ...]
    match_dtypes: tuple[str, ...]
    score_dtypes: tuple[str | None, ...]
    graph: _core.MatchGraph

    def __post_init__(self) -> None:
        image_names = tuple(self.image_names)
        pair_names = tuple(tuple(pair) for pair in self.pair_names)
        source_counts = tuple(int(value) for value in self.source_keypoint_counts)
        match_dtypes = tuple(self.match_dtypes)
        score_dtypes = tuple(self.score_dtypes)
        if not isinstance(self.graph, _core.MatchGraph):
            raise TypeError("hloc matches: graph must be MatchGraph")
        if len(image_names) != len(set(image_names)):
            raise ValueError("hloc matches: image names must be unique")
        for name in image_names:
            _validate_hloc_image_name(name)
        pair_count = int(self.graph.num_pairs)
        if not (
            len(pair_names)
            == len(source_counts)
            == len(match_dtypes)
            == len(score_dtypes)
            == pair_count
        ):
            raise ValueError(
                "hloc matches: pair metadata lengths must equal graph pair count"
            )
        if len(pair_names) != len(set(frozenset(pair) for pair in pair_names)):
            raise ValueError("hloc matches: unordered image pairs must be unique")
        ids = {name: index + 1 for index, name in enumerate(image_names)}
        image_pairs = np.asarray(self.graph.image_pairs)
        offsets = np.asarray(self.graph.match_offsets)
        score_presence = np.asarray(self.graph.match_score_present)
        for index, pair in enumerate(pair_names):
            if len(pair) != 2 or pair[0] == pair[1]:
                raise ValueError(
                    "hloc matches: pair names must contain two distinct images"
                )
            for name in pair:
                if name not in ids:
                    raise ValueError(
                        f"hloc matches: pair references unknown image {name!r}"
                    )
            expected = sorted((ids[pair[0]], ids[pair[1]]))
            if image_pairs[index].tolist() != expected:
                raise ValueError(
                    f"hloc matches: graph pair {index} disagrees with endpoint names"
                )
            if source_counts[index] < 0:
                raise ValueError("hloc matches: source keypoint counts must be non-negative")
            if match_dtypes[index] not in {"int16", "int32", "int64"}:
                raise ValueError(
                    "hloc matches: matches0 dtype must be int16, int32, or int64"
                )
            score_dtype = score_dtypes[index]
            if score_dtype not in {None, "float16", "float32"}:
                raise ValueError(
                    "hloc matches: score dtype must be float16, float32, or None"
                )
            if (score_dtype is not None) != bool(score_presence[index]):
                raise ValueError(
                    f"hloc matches: score dtype presence disagrees for pair {pair!r}"
                )
            begin, end = int(offsets[index]), int(offsets[index + 1])
            matches = np.asarray(self.graph.matches)[begin:end]
            source_column = 0 if ids[pair[0]] < ids[pair[1]] else 1
            if len(matches) and int(matches[:, source_column].max()) >= source_counts[index]:
                raise ValueError(
                    f"hloc matches: source index exceeds dense extent for pair {pair!r}"
                )
        object.__setattr__(self, "image_names", image_names)
        object.__setattr__(self, "pair_names", pair_names)
        object.__setattr__(self, "source_keypoint_counts", source_counts)
        object.__setattr__(self, "match_dtypes", match_dtypes)
        object.__setattr__(self, "score_dtypes", score_dtypes)

    def __len__(self) -> int:
        return len(self.pair_names)


def _validate_hloc_image_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("hloc: image names must be non-empty strings")
    normalized = name.replace("\\", "/")
    if normalized != name or name.startswith("/") or name.endswith("/"):
        raise ValueError(f"hloc: image name {name!r} must be a relative POSIX path")
    if any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError(f"hloc: image name {name!r} contains an invalid component")
    return name


def _feature_groups(handle) -> tuple[tuple[str, Any], ...]:
    h5py = _require_h5py()
    groups: dict[str, Any] = {}
    for _name, dataset in _dataset_items(handle):
        parent = dataset.parent
        parent_name = parent.name.strip("/")
        groups[parent_name] = parent
    result: list[tuple[str, Any]] = []
    for name in sorted(groups):
        group = groups[name]
        datasets = {
            key for key, value in group.items() if isinstance(value, h5py.Dataset)
        }
        if not datasets:
            continue
        unknown = datasets - _SUPPORTED_FEATURE_DATASETS
        if unknown or "keypoints" not in datasets or "image_size" not in datasets:
            rendered = ", ".join(sorted(unknown or datasets))
            raise ValueError(
                f"hloc features: group {name!r} is not a supported local-feature "
                f"group ({rendered})"
            )
        result.append((name, group))
    if not result:
        raise ValueError("hloc features: no local-feature image groups found")
    return tuple(result)


def _validate_feature_group_metadata(name: str, group) -> int:
    _validate_hloc_image_name(name)
    if set(group.attrs):
        raise ValueError(
            f"hloc features: group {name!r} has unsupported attributes"
        )
    keypoints = group["keypoints"]
    if (
        keypoints.ndim != 2
        or keypoints.shape[1] != 2
        or keypoints.dtype.name not in {"float16", "float32"}
    ):
        raise ValueError(
            f"hloc features: {name!r}/keypoints must be float16/float32 (N,2)"
        )
    _validate_dataset_attrs(
        keypoints,
        allowed=frozenset({"uncertainty"}),
        context=f"hloc features: {name!r}/keypoints",
    )
    if "uncertainty" in keypoints.attrs:
        uncertainty = np.asarray(keypoints.attrs["uncertainty"])
        if (
            uncertainty.shape != ()
            or not np.isfinite(float(uncertainty))
            or float(uncertainty) < 0
        ):
            raise ValueError(
                f"hloc features: {name!r} uncertainty must be a finite, "
                "non-negative scalar"
            )

    image_size = group["image_size"]
    if (
        image_size.shape != (2,)
        or image_size.dtype.kind not in {"i", "u"}
    ):
        raise ValueError(
            f"hloc features: {name!r}/image_size must be two positive integers"
        )
    _validate_dataset_attrs(
        image_size,
        context=f"hloc features: {name!r}/image_size",
    )
    size_values = np.asarray(image_size[...])
    if np.any(size_values <= 0):
        raise ValueError(
            f"hloc features: {name!r}/image_size must be two positive integers"
        )

    count = int(keypoints.shape[0])
    if "descriptors" in group:
        descriptors = group["descriptors"]
        if (
            descriptors.ndim != 2
            or descriptors.shape[1] != count
            or descriptors.dtype.name not in _SUPPORTED_DESCRIPTOR_DTYPES
        ):
            raise ValueError(
                f"hloc features: {name!r}/descriptors must be supported "
                "dtype with shape (D,N)"
            )
        _validate_dataset_attrs(
            descriptors,
            context=f"hloc features: {name!r}/descriptors",
        )
    if "scores" in group:
        scores = group["scores"]
        if (
            scores.shape != (count,)
            or scores.dtype.name not in {"float16", "float32"}
        ):
            raise ValueError(
                f"hloc features: {name!r}/scores must be float16/float32 (N,)"
            )
        _validate_dataset_attrs(
            scores,
            context=f"hloc features: {name!r}/scores",
        )
    return count


def read_hloc_features(path: str | Path) -> HlocFeatureStore:
    """Read the documented hloc local-feature layout."""

    h5py = _require_h5py()
    features: dict[str, _core.FeatureSet] = {}
    uncertainties: dict[str, float | None] = {}
    with h5py.File(path, "r", libver="latest") as handle:
        _validate_hloc_root(handle, "hloc_features")
        for name, group in _feature_groups(handle):
            _validate_feature_group_metadata(name, group)
            keypoint_dataset = group["keypoints"]
            keypoints = np.asarray(keypoint_dataset[...])
            if (
                keypoints.ndim != 2
                or keypoints.shape[1] != 2
                or keypoints.dtype.name not in {"float16", "float32"}
            ):
                raise ValueError(
                    f"hloc features: {name!r}/keypoints must be "
                    "float16/float32 (N,2)"
                )
            keypoints = np.ascontiguousarray(keypoints, dtype=np.float32)
            if not np.isfinite(keypoints).all():
                raise ValueError(f"hloc features: {name!r}/keypoints must be finite")
            image_size = np.asarray(group["image_size"][...])
            if (
                image_size.shape != (2,)
                or image_size.dtype.kind not in {"i", "u"}
                or np.any(image_size <= 0)
            ):
                raise ValueError(
                    f"hloc features: {name!r}/image_size must be two positive integers"
                )
            width, height = (int(image_size[0]), int(image_size[1]))
            if width > 0xFFFF_FFFF_FFFF_FFFF or height > 0xFFFF_FFFF_FFFF_FFFF:
                raise ValueError(f"hloc features: {name!r}/image_size is too large")

            descriptors: np.ndarray | None = None
            if "descriptors" in group:
                source = np.asarray(group["descriptors"][...])
                if (
                    source.ndim != 2
                    or source.shape[1] != keypoints.shape[0]
                    or source.dtype.name not in _SUPPORTED_DESCRIPTOR_DTYPES
                ):
                    raise ValueError(
                        f"hloc features: {name!r}/descriptors must be supported "
                        "dtype with shape (D,N)"
                    )
                descriptors = np.ascontiguousarray(source.T)
                if descriptors.dtype.kind == "f" and not np.isfinite(descriptors).all():
                    raise ValueError(
                        f"hloc features: {name!r}/descriptors must be finite"
                    )

            scores: np.ndarray | None = None
            if "scores" in group:
                source_scores = np.asarray(group["scores"][...])
                if (
                    source_scores.shape != (keypoints.shape[0],)
                    or source_scores.dtype.name not in {"float16", "float32"}
                ):
                    raise ValueError(
                        f"hloc features: {name!r}/scores must be "
                        "float16/float32 (N,)"
                    )
                scores = np.ascontiguousarray(source_scores, dtype=np.float32)
                if not np.isfinite(scores).all():
                    raise ValueError(f"hloc features: {name!r}/scores must be finite")

            uncertainty: float | None = None
            if "uncertainty" in keypoint_dataset.attrs:
                raw_uncertainty = np.asarray(keypoint_dataset.attrs["uncertainty"])
                uncertainty = float(raw_uncertainty)

            features[name] = _core.feature_set(
                keypoints,
                descriptors,
                scores,
                image_name=name,
                image_size=(width, height),
            )
            uncertainties[name] = uncertainty
    return HlocFeatureStore(features, uncertainties)


def _validate_hloc_feature_for_write(name: str, feature: _core.FeatureSet) -> None:
    if feature.image_name != name:
        raise ValueError(
            f"hloc features: mapping key {name!r} disagrees with "
            f"FeatureSet.image_name {feature.image_name!r}"
        )
    if (
        feature.image_id != 0
        or feature.camera_id != 0
        or feature.time_id is not None
        or feature.extractor_type != -1
        or feature.extractor_type_name is not None
        or feature.keypoint_colors is not None
        or feature.quality is not None
        or feature.keypoint_columns != 2
        or not feature.keypoints_present
    ):
        raise ValueError(
            f"hloc features: FeatureSet {name!r} carries fields that the "
            "documented hloc layout cannot represent"
        )
    width, height = feature.image_size
    if width <= 0 or height <= 0:
        raise ValueError(f"hloc features: FeatureSet {name!r} needs image_size")


def write_hloc_features(value: HlocFeatureStore, path: str | Path) -> None:
    """Write native per-image features in the documented hloc orientation."""

    if not isinstance(value, HlocFeatureStore):
        if not isinstance(value, Mapping):
            raise TypeError("hloc feature writer expects HlocFeatureStore or mapping")
        value = HlocFeatureStore(value)

    def emit(handle) -> None:
        _write_root_attrs(handle, {}, "hloc_features")
        for name, feature in value.items():
            _validate_hloc_feature_for_write(name, feature)
            group = handle.create_group(name, track_order=True)
            keypoints = group.create_dataset(
                "keypoints",
                data=np.asarray(feature.keypoints),
            )
            uncertainty = value.uncertainties[name]
            if uncertainty is not None:
                keypoints.attrs["uncertainty"] = uncertainty
            if feature.descriptors is not None:
                group.create_dataset(
                    "descriptors",
                    data=np.ascontiguousarray(np.asarray(feature.descriptors).T),
                )
            if feature.scores is not None:
                group.create_dataset("scores", data=np.asarray(feature.scores))
            group.create_dataset(
                "image_size",
                data=np.asarray(feature.image_size, dtype=np.int64),
            )

    _atomic_hdf5_write(path, emit, libver="latest")


def inspect_hloc_features(path: str | Path) -> Inspection:
    """Inspect hloc feature groups without decoding their datasets."""

    h5py = _require_h5py()
    arrays: list[ArrayInspection] = []
    total_keypoints = 0
    descriptor_groups = 0
    with h5py.File(path, "r", libver="latest") as handle:
        _validate_hloc_root(handle, "hloc_features")
        groups = _feature_groups(handle)
        for name, group in groups:
            total_keypoints += _validate_feature_group_metadata(name, group)
            for dataset_name in sorted(_SUPPORTED_FEATURE_DATASETS & set(group)):
                dataset = group[dataset_name]
                arrays.append(
                    ArrayInspection(
                        f"{name}/{dataset_name}",
                        tuple(int(v) for v in dataset.shape),
                        dataset.dtype.name,
                    )
                )
            descriptor_groups += int("descriptors" in group)
    return Inspection(
        format="hloc_features",
        datatype="feature_set",
        byte_size=Path(path).stat().st_size,
        count=total_keypoints,
        arrays=tuple(arrays),
        metadata={
            "image_count": len(groups),
            "descriptor_image_count": descriptor_groups,
        },
    )


def _match_groups(handle) -> tuple[tuple[str, Any], ...]:
    h5py = _require_h5py()
    groups: dict[str, Any] = {}
    for _, dataset in _dataset_items(handle):
        group = dataset.parent
        groups[group.name.strip("/")] = group
    if not groups:
        raise ValueError("hloc matches: no pair groups found")
    result = []
    for name in sorted(groups):
        group = groups[name]
        datasets = {
            key for key, value in group.items() if isinstance(value, h5py.Dataset)
        }
        if "matches0" not in datasets:
            raise ValueError(
                f"hloc matches: group {name!r} has no matches0 dataset"
            )
        unknown = datasets - _SUPPORTED_MATCH_DATASETS
        if unknown:
            raise ValueError(
                f"hloc matches: group {name!r} has unsupported datasets "
                + ", ".join(sorted(unknown))
            )
        result.append((name, group))
    pair_indices = [
        int(group.attrs["sceneio_pair_index"])
        for _, group in result
        if "sceneio_pair_index" in group.attrs
    ]
    if pair_indices:
        if (
            len(pair_indices) != len(result)
            or sorted(pair_indices) != list(range(len(result)))
        ):
            raise ValueError(
                "hloc matches: sceneio_pair_index attributes must form 0..P-1"
            )
        result.sort(key=lambda item: int(item[1].attrs["sceneio_pair_index"]))
    return tuple(result)


def _pair_names(storage_name: str, group) -> tuple[str, str]:
    attrs = set(group.attrs)
    if attrs:
        if attrs not in (
            {"name0", "name1"},
            {"name0", "name1", "sceneio_pair_index"},
        ):
            raise ValueError(
                f"hloc matches: group {storage_name!r} has unsupported attributes"
            )
        return (
            _validate_hloc_image_name(
                _text_attr(group.attrs["name0"], "hloc match name0")
            ),
            _validate_hloc_image_name(
                _text_attr(group.attrs["name1"], "hloc match name1")
            ),
        )
    parts = storage_name.split("/")
    if len(parts) != 2:
        raise ValueError(
            f"hloc matches: pair group {storage_name!r} does not expose "
            "two endpoint names; add name0/name1 attrs or use the current "
            "two-level hloc layout"
        )
    return (_validate_hloc_image_name(parts[0]), _validate_hloc_image_name(parts[1]))


def _validate_match_group_metadata(
    storage_name: str,
    group,
) -> tuple[str, str]:
    pair = _pair_names(storage_name, group)
    matches = group["matches0"]
    if matches.ndim != 1 or matches.dtype.name not in {
        "int16",
        "int32",
        "int64",
    }:
        raise ValueError(
            f"hloc matches: {storage_name!r}/matches0 must be "
            "signed integer (N,)"
        )
    _validate_dataset_attrs(
        matches,
        context=f"hloc matches: {storage_name!r}/matches0",
    )
    if "matching_scores0" in group:
        scores = group["matching_scores0"]
        if (
            scores.shape != matches.shape
            or scores.dtype.name not in {"float16", "float32"}
        ):
            raise ValueError(
                f"hloc matches: {storage_name!r}/matching_scores0 must be "
                "float16/float32 with shape (N,)"
            )
        _validate_dataset_attrs(
            scores,
            context=f"hloc matches: {storage_name!r}/matching_scores0",
        )
    return pair


def read_hloc_matches(path: str | Path) -> HlocMatchStore:
    """Read current hloc ``matches0`` groups into one native ``MatchGraph``."""

    h5py = _require_h5py()
    records: list[
        tuple[
            tuple[str, str],
            np.ndarray,
            np.ndarray | None,
            str,
            str | None,
        ]
    ] = []
    with h5py.File(path, "r", libver="latest") as handle:
        _validate_hloc_root(handle, "hloc_matches")
        for storage_name, group in _match_groups(handle):
            pair = _validate_match_group_metadata(storage_name, group)
            dense = np.asarray(group["matches0"][...])
            score_values: np.ndarray | None = None
            score_dtype: str | None = None
            if "matching_scores0" in group:
                source_scores = np.asarray(group["matching_scores0"][...])
                score_values = source_scores
                score_dtype = source_scores.dtype.name
            records.append((pair, dense, score_values, dense.dtype.name, score_dtype))

    all_names = sorted({name for pair, *_ in records for name in pair})
    ids = {name: index + 1 for index, name in enumerate(all_names)}
    image_pairs: list[tuple[int, int]] = []
    pair_names: list[tuple[str, str]] = []
    source_counts: list[int] = []
    match_dtypes: list[str] = []
    score_dtypes: list[str | None] = []
    dense_matches: list[np.ndarray] = []
    score_rows: list[np.ndarray | None] = []
    reverse_flags: list[int] = []
    seen: set[frozenset[str]] = set()
    for pair, dense, pair_scores, match_dtype, score_dtype in records:
        unordered = frozenset(pair)
        if unordered in seen:
            raise ValueError(f"hloc matches: duplicate unordered pair {pair!r}")
        seen.add(unordered)
        name0, name1 = pair
        id0, id1 = ids[name0], ids[name1]
        image_pairs.append((min(id0, id1), max(id0, id1)))
        pair_names.append(pair)
        source_counts.append(len(dense))
        match_dtypes.append(match_dtype)
        score_dtypes.append(score_dtype)
        dense_matches.append(dense)
        score_rows.append(pair_scores)
        reverse_flags.append(int(id0 > id1))

    pair_count = len(records)
    graph = _core.hloc_match_graph(
        np.asarray(image_pairs, dtype=np.uint32).reshape(pair_count, 2),
        dense_matches,
        score_rows,
        np.asarray(reverse_flags, dtype=np.uint8),
    )
    return HlocMatchStore(
        tuple(all_names),
        tuple(pair_names),
        tuple(source_counts),
        tuple(match_dtypes),
        tuple(score_dtypes),
        graph,
    )


def _validate_hloc_match_graph(value: HlocMatchStore) -> None:
    graph = value.graph
    if (
        int(graph.num_verified_matches) != 0
        or np.any(np.asarray(graph.geometry_present))
        or np.any(np.asarray(graph.F_present))
        or np.any(np.asarray(graph.E_present))
        or np.any(np.asarray(graph.H_present))
        or np.any(np.asarray(graph.pose_present))
        or np.any(np.asarray(graph.camera1_present))
        or np.any(np.asarray(graph.camera2_present))
        or np.any(np.asarray(graph.provenance_present))
        or not np.all(np.asarray(graph.match_present) == 1)
    ):
        raise ValueError(
            "hloc matches: MatchGraph carries fields that the documented "
            "matches0 layout cannot represent"
        )


def _hloc_pair_storage_name(name0: str, name1: str) -> str:
    return f"{name0.replace('/', '-')}/{name1.replace('/', '-')}"


def write_hloc_matches(value: HlocMatchStore, path: str | Path) -> None:
    """Write a native match graph in current hloc dense ``matches0`` form."""

    if not isinstance(value, HlocMatchStore):
        raise TypeError("hloc match writer expects HlocMatchStore")
    _validate_hloc_match_graph(value)
    ids = {name: index + 1 for index, name in enumerate(value.image_names)}
    graph_matches = np.asarray(value.graph.matches)
    graph_scores = np.asarray(value.graph.scores)
    offsets = np.asarray(value.graph.match_offsets)
    score_presence = np.asarray(value.graph.match_score_present)
    storage_names = [
        _hloc_pair_storage_name(name0, name1)
        for name0, name1 in value.pair_names
    ]
    if len(storage_names) != len(set(storage_names)):
        raise ValueError("hloc matches: mangled pair names collide")

    def emit(handle) -> None:
        _write_root_attrs(handle, {}, "hloc_matches")
        for index, pair in enumerate(value.pair_names):
            name0, name1 = pair
            begin, end = int(offsets[index]), int(offsets[index + 1])
            matches = np.asarray(graph_matches[begin:end])
            source_column = 0 if ids[name0] < ids[name1] else 1
            target_column = 1 - source_column
            source_count = value.source_keypoint_counts[index]
            dtype = np.dtype(value.match_dtypes[index])
            info = np.iinfo(dtype)
            dense = np.full(source_count, -1, dtype=dtype)
            if len(matches):
                source_indices = matches[:, source_column]
                target_indices = matches[:, target_column]
                if int(target_indices.max()) > info.max:
                    raise ValueError(
                        f"hloc matches: target index exceeds {dtype.name} "
                        f"for pair {pair!r}"
                    )
                if _has_duplicate_indices(source_indices):
                    raise ValueError(
                        f"hloc matches: pair {pair!r} has multiple matches "
                        "for one source keypoint"
                    )
                dense[source_indices] = target_indices.astype(dtype)
            group = handle.create_group(storage_names[index], track_order=True)
            group.attrs["name0"] = name0
            group.attrs["name1"] = name1
            group.attrs["sceneio_pair_index"] = np.uint64(index)
            group.create_dataset("matches0", data=dense)
            if score_presence[index]:
                score_dtype = np.dtype(value.score_dtypes[index])
                dense_scores = np.zeros(source_count, dtype=score_dtype)
                selected_scores = graph_scores[begin:end]
                converted = selected_scores.astype(score_dtype)
                if not np.array_equal(
                    converted.astype(np.float32),
                    selected_scores,
                ):
                    raise ValueError(
                        f"hloc matches: scores for pair {pair!r} are not "
                        f"exactly representable as {score_dtype.name}"
                    )
                dense_scores[matches[:, source_column]] = converted
                group.create_dataset("matching_scores0", data=dense_scores)

    _atomic_hdf5_write(path, emit, libver="latest")


def inspect_hloc_matches(path: str | Path) -> Inspection:
    """Inspect hloc match groups without decoding match arrays."""

    h5py = _require_h5py()
    arrays: list[ArrayInspection] = []
    total_source_keypoints = 0
    pair_count = 0
    scored_pairs = 0
    with h5py.File(path, "r", libver="latest") as handle:
        _validate_hloc_root(handle, "hloc_matches")
        for storage_name, group in _match_groups(handle):
            _validate_match_group_metadata(storage_name, group)
            matches = group["matches0"]
            pair_count += 1
            total_source_keypoints += int(matches.shape[0])
            for dataset_name in sorted(_SUPPORTED_MATCH_DATASETS & set(group)):
                dataset = group[dataset_name]
                arrays.append(
                    ArrayInspection(
                        f"{storage_name}/{dataset_name}",
                        tuple(int(v) for v in dataset.shape),
                        dataset.dtype.name,
                    )
                )
            scored_pairs += int("matching_scores0" in group)
    return Inspection(
        format="hloc_matches",
        datatype="match_graph",
        byte_size=Path(path).stat().st_size,
        count=pair_count,
        arrays=tuple(arrays),
        metadata={
            "pair_count": pair_count,
            "dense_source_keypoint_count": total_source_keypoints,
            "scored_pair_count": scored_pairs,
        },
    )


def classify_hdf5(path: str | Path) -> str:
    """Classify generic HDF5 versus the two documented hloc layouts."""

    if importlib.util.find_spec("h5py") is None:
        return "hdf5"
    h5py = _require_h5py()
    try:
        with h5py.File(path, "r") as handle:
            if _SCENEIO_FORMAT_ATTR in handle.attrs:
                declared = _text_attr(
                    handle.attrs[_SCENEIO_FORMAT_ATTR],
                    "HDF5 sceneio_format",
                )
                if declared in {"hdf5", "hloc_features", "hloc_matches"}:
                    return declared
            has_features = False
            has_matches = False

            def visit(_name: str, value: object) -> None:
                nonlocal has_features, has_matches
                if isinstance(value, h5py.Group):
                    has_features = has_features or (
                        "keypoints" in value and "image_size" in value
                    )
                    has_matches = has_matches or "matches0" in value

            handle.visititems(visit)
            if has_features and not has_matches:
                return "hloc_features"
            if has_matches and not has_features:
                return "hloc_matches"
    except (OSError, ValueError):
        return "hdf5"
    return "hdf5"


__all__ = [
    "HDF5_AVAILABLE",
    "HDF5_MAGIC",
    "HlocFeatureStore",
    "HlocMatchStore",
    "classify_hdf5",
    "inspect_hdf5",
    "inspect_hloc_features",
    "inspect_hloc_matches",
    "read_hdf5",
    "read_hdf5_slices",
    "read_hdf5_tensors",
    "read_hloc_features",
    "read_hloc_matches",
    "write_hdf5",
    "write_hloc_features",
    "write_hloc_matches",
]
