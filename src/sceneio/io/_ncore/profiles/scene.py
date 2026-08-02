"""NCore V4 point-cloud and annotation component profiles."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from sceneio.io._ncore.model import (
    NCoreComponentData,
    NCoreItem,
    NCoreSemanticComponent,
)
from sceneio.io._ncore.profiles.common import (
    array_attributes,
    arrays_below,
    child_group_names,
    finite_number,
    integer,
    mapping,
    non_empty_string,
    numeric_vector,
    require_group,
    require_version,
    sequence,
    validate_sequence_timestamp,
)

_ATTRIBUTE_TRANSFORMS = {"DIRECTION", "INVARIANT", "POINT"}
_COORDINATE_UNITS = {"METERS", "UNITLESS"}
_LABEL_CATEGORIES = {
    "DEPTH",
    "FEATURE",
    "FLOW",
    "GEOMETRY",
    "MASK",
    "MATERIAL",
    "OTHER",
    "SEGMENTATION",
    "UNKNOWN",
}
_LABEL_UNITS = {"METERS", "PIXELS", "UNITLESS", "UNKNOWN"}
_LABEL_SOURCES = {
    "AUTOLABEL",
    "EXTERNAL",
    "GT_ANNOTATION",
    "GT_SYNTHETIC",
    "UNKNOWN",
}


def _dtype(value: object, context: str) -> np.dtype:
    try:
        result = np.dtype(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} has an invalid dtype") from exc
    if result.hasobject:
        raise ValueError(f"{context} cannot use object dtype")
    return result


def _shape_suffix(value: object, context: str) -> tuple[int, ...]:
    raw = sequence(value, context)
    return tuple(integer(item, f"{context}[{index}]") for index, item in enumerate(raw))


def _point_cloud_indices(
    data: NCoreComponentData, timestamps: np.ndarray
) -> tuple[int, ...]:
    has_selection = (
        data.selection.frames is not None
        or data.selection.timestamps_us is not None
    )
    if has_selection:
        try:
            indices = tuple(int(value) for value in data.selected_items)
        except ValueError:
            raise ValueError("NCore point-cloud selected item ids must be indices") from None
        if len(indices) != len(timestamps):
            raise ValueError("NCore point-cloud selection timestamps disagree")
        return indices
    return tuple(range(len(timestamps)))


def read_point_clouds_profile(
    data: NCoreComponentData,
    sequence_interval_us: tuple[int, int],
) -> NCoreSemanticComponent:
    require_version(data)
    pcs_group = require_group(data, "pcs")
    coordinate_unit = pcs_group.attributes.get("coordinate_unit")
    if coordinate_unit not in _COORDINATE_UNITS:
        raise ValueError("NCore point-cloud coordinate_unit is invalid")
    raw_schemas = mapping(
        pcs_group.attributes.get("attribute_schemas", {}),
        "NCore point-cloud attribute_schemas",
    )
    schemas: dict[str, tuple[str, np.dtype, tuple[int, ...]]] = {}
    for name, raw_schema in raw_schemas.items():
        non_empty_string(name, "NCore point-cloud attribute name")
        schema = mapping(raw_schema, f"NCore point-cloud attribute {name!r}")
        transform = schema.get("transform_type")
        if transform not in _ATTRIBUTE_TRANSFORMS:
            raise ValueError(
                f"NCore point-cloud attribute {name!r} transform is invalid"
            )
        schemas[name] = (
            str(transform),
            _dtype(schema.get("dtype"), f"NCore point-cloud attribute {name!r}"),
            _shape_suffix(
                schema.get("shape_suffix", ()),
                f"NCore point-cloud attribute {name!r} shape_suffix",
            ),
        )
    try:
        timestamps = data.arrays["pc_timestamps_us"]
    except KeyError:
        raise ValueError("NCore point-cloud component lacks pc_timestamps_us") from None
    if timestamps.dtype != np.dtype("uint64") or timestamps.ndim != 1:
        raise ValueError("NCore point-cloud timestamps must be a uint64 vector")
    indices = _point_cloud_indices(data, timestamps)
    if data.selection.frames is None and data.selection.timestamps_us is None:
        group_indices = set(child_group_names(data, "pcs"))
        expected = {str(index) for index in range(len(timestamps))}
        if group_indices != expected:
            raise ValueError("NCore point-cloud groups must be contiguous and aligned")
    items: list[NCoreItem] = []
    for index, raw_timestamp in zip(indices, timestamps, strict=True):
        timestamp = int(raw_timestamp)
        validate_sequence_timestamp(
            timestamp, sequence_interval_us, "NCore point-cloud timestamp"
        )
        pc_group = require_group(data, f"pcs/{index}")
        reference_frame_id = non_empty_string(
            pc_group.attributes.get("reference_frame_id"),
            f"NCore point-cloud {index} reference_frame_id",
        )
        generic_meta_data = mapping(
            pc_group.attributes.get("generic_meta_data", {}),
            f"NCore point-cloud {index} generic_meta_data",
        )
        require_group(data, f"pcs/{index}/generic_data")
        arrays = arrays_below(data, f"pcs/{index}")
        try:
            xyz = arrays["xyz"]
        except KeyError:
            raise ValueError(f"NCore point-cloud {index} lacks xyz") from None
        if xyz.dtype != np.dtype("float32") or xyz.ndim != 2 or xyz.shape[1] != 3:
            raise ValueError(f"NCore point-cloud {index} xyz must be float32 (N, 3)")
        if not np.all(np.isfinite(xyz)):
            raise ValueError(f"NCore point-cloud {index} xyz must be finite")
        for name, (transform, dtype, suffix) in schemas.items():
            try:
                attribute = arrays[name]
            except KeyError:
                raise ValueError(
                    f"NCore point-cloud {index} lacks attribute {name!r}"
                ) from None
            if attribute.dtype != dtype or attribute.shape != (len(xyz), *suffix):
                raise ValueError(
                    f"NCore point-cloud {index} attribute {name!r} "
                    "disagrees with its schema"
                )
            if transform in {"DIRECTION", "POINT"} and suffix != (3,):
                raise ValueError(
                    f"NCore point-cloud attribute {name!r} transform requires vectors"
                )
        items.append(
            NCoreItem(
                kind="point_cloud",
                id=str(index),
                arrays=arrays,
                attributes={
                    "generic_meta_data": dict(generic_meta_data),
                    "coordinate_unit": coordinate_unit,
                    "attribute_schemas": dict(raw_schemas),
                },
                timestamp_us=timestamp,
                reference_frame_id=reference_frame_id,
            )
        )
    return NCoreSemanticComponent(
        raw=data,
        profile="point_clouds/v1",
        items=tuple(items),
        attributes={
            "coordinate_unit": coordinate_unit,
            "attribute_schemas": dict(raw_schemas),
        },
    )


def read_cuboids_profile(
    data: NCoreComponentData,
    sequence_interval_us: tuple[int, int],
) -> NCoreSemanticComponent:
    require_version(data)
    raw_observations = require_group(data, "cuboids").attributes.get(
        "cuboid_track_observations"
    )
    observations = sequence(raw_observations, "NCore cuboid observations")
    items: list[NCoreItem] = []
    for index, raw_observation in enumerate(observations):
        context = f"NCore cuboid observation {index}"
        observation = mapping(raw_observation, context)
        track_id = non_empty_string(observation.get("track_id"), f"{context}.track_id")
        class_id = non_empty_string(observation.get("class_id"), f"{context}.class_id")
        timestamp = integer(observation.get("timestamp_us"), f"{context}.timestamp_us")
        reference_timestamp = integer(
            observation.get("reference_frame_timestamp_us"),
            f"{context}.reference_frame_timestamp_us",
        )
        validate_sequence_timestamp(timestamp, sequence_interval_us, context)
        validate_sequence_timestamp(
            reference_timestamp, sequence_interval_us, context
        )
        reference_frame_id = non_empty_string(
            observation.get("reference_frame_id"),
            f"{context}.reference_frame_id",
        )
        bbox = mapping(observation.get("bbox3"), f"{context}.bbox3")
        bbox_array = np.concatenate(
            tuple(
                numeric_vector(bbox.get(name), 3, f"{context}.bbox3.{name}")
                for name in ("centroid", "dim", "rot")
            )
        ).astype(np.float32)
        source = observation.get("source")
        if source not in _LABEL_SOURCES:
            raise ValueError(f"{context}.source is invalid")
        source_version = observation.get("source_version")
        if source_version is not None and not isinstance(source_version, str):
            raise ValueError(f"{context}.source_version must be a string or null")
        items.append(
            NCoreItem(
                kind="cuboid_observation",
                id=f"{index}:{track_id}",
                arrays={"bbox3": bbox_array},
                attributes={
                    "track_id": track_id,
                    "class_id": class_id,
                    "reference_frame_timestamp_us": reference_timestamp,
                    "source": source,
                    "source_version": source_version,
                },
                timestamp_us=timestamp,
                reference_frame_id=reference_frame_id,
            )
        )
    return NCoreSemanticComponent(
        raw=data,
        profile="cuboids/v1",
        items=tuple(items),
    )


def _label_descriptor(value: object) -> tuple[Mapping[str, object], np.dtype, tuple[int, ...], str, np.dtype]:
    descriptor = mapping(value, "NCore camera-label descriptor")
    non_empty_string(descriptor.get("camera_id"), "NCore camera-label camera_id")
    label_type = mapping(
        descriptor.get("label_type"), "NCore camera-label label_type"
    )
    if label_type.get("category") not in _LABEL_CATEGORIES:
        raise ValueError("NCore camera-label category is invalid")
    non_empty_string(label_type.get("qualifier"), "NCore camera-label qualifier")
    if label_type.get("unit") not in _LABEL_UNITS | {None}:
        raise ValueError("NCore camera-label unit is invalid")
    if descriptor.get("label_source") not in _LABEL_SOURCES:
        raise ValueError("NCore camera-label source is invalid")
    schema = mapping(
        descriptor.get("label_schema"), "NCore camera-label schema"
    )
    logical_dtype = _dtype(schema.get("dtype"), "NCore camera-label schema")
    suffix = _shape_suffix(
        schema.get("shape_suffix", ()), "NCore camera-label shape_suffix"
    )
    encoding = schema.get("encoding")
    if encoding not in {"RAW", "IMAGE_ENCODED"}:
        raise ValueError("NCore camera-label encoding is invalid")
    encoded_format = schema.get("encoded_format")
    if encoding == "IMAGE_ENCODED":
        non_empty_string(encoded_format, "NCore camera-label encoded_format")
    elif encoded_format is not None:
        raise ValueError("NCore raw camera-label cannot declare encoded_format")
    stored_dtype = logical_dtype
    quantization = schema.get("quantization")
    if quantization is not None:
        if encoding != "RAW":
            raise ValueError("NCore encoded camera-label cannot be quantized")
        quantized = mapping(quantization, "NCore camera-label quantization")
        stored_dtype = _dtype(
            quantized.get("quantized_dtype"),
            "NCore camera-label quantized dtype",
        )
        if not np.issubdtype(stored_dtype, np.integer):
            raise ValueError("NCore camera-label quantized dtype must be integer")
        scale = finite_number(
            quantized.get("scale", 1.0), "NCore camera-label quantization scale"
        )
        if scale == 0:
            raise ValueError("NCore camera-label quantization scale cannot be zero")
        finite_number(
            quantized.get("offset", 0.0), "NCore camera-label quantization offset"
        )
    return descriptor, logical_dtype, suffix, str(encoding), stored_dtype


def read_camera_labels_profile(
    data: NCoreComponentData,
    sequence_interval_us: tuple[int, int],
) -> NCoreSemanticComponent:
    require_version(data)
    labels_group = require_group(data, "labels")
    descriptor, logical_dtype, suffix, encoding, stored_dtype = _label_descriptor(
        labels_group.attributes.get("descriptor")
    )
    try:
        timestamps = data.arrays["timestamps_us"]
    except KeyError:
        raise ValueError("NCore camera-label component lacks timestamps_us") from None
    if timestamps.dtype != np.dtype("uint64") or timestamps.ndim != 1:
        raise ValueError("NCore camera-label timestamps must be a uint64 vector")
    if len(timestamps) > 1 and not np.all(timestamps[:-1] < timestamps[1:]):
        raise ValueError("NCore camera-label timestamps must be strictly increasing")
    if data.selection.frames is None and data.selection.timestamps_us is None:
        group_timestamps = set(child_group_names(data, "labels"))
        expected_timestamps = {str(int(value)) for value in timestamps}
        if group_timestamps != expected_timestamps:
            raise ValueError("NCore camera-label groups and timestamps disagree")
    items: list[NCoreItem] = []
    for raw_timestamp in timestamps:
        timestamp = int(raw_timestamp)
        validate_sequence_timestamp(
            timestamp, sequence_interval_us, "NCore camera-label timestamp"
        )
        label_id = str(timestamp)
        label_group = require_group(data, f"labels/{label_id}")
        generic = mapping(
            label_group.attributes.get("generic_meta_data", {}),
            f"NCore camera-label {label_id} generic_meta_data",
        )
        arrays = arrays_below(data, f"labels/{label_id}")
        try:
            label = arrays["data"]
        except KeyError:
            raise ValueError(f"NCore camera-label {label_id} lacks data") from None
        if encoding == "RAW":
            if label.dtype != stored_dtype or label.ndim != 2 + len(suffix):
                raise ValueError(
                    f"NCore camera-label {label_id} raw dtype/rank disagrees"
                )
            if label.shape[2:] != suffix:
                raise ValueError(
                    f"NCore camera-label {label_id} shape suffix disagrees"
                )
        else:
            if label.dtype != np.dtype("uint8") or label.ndim != 1:
                raise ValueError(
                    f"NCore camera-label {label_id} encoded data must be uint8"
                )
            attributes = array_attributes(data, f"labels/{label_id}/data")
            if attributes.get("format") != descriptor["label_schema"][
                "encoded_format"
            ]:
                raise ValueError(
                    f"NCore camera-label {label_id} encoded format disagrees"
                )
        items.append(
            NCoreItem(
                kind="camera_label",
                id=label_id,
                arrays=arrays,
                attributes={
                    "generic_meta_data": dict(generic),
                    "encoding": encoding,
                    "logical_dtype": logical_dtype.name,
                },
                timestamp_us=timestamp,
                reference_frame_id=str(descriptor["camera_id"]),
            )
        )
    return NCoreSemanticComponent(
        raw=data,
        profile="camera_labels/v1",
        items=tuple(items),
        attributes={"descriptor": dict(descriptor)},
    )


__all__ = [
    "read_camera_labels_profile",
    "read_cuboids_profile",
    "read_point_clouds_profile",
]
