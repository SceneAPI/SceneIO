"""Static 3D-CV mesh scenes in ASCII USD and aligned USDZ packages."""

from __future__ import annotations

import os
import re
import shutil
import struct
import tempfile
import zipfile
from contextlib import suppress
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.model import Inspection

_IDENTITY = np.eye(4, dtype=np.float64)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_XFORM_PROPERTIES = frozenset({"xformOp:transform", "xformOpOrder"})
_MESH_PROPERTIES = frozenset(
    {
        "points",
        "faceVertexCounts",
        "faceVertexIndices",
        "normals",
        "primvars:st",
        "subdivisionScheme",
        "extent",
    }
)


def _require_tinyusdz():
    try:
        import tinyusdz
    except ModuleNotFoundError:
        raise RuntimeError(
            "USD/USDZ support requires the optional dependency; "
            "install sceneio[usd]"
        ) from None
    return tinyusdz


def _load_stage(path: str | os.PathLike[str]):
    tinyusdz = _require_tinyusdz()
    try:
        return tinyusdz.load(os.fspath(path))
    except Exception as exc:
        raise ValueError(f"USD: provider could not load the stage: {exc}") from exc


def _value_array(
    prim,
    name: str,
    dtype: np.dtype,
    *,
    copy: bool = True,
) -> np.ndarray:
    attribute = prim.get_attribute(name)
    if attribute is None:
        raise ValueError(f"USD mesh {prim.name!r}: missing {name!r}")
    samples = prim.get_attribute_timesamples(name)
    if samples:
        raise ValueError(
            f"USD mesh {prim.name!r}: time-sampled {name!r} is unsupported"
        )
    array = np.asarray(attribute.value)
    if array.dtype != dtype:
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} must have dtype {dtype.name}"
        )
    if copy:
        return np.array(array, copy=True, order="C")
    return array


def _render_transforms(stage) -> dict[str, np.ndarray]:
    tinyusdz = _require_tinyusdz()
    try:
        rendered = tinyusdz.tydra.convert_to_render_scene(stage)
    except Exception as exc:
        raise ValueError(
            f"USD: provider could not evaluate static transforms: {exc}"
        ) from exc
    result = {}
    for node in rendered.nodes():
        matrix = np.asarray(node.local_matrix, dtype=np.float64)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise ValueError(
                f"USD prim {node.abs_path!r}: invalid local transform"
            )
        result[str(node.abs_path)] = np.array(matrix, copy=True, order="C")
    return result


def _interpolation(prim, name: str) -> str:
    value = prim.get_attribute_metadata(name, "interpolation")
    if value not in {"vertex", "faceVarying"}:
        raise ValueError(
            f"USD mesh {prim.name!r}: {name!r} interpolation must be "
            "'vertex' or 'faceVarying'"
        )
    return value


def _mesh_arrays_from_prim(
    prim,
    *,
    copy: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    properties = set(prim.property_names())
    unsupported = sorted(properties - _MESH_PROPERTIES)
    if unsupported:
        raise ValueError(
            f"USD mesh {prim.name!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    required = {"points", "faceVertexCounts", "faceVertexIndices"}
    missing = sorted(required - properties)
    if missing:
        raise ValueError(
            f"USD mesh {prim.name!r}: missing properties: "
            + ", ".join(missing)
        )

    positions = _value_array(
        prim, "points", np.dtype(np.float32), copy=copy
    )
    if positions.ndim != 2 or positions.shape[1:] != (3,):
        raise ValueError(
            f"USD mesh {prim.name!r}: points must have shape (N, 3)"
        )
    counts = _value_array(
        prim, "faceVertexCounts", np.dtype(np.int32), copy=copy
    )
    indices_i32 = _value_array(
        prim, "faceVertexIndices", np.dtype(np.int32), copy=copy
    )
    if counts.ndim != 1 or indices_i32.ndim != 1:
        raise ValueError(
            f"USD mesh {prim.name!r}: face topology arrays must be rank 1"
        )
    if counts.size and int(counts.min()) < 3:
        raise ValueError(
            f"USD mesh {prim.name!r}: faces must contain at least 3 corners"
        )
    if int(counts.astype(np.int64).sum()) != len(indices_i32):
        raise ValueError(
            f"USD mesh {prim.name!r}: face counts and indices disagree"
        )
    if indices_i32.size and (
        int(indices_i32.min()) < 0 or int(indices_i32.max()) >= len(positions)
    ):
        raise ValueError(
            f"USD mesh {prim.name!r}: face index is outside the point array"
        )
    if positions.size and not np.isfinite(positions).all():
        raise ValueError(f"USD mesh {prim.name!r}: points must be finite")

    kwargs: dict[str, np.ndarray] = {}

    for usd_name, vertex_name, corner_name, width in (
        ("normals", "vertex_normals", "corner_normals", 3),
        ("primvars:st", "vertex_uvs", "corner_uvs", 2),
    ):
        if usd_name not in properties:
            continue
        array = _value_array(
            prim, usd_name, np.dtype(np.float32), copy=copy
        )
        if array.ndim != 2 or array.shape[1:] != (width,):
            raise ValueError(
                f"USD mesh {prim.name!r}: {usd_name!r} has invalid shape"
            )
        if array.size and not np.isfinite(array).all():
            raise ValueError(
                f"USD mesh {prim.name!r}: {usd_name!r} must be finite"
            )
        domain = _interpolation(prim, usd_name)
        expected = (
            len(positions) if domain == "vertex" else len(indices_i32)
        )
        if len(array) != expected:
            raise ValueError(
                f"USD mesh {prim.name!r}: {usd_name!r} {domain} count "
                "does not match topology"
            )
        kwargs[vertex_name if domain == "vertex" else corner_name] = array

    if "subdivisionScheme" in properties:
        attribute = prim.get_attribute("subdivisionScheme")
        if attribute is None or attribute.value.to_string() != '"none"':
            raise ValueError(
                f"USD mesh {prim.name!r}: subdivision surfaces are unsupported"
            )
    if "extent" in properties:
        extent = _value_array(
            prim, "extent", np.dtype(np.float32), copy=copy
        )
        if extent.shape != (2, 3) or (
            extent.size and not np.isfinite(extent).all()
        ):
            raise ValueError(f"USD mesh {prim.name!r}: invalid extent")

    return positions, counts, indices_i32, kwargs


def _mesh_from_prim(prim):
    positions, counts, indices_i32, kwargs = _mesh_arrays_from_prim(
        prim, copy=True
    )
    face_offsets = np.empty(len(counts) + 1, dtype=np.uint64)
    face_offsets[0] = 0
    np.cumsum(counts, dtype=np.uint64, out=face_offsets[1:])
    indices = indices_i32.astype(np.uint64)

    return _core.mesh(
        positions,
        face_offsets,
        indices,
        coordinate_frame="opengl",
        scale_to_meters=1.0,
        **kwargs,
    )


def _validate_stage_metadata(stage) -> None:
    up_axis = stage.get_metadata("upAxis")
    meters = stage.get_metadata("metersPerUnit")
    if up_axis != "Y" or meters != 1.0:
        raise ValueError(
            "USD: the bounded profile requires upAxis='Y' and "
            "metersPerUnit=1"
        )
    for key in (
        "startTimeCode",
        "endTimeCode",
        "timeCodesPerSecond",
        "framesPerSecond",
    ):
        if stage.get_metadata(key) is not None:
            raise ValueError("USD: animated stages are unsupported")


def _validate_prim_shell(
    prim,
    parent_path: str,
    render_transforms: dict[str, np.ndarray],
) -> str:
    if prim.type_name not in {"Xform", "Scope", "Mesh"}:
        raise ValueError(
            f"USD: prim {prim.name!r} has unsupported type "
            f"{prim.type_name!r}"
        )
    if not _IDENTIFIER.fullmatch(prim.name):
        raise ValueError(
            f"USD: prim name {prim.name!r} is not a portable identifier"
        )
    properties = set(prim.property_names())
    allowed = _MESH_PROPERTIES if prim.type_name == "Mesh" else (
        _XFORM_PROPERTIES if prim.type_name == "Xform" else frozenset()
    )
    unsupported = sorted(properties - allowed)
    if unsupported:
        raise ValueError(
            f"USD prim {prim.name!r}: unsupported properties: "
            + ", ".join(unsupported)
        )
    path = f"{parent_path}/{prim.name}"
    if prim.type_name == "Xform" and path not in render_transforms:
        raise ValueError(
            f"USD prim {path!r}: transform evaluation is unavailable"
        )
    return path


def _stage_to_scene(stage):
    _validate_stage_metadata(stage)
    primitives = []
    render_transforms = _render_transforms(stage)
    node_meshes: list[int] = []
    node_transforms: list[np.ndarray] = []
    node_names: list[str] = []
    child_lists: list[list[int]] = []
    roots: list[int] = []

    def visit(prim, parent_path: str) -> int:
        path = _validate_prim_shell(
            prim, parent_path, render_transforms
        )
        index = len(node_names)
        node_names.append(prim.name)
        node_meshes.append(-1)
        if prim.type_name == "Xform":
            node_transforms.append(render_transforms[path])
        else:
            node_transforms.append(_IDENTITY.copy())
        child_lists.append([])
        if prim.type_name == "Mesh":
            node_meshes[index] = len(primitives)
            primitives.append(_mesh_from_prim(prim))
        children = list(prim.children())
        if len({child.name for child in children}) != len(children):
            raise ValueError(
                f"USD prim {prim.name!r}: child names must be unique"
            )
        child_lists[index].extend(visit(child, path) for child in children)
        return index

    root_prims = list(stage.root_prims())
    if len({prim.name for prim in root_prims}) != len(root_prims):
        raise ValueError("USD: root prim names must be unique")
    roots.extend(visit(prim, "") for prim in root_prims)

    node_child_offsets = np.empty(len(child_lists) + 1, dtype=np.uint64)
    node_child_offsets[0] = 0
    flat_children: list[int] = []
    for index, children in enumerate(child_lists, start=1):
        flat_children.extend(children)
        node_child_offsets[index] = len(flat_children)
    mesh_offsets = np.arange(len(primitives) + 1, dtype=np.uint64)
    scene_offsets = np.array([0, len(roots)], dtype=np.uint64)
    return _core.mesh_scene(
        primitives,
        mesh_offsets,
        node_meshes=np.asarray(node_meshes, dtype=np.int64),
        node_child_offsets=node_child_offsets,
        node_children=np.asarray(flat_children, dtype=np.uint64),
        node_local_transforms=np.asarray(
            node_transforms, dtype=np.float64
        ).reshape(-1, 4, 4),
        node_names=node_names,
        scene_root_offsets=scene_offsets,
        scene_roots=np.asarray(roots, dtype=np.uint64),
        default_scene=0,
    )


def read_usd(path: str | os.PathLike[str]):
    """Read a bounded static USD stage as a hierarchy-preserving MeshScene."""

    return _stage_to_scene(_load_stage(path))


def inspect_usd(
    path: str | os.PathLike[str],
    *,
    format_id: str = "usd",
) -> Inspection:
    """Inspect the bounded USD stage using the upstream path parser."""

    stage = _load_stage(path)
    _validate_stage_metadata(stage)
    render_transforms = _render_transforms(stage)
    vertices = 0
    faces = 0
    primitive_count = 0
    node_count = 0

    def visit(prim, parent_path: str) -> None:
        nonlocal faces, node_count, primitive_count, vertices
        path = _validate_prim_shell(
            prim, parent_path, render_transforms
        )
        node_count += 1
        if prim.type_name == "Mesh":
            positions, counts, _, _ = _mesh_arrays_from_prim(
                prim, copy=False
            )
            vertices += len(positions)
            faces += len(counts)
            primitive_count += 1
        children = list(prim.children())
        if len({child.name for child in children}) != len(children):
            raise ValueError(
                f"USD prim {prim.name!r}: child names must be unique"
            )
        for child in children:
            visit(child, path)

    root_prims = list(stage.root_prims())
    if len({prim.name for prim in root_prims}) != len(root_prims):
        raise ValueError("USD: root prim names must be unique")
    for prim in root_prims:
        visit(prim, "")
    return Inspection(
        format=format_id,
        datatype="mesh_scene",
        byte_size=Path(path).stat().st_size,
        shape=(vertices, 3),
        dtype="float32",
        count=primitive_count,
        metadata={
            "node_count": node_count,
            "primitive_count": primitive_count,
            "face_count": faces,
            "scene_count": 1,
        },
    )


def inspect_usdz(path: str | os.PathLike[str]) -> Inspection:
    return inspect_usd(path, format_id="usdz")


def _valid_name(name: object, context: str) -> str:
    if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        raise ValueError(
            f"USD: {context} must be an ASCII USD identifier, got {name!r}"
        )
    return name


def _validate_mesh(mesh, index: int) -> None:
    context = f"mesh primitive {index}"
    if mesh.coordinate_frame != "opengl" or mesh.scale_to_meters != 1.0:
        raise ValueError(
            f"USD: {context} must use OpenGL/Y-up frame and meter scale 1"
        )
    if not np.array_equal(np.asarray(mesh.local_transform), _IDENTITY):
        raise ValueError(
            f"USD: {context} local_transform must be identity; use the "
            "scene node transform"
        )
    if mesh.num_primitives != 1:
        raise ValueError(f"USD: {context} must contain exactly one primitive")
    if (
        mesh.has_materials
        or mesh.has_vertex_colors
        or mesh.has_corner_colors
        or mesh.has_vertex_display_colors
        or mesh.has_corner_display_colors
        or mesh.has_vertex_display_opacities
        or mesh.has_corner_display_opacities
        or mesh.display_color_space != "unknown"
        or mesh.orientation != "unknown"
        or mesh.has_double_sided
        or mesh.has_face_smoothing_groups
        or mesh.has_primitive_object_names
        or mesh.has_primitive_group_names
    ):
        raise ValueError(
            f"USD: {context} contains unsupported material, display, "
            "orientation, double-sided, smoothing, or grouping data"
        )
    if mesh.has_vertex_normals and mesh.has_corner_normals:
        raise ValueError(f"USD: {context} has two normal domains")
    if mesh.has_vertex_uvs and mesh.has_corner_uvs:
        raise ValueError(f"USD: {context} has two UV domains")
    positions = np.asarray(mesh.positions)
    if positions.size and not np.isfinite(positions).all():
        raise ValueError(f"USD: {context} positions must be finite")
    for name in (
        "vertex_normals",
        "corner_normals",
        "vertex_uvs",
        "corner_uvs",
    ):
        if getattr(mesh, f"has_{name}"):
            array = np.asarray(getattr(mesh, name))
            if array.size and not np.isfinite(array).all():
                raise ValueError(f"USD: {context} {name} must be finite")
    face_offsets = np.asarray(mesh.face_offsets)
    indices = np.asarray(mesh.face_indices)
    counts = np.diff(face_offsets)
    limit = np.iinfo(np.int32).max
    if (
        (counts.size and int(counts.max()) > limit)
        or (indices.size and int(indices.max()) > limit)
        or len(positions) > limit
    ):
        raise ValueError(f"USD: {context} topology exceeds int32 storage")


def _validate_scene(scene):
    if not isinstance(scene, _core.MeshScene):
        raise TypeError("USD: expected a MeshScene")
    if scene.has_materials:
        raise ValueError("USD: scene materials are unsupported")
    mesh_offsets = np.asarray(scene.mesh_primitive_offsets)
    if not np.array_equal(
        mesh_offsets, np.arange(scene.num_meshes + 1, dtype=np.uint64)
    ):
        raise ValueError("USD: every mesh must contain exactly one primitive")
    if any(scene.mesh_names):
        raise ValueError("USD: mesh_names are unsupported; use node_names")
    if any(scene.scene_names):
        raise ValueError("USD: scene_names are unsupported")
    if scene.num_scenes != 1 or scene.default_scene != 0:
        raise ValueError("USD: exactly one default scene is required")

    node_names = [
        _valid_name(name, f"node name {index}")
        for index, name in enumerate(scene.node_names)
    ]
    if len(node_names) != scene.num_nodes:
        raise ValueError("USD: every node must have a name")
    node_meshes = np.asarray(scene.node_meshes, dtype=np.int64)
    referenced = node_meshes[node_meshes >= 0]
    if not np.array_equal(
        np.sort(referenced), np.arange(scene.num_meshes, dtype=np.int64)
    ):
        raise ValueError("USD: every mesh must be referenced by exactly one node")
    transforms = np.asarray(scene.node_local_transforms)
    if transforms.size and not np.isfinite(transforms).all():
        raise ValueError("USD: node transforms must be finite")
    for node, mesh_index in enumerate(node_meshes):
        if mesh_index >= 0 and not np.array_equal(transforms[node], _IDENTITY):
            raise ValueError(
                "USD: mesh-referencing nodes must use an identity transform; "
                "put transforms on a parent node"
            )

    child_offsets = np.asarray(scene.node_child_offsets)
    children = np.asarray(scene.node_children)
    roots = np.asarray(scene.scene_roots)
    root_offsets = np.asarray(scene.scene_root_offsets)
    if not np.array_equal(root_offsets, np.array([0, len(roots)], np.uint64)):
        raise ValueError("USD: invalid single-scene root offsets")
    parents = np.zeros(scene.num_nodes, dtype=np.int32)
    for child in children:
        parents[int(child)] += 1
    if parents.size and int(parents.max()) > 1:
        raise ValueError("USD: shared nodes cannot be represented by a USD tree")
    expected_roots = np.flatnonzero(parents == 0).astype(np.uint64)
    if set(int(value) for value in roots) != set(
        int(value) for value in expected_roots
    ):
        raise ValueError("USD: scene roots do not cover the complete node tree")
    for node in range(scene.num_nodes):
        begin, end = int(child_offsets[node]), int(child_offsets[node + 1])
        sibling_names = [node_names[int(child)] for child in children[begin:end]]
        if len(sibling_names) != len(set(sibling_names)):
            raise ValueError("USD: sibling node names must be unique")
    root_names = [node_names[int(root)] for root in roots]
    if len(root_names) != len(set(root_names)):
        raise ValueError("USD: root node names must be unique")

    primitives = [scene.primitive_at(i) for i in range(scene.num_primitives)]
    for index, mesh in enumerate(primitives):
        _validate_mesh(mesh, index)
    return (
        node_names,
        node_meshes,
        transforms,
        child_offsets,
        children,
        roots,
        primitives,
    )


def _float(value: object, *, double: bool = False) -> str:
    return format(float(value), ".17g" if double else ".9g")


def _write_rows(stream, array: np.ndarray, *, double: bool = False) -> None:
    stream.write("[")
    for start in range(0, len(array), 1024):
        chunk = array[start : start + 1024]
        rendered = ", ".join(
            "(" + ", ".join(_float(value, double=double) for value in row) + ")"
            for row in chunk
        )
        if start:
            stream.write(", ")
        stream.write(rendered)
    stream.write("]")


def _write_ints(stream, array: np.ndarray) -> None:
    stream.write("[")
    for start in range(0, len(array), 4096):
        if start:
            stream.write(", ")
        stream.write(
            ", ".join(str(int(value)) for value in array[start : start + 4096])
        )
    stream.write("]")


def _write_usda(scene, stream) -> None:
    (
        node_names,
        node_meshes,
        transforms,
        child_offsets,
        children,
        roots,
        primitives,
    ) = _validate_scene(scene)
    stream.write(
        '#usda 1.0\n(\n    upAxis = "Y"\n    metersPerUnit = 1\n)\n\n'
    )

    def write_node(node: int, indent: str) -> None:
        mesh_index = int(node_meshes[node])
        type_name = "Mesh" if mesh_index >= 0 else "Xform"
        stream.write(f'{indent}def {type_name} "{node_names[node]}"\n{indent}{{\n')
        inner = indent + "    "
        matrix = transforms[node]
        if not np.array_equal(matrix, _IDENTITY):
            stream.write(f"{inner}matrix4d xformOp:transform = (")
            for row_index, row in enumerate(matrix):
                if row_index:
                    stream.write(", ")
                stream.write(
                    "("
                    + ", ".join(_float(value, double=True) for value in row)
                    + ")"
                )
            stream.write(")\n")
            stream.write(
                f'{inner}uniform token[] xformOpOrder = '
                '["xformOp:transform"]\n'
            )
        if mesh_index >= 0:
            mesh = primitives[mesh_index]
            stream.write(f"{inner}point3f[] points = ")
            _write_rows(stream, np.asarray(mesh.positions))
            stream.write("\n")
            stream.write(f"{inner}int[] faceVertexCounts = ")
            _write_ints(stream, np.diff(np.asarray(mesh.face_offsets)))
            stream.write("\n")
            stream.write(f"{inner}int[] faceVertexIndices = ")
            _write_ints(stream, np.asarray(mesh.face_indices))
            stream.write("\n")
            for present, values, name, interpolation in (
                (
                    mesh.has_vertex_normals,
                    mesh.vertex_normals,
                    "normal3f[] normals",
                    "vertex",
                ),
                (
                    mesh.has_corner_normals,
                    mesh.corner_normals,
                    "normal3f[] normals",
                    "faceVarying",
                ),
                (
                    mesh.has_vertex_uvs,
                    mesh.vertex_uvs,
                    "texCoord2f[] primvars:st",
                    "vertex",
                ),
                (
                    mesh.has_corner_uvs,
                    mesh.corner_uvs,
                    "texCoord2f[] primvars:st",
                    "faceVarying",
                ),
            ):
                if not present:
                    continue
                stream.write(f"{inner}{name} = ")
                _write_rows(stream, np.asarray(values))
                stream.write(
                    f" (\n{inner}    interpolation = "
                    f'"{interpolation}"\n{inner})\n'
                )
            stream.write(f'{inner}uniform token subdivisionScheme = "none"\n')
        begin, end = int(child_offsets[node]), int(child_offsets[node + 1])
        for child in children[begin:end]:
            stream.write("\n")
            write_node(int(child), inner)
        stream.write(f"{indent}}}\n")

    for index, root in enumerate(roots):
        if index:
            stream.write("\n")
        write_node(int(root), "")


def _temporary_path(destination: Path, suffix: str) -> Path:
    fd, name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=suffix,
        dir=destination.parent,
    )
    os.close(fd)
    return Path(name)


def _write_usdz_archive(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(
        destination,
        mode="w",
        compression=zipfile.ZIP_STORED,
        allowZip64=True,
    ) as archive:
        name = "root.usda"
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        info.file_size = source.stat().st_size
        base = archive.fp.tell() + 30 + len(name.encode("utf-8")) + 4
        padding = (-base) % 64
        info.extra = struct.pack("<HH", 0xFFFF, padding) + bytes(padding)
        with source.open("rb") as input_stream, archive.open(
            info, mode="w", force_zip64=source.stat().st_size >= 0xFFFFFFFF
        ) as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)


def write_usd(scene, path: str | os.PathLike[str]) -> None:
    """Stream a bounded MeshScene to ASCII USD or an aligned USDZ package."""

    destination = Path(path)
    suffix = destination.suffix.lower()
    if suffix not in {".usd", ".usda", ".usdz"}:
        raise ValueError("USD: destination suffix must be .usd, .usda, or .usdz")
    destination.parent.mkdir(parents=True, exist_ok=True)
    usda = _temporary_path(destination, ".usda.tmp")
    output = None
    try:
        with usda.open("w", encoding="utf-8", newline="\n") as stream:
            _write_usda(scene, stream)
        if suffix == ".usdz":
            output = _temporary_path(destination, ".usdz.tmp")
            _write_usdz_archive(usda, output)
        else:
            output = usda
        os.replace(output, destination)
    finally:
        with suppress(FileNotFoundError):
            usda.unlink()
        if output is not None:
            with suppress(FileNotFoundError):
                output.unlink()


def write_usdz(scene, path: str | os.PathLike[str]) -> None:
    """Write the bounded MeshScene profile to an aligned USDZ package."""

    if Path(path).suffix.lower() != ".usdz":
        raise ValueError("USDZ: destination suffix must be .usdz")
    write_usd(scene, path)


__all__ = [
    "inspect_usd",
    "inspect_usdz",
    "read_usd",
    "write_usd",
    "write_usdz",
]
