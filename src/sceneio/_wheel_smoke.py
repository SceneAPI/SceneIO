"""Private numpy-only smoke exercised against each built wheel.

Keep this module free of test-only dependencies: cibuildwheel installs only the
wheel and NumPy before invoking it on Windows, Linux, and macOS.
"""

from __future__ import annotations

import gc
import importlib.util
import json
import mmap
import shutil
import sqlite3
import struct
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from types import MappingProxyType

import numpy as np

import sceneio
from sceneio import _core
from sceneio.coordinates import CoordinateConvention, coordinate_convention
from sceneio.io import registry

_PARTIAL_SELECTORS = (
    "window",
    "points",
    "faces",
    "mesh_id",
    "primitive_id",
    "states",
    "frames",
    "image_id",
    "pair",
    "tensors",
    "slices",
)

# Every supported operation is exercised by the installed smoke today. This
# typed empty mapping is the only place a future, reviewed property-specific
# exemption may be added; the validator rejects stale or incomplete entries.
_SMOKE_EXEMPTIONS: Mapping[tuple[str, str], Mapping[str, str]] = (
    MappingProxyType({})
)


def _record_observation(
    observations: dict[str, set[str]],
    format_id: str,
    property_name: str,
) -> None:
    if format_id not in observations:
        raise AssertionError(
            f"wheel smoke observed non-built-in codec {format_id!r}"
        )
    observations[format_id].add(property_name)


def _known_coordinate_values_agree(
    actual: CoordinateConvention,
    expected: CoordinateConvention,
) -> bool:
    omitted = {None, "unknown", "not_applicable", "file_declared"}
    for item in fields(CoordinateConvention):
        if item.name == "name":
            continue
        value = getattr(actual, item.name)
        if value in omitted:
            continue
        if value != getattr(expected, item.name):
            return False
    return True


def _validate_coordinates(format_id: str, result: object, inspection: object) -> None:
    contract = registry.REGISTRY[format_id].capabilities().coordinates
    inspected = inspection.coordinates
    recorded = coordinate_convention(result)
    if contract.status == "fixed":
        if inspected != contract.decoded:
            raise AssertionError(
                f"{format_id}: inspection coordinate contract differs from registry"
            )
        if recorded is not None and not _known_coordinate_values_agree(
            recorded,
            contract.decoded,
        ):
            raise AssertionError(
                f"{format_id}: decoded record contradicts its coordinate contract"
            )
    elif contract.status == "file_declared":
        if inspected is None:
            raise AssertionError(
                f"{format_id}: file-declared coordinates were not inspected"
            )
    elif contract.status == "unspecified":
        if inspected != sceneio.UNKNOWN_COORDINATES:
            raise AssertionError(
                f"{format_id}: unspecified coordinates were presented as known"
            )
    elif contract.status == "not_applicable":
        if inspected is not None or recorded is not None:
            raise AssertionError(
                f"{format_id}: non-coordinate data acquired a coordinate contract"
            )
    else:  # pragma: no cover - frozen public vocabulary
        raise AssertionError(f"{format_id}: unknown coordinate status")


@contextmanager
def _observe_public_io() -> Iterator[dict[str, set[str]]]:
    definitions = tuple(registry.BUILTIN_DEFINITIONS)
    observations = {codec.id: set() for codec in definitions}
    capabilities = {codec.id: codec.capabilities() for codec in definitions}
    original_write = sceneio.write
    original_read = sceneio.read
    original_inspect = sceneio.inspect
    original_partial = sceneio.read_partial
    original_detect = sceneio.detect

    def resolve(path, explicit_format) -> str:
        return explicit_format or original_detect(path)

    def observed_write(obj, path, **kwargs):
        result = original_write(obj, path, **kwargs)
        format_id = resolve(path, kwargs.get("format"))
        _record_observation(observations, format_id, "write")
        if capabilities[format_id].streams_write:
            _record_observation(observations, format_id, "stream_write")
        return result

    def observed_read(path, **kwargs):
        result = original_read(path, **kwargs)
        format_id = resolve(path, kwargs.get("format"))
        _record_observation(observations, format_id, "read")
        inspection = original_inspect(path, format=format_id)
        _validate_coordinates(format_id, result, inspection)
        _record_observation(observations, format_id, "coordinates")
        if capabilities[format_id].streams_read:
            _record_observation(observations, format_id, "stream_read")
        return result

    def observed_inspect(path, **kwargs):
        result = original_inspect(path, **kwargs)
        format_id = resolve(path, kwargs.get("format"))
        _record_observation(observations, format_id, "inspect")
        return result

    def observed_partial(path, **kwargs):
        result = original_partial(path, **kwargs)
        format_id = resolve(path, kwargs.get("format"))
        selectors = tuple(
            selector
            for selector in _PARTIAL_SELECTORS
            if kwargs.get(selector) is not None
        )
        if len(selectors) != 1:
            raise AssertionError(
                f"wheel smoke partial call for {format_id!r} has selectors "
                f"{selectors!r}"
            )
        _record_observation(
            observations,
            format_id,
            f"selector:{selectors[0]}",
        )
        return result

    sceneio.write = observed_write
    sceneio.read = observed_read
    sceneio.inspect = observed_inspect
    sceneio.read_partial = observed_partial
    try:
        yield observations
    finally:
        sceneio.write = original_write
        sceneio.read = original_read
        sceneio.inspect = original_inspect
        sceneio.read_partial = original_partial


def _expected_smoke_properties(codec) -> set[str]:
    capabilities = codec.capabilities()
    if not capabilities.available:
        return set()
    expected = {"coordinates", "read", "inspect"}
    if capabilities.streams_read:
        expected.add("stream_read")
    if capabilities.can_write:
        expected.add("write")
    if capabilities.streams_write:
        expected.add("stream_write")
    expected.update(
        f"selector:{selector}" for selector in capabilities.partial_selectors
    )
    return expected


def _validate_smoke_observations(
    observations: Mapping[str, set[str]],
) -> None:
    definitions = tuple(registry.BUILTIN_DEFINITIONS)
    built_in_ids = tuple(codec.id for codec in definitions)
    if built_in_ids != tuple(registry.REGISTRY):
        raise AssertionError(
            "installed built-in definitions and registry order differ"
        )
    if built_in_ids != tuple(sceneio.codecs()):
        raise AssertionError(
            "installed public codec ids differ from built-in definitions"
        )
    if built_in_ids != tuple(observations):
        raise AssertionError("wheel-smoke observation ids are incomplete")

    expected_exemptions = set()
    failures = []
    for codec in definitions:
        expected = _expected_smoke_properties(codec)
        observed = observations[codec.id]
        for property_name in sorted(expected - observed):
            exemption_key = (codec.id, property_name)
            if exemption_key in _SMOKE_EXEMPTIONS:
                expected_exemptions.add(exemption_key)
            else:
                failures.append(f"{codec.id}:{property_name}")
        unexpected = sorted(observed - expected)
        failures.extend(f"{codec.id}:unexpected:{item}" for item in unexpected)

    if set(_SMOKE_EXEMPTIONS) != expected_exemptions:
        failures.append("stale wheel-smoke exemption")
    for key, exemption in _SMOKE_EXEMPTIONS.items():
        if set(exemption) != {"reason", "verification"} or not all(
            isinstance(value, str) and value.strip()
            for value in exemption.values()
        ):
            failures.append(f"invalid wheel-smoke exemption {key!r}")
    if failures:
        raise AssertionError(
            "installed-wheel smoke coverage is incomplete: "
            + ", ".join(failures)
        )


def _pfm_and_typed_depth(root: Path, values: np.ndarray) -> None:
    encoded = _core.write_pfm(values)
    assert np.array_equal(_core.read_pfm(memoryview(encoded)), values)
    path = root / "values.pfm"
    sceneio.write(values, path, format="pfm")
    assert path.read_bytes() == bytes(encoded)
    assert np.array_equal(sceneio.read(path), values)
    info = sceneio.inspect(path)
    assert info.shape == values.shape
    assert info.dtype == "float32"
    partial = sceneio.read_partial(path, window=(1, 3, 1, 4))
    assert np.array_equal(partial, values[1:3, 1:4])
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        owned = _core.read_pfm(mapped)
    path.unlink()
    assert np.array_equal(owned, values)

    pfm_encoding = sceneio.DepthEncoding("meters", 1.0, "none")
    pfm_depth = _core.depth_map(values)
    typed_pfm = root / "typed.pfm"
    sceneio.write_depth(pfm_depth, typed_pfm, encoding=pfm_encoding)
    assert np.array_equal(
        sceneio.read_depth(typed_pfm, encoding=pfm_encoding).depth,
        values,
    )
    assert (
        sceneio.inspect_depth(typed_pfm, encoding=pfm_encoding).metadata[
            "header_scale"
        ]
        == -1.0
    )
    assert isinstance(sceneio.read(typed_pfm), np.ndarray)

    png_encoding = sceneio.DepthEncoding("millimeters", 0.001, "zero")
    png_depth = _core.depth_map(
        values,
        unit="millimeters",
        invalid_policy="zero",
    )
    typed_png = root / "typed.png"
    sceneio.write_depth(png_depth, typed_png, encoding=png_encoding)
    assert np.array_equal(
        sceneio.read_depth(typed_png, encoding=png_encoding).depth,
        values,
    )
    png_info = sceneio.inspect_depth(typed_png, encoding=png_encoding)
    assert png_info.dtype == "float32"
    assert png_info.metadata["stored_dtype"] == "uint16"
    assert isinstance(sceneio.read(typed_png), _core.Image)

    exr_encoding = sceneio.DepthEncoding("meters", 1.0, "none", "Z")
    typed_exr = root / "typed.exr"
    sceneio.write_depth(pfm_depth, typed_exr, encoding=exr_encoding)
    assert np.array_equal(
        sceneio.read_depth(typed_exr, encoding=exr_encoding).depth,
        values,
    )
    exr_info = sceneio.inspect_depth(typed_exr, encoding=exr_encoding)
    assert exr_info.dtype == "float32"
    assert exr_info.metadata["channel_name"] == "Z"
    assert isinstance(sceneio.read(typed_exr), _core.Image)


def _mapped_safetensors(root: Path, values: np.ndarray) -> None:
    path = root / "values.safetensors"
    sceneio.write({"x": values}, path)
    record = sceneio.read(path)
    assert np.array_equal(record["x"], values)
    assert not record["x"].flags.writeable
    assert sceneio.inspect(path).arrays[0].shape == values.shape
    named = sceneio.read_partial(path, tensors=("x",))
    assert np.array_equal(named["x"], values)
    selected = sceneio.read_partial(path, slices={"x": (1, 3)})
    assert np.array_equal(selected["x"], values[1:3])
    del record, named, selected
    gc.collect()
    path.unlink()


def _numpy_archives(root: Path, values: np.ndarray) -> None:
    npy = root / "values.npy"
    sceneio.write(values, npy, format="npy")
    assert np.array_equal(sceneio.read(npy), values)
    npy_info = sceneio.inspect(npy)
    assert npy_info.shape == values.shape
    assert npy_info.dtype == "float32"

    arrays = {"x": values, "indices": np.arange(5, dtype=np.int64)}
    npz = root / "values.npz"
    sceneio.write(arrays, npz, format="npz")
    decoded = sceneio.read(npz)
    assert np.array_equal(decoded["x"], values)
    assert np.array_equal(decoded["indices"], arrays["indices"])
    npz_info = sceneio.inspect(npz)
    assert tuple(item.name for item in npz_info.arrays) == ("x", "indices")


def _array_formats(root: Path) -> None:
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    _pfm_and_typed_depth(root, values)
    _numpy_archives(root, values)
    _mapped_safetensors(root, values)


def _las_waveform(root: Path) -> None:
    descriptor_payload = struct.pack("<BBIIdd", 8, 0, 4, 1000, 2.0, -1.0)
    descriptor = struct.pack(
        "<H16sHH32s",
        0,
        b"LASF_Spec\0\0\0\0\0\0\0",
        100,
        len(descriptor_payload),
        b"waveform descriptor".ljust(32, b"\0"),
    ) + descriptor_payload
    packet_payload = b"\x01\x02\x03\x04"
    packet = struct.pack(
        "<H16sHQ32s",
        0,
        b"LASF_Spec\0\0\0\0\0\0\0",
        65535,
        len(packet_payload),
        b"waveform packets".ljust(32, b"\0"),
    ) + packet_payload
    records = np.zeros((2, 59), np.uint8)
    for row in range(2):
        struct.pack_into(
            "<BQIffff",
            records[row],
            30,
            1,
            60,
            4,
            0.25 + row,
            1.0,
            2.0,
            3.0,
        )
    sidecar = _core.las_waveform_sidecar(
        9,
        4,
        2,
        records,
        np.frombuffer(descriptor, np.uint8),
        np.frombuffer(packet, np.uint8),
    )
    cloud = _core.point_cloud(
        np.array([[0, 0, 0], [0.01, 0.02, 0.03]], np.float32),
        intensity=np.array([10, 11], np.float32),
        intensity_range="u16",
        las_waveform=sidecar,
    )
    assert isinstance(sidecar, _core.LasWaveformSidecar)
    path = root / "waveform.las"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "las"
    decoded = sceneio.read(path)
    assert decoded.has_las_waveform
    assert decoded.las_waveform.point_format == 9
    assert decoded.las_waveform.waveform_packet_record.tobytes() == packet
    assert sceneio.inspect(path).metadata["has_waveform"]
    selected = sceneio.read_partial(path, points=(1, 2))
    assert selected.positions.shape == (1, 3)
    assert selected.las_waveform.point_records.shape == (1, 59)


def _laz(root: Path) -> None:
    positions = np.array(
        [[0.0, 0.0, 0.0], [1.25, -2.5, 3.75], [4.0, 5.0, 6.0]],
        np.float32,
    )
    colors = np.array(
        [[1, 2, 3], [1000, 2000, 3000], [65533, 65534, 65535]],
        np.uint16,
    )
    cloud = _core.point_cloud(
        positions,
        colors16=colors,
        intensity=np.array([0, 1234, 65535], np.float32),
        intensity_range="u16",
        origin=np.array([500_000.0, 4_000_000.0, 100.0]),
    )
    path = root / "points.laz"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "laz"
    decoded = sceneio.read(path)
    np.testing.assert_allclose(decoded.positions, positions, atol=0.0005)
    np.testing.assert_array_equal(decoded.colors16, colors)
    assert sceneio.inspect(path).metadata["point_format"] == 2
    selected = sceneio.read_partial(path, points=(1, 3))
    np.testing.assert_array_equal(
        selected.colors16,
        colors[1:3],
    )


def _compressed_ply(root: Path) -> None:
    count = 5
    cloud = _core.gaussian_cloud(
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 8,
        np.zeros((count, 3), np.float32),
        np.tile(np.array([[1.0, 0.0, 0.0, 0.0]], np.float32), (count, 1)),
        np.linspace(-1, 1, count, dtype=np.float32),
        np.zeros((count, 3), np.float32),
        np.arange(count * 9, dtype=np.float32).reshape(count, 9) / 32,
    )
    path = root / "smoke.compressed.ply"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "compressed_ply"
    decoded = sceneio.read(path)
    assert isinstance(decoded, _core.GaussianCloud)
    assert decoded.num_gaussians == count
    assert decoded.sh_degree == 1
    assert sceneio.inspect(path).metadata["num_chunks"] == 1
    selected = sceneio.read_partial(path, points=(1, 4))
    assert np.array_equal(selected.means, decoded.means[1:4])
    retired = path.with_suffix(".retired")
    path.rename(retired)
    retired.unlink()
    assert decoded.num_gaussians == count
    assert selected.num_gaussians == 3


def _sog(root: Path) -> None:
    count = 7
    cloud = _core.gaussian_cloud(
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 8,
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 32,
        np.tile(np.array([[1.0, 0.1, 0.2, 0.3]], np.float32), (count, 1)),
        np.linspace(-2, 2, count, dtype=np.float32),
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 64,
        np.arange(count * 24, dtype=np.float32).reshape(count, 24) / 128,
    )
    bundle = root / "smoke.sog"
    sceneio.write(cloud, bundle)
    assert sceneio.detect(bundle) == "sog"
    decoded = sceneio.read(bundle)
    assert decoded.num_gaussians == count
    assert decoded.sh_degree == 2
    assert sceneio.inspect(bundle).metadata["packaging"] == "zip"
    selected = sceneio.read_partial(bundle, points=(2, 6))
    assert np.array_equal(selected.means, decoded.means[2:6])
    retired_bundle = bundle.with_suffix(".retired")
    bundle.rename(retired_bundle)
    retired_bundle.unlink()
    assert decoded.num_gaussians == count
    assert selected.num_gaussians == 4

    directory = root / "unbundled-sog"
    sceneio.write(cloud, directory)
    assert sceneio.detect(directory) == "sog"
    assert sceneio.inspect(directory).metadata["packaging"] == "directory"
    directory_decoded = sceneio.read(directory)
    assert np.array_equal(directory_decoded.means, decoded.means)
    retired_directory = root / "retired-sog"
    directory.rename(retired_directory)
    shutil.rmtree(retired_directory)
    assert directory_decoded.num_gaussians == count


def _ksplat(root: Path) -> None:
    count = 9
    cloud = _core.gaussian_cloud(
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 8,
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 32,
        np.tile(np.array([[1.0, 0.1, 0.2, 0.3]], np.float32), (count, 1)),
        np.linspace(-2, 2, count, dtype=np.float32),
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 64,
        np.arange(count * 24, dtype=np.float32).reshape(count, 24) / 128,
    )
    path = root / "smoke.ksplat"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "ksplat"
    decoded = sceneio.read(path)
    assert decoded.num_gaussians == count
    assert decoded.sh_degree == 2
    assert sceneio.inspect(path).metadata["compression_level"] == 1
    selected = sceneio.read_partial(path, points=(2, 7))
    assert np.array_equal(selected.means, decoded.means[2:7])
    retired = path.with_suffix(".retired")
    path.rename(retired)
    retired.unlink()
    assert decoded.num_gaussians == count
    assert selected.num_gaussians == 5


def _gaussian_ply(root: Path) -> None:
    count = 6
    cloud = _core.gaussian_cloud(
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 8,
        np.zeros((count, 3), np.float32),
        np.tile(np.array([[1.0, 0.0, 0.0, 0.0]], np.float32), (count, 1)),
        np.linspace(-1, 1, count, dtype=np.float32),
        np.zeros((count, 3), np.float32),
    )
    path = root / "smoke-gaussian.ply"
    sceneio.write(cloud, path, format="gaussian_ply")
    assert sceneio.detect(path) == "gaussian_ply"
    assert sceneio.inspect(path).count == count
    decoded = sceneio.read(path)
    assert decoded.num_gaussians == count
    selected = sceneio.read_partial(path, points=(1, 5))
    assert np.array_equal(selected.means, decoded.means[1:5])
    retired = path.with_suffix(".retired")
    path.rename(retired)
    retired.unlink()
    assert decoded.num_gaussians == count
    assert selected.num_gaussians == 4


def _spz(root: Path) -> None:
    count = 6
    cloud = _core.gaussian_cloud(
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 8,
        np.zeros((count, 3), np.float32),
        np.tile(np.array([[1.0, 0.0, 0.0, 0.0]], np.float32), (count, 1)),
        np.linspace(-1, 1, count, dtype=np.float32),
        np.zeros((count, 3), np.float32),
    )
    path = root / "smoke.spz"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "spz"
    assert sceneio.inspect(path).count == count
    decoded = sceneio.read(path)
    assert decoded.num_gaussians == count
    assert sceneio.capabilities("spz").partial_selectors == ()
    retired = path.with_suffix(".retired")
    path.rename(retired)
    retired.unlink()
    assert decoded.num_gaussians == count


def _splat(root: Path) -> None:
    count = 6
    cloud = _core.gaussian_cloud(
        np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 8,
        np.zeros((count, 3), np.float32),
        np.tile(np.array([[1.0, 0.0, 0.0, 0.0]], np.float32), (count, 1)),
        np.linspace(-1, 1, count, dtype=np.float32),
        np.zeros((count, 3), np.float32),
    )
    path = root / "smoke.splat"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "splat"
    assert sceneio.inspect(path).count == count
    decoded = sceneio.read(path)
    assert decoded.num_gaussians == count
    selected = sceneio.read_partial(path, points=(1, 5))
    assert np.array_equal(selected.means, decoded.means[1:5])
    retired = path.with_suffix(".retired")
    path.rename(retired)
    retired.unlink()
    assert decoded.num_gaussians == count
    assert selected.num_gaussians == 4


def _splats(root: Path) -> None:
    _gaussian_ply(root)
    _compressed_ply(root)
    _sog(root)
    _ksplat(root)
    _spz(root)
    _splat(root)


def _mesh_ply(root: Path) -> None:
    mesh = _core.mesh(
        np.array(
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1]],
            np.float32,
        ),
        np.array([0, 4, 7], np.uint64),
        np.array([0, 1, 2, 3, 0, 3, 4], np.uint64),
        corner_uvs=np.arange(14, dtype=np.float32).reshape(7, 2) / 14,
        primitive_offsets=np.array([0, 1, 2], np.uint64),
        primitive_materials=np.array([2, -1], np.int32),
        coordinate_frame="opengl",
        scale_to_meters=0.01,
    )
    assert sceneio.Mesh is _core.Mesh
    path = root / "mesh.ply"
    sceneio.write(mesh, path)
    assert sceneio.detect(path) == "ply_mesh"
    decoded = sceneio.read(path)
    assert np.array_equal(decoded.positions, mesh.positions)
    assert np.array_equal(decoded.face_offsets, mesh.face_offsets)
    assert np.array_equal(decoded.face_indices, mesh.face_indices)
    assert np.array_equal(decoded.corner_uvs, mesh.corner_uvs)
    assert np.array_equal(decoded.primitive_offsets, mesh.primitive_offsets)
    assert np.array_equal(
        decoded.primitive_materials, mesh.primitive_materials
    )
    inspected = sceneio.inspect(path)
    assert inspected.metadata["num_vertices"] == 5
    assert inspected.metadata["num_faces"] == 2
    selected = sceneio.read_partial(path, faces=(1, 2))
    assert np.array_equal(selected.positions, mesh.positions)
    assert np.array_equal(selected.face_offsets, [0, 3])
    assert np.array_equal(selected.face_indices, mesh.face_indices[4:7])
    assert np.array_equal(selected.corner_uvs, mesh.corner_uvs[4:7])
    assert np.array_equal(selected.primitive_offsets, [0, 1])
    assert np.array_equal(selected.primitive_materials, [-1])


def _obj_mtl(root: Path) -> None:
    materials = _core.material_set(
        ["matte"],
        base_colors=np.array([[0.25, 0.5, 0.75, 1]], np.float32),
        texture_materials=np.array([0], np.uint64),
        texture_semantics=["base_color"],
        texture_paths=["albedo.png"],
    )
    mesh = _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        vertex_normals=np.array([[0, 0, 1]] * 3, np.float32),
        vertex_uvs=np.array([[0, 0], [1, 0], [0, 1]], np.float32),
        vertex_colors=np.array(
            [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]],
            np.uint8,
        ),
        face_smoothing_groups=np.array([3], np.uint32),
        primitive_offsets=np.array([0, 1], np.uint64),
        primitive_materials=np.array([0], np.int32),
        primitive_object_names=["triangle"],
        primitive_group_names=["front"],
        materials=materials,
    )
    assert sceneio.MaterialSet is _core.MaterialSet
    path = root / "mesh.obj"
    sceneio.write(mesh, path)
    assert (root / "mesh.mtl").is_file()
    assert sceneio.detect(path) == "obj"
    decoded = sceneio.read(path)
    assert np.array_equal(decoded.positions, mesh.positions)
    assert np.array_equal(decoded.face_indices, mesh.face_indices)
    assert np.array_equal(decoded.vertex_normals, mesh.vertex_normals)
    assert np.array_equal(decoded.vertex_uvs, mesh.vertex_uvs)
    assert np.array_equal(decoded.vertex_colors, mesh.vertex_colors)
    assert decoded.primitive_object_names == ["triangle"]
    assert decoded.primitive_group_names == ["front"]
    assert decoded.materials.names == ["matte"]
    assert decoded.materials.texture_paths == ["albedo.png"]
    inspected = sceneio.inspect(path)
    assert inspected.metadata["num_faces"] == 1
    assert inspected.metadata["num_materials"] == 1
    assert inspected.metadata["num_textures"] == 1


def _stl_off(root: Path) -> None:
    soup = _core.mesh(
        np.array(
            [
                [0, 0, 0],
                [1, 0, 0],
                [0, 1, 0],
                [0, 0, 1],
                [1, 0, 1],
                [0, 1, 1],
            ],
            np.float32,
        ),
        np.array([0, 3, 6], np.uint64),
        np.arange(6, dtype=np.uint64),
        corner_normals=np.array(
            [[0, 0, 1]] * 3 + [[0, 0, -1]] * 3,
            np.float32,
        ),
    )
    stl = root / "mesh.stl"
    sceneio.write(soup, stl)
    assert sceneio.detect(stl) == "stl"
    assert np.array_equal(sceneio.read(stl).positions, soup.positions)
    assert sceneio.inspect(stl).metadata["encoding"] == "binary"
    assert np.array_equal(
        sceneio.read_partial(stl, faces=(1, 2)).positions,
        soup.positions[3:6],
    )

    polygon = _core.mesh(
        np.array(
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            np.float32,
        ),
        np.array([0, 4], np.uint64),
        np.array([0, 1, 2, 3], np.uint64),
        vertex_normals=np.array([[0, 0, 1]] * 4, np.float32),
        vertex_uvs=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32),
        vertex_colors=np.array(
            [
                [255, 0, 0, 255],
                [0, 255, 0, 255],
                [0, 0, 255, 255],
                [255, 255, 255, 255],
            ],
            np.uint8,
        ),
    )
    off = root / "mesh.off"
    sceneio.write(polygon, off)
    assert sceneio.detect(off) == "off"
    decoded = sceneio.read(off)
    assert np.array_equal(decoded.face_offsets, polygon.face_offsets)
    assert np.array_equal(decoded.vertex_colors, polygon.vertex_colors)
    assert sceneio.inspect(off).metadata["variant"] == "STCNOFF"
    assert np.array_equal(
        sceneio.read_partial(off, faces=(0, 1)).face_indices,
        polygon.face_indices,
    )


def _gltf_glb(root: Path) -> None:
    primitive = _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        vertex_normals=np.array([[0, 0, 1]] * 3, np.float32),
        vertex_uvs=np.array([[0, 0], [1, 0], [0, 1]], np.float32),
        coordinate_frame="opengl",
    )
    mesh_scene = _core.mesh_scene(
        [primitive],
        np.array([0, 1], np.uint64),
        mesh_names=["triangle"],
        node_meshes=np.array([0], np.int64),
        node_child_offsets=np.array([0, 0], np.uint64),
        node_children=np.array([], np.uint64),
        node_local_transforms=np.eye(4, dtype=np.float64)[None],
        node_names=["node"],
        scene_root_offsets=np.array([0, 1], np.uint64),
        scene_roots=np.array([0], np.uint64),
        scene_names=["main"],
        default_scene=0,
    )
    assert sceneio.MeshScene is _core.MeshScene
    for suffix, format_id in ((".gltf", "gltf"), (".glb", "glb")):
        path = root / f"mesh{suffix}"
        sceneio.write(mesh_scene, path)
        assert sceneio.detect(path) == format_id
        decoded = sceneio.read(path)
        assert decoded.mesh_names == ["triangle"]
        assert np.array_equal(
            decoded.primitive_at(0).positions, primitive.positions
        )
        assert sceneio.inspect(path).metadata["num_nodes"] == 1
        selected = sceneio.read_partial(path, primitive_id=0)
        assert selected.num_primitives == 1
        assert np.array_equal(
            selected.primitive_at(0).face_indices,
            primitive.face_indices,
        )
        selected_mesh = sceneio.read_partial(path, mesh_id=0)
        assert selected_mesh.num_primitives == 1
        assert np.array_equal(
            selected_mesh.primitive_at(0).positions,
            primitive.positions,
        )


def _point_depth_and_flow(root: Path, values: np.ndarray) -> None:
    points = root / "points.pts"
    sceneio.write(_core.point_cloud(values[:, :3]), points)
    assert np.array_equal(sceneio.read(points).positions, values[:, :3])
    assert sceneio.inspect(points).count == 3
    selected = sceneio.read_partial(points, points=(1, 3))
    assert np.array_equal(selected.positions, values[1:3, :3])

    xyz = root / "points.xyz"
    sceneio.write(_core.point_cloud(values[:, :3]), xyz, format="xyz")
    assert np.array_equal(sceneio.read(xyz).positions, values[:, :3])
    assert sceneio.inspect(xyz).count == 3
    selected = sceneio.read_partial(xyz, points=(1, 3))
    assert np.array_equal(selected.positions, values[1:3, :3])

    ply = root / "points.ply"
    ply_record = _core.point_cloud(
        values[:, :3],
        colors=np.arange(9, dtype=np.uint8).reshape(3, 3),
    )
    sceneio.write(ply_record, ply, format="ply")
    assert sceneio.detect(ply) == "ply"
    assert np.array_equal(sceneio.read(ply).positions, values[:, :3])
    assert np.array_equal(
        sceneio.read_partial(ply, points=(1, 3)).colors,
        ply_record.colors[1:3],
    )
    assert sceneio.inspect(ply).count == 3
    ply.write_bytes(_core.write_ply(ply_record, "binary_big_endian"))
    assert sceneio.detect(ply) == "ply"
    assert np.array_equal(sceneio.read(ply).positions, values[:, :3])
    assert np.array_equal(
        sceneio.read_partial(ply, points=(1, 3)).colors,
        ply_record.colors[1:3],
    )
    assert sceneio.inspect(ply).metadata["byte_order"] == "big"

    pcd = root / "points.pcd"
    pcd_record = _core.point_cloud(
        values[:, :3],
        colors=np.arange(9, dtype=np.uint8).reshape(3, 3),
        width=1,
        height=3,
        viewpoint=np.asarray(
            [1, 2, 3, 1, 0, 0, 0],
            dtype=np.float64,
        ),
    )
    sceneio.write(pcd_record, pcd, format="pcd")
    assert sceneio.detect(pcd) == "pcd"
    pcd_decoded = sceneio.read(pcd)
    assert np.array_equal(pcd_decoded.positions, values[:, :3])
    assert np.array_equal(pcd_decoded.colors, pcd_record.colors)
    assert (pcd_decoded.width, pcd_decoded.height) == (1, 3)
    assert pcd_decoded.viewpoint == pcd_record.viewpoint
    assert sceneio.inspect(pcd).count == 3

    pcd.write_bytes(_core.write_pcd(pcd_record, "binary_compressed"))
    assert sceneio.detect(pcd) == "pcd"
    pcd_decoded = sceneio.read(pcd)
    assert np.array_equal(pcd_decoded.positions, values[:, :3])
    assert np.array_equal(pcd_decoded.colors, pcd_record.colors)
    assert (pcd_decoded.width, pcd_decoded.height) == (1, 3)
    assert pcd_decoded.viewpoint == pcd_record.viewpoint
    assert sceneio.inspect(pcd).metadata["storage"] == "binary_compressed"

    pcd.write_bytes(_core.write_pcd(pcd_record, "binary"))
    assert np.array_equal(
        sceneio.read_partial(pcd, points=(1, 3)).colors,
        pcd_record.colors[1:3],
    )

    depth_values = np.arange(20, dtype=np.float32).reshape(4, 5)
    depth = _core.depth_map(
        depth_values,
        unit="unknown",
        invalid_policy="zero",
    )
    dmb = root / "depth.dmb"
    sceneio.write(depth, dmb)
    assert np.array_equal(sceneio.read(dmb).depth, depth_values)
    assert sceneio.inspect(dmb).shape == (4, 5)
    window = sceneio.read_partial(dmb, window=(1, 4, 2, 5))
    assert np.array_equal(window.depth, depth_values[1:4, 2:5])

    flow = _core.flow_field(np.zeros((2, 3, 2), np.float32))
    assert sceneio.FlowField is _core.FlowField
    assert flow.vectors.shape == (2, 3, 2)
    assert flow.component_order == "uv"
    flo = root / "flow.flo"
    sceneio.write(flow.vectors, flo, format="flo")
    generic_flow = sceneio.read(flo)
    assert np.array_equal(generic_flow, flow.vectors)
    assert sceneio.inspect(flo).shape == (2, 3, 2)
    selected_flow = sceneio.read_partial(
        flo,
        window=(0, 2, 1, 3),
    )
    assert np.array_equal(selected_flow, flow.vectors[:, 1:3])
    decoded = sceneio.read_flow(flo)
    assert np.array_equal(decoded.vectors, flow.vectors)
    assert sceneio.inspect_flow(flo).metadata["unit"] == "pixels"


def _point_formats(root: Path) -> None:
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    _point_depth_and_flow(root, values)


def _bal(root: Path) -> None:
    bal_bytes = (
        b"1 1 1\n"
        b"0 0 10.5 20.25\n"
        b"0\n0\n0\n1\n2\n3\n800\n0.5\n0.25\n"
        b"1.5\n-2.5\n3.5\n"
    )
    reconstruction = _core.read_bal(bal_bytes)
    bal = root / "problem.bal"
    sceneio.write(reconstruction, bal)
    assert sceneio.inspect(bal).metadata["num_observations"] == 1
    assert sceneio.read(bal).num_points3D == 1


def _raster_images(root: Path) -> None:
    pixels = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
    image = _core.image(pixels, color_space="srgb")
    for format_id, suffix in (
        ("netpbm", ".ppm"),
        ("png", ".png"),
        ("jpeg", ".jpg"),
        ("bmp", ".bmp"),
        ("tga", ".tga"),
        ("webp", ".webp"),
    ):
        path = root / f"image{suffix}"
        sceneio.write(image, path, format=format_id)
        decoded = sceneio.read(path, format=format_id)
        assert decoded.pixels.shape == pixels.shape
        if format_id in {"bmp", "tga"}:
            assert np.array_equal(decoded.pixels, pixels)
        assert sceneio.inspect(path).shape == (3, 4, 3)
        if format_id in {"netpbm", "webp"}:
            selected = sceneio.read_partial(
                path,
                format=format_id,
                window=(1, 3, 1, 4),
            )
            assert selected.pixels.shape == (2, 3, 3)

    linear_pixels = np.arange(36, dtype=np.float32).reshape(3, 4, 3) / 35
    linear_image = _core.image(linear_pixels, color_space="linear")
    for format_id, suffix in (("hdr", ".hdr"), ("exr", ".exr")):
        path = root / f"image{suffix}"
        sceneio.write(linear_image, path, format=format_id)
        decoded = sceneio.read(path, format=format_id)
        assert decoded.pixels.shape == linear_pixels.shape
        info = sceneio.inspect(path, format=format_id)
        assert info.shape == (3, 4, 3)
        assert info.dtype == "float32"


def _remove_smoke_artifact(path: Path) -> None:
    if path.is_dir():
        for member in path.iterdir():
            member.unlink()
        path.rmdir()
    else:
        path.unlink()


def _reconstruction_formats(root: Path) -> None:
    reconstruction = _core.read_nvm(
        b"NVM_V3\n1\n"
        b"a.jpg 800 1 0 0 0 1 2 3 0 0\n"
        b"1\n"
        b"1.5 -2.5 3.5 10 20 30 1 0 0 4.5 -5.5\n"
        b"0\n"
    )
    transforms_json = _core.read_transforms_json(
        b'{"camera_model":"PINHOLE","fl_x":500,"fl_y":510,'
        b'"cx":320,"cy":240,"w":640,"h":480,"frames":['
        b'{"file_path":"a.png","transform_matrix":'
        b"[[1,0,0,1],[0,1,0,2],[0,0,1,3],[0,0,0,1]]}]}"
    )
    tum = _core.read_tum(b"0 1 2 3 0 0 0 1\n")
    kitti = _core.read_kitti(b"1 0 0 1 0 1 0 2 0 0 1 3\n")
    cases = (
        ("colmap_sparse", root / "colmap-binary", reconstruction),
        ("transforms_json", root / "transforms.json", transforms_json),
        ("tum", root / "poses.tum", tum),
        ("kitti", root / "poses.kitti", kitti),
        ("colmap_sparse_txt", root / "colmap-text", reconstruction),
        ("bundler", root / "bundle.out", reconstruction),
        ("nvm", root / "model.nvm", reconstruction),
        ("openmvg", root / "sfm_data.json", reconstruction),
    )
    explicit_only = {"tum", "kitti"}
    directory_formats = {"colmap_sparse", "colmap_sparse_txt"}
    for format_id, path, source in cases:
        if format_id in directory_formats:
            path.mkdir()
        sceneio.write(source, path, format=format_id)
        if format_id in explicit_only:
            try:
                sceneio.detect(path)
            except sceneio.FormatError:
                pass
            else:
                raise AssertionError(f"{format_id} must remain explicit-only")
        else:
            assert sceneio.detect(path) == format_id
        inspected = sceneio.inspect(path, format=format_id)
        decoded = sceneio.read(path, format=format_id)
        assert inspected.format == format_id
        if format_id in directory_formats:
            selected = sceneio.read_partial(
                path,
                format=format_id,
                image_id=int(decoded.image_ids[0]),
            )
            assert selected.num_images == 1
        _remove_smoke_artifact(path)
        if isinstance(decoded, _core.PosedViewSet):
            assert decoded.num_views == 1
        else:
            assert decoded.num_images == 1


def _state_trajectory(root: Path) -> None:
    timestamps = np.array(
        [1_403_636_580_000_000_000, 1_403_636_580_005_000_000],
        dtype=np.int64,
    )
    positions = np.arange(6, dtype=np.float64).reshape(2, 3)
    quaternions = np.array(
        [[1.0, 0.0, 0.0, 0.0], [0.5, 0.5, 0.5, 0.5]],
        dtype=np.float64,
    )
    zeros = np.zeros((2, 3), dtype=np.float64)
    trajectory = _core.state_trajectory(
        timestamps,
        positions,
        quaternions,
        zeros,
        zeros,
        zeros,
    )
    path = root / "euroc.csv"
    sceneio.write(trajectory, path, format="euroc_state")
    assert sceneio.detect(path) == "euroc_state"
    decoded = sceneio.read(path)
    assert np.array_equal(decoded.timestamps_ns, timestamps)
    assert np.array_equal(decoded.positions, positions)
    assert sceneio.inspect(path).count == 2
    selected = sceneio.read_partial(path, states=(1, 2))
    assert np.array_equal(selected.timestamps_ns, timestamps[1:2])


def _camera_calibration(root: Path) -> None:
    matrix = np.array(
        [[[500.0, 0.0, 320.0], [0.0, 510.0, 240.0], [0.0, 0.0, 1.0]]]
    )
    rig = _core.camera_rig(
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500.0, 510.0, 320.0, 240.0]),
        ["plumb_bob"],
        np.array([0, 4], np.uint64),
        np.array([0.1, -0.2, 0.01, 0.02]),
        np.array([[1.0, 0.0, 0.0, 0.0]]),
        np.zeros((1, 3)),
        has_extrinsics=np.zeros(1, np.uint8),
        camera_matrices=matrix,
    )
    assert sceneio.CameraRig is _core.CameraRig
    imu_calibration = _core.imu_calibration(
        0,
        "imu0",
        "/imu0",
        np.array([1.0, 0.0, 0.0, 0.0]),
        np.zeros(3),
        nominal_rate_hz=200.0,
        time_offset_ns=0,
    )
    imu_sequence = _core.imu_sequence(
        0,
        np.array([0, 5_000_000], np.int64),
        np.zeros((2, 3)),
        np.zeros((2, 3)),
    )
    assert sceneio.ImuCalibration is _core.ImuCalibration
    assert sceneio.ImuSequence is _core.ImuSequence
    assert imu_calibration.time_offset_ns == 0
    assert imu_sequence.angular_velocities.shape == (2, 3)
    for format_id in ("opencv_yaml", "opencv_xml"):
        path = root / format_id
        sceneio.write(rig, path, format=format_id)
        assert sceneio.detect(path) == format_id
        decoded = sceneio.read(path)
        assert np.array_equal(decoded.camera_matrices, matrix)
        assert sceneio.inspect(path).count == 1

    ros_rig = _core.camera_rig(
        np.array([0], np.uint32),
        np.array([[640, 480]], np.uint64),
        ["pinhole"],
        np.array([0, 4], np.uint64),
        np.array([500.0, 510.0, 320.0, 240.0]),
        ["plumb_bob"],
        np.array([0, 4], np.uint64),
        np.array([0.1, -0.2, 0.01, 0.02]),
        np.array([[1.0, 0.0, 0.0, 0.0]]),
        np.zeros((1, 3)),
        has_extrinsics=np.zeros(1, np.uint8),
        camera_matrices=matrix,
        rectification_matrices=np.eye(3)[None],
        projection_matrices=np.array(
            [
                [
                    [500.0, 0.0, 320.0, 0.0],
                    [0.0, 510.0, 240.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                ]
            ]
        ),
        binning=np.zeros((1, 2), np.uint32),
        roi=np.zeros((1, 4), np.uint32),
        has_operational=np.ones(1, np.uint8),
    )
    ros = root / "ros-camera-info"
    sceneio.write(ros_rig, ros, format="ros_camera_info")
    assert sceneio.detect(ros) == "ros_camera_info"
    assert np.array_equal(sceneio.read(ros).projection_matrices, ros_rig.projection_matrices)
    assert sceneio.inspect(ros).count == 1

    kalibr = root / "kalibr"
    kalibr.write_bytes(
        b"cam0:\n"
        b"  camera_model: pinhole\n"
        b"  intrinsics: [500, 510, 320, 240]\n"
        b"  distortion_model: radtan\n"
        b"  distortion_coeffs: [0.1, -0.2, 0.01, 0.02]\n"
        b"  resolution: [640, 480]\n"
        b"  rostopic: /cam0/image_raw\n"
        b"  T_cam_imu:\n"
        b"  - [1, 0, 0, 0]\n"
        b"  - [0, 1, 0, 0]\n"
        b"  - [0, 0, 1, 0]\n"
        b"  - [0, 0, 0, 1]\n"
    )
    assert sceneio.detect(kalibr) == "kalibr"
    decoded = sceneio.read(kalibr)
    assert decoded.reference_frame == "imu"
    assert sceneio.inspect(kalibr).count == 1
    sceneio.write(decoded, root / "kalibr-copy", format="kalibr")


def _pose_graph(root: Path) -> None:
    information = np.tile(np.eye(6), (1, 1, 1))
    graph = _core.pose_graph(
        np.array([3, 9], np.int64),
        np.array([[0.0, 0, 0], [1.0, 0, 0]]),
        np.array([[0.0, 0.0, 0.0, 1.0]] * 2),
        np.array([[3, 9]], np.int64),
        np.array([[1.0, 0, 0]]),
        np.array([[0.0, 0.0, 0.0, 1.0]]),
        information,
        fixed=np.array([1, 0], np.uint8),
    )
    assert sceneio.PoseGraph is _core.PoseGraph
    path = root / "graph.g2o"
    sceneio.write(graph, path)
    assert sceneio.detect(path) == "g2o"
    decoded = sceneio.read(path)
    assert np.array_equal(decoded.node_ids, graph.node_ids)
    assert np.array_equal(decoded.edge_endpoints, graph.edge_endpoints)
    assert np.array_equal(
        decoded.information_matrices, graph.information_matrices
    )
    inspected = sceneio.inspect(path)
    assert inspected.count == 2
    assert inspected.metadata["num_edges"] == 1
    assert inspected.metadata["num_fixed_nodes"] == 1


def _colmap_database(root: Path) -> None:
    camera = _core.camera(
        5,
        1,
        640,
        480,
        np.array([500.0, 501.0, 320.0, 240.0]),
    )
    features = [
        _core.feature_set(
            np.array([[10.0, 20.0], [30.0, 40.0]], np.float32),
            np.arange(8, dtype=np.uint8).reshape(2, 4) + image_id,
            image_id=image_id,
            image_name=f"{image_id}.jpg",
            camera_id=5,
            image_size=(640, 480),
            extractor_type=0,
        )
        for image_id in (2, 11)
    ]
    graph = _core.match_graph(
        np.array([[2, 11]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[0, 1]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[0, 1]], np.uint32),
        configs=np.array([2], np.int32),
        fundamental_matrices=np.eye(3)[None],
        fundamental_present=np.array([1], np.uint8),
        geometry_present=np.array([1], np.uint8),
        match_present=np.array([1], np.uint8),
    )
    database = _core.colmap_database(
        [camera],
        features,
        graph,
        prior_focal_length=np.array([1], np.uint8),
    )
    assert sceneio.FeatureSet is _core.FeatureSet
    assert sceneio.MatchGraph is _core.MatchGraph
    assert sceneio.ColmapDatabase is _core.ColmapDatabase
    assert sceneio.ColmapDatabaseConversionReport.__name__ == (
        "ColmapDatabaseConversionReport"
    )
    assert sceneio.ColmapMarkerSet is _core.ColmapMarkerSet
    assert sceneio.ColmapMaxxSchemaInfo is _core.ColmapMaxxSchemaInfo
    assert sceneio.ColmapRigFrameSet is _core.ColmapRigFrameSet
    assert sceneio.ColmapPosePriorSet is _core.ColmapPosePriorSet
    assert sceneio.ColmapVideoMetadataSet is _core.ColmapVideoMetadataSet
    path = root / "database.db"
    sceneio.write(database, path)
    assert sceneio.detect(path) == "colmap_db"
    decoded = sceneio.read(path)
    assert decoded.num_images == 2
    assert decoded.match_graph.image_pairs.tolist() == [[2, 11]]
    selected_image = sceneio.read_partial(path, image_id=11)
    assert selected_image.image_name == "11.jpg"
    selected_pair = sceneio.read_partial(path, pair=(11, 2))
    assert selected_pair.matches.tolist() == [[0, 1]]
    inspected = sceneio.inspect(path)
    assert inspected.metadata["num_cameras"] == 1
    assert inspected.metadata["num_matches"] == 1

    maxx_path = root / "maxx.db"
    connection = sqlite3.connect(maxx_path)
    try:
        connection.executescript(_core._colmap_db_profile_schema("maxx-v1"))
        connection.execute("PRAGMA application_id=1296128088")
        connection.execute("PRAGMA user_version=3140003")
        connection.execute(
            "INSERT INTO maxx_schema_info VALUES(1,1,'3.14.0',?)",
            ("de15b08a2dba98b55d6ddfb7cedac147838afbb4",),
        )
        connection.execute(
            "INSERT INTO cameras VALUES(5,0,640,480,?,1)",
            (struct.pack("<3d", 500.0, 320.0, 240.0),),
        )
        connection.execute(
            "INSERT INTO images VALUES(2,'2.jpg',5,17)"
        )
        connection.execute(
            "INSERT INTO keypoints VALUES(2,1,2,?)",
            (struct.pack("<2f", 10.0, 20.0),),
        )
        connection.execute(
            "INSERT INTO descriptors VALUES(2,-1,'plugin',3,2,1,8,?)",
            (struct.pack("<2f", 0.25, -0.5),),
        )
        connection.execute(
            "INSERT INTO keypoint_colors VALUES(2,1,3,?)",
            (bytes((1, 2, 3)),),
        )
        connection.execute(
            "INSERT INTO image_qualities VALUES(2,0.75)"
        )
        connection.execute(
            "INSERT INTO pose_priors VALUES"
            "(1,2,5,0,NULL,NULL,NULL,-1,?,NULL,NULL)",
            (struct.pack("<4d", 0.0, 0.0, 0.0, 1.0),),
        )
        connection.execute(
            "INSERT INTO markers VALUES"
            "(7,'target',3,NULL,NULL,-1,1)"
        )
        connection.execute(
            "INSERT INTO marker_projections VALUES"
            "(7,2,10.0,20.0,2.0,1,4294967295)"
        )
        connection.execute(
            "INSERT INTO videos VALUES"
            "(3,'source',NULL,NULL,640,480,1,30.0,0.033,NULL,NULL)"
        )
        connection.execute(
            "INSERT INTO video_frames VALUES(3,2,0,0.0,19)"
        )
        pair_id = 2 * 2_147_483_647 + 3
        connection.execute(
            "INSERT INTO pair_provenance VALUES(?,65,NULL)",
            (pair_id,),
        )
        connection.commit()
    finally:
        connection.close()

    maxx = sceneio.read(maxx_path)
    assert maxx.maxx_schema_info.producer_version == "3.14.0"
    assert maxx.feature(2).descriptors.dtype == np.float32
    assert maxx.feature(2).keypoint_colors.tolist() == [[1, 2, 3]]
    assert maxx.markers.marker_types.tolist() == [3]
    assert maxx.video_metadata.video_frame_indices.tolist() == [0]
    assert maxx.match_graph.source_flags.tolist() == [65]
    assert sceneio.read_partial(maxx_path, image_id=2).quality == 0.75
    assert sceneio.read_partial(maxx_path, pair=(3, 2)).source_flags.tolist() == [65]
    assert sceneio.inspect(maxx_path).metadata["num_markers"] == 1
    report = sceneio.colmap_database_conversion_report(
        maxx, profile="maxx-v1"
    )
    assert report.writable
    assert not report.incompatibilities
    maxx_copy = root / "maxx-copy.db"
    sceneio.write(maxx, maxx_copy)
    copied_maxx = sceneio.read(maxx_copy)
    assert copied_maxx.profile == "maxx-v1"
    assert copied_maxx.feature(2).descriptors.tobytes() == (
        maxx.feature(2).descriptors.tobytes()
    )
    assert copied_maxx.markers.labels == ["target"]


def _hdf5_formats(root: Path) -> None:
    if not sceneio.capabilities("hdf5").available:
        return

    tensors = _core.tensor_dict(
        {
            "dense/a": np.arange(24, dtype=np.float32).reshape(4, 6),
            "ids": np.arange(5, dtype=np.int16),
        },
        {"producer": "wheel-smoke"},
    )
    hdf5_path = root / "arrays.h5"
    sceneio.write(tensors, hdf5_path, format="hdf5")
    assert sceneio.detect(hdf5_path) == "hdf5"
    decoded_tensors = sceneio.read(hdf5_path)
    np.testing.assert_array_equal(decoded_tensors["dense/a"], tensors["dense/a"])
    assert sceneio.inspect(hdf5_path).count == 2
    selected = sceneio.read_partial(hdf5_path, tensors=("ids",))
    np.testing.assert_array_equal(selected["ids"], tensors["ids"])
    sliced = sceneio.read_partial(
        hdf5_path,
        slices={"dense/a": (1, 3)},
    )
    np.testing.assert_array_equal(sliced["dense/a"], tensors["dense/a"][1:3])

    feature = _core.feature_set(
        np.array([[1.5, 2.5], [3.5, 4.5]], dtype=np.float32),
        np.arange(8, dtype=np.float16).reshape(2, 4),
        np.array([0.25, 0.75], dtype=np.float32),
        image_name="db/a.jpg",
        image_size=(640, 480),
        pixel_center=(0.0, 0.0),
    )
    feature_store = sceneio.HlocFeatureStore(
        {"db/a.jpg": feature},
        {"db/a.jpg": 0.5},
    )
    feature_path = root / "features.h5"
    sceneio.write(feature_store, feature_path)
    assert sceneio.detect(feature_path) == "hloc_features"
    decoded_features = sceneio.read(feature_path)
    np.testing.assert_array_equal(
        decoded_features["db/a.jpg"].descriptors,
        feature.descriptors,
    )
    assert sceneio.inspect(feature_path).metadata["image_count"] == 1

    graph = _core.match_graph(
        np.array([[1, 2]], dtype=np.uint32),
        np.array([0, 2], dtype=np.uint64),
        np.array([[0, 1], [2, 3]], dtype=np.uint32),
        np.array([0, 0], dtype=np.uint64),
        np.empty((0, 2), dtype=np.uint32),
        scores=np.array([0.5, 0.75], dtype=np.float32),
        match_score_present=np.array([1], dtype=np.uint8),
        match_present=np.array([1], dtype=np.uint8),
        geometry_present=np.array([0], dtype=np.uint8),
    )
    match_store = sceneio.HlocMatchStore(
        ("db/a.jpg", "query/b.jpg"),
        (("db/a.jpg", "query/b.jpg"),),
        (4,),
        ("int16",),
        ("float16",),
        graph,
    )
    match_path = root / "matches.h5"
    sceneio.write(match_store, match_path)
    assert sceneio.detect(match_path) == "hloc_matches"
    decoded_matches = sceneio.read(match_path)
    np.testing.assert_array_equal(decoded_matches.graph.matches, graph.matches)
    assert sceneio.inspect(match_path).metadata["pair_count"] == 1


def _zarr_formats(root: Path) -> None:
    if not sceneio.capabilities("zarr").available:
        return

    tensors = _core.tensor_dict(
        {
            "dense/a": np.arange(24, dtype=np.float32).reshape(4, 6),
            "ids": np.arange(5, dtype=np.int16),
        },
        {"producer": "wheel-smoke"},
    )
    path = root / "arrays.zarr"
    sceneio.write(tensors, path, format="zarr")
    assert sceneio.detect(path) == "zarr"
    decoded = sceneio.read(path)
    np.testing.assert_array_equal(decoded["dense/a"], tensors["dense/a"])
    assert sceneio.inspect(path).count == 2
    selected = sceneio.read_partial(path, tensors=("ids",))
    np.testing.assert_array_equal(selected["ids"], tensors["ids"])
    sliced = sceneio.read_partial(path, slices={"dense/a": (1, 3)})
    np.testing.assert_array_equal(sliced["dense/a"], tensors["dense/a"][1:3])


def _tiff_formats(root: Path) -> None:
    if not sceneio.capabilities("tiff").available:
        return

    pixels = np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3)
    image = _core.image(pixels, color_space="srgb")
    path = root / "image.tiff"
    sceneio.write(image, path)
    assert sceneio.detect(path) == "tiff"
    np.testing.assert_array_equal(sceneio.read(path).pixels, pixels)
    assert sceneio.inspect(path).shape == pixels.shape


def _e57_formats(root: Path) -> None:
    if not sceneio.capabilities("e57").available:
        return

    positions = np.arange(18, dtype=np.float32).reshape(6, 3) / 8
    colors = np.arange(18, dtype=np.uint8).reshape(6, 3)
    intensity = np.linspace(0, 1, 6, dtype=np.float32)
    cloud = _core.point_cloud(
        positions,
        colors=colors,
        intensity=intensity,
    )
    path = root / "points.e57"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "e57"
    decoded = sceneio.read(path)
    np.testing.assert_array_equal(decoded.positions, positions)
    np.testing.assert_array_equal(decoded.colors, colors)
    assert sceneio.inspect(path).count == 6


def _columnar_formats(root: Path) -> None:
    if not sceneio.capabilities("parquet").available:
        return

    arrays = {
        "image_id": np.arange(5, dtype=np.uint32),
        "xy": np.arange(10, dtype=np.float32).reshape(5, 2),
    }
    tensors = _core.tensor_dict(arrays, {"role": "features"})
    for format_id, suffix in (
        ("parquet", ".parquet"),
        ("arrow_ipc", ".arrow"),
    ):
        path = root / f"features{suffix}"
        sceneio.write(tensors, path, format=format_id)
        assert sceneio.detect(path) == format_id
        decoded = sceneio.read(path)
        np.testing.assert_array_equal(decoded["xy"], arrays["xy"])
        assert sceneio.inspect(path).count == 5
        if format_id == "parquet":
            selected = sceneio.read_partial(
                path,
                tensors=("image_id",),
            )
            np.testing.assert_array_equal(
                selected["image_id"],
                arrays["image_id"],
            )


def _openvdb_formats(root: Path) -> None:
    if not sceneio.capabilities("openvdb").available:
        return

    coords = np.array([[0, 0, 0], [3, -2, 7]], dtype=np.int32)
    values = np.array([0.25, -1.5], dtype=np.float32)
    grid = _core.tensor_dict(
        {"coords": coords, "values": values},
        {"name": "tsdf"},
    )
    path = root / "volume.vdb"
    sceneio.write(grid, path)
    assert sceneio.detect(path) == "openvdb"
    decoded = sceneio.read(path)
    assert {
        tuple(coord): value.view(np.uint32)
        for coord, value in zip(
            np.asarray(decoded["coords"]),
            np.asarray(decoded["values"]),
            strict=True,
        )
    } == {
        tuple(coord): value.view(np.uint32)
        for coord, value in zip(coords, values, strict=True)
    }
    assert sceneio.inspect(path).count == 2


def _usd_formats(root: Path) -> None:
    if not sceneio.capabilities("usd").available:
        return

    usd_capabilities = sceneio.capabilities("usd")
    assert "profile_sceneio_usd_3dcv_1" in usd_capabilities.supported_features
    assert {"current_usdc", "composition", "selected_time"} <= set(
        usd_capabilities.unsupported_features
    )

    positions = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        dtype=np.float32,
    )
    mesh = _core.mesh(
        positions,
        np.array([0, 3], dtype=np.uint64),
        np.array([0, 1, 2], dtype=np.uint64),
        coordinate_frame="opengl",
    )
    source = _core.mesh_scene(
        [mesh],
        np.array([0, 1], dtype=np.uint64),
        node_meshes=np.array([0], dtype=np.int64),
        node_child_offsets=np.array([0, 0], dtype=np.uint64),
        node_children=np.empty(0, dtype=np.uint64),
        node_local_transforms=np.eye(4, dtype=np.float64)[None],
        node_names=["Triangle"],
        scene_root_offsets=np.array([0, 1], dtype=np.uint64),
        scene_roots=np.array([0], dtype=np.uint64),
        default_scene=0,
    )
    for format_id, suffix in (("usd", ".usd"), ("usdz", ".usdz")):
        path = root / f"scene{suffix}"
        sceneio.write(source, path, format=format_id)
        assert sceneio.detect(path) == format_id
        decoded = sceneio.read(path)
        np.testing.assert_array_equal(
            decoded.primitive_at(0).positions,
            positions,
        )
        info = sceneio.inspect(path)
        assert info.count == 1
        assert info.metadata["profile"] == "sceneio.usd.3dcv/1"
        assert info.metadata["provider_current_usdc"] is False
        assert info.metadata["provider_composition"] is False
        assert info.metadata["provider_selected_time"] is False
        rich = sceneio.read_scene(path)
        assert rich.node_names == ["Triangle"]
        retained_positions = rich.mesh_at(0).positions
        np.testing.assert_array_equal(retained_positions, positions)
        path.unlink()
        gc.collect()
        np.testing.assert_array_equal(retained_positions, positions)

    arc = root / "unsupported-arc.usda"
    arc.write_text(
        '#usda 1.0\ndef Xform "Arc" ( inherits = </Base> ) {}\n',
        encoding="utf-8",
    )
    assert "inherits" in sceneio.inspect(arc).metadata["unsupported_features"]
    try:
        sceneio.read_scene(arc)
    except sceneio.FormatError as exc:
        error = str(exc)
    else:
        raise AssertionError("installed USD profile accepted composition")
    assert "evaluated composition" in error


def _image_sequences(root: Path) -> None:
    assert sceneio.ImageSequence is _core.ImageSequence
    frames = root / "frames"
    frames.mkdir()
    first = b"P5\n3 2\n255\n" + bytes(range(6))
    second = b"P5\n3 2\n255\n" + bytes(range(6, 12))
    (frames / "frame10.pgm").write_bytes(second)
    (frames / "frame2.pgm").write_bytes(first)
    lazy = sceneio.read(frames, format="image_sequence")
    assert lazy.frame_names == ["frame2.pgm", "frame10.pgm"]
    assert lazy.y.shape == (0, 0, 0)
    copied = root / "frames-copy"
    sceneio.write(lazy, copied)
    assert sceneio.detect(copied) == "image_sequence"
    assert (copied / "frame2.pgm").read_bytes() == first
    assert sceneio.inspect(copied).count == 2
    assert sceneio.read_partial(copied, frames=(1, 2)).num_frames == 1

    empty = np.empty(0, np.int64)
    y = np.arange(2 * 3 * 5, dtype=np.uint8).reshape(2, 3, 5)
    u = np.arange(2 * 2 * 3, dtype=np.uint8).reshape(2, 2, 3)
    v = u + 50
    planar = _core.image_sequence_yuv(
        y,
        u,
        v,
        empty,
        empty,
        "420",
        "jpeg",
        "full",
        "bt709",
        "progressive",
        25,
        1,
        1,
        1,
    )
    path = root / "sequence.y4m"
    sceneio.write(planar, path)
    assert sceneio.detect(path) == "y4m"
    decoded = sceneio.read(path)
    assert decoded.y.tobytes() == y.tobytes()
    assert decoded.u.tobytes() == u.tobytes()
    assert sceneio.inspect(path).shape == (2, 3, 5, 3)
    assert sceneio.read_partial(path, frames=(1, 2)).y.tobytes() == y[1:].tobytes()

    webm_pixels = np.zeros((2, 3, 5, 3), dtype=np.uint8)
    webm_pixels[0, ...] = (255, 0, 0)
    webm_pixels[1, ...] = (0, 255, 0)
    webm_sequence = _core.image_sequence_packed(
        webm_pixels,
        np.array([0, 40_000_000], dtype=np.int64),
        np.array([40_000_000, 40_000_000], dtype=np.int64),
        "srgb",
        "none",
    )
    webm_path = root / "sequence.webm"
    sceneio.write(webm_sequence, webm_path)
    assert sceneio.detect(webm_path) == "webm"
    decoded_webm = sceneio.read(webm_path)
    assert decoded_webm.pixels.shape == webm_pixels.shape
    assert decoded_webm.durations_ns.tolist() == [40_000_000, 40_000_000]
    assert sceneio.inspect(webm_path).shape == (2, 3, 5, 3)
    assert sceneio.read_partial(webm_path, frames=(1, 2)).num_frames == 1
    for webm_profile in ("vp8-temporal", "vp9-temporal"):
        temporal_path = root / f"sequence-{webm_profile}.webm"
        sceneio.write(
            webm_sequence,
            temporal_path,
            format="webm",
            profile=webm_profile,
        )
        temporal_info = sceneio.inspect(temporal_path)
        assert temporal_info.metadata["profile"] == "temporal"
        assert temporal_info.metadata["codec"] == webm_profile[:3]
        temporal = sceneio.read(temporal_path)
        assert temporal.storage_mode == "yuv_planar"
        assert temporal.y.shape == (2, 3, 5)
        assert sceneio.read_partial(
            temporal_path, frames=(1, 2)
        ).num_frames == 1

    theora_sequence = _core.image_sequence_yuv(
        y,
        u,
        v,
        empty,
        empty,
        "420",
        "unspecified",
        "unknown",
        "unknown",
        "progressive",
        25,
        1,
        1,
        1,
    )
    theora_path = root / "sequence.ogv"
    sceneio.write(theora_sequence, theora_path)
    assert sceneio.detect(theora_path) == "theora"
    decoded_theora = sceneio.read(theora_path)
    assert decoded_theora.y.shape == y.shape
    assert decoded_theora.durations_ns.tolist() == [40_000_000, 40_000_000]
    assert sceneio.inspect(theora_path).shape == (2, 3, 5, 3)
    assert sceneio.read_partial(theora_path, frames=(1, 2)).num_frames == 1

    pixels = np.zeros((2, 3, 5, 4), dtype=np.uint8)
    pixels[0, ...] = (255, 0, 0, 255)
    pixels[1, ...] = (0, 255, 0, 192)
    animation = _core.image_sequence_packed(
        pixels,
        np.array([0, 40_000_000], dtype=np.int64),
        np.array([40_000_000, 60_000_000], dtype=np.int64),
        "srgb",
        "straight",
        None,
        2,
        np.array([1, 2, 3, 4], dtype=np.uint8),
    )
    animation_path = root / "animation.webp"
    sceneio.write(animation, animation_path)
    assert sceneio.detect(animation_path) == "animated_webp"
    decoded_animation = sceneio.read(animation_path)
    assert decoded_animation.pixels.tobytes() == pixels.tobytes()
    assert decoded_animation.durations_ns.tolist() == [40_000_000, 60_000_000]
    assert sceneio.inspect(animation_path).shape == (2, 3, 5, 4)

    apng_animation = _core.image_sequence_packed(
        pixels,
        np.array([0, 40_000_000], dtype=np.int64),
        np.array([40_000_000, 60_000_000], dtype=np.int64),
        "srgb",
        "straight",
        None,
        2,
    )
    apng_path = root / "animation.png"
    sceneio.write(apng_animation, apng_path)
    assert sceneio.detect(apng_path) == "apng"
    decoded_apng = sceneio.read(apng_path)
    assert decoded_apng.pixels.tobytes() == pixels.tobytes()
    assert decoded_apng.durations_ns.tolist() == [40_000_000, 60_000_000]
    assert sceneio.inspect(apng_path).shape == (2, 3, 5, 4)


def _rtmv_dataset(root: Path) -> None:
    directory = root / "rtmv"
    directory.mkdir()
    image = _core.image(
        np.zeros((3, 4, 4), dtype=np.float32),
        color_space="linear",
        alpha_mode="premultiplied",
    )
    encoded = bytes(_core.write_exr(image))
    for index in range(2):
        stem = f"{index:05d}"
        translation = [index + 0.25, -0.5, 2.0]
        c2w = np.eye(4, dtype=np.float64)
        c2w[:3, 3] = translation
        metadata = {
            "camera_data": {
                "cam2world": c2w.T.tolist(),
                "camera_view_matrix": np.linalg.inv(c2w).T.tolist(),
                "camera_look_at": {
                    "at": [translation[0], translation[1], 1.0],
                    "eye": translation,
                    "up": [0.0, 1.0, 0.0],
                },
                "width": 4,
                "height": 3,
                "intrinsics": {
                    "cx": 2.0,
                    "cy": 1.5,
                    "fx": 5.0,
                    "fy": 5.5,
                },
                "location_world": translation,
                "quaternion_world_xyzw": [0.0, 0.0, 0.0, 1.0],
                "scene_center_3d_box": [0.0, 0.0, 0.0],
                "scene_min_3d_box": [-1.0, -1.0, -1.0],
                "scene_max_3d_box": [1.0, 1.0, 1.0],
            },
            "objects": [{} for _ in range(index)],
        }
        (directory / f"{stem}.json").write_text(
            json.dumps(metadata, separators=(",", ":")),
            encoding="utf-8",
        )
        for suffix in (".exr", ".depth.exr", ".seg.exr"):
            (directory / f"{stem}{suffix}").write_bytes(encoded)
    assert sceneio.detect(directory) == "rtmv"
    dataset = sceneio.read(directory)
    assert dataset.num_frames == 2
    assert dataset.object_counts == (0, 1)
    assert dataset.views.num_cameras == 2
    assert sceneio.inspect(directory).shape == (2, 3, 4, 4)
    assert sceneio.read_partial(directory, frames=(1, 2)).frame_ids == (
        "00001",
    )


def _ncore_v4(root: Path) -> None:
    if not sceneio.capabilities("ncore_v4").available:
        return
    store = root / "smoke.ncore4.zarr"
    component = store / "poses" / "rig"
    component.mkdir(parents=True)
    (store / ".zgroup").write_text(
        '{"zarr_format":2}',
        encoding="utf-8",
    )
    (store / ".zattrs").write_text(
        json.dumps(
            {
                "sequence_id": "wheel-smoke",
                "sequence_timestamp_interval_us": {
                    "start": 1,
                    "stop": 2,
                },
                "generic_meta_data": {},
                "version": "v4",
                "component_group_name": "",
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (component / ".zgroup").write_text(
        '{"zarr_format":2}',
        encoding="utf-8",
    )
    (component / ".zattrs").write_text(
        json.dumps(
            {
                "component_name": "poses",
                "component_instance_name": "rig",
                "component_version": "v1",
                "generic_meta_data": {},
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    for child in ("static_poses", "dynamic_poses"):
        group = component / child
        group.mkdir()
        (group / ".zgroup").write_text(
            '{"zarr_format":2}',
            encoding="utf-8",
        )
        (group / ".zattrs").write_text("{}", encoding="utf-8")
    assert sceneio.detect(store) == "ncore_v4"
    dataset = sceneio.read(store)
    assert dataset.sequence_id == "wheel-smoke"
    assert tuple(item.id for item in dataset.components) == ("poses:rig",)
    assert sceneio.inspect(store).count == 1
    loaded = sceneio.read_ncore_component(
        store,
        sceneio.NCoreSelection("poses", "rig"),
    )
    assert loaded.component == dataset.components[0]
    assert loaded.group().attributes["component_name"] == "poses"
    semantic = sceneio.read_ncore_semantic_component(
        store,
        sceneio.NCoreSelection("poses", "rig"),
    )
    assert semantic.profile == "poses/v1"
    assert semantic.items == ()
    exported = root / "ncore-export"
    sceneio.write(dataset, exported, format="ncore_v4")
    assert (exported / "dataset.ncore4.zarr.itar").is_file()
    authored = sceneio.read(exported / "dataset.ncore4.json")
    assert authored.sequence_id == dataset.sequence_id
    assert tuple(item.id for item in authored.components) == ("poses:rig",)


def _euroc_dataset(root: Path) -> None:
    source = root / "source"
    camera = source / "mav0" / "cam0"
    image_directory = camera / "data"
    imu = source / "mav0" / "imu0"
    image_directory.mkdir(parents=True)
    imu.mkdir()
    transform = (
        "T_BS: !!opencv-matrix\n"
        "  rows: 4\n"
        "  cols: 4\n"
        "  dt: d\n"
        "  data: [1, 0, 0, 0.1, 0, 1, 0, 0.2, "
        "0, 0, 1, 0.3, 0, 0, 0, 1]\n"
    )
    for timestamp, value in ((10, 7), (20, 11)):
        pixels = np.full((2, 3), value, dtype=np.uint8)
        (image_directory / f"{timestamp}.pgm").write_bytes(
            b"P5\n3 2\n255\n" + pixels.tobytes()
        )
    (camera / "data.csv").write_text(
        "#timestamp [ns],filename\n10,10.pgm\n20,20.pgm\n",
        encoding="ascii",
        newline="\n",
    )
    (camera / "sensor.yaml").write_text(
        "%YAML:1.0\n---\nsensor_type: camera\n"
        + transform
        + "rate_hz: 20\n"
        + "resolution: [3, 2]\n"
        + "camera_model: pinhole\n"
        + "intrinsics: [3, 3, 1.5, 1]\n"
        + "distortion_model: radtan\n"
        + "distortion_coefficients: [0, 0, 0, 0]\n",
        encoding="ascii",
        newline="\n",
    )
    (imu / "data.csv").write_text(
        "#timestamp [ns],w_RS_S_x [rad s^-1],"
        "w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],"
        "a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
        "a_RS_S_z [m s^-2]\n"
        "10,1,2,3,4,5,6\n20,7,8,9,10,11,12\n",
        encoding="ascii",
        newline="\n",
    )
    (imu / "sensor.yaml").write_text(
        "%YAML:1.0\n---\nsensor_type: imu\n"
        + transform
        + "rate_hz: 200\n"
        + "gyroscope_noise_density: 0.001\n"
        + "accelerometer_noise_density: 0.002\n",
        encoding="ascii",
        newline="\n",
    )

    assert sceneio.detect(source) == "euroc_dataset"
    dataset = sceneio.read(source)
    assert dataset.camera_names == ("cam0",)
    assert dataset.imu_names == ("imu0",)
    assert dataset.num_camera_frames == 2
    assert dataset.num_imu_samples == 2
    assert sceneio.inspect(source).metadata["imu_counts"] == (2,)
    selected = sceneio.read_euroc_dataset(
        source,
        time_range_ns=(15, 25),
    )
    assert selected.camera_timestamps_ns[0].tolist() == [20]
    assert selected.imu_streams[0].timestamps_ns.tolist() == [20]

    destination = root / "copy"
    sceneio.write(dataset, destination, format="euroc_dataset")
    copied = sceneio.read(destination)
    assert copied.camera_timestamps_ns[0].tolist() == [10, 20]
    assert copied.imu_streams[0].timestamps_ns.tolist() == [10, 20]
    assert (
        destination / "mav0" / "cam0" / "data" / "10.pgm"
    ).read_bytes() == (image_directory / "10.pgm").read_bytes()


def _avif_formats(root: Path) -> None:
    if not sceneio.capabilities("avif").available:
        assert not sceneio.capabilities("animated_avif").available
        return
    pixels = np.zeros((5, 7, 3), dtype=np.uint8)
    pixels[..., 0] = 64
    still = _core.image(pixels, color_space="srgb")
    still_path = root / "still.avif"
    sceneio.write(still, still_path)
    assert sceneio.detect(still_path) == "avif"
    assert sceneio.read(still_path).pixels.shape == pixels.shape
    assert sceneio.inspect(still_path).shape == pixels.shape

    frames = np.stack((pixels, np.roll(pixels, 1, axis=1)))
    sequence = _core.image_sequence_packed(
        frames,
        np.array([0, 40_000_000], dtype=np.int64),
        np.array([40_000_000, 60_000_000], dtype=np.int64),
        "srgb",
        "none",
    )
    sequence_path = root / "sequence.avifs"
    sceneio.write(sequence, sequence_path)
    assert sceneio.detect(sequence_path) == "animated_avif"
    assert sceneio.read(sequence_path).num_frames == 2
    assert sceneio.read_partial(sequence_path, frames=(1, 2)).num_frames == 1
    assert sceneio.inspect(sequence_path).shape == (2, 5, 7, 3)


def _dense_mvs(root: Path) -> None:
    depth = _core.depth_map(
        np.arange(12, dtype=np.float32).reshape(3, 4),
        unit="unknown",
        invalid_policy="nonpositive",
        depth_convention="camera_z",
    )
    depth_path = root / "depth.bin"
    sceneio.write(depth, depth_path, format="colmap_mvs_depth")
    decoded_depth = sceneio.read(depth_path, format="colmap_mvs_depth")
    assert decoded_depth.depth.tobytes() == depth.depth.tobytes()
    assert sceneio.inspect(
        depth_path, format="colmap_mvs_depth"
    ).metadata["depth_convention"] == "camera_z"
    assert sceneio.read_partial(
        depth_path,
        window=(1, 3, 1, 4),
        format="colmap_mvs_depth",
    ).depth.shape == (2, 3)

    normal = _core.normal_map(
        np.arange(36, dtype=np.float32).reshape(3, 4, 3)
    )
    normal_path = root / "normal.bin"
    sceneio.write(normal, normal_path, format="colmap_mvs_normal")
    decoded_normal = sceneio.read(
        normal_path, format="colmap_mvs_normal"
    )
    assert decoded_normal.normals.tobytes() == normal.normals.tobytes()
    assert sceneio.inspect(
        normal_path, format="colmap_mvs_normal"
    ).shape == (3, 4, 3)
    assert sceneio.read_partial(
        normal_path,
        window=(0, 2, 2, 4),
        format="colmap_mvs_normal",
    ).normals.shape == (2, 2, 3)

    graph = _core.consistency_graph(
        3,
        4,
        np.array([0, 2], np.uint32),
        np.array([1, 3], np.uint32),
        np.array([0, 2, 3], np.uint64),
        np.array([2, 0, 1], np.uint32),
    )
    graph_path = root / "consistency.bin"
    sceneio.write(
        graph, graph_path, format="colmap_mvs_consistency"
    )
    decoded_graph = sceneio.read(
        graph_path, format="colmap_mvs_consistency"
    )
    assert decoded_graph.image_indices.tolist() == [2, 0, 1]
    assert sceneio.inspect(
        graph_path, format="colmap_mvs_consistency"
    ).count == 2

    visibility = _core.point_visibility(
        np.array([0, 2, 2], np.uint64),
        np.array([3, 1], np.uint32),
    )
    visibility_path = root / "visibility.bin"
    sceneio.write(
        visibility,
        visibility_path,
        format="colmap_fused_visibility",
    )
    decoded_visibility = sceneio.read(
        visibility_path, format="colmap_fused_visibility"
    )
    assert decoded_visibility.offsets.tolist() == [0, 2, 2]
    assert sceneio.inspect(
        visibility_path, format="colmap_fused_visibility"
    ).count == 2


def _colmap_adapters(root: Path) -> None:
    from sceneio.colmap import (
        MappingCamera,
        MappingImage,
        MappingInput,
        MegaLocArtifacts,
        MegaLocImage,
        NamedMatches,
        RigConfigCamera,
        RigConfiguration,
        SiftFeatures,
        SimilarityTransform,
        inspect_mapping_input,
        inspect_megaloc_artifacts,
        read_extended_sparse_model,
        read_feature_matches,
        read_image_pairs,
        read_mapping_input,
        read_megaloc_artifacts,
        read_rig_config,
        read_sift_features,
        read_similarity_transform,
        read_sparse_extensions,
        read_stock_image_pairs,
        write_extended_sparse_model,
        write_feature_matches,
        write_image_pairs,
        write_mapping_input,
        write_megaloc_artifacts,
        write_rig_config,
        write_sift_features,
        write_similarity_transform,
    )

    mapping = MappingInput(
        2,
        (
            MappingCamera(
                1,
                1,
                640,
                480,
                np.array([500, 500, 320, 240], dtype=np.float64),
            ),
        ),
        (
            MappingImage(
                1,
                1,
                2,
                "frame.png",
                np.array([[1, 2]], dtype=np.float32),
            ),
        ),
        (),
    )
    mapping_path = root / "mapping.pcmapin"
    write_mapping_input(mapping, mapping_path)
    assert read_mapping_input(mapping_path).images[0].time_id == 2
    assert inspect_mapping_input(mapping_path)["num_images"] == 1

    megaloc = MegaLocArtifacts(
        root,
        (MegaLocImage(1, "frame.png", "images/frame.png"),),
        (),
        np.array([[1, 2]], dtype=np.float32),
        False,
        {"smoke": True},
    )
    megaloc_root = root / "megaloc"
    write_megaloc_artifacts(megaloc, megaloc_root)
    assert read_megaloc_artifacts(
        megaloc_root
    ).descriptors.shape == (1, 2)
    assert inspect_megaloc_artifacts(
        megaloc_root
    )["descriptor_columns"] == 2

    rigs = (
        RigConfiguration(
            (
                RigConfigCamera("left/", True),
                RigConfigCamera(
                    "right/",
                    cam_from_rig=np.array(
                        [1, 0, 0, 0, 1, 0, 0],
                        dtype=np.float64,
                    ),
                ),
            )
        ),
    )
    rig_path = root / "rig.json"
    write_rig_config(rigs, rig_path)
    assert read_rig_config(rig_path)[0].cameras[0].ref_sensor

    sift_path = root / "sift.txt"
    write_sift_features(
        SiftFeatures(
            np.array([[1, 2, 3, 4]], dtype=np.float32),
            np.arange(128, dtype=np.uint8).reshape(1, 128),
        ),
        sift_path,
    )
    assert read_sift_features(sift_path).descriptors[0, 127] == 127

    pair_path = root / "pairs.txt"
    cap_path = root / "caps.txt"
    write_image_pairs(
        (("left.png", "right.png"),),
        pair_path,
        caps=np.array([100], dtype=np.uint32),
        cap_path=cap_path,
    )
    assert read_image_pairs(pair_path, cap_path=cap_path)[1][0] == 100
    assert read_stock_image_pairs(pair_path) == (
        ("left.png", "right.png"),
    )

    match_path = root / "matches.txt"
    write_feature_matches(
        (
            NamedMatches(
                "left.png",
                "right.png",
                np.array([[0, 1]], dtype=np.uint32),
            ),
        ),
        match_path,
    )
    assert read_feature_matches(match_path)[0].matches[0, 1] == 1

    sim3_path = root / "sim3.txt"
    write_similarity_transform(
        SimilarityTransform(
            2.0,
            np.array([1, 0, 0, 0], dtype=np.float64),
            np.array([1, 2, 3], dtype=np.float64),
        ),
        sim3_path,
    )
    assert read_similarity_transform(sim3_path).scale == 2.0

    sparse = root / "sparse"
    sparse.mkdir()
    (sparse / "cameras.txt").write_text(
        "1 PINHOLE 640 480 500 500 320 240\n",
        encoding="utf-8",
    )
    (sparse / "images.txt").write_text(
        "1 1 0 0 0 0 0 0 1 frame.png\n\n",
        encoding="utf-8",
    )
    (sparse / "points3D.txt").write_text("", encoding="utf-8")
    (sparse / "markers.txt").write_text(
        f'1 0 1 "marker" nan nan nan nan nan nan nan nan '
        f'nan nan nan nan {(1 << 64) - 1}\n',
        encoding="utf-8",
    )
    extended = read_extended_sparse_model(sparse)
    assert read_sparse_extensions(
        sparse,
        encoding="text",
    ).markers[0].label == "marker"
    extended_out = root / "sparse-out"
    write_extended_sparse_model(extended, extended_out)
    assert read_extended_sparse_model(
        extended_out
    ).extensions.markers[0].label == "marker"


_SMOKE_RUNNERS: Mapping[str, Callable[[Path], None]] = MappingProxyType(
    {
        "pfm": _array_formats,
        "colmap_sparse": _reconstruction_formats,
        "gaussian_ply": _splats,
        "compressed_ply": _splats,
        "sog": _splats,
        "ksplat": _splats,
        "ply_mesh": _mesh_ply,
        "obj": _obj_mtl,
        "stl": _stl_off,
        "off": _stl_off,
        "gltf": _gltf_glb,
        "glb": _gltf_glb,
        "usd": _usd_formats,
        "usdz": _usd_formats,
        "ply": _point_formats,
        "pcd": _point_formats,
        "spz": _splats,
        "transforms_json": _reconstruction_formats,
        "tum": _reconstruction_formats,
        "kitti": _reconstruction_formats,
        "euroc_state": _state_trajectory,
        "opencv_yaml": _camera_calibration,
        "opencv_xml": _camera_calibration,
        "ros_camera_info": _camera_calibration,
        "kalibr": _camera_calibration,
        "g2o": _pose_graph,
        "colmap_db": _colmap_database,
        "npy": _array_formats,
        "npz": _array_formats,
        "safetensors": _array_formats,
        "netpbm": _raster_images,
        "png": _raster_images,
        "jpeg": _raster_images,
        "bmp": _raster_images,
        "tga": _raster_images,
        "hdr": _raster_images,
        "exr": _raster_images,
        "webp": _raster_images,
        "avif": _avif_formats,
        "y4m": _image_sequences,
        "webm": _image_sequences,
        "theora": _image_sequences,
        "animated_webp": _image_sequences,
        "apng": _image_sequences,
        "animated_avif": _avif_formats,
        "rtmv": _rtmv_dataset,
        "image_sequence": _image_sequences,
        "colmap_sparse_txt": _reconstruction_formats,
        "xyz": _point_formats,
        "pts": _point_formats,
        "las": _las_waveform,
        "laz": _laz,
        "flo": _point_formats,
        "dmb": _point_formats,
        "bundler": _reconstruction_formats,
        "bal": _bal,
        "nvm": _reconstruction_formats,
        "openmvg": _reconstruction_formats,
        "splat": _splats,
        "colmap_mvs_depth": _dense_mvs,
        "colmap_mvs_normal": _dense_mvs,
        "colmap_mvs_consistency": _dense_mvs,
        "colmap_fused_visibility": _dense_mvs,
        "hdf5": _hdf5_formats,
        "hloc_features": _hdf5_formats,
        "hloc_matches": _hdf5_formats,
        "ncore_v4": _ncore_v4,
        "euroc_dataset": _euroc_dataset,
        "zarr": _zarr_formats,
        "tiff": _tiff_formats,
        "e57": _e57_formats,
        "parquet": _columnar_formats,
        "arrow_ipc": _columnar_formats,
        "openvdb": _openvdb_formats,
    }
)


def _smoke_runner_plan() -> tuple[Callable[[Path], None], ...]:
    definitions = tuple(registry.BUILTIN_DEFINITIONS)
    built_in_ids = tuple(codec.id for codec in definitions)
    if tuple(_SMOKE_RUNNERS) != built_in_ids:
        raise AssertionError(
            "wheel-smoke runners differ from installed built-in definitions"
        )
    plan = []
    seen = set()
    for codec in definitions:
        runner = _SMOKE_RUNNERS[codec.id]
        if runner not in seen:
            seen.add(runner)
            plan.append(runner)
    return tuple(plan)


def _run_manifest_smoke(root: Path) -> Mapping[str, frozenset[str]]:
    with _observe_public_io() as observations:
        for index, runner in enumerate(_smoke_runner_plan()):
            runner_root = root / f"{index:02d}-{runner.__name__.removeprefix('_')}"
            runner_root.mkdir()
            runner(runner_root)
    _validate_smoke_observations(observations)
    return MappingProxyType(
        {
            format_id: frozenset(properties)
            for format_id, properties in observations.items()
        }
    )


def main() -> None:
    assert importlib.util.find_spec("sceneio._native_test") is None
    assert not any("test" in name.lower() for name in dir(_core))
    with tempfile.TemporaryDirectory(prefix="sceneio-wheel-smoke-") as directory:
        root = Path(directory)
        _run_manifest_smoke(root)
        adapter_root = root / "colmap-adapters"
        adapter_root.mkdir()
        _colmap_adapters(adapter_root)
    print(_core.__phase__)


if __name__ == "__main__":
    main()
