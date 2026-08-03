"""Large scene-I/O benchmark cases and provider adapters.

The cases in this module deliberately keep acquisition and fixture building out
of timed worker operations.  A caller injects paths returned by the source
catalog (or ordinary :class:`~pathlib.Path` objects in a smoke test), prepares a
derived common artifact, and then dispatches the provider adapters below.

Only optional benchmark/oracle packages are imported inside provider calls.  A
normal ``import sceneio`` therefore remains independent of Niantic SPZ,
trimesh, and pycolmap.
"""

from __future__ import annotations

import contextlib
import gc
import gzip
import math
import struct
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from .model import CaseArtifact, CaseDefinition

MIB = 1024 * 1024
STANDARD_LOGICAL_BYTES = 256 * MIB
SMOKE_LOGICAL_BYTES = 1 * MIB
# pycolmap's Python mapping exposes one object per point and observation.  Keep
# the exhaustive contract for small fixtures, but switch to the bounded
# deterministic profile before provider-native object materialization becomes
# the dominant part of preparation.  The closure fixture uses sequential point
# IDs, so the large profile can sample IDs without sorting the pycolmap map.
COLMAP_LARGE_POINT_THRESHOLD = 100_000
COLMAP_LARGE_SAMPLE_LIMIT = 4_096
NIANTIC_SPZ_REVISION = "5bf2945de1a003cee07133b1e495fe9c6ffdc7e7"
_SH_DIM = {0: 0, 1: 3, 2: 8, 3: 15}


class ProviderUnavailable(RuntimeError):
    """Raised when an optional benchmark provider is not installed."""


@dataclass(frozen=True, slots=True)
class ProviderAdapter:
    """Path-based provider operations used by the large-file runner."""

    name: str
    read: Callable[[Path], Any]
    write: Callable[[Any, Path], None]
    inspect: Callable[[Path], Any] | None = None
    version: Callable[[], str | None] | None = None

    def provider_version(self) -> str | None:
        return self.version() if self.version is not None else None


@dataclass(frozen=True, slots=True)
class PreparedScene:
    """In-process fixture details kept outside the serializable artifact."""

    case_id: str
    tier: str
    path: Path
    record: Any
    logical_bytes: int
    metadata: Mapping[str, Any]
    source_path: Path | None
    provider_values: Mapping[str, Any]


def _module(name: str):
    try:
        return __import__(name)
    except Exception as exc:  # pragma: no cover - provider-dependent
        raise ProviderUnavailable(
            f"provider {name!r} is unavailable: {exc}"
        ) from exc


def _source_path(source: Any, source_id: str) -> Path:
    """Resolve a direct path or a source-catalog result without downloading."""

    if isinstance(source, (str, Path)):
        return Path(source)
    if source is None:
        raise ValueError(f"source path is required for {source_id}")
    candidate = getattr(source, "path", None)
    if candidate is not None:
        return Path(candidate)
    if isinstance(source, Mapping):
        value = source.get(source_id, source.get("path"))
        if value is not None:
            return _source_path(value, source_id)
    raise TypeError(
        f"source for {source_id} must be a Path or an acquired source with path"
    )


def _cache_dir(cache: Path | None, case_id: str, tier: str) -> Path:
    root = (
        Path(cache)
        if cache is not None
        else Path(tempfile.mkdtemp(prefix=f"sceneio-large-{case_id}-{tier}-"))
    )
    target = root / case_id / tier
    target.mkdir(parents=True, exist_ok=True)
    return target


def _artifact(
    *,
    case_id: str,
    tier: str,
    path: Path,
    logical_bytes: int,
    metadata: Mapping[str, Any],
    source_id: str | None,
    source_path: Path | None,
    acquisition_mode: str,
    derivation: Mapping[str, Any],
) -> CaseArtifact:
    encoded_bytes = (
        sum(item.stat().st_size for item in path.iterdir())
        if path.is_dir()
        else path.stat().st_size
    )
    return CaseArtifact(
        case_id=case_id,
        tier=tier,
        path=path,
        logical_bytes=int(logical_bytes),
        encoded_bytes=int(encoded_bytes),
        metadata=dict(metadata),
        source_id=source_id,
        acquisition_mode=acquisition_mode,
        derivation=dict(derivation),
    )


def _sceneio_adapter(format_id: str) -> ProviderAdapter:
    def read(path: Path):
        import sceneio

        return sceneio.read(path, format=format_id)

    def write(value: Any, path: Path) -> None:
        import sceneio

        path.parent.mkdir(parents=True, exist_ok=True)
        sceneio.write(value, path, format=format_id)

    def inspect(path: Path):
        import sceneio

        return sceneio.inspect(path, format=format_id)

    def version() -> str | None:
        import sceneio

        return getattr(sceneio, "__version__", None)

    return ProviderAdapter("sceneio", read, write, inspect, version)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        return 1.0 / (1.0 + np.exp(-values))


def _quaternion_error(left: np.ndarray, right: np.ndarray) -> float:
    a = np.asarray(left, dtype=np.float64).reshape(-1, 4)
    b = np.asarray(right, dtype=np.float64).reshape(-1, 4)
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    return float(np.max(1.0 - np.abs(np.sum(a * b, axis=1)))) if len(a) else 0.0


def _field(value: Any, *names: str) -> Any:
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    raise AttributeError(f"{type(value).__name__} has none of {names!r}")


def _canonical_spz(value: Any) -> dict[str, Any]:
    """Normalize SceneIO, Niantic, and gsply clouds to one comparison shape."""

    degree_value = None
    for name in ("sh_degree", "degree"):
        if hasattr(value, name):
            degree_value = getattr(value, name)
            break
    if degree_value is None and hasattr(value, "get_sh_degree"):
        degree_value = value.get_sh_degree()
    if degree_value is None:
        raw_sh = getattr(value, "shN", None)
        rest = 0 if raw_sh is None else int(np.asarray(raw_sh).shape[1])
        degree_value = {0: 0, 3: 1, 8: 2, 15: 3}[rest]
    degree = int(degree_value)
    if hasattr(value, "num_gaussians"):
        count = int(value.num_gaussians)
        means = np.asarray(value.means, dtype=np.float32).reshape(count, 3)
        scales = np.asarray(value.scales, dtype=np.float32).reshape(count, 3)
        quats = np.asarray(value.quaternions, dtype=np.float32).reshape(count, 4)
        opacities = np.asarray(value.opacities, dtype=np.float32).reshape(count)
        sh_dc = np.asarray(value.sh_dc, dtype=np.float32).reshape(count, 3)
        rest = _SH_DIM[degree]
        raw_rest = np.asarray(getattr(value, "sh_rest", np.empty(0)), dtype=np.float32)
        sh_rest = raw_rest.reshape(count, 3, rest) if rest else np.empty((count, 3, 0), np.float32)
        return {
            "degree": degree,
            "means": means,
            "scales": scales,
            "quats": quats,
            "opacities": opacities,
            "sh_dc": sh_dc,
            "sh_rest": sh_rest,
        }

    means_value = _field(value, "positions", "means")
    count = int(getattr(value, "num_points", len(np.asarray(means_value).reshape(-1, 3))))
    positions = np.asarray(_field(value, "positions", "means"), dtype=np.float32)
    means = positions.reshape(count, 3)
    scales = np.asarray(_field(value, "scales"), dtype=np.float32).reshape(count, 3)
    has_official_rotations = hasattr(value, "rotations")
    rotations = np.asarray(_field(value, "rotations", "quats", "quaternions"), dtype=np.float32)
    rotations = rotations.reshape(count, 4)
    # Niantic exposes XYZW; gsply's GSData contract is WXYZ.
    quats = rotations[:, [3, 0, 1, 2]] if has_official_rotations else rotations
    opacities = np.asarray(_field(value, "alphas", "opacities"), dtype=np.float32).reshape(count)
    sh_dc = np.asarray(_field(value, "colors", "sh0", "sh_dc"), dtype=np.float32).reshape(count, 3)
    rest = _SH_DIM[degree]
    raw_sh = np.asarray(getattr(value, "sh", getattr(value, "shN", np.empty(0))), dtype=np.float32)
    if rest:
        # Official Niantic/gsply layout is coefficient-major RGB; canonical is
        # channel-major, matching SceneIO's ``sh_rest`` record.
        sh_rest = raw_sh.reshape(count, rest, 3).transpose(0, 2, 1)
    else:
        sh_rest = np.empty((count, 3, 0), np.float32)
    return {
        "degree": degree,
        "means": means,
        "scales": scales,
        "quats": quats,
        "opacities": opacities,
        "sh_dc": sh_dc,
        "sh_rest": sh_rest,
    }


def compare_spz(left: Any, right: Any) -> None:
    """Compare SPZ providers using the documented quantization domains."""

    actual = _canonical_spz(left)
    expected = _canonical_spz(right)
    assert actual["degree"] == expected["degree"]
    assert actual["means"].shape == expected["means"].shape
    np.testing.assert_allclose(actual["means"], expected["means"], rtol=0.0, atol=1 / 4096 + 2e-6)
    np.testing.assert_allclose(actual["scales"], expected["scales"], rtol=0.0, atol=1 / 32 + 2e-6)
    np.testing.assert_allclose(
        _sigmoid(actual["opacities"]),
        _sigmoid(expected["opacities"]),
        rtol=0.0,
        atol=0.5 / 255 + 2e-6,
    )
    np.testing.assert_allclose(actual["sh_dc"], expected["sh_dc"], rtol=0.0, atol=0.5 / (0.15 * 255) + 2e-6)
    rest = _SH_DIM[actual["degree"]]
    if rest:
        bits = np.full(rest, 4, dtype=np.int32)
        bits[:3] = 5
        bounds = 0.5 * (2 ** (8 - bits) + 1) / 128.0 + 2e-6
        difference = np.abs(actual["sh_rest"] - expected["sh_rest"])
        assert float(np.max(difference - bounds[None, None, :])) <= 0.0
    assert _quaternion_error(actual["quats"], expected["quats"]) <= 2e-6


def _sceneio_cloud(canonical: Mapping[str, Any]):
    from sceneio import _core

    return _core.gaussian_cloud(
        np.asarray(canonical["means"], np.float32),
        np.asarray(canonical["scales"], np.float32),
        np.asarray(canonical["quats"], np.float32),
        np.asarray(canonical["opacities"], np.float32),
        np.asarray(canonical["sh_dc"], np.float32),
        np.asarray(canonical["sh_rest"], np.float32).reshape(len(canonical["means"]), -1),
    )


def _official_cloud(canonical: Mapping[str, Any]):
    spz = _module("spz")
    cloud = spz.GaussianCloud()
    degree = int(canonical["degree"])
    cloud.sh_degree = degree
    cloud.positions = np.asarray(canonical["means"], np.float32).reshape(-1)
    cloud.scales = np.asarray(canonical["scales"], np.float32).reshape(-1)
    quats = np.asarray(canonical["quats"], np.float32).reshape(-1, 4)
    cloud.rotations = quats[:, [1, 2, 3, 0]].reshape(-1)
    cloud.alphas = np.asarray(canonical["opacities"], np.float32).reshape(-1)
    cloud.colors = np.asarray(canonical["sh_dc"], np.float32).reshape(-1)
    cloud.sh = np.asarray(canonical["sh_rest"], np.float32).transpose(0, 2, 1).reshape(-1)
    return cloud


def _official_spz_read(path: Path):
    spz = _module("spz")
    options = spz.UnpackOptions()
    if hasattr(options, "to_coord") and hasattr(spz, "CoordinateSystem"):
        options.to_coord = spz.CoordinateSystem.UNSPECIFIED
    return spz.load_spz(str(path), options)


def _official_spz_write(value: Any, path: Path) -> None:
    spz = _module("spz")
    options = spz.PackOptions()
    options.version = 4
    if hasattr(options, "from_coord") and hasattr(spz, "CoordinateSystem"):
        options.from_coord = spz.CoordinateSystem.UNSPECIFIED
    path.parent.mkdir(parents=True, exist_ok=True)
    cloud = value if isinstance(value, spz.GaussianCloud) else _official_cloud(
        _canonical_spz(value)
    )
    result = spz.save_spz(cloud, options, str(path))
    if result is False:
        raise RuntimeError("official Niantic SPZ writer reported failure")


@contextlib.contextmanager
def _gsply_cpp_backend():
    gsply = _module("gsply")
    backend = getattr(gsply, "_backend", None)
    if backend is None or not hasattr(backend, "cpp") or backend.cpp() is None:
        yield gsply
        return
    previous = gsply.active_backend() if hasattr(gsply, "active_backend") else None
    gsply.use_backend("cpp")
    try:
        yield gsply
    finally:
        if previous is not None:
            gsply.use_backend(previous)


def _gsply_spz_read(path: Path):
    try:
        with _gsply_cpp_backend() as gsply:
            return gsply.read_spz(str(path))
    except Exception as exc:  # pragma: no cover - provider/version dependent
        raise ProviderUnavailable(f"gsply SPZ profile is unavailable: {exc}") from exc


def _gsply_spz_write(value: Any, path: Path) -> None:
    try:
        with _gsply_cpp_backend() as gsply:
            if isinstance(value, gsply.GSData):
                cloud = value
            else:
                canonical = _canonical_spz(value)
                arrays = {
                    "means": canonical["means"],
                    "scales": canonical["scales"],
                    "quats": canonical["quats"],
                    "opacities": canonical["opacities"],
                    "sh0": canonical["sh_dc"],
                    "shN": canonical["sh_rest"].transpose(0, 2, 1),
                    "format": "ply",
                }
                cloud = gsply.GSData.from_arrays(**arrays)
            path.parent.mkdir(parents=True, exist_ok=True)
            gsply.write_spz(str(path), cloud, version=4)
    except Exception as exc:  # pragma: no cover - provider/version dependent
        raise ProviderUnavailable(f"gsply SPZ profile is unavailable: {exc}") from exc


def _spz_adapters() -> dict[str, ProviderAdapter]:
    return {
        "sceneio": _sceneio_adapter("spz"),
        "niantic_spz": ProviderAdapter("niantic_spz", _official_spz_read, _official_spz_write),
        "gsply": ProviderAdapter("gsply", _gsply_spz_read, _gsply_spz_write),
    }


def _trimesh_scene_read(path: Path):
    trimesh = _module("trimesh")
    return trimesh.load(
        str(path),
        file_type="glb",
        process=False,
        maintain_order=True,
        force="scene",
    )


def _mesh_from_trimesh(value: Any):
    """Return one flattened trimesh object without mutating the source scene."""

    if hasattr(value, "geometry"):
        if not value.geometry:
            raise ValueError("GLB source contains no mesh geometry")
        if len(value.geometry) != 1:
            raise ValueError(
                "large GLB benchmark comparison requires exactly one mesh geometry"
            )
        # Preserve mesh-local vertices. Instance world transforms are compared
        # separately and must not be baked into the geometry a second time.
        return next(iter(value.geometry.values()))
    return value


def _rgba8_colors(mesh: Any) -> np.ndarray:
    visual = getattr(mesh, "visual", None)
    raw = getattr(visual, "vertex_colors", None)
    count = len(np.asarray(mesh.vertices))
    if raw is None:
        return np.full((count, 4), 255, dtype=np.uint8)
    array = np.asarray(raw)
    if array.ndim != 2 or array.shape[0] != count:
        raise ValueError("GLB source vertex colors have an invalid shape")
    if array.shape[1] == 3:
        array = np.column_stack((array, np.ones(count, dtype=array.dtype)))
    elif array.shape[1] != 4:
        raise ValueError("GLB source vertex colors must have 3 or 4 channels")
    if np.issubdtype(array.dtype, np.floating):
        scale = 255.0 if float(np.nanmax(array)) <= 1.0 else 1.0
        array = np.rint(np.clip(array * scale, 0.0, 255.0))
    return np.asarray(array, dtype=np.uint8)


def _canonical_mesh(value: Any) -> dict[str, Any]:
    """Canonicalize a SceneIO MeshScene or trimesh Scene for comparisons."""

    if hasattr(value, "num_primitives") and hasattr(value, "primitive_at"):
        meshes = [value.primitive_at(i) for i in range(value.num_primitives)]
        names = tuple(getattr(value, "mesh_names", ()))
        positions = []
        faces = []
        normals = []
        colors = []
        vertex_offset = 0
        has_normals = True
        has_colors = True
        for mesh in meshes:
            pos = np.asarray(mesh.positions, np.float32).reshape(-1, 3)
            offsets = np.asarray(mesh.face_offsets, np.uint64)
            indices = np.asarray(mesh.face_indices, np.uint64)
            tri = []
            for start, stop in pairwise(offsets):
                if int(stop - start) != 3:
                    raise AssertionError("GLB comparison requires triangles")
                tri.append(indices[int(start) : int(stop)])
            faces.append(np.asarray(tri, np.uint64) + vertex_offset)
            positions.append(pos)
            has_normals = mesh.has_vertex_normals() if callable(mesh.has_vertex_normals) else mesh.has_vertex_normals
            if has_normals:
                normals.append(np.asarray(mesh.vertex_normals, np.float32).reshape(-1, 3))
            else:
                has_normals = False
            has_colors_attr = mesh.has_vertex_colors() if callable(mesh.has_vertex_colors) else mesh.has_vertex_colors
            if has_colors_attr:
                colors.append(np.asarray(mesh.vertex_colors, np.uint8).reshape(-1, 4))
            else:
                has_colors = False
            vertex_offset += len(pos)
        node_meshes = np.asarray(value.node_meshes, dtype=np.int64)
        local_transforms = np.asarray(value.node_local_transforms, dtype=np.float64)
        child_offsets = np.asarray(value.node_child_offsets, dtype=np.uint64)
        children = np.asarray(value.node_children, dtype=np.uint64)
        node_names = tuple(value.node_names)
        root_offsets = np.asarray(value.scene_root_offsets, dtype=np.uint64)
        roots = np.asarray(value.scene_roots, dtype=np.uint64)
        instances: list[tuple[str, str, np.ndarray]] = []

        def visit(node: int, parent_transform: np.ndarray) -> None:
            world = parent_transform @ local_transforms[node]
            mesh_index = int(node_meshes[node])
            if mesh_index >= 0:
                mesh_name = names[mesh_index] if mesh_index < len(names) else ""
                node_name = node_names[node] if node < len(node_names) else ""
                instances.append((mesh_name, node_name, world))
            for child in children[
                int(child_offsets[node]) : int(child_offsets[node + 1])
            ]:
                visit(int(child), world)

        default_scene = int(value.default_scene)
        root_start = int(root_offsets[default_scene])
        root_stop = int(root_offsets[default_scene + 1])
        for root in roots[root_start:root_stop]:
            visit(int(root), np.eye(4, dtype=np.float64))
        return {
            "names": names,
            "positions": np.concatenate(positions) if positions else np.empty((0, 3), np.float32),
            "faces": np.concatenate(faces) if faces else np.empty((0, 3), np.uint64),
            "normals": np.concatenate(normals) if has_normals and normals else None,
            "colors": np.concatenate(colors) if has_colors and colors else None,
            "instances": tuple(
                sorted(instances, key=lambda item: (item[0], item[1]))
            ),
        }

    mesh = _mesh_from_trimesh(value)
    positions = np.asarray(mesh.vertices, np.float32).reshape(-1, 3)
    faces = np.asarray(mesh.faces, np.uint64).reshape(-1, 3)
    normals = getattr(mesh, "vertex_normals", None)
    colors = _rgba8_colors(mesh)
    geometry_names = tuple(getattr(value, "geometry", {}).keys()) if hasattr(value, "geometry") else ()
    instances = ()
    if hasattr(value, "graph"):
        items = []
        for node_name in value.graph.nodes_geometry:
            transform, mesh_name = value.graph.get(node_name)
            items.append(
                (
                    str(mesh_name),
                    str(node_name),
                    np.asarray(transform, dtype=np.float64),
                )
            )
        instances = tuple(sorted(items, key=lambda item: (item[0], item[1])))
    return {
        "names": geometry_names,
        "positions": positions,
        "faces": faces,
        "normals": None if normals is None else np.asarray(normals, np.float32).reshape(-1, 3),
        "colors": colors,
        "instances": instances,
    }


def compare_glb(left: Any, right: Any) -> None:
    """Compare mesh topology and attributes after deterministic flattening."""

    actual = _canonical_mesh(left)
    expected = _canonical_mesh(right)
    assert actual["positions"].shape == expected["positions"].shape
    np.testing.assert_array_equal(actual["faces"], expected["faces"])
    np.testing.assert_allclose(actual["positions"], expected["positions"], rtol=0.0, atol=2e-6)
    for field in ("normals", "colors"):
        if actual[field] is None or expected[field] is None:
            assert actual[field] is expected[field] is None
        elif field == "colors":
            np.testing.assert_array_equal(actual[field], expected[field])
        else:
            np.testing.assert_allclose(actual[field], expected[field], rtol=0.0, atol=2e-6)
    assert actual["names"] == expected["names"]
    assert len(actual["instances"]) == len(expected["instances"])
    for left_instance, right_instance in zip(
        actual["instances"], expected["instances"], strict=True
    ):
        assert left_instance[:2] == right_instance[:2]
        np.testing.assert_allclose(
            left_instance[2], right_instance[2], rtol=0.0, atol=1e-12
        )


def _trimesh_from_scene(value: Any):
    trimesh = _module("trimesh")
    scene = trimesh.Scene()
    names = tuple(getattr(value, "mesh_names", ()))
    node_meshes = np.asarray(value.node_meshes, dtype=np.int64)
    node_names = tuple(value.node_names)
    local_transforms = np.asarray(value.node_local_transforms, dtype=np.float64)
    for index in range(value.num_primitives):
        mesh = value.primitive_at(index)
        offsets = np.asarray(mesh.face_offsets, np.uint64)
        indices = np.asarray(mesh.face_indices, np.uint64)
        if not all(int(stop - start) == 3 for start, stop in pairwise(offsets)):
            raise ValueError("trimesh GLB adapter only accepts triangles")
        faces = indices.reshape(-1, 3)
        kwargs: dict[str, Any] = {
            "vertices": np.asarray(mesh.positions, np.float32),
            "faces": faces,
            "process": False,
        }
        has_normals = mesh.has_vertex_normals() if callable(mesh.has_vertex_normals) else mesh.has_vertex_normals
        if has_normals:
            kwargs["vertex_normals"] = np.asarray(mesh.vertex_normals, np.float32)
        has_colors = mesh.has_vertex_colors() if callable(mesh.has_vertex_colors) else mesh.has_vertex_colors
        if has_colors:
            kwargs["vertex_colors"] = np.asarray(mesh.vertex_colors, np.uint8)
        item = trimesh.Trimesh(**kwargs)
        name = names[index] if index < len(names) else f"mesh_{index}"
        matching_nodes = np.flatnonzero(node_meshes == index)
        if len(matching_nodes) != 1:
            raise ValueError(
                "trimesh GLB benchmark adapter requires one node per mesh"
            )
        node = int(matching_nodes[0])
        node_name = node_names[node] if node < len(node_names) else name
        scene.add_geometry(
            item,
            node_name=node_name,
            geom_name=name,
            transform=local_transforms[node],
        )
    return scene


def _trimesh_glb_write(value: Any, path: Path) -> None:
    trimesh = _module("trimesh")
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = value if hasattr(value, "geometry") else _trimesh_from_scene(value)
    payload = trimesh.exchange.gltf.export_glb(scene)
    path.write_bytes(payload)


def _trimesh_glb_inspect(path: Path) -> dict[str, Any]:
    value = _trimesh_scene_read(path)
    canonical = _canonical_mesh(value)
    return {
        "num_meshes": len(canonical["names"]),
        "num_vertices": len(canonical["positions"]),
        "num_faces": len(canonical["faces"]),
    }


def _glb_adapters() -> dict[str, ProviderAdapter]:
    return {
        "sceneio": _sceneio_adapter("glb"),
        "trimesh": ProviderAdapter("trimesh", _trimesh_scene_read, _trimesh_glb_write, _trimesh_glb_inspect),
    }


def _quat_xyzw_matrix(quaternion: np.ndarray) -> np.ndarray:
    x, y, z, w = np.asarray(quaternion, dtype=np.float64)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0 or not math.isfinite(norm):
        return np.eye(3, dtype=np.float64)
    x, y, z, w = (x / norm, y / norm, z / norm, w / norm)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _matrix_quat_wxyz(matrix: np.ndarray) -> np.ndarray:
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (matrix[2, 1] - matrix[1, 2]) / scale
        y = (matrix[0, 2] - matrix[2, 0]) / scale
        z = (matrix[1, 0] - matrix[0, 1]) / scale
    else:
        diagonal = np.diag(matrix)
        index = int(np.argmax(diagonal))
        if index == 0:
            scale = math.sqrt(max(0.0, 1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2])) * 2.0
            x = 0.25 * scale
            y = (matrix[0, 1] + matrix[1, 0]) / scale
            z = (matrix[0, 2] + matrix[2, 0]) / scale
            w = (matrix[2, 1] - matrix[1, 2]) / scale
        elif index == 1:
            scale = math.sqrt(max(0.0, 1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2])) * 2.0
            x = (matrix[0, 1] + matrix[1, 0]) / scale
            y = 0.25 * scale
            z = (matrix[1, 2] + matrix[2, 1]) / scale
            w = (matrix[0, 2] - matrix[2, 0]) / scale
        else:
            scale = math.sqrt(max(0.0, 1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1])) * 2.0
            x = (matrix[0, 2] + matrix[2, 0]) / scale
            y = (matrix[1, 2] + matrix[2, 1]) / scale
            z = 0.25 * scale
            w = (matrix[1, 0] - matrix[0, 1]) / scale
    quaternion = np.asarray([w, x, y, z], dtype=np.float64)
    quaternion /= np.linalg.norm(quaternion)
    return quaternion


def _tum_poses(source: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse TUM text independently, then convert C2W XYZW to COLMAP."""

    rows: list[list[float]] = []
    for line_number, raw in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 8:
            raise ValueError(
                f"TUM source line {line_number} has {len(fields)} fields; expected 8"
            )
        try:
            row = [float(field) for field in fields]
        except ValueError as exc:
            raise ValueError(f"TUM source line {line_number} is not numeric") from exc
        if not np.all(np.isfinite(row)):
            raise ValueError(f"TUM source line {line_number} contains non-finite data")
        rows.append(row)
    if not rows:
        raise ValueError("TUM source contains no poses")
    parsed = np.asarray(rows, dtype=np.float64)
    timestamps = parsed[:, 0]
    positions = parsed[:, 1:4]
    quaternions = parsed[:, 4:8]
    if len(positions) == 0:
        raise ValueError("TUM source contains no poses")
    # TUM stores camera-to-world XYZW.  COLMAP stores world-to-camera WXYZ.
    world_to_camera_q = []
    world_to_camera_t = []
    for quaternion, translation in zip(quaternions, positions, strict=True):
        camera_to_world = _quat_xyzw_matrix(quaternion)
        rotation = camera_to_world.T
        world_to_camera_q.append(_matrix_quat_wxyz(rotation))
        world_to_camera_t.append(-rotation @ translation)
    if len(world_to_camera_q) == 1:
        timestamps = np.concatenate((timestamps, timestamps + 1.0))
        world_to_camera_q.append(world_to_camera_q[0].copy())
        world_to_camera_t.append(world_to_camera_t[0].copy())
    return (
        np.asarray(timestamps, dtype=np.float64),
        np.asarray(world_to_camera_q, dtype=np.float64),
        np.asarray(world_to_camera_t, dtype=np.float64),
    )


def _residue_count(total: int, modulus: int, residue: int) -> int:
    return 0 if residue >= total else (total - 1 - residue) // modulus + 1


def _write_colmap_fixture(
    path: Path,
    timestamps: np.ndarray,
    world_to_camera_q: np.ndarray,
    world_to_camera_t: np.ndarray,
    point_count: int,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "cameras.bin").write_bytes(
        struct.pack("<QIiQQ4d", 1, 1, 1, 640, 480, 500.0, 500.0, 320.0, 240.0)
    )
    view_count = len(world_to_camera_q)
    first_counts = [_residue_count(point_count, view_count, i) for i in range(view_count)]
    observation_dtype = np.dtype(
        {
            "names": ["xy", "point3D_id"],
            "formats": [("<f8", (2,)), "<i8"],
            "offsets": [0, 16],
            "itemsize": 24,
        }
    )
    with (path / "images.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", view_count))
        for index, (quaternion, translation, timestamp) in enumerate(
            zip(world_to_camera_q, world_to_camera_t, timestamps, strict=True),
            start=1,
        ):
            first_residue = index - 1
            second_residue = (first_residue - 1) % view_count
            observation_count = first_counts[first_residue] + first_counts[second_residue]
            stream.write(
                struct.pack(
                    "<I7dI",
                    index,
                    *quaternion,
                    *translation,
                    1,
                )
            )
            stream.write(f"tum_{float(timestamp):.9f}_{index:06d}.png\0".encode())
            stream.write(struct.pack("<Q", observation_count))
            first_indices = np.arange(
                first_residue, point_count, view_count, dtype=np.int64
            )
            second_indices = np.arange(
                second_residue, point_count, view_count, dtype=np.int64
            )
            observations = np.empty(observation_count, dtype=observation_dtype)
            first_stop = len(first_indices)
            observations["xy"][:first_stop, 0] = (
                320.0 + (first_indices % 101) - 50.0
            )
            observations["xy"][:first_stop, 1] = (
                240.0 + (first_indices % 79) - 39.0
            )
            observations["point3D_id"][:first_stop] = first_indices + 1
            observations["xy"][first_stop:, 0] = (
                320.0 + (second_indices % 101) - 49.75
            )
            observations["xy"][first_stop:, 1] = (
                240.0 + (second_indices % 79) - 39.25
            )
            observations["point3D_id"][first_stop:] = second_indices + 1
            stream.write(observations.tobytes())
    point_dtype = np.dtype(
        {
            "names": ["id", "xyz", "rgb", "error", "track_length", "track"],
            "formats": [
                "<u8",
                ("<f8", (3,)),
                ("u1", (3,)),
                "<f8",
                "<u8",
                ("<u4", (4,)),
            ],
            "offsets": [0, 8, 32, 35, 43, 51],
            "itemsize": 67,
        }
    )
    with (path / "points3D.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", point_count))
        for start in range(0, point_count, 262_144):
            indices = np.arange(
                start,
                min(point_count, start + 262_144),
                dtype=np.uint64,
            )
            records = np.empty(len(indices), dtype=point_dtype)
            records["id"] = indices + 1
            records["xyz"][:, 0] = 0.1 + (indices % 97) * 0.01
            records["xyz"][:, 1] = -0.2 + (indices % 53) * 0.015
            records["xyz"][:, 2] = 4.0 + (indices % 127) * 0.02
            records["rgb"][:, 0] = indices % 256
            records["rgb"][:, 1] = (indices * 3) % 256
            records["rgb"][:, 2] = (indices * 7) % 256
            records["error"] = (indices % 13) * 0.01
            records["track_length"] = 2
            residues = indices % view_count
            second_residues = (residues + 1) % view_count
            first_indices = indices // view_count
            counts = np.asarray(first_counts, dtype=np.uint64)
            records["track"][:, 0] = residues + 1
            records["track"][:, 1] = first_indices
            records["track"][:, 2] = second_residues + 1
            records["track"][:, 3] = counts[second_residues] + first_indices
            stream.write(records.tobytes())


def _camera_model_name(camera: Any) -> str:
    """Return a stable camera-model name for both provider object models."""

    model = getattr(camera, "model", None)
    if model is None:
        model = getattr(camera, "model_name", None)
    if model is None:
        model = camera.model_id
    return str(model).rsplit(".", 1)[-1]


def _is_sceneio_colmap(value: Any) -> bool:
    """Identify the compact SceneIO record without importing the extension."""

    return hasattr(value, "image_ids") and not callable(getattr(value, "image_ids", None))


def _colmap_count(value: Any, name: str) -> int:
    raw = getattr(value, name)
    return int(raw() if callable(raw) else raw)


def _colmap_image_summary(value: Any) -> dict[str, Any]:
    """Collect complete camera/image metadata without touching point maps."""

    if _is_sceneio_colmap(value):
        image_ids = np.asarray(value.image_ids, dtype=np.uint32)
        image_order = np.argsort(image_ids)
        return {
            "image_ids": image_ids[image_order],
            "image_names": tuple(value.image_names[int(i)] for i in image_order),
            "image_camera_ids": np.asarray(value.image_camera_ids, dtype=np.uint32)[
                image_order
            ],
            "quaternions": np.asarray(value.quaternions, dtype=np.float64).reshape(-1, 4)[
                image_order
            ],
            "translations": np.asarray(value.translations, dtype=np.float64).reshape(-1, 3)[
                image_order
            ],
        }
    image_items = []
    for image_id, image in sorted(value.images.items()):
        pose = image.cam_from_world() if callable(image.cam_from_world) else image.cam_from_world
        quat_xyzw = np.asarray(pose.rotation.quat, dtype=np.float64)
        image_items.append(
            (
                int(image_id),
                image.name,
                int(image.camera_id),
                np.asarray([quat_xyzw[3], quat_xyzw[0], quat_xyzw[1], quat_xyzw[2]]),
                np.asarray(pose.translation, dtype=np.float64),
            )
        )
    return {
        "image_ids": np.asarray([item[0] for item in image_items], np.uint32),
        "image_names": tuple(item[1] for item in image_items),
        "image_camera_ids": np.asarray([item[2] for item in image_items], np.uint32),
        "quaternions": np.asarray([item[3] for item in image_items], np.float64).reshape(-1, 4),
        "translations": np.asarray([item[4] for item in image_items], np.float64).reshape(-1, 3),
    }


def _colmap_camera_summary(value: Any) -> tuple[tuple[Any, ...], ...]:
    if _is_sceneio_colmap(value):
        cameras = value.cameras
        iterator = sorted(cameras, key=lambda item: int(item.id))
        return tuple(
            (
                int(camera.id),
                _camera_model_name(camera),
                int(camera.width),
                int(camera.height),
                np.asarray(camera.params, dtype=np.float64),
            )
            for camera in iterator
        )
    return tuple(
        (
            int(camera_id),
            _camera_model_name(camera),
            int(camera.width),
            int(camera.height),
            np.asarray(camera.params, dtype=np.float64),
        )
        for camera_id, camera in sorted(value.cameras.items())
    )


def _colmap_sample_ids(left: Any, right: Any, count: int) -> np.ndarray:
    """Select deterministic point IDs without enumerating a pycolmap map."""

    sample_count = min(max(0, int(count)), COLMAP_LARGE_SAMPLE_LIMIT)
    if sample_count == 0:
        return np.empty(0, dtype=np.uint64)
    positions = np.linspace(0, count - 1, sample_count, dtype=np.int64)
    # SceneIO keeps point IDs in its compact sorted SoA.  Prefer those IDs so
    # a non-sequential external model can still be compared without asking
    # pycolmap to materialize or sort its Point3DMap.  The generated fixture
    # fallback is sequential (1..N), which is the documented large profile.
    for value in (left, right):
        if not _is_sceneio_colmap(value):
            continue
        point_ids = np.asarray(value.point3D_ids, dtype=np.uint64)
        if point_ids.size != count:
            raise AssertionError("COLMAP point count does not match point ID SoA")
        if point_ids.size > 1 and np.any(point_ids[1:] < point_ids[:-1]):
            point_ids = np.sort(point_ids)
        return point_ids[positions]
    return positions.astype(np.uint64) + np.uint64(1)


def _sceneio_point_sample(value: Any, sample_ids: np.ndarray) -> dict[str, Any]:
    point_ids = np.asarray(value.point3D_ids, dtype=np.uint64)
    xyz = np.asarray(value.xyz, dtype=np.float64).reshape(-1, 3)
    rgb = np.asarray(value.rgb, dtype=np.uint8).reshape(-1, 3)
    errors = np.asarray(value.errors, dtype=np.float64)
    if point_ids.size > 1 and np.any(point_ids[1:] < point_ids[:-1]):
        order = np.argsort(point_ids)
        point_ids = point_ids[order]
        xyz = xyz[order]
        rgb = rgb[order]
        errors = errors[order]
    positions = np.searchsorted(point_ids, sample_ids)
    if np.any(positions >= point_ids.size) or not np.array_equal(
        point_ids[positions], sample_ids
    ):
        raise AssertionError("COLMAP sample point ID is absent from the SceneIO record")
    return {
        "point_ids": point_ids[positions],
        "xyz": xyz[positions],
        "rgb": rgb[positions],
        "errors": errors[positions],
    }


def _pycolmap_point_sample(value: Any, sample_ids: np.ndarray) -> dict[str, Any]:
    points: list[Any] = []
    for point_id in sample_ids:
        identifier = int(point_id)
        if not value.exists_point3D(identifier):
            raise AssertionError(f"COLMAP sample point ID {identifier} is absent from pycolmap")
        points.append(value.point3D(identifier))
    return {
        "point_ids": np.asarray([int(point_id) for point_id in sample_ids], dtype=np.uint64),
        "xyz": np.asarray([point.xyz for point in points], dtype=np.float64).reshape(-1, 3),
        "rgb": np.asarray([point.color for point in points], dtype=np.uint8).reshape(-1, 3),
        "errors": np.asarray([point.error for point in points], dtype=np.float64),
    }


def _colmap_point_sample(value: Any, sample_ids: np.ndarray) -> dict[str, Any]:
    return (
        _sceneio_point_sample(value, sample_ids)
        if _is_sceneio_colmap(value)
        else _pycolmap_point_sample(value, sample_ids)
    )


def _sceneio_sampled_tracks(
    value: Any, sample_ids: np.ndarray
) -> tuple[dict[int, tuple[tuple[int, int], ...]], None]:
    observation_ids = np.asarray(value._observation_point3D_ids)
    offsets = np.asarray(value._observation_offsets, dtype=np.uint64)
    image_ids = np.asarray(value.image_ids, dtype=np.uint32)
    positions = np.flatnonzero(np.isin(observation_ids, sample_ids))
    image_indices = np.searchsorted(offsets, positions, side="right") - 1
    tracks = {int(point_id): [] for point_id in sample_ids}
    for position, image_index in zip(positions, image_indices, strict=True):
        point_id = int(observation_ids[position])
        tracks[point_id].append(
            (int(image_ids[image_index]), int(position - offsets[image_index]))
        )
    normalized = {point_id: tuple(sorted(entries)) for point_id, entries in tracks.items()}
    return normalized, None


def _pycolmap_sampled_tracks(
    value: Any, sample_ids: np.ndarray
) -> tuple[dict[int, tuple[tuple[int, int], ...]], dict[int, np.ndarray]]:
    tracks: dict[int, tuple[tuple[int, int], ...]] = {}
    xy: dict[int, np.ndarray] = {}
    for point_id in sample_ids:
        identifier = int(point_id)
        point = value.point3D(identifier)
        elements = sorted(
            point.track.elements,
            key=lambda element: (int(element.image_id), int(element.point2D_idx)),
        )
        tracks[identifier] = tuple(
            (int(element.image_id), int(element.point2D_idx)) for element in elements
        )
        xy[identifier] = np.asarray(
            [
                value.images[int(element.image_id)]
                .points2D[int(element.point2D_idx)]
                .xy
                for element in elements
            ],
            dtype=np.float64,
        ).reshape(-1, 2)
    return tracks, xy


def _colmap_sampled_tracks(
    value: Any, sample_ids: np.ndarray
) -> tuple[dict[int, tuple[tuple[int, int], ...]], dict[int, np.ndarray] | None]:
    if _is_sceneio_colmap(value):
        return _sceneio_sampled_tracks(value, sample_ids)
    return _pycolmap_sampled_tracks(value, sample_ids)


def _colmap_observation_count(value: Any) -> int:
    if _is_sceneio_colmap(value):
        return int(np.asarray(value._observation_point3D_ids).size)
    return int(value.compute_num_observations())


def _compare_colmap_large(left: Any, right: Any) -> dict[str, Any]:
    """Compare large COLMAP records with a bounded deterministic contract.

    Camera/image metadata remains exhaustive.  Point attributes and two-entry
    tracks are checked at evenly spaced fixture IDs (up to 4096); pycolmap is
    queried one sampled point at a time, so no all-point object list or sort is
    created.  Observation XY is compared only when both values expose it.
    """

    left_counts = {
        "num_cameras": _colmap_count(left, "num_cameras"),
        "num_images": _colmap_count(left, "num_images"),
        "num_points3D": _colmap_count(left, "num_points3D"),
    }
    right_counts = {
        "num_cameras": _colmap_count(right, "num_cameras"),
        "num_images": _colmap_count(right, "num_images"),
        "num_points3D": _colmap_count(right, "num_points3D"),
    }
    assert left_counts == right_counts
    assert _colmap_observation_count(left) == _colmap_observation_count(right)
    left_cameras = _colmap_camera_summary(left)
    right_cameras = _colmap_camera_summary(right)
    assert len(left_cameras) == len(right_cameras)
    for left_camera, right_camera in zip(left_cameras, right_cameras, strict=True):
        assert left_camera[:4] == right_camera[:4]
        np.testing.assert_allclose(left_camera[4], right_camera[4], rtol=0.0, atol=1e-12)
    left_images = _colmap_image_summary(left)
    right_images = _colmap_image_summary(right)
    for field in ("image_ids", "image_camera_ids"):
        np.testing.assert_array_equal(left_images[field], right_images[field])
    assert left_images["image_names"] == right_images["image_names"]
    np.testing.assert_allclose(
        left_images["translations"], right_images["translations"], rtol=0.0, atol=1e-10
    )
    assert _quaternion_error(left_images["quaternions"], right_images["quaternions"]) <= 1e-10
    sample_ids = _colmap_sample_ids(left, right, left_counts["num_points3D"])
    left_points = _colmap_point_sample(left, sample_ids)
    right_points = _colmap_point_sample(right, sample_ids)
    np.testing.assert_array_equal(left_points["point_ids"], right_points["point_ids"])
    np.testing.assert_allclose(left_points["xyz"], right_points["xyz"], rtol=0.0, atol=1e-10)
    np.testing.assert_array_equal(left_points["rgb"], right_points["rgb"])
    np.testing.assert_allclose(left_points["errors"], right_points["errors"], rtol=0.0, atol=1e-12)
    left_tracks, left_xy = _colmap_sampled_tracks(left, sample_ids)
    right_tracks, right_xy = _colmap_sampled_tracks(right, sample_ids)
    for point_id in sample_ids:
        identifier = int(point_id)
        assert len(left_tracks[identifier]) == 2
        assert len(right_tracks[identifier]) == 2
        assert left_tracks[identifier] == right_tracks[identifier]
        if left_xy is not None and right_xy is not None:
            np.testing.assert_allclose(
                left_xy[identifier], right_xy[identifier], rtol=0.0, atol=1e-10
            )
    return {
        "profile": "colmap:semantic-large-sampled-v1",
        "sample_count": int(sample_ids.size),
        "sample_point_ids": [int(item) for item in sample_ids],
        "total_observations": _colmap_observation_count(left),
    }


def _canonical_colmap(value: Any) -> dict[str, Any]:

    if hasattr(value, "image_ids"):
        image_ids = np.asarray(value.image_ids, dtype=np.uint32)
        image_order = np.argsort(image_ids)
        point_ids = np.asarray(value.point3D_ids, dtype=np.uint64)
        point_order = np.argsort(point_ids)
        cameras = tuple(
            (
                int(camera.id),
                _camera_model_name(camera),
                int(camera.width),
                int(camera.height),
                np.asarray(camera.params, dtype=np.float64),
            )
            for camera in sorted(value.cameras, key=lambda item: int(item.id))
        )
        return {
            "cameras": cameras,
            "image_ids": image_ids[image_order],
            "image_names": tuple(value.image_names[int(i)] for i in image_order),
            "image_camera_ids": np.asarray(value.image_camera_ids)[image_order],
            "quaternions": np.asarray(value.quaternions).reshape(-1, 4)[image_order],
            "translations": np.asarray(value.translations).reshape(-1, 3)[image_order],
            "point_ids": point_ids[point_order],
            "xyz": np.asarray(value.xyz).reshape(-1, 3)[point_order],
            "rgb": np.asarray(value.rgb).reshape(-1, 3)[point_order],
            "errors": np.asarray(value.errors)[point_order],
            # The nanobind Reconstruction intentionally exposes the compact
            # camera/point SoA only; observation/track CSR is validated by the
            # reader and retained by pycolmap for the provider-side check.
            "obs_xy": None,
            "obs_pt3d": np.asarray(
                value._observation_point3D_ids, dtype=np.uint64
            ),
            "obs_off": np.asarray(value._observation_offsets, dtype=np.uint64),
            "track": None,
            "track_off": None,
        }
    cameras = tuple(
        (
            int(camera_id),
            _camera_model_name(camera),
            int(camera.width),
            int(camera.height),
            np.asarray(camera.params, dtype=np.float64),
        )
        for camera_id, camera in sorted(value.cameras.items())
    )
    image_items = []
    observation_xy: list[np.ndarray] = []
    observation_point_ids: list[np.ndarray] = []
    observation_offsets = [0]
    for image_id, image in sorted(value.images.items()):
        pose = image.cam_from_world() if callable(image.cam_from_world) else image.cam_from_world
        quat_xyzw = np.asarray(pose.rotation.quat, dtype=np.float64)
        points2d = list(image.points2D)
        observation_xy.append(
            np.asarray([point.xy for point in points2d], dtype=np.float64).reshape(-1, 2)
        )
        observation_point_ids.append(
            np.asarray([point.point3D_id for point in points2d], dtype=np.uint64)
        )
        observation_offsets.append(observation_offsets[-1] + len(points2d))
        image_items.append(
            (
                int(image_id),
                image.name,
                int(image.camera_id),
                np.asarray([quat_xyzw[3], quat_xyzw[0], quat_xyzw[1], quat_xyzw[2]]),
                np.asarray(pose.translation, dtype=np.float64),
            )
        )
    point_items = sorted(value.points3D.items())
    return {
        "cameras": cameras,
        "image_ids": np.asarray([item[0] for item in image_items], np.uint32),
        "image_names": tuple(item[1] for item in image_items),
        "image_camera_ids": np.asarray([item[2] for item in image_items], np.uint32),
        "quaternions": np.asarray([item[3] for item in image_items], np.float64).reshape(-1, 4),
        "translations": np.asarray([item[4] for item in image_items], np.float64).reshape(-1, 3),
        "point_ids": np.asarray([item[0] for item in point_items], np.uint64),
        "xyz": np.asarray([item[1].xyz for item in point_items], np.float64).reshape(-1, 3),
        "rgb": np.asarray([item[1].color for item in point_items], np.uint8).reshape(-1, 3),
        "errors": np.asarray([item[1].error for item in point_items], np.float64),
        "obs_xy": (
            np.concatenate(observation_xy)
            if observation_xy
            else np.empty((0, 2), dtype=np.float64)
        ),
        "obs_pt3d": (
            np.concatenate(observation_point_ids)
            if observation_point_ids
            else np.empty(0, dtype=np.uint64)
        ),
        "obs_off": np.asarray(observation_offsets, dtype=np.uint64),
        "track": np.asarray(
            [[int(element.image_id), int(element.point2D_idx)] for _, point in point_items for element in point.track.elements],
            np.uint32,
        ).reshape(-1, 2),
        "track_off": np.asarray(
            [0, *np.cumsum([point.track.length() for _, point in point_items])], np.uint64
        ),
    }


def compare_colmap(left: Any, right: Any) -> dict[str, Any] | None:
    """Compare COLMAP records, using a bounded profile for large fixtures."""

    point_count = max(_colmap_count(left, "num_points3D"), _colmap_count(right, "num_points3D"))
    if point_count >= COLMAP_LARGE_POINT_THRESHOLD:
        return _compare_colmap_large(left, right)

    actual = _canonical_colmap(left)
    expected = _canonical_colmap(right)
    assert actual["cameras"]
    assert len(actual["cameras"]) == len(expected["cameras"])
    for left_camera, right_camera in zip(actual["cameras"], expected["cameras"], strict=True):
        assert left_camera[:4] == right_camera[:4]
        np.testing.assert_allclose(left_camera[4], right_camera[4], rtol=0.0, atol=1e-12)
    for field in ("image_ids", "image_camera_ids", "point_ids", "rgb"):
        np.testing.assert_array_equal(actual[field], expected[field])
    assert actual["image_names"] == expected["image_names"]
    np.testing.assert_allclose(actual["translations"], expected["translations"], rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(actual["xyz"], expected["xyz"], rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(actual["errors"], expected["errors"], rtol=0.0, atol=1e-12)
    if actual["obs_xy"] is not None and expected["obs_xy"] is not None:
        np.testing.assert_allclose(actual["obs_xy"], expected["obs_xy"], rtol=0.0, atol=1e-10)
    if actual["obs_pt3d"] is not None and expected["obs_pt3d"] is not None:
        np.testing.assert_array_equal(actual["obs_pt3d"], expected["obs_pt3d"])
        np.testing.assert_array_equal(actual["obs_off"], expected["obs_off"])
    if actual["track"] is not None and expected["track"] is not None:
        np.testing.assert_array_equal(actual["track"], expected["track"])
        np.testing.assert_array_equal(actual["track_off"], expected["track_off"])
    assert _quaternion_error(actual["quaternions"], expected["quaternions"]) <= 1e-10
    return None


def _pycolmap_read(path: Path):
    pycolmap = _module("pycolmap")
    return pycolmap.Reconstruction(str(path))


def _pycolmap_write(value: Any, path: Path) -> None:
    pycolmap = _module("pycolmap")
    if isinstance(value, pycolmap.Reconstruction):
        path.mkdir(parents=True, exist_ok=True)
        value.write_binary(str(path))
        return
    # The prepared case caches this conversion before timing.  The fallback
    # keeps the adapter useful when called directly by a smoke test.
    import sceneio

    with tempfile.TemporaryDirectory(prefix="sceneio-colmap-provider-") as directory:
        sceneio.write(value, directory, format="colmap_sparse")
        converted = pycolmap.Reconstruction(directory)
        path.mkdir(parents=True, exist_ok=True)
        converted.write_binary(str(path))


def _pycolmap_inspect(path: Path) -> dict[str, int]:
    value = _pycolmap_read(path)
    return {
        "num_cameras": int(value.num_cameras()),
        "num_images": int(value.num_images()),
        "num_points3D": int(value.num_points3D()),
    }


def _colmap_adapters() -> dict[str, ProviderAdapter]:
    return {
        "sceneio": _sceneio_adapter("colmap_sparse"),
        "pycolmap": ProviderAdapter("pycolmap", _pycolmap_read, _pycolmap_write, _pycolmap_inspect),
    }


def _repeat_spz(seed: Mapping[str, Any], target_bytes: int) -> tuple[dict[str, Any], int]:
    total_seed_bytes = sum(
        np.asarray(seed[field]).nbytes
        for field in ("means", "scales", "quats", "opacities", "sh_dc", "sh_rest")
    )
    seed_count = len(seed["means"])
    per_record = total_seed_bytes // seed_count
    count = max(1, math.ceil(target_bytes / max(1, per_record)))
    indices = np.arange(count, dtype=np.int64) % seed_count
    cycles = np.arange(count, dtype=np.int64) // seed_count
    offsets = cycles.astype(np.float32) * np.float32(0.125)
    means = np.asarray(seed["means"], np.float32)[indices].copy()
    means[:, 0] += offsets
    return (
        {
            "degree": int(seed["degree"]),
            "means": means,
            "scales": np.asarray(seed["scales"], np.float32)[indices].copy(),
            "quats": np.asarray(seed["quats"], np.float32)[indices].copy(),
            "opacities": np.asarray(seed["opacities"], np.float32)[indices].copy(),
            "sh_dc": np.asarray(seed["sh_dc"], np.float32)[indices].copy(),
            "sh_rest": np.asarray(seed["sh_rest"], np.float32)[indices].copy(),
        },
        count,
    )


def _spz_source_profile(path: Path) -> dict[str, Any]:
    profile: dict[str, Any] = {"container": "unknown", "flags": 0}
    try:
        prefix = path.read_bytes()[:2]
        if prefix == b"\x1f\x8b":
            raw = gzip.decompress(path.read_bytes())[:16]
            if len(raw) >= 16:
                profile.update({"container": "legacy", "version": int(struct.unpack_from("<I", raw, 4)[0]), "flags": raw[14]})
        else:
            raw = path.read_bytes()[:32]
            if len(raw) >= 32:
                profile.update({"container": "v4", "version": int(struct.unpack_from("<I", raw, 4)[0]), "flags": raw[14]})
    except (OSError, ValueError, struct.error):
        pass
    return profile


def _load_spz_seed(
    source: Path, *, require_official: bool = False
) -> tuple[dict[str, Any], str]:
    try:
        return _canonical_spz(_official_spz_read(source)), "niantic_spz"
    except Exception as exc:
        if require_official:
            raise ProviderUnavailable(
                f"standard SPZ fixture requires the pinned Niantic decoder: {exc}"
            ) from exc
    try:
        return _canonical_spz(_gsply_spz_read(source)), "gsply"
    except Exception:
        pass
    import sceneio

    return _canonical_spz(sceneio.read(source, format="spz")), "sceneio"


def build_spz_fixture(
    source: Path,
    *,
    tier: str = "smoke",
    cache: Path | None = None,
) -> tuple[CaseArtifact, PreparedScene]:
    """Decode the licensed racoonfamily seed, then build a flag-free v4 file."""

    source = Path(source)
    target = STANDARD_LOGICAL_BYTES if tier == "standard" else SMOKE_LOGICAL_BYTES
    seed, seed_provider = _load_spz_seed(
        source,
        require_official=tier == "standard",
    )
    canonical, count = _repeat_spz(seed, target)
    record = _sceneio_cloud(canonical)
    path = _cache_dir(cache, "spz_racoon_v4", tier) / "fixture.spz"
    common_writer = "sceneio"
    for name, writer in (
        ("niantic_spz", _official_spz_write),
        ("gsply", _gsply_spz_write),
        ("sceneio", _sceneio_adapter("spz").write),
    ):
        try:
            writer(record, path)
            _sceneio_adapter("spz").read(path)
        except Exception:
            continue
        common_writer = name
        break
    else:
        raise RuntimeError("no SPZ provider could write the derived v4 common input")
    if tier == "standard" and common_writer != "niantic_spz":
        raise ProviderUnavailable(
            "standard SPZ fixture requires the pinned Niantic reference writer"
        )
    profile = _spz_source_profile(source)
    output_profile = _spz_source_profile(path)
    if tier == "standard" and (
        output_profile.get("version") != 4 or output_profile.get("flags") != 0
    ):
        raise ValueError(
            f"standard SPZ common output is not flag-free v4: {output_profile}"
        )
    metadata = {
        "num_gaussians": count,
        "sh_degree": int(canonical["degree"]),
        "dtype": "float32",
        "source_decoder": seed_provider,
        "common_writer": common_writer,
        "source_profile": profile,
        "output_profile": output_profile,
        "coordinate_profile": "unspecified:spatial/raw-preserved",
        "coordinate_conversion": "none",
    }
    derivation = {
        "kind": "derived_fixture",
        "seed": "niantic-racoonfamily",
        "selected_seed_count": min(count, len(seed["means"])),
        "repeat_count": max(1, math.ceil(count / len(seed["means"]))),
        "translation_step": [0.125, 0.0, 0.0],
        "output_profile": (
            f"SPZ v{output_profile.get('version', 'unknown')} "
            f"flags={output_profile.get('flags', 'unknown')}"
        ),
        "unsupported_source_flags_dropped": bool(profile.get("flags", 0)),
    }
    artifact = _artifact(
        case_id="spz_racoon_v4",
        tier=tier,
        path=path,
        logical_bytes=int(sum(np.asarray(canonical[field]).nbytes for field in ("means", "scales", "quats", "opacities", "sh_dc", "sh_rest"))),
        metadata=metadata,
        source_id="niantic_racoonfamily_spz",
        source_path=source,
        acquisition_mode="derived_fixture",
        derivation=derivation,
    )
    prepared = PreparedScene(
        "spz_racoon_v4", tier, path, record, artifact.logical_bytes, metadata, source, {"sceneio": record}
    )
    return artifact, prepared


def build_glb_fixture(
    source: Path,
    *,
    tier: str = "smoke",
    cache: Path | None = None,
) -> tuple[CaseArtifact, PreparedScene]:
    """Flatten BoxVertexColors and replicate it on a deterministic 3-D grid."""

    source = Path(source)
    target = STANDARD_LOGICAL_BYTES if tier == "standard" else SMOKE_LOGICAL_BYTES
    seed = _canonical_mesh(_trimesh_scene_read(source))
    vertices = seed["positions"]
    faces = seed["faces"]
    normals = seed["normals"]
    colors = seed["colors"]
    per_copy = vertices.nbytes + faces.nbytes + (0 if normals is None else normals.nbytes) + (0 if colors is None else colors.nbytes)
    repeats = max(1, math.ceil(target / max(1, per_copy)))
    side = max(1, math.ceil(repeats ** (1 / 3)))
    repeat_indices = np.arange(repeats, dtype=np.int64)
    translations = np.column_stack(
        (
            repeat_indices % side,
            (repeat_indices // side) % side,
            repeat_indices // (side * side),
        )
    ).astype(np.float32)
    translations *= np.float32(4.0)
    positions = (
        vertices[None, :, :] + translations[:, None, :]
    ).reshape(-1, 3)
    face_offsets = (repeat_indices * len(vertices))[:, None, None]
    repeated_faces = (faces[None, :, :] + face_offsets).reshape(-1, 3)
    repeated_normals = None if normals is None else np.tile(normals, (repeats, 1))
    repeated_colors = None if colors is None else np.tile(colors, (repeats, 1))
    from sceneio import _core

    mesh = _core.mesh(
        positions,
        np.arange(0, len(repeated_faces) * 3 + 1, 3, dtype=np.uint64),
        repeated_faces.reshape(-1),
        vertex_normals=repeated_normals,
        vertex_colors=repeated_colors,
        coordinate_frame="opengl",
    )
    instance_transform = np.eye(4, dtype=np.float64)
    instance_transform[:3, 3] = [0.75, -1.25, 2.5]
    scene = _core.mesh_scene(
        [mesh],
        np.asarray([0, 1], dtype=np.uint64),
        mesh_names=["box_grid"],
        node_meshes=np.asarray([0], dtype=np.int64),
        node_child_offsets=np.asarray([0, 0], dtype=np.uint64),
        node_children=np.empty(0, dtype=np.uint64),
        node_local_transforms=instance_transform[None],
        node_names=["box_grid"],
        scene_root_offsets=np.asarray([0, 1], dtype=np.uint64),
        scene_roots=np.asarray([0], dtype=np.uint64),
        scene_names=["box_grid"],
        default_scene=0,
    )
    path = _cache_dir(cache, "glb_box_grid", tier) / "fixture.glb"
    common_writer = "trimesh"
    try:
        _trimesh_glb_write(scene, path)
        _sceneio_adapter("glb").read(path)
    except Exception:
        common_writer = "sceneio"
        _sceneio_adapter("glb").write(scene, path)
    if tier == "standard" and common_writer == "sceneio":
        raise ProviderUnavailable("standard GLB fixture requires the trimesh writer")
    logical_bytes = int(positions.nbytes + repeated_faces.nbytes + (0 if repeated_normals is None else repeated_normals.nbytes) + (0 if repeated_colors is None else repeated_colors.nbytes))
    metadata = {
        "num_vertices": len(positions),
        "num_faces": len(repeated_faces),
        "grid_repeats": repeats,
        "grid_spacing": [4.0, 4.0, 4.0],
        "instance_translation": [0.75, -1.25, 2.5],
        "color_dtype": "uint8",
        "common_writer": common_writer,
        "color_transform": "BoxVertexColors values canonicalized/quantized to RGBA8",
        "coordinate_frame": "opengl",
        "coordinate_handedness": "right",
        "up_axis": "y",
        "scale_to_meters": 1.0,
        "coordinate_conversion": "none after deterministic translations",
    }
    derivation = {
        "kind": "derived_fixture",
        "seed": "khronos-box-vertex-colors",
        "repeat_count": repeats,
        "grid_order": "x-major then y then z",
        "color_normalization": "float-or-normalized source values rounded to uint8",
    }
    artifact = _artifact(
        case_id="glb_box_grid",
        tier=tier,
        path=path,
        logical_bytes=logical_bytes,
        metadata=metadata,
        source_id="khronos_box_vertex_colors_glb",
        source_path=source,
        acquisition_mode="derived_fixture",
        derivation=derivation,
    )
    return artifact, PreparedScene("glb_box_grid", tier, path, scene, logical_bytes, metadata, source, {"sceneio": scene})


def build_colmap_fixture(
    source: Path,
    *,
    tier: str = "smoke",
    cache: Path | None = None,
) -> tuple[CaseArtifact, PreparedScene]:
    """Derive a legacy COLMAP model with two valid observations per point."""

    source = Path(source)
    target = STANDARD_LOGICAL_BYTES if tier == "standard" else SMOKE_LOGICAL_BYTES
    timestamps, quaternions, translations = _tum_poses(source)
    point_count = max(1, math.ceil(target / 115))
    path = _cache_dir(cache, "colmap_tum_tracks", tier) / "model"
    _write_colmap_fixture(path, timestamps, quaternions, translations, point_count)
    common_writer = "independent_binary_builder"
    pycolmap_value = None
    try:
        pycolmap_value = _pycolmap_read(path)
        canonical_path = path.with_name("common")
        _pycolmap_write(pycolmap_value, canonical_path)
        path = canonical_path
        common_writer = "pycolmap"
    except ProviderUnavailable:
        pass
    from sceneio import _core

    record = _core.read_colmap_sparse(str(path))
    compact_logical_bytes = int(
        np.asarray(record.xyz).nbytes
        + np.asarray(record.rgb).nbytes
        + np.asarray(record.errors).nbytes
        + np.asarray(record.quaternions).nbytes
        + np.asarray(record.translations).nbytes
        + np.asarray(record.image_ids).nbytes
        + np.asarray(record.point3D_ids).nbytes
    )
    observation_count = point_count * 2
    logical_bytes = int(
        compact_logical_bytes
        + observation_count * (2 * np.dtype(np.float64).itemsize)
        + observation_count * np.dtype(np.uint64).itemsize
        + observation_count * 2 * np.dtype(np.uint32).itemsize
        + (point_count + 1) * np.dtype(np.uint64).itemsize
        + (int(record.num_images) + 1) * np.dtype(np.uint64).itemsize
    )
    metadata = {
        "num_cameras": int(record.num_cameras),
        "num_images": int(record.num_images),
        "num_points3D": int(record.num_points3D),
        "track_length": 2,
        "common_writer": common_writer,
        "tum_pose_count": len(timestamps),
        "quaternion_order": "wxyz",
        "pose_convention": "world_to_camera",
        "observation_coordinates": "finite synthetic projections",
        "camera_frame": "opencv",
        "world_frame": "arbitrary",
        "coordinate_unit": "arbitrary",
        "projection_origin": "top_left",
        "projection_unit": "pixels",
        "tum_parser": "independent_text_v1",
    }
    derivation = {
        "kind": "derived_fixture",
        "seed": "tum-freiburg1-xyz-groundtruth",
        "point_count": point_count,
        "observations_per_point": 2,
        "point_generation": "deterministic finite points; TUM contributes poses only",
    }
    artifact = _artifact(
        case_id="colmap_tum_tracks",
        tier=tier,
        path=path,
        logical_bytes=logical_bytes,
        metadata=metadata,
        source_id="tum_freiburg1_xyz_groundtruth",
        source_path=source,
        acquisition_mode="derived_fixture",
        derivation=derivation,
    )
    provider_values: dict[str, Any] = {"sceneio": record}
    if pycolmap_value is not None:
        provider_values["pycolmap"] = pycolmap_value
    if artifact.logical_bytes < target:
        raise AssertionError(
            f"COLMAP fixture logical payload {artifact.logical_bytes} is below {target}"
        )
    return artifact, PreparedScene(
        "colmap_tum_tracks",
        tier,
        path,
        record,
        artifact.logical_bytes,
        metadata,
        source,
        provider_values,
    )


_CASE_DEFINITIONS = (
    CaseDefinition(
        id="spz_racoon_v4",
        format="spz",
        source_id="niantic_racoonfamily_spz",
        description=(
            "Niantic racoonfamily seed decoded by the pinned official SPZ "
            "provider and enlarged into a flag-free v4 translated fixture; "
            "gsply is exercised only on its overlapping v4 profile."
        ),
        standard_logical_bytes=STANDARD_LOGICAL_BYTES,
        operations=("read", "write", "cross_read", "inspect"),
        providers=("sceneio", "niantic_spz", "gsply"),
    ),
    CaseDefinition(
        id="glb_box_grid",
        format="glb",
        source_id="khronos_box_vertex_colors_glb",
        description=(
            "Khronos BoxVertexColors geometry flattened and replicated on a "
            "deterministic 3-D translation grid; source colors are explicitly "
            "canonicalized to uint8 for the SceneIO GLB contract."
        ),
        standard_logical_bytes=STANDARD_LOGICAL_BYTES,
        operations=("read", "write", "cross_read", "inspect"),
        providers=("sceneio", "trimesh"),
    ),
    CaseDefinition(
        id="colmap_tum_tracks",
        format="colmap_sparse",
        source_id="tum_freiburg1_xyz_groundtruth",
        description=(
            "TUM-derived COLMAP sparse model with world-to-camera WXYZ poses, "
            "finite generated points, and two valid observations per point."
        ),
        standard_logical_bytes=STANDARD_LOGICAL_BYTES,
        operations=("read", "write", "cross_read", "inspect", "image"),
        providers=("sceneio", "pycolmap"),
    ),
)
_CASE_BY_ID = {case.id: case for case in _CASE_DEFINITIONS}


def case_definitions() -> Mapping[str, CaseDefinition]:
    """Return immutable definitions consumed by the large benchmark runner."""

    return dict(_CASE_BY_ID)


def provider_adapters(case_id: str) -> dict[str, ProviderAdapter]:
    if case_id == "spz_racoon_v4":
        return _spz_adapters()
    if case_id == "glb_box_grid":
        return _glb_adapters()
    if case_id == "colmap_tum_tracks":
        return _colmap_adapters()
    raise KeyError(f"unknown large scene case {case_id!r}")


def inspection_diagnostic(case_id: str, value: Any) -> dict[str, Any]:
    """Normalize public provider metadata to comparable case fields."""

    if isinstance(value, Mapping):
        raw = dict(value)
    else:
        raw = dict(getattr(value, "metadata", {}))
        count = getattr(value, "count", None)
        if count is not None:
            raw.setdefault("count", int(count))
    if case_id == "spz_racoon_v4":
        return {
            "count": int(raw.get("count", raw.get("num_gaussians", 0))),
            "sh_degree": int(raw.get("sh_degree", -1)),
            "version": int(raw.get("version", -1)),
        }
    if case_id == "glb_box_grid":
        return {
            "num_meshes": int(raw.get("num_meshes", 0)),
            "num_vertices": int(raw.get("num_vertices", raw.get("count", 0))),
            "num_faces": int(raw.get("num_faces", 0)),
        }
    if case_id == "colmap_tum_tracks":
        return {
            "num_cameras": int(raw.get("num_cameras", 0)),
            "num_images": int(raw.get("num_images", raw.get("count", 0))),
            "num_points3D": int(raw.get("num_points3D", 0)),
        }
    raise KeyError(case_id)


def fixture_record(case_id: str, artifact: CaseArtifact) -> Any:
    """Load a prepared common record before entering a timed write operation."""

    return _sceneio_adapter(_CASE_BY_ID[case_id].format).read(artifact.path)


def provider_fixture(case_id: str, provider: str, artifact: CaseArtifact) -> Any:
    """Materialize a provider-native value before a timed write operation."""

    adapter = provider_adapters(case_id)[provider]
    return adapter.read(artifact.path)


def validate_common_input(
    artifact: CaseArtifact,
    *,
    sceneio_value: Any | None = None,
    provider_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Decode and semantically validate the reference-written common input."""

    case_id = artifact.case_id
    prepared_values = provider_values or {}
    if sceneio_value is None:
        sceneio_value = prepared_values.get("sceneio")
    if sceneio_value is None:
        sceneio_value = provider_fixture(case_id, "sceneio", artifact)
    providers: dict[str, str] = {}
    unavailable: dict[str, str] = {}
    contract: dict[str, Any] | None = None
    for provider in _CASE_BY_ID[case_id].providers:
        if provider == "sceneio":
            continue
        try:
            value = prepared_values.get(provider)
            if value is None:
                value = provider_fixture(case_id, provider, artifact)
        except ProviderUnavailable as exc:
            unavailable[provider] = str(exc)
            continue
        if case_id == "colmap_tum_tracks":
            contract = compare_colmap(sceneio_value, value)
            if contract is None:
                for point in value.points3D.values():
                    if int(point.track.length()) != 2:
                        raise AssertionError(
                            "COLMAP common input contains a non-two-observation track"
                        )
        else:
            compare_case(case_id, sceneio_value, value)
        providers[provider] = "ok"
    required_reference = {
        "spz_racoon_v4": "niantic_spz",
        "glb_box_grid": "trimesh",
        "colmap_tum_tracks": "pycolmap",
    }[case_id]
    required_available = required_reference in providers
    status = "pass" if providers else "unavailable"
    if artifact.tier == "standard" and not required_available:
        status = "fail"
    profile = (
        f"{case_id}:semantic-large-sampled-v1"
        if case_id == "colmap_tum_tracks"
        and int(artifact.metadata.get("num_points3D", 0)) >= COLMAP_LARGE_POINT_THRESHOLD
        else f"{case_id}:semantic-v1"
    )
    result = {
        "status": status,
        "providers": providers,
        "unavailable": unavailable,
        "required_reference": required_reference,
        "required_reference_available": required_available,
        "profile": profile,
    }
    if contract is not None:
        result.update(
            {
                "sample_count": contract["sample_count"],
                "sample_point_ids": contract["sample_point_ids"],
                "total_observations": contract["total_observations"],
            }
        )
    return result


def _nonempty_output(path: Path | None) -> bool:
    if path is None:
        return False
    if path.is_file():
        return path.stat().st_size > 0
    return path.is_dir() and any(
        item.stat().st_size > 0 for item in path.rglob("*") if item.is_file()
    )


def _semantic_profile(case_id: str, artifact: CaseArtifact | None = None) -> str:
    if (
        case_id == "colmap_tum_tracks"
        and artifact is not None
        and int(artifact.metadata.get("num_points3D", 0)) >= COLMAP_LARGE_POINT_THRESHOLD
    ):
        return f"{case_id}:semantic-large-sampled-v1"
    return f"{case_id}:semantic-v1"


def cross_read_matrix(
    artifact: CaseArtifact, outputs: Mapping[str, Path | None]
) -> list[dict[str, Any]]:
    """Read every writer output through every provider's ordinary reader."""

    case_id = artifact.case_id
    providers = _CASE_BY_ID[case_id].providers
    adapters = provider_adapters(case_id)
    rows: list[dict[str, Any]] = []
    for reader in providers:
        expected = None
        try:
            # Use the same independent reader for the common input and every
            # writer output. This makes the matrix directional and lets the
            # pycolmap lanes compare observations/tracks that SceneIO's public
            # record view does not expose directly.  Large fixtures use the
            # bounded sampled contract rather than materializing every point.
            expected = adapters[reader].read(artifact.path)
        except Exception as exc:
            for writer in providers:
                rows.append(
                    {
                        "case_id": case_id,
                        "kind": "provider_output_cross_read",
                        "writer_provider": writer,
                        "reader_provider": reader,
                        "profile": _semantic_profile(case_id, artifact),
                        "status": "fail",
                        "error": (
                            "common input reader failed: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    }
                )
            continue
        try:
            for writer in providers:
                output = outputs.get(writer)
                row = {
                    "case_id": case_id,
                    "kind": "provider_output_cross_read",
                    "writer_provider": writer,
                    "reader_provider": reader,
                    "profile": _semantic_profile(case_id, artifact),
                }
                if not _nonempty_output(output):
                    rows.append(
                        {
                            **row,
                            "status": "fail",
                            "error": "writer output is missing or empty",
                        }
                    )
                    continue
                actual = None
                try:
                    actual = adapters[reader].read(output)
                    compare_case(case_id, expected, actual)
                    rows.append({**row, "status": "pass"})
                except Exception as exc:
                    rows.append(
                        {
                            **row,
                            "status": "fail",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                finally:
                    del actual
                    gc.collect()
        finally:
            del expected
            gc.collect()
    return rows


def _sceneio_image_metadata(value: Any, image_id: int) -> dict[str, Any]:
    image_ids = np.asarray(value.image_ids, dtype=np.uint32)
    positions = np.flatnonzero(image_ids == np.uint32(image_id))
    if positions.size != 1:
        raise AssertionError(f"SceneIO record does not contain exactly one image {image_id}")
    position = int(positions[0])
    return {
        "image_id": int(image_ids[position]),
        "name": str(value.image_names[position]),
        "camera_id": int(np.asarray(value.image_camera_ids, dtype=np.uint32)[position]),
        "quaternion": np.asarray(value.quaternions, dtype=np.float64).reshape(-1, 4)[position],
        "translation": np.asarray(value.translations, dtype=np.float64).reshape(-1, 3)[position],
    }


def _pycolmap_image_metadata(value: Any, image_id: int) -> dict[str, Any]:
    image = value.images[int(image_id)]
    pose = image.cam_from_world() if callable(image.cam_from_world) else image.cam_from_world
    quat_xyzw = np.asarray(pose.rotation.quat, dtype=np.float64)
    return {
        "image_id": int(image.image_id),
        "name": str(image.name),
        "camera_id": int(image.camera_id),
        "quaternion": np.asarray(
            [quat_xyzw[3], quat_xyzw[0], quat_xyzw[1], quat_xyzw[2]], dtype=np.float64
        ),
        "translation": np.asarray(pose.translation, dtype=np.float64),
    }


def partial_read_check(artifact: CaseArtifact) -> dict[str, Any]:
    """Verify COLMAP single-image reads against full SceneIO and pycolmap data."""

    if artifact.case_id != "colmap_tum_tracks":
        return {"status": "pass", "profile": "not_applicable"}
    import sceneio

    image_id = 1
    if int(artifact.metadata.get("num_points3D", 0)) >= COLMAP_LARGE_POINT_THRESHOLD:
        full_value = sceneio.read(artifact.path, format="colmap_sparse")
        selected_value = sceneio.read_partial(
            artifact.path,
            format="colmap_sparse",
            image_id=image_id,
        )
        oracle = _pycolmap_read(artifact.path)
        full = _sceneio_image_metadata(full_value, image_id)
        selected = _sceneio_image_metadata(selected_value, image_id)
        expected = _pycolmap_image_metadata(oracle, image_id)
        equal = (
            int(selected_value.num_images) == 1
            and selected["image_id"] == image_id
            and selected["name"] == full["name"] == expected["name"]
            and selected["camera_id"] == full["camera_id"] == expected["camera_id"]
            and _quaternion_error(
                selected["quaternion"][None, :], full["quaternion"][None, :]
            )
            <= 1e-10
            and _quaternion_error(
                selected["quaternion"][None, :], expected["quaternion"][None, :]
            )
            <= 1e-10
            and np.allclose(
                selected["translation"], full["translation"], rtol=0.0, atol=1e-10
            )
            and np.allclose(
                selected["translation"], expected["translation"], rtol=0.0, atol=1e-10
            )
        )
        return {
            "status": "pass" if equal else "fail",
            "profile": "sceneio_single_image_large-sampled-no-point-canonicalization",
            "image_id": image_id,
        }
    full = _canonical_colmap(sceneio.read(artifact.path, format="colmap_sparse"))
    selected = _canonical_colmap(
        sceneio.read_partial(
            artifact.path,
            format="colmap_sparse",
            image_id=image_id,
        )
    )
    oracle = _canonical_colmap(_pycolmap_read(artifact.path))
    full_index = int(np.flatnonzero(full["image_ids"] == image_id)[0])
    oracle_index = int(np.flatnonzero(oracle["image_ids"] == image_id)[0])
    equal = (
        selected["image_ids"].tolist() == [image_id]
        and selected["image_names"] == (full["image_names"][full_index],)
        and selected["image_names"] == (oracle["image_names"][oracle_index],)
        and int(selected["image_camera_ids"][0])
        == int(full["image_camera_ids"][full_index])
        == int(oracle["image_camera_ids"][oracle_index])
        and np.allclose(
            selected["translations"][0],
            full["translations"][full_index],
            rtol=0.0,
            atol=1e-10,
        )
        and np.allclose(
            selected["translations"][0],
            oracle["translations"][oracle_index],
            rtol=0.0,
            atol=1e-10,
        )
        and _quaternion_error(
            selected["quaternions"],
            full["quaternions"][full_index : full_index + 1],
        )
        <= 1e-10
        and _quaternion_error(
            selected["quaternions"],
            oracle["quaternions"][oracle_index : oracle_index + 1],
        )
        <= 1e-10
    )
    return {
        "status": "pass" if equal else "fail",
        "profile": "sceneio_single_image_equals_full_and_pycolmap",
        "image_id": image_id,
    }


def prepare_case(
    case_id: str,
    tier: str = "smoke",
    cache: Path | None = None,
    sources: Any = None,
) -> CaseArtifact:
    """Build one smoke or standard artifact from an injected source path."""

    if tier not in {"smoke", "standard"}:
        raise ValueError("tier must be 'smoke' or 'standard'")
    case = _CASE_BY_ID.get(case_id)
    if case is None:
        raise KeyError(f"unknown large scene case {case_id!r}")
    source = _source_path(sources, case.source_id or case_id)
    if case_id == "spz_racoon_v4":
        artifact, prepared = build_spz_fixture(source, tier=tier, cache=cache)
    elif case_id == "glb_box_grid":
        artifact, prepared = build_glb_fixture(source, tier=tier, cache=cache)
    else:
        artifact, prepared = build_colmap_fixture(source, tier=tier, cache=cache)
    if case_id == "colmap_tum_tracks":
        validation = validate_common_input(
            artifact,
            sceneio_value=prepared.record,
            provider_values=prepared.provider_values,
        )
    else:
        # SPZ and GLB writers may quantize or normalize their common output;
        # validate the decoded file rather than the pre-write source record.
        validation = validate_common_input(artifact)
    if tier == "standard" and validation["status"] != "pass":
        raise ProviderUnavailable(
            f"standard fixture has no available reference validator: {validation}"
        )
    return artifact


def compare_case(case_or_artifact: str | CaseArtifact, left: Any, right: Any = None) -> Any:
    """Apply the format-specific semantic comparison profile."""

    if isinstance(case_or_artifact, CaseArtifact):
        case_id = case_or_artifact.case_id
        if right is None:
            raise TypeError("compare_case(artifact, left_path, right_path) needs two paths")
        left_path = Path(left)
        right_path = Path(right)
        left_value = _sceneio_adapter(_CASE_BY_ID[case_id].format).read(left_path)
        oracle_name = None
        right_value = None
        for candidate in _CASE_BY_ID[case_id].providers:
            if candidate == "sceneio":
                continue
            try:
                right_value = provider_adapters(case_id)[candidate].read(right_path)
            except ProviderUnavailable:
                continue
            oracle_name = candidate
            break
        if oracle_name is None:
            raise ProviderUnavailable(f"no comparison provider is available for {case_id}")
        compare_case(case_id, left_value, right_value)
        return {
            "status": "pass",
            "case_id": case_id,
            "profile": _semantic_profile(case_id, case_or_artifact),
            "providers": ("sceneio", oracle_name),
        }
    case_id = case_or_artifact
    if case_id == "spz_racoon_v4":
        compare_spz(left, right)
    elif case_id == "glb_box_grid":
        compare_glb(left, right)
    elif case_id == "colmap_tum_tracks":
        return compare_colmap(left, right)
    else:
        raise KeyError(f"unknown large scene case {case_id!r}")


def execute_case(request: Mapping[str, Any]) -> Any:
    """Execute one un-timed worker operation from a serializable request."""

    case_id = str(request["case_id"])
    provider = str(request["provider"])
    operation = str(request["operation"])
    path = Path(request["path"])
    adapter = provider_adapters(case_id)[provider]
    if operation in {"read", "cross_read"}:
        return adapter.read(path)
    if operation == "inspect":
        if adapter.inspect is not None:
            return adapter.inspect(path)
        return _sceneio_adapter(_CASE_BY_ID[case_id].format).inspect(path)
    if operation == "write":
        output = Path(request["output_path"])
        artifact = CaseArtifact.from_dict(dict(request["artifact"]))
        adapter.write(provider_fixture(case_id, provider, artifact), output)
        return output
    if operation == "image" and case_id == "colmap_tum_tracks":
        image_id = int(request.get("image_id", 1))
        import sceneio

        return sceneio.read_partial(path, format="colmap_sparse", image_id=image_id)
    raise ValueError(f"unsupported {case_id}/{provider}/{operation} operation")


# Compatibility aliases used by small local runners and focused tests.
CASE_DEFINITIONS = dict(_CASE_BY_ID)
scene_cases = case_definitions
build_scene_cases = case_definitions


__all__ = [
    "CASE_DEFINITIONS",
    "COLMAP_LARGE_POINT_THRESHOLD",
    "COLMAP_LARGE_SAMPLE_LIMIT",
    "NIANTIC_SPZ_REVISION",
    "SMOKE_LOGICAL_BYTES",
    "STANDARD_LOGICAL_BYTES",
    "ProviderAdapter",
    "ProviderUnavailable",
    "build_colmap_fixture",
    "build_glb_fixture",
    "build_scene_cases",
    "build_spz_fixture",
    "case_definitions",
    "compare_case",
    "compare_colmap",
    "compare_glb",
    "compare_spz",
    "cross_read_matrix",
    "execute_case",
    "fixture_record",
    "inspection_diagnostic",
    "partial_read_check",
    "prepare_case",
    "provider_adapters",
    "provider_fixture",
    "scene_cases",
    "validate_common_input",
]
