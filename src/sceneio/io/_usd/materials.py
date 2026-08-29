"""Bounded UsdPreviewSurface and material-binding mapping."""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np

from sceneio import _core
from sceneio.io._usd import package

MATERIAL_PRIM_TYPES = frozenset({"Material", "Shader", "NodeGraph"})
PREVIEW_SURFACE_SHADER_ID = "UsdPreviewSurface"
UV_TEXTURE_SHADER_ID = "UsdUVTexture"
PRIMVAR_READER_SHADER_ID = "UsdPrimvarReader_float2"
SUPPORTED_TEXTURE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".exr"})
PREVIEW_SURFACE_INPUTS = frozenset(
    {
        "diffuseColor",
        "emissiveColor",
        "useSpecularWorkflow",
        "specularColor",
        "metallic",
        "roughness",
        "clearcoat",
        "clearcoatRoughness",
        "opacity",
        "opacityMode",
        "opacityThreshold",
        "ior",
        "normal",
        "displacement",
        "occlusion",
    }
)
MESH_MATERIAL_PROPERTIES = frozenset(
    {
        "material:binding",
        "subsetFamily:materialBind:familyType",
    }
)

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SUBSET_TOKEN = {
    name: re.compile(
        rf'^ {{4}}(?:uniform\s+)?token\s+{re.escape(name)}\s*=\s*'
        r'"([^"]+)"\s*$',
        re.MULTILINE,
    )
    for name in ("elementType", "familyName")
}
_SUBSET_INDICES = re.compile(
    r"^ {4}int\[\]\s+indices\s*=\s*\[([^\]]*)\]",
    re.MULTILINE | re.DOTALL,
)
_FAMILY_TYPE = re.compile(
    r'^ {4}(?:uniform\s+)?token\s+'
    r'subsetFamily:materialBind:familyType\s*=\s*'
    r'"(partition|nonOverlapping|unrestricted)"\s*$',
    re.MULTILINE,
)
_VECTOR_TYPES = {
    "color3f": 3,
    "normal3f": 3,
    "float4": 4,
}
_INPUT_TYPES = {
    "diffuseColor": "color3f",
    "emissiveColor": "color3f",
    "useSpecularWorkflow": "int",
    "specularColor": "color3f",
    "metallic": "float",
    "roughness": "float",
    "clearcoat": "float",
    "clearcoatRoughness": "float",
    "opacity": "float",
    "opacityMode": "token",
    "opacityThreshold": "float",
    "ior": "float",
    "normal": "normal3f",
    "displacement": "float",
    "occlusion": "float",
}
_DEFAULTS: dict[str, object] = {
    "diffuseColor": (0.18, 0.18, 0.18),
    "emissiveColor": (0.0, 0.0, 0.0),
    "useSpecularWorkflow": 0,
    "specularColor": (0.0, 0.0, 0.0),
    "metallic": 0.0,
    "roughness": 0.5,
    "clearcoat": 0.0,
    "clearcoatRoughness": 0.01,
    "opacity": 1.0,
    "opacityMode": "transparent",
    "opacityThreshold": 0.0,
    "ior": 1.5,
    "normal": (0.0, 0.0, 1.0),
    "displacement": 0.0,
    "occlusion": 1.0,
}
_REPRESENTED_INPUTS = frozenset(
    {
        "diffuseColor",
        "emissiveColor",
        "metallic",
        "roughness",
        "opacity",
        "opacityThreshold",
        "normal",
    }
)
_PREVIEW_INPUT_ORDER = (
    "diffuseColor",
    "emissiveColor",
    "useSpecularWorkflow",
    "specularColor",
    "metallic",
    "roughness",
    "clearcoat",
    "clearcoatRoughness",
    "opacity",
    "opacityMode",
    "opacityThreshold",
    "ior",
    "normal",
    "displacement",
    "occlusion",
)
_TEXTURE_INPUTS = {
    "diffuseColor": ("base_color", "rgb", "sRGB"),
    "emissiveColor": ("emissive", "rgb", "sRGB"),
    "metallic": ("metallic", "r", "raw"),
    "roughness": ("roughness", "r", "raw"),
    "opacity": ("alpha", "a", "raw"),
    "normal": ("normal", "rgb", "raw"),
}
_SEMANTIC_INPUTS = {
    semantic: name
    for name, (semantic, _, _) in _TEXTURE_INPUTS.items()
}
_TEXTURE_SEMANTIC_ORDER = tuple(
    _TEXTURE_INPUTS[name][0]
    for name in _PREVIEW_INPUT_ORDER
    if name in _TEXTURE_INPUTS
)
_WRAP_FROM_USD = {
    "repeat": "repeat",
    "clamp": "clamp",
    "mirror": "mirrored_repeat",
}
_WRAP_TO_USD = {value: key for key, value in _WRAP_FROM_USD.items()}
_WRAP_CODE_NAMES = {0: "repeat", 1: "clamp", 2: "mirrored_repeat"}


@dataclass(frozen=True)
class StageMaterials:
    """Parsed material resources and their source-backed texture table."""

    record: object | None
    material_indices: dict[str, int]
    resource_paths: frozenset[str]
    external_asset_uris: tuple[str, ...]
    external_asset_sources: tuple[str, ...]


@dataclass(frozen=True)
class _Texture:
    material: int
    semantic: str
    uri: str
    wrap_s: str
    wrap_t: str
    resource_paths: tuple[str, str]


def _prim_index(stage) -> tuple[dict[str, object], dict[str, str | None]]:
    prims: dict[str, object] = {}
    parents: dict[str, str | None] = {}

    def visit(prim, parent_path: str | None) -> None:
        path = f"{parent_path or ''}/{prim.name}"
        if path in prims:
            raise ValueError(f"USD: duplicate prim path {path!r}")
        prims[path] = prim
        parents[path] = parent_path
        for child in prim.children():
            visit(child, path)

    for root in stage.root_prims():
        visit(root, None)
    return prims, parents


def _api_schemas(prim) -> frozenset[str]:
    return frozenset(str(item) for item in prim.api_schemas())


def _connections(prim, name: str) -> tuple[str, ...]:
    values = prim.get_attribute_connections(name)
    return () if values is None else tuple(str(value) for value in values)


def _connected_fallback_is_authored(prim, name: str) -> bool:
    return re.search(
        rf"^\s*(?:uniform\s+)?\S+\s+{re.escape(name)}\s*=",
        prim.to_string(),
        re.MULTILINE,
    ) is not None


def _attribute(
    prim,
    name: str,
    expected_type: str | tuple[str, ...],
    *,
    required: bool = False,
):
    attribute = (
        prim.get_attribute(name)
        if name in set(prim.property_names())
        else None
    )
    if attribute is None:
        if required:
            raise ValueError(
                f"USD shader {prim.name!r}: missing {name!r}"
            )
        return None
    expected = (
        (expected_type,)
        if isinstance(expected_type, str)
        else expected_type
    )
    if str(attribute.type_name) not in expected:
        raise ValueError(
            f"USD shader {prim.name!r}: {name!r} must have type "
            f"{' or '.join(expected)}, not {attribute.type_name}"
        )
    if prim.get_attribute_timesamples(name):
        raise ValueError(
            f"USD shader {prim.name!r}: time-sampled {name!r} is unsupported"
        )
    return attribute


def _vector_value(value: object, width: int, context: str) -> tuple[float, ...]:
    if not isinstance(value, str):
        raise ValueError(f"{context}: expected a vector value")
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        raise ValueError(f"{context}: invalid vector value") from None
    if not isinstance(parsed, tuple) or len(parsed) != width:
        raise ValueError(f"{context}: expected {width} components")
    try:
        result = tuple(float(item) for item in parsed)
    except (TypeError, ValueError):
        raise ValueError(f"{context}: vector components must be numeric") from None
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{context}: vector components must be finite")
    return result


def _direct_value(
    prim,
    input_name: str,
    *,
    default: object,
) -> object:
    property_name = f"inputs:{input_name}"
    expected_type = _INPUT_TYPES[input_name]
    attribute = _attribute(prim, property_name, expected_type)
    if attribute is None:
        return default
    if _connections(prim, property_name):
        raise ValueError(
            f"USD shader {prim.name!r}: connected {property_name!r} "
            "cannot also be read as a constant"
        )
    if attribute.value is None:
        raise ValueError(
            f"USD shader {prim.name!r}: {property_name!r} has no value"
        )
    value = attribute.value.as_scalar()
    if expected_type in _VECTOR_TYPES:
        return _vector_value(
            value,
            _VECTOR_TYPES[expected_type],
            f"USD shader {prim.name!r} {property_name!r}",
        )
    if expected_type == "float":
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"USD shader {prim.name!r}: {property_name!r} must be numeric"
            ) from None
        if not math.isfinite(result):
            raise ValueError(
                f"USD shader {prim.name!r}: {property_name!r} must be finite"
            )
        return result
    if expected_type == "int":
        if not isinstance(value, int):
            raise ValueError(
                f"USD shader {prim.name!r}: {property_name!r} must be int"
            )
        return value
    if expected_type == "token":
        if not isinstance(value, str):
            raise ValueError(
                f"USD shader {prim.name!r}: {property_name!r} must be token"
            )
        return value
    raise AssertionError(expected_type)


def _shader_id(prim) -> str:
    attribute = _attribute(prim, "info:id", "token", required=True)
    if attribute.value is None:
        raise ValueError(f"USD shader {prim.name!r}: info:id has no value")
    value = attribute.value.as_scalar()
    if not isinstance(value, str):
        raise ValueError(f"USD shader {prim.name!r}: info:id must be token")
    return value


def _asset_value(prim, name: str) -> str:
    attribute = _attribute(prim, name, "asset", required=True)
    if _connections(prim, name) or attribute.value is None:
        raise ValueError(
            f"USD shader {prim.name!r}: {name!r} must be a direct asset"
        )
    encoded = attribute.value.to_string()
    if (
        not isinstance(encoded, str)
        or len(encoded) < 2
        or encoded[0] != "@"
        or encoded[-1] != "@"
        or "@" in encoded[1:-1]
    ):
        raise ValueError(
            f"USD shader {prim.name!r}: {name!r} has an invalid asset path"
        )
    return package.normalize_asset_uri(
        encoded[1:-1],
        context=f"USD shader {prim.name!r} texture",
    )


def _target_prim(
    target: str,
    *,
    output: str,
    prims: dict[str, object],
    context: str,
):
    suffix = f".outputs:{output}"
    if not target.startswith("/") or not target.endswith(suffix):
        raise ValueError(
            f"{context}: connection must target an absolute {suffix!r} output"
        )
    path = target[: -len(suffix)]
    try:
        prim = prims[path]
    except KeyError:
        raise ValueError(f"{context}: connection target {path!r} is missing") from None
    return path, prim


def _validate_shader_properties(
    prim,
    allowed: frozenset[str],
    *,
    context: str,
) -> None:
    properties = set(prim.property_names())
    unsupported = sorted(properties - allowed)
    if unsupported:
        raise ValueError(
            f"{context}: unsupported properties: " + ", ".join(unsupported)
        )
    for name in properties:
        if prim.get_attribute_timesamples(name):
            raise ValueError(f"{context}: time-sampled {name!r} is unsupported")


def _texture_from_connection(
    preview,
    input_name: str,
    *,
    material_index: int,
    material_path: str,
    prims: dict[str, object],
) -> _Texture | None:
    property_name = f"inputs:{input_name}"
    connections = _connections(preview, property_name)
    if not connections:
        return None
    if len(connections) != 1:
        raise ValueError(
            f"USD material {material_path!r}: {property_name!r} must have "
            "exactly one connection"
        )
    _attribute(
        preview,
        property_name,
        _INPUT_TYPES[input_name],
        required=True,
    )
    if _connected_fallback_is_authored(preview, property_name):
        raise ValueError(
            f"USD material {material_path!r}: connected {property_name!r} "
            "may not also author a fallback value"
        )
    semantic, output, source_color_space = _TEXTURE_INPUTS[input_name]
    texture_path, texture = _target_prim(
        connections[0],
        output=output,
        prims=prims,
        context=f"USD material {material_path!r} {property_name!r}",
    )
    if texture.type_name != "Shader" or _shader_id(texture) != UV_TEXTURE_SHADER_ID:
        raise ValueError(
            f"USD material {material_path!r}: {property_name!r} must connect "
            "directly to UsdUVTexture"
        )
    if not texture_path.startswith(material_path + "/"):
        raise ValueError(
            f"USD material {material_path!r}: texture shader must be a descendant"
        )
    allowed = frozenset(
        {
            "info:id",
            "inputs:file",
            "inputs:st",
            "inputs:wrapS",
            "inputs:wrapT",
            "inputs:fallback",
            "inputs:scale",
            "inputs:bias",
            "inputs:sourceColorSpace",
            "outputs:r",
            "outputs:g",
            "outputs:b",
            "outputs:a",
            "outputs:rgb",
        }
    )
    _validate_shader_properties(
        texture,
        allowed,
        context=f"USD texture shader {texture_path!r}",
    )
    for output_name in ("r", "g", "b", "a", "rgb"):
        output_attribute = _attribute(
            texture,
            f"outputs:{output_name}",
            "float3" if output_name == "rgb" else "float",
            required=output_name == output,
        )
        if output_attribute is not None and output_attribute.value is not None:
            raise ValueError(
                f"USD texture shader {texture_path!r}: output may not "
                "author a value"
            )

    st_connections = _connections(texture, "inputs:st")
    _attribute(
        texture,
        "inputs:st",
        ("float2", "texCoord2f"),
        required=True,
    )
    if _connected_fallback_is_authored(texture, "inputs:st"):
        raise ValueError(
            f"USD texture shader {texture_path!r}: connected inputs:st "
            "may not also author a fallback value"
        )
    if (
        len(st_connections) != 1
    ):
        raise ValueError(
            f"USD texture shader {texture_path!r}: inputs:st must have one "
            "primvar-reader connection"
        )
    reader_path, reader = _target_prim(
        st_connections[0],
        output="result",
        prims=prims,
        context=f"USD texture shader {texture_path!r} inputs:st",
    )
    if (
        reader.type_name != "Shader"
        or _shader_id(reader) != PRIMVAR_READER_SHADER_ID
        or not reader_path.startswith(material_path + "/")
    ):
        raise ValueError(
            f"USD texture shader {texture_path!r}: inputs:st must connect "
            "to a descendant UsdPrimvarReader_float2"
        )
    _validate_shader_properties(
        reader,
        frozenset({"info:id", "inputs:varname", "outputs:result"}),
        context=f"USD primvar reader {reader_path!r}",
    )
    varname = _attribute(
        reader,
        "inputs:varname",
        "string",
        required=True,
    )
    if (
        varname.value is None
        or varname.value.as_scalar() != "st"
        or _connections(reader, "inputs:varname")
    ):
        raise ValueError(
            f"USD primvar reader {reader_path!r}: inputs:varname must be 'st'"
        )
    result_attribute = _attribute(
        reader,
        "outputs:result",
        ("float2", "texCoord2f"),
        required=True,
    )
    if result_attribute.value is not None:
        raise ValueError(
            f"USD primvar reader {reader_path!r}: output may not author a value"
        )

    wrap_values = {}
    for axis in ("S", "T"):
        name = f"inputs:wrap{axis}"
        attribute = _attribute(texture, name, "token", required=True)
        if attribute.value is None or _connections(texture, name):
            raise ValueError(
                f"USD texture shader {texture_path!r}: {name!r} "
                "must be a direct token"
            )
        token = attribute.value.as_scalar()
        try:
            wrap_values[axis] = _WRAP_FROM_USD[token]
        except KeyError:
            raise ValueError(
                f"USD texture shader {texture_path!r}: {name!r} must be "
                "repeat, clamp, or mirror"
            ) from None

    color_space = _attribute(
        texture,
        "inputs:sourceColorSpace",
        "token",
        required=True,
    )
    if (
        color_space.value is None
        or _connections(texture, "inputs:sourceColorSpace")
        or (
            color_space.value.as_scalar() != source_color_space
            and not (
                semantic == "alpha"
                and color_space.value.as_scalar() == "sRGB"
            )
        )
    ):
        raise ValueError(
            f"USD texture shader {texture_path!r}: sourceColorSpace must be "
            f"{source_color_space!r} for {semantic}"
        )

    identity = (1.0, 1.0, 1.0, 1.0)
    zero = (0.0, 0.0, 0.0, 0.0)
    expected_scale = (2.0, 2.0, 2.0, 1.0) if semantic == "normal" else identity
    expected_bias = (
        (-1.0, -1.0, -1.0, 0.0) if semantic == "normal" else zero
    )
    for name, default, expected in (
        ("fallback", (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0, 1.0)),
        ("scale", identity, expected_scale),
        ("bias", zero, expected_bias),
    ):
        attribute = _attribute(texture, f"inputs:{name}", "float4")
        value = default
        if attribute is not None:
            if attribute.value is None or _connections(texture, f"inputs:{name}"):
                raise ValueError(
                    f"USD texture shader {texture_path!r}: inputs:{name} "
                    "must be a direct float4"
                )
            value = _vector_value(
                attribute.value.as_scalar(),
                4,
                f"USD texture shader {texture_path!r} inputs:{name}",
            )
        if value != expected:
            raise ValueError(
                f"USD texture shader {texture_path!r}: inputs:{name} "
                "is outside the bounded material mapping"
            )

    uri = _asset_value(texture, "inputs:file")
    if _pure_suffix(uri) not in SUPPORTED_TEXTURE_EXTENSIONS:
        raise ValueError(
            f"USD texture shader {texture_path!r}: only PNG, JPEG, and EXR "
            "textures are supported"
        )
    return _Texture(
        material=material_index,
        semantic=semantic,
        uri=uri,
        wrap_s=wrap_values["S"],
        wrap_t=wrap_values["T"],
        resource_paths=(texture_path, reader_path),
    )


def _pure_suffix(uri: str) -> str:
    """Return the normalized lowercase suffix without filesystem semantics."""

    return PurePosixPath(uri).suffix.lower()


def _parse_material(
    prim,
    path: str,
    *,
    material_index: int,
    prims: dict[str, object],
) -> tuple[dict[str, object], list[_Texture], frozenset[str]]:
    properties = set(prim.property_names())
    if properties != {"outputs:surface"}:
        unsupported = sorted(properties - {"outputs:surface"})
        missing = "outputs:surface" not in properties
        detail = (
            "missing outputs:surface"
            if missing
            else "unsupported properties: " + ", ".join(unsupported)
        )
        raise ValueError(f"USD material {path!r}: {detail}")
    surface = _attribute(prim, "outputs:surface", "token", required=True)
    if surface.value is not None:
        raise ValueError(
            f"USD material {path!r}: outputs:surface may not author a value"
        )
    connections = _connections(prim, "outputs:surface")
    if len(connections) != 1:
        raise ValueError(
            f"USD material {path!r}: outputs:surface must have exactly "
            "one connection"
        )
    preview_path, preview = _target_prim(
        connections[0],
        output="surface",
        prims=prims,
        context=f"USD material {path!r} outputs:surface",
    )
    if (
        preview.type_name != "Shader"
        or _shader_id(preview) != PREVIEW_SURFACE_SHADER_ID
        or not preview_path.startswith(path + "/")
    ):
        raise ValueError(
            f"USD material {path!r}: surface must connect to one descendant "
            "UsdPreviewSurface"
        )
    allowed = frozenset(
        {"info:id", "outputs:surface"}
        | {f"inputs:{name}" for name in PREVIEW_SURFACE_INPUTS}
    )
    _validate_shader_properties(
        preview,
        allowed,
        context=f"USD preview shader {preview_path!r}",
    )
    output = _attribute(
        preview,
        "outputs:surface",
        "token",
        required=True,
    )
    if output.value is not None:
        raise ValueError(
            f"USD preview shader {preview_path!r}: output may not author a value"
        )

    values: dict[str, object] = {}
    textures: list[_Texture] = []
    consumed_paths = {preview_path}
    for input_name in _PREVIEW_INPUT_ORDER:
        connections = _connections(preview, f"inputs:{input_name}")
        if connections:
            if input_name not in _TEXTURE_INPUTS:
                raise ValueError(
                    f"USD preview shader {preview_path!r}: connected "
                    f"inputs:{input_name} is not representable"
                )
            texture = _texture_from_connection(
                preview,
                input_name,
                material_index=material_index,
                material_path=path,
                prims=prims,
            )
            assert texture is not None
            textures.append(texture)
            consumed_paths.update(texture.resource_paths)
            values[input_name] = _DEFAULTS[input_name]
            continue
        value = _direct_value(
            preview,
            input_name,
            default=_DEFAULTS[input_name],
        )
        if input_name not in _REPRESENTED_INPUTS and value != _DEFAULTS[input_name]:
            raise ValueError(
                f"USD preview shader {preview_path!r}: inputs:{input_name} "
                "must retain its specification default"
            )
        if input_name == "normal" and value != _DEFAULTS[input_name]:
            raise ValueError(
                f"USD preview shader {preview_path!r}: a non-default constant "
                "normal is not representable; use a supported normal texture"
            )
        values[input_name] = value

    if values["opacityMode"] != "transparent":
        raise ValueError(
            f"USD preview shader {preview_path!r}: opacityMode must be transparent"
        )
    for name in ("metallic", "roughness", "opacity", "opacityThreshold"):
        value = float(values[name])
        if value < 0.0 or value > 1.0:
            raise ValueError(
                f"USD preview shader {preview_path!r}: inputs:{name} "
                "must be in [0, 1]"
            )
    texture_semantics = {texture.semantic for texture in textures}
    base_rgb = (
        (1.0, 1.0, 1.0)
        if "base_color" in texture_semantics
        else tuple(values["diffuseColor"])
    )
    emissive = (
        (1.0, 1.0, 1.0)
        if "emissive" in texture_semantics
        else tuple(values["emissiveColor"])
    )
    metallic = 1.0 if "metallic" in texture_semantics else float(values["metallic"])
    roughness = (
        1.0 if "roughness" in texture_semantics else float(values["roughness"])
    )
    opacity = 1.0 if "alpha" in texture_semantics else float(values["opacity"])
    threshold = float(values["opacityThreshold"])
    alpha_mode = (
        "mask"
        if threshold > 0.0
        else "blend"
        if opacity < 1.0 or "alpha" in texture_semantics
        else "opaque"
    )
    return (
        {
            "base_color": (*base_rgb, opacity),
            "emissive": emissive,
            "metallic": metallic,
            "roughness": roughness,
            "alpha_mode": alpha_mode,
            "alpha_cutoff": threshold if alpha_mode == "mask" else 0.5,
        },
        textures,
        frozenset(consumed_paths),
    )


def collect_stage_materials(
    stage,
    *,
    source_path: str | Path,
    build_record: bool = True,
    include_material_paths: frozenset[str] | None = None,
    include_mesh_paths: frozenset[str] | None = None,
    resolve_assets: bool = True,
) -> StageMaterials:
    """Parse the selected bounded shading resources without texture pixels."""

    prims, parents = _prim_index(stage)
    all_material_paths = [
        path for path, prim in prims.items() if prim.type_name == "Material"
    ]
    material_paths = [
        path
        for path in all_material_paths
        if include_material_paths is None or path in include_material_paths
    ]
    names = [prims[path].name for path in material_paths]
    if len(set(names)) != len(names):
        raise ValueError(
            "USD: selected Material prims must have unique leaf names"
        )
    all_material_set = set(all_material_paths)
    active_material_set = set(material_paths)
    resource_paths = {
        path
        for path, prim in prims.items()
        if prim.type_name in MATERIAL_PRIM_TYPES
        or prim.type_name == "GeomSubset"
    }
    for path, prim in prims.items():
        ancestor = parents[path]
        while ancestor is not None and ancestor not in all_material_set:
            ancestor = parents[ancestor]
        if prim.type_name in {"Shader", "NodeGraph"}:
            if ancestor is None:
                if include_material_paths is None:
                    raise ValueError(
                        f"USD shading prim {path!r}: Shader/NodeGraph must be "
                        "a Material descendant"
                    )
                continue
            if ancestor in active_material_set and prim.type_name == "NodeGraph":
                raise ValueError(
                    f"USD material {ancestor!r}: NodeGraph {path!r} is "
                    "outside the bounded material profile"
                )
        if (
            ancestor in active_material_set
            and path != ancestor
            and prim.type_name not in {"Shader", "NodeGraph"}
        ):
            raise ValueError(
                f"USD material {ancestor!r}: descendant {path!r} has "
                f"unsupported type {prim.type_name!r}"
            )
    for path, prim in prims.items():
        if prim.type_name != "GeomSubset":
            continue
        parent = parents[path]
        if (
            include_mesh_paths is not None
            and parent not in include_mesh_paths
        ):
            continue
        if parent is None or prims[parent].type_name != "Mesh":
            raise ValueError(
                f"USD GeomSubset {path!r}: must be a direct Mesh child"
            )

    material_indices = {
        path: index for index, path in enumerate(material_paths)
    }
    rows: list[dict[str, object]] = []
    textures: list[_Texture] = []
    for path in material_paths:
        prim = prims[path]
        children = list(prim.children())
        if any(
            child.type_name not in {"Shader", "NodeGraph"}
            for child in children
        ):
            raise ValueError(
                f"USD material {path!r}: only Shader/NodeGraph children "
                "are supported"
            )
        row, material_textures, consumed_paths = _parse_material(
            prim,
            path,
            material_index=material_indices[path],
            prims=prims,
        )
        shading_descendants = {
            candidate
            for candidate, descendant in prims.items()
            if candidate.startswith(path + "/")
            and descendant.type_name in {"Shader", "NodeGraph"}
        }
        unconsumed = sorted(shading_descendants - consumed_paths)
        if unconsumed:
            raise ValueError(
                f"USD material {path!r}: unconsumed shading prims are "
                "outside the bounded profile: " + ", ".join(unconsumed)
            )
        rows.append(row)
        textures.extend(material_textures)

    asset_uris = tuple(dict.fromkeys(texture.uri for texture in textures))
    assets: dict[str, str] = {}
    source = Path(source_path)
    for uri in asset_uris:
        assets[uri] = (
            package.asset_source_for(source, uri)
            if resolve_assets
            else uri
        )
    for texture in textures:
        if texture.uri not in assets:
            raise ValueError(
                f"USD texture {texture.uri!r}: has no external asset source"
            )
    record = None
    if rows and build_record:
        record = _core.material_set(
            names,
            base_colors=np.asarray(
                [row["base_color"] for row in rows],
                dtype=np.float32,
            ),
            emissive_colors=np.asarray(
                [row["emissive"] for row in rows],
                dtype=np.float32,
            ),
            metallic=np.asarray(
                [row["metallic"] for row in rows],
                dtype=np.float32,
            ),
            roughness=np.asarray(
                [row["roughness"] for row in rows],
                dtype=np.float32,
            ),
            alpha_modes=[str(row["alpha_mode"]) for row in rows],
            alpha_cutoffs=np.asarray(
                [row["alpha_cutoff"] for row in rows],
                dtype=np.float32,
            ),
            texture_materials=np.asarray(
                [texture.material for texture in textures],
                dtype=np.uint64,
            ),
            texture_semantics=[texture.semantic for texture in textures],
            texture_paths=[texture.uri for texture in textures],
            texture_uv_sets=np.zeros(len(textures), dtype=np.uint32),
            texture_wrap_s=[texture.wrap_s for texture in textures],
            texture_wrap_t=[texture.wrap_t for texture in textures],
        )
    return StageMaterials(
        record=record,
        material_indices=material_indices,
        resource_paths=frozenset(resource_paths),
        external_asset_uris=asset_uris,
        external_asset_sources=tuple(assets.values()),
    )


def stage_resource_paths(stage) -> frozenset[str]:
    """Identify shading and face-subset prims excluded from SceneGraph nodes."""

    prims, _ = _prim_index(stage)
    return frozenset(
        path
        for path, prim in prims.items()
        if prim.type_name in MATERIAL_PRIM_TYPES
        or prim.type_name == "GeomSubset"
    )


def bound_material_paths(prim) -> frozenset[str]:
    """Return material targets reachable from one mesh and its subsets."""

    targets: set[str] = set()
    direct = prim.get_relationship_targets("material:binding")
    if direct is not None:
        targets.update(str(target) for target in direct)
    for child in prim.children():
        if child.type_name != "GeomSubset":
            continue
        subset = child.get_relationship_targets("material:binding")
        if subset is not None:
            targets.update(str(target) for target in subset)
    return frozenset(targets)


def mesh_shell_properties(prim) -> frozenset[str]:
    """Return the material properties consumed outside mesh geometry."""

    return frozenset(set(prim.property_names()) & MESH_MATERIAL_PROPERTIES)


def _one_binding_target(
    prim,
    *,
    context: str,
    material_indices: dict[str, int],
) -> int | None:
    targets = prim.get_relationship_targets("material:binding")
    if targets is None:
        return None
    if "MaterialBindingAPI" not in _api_schemas(prim):
        raise ValueError(f"{context}: material binding requires MaterialBindingAPI")
    if len(targets) != 1:
        raise ValueError(f"{context}: material binding must have one target")
    target = str(targets[0])
    try:
        return material_indices[target]
    except KeyError:
        raise ValueError(
            f"{context}: material target {target!r} is not a bounded Material"
        ) from None


def _subset_token(prim, name: str, text: str) -> str:
    match = _SUBSET_TOKEN[name].search(text)
    if match is None:
        raise ValueError(f"USD GeomSubset {prim.name!r}: missing {name}")
    return match.group(1)


def _subset_indices(prim, text: str) -> np.ndarray:
    match = _SUBSET_INDICES.search(text)
    if match is None:
        raise ValueError(f"USD GeomSubset {prim.name!r}: missing indices")
    encoded = match.group(1)
    if re.fullmatch(r"\s*(?:[+-]?\d+\s*(?:,\s*)?)*", encoded) is None:
        raise ValueError(f"USD GeomSubset {prim.name!r}: invalid indices")
    values = np.fromstring(encoded.replace(",", " "), sep=" ", dtype=np.int64)
    return values


def binding_ranges_for_mesh(
    prim,
    *,
    face_count: int,
    material_indices: dict[str, int],
) -> dict[str, np.ndarray]:
    """Map direct and face-subset bindings to contiguous primitive ranges."""

    context = f"USD mesh {prim.name!r}"
    properties = set(prim.property_names())
    material_properties = {
        name
        for name in properties
        if name == "material:binding"
        or name.startswith("material:binding:")
        or name.startswith("subsetFamily:")
    }
    unsupported = sorted(material_properties - MESH_MATERIAL_PROPERTIES)
    if unsupported:
        raise ValueError(
            f"{context}: unsupported material properties: "
            + ", ".join(unsupported)
        )
    subsets = [child for child in prim.children() if child.type_name == "GeomSubset"]
    if not material_properties and not subsets:
        return {}
    direct = _one_binding_target(
        prim,
        context=context,
        material_indices=material_indices,
    )
    if not subsets:
        if direct is None or face_count == 0:
            return {}
        return {
            "primitive_offsets": np.array(
                [0, face_count], dtype=np.uint64
            ),
            "primitive_materials": np.array([direct], dtype=np.int32),
        }
    family_match = _FAMILY_TYPE.search(prim.to_string())
    family_type = None if family_match is None else family_match.group(1)
    if family_type == "unrestricted":
        raise ValueError(
            f"{context}: materialBind subsets must be non-overlapping"
        )
    if family_type is None:
        raise ValueError(
            f"{context}: material GeomSubsets require partition or "
            "nonOverlapping family type"
        )
    face_materials = np.full(
        face_count,
        -1 if direct is None else direct,
        dtype=np.int32,
    )
    assigned = np.zeros(face_count, dtype=bool)
    for subset in subsets:
        subset_context = f"USD GeomSubset {subset.name!r}"
        if set(subset.property_names()) != {
            "elementType",
            "familyName",
            "indices",
            "material:binding",
        }:
            raise ValueError(
                f"{subset_context}: unsupported or missing properties"
            )
        if subset.children():
            raise ValueError(f"{subset_context}: children are unsupported")
        if "MaterialBindingAPI" not in _api_schemas(subset):
            raise ValueError(
                f"{subset_context}: material binding requires MaterialBindingAPI"
            )
        text = subset.to_string()
        if _subset_token(subset, "elementType", text) != "face":
            raise ValueError(f"{subset_context}: elementType must be face")
        if _subset_token(subset, "familyName", text) != "materialBind":
            raise ValueError(
                f"{subset_context}: familyName must be materialBind"
            )
        indices = _subset_indices(subset, text)
        if indices.size and (
            int(indices.min()) < 0 or int(indices.max()) >= face_count
        ):
            raise ValueError(f"{subset_context}: face index is out of range")
        if indices.size != np.unique(indices).size:
            raise ValueError(f"{subset_context}: face indices must be unique")
        if indices.size and np.any(assigned[indices]):
            raise ValueError(f"{context}: material subsets overlap")
        material = _one_binding_target(
            subset,
            context=subset_context,
            material_indices=material_indices,
        )
        if material is None:
            raise ValueError(f"{subset_context}: material binding is required")
        face_materials[indices] = material
        assigned[indices] = True
    if family_type == "partition" and face_count and not np.all(assigned):
        raise ValueError(
            f"{context}: partition material subsets must cover every face"
        )
    if face_count == 0:
        return {}
    boundaries = np.flatnonzero(face_materials[1:] != face_materials[:-1]) + 1
    offsets = np.concatenate(
        (
            np.array([0], dtype=np.uint64),
            boundaries.astype(np.uint64),
            np.array([face_count], dtype=np.uint64),
        )
    )
    return {
        "primitive_offsets": offsets,
        "primitive_materials": face_materials[offsets[:-1]],
    }


def validate_writable_materials(scene) -> None:
    """Guard MaterialSet fields outside the bounded USD vocabulary."""

    if not scene.has_materials:
        if any(kind == "texture" for kind in scene.external_asset_kinds):
            raise ValueError("USD: texture assets require SceneGraph.materials")
        return
    material_set = scene.materials
    names = tuple(material_set.names)
    if (
        len(set(names)) != len(names)
        or any(_IDENTIFIER.fullmatch(name) is None for name in names)
    ):
        raise ValueError(
            "USD: material names must be unique portable identifiers"
        )
    semantics = tuple(material_set.texture_semantics)
    unsupported = sorted(set(semantics) - set(_SEMANTIC_INPUTS))
    if unsupported:
        raise ValueError(
            "USD: unsupported material texture semantics: "
            + ", ".join(unsupported)
        )
    if np.any(np.asarray(material_set.texture_uv_sets) != 0):
        raise ValueError("USD: material textures must use UV set 0 ('st')")
    if np.any(np.asarray(material_set.texture_min_filter_codes) != 0) or np.any(
        np.asarray(material_set.texture_mag_filter_codes) != 0
    ):
        raise ValueError(
            "USD: UsdUVTexture cannot preserve explicit min/mag filters"
        )
    for uri in material_set.texture_paths:
        package.normalize_asset_uri(uri, context="USD material texture")
        if _pure_suffix(uri) not in SUPPORTED_TEXTURE_EXTENSIONS:
            raise ValueError("USD: material textures must be PNG, JPEG, or EXR")
    rows: dict[tuple[int, str], int] = {}
    actual_order: list[tuple[int, str]] = []
    for row, (material, semantic) in enumerate(
        zip(material_set.texture_materials, semantics, strict=True)
    ):
        key = (int(material), semantic)
        rows[key] = row
        actual_order.append(key)
    expected_order = sorted(
        actual_order,
        key=lambda item: (
            item[0],
            _TEXTURE_SEMANTIC_ORDER.index(item[1]),
        ),
    )
    if actual_order != expected_order:
        raise ValueError(
            "USD: material texture rows must be grouped by material in "
            "base_color/emissive/metallic/roughness/alpha/normal order"
        )
    base = np.asarray(material_set.base_colors)
    emissive = np.asarray(material_set.emissive_colors)
    metallic = np.asarray(material_set.metallic)
    roughness = np.asarray(material_set.roughness)
    cutoffs = np.asarray(material_set.alpha_cutoffs)
    for index, mode in enumerate(material_set.alpha_modes):
        if (index, "base_color") in rows and not np.array_equal(
            base[index, :3], np.ones(3, dtype=np.float32)
        ):
            raise ValueError(
                "USD: textured base color requires a unit RGB factor"
            )
        if (index, "emissive") in rows and not np.array_equal(
            emissive[index], np.ones(3, dtype=np.float32)
        ):
            raise ValueError(
                "USD: textured emissive color requires a unit RGB factor"
            )
        if (index, "metallic") in rows and metallic[index] != 1.0:
            raise ValueError(
                "USD: textured metallic requires a unit factor"
            )
        if (index, "roughness") in rows and roughness[index] != 1.0:
            raise ValueError(
                "USD: textured roughness requires a unit factor"
            )
        has_alpha = (index, "alpha") in rows
        if has_alpha and base[index, 3] != 1.0:
            raise ValueError(
                "USD: textured opacity requires a unit alpha factor"
            )
        if mode == "opaque" and (has_alpha or base[index, 3] != 1.0):
            raise ValueError(
                "USD: opaque materials must have unit constant opacity "
                "and no opacity texture"
            )
        if mode == "blend" and not has_alpha and base[index, 3] == 1.0:
            raise ValueError(
                "USD: blend materials require opacity below one or an "
                "opacity texture"
            )
        if mode == "mask" and not (cutoffs[index] > 0.0):
            raise ValueError(
                "USD: mask materials require a positive alpha cutoff"
            )
        if mode != "mask" and cutoffs[index] != np.float32(0.5):
            raise ValueError(
                "USD: non-mask material alpha cutoffs must retain 0.5"
            )


def choose_material_scope(scene) -> str:
    """Choose a deterministic collision-free root scope name."""

    parents = np.asarray(scene.node_parents)
    root_names = {
        scene.node_names[index]
        for index in np.flatnonzero(parents == -1)
    }
    base = "SceneIOMaterials"
    name = base
    suffix = 1
    while name in root_names:
        name = f"{base}_{suffix}"
        suffix += 1
    return name


def material_paths(scope_name: str, material_set) -> tuple[str, ...]:
    return tuple(
        f"/{scope_name}/{name}" for name in material_set.names
    )


def _f32(value: object) -> str:
    return format(float(np.float32(value)), ".9g")


def _tuple(values: object) -> str:
    return "(" + ", ".join(_f32(value) for value in values) + ")"


def _texture_rows(material_set) -> dict[int, dict[str, int]]:
    result: dict[int, dict[str, int]] = {}
    for row, (material, semantic) in enumerate(
        zip(
            material_set.texture_materials,
            material_set.texture_semantics,
            strict=True,
        )
    ):
        result.setdefault(int(material), {})[semantic] = row
    return result


def write_material_library(
    stream,
    material_set,
    *,
    scope_name: str,
    texture_paths: dict[str, str],
) -> None:
    """Write the canonical bounded PreviewSurface networks."""

    rows = _texture_rows(material_set)
    stream.write(f'\ndef Scope "{scope_name}"\n{{\n')
    for material_index, name in enumerate(material_set.names):
        path = f"/{scope_name}/{name}"
        preview_path = f"{path}/PreviewSurface"
        material_rows = rows.get(material_index, {})
        stream.write(
            f'    def Material "{name}"\n'
            "    {\n"
            "        token outputs:surface.connect = "
            f"<{preview_path}.outputs:surface>\n\n"
            '        def Shader "PreviewSurface"\n'
            "        {\n"
            '            uniform token info:id = "UsdPreviewSurface"\n'
        )
        for input_name, semantic in (
            ("diffuseColor", "base_color"),
            ("emissiveColor", "emissive"),
            ("metallic", "metallic"),
            ("roughness", "roughness"),
            ("opacity", "alpha"),
            ("normal", "normal"),
        ):
            if semantic not in material_rows:
                continue
            _, output, _ = _TEXTURE_INPUTS[input_name]
            type_name = _INPUT_TYPES[input_name]
            texture_name = f"Texture_{semantic}"
            stream.write(
                f"            {type_name} inputs:{input_name}.connect = "
                f"<{path}/{texture_name}.outputs:{output}>\n"
            )
        if "base_color" not in material_rows:
            stream.write(
                "            color3f inputs:diffuseColor = "
                f"{_tuple(material_set.base_colors[material_index, :3])}\n"
            )
        if "emissive" not in material_rows:
            stream.write(
                "            color3f inputs:emissiveColor = "
                f"{_tuple(material_set.emissive_colors[material_index])}\n"
            )
        if "metallic" not in material_rows:
            stream.write(
                "            float inputs:metallic = "
                f"{_f32(material_set.metallic[material_index])}\n"
            )
        if "roughness" not in material_rows:
            stream.write(
                "            float inputs:roughness = "
                f"{_f32(material_set.roughness[material_index])}\n"
            )
        if "alpha" not in material_rows:
            stream.write(
                "            float inputs:opacity = "
                f"{_f32(material_set.base_colors[material_index, 3])}\n"
            )
        threshold = (
            material_set.alpha_cutoffs[material_index]
            if material_set.alpha_modes[material_index] == "mask"
            else 0.0
        )
        stream.write(
            "            float inputs:opacityThreshold = "
            f"{_f32(threshold)}\n"
            "            token outputs:surface\n"
            "        }\n"
        )
        if material_rows:
            stream.write(
                '\n        def Shader "Primvar_st"\n'
                "        {\n"
                '            uniform token info:id = "UsdPrimvarReader_float2"\n'
                '            string inputs:varname = "st"\n'
                "            float2 outputs:result\n"
                "        }\n"
            )
        for semantic in _TEXTURE_SEMANTIC_ORDER:
            if semantic not in material_rows:
                continue
            row = material_rows[semantic]
            input_name = _SEMANTIC_INPUTS[semantic]
            _, output, color_space = _TEXTURE_INPUTS[input_name]
            wrap_s = _WRAP_TO_USD[
                _WRAP_CODE_NAMES[
                    int(material_set.texture_wrap_s_codes[row])
                ]
            ]
            wrap_t = _WRAP_TO_USD[
                _WRAP_CODE_NAMES[
                    int(material_set.texture_wrap_t_codes[row])
                ]
            ]
            texture_name = f"Texture_{semantic}"
            uri = texture_paths[material_set.texture_paths[row]]
            scale = (
                (2.0, 2.0, 2.0, 1.0)
                if semantic == "normal"
                else (1.0, 1.0, 1.0, 1.0)
            )
            bias = (
                (-1.0, -1.0, -1.0, 0.0)
                if semantic == "normal"
                else (0.0, 0.0, 0.0, 0.0)
            )
            output_type = "float3" if output == "rgb" else "float"
            stream.write(
                f'\n        def Shader "{texture_name}"\n'
                "        {\n"
                '            uniform token info:id = "UsdUVTexture"\n'
                f"            asset inputs:file = @{uri}@\n"
                "            float2 inputs:st.connect = "
                f"<{path}/Primvar_st.outputs:result>\n"
                f'            token inputs:wrapS = "{wrap_s}"\n'
                f'            token inputs:wrapT = "{wrap_t}"\n'
                "            float4 inputs:scale = "
                f"{_tuple(scale)}\n"
                "            float4 inputs:bias = "
                f"{_tuple(bias)}\n"
                "            token inputs:sourceColorSpace = "
                f'"{color_space}"\n'
                f"            {output_type} outputs:{output}\n"
                "        }\n"
            )
        stream.write("    }\n")
    stream.write("}\n")


def write_mesh_bindings(
    stream,
    mesh,
    *,
    inner: str,
    paths: tuple[str, ...],
) -> None:
    """Write direct or non-overlapping face material bindings."""

    if mesh.num_faces == 0:
        return
    offsets = np.asarray(mesh.primitive_offsets)
    assignments = np.asarray(mesh.primitive_materials)
    if len(assignments) == 1 and int(assignments[0]) >= 0:
        stream.write(
            f"{inner}rel material:binding = "
            f"<{paths[int(assignments[0])]}>"
            "\n"
        )
        return
    ranges_by_material: dict[int, list[tuple[int, int]]] = {}
    bound_faces = 0
    for primitive, value in enumerate(assignments):
        material = int(value)
        if material < 0:
            continue
        start = int(offsets[primitive])
        stop = int(offsets[primitive + 1])
        if stop <= start:
            continue
        ranges_by_material.setdefault(material, []).append((start, stop))
        bound_faces += stop - start
    if not bound_faces:
        return
    family_type = (
        "partition" if bound_faces == mesh.num_faces else "nonOverlapping"
    )
    stream.write(
        f"{inner}uniform token subsetFamily:materialBind:familyType = "
        f'"{family_type}"\n'
    )
    for material, ranges in sorted(ranges_by_material.items()):
        stream.write(
            f'\n{inner}def GeomSubset "material_{material}"\n'
            f"{inner}(\n"
            f'{inner}    prepend apiSchemas = ["MaterialBindingAPI"]\n'
            f"{inner})\n"
            f"{inner}{{\n"
            f'{inner}    uniform token elementType = "face"\n'
            f'{inner}    uniform token familyName = "materialBind"\n'
            f"{inner}    int[] indices = ["
        )
        first = True
        for range_start, range_stop in ranges:
            for start in range(range_start, range_stop, 4096):
                stop = min(start + 4096, range_stop)
                values = np.arange(start, stop, dtype=np.int64)
                rendered = np.char.mod("%d", values).tolist()
                if not first:
                    stream.write(", ")
                stream.write(", ".join(rendered))
                first = False
        stream.write(
            "]\n"
            f"{inner}    rel material:binding = <{paths[material]}>\n"
            f"{inner}}}\n"
        )


__all__ = [
    "MATERIAL_PRIM_TYPES",
    "MESH_MATERIAL_PROPERTIES",
    "PREVIEW_SURFACE_INPUTS",
    "PREVIEW_SURFACE_SHADER_ID",
    "SUPPORTED_TEXTURE_EXTENSIONS",
    "StageMaterials",
    "binding_ranges_for_mesh",
    "bound_material_paths",
    "choose_material_scope",
    "collect_stage_materials",
    "material_paths",
    "mesh_shell_properties",
    "stage_resource_paths",
    "validate_writable_materials",
    "write_material_library",
    "write_mesh_bindings",
]
