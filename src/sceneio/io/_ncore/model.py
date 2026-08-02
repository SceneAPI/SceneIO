"""Immutable public metadata records for NCore V4 datasets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import numpy as np

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


def _freeze_json(value: object, context: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{context}: JSON numbers must be finite")
        return value
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{context}[{index}]")
            for index, item in enumerate(value)
        )
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for raw_name, item in value.items():
            if not isinstance(raw_name, str):
                raise ValueError(f"{context}: JSON object keys must be strings")
            if raw_name in frozen:
                raise ValueError(f"{context}: duplicate key {raw_name!r}")
            frozen[raw_name] = _freeze_json(item, f"{context}.{raw_name}")
        return MappingProxyType(frozen)
    raise ValueError(
        f"{context}: expected JSON-compatible data, got {type(value).__name__}"
    )


def _non_empty(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _half_open(value: object, context: str) -> tuple[int, int]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError(f"{context} must be a two-integer half-open interval")
    start, stop = value
    if (
        isinstance(start, bool)
        or isinstance(stop, bool)
        or not isinstance(start, int)
        or not isinstance(stop, int)
    ):
        raise ValueError(f"{context} must contain integers")
    if start < 0 or stop <= start:
        raise ValueError(f"{context} must satisfy 0 <= start < stop")
    return start, stop


def _normalize_arrays(
    arrays: Mapping[str, np.ndarray], context: str
) -> Mapping[str, np.ndarray]:
    normalized: dict[str, np.ndarray] = {}
    for name, raw_value in arrays.items():
        _non_empty(name, f"{context} array name")
        if name.startswith("/") or any(
            part in {"", ".", ".."} for part in name.split("/")
        ):
            raise ValueError(f"{context} array names must be relative paths")
        value = np.asarray(raw_value)
        if value.dtype.hasobject:
            raise ValueError(f"{context} arrays cannot use object dtype")
        if not value.flags.owndata or not value.flags.c_contiguous:
            value = np.array(value, copy=True, order="C")
        value.setflags(write=False)
        normalized[name] = value
    if len(normalized) != len(arrays):
        raise ValueError(f"{context} array names must be unique")
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class NCoreArray:
    """Metadata for one array inside an NCore component instance."""

    name: str
    shape: tuple[int, ...]
    dtype: str
    chunks: tuple[int, ...]
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _non_empty(self.name, "NCoreArray.name")
        if self.name.startswith("/") or any(
            part in {"", ".", ".."} for part in self.name.split("/")
        ):
            raise ValueError("NCoreArray.name must be a relative '/'-separated path")
        shape = tuple(self.shape)
        chunks = tuple(self.chunks)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in shape):
            raise ValueError("NCoreArray.shape must contain non-negative integers")
        if len(chunks) != len(shape) or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in chunks
        ):
            raise ValueError(
                "NCoreArray.chunks must contain one positive integer per dimension"
            )
        _non_empty(self.dtype, "NCoreArray.dtype")
        object.__setattr__(self, "shape", shape)
        object.__setattr__(self, "chunks", chunks)
        frozen = _freeze_json(dict(self.attributes), "NCoreArray.attributes")
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "attributes", frozen)


@dataclass(frozen=True, slots=True)
class NCoreComponent:
    """One typed component instance catalogued from a component store."""

    name: str
    instance: str
    version: str
    group: str
    store_index: int
    generic_metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    arrays: tuple[NCoreArray, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.name, "NCoreComponent.name")
        _non_empty(self.instance, "NCoreComponent.instance")
        _non_empty(self.version, "NCoreComponent.version")
        if not isinstance(self.group, str):
            raise ValueError("NCoreComponent.group must be a string")
        if (
            isinstance(self.store_index, bool)
            or not isinstance(self.store_index, int)
            or self.store_index < 0
        ):
            raise ValueError("NCoreComponent.store_index must be non-negative")
        arrays = tuple(self.arrays)
        names = tuple(array.name for array in arrays)
        if len(names) != len(set(names)):
            raise ValueError("NCoreComponent array names must be unique")
        frozen = _freeze_json(
            dict(self.generic_metadata), "NCoreComponent.generic_metadata"
        )
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "generic_metadata", frozen)
        object.__setattr__(self, "arrays", arrays)

    @property
    def id(self) -> str:
        """Canonical ``component:instance`` identifier."""

        return f"{self.name}:{self.instance}"


@dataclass(frozen=True, slots=True)
class NCoreStore:
    """One local NCore V4 component store."""

    path: str
    group: str
    storage: str
    byte_size: int
    components: tuple[NCoreComponent, ...]

    def __post_init__(self) -> None:
        _non_empty(self.path, "NCoreStore.path")
        if not Path(self.path).is_absolute():
            raise ValueError("NCoreStore.path must be absolute")
        if not isinstance(self.group, str):
            raise ValueError("NCoreStore.group must be a string")
        if self.storage not in {"directory", "itar"}:
            raise ValueError("NCoreStore.storage must be 'directory' or 'itar'")
        if isinstance(self.byte_size, bool) or self.byte_size < 0:
            raise ValueError("NCoreStore.byte_size must be non-negative")
        components = tuple(self.components)
        ids = tuple(component.id for component in components)
        if len(ids) != len(set(ids)):
            raise ValueError("NCoreStore component ids must be unique")
        object.__setattr__(self, "components", components)


@dataclass(frozen=True, slots=True)
class NCoreDataset:
    """Lazy, path-backed catalog for one NCore V4 sequence."""

    source: str
    sequence_id: str
    timestamp_interval_us: tuple[int, int]
    generic_metadata: Mapping[str, JsonValue]
    stores: tuple[NCoreStore, ...]
    version: str = "v4"

    def __post_init__(self) -> None:
        _non_empty(self.source, "NCoreDataset.source")
        _non_empty(self.sequence_id, "NCoreDataset.sequence_id")
        if self.version != "v4":
            raise ValueError("NCoreDataset supports exactly version 'v4'")
        interval = _half_open(
            self.timestamp_interval_us,
            "NCoreDataset.timestamp_interval_us",
        )
        stores = tuple(self.stores)
        if not stores:
            raise ValueError("NCoreDataset requires at least one component store")
        groups = tuple(store.group for store in stores)
        if len(groups) != len(set(groups)):
            raise ValueError("NCoreDataset component-store groups must be unique")
        components = tuple(
            component for store in stores for component in store.components
        )
        for store_index, store in enumerate(stores):
            for component in store.components:
                if component.store_index != store_index:
                    raise ValueError(
                        "NCoreDataset component store_index disagrees with its store"
                    )
                if component.group != store.group:
                    raise ValueError(
                        "NCoreDataset component group disagrees with its store"
                    )
        ids = tuple(component.id for component in components)
        if len(ids) != len(set(ids)):
            raise ValueError("NCoreDataset component ids must be unique across stores")
        frozen = _freeze_json(
            dict(self.generic_metadata), "NCoreDataset.generic_metadata"
        )
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "timestamp_interval_us", interval)
        object.__setattr__(self, "generic_metadata", frozen)
        object.__setattr__(self, "stores", stores)

    @property
    def components(self) -> tuple[NCoreComponent, ...]:
        """All component instances in stable store/path order."""

        return tuple(component for store in self.stores for component in store.components)

    @property
    def byte_size(self) -> int:
        """Total physical size of the referenced local stores."""

        return sum(store.byte_size for store in self.stores)

    def find_component(self, name: str, instance: str) -> NCoreComponent:
        """Find one exact component instance or raise ``KeyError``."""

        matches = tuple(
            component
            for component in self.components
            if component.name == name and component.instance == instance
        )
        if not matches:
            raise KeyError(f"NCore component {name}:{instance} does not exist")
        return matches[0]


@dataclass(frozen=True, slots=True)
class NCoreSelection:
    """One typed NCore component request for ``read_partial``."""

    component: str
    instance: str
    group: str | None = None
    frames: tuple[int, int] | None = None
    timestamps_us: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        _non_empty(self.component, "NCoreSelection.component")
        _non_empty(self.instance, "NCoreSelection.instance")
        if self.group is not None and not isinstance(self.group, str):
            raise ValueError("NCoreSelection.group must be a string or None")
        if self.frames is not None and self.timestamps_us is not None:
            raise ValueError(
                "NCoreSelection accepts a frame interval or timestamp interval, not both"
            )
        if self.frames is not None:
            object.__setattr__(
                self, "frames", _half_open(self.frames, "NCoreSelection.frames")
            )
        if self.timestamps_us is not None:
            object.__setattr__(
                self,
                "timestamps_us",
                _half_open(
                    self.timestamps_us,
                    "NCoreSelection.timestamps_us",
                ),
            )


@dataclass(frozen=True, slots=True)
class NCoreGroup:
    """Metadata for one group relative to a loaded component root."""

    name: str
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise ValueError("NCoreGroup.name must be a string")
        if self.name and (
            self.name.startswith("/")
            or any(part in {"", ".", ".."} for part in self.name.split("/"))
        ):
            raise ValueError(
                "NCoreGroup.name must be empty or a relative '/'-separated path"
            )
        frozen = _freeze_json(dict(self.attributes), "NCoreGroup.attributes")
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "attributes", frozen)


@dataclass(frozen=True, slots=True, eq=False)
class NCoreItem:
    """One validated semantic item inside a standard NCore component."""

    kind: str
    id: str
    arrays: Mapping[str, np.ndarray] = field(default_factory=dict)
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)
    timestamp_interval_us: tuple[int, int] | None = None
    timestamp_us: int | None = None
    reference_frame_id: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.kind, "NCoreItem.kind")
        _non_empty(self.id, "NCoreItem.id")
        if self.timestamp_interval_us is not None:
            value = self.timestamp_interval_us
            if not isinstance(value, (tuple, list)) or len(value) != 2:
                raise ValueError(
                    "NCoreItem.timestamp_interval_us must contain start/stop"
                )
            start, stop = value
            if (
                isinstance(start, bool)
                or isinstance(stop, bool)
                or not isinstance(start, int)
                or not isinstance(stop, int)
                or start < 0
                or stop < start
                or stop > np.iinfo(np.uint64).max
            ):
                raise ValueError(
                    "NCoreItem.timestamp_interval_us must satisfy uint64 "
                    "0 <= start <= stop"
                )
            object.__setattr__(self, "timestamp_interval_us", (start, stop))
        if self.timestamp_us is not None and (
            isinstance(self.timestamp_us, bool)
            or not isinstance(self.timestamp_us, int)
            or not 0 <= self.timestamp_us <= np.iinfo(np.uint64).max
        ):
            raise ValueError("NCoreItem.timestamp_us must be a uint64 integer")
        if self.reference_frame_id is not None:
            _non_empty(self.reference_frame_id, "NCoreItem.reference_frame_id")
        frozen = _freeze_json(dict(self.attributes), "NCoreItem.attributes")
        assert isinstance(frozen, Mapping)
        object.__setattr__(
            self,
            "arrays",
            _normalize_arrays(self.arrays, "NCoreItem"),
        )
        object.__setattr__(self, "attributes", frozen)

    def array(self, name: str) -> np.ndarray:
        """Return one item-local array by name."""

        try:
            return self.arrays[name]
        except KeyError:
            raise KeyError(f"NCore item array {name!r} does not exist") from None

    def to_sceneio(self):
        """Project the exact payload; NCore metadata remains on this item."""

        from sceneio.io._ncore.projection import project_ncore_item

        return project_ncore_item(self)


@dataclass(frozen=True, slots=True, eq=False)
class NCoreComponentData:
    """Owned arrays and exact group metadata for one NCore component instance."""

    component: NCoreComponent
    selection: NCoreSelection
    arrays: Mapping[str, np.ndarray]
    groups: tuple[NCoreGroup, ...]
    selected_items: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.component.name != self.selection.component
            or self.component.instance != self.selection.instance
        ):
            raise ValueError(
                "NCoreComponentData selection disagrees with its component"
            )
        if (
            self.selection.group is not None
            and self.selection.group != self.component.group
        ):
            raise ValueError(
                "NCoreComponentData selection group disagrees with its component"
            )
        groups = tuple(self.groups)
        group_names = tuple(group.name for group in groups)
        if len(group_names) != len(set(group_names)):
            raise ValueError("NCoreComponentData group names must be unique")
        selected_items = tuple(self.selected_items)
        if any(not isinstance(item, str) or not item for item in selected_items):
            raise ValueError(
                "NCoreComponentData.selected_items must contain non-empty strings"
            )
        object.__setattr__(
            self,
            "arrays",
            _normalize_arrays(self.arrays, "NCoreComponentData"),
        )
        object.__setattr__(self, "groups", groups)
        object.__setattr__(self, "selected_items", selected_items)

    def array(self, name: str) -> np.ndarray:
        """Return one loaded array by its component-relative path."""

        try:
            return self.arrays[name]
        except KeyError:
            raise KeyError(f"NCore component array {name!r} does not exist") from None

    def group(self, name: str = "") -> NCoreGroup:
        """Return one loaded group-metadata record by relative path."""

        for group in self.groups:
            if group.name == name:
                return group
        raise KeyError(f"NCore component group {name!r} does not exist")


@dataclass(frozen=True, slots=True, eq=False)
class NCoreSemanticComponent:
    """Validated standard-component profile layered over exact raw NCore data."""

    raw: NCoreComponentData
    profile: str
    items: tuple[NCoreItem, ...]
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.raw, NCoreComponentData):
            raise ValueError("NCoreSemanticComponent.raw must be component data")
        _non_empty(self.profile, "NCoreSemanticComponent.profile")
        items = tuple(self.items)
        if any(not isinstance(item, NCoreItem) for item in items):
            raise ValueError(
                "NCoreSemanticComponent.items must contain NCoreItem records"
            )
        keys = tuple((item.kind, item.id) for item in items)
        if len(keys) != len(set(keys)):
            raise ValueError(
                "NCoreSemanticComponent item kind/id pairs must be unique"
            )
        frozen = _freeze_json(
            dict(self.attributes), "NCoreSemanticComponent.attributes"
        )
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "attributes", frozen)

    def items_of_kind(self, kind: str) -> tuple[NCoreItem, ...]:
        """Return all items with one exact semantic kind."""

        return tuple(item for item in self.items if item.kind == kind)

    def item(self, kind: str, id: str) -> NCoreItem:
        """Return one semantic item by kind and id."""

        for item in self.items:
            if item.kind == kind and item.id == id:
                return item
        raise KeyError(f"NCore semantic item {kind}:{id} does not exist")


for _record in (
    NCoreArray,
    NCoreComponent,
    NCoreComponentData,
    NCoreDataset,
    NCoreGroup,
    NCoreItem,
    NCoreSelection,
    NCoreSemanticComponent,
    NCoreStore,
):
    _record.__module__ = "sceneio.io"


__all__ = [
    "JsonScalar",
    "JsonValue",
    "NCoreArray",
    "NCoreComponent",
    "NCoreComponentData",
    "NCoreDataset",
    "NCoreGroup",
    "NCoreItem",
    "NCoreSelection",
    "NCoreSemanticComponent",
    "NCoreStore",
]
