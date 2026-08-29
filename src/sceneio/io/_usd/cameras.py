"""Bounded OpenUSD 26.08 camera and render-product mapping."""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import TextIO

import numpy as np

from sceneio import _core

CAMERA_PRIM_TYPE = "Camera"
RENDER_PRODUCT_PRIM_TYPE = "RenderProduct"
CAMERA_PROPERTIES = frozenset(
    {
        "clippingPlanes",
        "clippingRange",
        "exposure",
        "exposure:fStop",
        "exposure:iso",
        "exposure:responsivity",
        "exposure:time",
        "fStop",
        "focalLength",
        "focusDistance",
        "horizontalAperture",
        "horizontalApertureOffset",
        "projection",
        "shutter:close",
        "shutter:open",
        "stereoRole",
        "verticalAperture",
        "verticalApertureOffset",
    }
)
RENDER_PRODUCT_PROPERTIES = frozenset(
    {
        "aspectRatioConformPolicy",
        "camera",
        "dataWindowNDC",
        "disableDepthOfField",
        "disableMotionBlur",
        "instantaneousShutter",
        "orderedVars",
        "pixelAspectRatio",
        "productName",
        "productType",
        "resolution",
    }
)
PROJECTIONS = frozenset({"perspective", "orthographic"})
CONFORM_POLICIES = frozenset(
    {
        "adjustApertureHeight",
        "adjustApertureWidth",
        "adjustPixelAspectRatio",
        "cropAperture",
        "expandAperture",
    }
)

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_DECLARATION = re.compile(
    r"^ {4}(?:(?:custom|uniform)\s+)*"
    r"(?P<type>rel|[A-Za-z_][A-Za-z0-9_]*\[\]|"
    r"[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_:.]*)\s*=",
    re.MULTILINE,
)
_TIME_SAMPLES = re.compile(
    r"^ {4}(?:(?:custom|uniform)\s+)*"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\[\])?\s+"
    r"[A-Za-z_][A-Za-z0-9_:]*\.timeSamples\s*=",
    re.MULTILINE,
)
_CAMERA_DEFAULTS = {
    "clippingRange": (1.0, 1_000_000.0),
    "exposure": 0.0,
    "exposure:fStop": 1.0,
    "exposure:iso": 100.0,
    "exposure:responsivity": 1.0,
    "exposure:time": 1.0,
    "fStop": 0.0,
    "focalLength": 50.0,
    "focusDistance": 0.0,
    "horizontalAperture": 20.955,
    "horizontalApertureOffset": 0.0,
    "projection": "perspective",
    "shutter:close": 0.0,
    "shutter:open": 0.0,
    "stereoRole": "mono",
    "verticalAperture": 15.2908,
    "verticalApertureOffset": 0.0,
}
_CAMERA_TYPES = {
    "clippingRange": "float2",
    "exposure": "float",
    "exposure:fStop": "float",
    "exposure:iso": "float",
    "exposure:responsivity": "float",
    "exposure:time": "float",
    "fStop": "float",
    "focalLength": "float",
    "focusDistance": "float",
    "horizontalAperture": "float",
    "horizontalApertureOffset": "float",
    "projection": "token",
    "shutter:close": "double",
    "shutter:open": "double",
    "stereoRole": "token",
    "verticalAperture": "float",
    "verticalApertureOffset": "float",
}
_PRODUCT_DEFAULTS = {
    "aspectRatioConformPolicy": "expandAperture",
    "dataWindowNDC": (0.0, 0.0, 1.0, 1.0),
    "disableDepthOfField": False,
    "disableMotionBlur": False,
    "instantaneousShutter": False,
    "pixelAspectRatio": 1.0,
    "productName": "",
    "productType": "raster",
    "resolution": (2048, 1080),
}
_PRODUCT_TYPES = {
    "aspectRatioConformPolicy": "token",
    "dataWindowNDC": "float4",
    "disableDepthOfField": "bool",
    "disableMotionBlur": "bool",
    "instantaneousShutter": "bool",
    "pixelAspectRatio": "float",
    "productName": "token",
    "productType": "token",
    "resolution": "int2",
}
_POSE_TOLERANCE = 1e-10


@dataclass(frozen=True)
class RenderProduct:
    """Validated projection-affecting fields for one render product."""

    path: str
    camera_path: str
    resolution: tuple[int, int]
    pixel_aspect_ratio: float
    conform_policy: str


@dataclass(frozen=True)
class StageCameras:
    """Validated products indexed by their single camera target."""

    by_camera: dict[str, RenderProduct]
    resource_paths: frozenset[str]


@dataclass(frozen=True)
class CameraWriteRow:
    """Canonical USD camera values derived from one CameraRig row."""

    node: int
    camera_index: int
    camera_path: str
    projection: str
    horizontal_aperture: np.float32
    vertical_aperture: np.float32
    horizontal_offset: np.float32
    vertical_offset: np.float32
    focal_length: np.float32
    resolution: tuple[int, int]


def _static_attribute(prim, name: str, expected_type: str):
    attribute = prim.get_attribute(name)
    if attribute is None:
        raise ValueError(f"USD {prim.type_name} {prim.name!r}: missing {name!r}")
    if prim.get_attribute_timesamples(name):
        raise ValueError(
            f"USD {prim.type_name} {prim.name!r}: time-sampled {name!r} "
            "is unsupported"
        )
    if str(attribute.type_name) != expected_type:
        raise ValueError(
            f"USD {prim.type_name} {prim.name!r}: {name!r} must have type "
            f"{expected_type}, not {attribute.type_name}"
        )
    if attribute.value is None:
        raise ValueError(
            f"USD {prim.type_name} {prim.name!r}: {name!r} has no static value"
        )
    return attribute


def property_names(prim, *, text: str | None = None) -> set[str]:
    """Return Camera properties from TinyUSDZ's normalized text fallback."""

    if text is None:
        text = prim.to_string()
    return {
        match.group("name").removesuffix(".timeSamples")
        for match in _DECLARATION.finditer(text)
    }


def has_time_samples(prim, *, text: str | None = None) -> bool:
    """Report Camera value samples without the provider's Camera binding."""

    if text is None:
        text = prim.to_string()
    return _TIME_SAMPLES.search(text) is not None


def _text_declaration(
    prim,
    text: str,
    name: str,
    expected_type: str,
) -> int:
    for match in _DECLARATION.finditer(text):
        if match.group("name") != name:
            continue
        actual_type = match.group("type")
        if actual_type != expected_type:
            raise ValueError(
                f"USD Camera {prim.name!r}: {name!r} must have type "
                f"{expected_type}, not {actual_type}"
            )
        return match.end()
    raise ValueError(f"USD Camera {prim.name!r}: missing {name!r}")


def _text_value(prim, text: str, name: str, expected_type: str):
    start = _text_declaration(prim, text, name, expected_type)
    end = text.find("\n", start)
    if end < 0:
        end = len(text)
    encoded = text[start:end].strip()
    if expected_type == "token":
        try:
            value = ast.literal_eval(encoded)
        except (SyntaxError, ValueError):
            raise ValueError(
                f"USD Camera {prim.name!r}: {name!r} must be a token"
            ) from None
        if not isinstance(value, str):
            raise ValueError(
                f"USD Camera {prim.name!r}: {name!r} must be a token"
            )
        return value
    try:
        value = float(encoded)
    except ValueError:
        raise ValueError(
            f"USD Camera {prim.name!r}: {name!r} must be numeric"
        ) from None
    return float(np.float32(value)) if expected_type == "float" else value


def _text_vector(
    prim,
    text: str,
    name: str,
    expected_type: str,
    width: int,
) -> tuple[float, ...]:
    start = _text_declaration(prim, text, name, expected_type)
    end = text.find("\n", start)
    if end < 0:
        end = len(text)
    values = _vector_value(
        text[start:end].strip(),
        width,
        f"USD Camera {prim.name!r} {name}",
    )
    return tuple(float(np.float32(value)) for value in values)


def _text_array_is_empty(
    prim,
    text: str,
    name: str,
    expected_type: str,
) -> bool:
    start = _text_declaration(prim, text, name, expected_type)
    opening = text.find("[", start)
    closing = text.find("]", opening + 1)
    if opening < 0 or closing < 0:
        raise ValueError(
            f"USD Camera {prim.name!r}: {name!r} must be a static array"
        )
    return not text[opening + 1 : closing].strip()


def _scalar(
    prim,
    properties: set[str],
    name: str,
    default,
    *,
    text: str | None = None,
):
    if name not in properties:
        return (
            float(np.float32(default))
            if _CAMERA_TYPES[name] == "float"
            else default
        )
    if text is not None:
        return _text_value(prim, text, name, _CAMERA_TYPES[name])
    attribute = _static_attribute(prim, name, _CAMERA_TYPES[name])
    try:
        return attribute.value.as_scalar()
    except (TypeError, ValueError):
        raise ValueError(
            f"USD Camera {prim.name!r}: {name!r} must be scalar"
        ) from None


def _product_value(prim, properties: set[str], name: str):
    default = _PRODUCT_DEFAULTS[name]
    if name not in properties:
        return default
    attribute = _static_attribute(prim, name, _PRODUCT_TYPES[name])
    if name in {
        "aspectRatioConformPolicy",
        "disableDepthOfField",
        "disableMotionBlur",
        "instantaneousShutter",
        "pixelAspectRatio",
        "productName",
        "productType",
    }:
        try:
            return attribute.value.as_scalar()
        except (TypeError, ValueError):
            raise ValueError(
                f"USD RenderProduct {prim.name!r}: {name!r} must be scalar"
            ) from None
    try:
        return attribute.value.as_scalar()
    except (TypeError, ValueError):
        raise ValueError(
            f"USD RenderProduct {prim.name!r}: {name!r} must be a vector"
        ) from None


def _vector_value(
    value: object,
    width: int,
    context: str,
    *,
    integer: bool = False,
) -> tuple[float, ...] | tuple[int, ...]:
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            raise ValueError(f"{context}: invalid vector value") from None
    if not isinstance(value, (tuple, list)) or len(value) != width:
        raise ValueError(f"{context}: expected {width} components")
    try:
        if integer:
            if any(isinstance(item, bool) or int(item) != item for item in value):
                raise ValueError
            return tuple(int(item) for item in value)
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        kind = "integer" if integer else "numeric"
        raise ValueError(f"{context}: components must be {kind}") from None
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{context}: components must be finite")
    return result


def _prim_index(stage) -> dict[str, object]:
    result: dict[str, object] = {}

    def visit(prim, parent_path: str) -> None:
        path = f"{parent_path}/{prim.name}"
        if path in result:
            raise ValueError(f"USD: duplicate prim path {path!r}")
        result[path] = prim
        for child in prim.children():
            visit(child, path)

    for root in stage.root_prims():
        visit(root, "")
    return result


def _render_product(prim, path: str, prims: dict[str, object]) -> RenderProduct:
    if not isinstance(prim.name, str) or not _IDENTIFIER.fullmatch(prim.name):
        raise ValueError(
            f"USD: RenderProduct name {prim.name!r} is not a portable identifier"
        )
    properties = set(prim.property_names())
    unsupported = sorted(properties - RENDER_PRODUCT_PROPERTIES)
    if unsupported:
        raise ValueError(
            f"USD RenderProduct {path!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    targets = prim.get_relationship_targets("camera")
    if targets is None or len(targets) != 1:
        raise ValueError(
            f"USD RenderProduct {path!r}: camera relationship must have "
            "exactly one target"
        )
    camera_path = str(targets[0])
    target = prims.get(camera_path)
    if target is None or target.type_name != CAMERA_PRIM_TYPE:
        raise ValueError(
            f"USD RenderProduct {path!r}: camera target {camera_path!r} "
            "must name a Camera prim"
        )
    ordered = prim.get_relationship_targets("orderedVars")
    if ordered:
        raise ValueError(
            f"USD RenderProduct {path!r}: orderedVars are not represented"
        )

    resolution_value = _vector_value(
        _product_value(prim, properties, "resolution"),
        2,
        f"USD RenderProduct {path!r} resolution",
        integer=True,
    )
    width, height = (int(value) for value in resolution_value)
    if width <= 0 or height <= 0:
        raise ValueError(
            f"USD RenderProduct {path!r}: resolution must be positive"
        )

    pixel_aspect = float(_product_value(prim, properties, "pixelAspectRatio"))
    if not math.isfinite(pixel_aspect) or pixel_aspect <= 0.0:
        raise ValueError(
            f"USD RenderProduct {path!r}: pixelAspectRatio must be finite "
            "and positive"
        )
    policy = str(_product_value(prim, properties, "aspectRatioConformPolicy"))
    if policy not in CONFORM_POLICIES:
        raise ValueError(
            f"USD RenderProduct {path!r}: unsupported "
            f"aspectRatioConformPolicy {policy!r}"
        )

    data_window = _vector_value(
        _product_value(prim, properties, "dataWindowNDC"),
        4,
        f"USD RenderProduct {path!r} dataWindowNDC",
    )
    if data_window != (0.0, 0.0, 1.0, 1.0):
        raise ValueError(
            f"USD RenderProduct {path!r}: dataWindowNDC must retain its "
            "schema default"
        )
    for name in (
        "disableDepthOfField",
        "disableMotionBlur",
        "instantaneousShutter",
    ):
        if bool(_product_value(prim, properties, name)):
            raise ValueError(
                f"USD RenderProduct {path!r}: {name} must retain its "
                "schema default"
            )
    if str(_product_value(prim, properties, "productType")) != "raster":
        raise ValueError(
            f"USD RenderProduct {path!r}: productType must be 'raster'"
        )
    if str(_product_value(prim, properties, "productName")):
        raise ValueError(
            f"USD RenderProduct {path!r}: productName is not represented"
        )
    return RenderProduct(
        path=path,
        camera_path=camera_path,
        resolution=(width, height),
        pixel_aspect_ratio=pixel_aspect,
        conform_policy=policy,
    )


def collect_stage_products(stage) -> StageCameras:
    """Validate RenderProducts and require one unambiguous product per target."""

    prims = _prim_index(stage)
    products = [
        _render_product(prim, path, prims)
        for path, prim in prims.items()
        if prim.type_name == RENDER_PRODUCT_PRIM_TYPE
    ]
    by_camera: dict[str, RenderProduct] = {}
    for product in products:
        previous = by_camera.get(product.camera_path)
        if previous is not None:
            detail = (
                "with conflicting resolutions"
                if previous.resolution != product.resolution
                else ""
            )
            raise ValueError(
                f"USD Camera {product.camera_path!r}: multiple RenderProducts "
                f"are ambiguous {detail}".rstrip()
            )
        by_camera[product.camera_path] = product
    return StageCameras(
        by_camera=by_camera,
        resource_paths=frozenset(product.path for product in products),
    )


def stage_resource_paths(stage) -> frozenset[str]:
    """Identify RenderProducts excluded from SceneGraph nodes."""

    return frozenset(
        path
        for path, prim in _prim_index(stage).items()
        if prim.type_name == RENDER_PRODUCT_PRIM_TYPE
    )


def _camera_values(
    prim,
    shell_properties: frozenset[str],
    *,
    text: str | None = None,
) -> dict[str, object]:
    if text is None:
        text = prim.to_string()
    properties = property_names(prim, text=text)
    unsupported = sorted(properties - CAMERA_PROPERTIES - shell_properties)
    if unsupported:
        raise ValueError(
            f"USD Camera {prim.name!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    values = {
        name: _scalar(prim, properties, name, default, text=text)
        for name, default in _CAMERA_DEFAULTS.items()
        if name != "clippingRange"
    }
    if "clippingRange" in properties:
        clipping = _text_vector(
            prim,
            text,
            "clippingRange",
            "float2",
            2,
        )
    else:
        clipping = tuple(
            float(np.float32(value))
            for value in _CAMERA_DEFAULTS["clippingRange"]
        )
    expected_clipping = tuple(
        float(np.float32(value))
        for value in _CAMERA_DEFAULTS["clippingRange"]
    )
    if clipping != expected_clipping:
        raise ValueError(
            f"USD Camera {prim.name!r}: clippingRange must retain its "
            "schema default"
        )
    if "clippingPlanes" in properties and not _text_array_is_empty(
        prim, text, "clippingPlanes", "float4[]"
    ):
        raise ValueError(
            f"USD Camera {prim.name!r}: clippingPlanes are not represented"
        )
    for name in (
        "exposure",
        "exposure:fStop",
        "exposure:iso",
        "exposure:responsivity",
        "exposure:time",
        "fStop",
        "focusDistance",
        "shutter:close",
        "shutter:open",
    ):
        value = float(values[name])
        expected = (
            float(np.float32(_CAMERA_DEFAULTS[name]))
            if _CAMERA_TYPES[name] == "float"
            else _CAMERA_DEFAULTS[name]
        )
        if not math.isfinite(value) or value != expected:
            raise ValueError(
                f"USD Camera {prim.name!r}: {name} must retain its "
                "schema default"
            )
    if str(values["stereoRole"]) != "mono":
        raise ValueError(
            f"USD Camera {prim.name!r}: stereoRole must retain 'mono'"
        )
    projection = str(values["projection"])
    if projection not in PROJECTIONS:
        raise ValueError(
            f"USD Camera {prim.name!r}: unsupported projection {projection!r}"
        )
    for name in (
        "horizontalAperture",
        "verticalAperture",
        "focalLength",
    ):
        value = float(values[name])
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"USD Camera {prim.name!r}: {name} must be finite and positive"
            )
    for name in ("horizontalApertureOffset", "verticalApertureOffset"):
        if not math.isfinite(float(values[name])):
            raise ValueError(f"USD Camera {prim.name!r}: {name} must be finite")
    return values


def _conformed_apertures(
    horizontal: float,
    vertical: float,
    product: RenderProduct,
) -> tuple[float, float]:
    width, height = product.resolution
    original_aspect = horizontal / vertical
    if product.conform_policy == "adjustPixelAspectRatio":
        return horizontal, vertical
    target_aspect = width * product.pixel_aspect_ratio / height
    if product.conform_policy == "adjustApertureWidth":
        return vertical * target_aspect, vertical
    if product.conform_policy == "adjustApertureHeight":
        return horizontal, horizontal / target_aspect
    if product.conform_policy == "expandAperture":
        if original_aspect > target_aspect:
            return horizontal, horizontal / target_aspect
        return vertical * target_aspect, vertical
    if original_aspect > target_aspect:
        return vertical * target_aspect, vertical
    return horizontal, horizontal / target_aspect


def _projection_row(
    values: dict[str, object], product: RenderProduct
) -> tuple[str, np.ndarray, np.ndarray]:
    width, height = product.resolution
    horizontal, vertical = _conformed_apertures(
        float(values["horizontalAperture"]),
        float(values["verticalAperture"]),
        product,
    )
    horizontal_offset = float(values["horizontalApertureOffset"])
    vertical_offset = float(values["verticalApertureOffset"])
    projection = str(values["projection"])
    if projection == "perspective":
        focal = float(values["focalLength"])
        x_scale = focal * width / horizontal
        y_scale = focal * height / vertical
        model = "pinhole"
    else:
        # Apertures are tenths of a scene unit. Orthographic parameters are
        # pixels per scene unit so the CameraRig scale tag remains meaningful.
        x_scale = width / (0.1 * horizontal)
        y_scale = height / (0.1 * vertical)
        model = "orthographic"
    cx = width * (0.5 - horizontal_offset / horizontal)
    cy = height * (0.5 + vertical_offset / vertical)
    intrinsics = np.asarray((x_scale, y_scale, cx, cy), np.float64)
    if not np.isfinite(intrinsics).all() or np.any(intrinsics[:2] <= 0.0):
        raise ValueError("USD Camera: evaluated projection is not finite and positive")
    matrix = np.asarray(
        ((x_scale, 0.0, cx), (0.0, y_scale, cy), (0.0, 0.0, 1.0)),
        np.float64,
    )
    return model, intrinsics, matrix


def _matrix_to_pose(matrix: np.ndarray, path: str) -> tuple[np.ndarray, np.ndarray]:
    value = np.asarray(matrix, dtype=np.float64)
    if value.shape != (4, 4) or not np.isfinite(value).all():
        raise ValueError(f"USD Camera {path!r}: transform must be finite (4, 4)")
    if not np.allclose(
        value[3], (0.0, 0.0, 0.0, 1.0), rtol=0.0, atol=_POSE_TOLERANCE
    ):
        raise ValueError(f"USD Camera {path!r}: transform must be affine")
    rotation = value[:3, :3]
    if not np.allclose(
        rotation.T @ rotation,
        np.eye(3),
        rtol=0.0,
        atol=_POSE_TOLERANCE,
    ) or not math.isclose(
        float(np.linalg.det(rotation)), 1.0, rel_tol=0.0, abs_tol=_POSE_TOLERANCE
    ):
        raise ValueError(
            f"USD Camera {path!r}: transform must contain a proper rigid rotation"
        )
    trace = float(np.trace(rotation))
    if trace > 0.0:
        root = math.sqrt(trace + 1.0) * 2.0
        quaternion = np.asarray(
            (
                0.25 * root,
                (rotation[2, 1] - rotation[1, 2]) / root,
                (rotation[0, 2] - rotation[2, 0]) / root,
                (rotation[1, 0] - rotation[0, 1]) / root,
            ),
            np.float64,
        )
    else:
        axis = int(np.argmax(np.diag(rotation)))
        if axis == 0:
            root = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
            quaternion = np.asarray(
                (
                    (rotation[2, 1] - rotation[1, 2]) / root,
                    0.25 * root,
                    (rotation[0, 1] + rotation[1, 0]) / root,
                    (rotation[0, 2] + rotation[2, 0]) / root,
                ),
                np.float64,
            )
        elif axis == 1:
            root = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
            quaternion = np.asarray(
                (
                    (rotation[0, 2] - rotation[2, 0]) / root,
                    (rotation[0, 1] + rotation[1, 0]) / root,
                    0.25 * root,
                    (rotation[1, 2] + rotation[2, 1]) / root,
                ),
                np.float64,
            )
        else:
            root = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
            quaternion = np.asarray(
                (
                    (rotation[1, 0] - rotation[0, 1]) / root,
                    (rotation[0, 2] + rotation[2, 0]) / root,
                    (rotation[1, 2] + rotation[2, 1]) / root,
                    0.25 * root,
                ),
                np.float64,
            )
    quaternion /= np.linalg.norm(quaternion)
    if quaternion[0] < 0.0 or (
        quaternion[0] == 0.0
        and next((item for item in quaternion[1:] if item != 0.0), 1.0) < 0.0
    ):
        quaternion *= -1.0
    return quaternion, np.array(value[:3, 3], copy=True)


def camera_row_from_prim(
    prim,
    *,
    path: str,
    product: RenderProduct | None,
    transform: np.ndarray,
    shell_properties: frozenset[str] = frozenset(),
    text: str | None = None,
) -> dict[str, object]:
    """Validate and map one Camera prim to an owning row description."""

    if product is None:
        raise ValueError(
            f"USD Camera {path!r}: exactly one associated RenderProduct "
            "is required for pixel resolution"
        )
    values = _camera_values(prim, shell_properties, text=text)
    model, intrinsics, matrix = _projection_row(values, product)
    quaternion, translation = _matrix_to_pose(transform, path)
    return {
        "name": path,
        "resolution": product.resolution,
        "projection_model": model,
        "intrinsics": intrinsics,
        "camera_matrix": matrix,
        "quaternion": quaternion,
        "translation": translation,
    }


def camera_rig_from_rows(rows: list[dict[str, object]], *, scale_to_meters: float):
    """Build one owning CameraRig from traversal-ordered camera rows."""

    if not rows:
        return None
    count = len(rows)
    intrinsics = np.asarray(
        [row["intrinsics"] for row in rows], np.float64
    ).reshape(-1)
    return _core.camera_rig(
        np.arange(count, dtype=np.uint32),
        np.asarray([row["resolution"] for row in rows], np.uint64),
        [str(row["projection_model"]) for row in rows],
        np.arange(0, 4 * count + 1, 4, dtype=np.uint64),
        intrinsics,
        ["none"] * count,
        np.zeros(count + 1, np.uint64),
        np.empty(0, np.float64),
        np.asarray([row["quaternion"] for row in rows], np.float64),
        np.asarray([row["translation"] for row in rows], np.float64),
        has_extrinsics=np.ones(count, np.uint8),
        names=[str(row["name"]) for row in rows],
        camera_matrices=np.asarray(
            [row["camera_matrix"] for row in rows], np.float64
        ),
        has_camera_matrix=np.ones(count, np.uint8),
        quaternion_order="wxyz",
        quaternion_sign="canonical_positive_w",
        transform_convention="camera_to_reference",
        axis_frame="opengl",
        reference_frame="unknown",
        scale_to_meters=scale_to_meters,
    )


def inspect_camera_prim(
    prim,
    *,
    path: str,
    product: RenderProduct | None,
    shell_properties: frozenset[str] = frozenset(),
    text: str | None = None,
) -> tuple[str, tuple[int, int]]:
    """Validate camera optics without constructing a CameraRig."""

    if product is None:
        raise ValueError(
            f"USD Camera {path!r}: exactly one associated RenderProduct "
            "is required for pixel resolution"
        )
    values = _camera_values(prim, shell_properties, text=text)
    model, _, _ = _projection_row(values, product)
    return model, product.resolution


def _ragged_row(offsets: np.ndarray, values: np.ndarray, index: int) -> np.ndarray:
    return values[int(offsets[index]) : int(offsets[index + 1])]


def _quaternion_to_matrix(quaternion: np.ndarray) -> np.ndarray:
    w, x, y, z = (float(value) for value in quaternion)
    return np.asarray(
        (
            (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
        ),
        np.float64,
    )


def _canonical_optics(
    projection: str,
    intrinsics: np.ndarray,
    resolution: tuple[int, int],
) -> tuple[np.float32, np.float32, np.float32, np.float32, np.float32]:
    x_scale, y_scale, cx, cy = (float(value) for value in intrinsics)
    width, height = resolution
    focal = np.float32(50.0)
    if projection == "pinhole":
        horizontal = np.float32(float(focal) * width / x_scale)
        vertical = np.float32(float(focal) * height / y_scale)
    else:
        horizontal = np.float32(10.0 * width / x_scale)
        vertical = np.float32(10.0 * height / y_scale)
    horizontal_offset = np.float32(
        float(horizontal) * (0.5 - cx / width)
    )
    vertical_offset = np.float32(float(vertical) * (cy / height - 0.5))
    return (
        horizontal,
        vertical,
        horizontal_offset,
        vertical_offset,
        focal,
    )


def validate_writable_camera_rig(
    scene,
    *,
    payload_kinds: tuple[str, ...],
    payload_indices: np.ndarray,
    transforms: np.ndarray,
    node_paths: tuple[str, ...],
) -> tuple[CameraWriteRow, ...]:
    """Guard the exact bounded CameraRig-to-USD projection."""

    camera_nodes = [
        node for node, kind in enumerate(payload_kinds) if kind == "camera"
    ]
    if not camera_nodes:
        if scene.has_cameras:
            raise ValueError(
                "USD: an attached CameraRig must have camera payload nodes"
            )
        return ()
    if not scene.has_cameras:
        raise ValueError("USD: camera payload nodes require an attached CameraRig")
    rig = scene.cameras
    if (
        rig.quaternion_order != "wxyz"
        or rig.quaternion_sign != "canonical_positive_w"
        or rig.transform_convention != "camera_to_reference"
        or rig.axis_frame != "opengl"
        or rig.reference_frame != "unknown"
        or rig.scale_to_meters != scene.meters_per_unit
    ):
        raise ValueError(
            "USD: CameraRig requires WXYZ canonical camera_to_reference / "
            "OpenGL / unknown-reference conventions and the scene unit scale"
        )
    intrinsic_offsets = np.asarray(rig.intrinsic_offsets)
    distortion_offsets = np.asarray(rig.distortion_offsets)
    all_intrinsics = np.asarray(rig.intrinsics)
    all_distortion = np.asarray(rig.distortion_coefficients)
    matrices = np.asarray(rig.camera_matrices)
    quaternions = np.asarray(rig.quaternions)
    translations = np.asarray(rig.translations)
    used: set[int] = set()
    rows: list[CameraWriteRow] = []
    for node in camera_nodes:
        index = int(payload_indices[node])
        if index in used:
            raise ValueError(
                f"USD: camera payload {index} is referenced by multiple nodes"
            )
        used.add(index)
        if int(rig.camera_ids[index]) != index or rig.names[index] != node_paths[node]:
            raise ValueError(
                "USD: camera ids must be traversal-order indices and names "
                "must equal their absolute prim paths"
            )
        projection = rig.projection_models[index]
        if projection not in {"pinhole", "orthographic"}:
            raise ValueError(
                f"USD: camera {index} projection model {projection!r} is unsupported"
            )
        intrinsics = _ragged_row(intrinsic_offsets, all_intrinsics, index)
        distortion = _ragged_row(distortion_offsets, all_distortion, index)
        if intrinsics.shape != (4,) or not np.isfinite(intrinsics).all():
            raise ValueError(
                f"USD: camera {index} requires finite fx/fy/cx/cy-style intrinsics"
            )
        if np.any(intrinsics[:2] <= 0.0):
            raise ValueError(
                f"USD: camera {index} projection scales must be positive"
            )
        if rig.distortion_models[index] != "none" or distortion.size:
            raise ValueError(
                f"USD: camera {index} distortion is not representable"
            )
        expected_matrix = np.asarray(
            (
                (intrinsics[0], 0.0, intrinsics[2]),
                (0.0, intrinsics[1], intrinsics[3]),
                (0.0, 0.0, 1.0),
            ),
            np.float64,
        )
        if not rig.has_camera_matrix[index] or not np.array_equal(
            matrices[index], expected_matrix
        ):
            raise ValueError(
                f"USD: camera {index} requires an exact K matrix matching intrinsics"
            )
        if (
            rig.has_rectification[index]
            or rig.has_projection_matrix[index]
            or rig.has_operational[index]
            or rig.has_time_offset[index]
            or rig.topics[index]
        ):
            raise ValueError(
                f"USD: camera {index} has fields outside the bounded USD profile"
            )
        quaternion = quaternions[index]
        norm = float(np.linalg.norm(quaternion))
        if (
            not rig.has_extrinsics[index]
            or not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=_POSE_TOLERANCE)
            or quaternion[0] < 0.0
        ):
            raise ValueError(
                f"USD: camera {index} requires a canonical unit camera-to-parent pose"
            )
        pose_matrix = np.eye(4, dtype=np.float64)
        pose_matrix[:3, :3] = _quaternion_to_matrix(quaternion / norm)
        pose_matrix[:3, 3] = translations[index]
        _matrix_to_pose(transforms[node], node_paths[node])
        if not np.allclose(
            pose_matrix,
            transforms[node],
            rtol=0.0,
            atol=_POSE_TOLERANCE,
        ):
            raise ValueError(
                f"USD: camera {index} pose must match its node local transform"
            )
        resolution = tuple(int(value) for value in rig.resolutions[index])
        (
            horizontal,
            vertical,
            horizontal_offset,
            vertical_offset,
            focal,
        ) = _canonical_optics(projection, intrinsics, resolution)
        if not np.isfinite(
            np.asarray(
                (
                    horizontal,
                    vertical,
                    horizontal_offset,
                    vertical_offset,
                    focal,
                )
            )
        ).all() or min(horizontal, vertical) <= 0.0:
            raise ValueError(
                f"USD: camera {index} optics exceed the schema float domain"
            )
        rows.append(
            CameraWriteRow(
                node=node,
                camera_index=index,
                camera_path=node_paths[node],
                projection=(
                    "perspective" if projection == "pinhole" else "orthographic"
                ),
                horizontal_aperture=horizontal,
                vertical_aperture=vertical,
                horizontal_offset=horizontal_offset,
                vertical_offset=vertical_offset,
                focal_length=focal,
                resolution=resolution,
            )
        )
    if used != set(range(rig.num_cameras)):
        raise ValueError("USD: every CameraRig row must be referenced exactly once")
    return tuple(rows)


def choose_product_names(scene, count: int) -> tuple[str, ...]:
    """Choose deterministic collision-free root RenderProduct names."""

    root_names = {
        scene.node_names[index]
        for index, parent in enumerate(scene.node_parents)
        if int(parent) == -1
    }
    names: list[str] = []
    for index in range(count):
        base = f"SceneIOCameraProduct_{index}"
        name = base
        suffix = 1
        while name in root_names:
            name = f"{base}_{suffix}"
            suffix += 1
        root_names.add(name)
        names.append(name)
    return tuple(names)


def _f32(value: object) -> str:
    return format(float(np.float32(value)), ".9g")


def write_camera_attributes(
    stream: TextIO,
    row: CameraWriteRow,
    *,
    inner: str,
) -> None:
    """Write canonical physical values for one projection-equivalent camera."""

    stream.write(
        f'{inner}token projection = "{row.projection}"\n'
        f"{inner}float horizontalAperture = {_f32(row.horizontal_aperture)}\n"
        f"{inner}float verticalAperture = {_f32(row.vertical_aperture)}\n"
        f"{inner}float horizontalApertureOffset = {_f32(row.horizontal_offset)}\n"
        f"{inner}float verticalApertureOffset = {_f32(row.vertical_offset)}\n"
        f"{inner}float focalLength = {_f32(row.focal_length)}\n"
    )


def write_render_products(
    stream: TextIO,
    rows: tuple[CameraWriteRow, ...],
    *,
    names: tuple[str, ...],
) -> None:
    """Write one unambiguous raster RenderProduct per camera."""

    for row, name in zip(rows, names, strict=True):
        width, height = row.resolution
        stream.write(
            f'\ndef RenderProduct "{name}"\n'
            "{\n"
            f"    rel camera = <{row.camera_path}>\n"
            f"    uniform int2 resolution = ({width}, {height})\n"
            "    uniform token aspectRatioConformPolicy = "
            '"adjustPixelAspectRatio"\n'
        )
        stream.write("}\n")


__all__ = [
    "CAMERA_PRIM_TYPE",
    "CAMERA_PROPERTIES",
    "CONFORM_POLICIES",
    "PROJECTIONS",
    "RENDER_PRODUCT_PRIM_TYPE",
    "RENDER_PRODUCT_PROPERTIES",
    "CameraWriteRow",
    "RenderProduct",
    "StageCameras",
    "camera_rig_from_rows",
    "camera_row_from_prim",
    "choose_product_names",
    "collect_stage_products",
    "inspect_camera_prim",
    "stage_resource_paths",
    "validate_writable_camera_rig",
    "write_camera_attributes",
    "write_render_products",
]
