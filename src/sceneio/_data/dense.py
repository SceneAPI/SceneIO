"""Dense per-pixel data contracts: geometry, confidence, masks, and labels.

These are the image-aligned array types: strict dtype (no silent
conversion of large buffers) and strict shape, validated on
construction with :class:`~sceneio.errors.ContractViolation`.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Literal

import numpy as np

from sceneio._data._validation import ensure_array, ensure_choice
from sceneio.errors import ContractViolation

POINTMAP_FRAMES: frozenset[str] = frozenset({"world", "camera"})
_VALIDATION_CHUNK = 1 << 20
_MAX_MEMBERSHIP_TABLE = 1 << 20


def _c_array(
    name: str,
    value: object,
    *,
    dtypes: tuple[object, ...],
    shape: tuple[int | None, ...],
) -> np.ndarray:
    array = ensure_array(name, value, dtypes=dtypes, shape=shape)
    if not array.flags.c_contiguous:
        raise ContractViolation(f"{name}: expected a C-contiguous array")
    return array


def _integer(name: str, value: object, dtype: object) -> int:
    if isinstance(value, bool):
        raise ContractViolation(f"{name}: expected an integer, got bool")
    try:
        result = operator.index(value)
    except TypeError:
        raise ContractViolation(
            f"{name}: expected an integer, got {type(value).__name__}"
        ) from None
    bounds = np.iinfo(dtype)
    if result < bounds.min or result > bounds.max:
        raise ContractViolation(
            f"{name}: value {result} is outside {np.dtype(dtype).name}"
        )
    return int(result)


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ContractViolation(f"{name}: expected a non-empty string without NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ContractViolation(f"{name}: expected valid UTF-8 text") from None
    return value


def _validity(
    name: str,
    value: object | None,
    shape: tuple[int, int],
) -> np.ndarray | None:
    if value is None:
        return None
    return _c_array(name, value, dtypes=(np.bool_,), shape=shape)


def _require_membership(
    name: str,
    values: np.ndarray,
    allowed: np.ndarray,
    *,
    valid: np.ndarray | None = None,
    excluded: int | None = None,
) -> None:
    """Check large rasters against a small id table with bounded scratch space."""

    ordered = np.sort(allowed)
    lower = int(ordered[0]) if ordered.size else 0
    upper = int(ordered[-1]) if ordered.size else -1
    span = upper - lower + 1
    contiguous = ordered.size > 0 and span == ordered.size
    lookup = None
    if ordered.size and not contiguous and span <= _MAX_MEMBERSHIP_TABLE:
        lookup = np.zeros(span, dtype=np.bool_)
        lookup[(ordered - lower).astype(np.intp, copy=False)] = True
    flat_values = values.reshape(-1)
    flat_valid = None if valid is None else valid.reshape(-1)
    for start in range(0, flat_values.size, _VALIDATION_CHUNK):
        stop = min(start + _VALIDATION_CHUNK, flat_values.size)
        observed = flat_values[start:stop]
        if flat_valid is not None:
            observed = observed[flat_valid[start:stop]]
        if excluded is not None:
            observed = observed[observed != excluded]
        if not observed.size:
            continue
        if not ordered.size:
            preview = ", ".join(
                str(int(value)) for value in np.unique(observed)[:4]
            )
            raise ContractViolation(
                f"{name}: values are absent from the table: {preview}"
            )
        in_range = (observed >= lower) & (observed <= upper)
        if contiguous:
            member = in_range
        elif lookup is not None:
            member = np.zeros(observed.shape, dtype=np.bool_)
            member[in_range] = lookup[
                (observed[in_range] - lower).astype(np.intp, copy=False)
            ]
        else:
            positions = np.searchsorted(ordered, observed)
            member = positions < ordered.size
            member[member] &= np.equal(ordered[positions[member]], observed[member])
        if not member.all():
            unknown = np.unique(observed[~member])
            preview = ", ".join(str(int(value)) for value in unknown[:4])
            raise ContractViolation(f"{name}: values are absent from the table: {preview}")


@dataclass(frozen=True)
class LabelTaxonomy:
    """Ordered semantic-label vocabulary with explicit identity and version.

    ``semantic_ids`` and the rows of ``names``/``display_colors``/
    ``is_thing`` have the same order.  Names are descriptive metadata, never
    identifiers: callers must use the unique ``int32`` semantic ids.
    """

    semantic_ids: np.ndarray  # (K,) int32, unique
    names: tuple[str, ...]
    identity: str
    version: str
    display_colors: np.ndarray | None = None  # (K, 3) uint8 RGB
    is_thing: np.ndarray | None = None  # (K,) bool

    def __post_init__(self) -> None:
        semantic_ids = _c_array(
            "LabelTaxonomy.semantic_ids",
            self.semantic_ids,
            dtypes=(np.int32,),
            shape=(None,),
        )
        if not isinstance(self.names, (tuple, list)):
            raise ContractViolation(
                "LabelTaxonomy.names: expected a tuple or list of strings"
            )
        names = tuple(self.names)
        if len(names) != len(semantic_ids):
            raise ContractViolation(
                "LabelTaxonomy.names: expected one name per semantic id"
            )
        for index, name in enumerate(names):
            _text(f"LabelTaxonomy.names[{index}]", name)
        if len(np.unique(semantic_ids)) != len(semantic_ids):
            raise ContractViolation("LabelTaxonomy.semantic_ids: ids must be unique")
        identity = _text("LabelTaxonomy.identity", self.identity)
        version = _text("LabelTaxonomy.version", self.version)
        if self.display_colors is not None:
            _c_array(
                "LabelTaxonomy.display_colors",
                self.display_colors,
                dtypes=(np.uint8,),
                shape=(len(semantic_ids), 3),
            )
        if self.is_thing is not None:
            _c_array(
                "LabelTaxonomy.is_thing",
                self.is_thing,
                dtypes=(np.bool_,),
                shape=(len(semantic_ids),),
            )
        object.__setattr__(self, "names", names)
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "version", version)

    def index(self, semantic_id: int) -> int:
        """Return the ordered row for one semantic id or raise ``KeyError``."""

        selected = _integer("semantic_id", semantic_id, np.int32)
        rows = np.flatnonzero(self.semantic_ids == selected)
        if not rows.size:
            raise KeyError(f"semantic id {selected} is not in taxonomy {self.identity!r}")
        return int(rows[0])


@dataclass(frozen=True)
class SemanticMap:
    """Canonical ``int32 (H, W)`` semantic ids.

    ``valid`` is independent observation validity.  ``void_id`` is the
    represented no-class value and may occur at otherwise valid pixels.  When
    a taxonomy is present, every valid non-void id must be declared by it.
    """

    class_ids: np.ndarray
    void_id: int
    valid: np.ndarray | None = None
    taxonomy: LabelTaxonomy | None = None

    def __post_init__(self) -> None:
        class_ids = _c_array(
            "SemanticMap.class_ids",
            self.class_ids,
            dtypes=(np.int32,),
            shape=(None, None),
        )
        void_id = _integer("SemanticMap.void_id", self.void_id, np.int32)
        valid = _validity("SemanticMap.valid", self.valid, self.shape)
        if self.taxonomy is not None:
            if not isinstance(self.taxonomy, LabelTaxonomy):
                raise ContractViolation(
                    "SemanticMap.taxonomy: expected LabelTaxonomy or None"
                )
            if np.any(self.taxonomy.semantic_ids == void_id):
                raise ContractViolation(
                    "SemanticMap.void_id: void must not also be a taxonomy class"
                )
            _require_membership(
                "SemanticMap.class_ids",
                class_ids,
                self.taxonomy.semantic_ids,
                valid=valid,
                excluded=void_id,
            )
        object.__setattr__(self, "void_id", void_id)

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.class_ids.shape[0]), int(self.class_ids.shape[1]))


@dataclass(frozen=True)
class InstanceMap:
    """Canonical ``int64 (H, W)`` instance ids and optional class table."""

    instance_ids: np.ndarray
    background_id: int
    valid: np.ndarray | None = None
    table_instance_ids: np.ndarray | None = None  # (N,) int64, unique
    table_semantic_ids: np.ndarray | None = None  # (N,) int32

    def __post_init__(self) -> None:
        instance_ids = _c_array(
            "InstanceMap.instance_ids",
            self.instance_ids,
            dtypes=(np.int64,),
            shape=(None, None),
        )
        background_id = _integer(
            "InstanceMap.background_id", self.background_id, np.int64
        )
        valid = _validity("InstanceMap.valid", self.valid, self.shape)
        if (self.table_instance_ids is None) != (self.table_semantic_ids is None):
            raise ContractViolation(
                "InstanceMap table: instance and semantic arrays must be present together"
            )
        if self.table_instance_ids is not None:
            table_instance_ids = _c_array(
                "InstanceMap.table_instance_ids",
                self.table_instance_ids,
                dtypes=(np.int64,),
                shape=(None,),
            )
            _c_array(
                "InstanceMap.table_semantic_ids",
                self.table_semantic_ids,
                dtypes=(np.int32,),
                shape=(len(table_instance_ids),),
            )
            if len(np.unique(table_instance_ids)) != len(table_instance_ids):
                raise ContractViolation(
                    "InstanceMap.table_instance_ids: ids must be unique"
                )
            if np.any(table_instance_ids == background_id):
                raise ContractViolation(
                    "InstanceMap table: background_id must not name an instance row"
                )
            _require_membership(
                "InstanceMap.instance_ids",
                instance_ids,
                table_instance_ids,
                valid=valid,
                excluded=background_id,
            )
        object.__setattr__(self, "background_id", background_id)

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.instance_ids.shape[0]), int(self.instance_ids.shape[1]))


@dataclass(frozen=True)
class PanopticMap:
    """Unpacked panoptic labels composed from semantic and instance maps.

    No divisor is implicit.  :meth:`from_packed` and :meth:`to_packed` are the
    only packed conversion surfaces and require the divisor and output dtype.
    """

    semantic: SemanticMap
    instance: InstanceMap

    def __post_init__(self) -> None:
        if not isinstance(self.semantic, SemanticMap):
            raise ContractViolation("PanopticMap.semantic: expected SemanticMap")
        if not isinstance(self.instance, InstanceMap):
            raise ContractViolation("PanopticMap.instance: expected InstanceMap")
        if self.semantic.shape != self.instance.shape:
            raise ContractViolation(
                "PanopticMap: semantic and instance shapes must be identical"
            )
        left_valid = self.semantic.valid
        right_valid = self.instance.valid
        if (left_valid is None) != (right_valid is None) or (
            left_valid is not None and not np.array_equal(left_valid, right_valid)
        ):
            raise ContractViolation(
                "PanopticMap: semantic and instance validity must be identical"
            )

        flat_semantic = self.semantic.class_ids.reshape(-1)
        flat_instance = self.instance.instance_ids.reshape(-1)
        flat_valid = None if left_valid is None else left_valid.reshape(-1)
        table_ids = self.instance.table_instance_ids
        table_classes = self.instance.table_semantic_ids
        ordered_ids = None if table_ids is None else np.argsort(table_ids)
        for start in range(0, flat_semantic.size, _VALIDATION_CHUNK):
            stop = min(start + _VALIDATION_CHUNK, flat_semantic.size)
            semantic = flat_semantic[start:stop]
            instance = flat_instance[start:stop]
            if flat_valid is not None:
                selected = flat_valid[start:stop]
                semantic = semantic[selected]
                instance = instance[selected]
            if not semantic.size:
                continue
            void = semantic == self.semantic.void_id
            if np.any(instance[void] != self.instance.background_id):
                raise ContractViolation(
                    "PanopticMap: valid void pixels must use the instance background_id"
                )
            if ordered_ids is None:
                continue
            foreground = instance != self.instance.background_id
            ids = instance[foreground]
            classes = semantic[foreground]
            if not ids.size:
                continue
            sorted_ids = table_ids[ordered_ids]
            positions = np.searchsorted(sorted_ids, ids)
            if np.any(positions >= len(sorted_ids)) or not np.equal(
                sorted_ids[np.minimum(positions, len(sorted_ids) - 1)], ids
            ).all():
                raise ContractViolation(
                    "PanopticMap: instance ids are absent from the class table"
                )
            expected = table_classes[ordered_ids[positions]]
            if not np.array_equal(expected, classes):
                raise ContractViolation(
                    "PanopticMap: instance-to-semantic table disagrees with pixels"
                )
        if table_classes is not None and self.semantic.taxonomy is not None:
            _require_membership(
                "PanopticMap.instance.table_semantic_ids",
                table_classes,
                self.semantic.taxonomy.semantic_ids,
            )

    @property
    def shape(self) -> tuple[int, int]:
        return self.semantic.shape

    @property
    def valid(self) -> np.ndarray | None:
        return self.semantic.valid

    @classmethod
    def from_packed(
        cls,
        packed: np.ndarray,
        *,
        divisor: int,
        void_id: int,
        background_id: int,
        valid: np.ndarray | None = None,
        taxonomy: LabelTaxonomy | None = None,
    ) -> PanopticMap:
        """Decode ``semantic_id * divisor + instance_id`` with checked bounds."""

        packed_array = ensure_array("PanopticMap.packed", packed, shape=(None, None))
        if not np.issubdtype(packed_array.dtype, np.integer):
            raise ContractViolation("PanopticMap.packed: expected an integer dtype")
        if not packed_array.flags.c_contiguous:
            raise ContractViolation("PanopticMap.packed: expected a C-contiguous array")
        divisor_value = _integer("PanopticMap.divisor", divisor, np.int64)
        if divisor_value <= 0:
            raise ContractViolation("PanopticMap.divisor: expected a positive integer")
        void_value = _integer("PanopticMap.void_id", void_id, np.int32)
        background_value = _integer(
            "PanopticMap.background_id", background_id, np.int64
        )
        if not 0 <= background_value < divisor_value:
            raise ContractViolation(
                "PanopticMap packed conversion requires "
                "0 <= background_id < divisor"
            )
        if packed_array.size and int(packed_array.min()) < 0:
            raise ContractViolation("PanopticMap.packed: values must be nonnegative")
        if packed_array.dtype.kind == "u":
            arithmetic = packed_array.astype(np.uint64, copy=False)
            selected_divisor = np.uint64(divisor_value)
        else:
            arithmetic = packed_array.astype(np.int64, copy=False)
            selected_divisor = np.int64(divisor_value)
        semantic64 = np.floor_divide(arithmetic, selected_divisor)
        if semantic64.size and int(semantic64.max()) > np.iinfo(np.int32).max:
            raise ContractViolation("PanopticMap.packed: semantic id exceeds int32")
        class_ids = np.array(semantic64, dtype=np.int32, copy=True, order="C")
        instance_ids = np.array(
            np.remainder(arithmetic, selected_divisor),
            dtype=np.int64,
            copy=True,
            order="C",
        )
        selected_valid = _validity("PanopticMap.valid", valid, class_ids.shape)
        semantic_map = SemanticMap(class_ids, void_value, selected_valid, taxonomy)
        instance_map = InstanceMap(instance_ids, background_value, selected_valid)
        return cls(semantic_map, instance_map)

    def to_packed(self, *, divisor: int, dtype: object = np.int64) -> np.ndarray:
        """Encode to a requested integer dtype or reject any overflow/loss."""

        divisor_value = _integer("PanopticMap.divisor", divisor, np.int64)
        if divisor_value <= 0:
            raise ContractViolation("PanopticMap.divisor: expected a positive integer")
        try:
            output_dtype = np.dtype(dtype)
        except (TypeError, ValueError):
            raise ContractViolation(
                "PanopticMap.dtype: expected a plain integer dtype"
            ) from None
        if output_dtype.fields is not None or output_dtype.kind not in {"i", "u"}:
            raise ContractViolation("PanopticMap.dtype: expected a plain integer dtype")
        classes = self.semantic.class_ids
        instances = self.instance.instance_ids
        if classes.size and int(classes.min()) < 0:
            raise ContractViolation(
                "PanopticMap: packed conversion cannot represent negative semantic ids"
            )
        if instances.size and (
            int(instances.min()) < 0 or int(instances.max()) >= divisor_value
        ):
            raise ContractViolation(
                "PanopticMap: packed instance ids must satisfy 0 <= id < divisor"
            )
        max_class = 0 if not classes.size else int(classes.max())
        max_instance = 0 if not instances.size else int(instances.max())
        if max_class > (np.iinfo(np.int64).max - max_instance) // divisor_value:
            raise ContractViolation("PanopticMap: packed value exceeds int64")
        packed = classes.astype(np.int64) * divisor_value + instances
        if packed.size:
            bounds = np.iinfo(output_dtype)
            minimum = int(packed.min())
            maximum = int(packed.max())
            if minimum < bounds.min or maximum > bounds.max:
                raise ContractViolation(
                    f"PanopticMap: packed values exceed {output_dtype.name}"
                )
        return np.array(packed, dtype=output_dtype, copy=True, order="C")


@dataclass(frozen=True)
class Pointmap:
    """Per-pixel 3-D points — (H, W, 3) float32 — in a declared frame.

    ``frame`` declares the coordinate frame of the points: ``"world"``
    (the owning set's world frame, see :class:`FrameMeta`) or
    ``"camera"`` (the emitting view's camera frame). Invalid pixels may
    be NaN.
    """

    points: np.ndarray  # (H, W, 3) float32
    frame: Literal["world", "camera"] = "world"

    def __post_init__(self) -> None:
        ensure_array("Pointmap.points", self.points, dtypes=(np.float32,), shape=(None, None, 3))
        ensure_choice("Pointmap.frame", self.frame, POINTMAP_FRAMES)

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.points.shape[0]), int(self.points.shape[1]))


@dataclass(frozen=True)
class ConfidenceMap:
    """Per-pixel confidence in [0, 1] — (H, W) float32, finite."""

    values: np.ndarray  # (H, W) float32 in [0, 1]

    def __post_init__(self) -> None:
        values = ensure_array(
            "ConfidenceMap.values",
            self.values,
            dtypes=(np.float32,),
            shape=(None, None),
            finite=True,
        )
        if values.size:
            lo, hi = float(values.min()), float(values.max())
            if lo < 0.0 or hi > 1.0:
                raise ContractViolation(
                    f"ConfidenceMap.values: values must lie in [0, 1] "
                    f"(observed range [{lo:g}, {hi:g}])"
                )

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.values.shape[0]), int(self.values.shape[1]))


@dataclass(frozen=True)
class Mask:
    """Per-pixel boolean mask — (H, W) bool. True = pixel participates."""

    mask: np.ndarray  # (H, W) bool

    def __post_init__(self) -> None:
        ensure_array("Mask.mask", self.mask, dtypes=(np.bool_,), shape=(None, None))

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.mask.shape[0]), int(self.mask.shape[1]))
