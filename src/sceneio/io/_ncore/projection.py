"""Exact NCore-item projections into existing SceneIO record types.

NCore's camera-label descriptor identifies a label family, but does not define
the void/background values or a taxonomy for segmentation labels.  Those
values are therefore accepted only from an explicit metadata extension.  In
particular, observed pixel values are never used to guess either meaning.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from sceneio import _core
from sceneio.data.dense import (
    InstanceMap,
    LabelTaxonomy,
    Mask,
    PanopticMap,
    SemanticMap,
)
from sceneio.errors import ContractViolation
from sceneio.io._ncore.model import (
    NCoreArray,
    NCoreComponent,
    NCoreComponentData,
    NCoreGroup,
    NCoreItem,
    NCoreSelection,
)

_IMAGE_READERS = {
    "exr": _core.read_exr,
    "hdr": _core.read_hdr,
    "jpeg": _core.read_jpeg,
    "jpg": _core.read_jpeg,
    "pgm": _core.read_netpbm,
    "png": _core.read_png,
    "pnm": _core.read_netpbm,
    "ppm": _core.read_netpbm,
    "webp": _core.read_webp,
}

_SEGMENTATION_CATEGORY = "SEGMENTATION"
_SEGMENTATION_QUALIFIERS = frozenset({"semantic", "instance", "panoptic"})
_LABEL_SOURCES = frozenset(
    {"AUTOLABEL", "EXTERNAL", "GT_ANNOTATION", "GT_SYNTHETIC", "UNKNOWN"}
)
_LABEL_SCHEMA = "sceneio.label_map/1"
_LABEL_METADATA_KEY = "__sceneio_label_map_v1__"
_TAXONOMY_FIELDS = frozenset(
    {
        "taxonomy_semantic_ids",
        "taxonomy_names",
        "taxonomy_identity",
        "taxonomy_version",
        "taxonomy_display_colors",
        "taxonomy_is_thing",
    }
)
_TABLE_FIELDS = frozenset({"table_instance_ids", "table_semantic_ids"})
_LABEL_FIELDS = {
    "semantic": frozenset({"schema", "kind", "semantic_void_id"})
    | _TAXONOMY_FIELDS,
    "instance": frozenset({"schema", "kind", "instance_background_id"})
    | _TABLE_FIELDS,
    "panoptic": frozenset(
        {
            "schema",
            "kind",
            "semantic_void_id",
            "instance_background_id",
            "panoptic_label_divisor",
        }
    )
    | _TAXONOMY_FIELDS
    | _TABLE_FIELDS,
}
_LABEL_REQUIRED_FIELDS = {
    "semantic": frozenset({"schema", "kind", "semantic_void_id"}),
    "instance": frozenset({"schema", "kind", "instance_background_id"}),
    "panoptic": frozenset(
        {
            "schema",
            "kind",
            "semantic_void_id",
            "instance_background_id",
            "panoptic_label_divisor",
        }
    ),
}


def _encoded_bytes(value: np.ndarray, context: str) -> bytes:
    if value.ndim == 0 and value.dtype.kind in {"S", "V"}:
        return bytes(value)
    if value.ndim == 1 and value.dtype == np.dtype("uint8"):
        return value.tobytes()
    raise ValueError(f"{context} does not contain encoded bytes")


def _image(item: NCoreItem, array_name: str, format_name: str):
    try:
        reader = _IMAGE_READERS[format_name.lower()]
    except KeyError:
        raise ValueError(
            f"NCore image format {format_name!r} has no SceneIO projection"
        ) from None
    return reader(memoryview(_encoded_bytes(item.array(array_name), "NCore image")))


def _mask(item: NCoreItem) -> Mask:
    image = _image(item, "data", str(item.attributes["format"]))
    pixels = np.asarray(image.pixels)
    if pixels.ndim == 3:
        first = pixels[..., 0]
        if not np.all(pixels == first[..., None]):
            raise ValueError(
                "NCore camera mask channels disagree and cannot form one boolean mask"
            )
        pixels = first
    try:
        return Mask(np.array(pixels != 0, dtype=bool, copy=True, order="C"))
    except ContractViolation as exc:
        raise ValueError(f"NCore camera mask cannot form a SceneIO Mask: {exc}") from exc


def _point_cloud(item: NCoreItem):
    if item.attributes.get("coordinate_unit") != "METERS":
        raise ValueError(
            "NCore point-cloud projection requires metric coordinates"
        )
    raw_schemas = item.attributes.get("attribute_schemas", {})
    if not isinstance(raw_schemas, Mapping):
        raise ValueError("NCore point-cloud attribute schemas are invalid")
    arrays = item.arrays
    if any(name.startswith("generic_data/") for name in arrays):
        raise ValueError(
            "NCore point-cloud generic arrays have no exact PointCloud payload projection"
        )
    recognized = {"color", "colors", "intensity", "normal", "normals", "rgb"}
    unknown = set(raw_schemas) - recognized
    if unknown:
        raise ValueError(
            "NCore point-cloud attributes have no exact PointCloud payload projection: "
            + ", ".join(sorted(unknown))
        )
    unexpected_arrays = set(arrays) - {"xyz", *raw_schemas}
    if unexpected_arrays:
        raise ValueError(
            "NCore point-cloud arrays have no exact PointCloud payload projection: "
            + ", ".join(sorted(unexpected_arrays))
        )
    color_names = tuple(name for name in ("rgb", "colors", "color") if name in arrays)
    normal_names = tuple(name for name in ("normals", "normal") if name in arrays)
    if len(color_names) > 1 or len(normal_names) > 1:
        raise ValueError("NCore point-cloud projection has duplicate standard channels")
    colors = arrays[color_names[0]] if color_names else None
    normals = arrays[normal_names[0]] if normal_names else None
    intensity = arrays.get("intensity")
    if colors is not None and (
        colors.dtype != np.dtype("uint8")
        or colors.shape != (len(item.array("xyz")), 3)
    ):
        raise ValueError("NCore point-cloud colors must be uint8 (N, 3)")
    if normals is not None and (
        normals.dtype != np.dtype("float32")
        or normals.shape != (len(item.array("xyz")), 3)
    ):
        raise ValueError("NCore point-cloud normals must be float32 (N, 3)")
    if intensity is not None and (
        intensity.dtype != np.dtype("float32")
        or intensity.shape != (len(item.array("xyz")),)
    ):
        raise ValueError("NCore point-cloud intensity must be float32 (N,)")
    return _core.point_cloud(
        item.array("xyz"),
        colors=colors,
        normals=normals,
        intensity=intensity,
        coordinate_frame="unknown",
        scale_to_meters=1.0,
        intensity_range="unknown",
    )


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    if any(not isinstance(name, str) for name in value):
        raise ValueError(f"{context} keys must be strings")
    return value


def _descriptor(item: NCoreItem) -> Mapping[str, object]:
    raw = item.attributes.get("descriptor")
    if raw is None:
        raise ValueError(
            "NCore camera-label projection requires its complete descriptor"
        )
    descriptor = _mapping(raw, "NCore camera-label descriptor")
    camera_id = descriptor.get("camera_id")
    if not isinstance(camera_id, str) or not camera_id:
        raise ValueError("NCore camera-label descriptor requires camera_id")
    label_source = descriptor.get("label_source")
    if not isinstance(label_source, str) or label_source not in _LABEL_SOURCES:
        raise ValueError("NCore camera-label descriptor has invalid label_source")
    return descriptor


def _label_kind(item: NCoreItem) -> tuple[str, str, Mapping[str, object]]:
    descriptor = _descriptor(item)
    label_type = _mapping(
        descriptor.get("label_type"), "NCore camera-label label_type"
    )
    if set(label_type) != {"category", "qualifier", "unit"}:
        raise ValueError(
            "NCore segmentation label_type fields must be exactly "
            "category, qualifier, and unit"
        )
    category = label_type.get("category")
    qualifier = label_type.get("qualifier")
    if category != _SEGMENTATION_CATEGORY:
        raise ValueError(
            "NCore camera-label projection supports only category 'SEGMENTATION'"
        )
    if not isinstance(qualifier, str) or qualifier not in _SEGMENTATION_QUALIFIERS:
        raise ValueError(
            "NCore segmentation qualifier must be one of semantic, instance, panoptic"
        )
    if label_type.get("unit") != "UNITLESS":
        raise ValueError("NCore segmentation labels require unit 'UNITLESS'")
    schema = _mapping(
        descriptor.get("label_schema"), "NCore camera-label label_schema"
    )
    required_schema = {"dtype", "shape_suffix", "encoding"}
    allowed_schema = required_schema | {"encoded_format", "quantization"}
    missing_schema = required_schema - set(schema)
    unknown_schema = set(schema) - allowed_schema
    if missing_schema or unknown_schema:
        details = []
        if missing_schema:
            details.append("missing " + ", ".join(sorted(missing_schema)))
        if unknown_schema:
            details.append("unknown " + ", ".join(sorted(unknown_schema)))
        raise ValueError(
            "NCore segmentation label_schema fields are invalid; "
            + "; ".join(details)
        )
    return str(qualifier), str(category), schema


def _metadata(
    item: NCoreItem,
    descriptor: Mapping[str, object],
    qualifier: str,
) -> Mapping[str, object]:
    descriptor_generic = descriptor.get("generic_meta_data", {})
    descriptor_metadata = _mapping(
        {} if descriptor_generic is None else descriptor_generic,
        "NCore camera-label descriptor metadata",
    )
    item_generic = item.attributes.get("generic_meta_data", {})
    item_metadata = _mapping(
        {} if item_generic is None else item_generic,
        "NCore camera-label item metadata",
    )
    if _LABEL_METADATA_KEY in item_metadata:
        raise ValueError(
            "NCore camera-label SceneIO label metadata must be declared on the descriptor"
        )
    if _LABEL_METADATA_KEY not in descriptor_metadata:
        raise ValueError(
            "NCore camera-label projection requires the explicit "
            f"{_LABEL_METADATA_KEY} descriptor extension"
        )
    extension = _mapping(
        descriptor_metadata[_LABEL_METADATA_KEY], "SceneIO label metadata"
    )
    if extension.get("schema") != _LABEL_SCHEMA:
        raise ValueError(
            "NCore camera-label SceneIO label metadata has unsupported schema"
        )
    unknown = set(extension) - _LABEL_FIELDS[qualifier]
    if unknown:
        raise ValueError(
            "NCore camera-label SceneIO label metadata contains unknown or "
            "incompatible fields "
            + ", ".join(sorted(repr(name) for name in unknown))
        )
    missing = _LABEL_REQUIRED_FIELDS[qualifier] - set(extension)
    if missing:
        raise ValueError(
            "NCore camera-label SceneIO label metadata is incomplete; missing "
            + ", ".join(sorted(missing))
        )
    return extension


def _integer(value: object, context: str, dtype: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{context} must be an integer")
    result = int(value)
    bounds = np.iinfo(dtype)
    if result < bounds.min or result > bounds.max:
        raise ValueError(f"{context} is outside {np.dtype(dtype).name}")
    return result


def _explicit_id(metadata: Mapping[str, object], names: tuple[str, ...], context: str, dtype: object) -> int:
    present = [name for name in names if name in metadata]
    if not present:
        raise ValueError(f"NCore {context} requires explicit metadata")
    values = [_integer(metadata[name], f"NCore {context}", dtype) for name in present]
    if any(value != values[0] for value in values[1:]):
        raise ValueError(f"NCore {context} metadata disagrees")
    return values[0]


def _taxonomy(metadata: Mapping[str, object]) -> LabelTaxonomy | None:
    required_names = (
        "taxonomy_semantic_ids",
        "taxonomy_names",
        "taxonomy_identity",
        "taxonomy_version",
    )
    names = (*required_names, "taxonomy_display_colors", "taxonomy_is_thing")
    present = {name for name in names if name in metadata}
    if not present:
        return None
    missing_names = set(required_names) - present
    if missing_names:
        missing = ", ".join(sorted(missing_names))
        raise ValueError(f"NCore label taxonomy is incomplete; missing {missing}")
    ids_value = metadata["taxonomy_semantic_ids"]
    names_value = metadata["taxonomy_names"]
    if not isinstance(ids_value, (list, tuple)) or not isinstance(names_value, (list, tuple)):
        raise ValueError("NCore label taxonomy ids/names must be arrays")
    ids = np.asarray(
        [_integer(value, "NCore taxonomy semantic id", np.int32) for value in ids_value],
        dtype=np.int32,
    )
    names = tuple(names_value)
    identity = metadata["taxonomy_identity"]
    version = metadata["taxonomy_version"]
    if not isinstance(identity, str) or not identity:
        raise ValueError("NCore label taxonomy requires explicit identity")
    if not isinstance(version, str) or not version:
        raise ValueError("NCore label taxonomy requires explicit version")
    colors = metadata.get("taxonomy_display_colors")
    is_thing = metadata.get("taxonomy_is_thing")
    if colors is not None:
        colors_array = (
            np.empty((0, 3), dtype=np.uint8)
            if isinstance(colors, (list, tuple)) and not colors
            else np.asarray(colors)
        )
        if colors_array.dtype.kind not in {"i", "u"} or (
            colors_array.size
            and (
                int(colors_array.min()) < 0
                or int(colors_array.max()) > np.iinfo(np.uint8).max
            )
        ):
            raise ValueError("NCore label taxonomy display_colors must be uint8 values")
        colors = np.array(colors_array, dtype=np.uint8, copy=True, order="C")
    if is_thing is not None:
        is_thing_array = (
            np.empty(0, dtype=bool)
            if isinstance(is_thing, (list, tuple)) and not is_thing
            else np.asarray(is_thing)
        )
        if is_thing_array.dtype != np.dtype("bool"):
            raise ValueError("NCore label taxonomy is_thing must be bool values")
        is_thing = np.array(is_thing_array, dtype=np.bool_, copy=True, order="C")
    try:
        return LabelTaxonomy(ids, names, identity, version, colors, is_thing)
    except ContractViolation as exc:
        raise ValueError(f"NCore label taxonomy is invalid: {exc}") from exc


def _label_array(item: NCoreItem, schema: Mapping[str, object]) -> np.ndarray:
    encoding = schema.get("encoding")
    shape_suffix = schema.get("shape_suffix")
    if not isinstance(shape_suffix, (list, tuple)) or any(
        isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0
        for value in shape_suffix
    ):
        raise ValueError("NCore camera-label shape_suffix is invalid")
    if tuple(shape_suffix):
        raise ValueError("NCore segmentation labels require an empty shape_suffix")
    if schema.get("quantization") is not None:
        raise ValueError("NCore segmentation labels cannot use quantization")
    try:
        declared_dtype = np.dtype(schema.get("dtype"))
    except (TypeError, ValueError) as exc:
        raise ValueError("NCore camera-label schema dtype is invalid") from exc
    if declared_dtype.kind not in {"i", "u"}:
        raise ValueError("NCore segmentation schema dtype must be integer")
    if encoding == "IMAGE_ENCODED":
        encoded_format = schema.get("encoded_format")
        if not isinstance(encoded_format, str) or not encoded_format:
            raise ValueError("NCore encoded label requires encoded_format")
        pixels = np.asarray(_image(item, "data", encoded_format).pixels)
    elif encoding == "RAW":
        if schema.get("encoded_format") is not None:
            raise ValueError("NCore raw segmentation labels cannot declare encoded_format")
        pixels = np.asarray(item.array("data"))
    else:
        raise ValueError("NCore camera-label encoding must be RAW or IMAGE_ENCODED")
    if pixels.ndim != 2:
        raise ValueError("NCore segmentation labels must be single-channel HxW arrays")
    if pixels.dtype.kind not in {"i", "u"}:
        raise ValueError("NCore segmentation labels must use an integer dtype")
    if pixels.dtype != declared_dtype:
        raise ValueError(
            "NCore segmentation label dtype disagrees with its descriptor"
        )
    if not pixels.flags.c_contiguous:
        raise ValueError("NCore segmentation labels must be C-contiguous")
    return pixels


def _valid_array(item: NCoreItem, shape: tuple[int, int]) -> np.ndarray | None:
    if "valid" not in item.arrays:
        return None
    valid = np.asarray(item.array("valid"))
    if valid.dtype != np.dtype("bool") or valid.shape != shape:
        raise ValueError("NCore label valid array must be a bool HxW array")
    if not valid.flags.c_contiguous:
        raise ValueError("NCore label valid array must be C-contiguous")
    return valid


def _instance_table(metadata: Mapping[str, object]) -> tuple[np.ndarray, np.ndarray] | None:
    raw_ids = metadata.get("table_instance_ids")
    raw_semantics = metadata.get("table_semantic_ids")
    if raw_ids is None and raw_semantics is None:
        return None
    if not isinstance(raw_ids, (list, tuple)) or not isinstance(raw_semantics, (list, tuple)):
        raise ValueError("NCore instance table arrays must be arrays")
    if len(raw_ids) != len(raw_semantics):
        raise ValueError("NCore instance table arrays must have equal length")
    ids = np.asarray(
        [_integer(key, "NCore instance table id", np.int64) for key in raw_ids],
        dtype=np.int64,
    )
    classes = np.asarray(
        [_integer(value, "NCore instance table semantic id", np.int32) for value in raw_semantics],
        dtype=np.int32,
    )
    return np.array(ids, copy=True, order="C"), np.array(classes, copy=True, order="C")


def _semantic_map(item: NCoreItem, metadata: Mapping[str, object], schema: Mapping[str, object]) -> SemanticMap:
    values = _label_array(item, schema)
    if values.size and (int(values.min()) < np.iinfo(np.int32).min or int(values.max()) > np.iinfo(np.int32).max):
        raise ValueError("NCore semantic ids exceed int32")
    class_ids = np.asarray(values, dtype=np.int32, order="C")
    void_id = _explicit_id(metadata, ("semantic_void_id",), "semantic void_id", np.int32)
    try:
        return SemanticMap(class_ids, void_id, _valid_array(item, class_ids.shape), _taxonomy(metadata))
    except ContractViolation as exc:
        raise ValueError(f"NCore semantic label is not representable: {exc}") from exc


def _instance_map(item: NCoreItem, metadata: Mapping[str, object], schema: Mapping[str, object]) -> InstanceMap:
    values = _label_array(item, schema)
    if values.size and int(values.min()) < np.iinfo(np.int64).min:
        raise ValueError("NCore instance ids exceed int64")
    if values.size and int(values.max()) > np.iinfo(np.int64).max:
        raise ValueError("NCore instance ids exceed int64")
    instance_ids = np.asarray(values, dtype=np.int64, order="C")
    background_id = _explicit_id(
        metadata,
        ("instance_background_id",),
        "instance background_id",
        np.int64,
    )
    table = _instance_table(metadata)
    try:
        return InstanceMap(
            instance_ids,
            background_id,
            _valid_array(item, instance_ids.shape),
            None if table is None else table[0],
            None if table is None else table[1],
        )
    except ContractViolation as exc:
        raise ValueError(f"NCore instance label is not representable: {exc}") from exc


def _panoptic_map(item: NCoreItem, metadata: Mapping[str, object], schema: Mapping[str, object]) -> PanopticMap:
    values = _label_array(item, schema)
    divisor = _explicit_id(
        metadata,
        ("panoptic_label_divisor",),
        "panoptic label divisor",
        np.int64,
    )
    if divisor <= 0:
        raise ValueError("NCore panoptic label divisor must be positive")
    void_id = _explicit_id(metadata, ("semantic_void_id",), "panoptic void_id", np.int32)
    background_id = _explicit_id(
        metadata,
        ("instance_background_id",),
        "panoptic background_id",
        np.int64,
    )
    valid = _valid_array(item, values.shape)
    try:
        decoded = PanopticMap.from_packed(
            values,
            divisor=divisor,
            void_id=void_id,
            background_id=background_id,
            valid=valid,
            taxonomy=_taxonomy(metadata),
        )
        table = _instance_table(metadata)
        if table is None:
            return decoded
        instance = InstanceMap(
            decoded.instance.instance_ids,
            decoded.instance.background_id,
            decoded.instance.valid,
            table[0],
            table[1],
        )
        return PanopticMap(decoded.semantic, instance)
    except ContractViolation as exc:
        raise ValueError(f"NCore panoptic label is not representable: {exc}") from exc


def _camera_label(item: NCoreItem):
    descriptor = _descriptor(item)
    qualifier, _category, schema = _label_kind(item)
    metadata = _metadata(item, descriptor, qualifier)
    declared_kind = metadata.get("kind")
    if declared_kind is not None and declared_kind != qualifier:
        raise ValueError("NCore camera-label metadata kind disagrees with its descriptor")
    if qualifier == "semantic":
        return _semantic_map(item, metadata, schema)
    if qualifier == "instance":
        return _instance_map(item, metadata, schema)
    return _panoptic_map(item, metadata, schema)


def project_ncore_item(item: NCoreItem):
    """Project an exact item payload while its NCore metadata stays on ``item``.

    Only the three official NCore segmentation qualifiers (``semantic``,
    ``instance``, and ``panoptic``) have an unambiguous SceneIO map record.
    """

    if not isinstance(item, NCoreItem):
        raise TypeError("item must be an NCoreItem")
    if item.kind == "camera_frame":
        return _image(item, "image", str(item.attributes["image_format"]))
    if item.kind == "camera_mask":
        return _mask(item)
    if item.kind == "camera_label":
        return _camera_label(item)
    if item.kind == "point_cloud":
        return _point_cloud(item)
    raise ValueError(
        f"NCore item kind {item.kind!r} has no exact SceneIO payload projection"
    )


def _taxonomy_metadata(taxonomy: LabelTaxonomy | None) -> dict[str, object] | None:
    if taxonomy is None:
        return None
    document: dict[str, object] = {
        "semantic_ids": [int(value) for value in taxonomy.semantic_ids],
        "names": list(taxonomy.names),
        "identity": taxonomy.identity,
        "version": taxonomy.version,
    }
    if taxonomy.display_colors is not None:
        document["display_colors"] = taxonomy.display_colors.tolist()
    if taxonomy.is_thing is not None:
        document["is_thing"] = taxonomy.is_thing.tolist()
    return document


def _component_data_from_sceneio_label_map(
    value: SemanticMap | InstanceMap | PanopticMap,
    *,
    instance_name: str,
    camera_id: str,
    timestamp_us: int,
    group: str = "",
    label_source: str = "EXTERNAL",
    panoptic_label_divisor: int | None = None,
) -> NCoreComponentData:
    """Build one complete ``camera_labels`` component for ``write_ncore_v4``.

    The helper deliberately refuses validity masks: NCore camera-label V4 has
    one data array per timestamp and no standard validity companion.  The
    SceneIO extension metadata carries taxonomy and id semantics losslessly.
    """

    if isinstance(value, PanopticMap):
        qualifier = "panoptic"
        selected = value
        if panoptic_label_divisor is None:
            raise ValueError("reverse NCore panoptic projection requires panoptic_label_divisor")
        divisor = _integer(
            panoptic_label_divisor,
            "reverse NCore panoptic label divisor",
            np.int64,
        )
        if divisor <= 0:
            raise ValueError("reverse NCore panoptic label divisor must be positive")
        if not 0 <= value.instance.background_id < divisor:
            raise ValueError(
                "reverse NCore panoptic background_id must satisfy "
                "0 <= background_id < panoptic_label_divisor"
            )
        data = value.to_packed(divisor=divisor, dtype=np.uint64)
        taxonomy = value.semantic.taxonomy
        metadata: dict[str, object] = {
            "semantic_void_id": value.semantic.void_id,
            "instance_background_id": value.instance.background_id,
            "panoptic_label_divisor": divisor,
        }
        table = value.instance.table_instance_ids
        if table is not None:
            metadata["table_instance_ids"] = [int(instance) for instance in table]
            metadata["table_semantic_ids"] = [
                int(semantic) for semantic in value.instance.table_semantic_ids
            ]
    elif isinstance(value, SemanticMap):
        qualifier = "semantic"
        selected = value
        data = np.array(value.class_ids, copy=True, order="C")
        taxonomy = value.taxonomy
        metadata = {"semantic_void_id": value.void_id}
    elif isinstance(value, InstanceMap):
        qualifier = "instance"
        selected = value
        data = np.array(value.instance_ids, copy=True, order="C")
        taxonomy = None
        metadata = {"instance_background_id": value.background_id}
        table = value.table_instance_ids
        if table is not None:
            metadata["table_instance_ids"] = [int(instance) for instance in table]
            metadata["table_semantic_ids"] = [
                int(semantic) for semantic in value.table_semantic_ids
            ]
    else:
        raise TypeError("value must be a SemanticMap, InstanceMap, or PanopticMap")
    if selected.valid is not None:
        raise ValueError("reverse NCore camera-label projection cannot encode a validity mask")
    if not isinstance(instance_name, str) or not instance_name:
        raise ValueError("NCore camera-label instance_name must be non-empty")
    if not isinstance(camera_id, str) or not camera_id:
        raise ValueError("NCore camera-label camera_id must be non-empty")
    if isinstance(timestamp_us, bool) or not isinstance(timestamp_us, (int, np.integer)):
        raise ValueError("NCore camera-label timestamp_us must be an integer")
    timestamp = int(timestamp_us)
    if timestamp < 0 or timestamp > np.iinfo(np.uint64).max:
        raise ValueError("NCore camera-label timestamp_us is outside uint64")
    if not isinstance(label_source, str) or label_source not in _LABEL_SOURCES:
        raise ValueError("NCore camera-label label_source is invalid")
    extension = {"schema": _LABEL_SCHEMA, "kind": qualifier, **metadata}
    taxonomy_document = _taxonomy_metadata(taxonomy)
    if taxonomy_document is not None:
        extension.update(
            {
                "taxonomy_semantic_ids": taxonomy_document["semantic_ids"],
                "taxonomy_names": taxonomy_document["names"],
                "taxonomy_identity": taxonomy_document["identity"],
                "taxonomy_version": taxonomy_document["version"],
            }
        )
        if "display_colors" in taxonomy_document:
            extension["taxonomy_display_colors"] = taxonomy_document["display_colors"]
        if "is_thing" in taxonomy_document:
            extension["taxonomy_is_thing"] = taxonomy_document["is_thing"]
    descriptor = {
        "camera_id": camera_id,
        "label_type": {
            "category": _SEGMENTATION_CATEGORY,
            "qualifier": qualifier,
            "unit": "UNITLESS",
        },
        "label_schema": {
            "dtype": data.dtype.str,
            "shape_suffix": [],
            "encoding": "RAW",
            "encoded_format": None,
            "quantization": None,
        },
        "label_source": label_source,
        "generic_meta_data": {_LABEL_METADATA_KEY: extension},
    }
    root_attributes = {
        "component_name": "camera_labels",
        "component_instance_name": instance_name,
        "component_version": "v1",
        "generic_meta_data": {},
    }
    descriptors = (
        NCoreArray("timestamps_us", (1,), np.dtype("uint64").str, (1,)),
        NCoreArray(
            f"labels/{timestamp}/data",
            data.shape,
            data.dtype.str,
            tuple(max(1, int(size)) for size in data.shape),
        ),
    )
    component = NCoreComponent(
        "camera_labels",
        instance_name,
        "v1",
        group,
        0,
        arrays=descriptors,
    )
    groups = (
        NCoreGroup("", root_attributes),
        NCoreGroup("labels", {"descriptor": descriptor}),
        NCoreGroup(
            f"labels/{timestamp}",
            {"generic_meta_data": {}},
        ),
    )
    arrays = {
        "timestamps_us": np.array([timestamp], dtype=np.uint64),
        f"labels/{timestamp}/data": data,
    }
    return NCoreComponentData(
        component,
        NCoreSelection("camera_labels", instance_name, group=group),
        arrays,
        groups,
    )


__all__ = ["project_ncore_item"]
