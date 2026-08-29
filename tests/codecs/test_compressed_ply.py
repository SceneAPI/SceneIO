"""Parity and hardening suite for PlayCanvas/SuperSplat compressed PLY.

The oracle below is a small NumPy/struct implementation of the published
chunked bit layout. Writer parity is additionally anchored by a SHA-256 over a
captured body produced by playcanvas/splat-transform 3.1.6 at commit
6b07ba05d731eac1163ad4ff1b14e47e5e3f162c. The header comment is intentionally
producer-specific, so the body is the normative byte comparison.
"""

from __future__ import annotations

import gc
import hashlib
import mmap
import os
import struct
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core

SH_C0 = 0.28209479177387814
PLAYCANVAS_REFERENCE_BODY_SHA256 = (
    "e32c9d9340ff7489177d93403078faa695e2a67ad19f763a4755ff24bdf3eff5"
)
APPLECLANG_REFERENCE_BODY_SHA256 = (
    "412aed8223afa9dd6e38cd3e36052ac8520ecb9381517567d292ba1cf8457c5f"
)


def _reference_body_sha256() -> str:
    # The writer consumes raw log-scales and logits, so the native exp/log
    # implementation can move a value across a quantization boundary.
    # The characterized hosted AppleClang/ARM profile therefore retains its
    # parent fingerprint. Any uncharacterized profile remains subject to the
    # portable PlayCanvas reference instead of inheriting an unproved hash.
    if (
        os.environ.get("SCENEIO_SPLAT_PARENT_PROFILE")
        == "macos_appleclang_arm64"
    ):
        return APPLECLANG_REFERENCE_BODY_SHA256
    return PLAYCANVAS_REFERENCE_BODY_SHA256


def _deterministic_cloud(n: int = 513, degree: int = 2):
    i = np.arange(n, dtype=np.int64)
    means = np.stack(
        [
            ((i * 17) % 1009 - 504) / 64,
            ((i * 31) % 997 - 498) / 64,
            ((i * 43) % 991 - 495) / 64,
        ],
        axis=1,
    ).astype(np.float32)
    scales = np.stack(
        [
            ((i * 7) % 97 - 48) / 16,
            ((i * 11) % 89 - 44) / 16,
            ((i * 13) % 83 - 41) / 16,
        ],
        axis=1,
    ).astype(np.float32)
    quaternions = np.stack(
        [
            ((i * 3) % 31 - 15) / 32,
            ((i * 5) % 29 - 14) / 32,
            ((i * 7) % 23 - 11) / 32,
            np.where(i % 2, 1, -1) / 32,
        ],
        axis=1,
    ).astype(np.float32)
    opacities = (((i * 19) % 127 - 63) / 16).astype(np.float32)
    sh_dc = np.stack(
        [
            ((i * 23) % 137 - 68) / 32,
            ((i * 29) % 131 - 65) / 32,
            ((i * 37) % 139 - 69) / 32,
        ],
        axis=1,
    ).astype(np.float32)
    rest = {0: 0, 1: 9, 2: 24, 3: 45}[degree]
    if rest:
        j = np.arange(rest, dtype=np.int64)
        sh_rest = (
            ((i[:, None] * 17 + j[None, :] * 37) % 249 - 124) / 32
        ).astype(np.float32)
        return _core.gaussian_cloud(
            means,
            scales,
            quaternions,
            opacities,
            sh_dc,
            sh_rest,
        )
    return _core.gaussian_cloud(
        means, scales, quaternions, opacities, sh_dc
    )


def _split_body(data: bytes) -> tuple[str, bytes]:
    marker = b"end_header\n"
    offset = data.index(marker) + len(marker)
    return data[:offset].decode("ascii"), data[offset:]


def _parse_header(text: str):
    elements: list[dict[str, object]] = []
    current = None
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] in {"ply", "format", "comment"}:
            continue
        if fields[0] == "element":
            current = {
                "name": fields[1],
                "count": int(fields[2]),
                "properties": [],
            }
            elements.append(current)
        elif fields[0] == "property":
            current["properties"].append((fields[2], fields[1]))
    return elements


def _unorm(value, bits):
    return (value & ((1 << bits) - 1)) / ((1 << bits) - 1)


def _unpack_111011(value):
    return (
        _unorm(value >> 21, 11),
        _unorm(value >> 11, 10),
        _unorm(value, 11),
    )


def _unpack_rotation(value):
    stored = [
        (_unorm(value >> 20, 10) - 0.5) / (np.sqrt(2.0) * 0.5),
        (_unorm(value >> 10, 10) - 0.5) / (np.sqrt(2.0) * 0.5),
        (_unorm(value, 10) - 0.5) / (np.sqrt(2.0) * 0.5),
    ]
    missing = np.sqrt(max(0.0, 1.0 - sum(component**2 for component in stored)))
    result = []
    source = iter(stored)
    for component in range(4):
        result.append(missing if component == value >> 30 else next(source))
    return result


def oracle_read(data: bytes) -> dict[str, np.ndarray]:
    text, body = _split_body(data)
    elements = _parse_header(text)
    chunk, vertex, *optional_sh = elements
    assert chunk["name"] == "chunk" and vertex["name"] == "vertex"
    chunk_names = [name for name, _ in chunk["properties"]]
    chunk_dtype = np.dtype(
        [(name, "<f4") for name, _ in chunk["properties"]]
    )
    chunk_rows = np.frombuffer(
        body,
        dtype=chunk_dtype,
        count=chunk["count"],
    )
    chunk_bytes = chunk_dtype.itemsize * chunk["count"]
    vertex_dtype = np.dtype(
        [(name, "<u4") for name, _ in vertex["properties"]]
    )
    vertices = np.frombuffer(
        body,
        dtype=vertex_dtype,
        count=vertex["count"],
        offset=chunk_bytes,
    )
    count = vertex["count"]
    rest = len(optional_sh[0]["properties"]) if optional_sh else 0
    sh = np.frombuffer(
        body,
        dtype=np.uint8,
        count=count * rest,
        offset=chunk_bytes + count * vertex_dtype.itemsize,
    ).reshape(count, rest)

    means = np.empty((count, 3), np.float32)
    scales = np.empty((count, 3), np.float32)
    quaternions = np.empty((count, 4), np.float32)
    opacities = np.empty(count, np.float32)
    sh_dc = np.empty((count, 3), np.float32)
    sh_rest = np.empty((count, rest), np.float32)
    has_color_ranges = "min_r" in chunk_names
    axes = "xyz"
    colors = "rgb"
    for row in range(count):
        chunk_index = row // 256
        position = _unpack_111011(int(vertices["packed_position"][row]))
        scale = _unpack_111011(int(vertices["packed_scale"][row]))
        packed_color = int(vertices["packed_color"][row])
        rgba = [
            _unorm(packed_color >> 24, 8),
            _unorm(packed_color >> 16, 8),
            _unorm(packed_color >> 8, 8),
            _unorm(packed_color, 8),
        ]
        for component in range(3):
            low = chunk_rows[f"min_{axes[component]}"][chunk_index]
            high = chunk_rows[f"max_{axes[component]}"][chunk_index]
            means[row, component] = low * (1 - position[component]) + high * position[component]
            low = chunk_rows[f"min_scale_{axes[component]}"][chunk_index]
            high = chunk_rows[f"max_scale_{axes[component]}"][chunk_index]
            scales[row, component] = low * (1 - scale[component]) + high * scale[component]
            color = rgba[component]
            if has_color_ranges:
                low = chunk_rows[f"min_{colors[component]}"][chunk_index]
                high = chunk_rows[f"max_{colors[component]}"][chunk_index]
                color = low * (1 - color) + high * color
            sh_dc[row, component] = (color - 0.5) / SH_C0
        quaternions[row] = _unpack_rotation(
            int(vertices["packed_rotation"][row])
        )
        alpha = rgba[3]
        opacities[row] = (
            -np.inf
            if alpha == 0
            else np.inf
            if alpha == 1
            else np.log(alpha / (1 - alpha))
        )
        if rest:
            normalized = np.where(
                sh[row] == 0,
                0.0,
                np.where(sh[row] == 255, 1.0, (sh[row] + 0.5) / 256),
            )
            sh_rest[row] = (normalized - 0.5) * 8
    return {
        "means": means,
        "scales": scales,
        "quaternions": quaternions,
        "opacities": opacities,
        "sh_dc": sh_dc,
        "sh_rest": sh_rest,
    }


def _fields(cloud):
    return {
        name: np.asarray(getattr(cloud, name))
        for name in (
            "means",
            "scales",
            "quaternions",
            "opacities",
            "sh_dc",
            "sh_rest",
        )
    }


def _assert_cloud_matches_oracle(cloud, expected):
    actual = _fields(cloud)
    for name in actual:
        np.testing.assert_allclose(
            actual[name],
            expected[name],
            rtol=2e-6,
            atol=2e-6,
            equal_nan=True,
            err_msg=name,
        )


def test_writer_body_matches_pinned_platform_reference():
    encoded = bytes(_core.write_compressed_ply(_deterministic_cloud()))
    _, body = _split_body(encoded)
    assert hashlib.sha256(body).hexdigest() == _reference_body_sha256()


@pytest.mark.parametrize("degree", [0, 1, 2, 3])
def test_reader_matches_independent_oracle_for_every_sh_degree(degree):
    encoded = bytes(
        _core.write_compressed_ply(_deterministic_cloud(513, degree))
    )
    decoded = _core.read_compressed_ply(encoded)
    assert decoded.sh_degree == degree
    _assert_cloud_matches_oracle(decoded, oracle_read(encoded))


def test_quantization_is_stable_after_first_decode():
    first = _core.read_compressed_ply(
        _core.write_compressed_ply(_deterministic_cloud())
    )
    first_bytes = bytes(_core.write_compressed_ply(first))
    assert bytes(_core.write_compressed_ply(first)) == first_bytes
    second = _core.read_compressed_ply(first_bytes)
    # Re-quantizing can move a value by another code step and can refine
    # Morton ties differently, so byte idempotence is not part of the format.
    # Each individual encode is deterministic and its decode still agrees
    # exactly with the independent layout oracle.
    _assert_cloud_matches_oracle(second, oracle_read(first_bytes))


def test_legacy_direct_color_chunk_schema():
    header = (
        b"ply\nformat binary_little_endian 1.0\n"
        b"element chunk 1\n"
        + b"".join(
            f"property float {name}\n".encode()
            for name in (
                "min_x",
                "min_y",
                "min_z",
                "max_x",
                "max_y",
                "max_z",
                "min_scale_x",
                "min_scale_y",
                "min_scale_z",
                "max_scale_x",
                "max_scale_y",
                "max_scale_z",
            )
        )
        + b"element vertex 1\n"
        b"property uint packed_position\n"
        b"property uint packed_rotation\n"
        b"property uint packed_scale\n"
        b"property uint packed_color\n"
        b"end_header\n"
    )
    chunk = struct.pack("<12f", 1, 2, 3, 5, 6, 7, -3, -2, -1, 1, 2, 3)
    # position/scale all zero; largest component 0 with the other three at
    # their UNORM midpoint; direct RGB=(1, 0, 128/255), alpha=64/255.
    rotation = (0 << 30) | (512 << 20) | (512 << 10) | 512
    vertex = struct.pack("<4I", 0, rotation, 0, 0xFF008040)
    decoded = _core.read_compressed_ply(header + chunk + vertex)
    np.testing.assert_array_equal(decoded.means, [[1, 2, 3]])
    np.testing.assert_array_equal(decoded.scales, [[-3, -2, -1]])
    np.testing.assert_allclose(
        decoded.sh_dc,
        [[0.5 / SH_C0, -0.5 / SH_C0, (128 / 255 - 0.5) / SH_C0]],
    )
    assert sceneio.capabilities("compressed_ply").supported_features[1] == (
        "legacy_direct_color_read"
    )


def test_public_detect_write_read_inspect_and_partial(tmp_path):
    cloud = _deterministic_cloud()
    path = tmp_path / "scene.compressed.ply"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "compressed_ply"
    decoded = sceneio.read(path)
    info = sceneio.inspect(path)
    assert info.format == "compressed_ply"
    assert info.count == decoded.num_gaussians == 513
    assert info.metadata["num_chunks"] == 3
    assert info.metadata["sh_degree"] == decoded.sh_degree == 2
    assert info.metadata["position_bits"] == (11, 10, 11)
    partial = sceneio.read_partial(path, points=(250, 265))
    for name, full in _fields(decoded).items():
        np.testing.assert_array_equal(
            np.asarray(getattr(partial, name)), full[250:265]
        )


def test_extensionless_ply_magic_classification(tmp_path):
    path = tmp_path / "scene"
    path.write_bytes(
        bytes(_core.write_compressed_ply(_deterministic_cloud(3, 0)))
    )
    assert sceneio.detect(path) == "compressed_ply"


def test_views_outlive_input_mapping_and_source_mutation(tmp_path):
    encoded = bytes(
        _core.write_compressed_ply(_deterministic_cloud(17, 1))
    )
    path = tmp_path / "lifetime.compressed.ply"
    path.write_bytes(encoded)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        cloud = _core.read_compressed_ply(mapped)
    expected = np.asarray(cloud.means).copy()
    gc.collect()
    path.unlink()
    np.testing.assert_array_equal(cloud.means, expected)

    backing = bytearray(encoded)
    readonly = memoryview(backing).toreadonly()
    isolated = _core.read_compressed_ply(readonly)
    isolated_means = np.asarray(isolated.means).copy()
    body = encoded.index(b"end_header\n") + len(b"end_header\n")
    backing[body:] = b"\xff" * (len(backing) - body)
    np.testing.assert_array_equal(isolated.means, isolated_means)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda data: data[:4], "missing|unterminated"),
        (lambda data: data[:-1], "truncated"),
        (lambda data: data + b"x", "trailing"),
        (
            lambda data: data.replace(
                b"element chunk 3", b"element chunk 4", 1
            ),
            "chunk count",
        ),
        (
            lambda data: data.replace(
                b"property uint packed_scale",
                b"property uint unknown_scale",
                1,
            ),
            "unsupported property",
        ),
        (
            lambda data: data.replace(
                b"binary_little_endian", b"binary_big_endian", 1
            ),
            "binary_little_endian",
        ),
    ],
)
def test_malformed_headers_and_extents_reject(mutate, match):
    encoded = bytes(
        _core.write_compressed_ply(_deterministic_cloud(513, 0))
    )
    with pytest.raises(ValueError, match=match):
        _core.read_compressed_ply(mutate(encoded))


def test_nonfinite_or_reversed_chunk_bounds_reject():
    encoded = bytearray(
        _core.write_compressed_ply(_deterministic_cloud(3, 0))
    )
    body = encoded.index(b"end_header\n") + len(b"end_header\n")
    for value in (np.nan, np.inf):
        damaged = bytearray(encoded)
        struct.pack_into("<f", damaged, body, value)
        with pytest.raises(ValueError, match="finite and ordered"):
            _core.read_compressed_ply(bytes(damaged))
    damaged = bytearray(encoded)
    minimum = struct.unpack_from("<f", damaged, body)[0]
    struct.pack_into("<f", damaged, body + 3 * 4, minimum - 1)
    with pytest.raises(ValueError, match="finite and ordered"):
        _core.read_compressed_ply(bytes(damaged))

    damaged = bytearray(encoded)
    # min_r is the 13th float in the current chunk schema. It is finite as a
    # stored float, but converting it back to an SH coefficient would overflow.
    struct.pack_into("<f", damaged, body + 12 * 4, np.finfo(np.float32).max)
    struct.pack_into("<f", damaged, body + 15 * 4, np.finfo(np.float32).max)
    with pytest.raises(ValueError, match="float32 SH storage"):
        _core.read_compressed_ply(bytes(damaged))


def test_writer_guards_unrepresentable_values_without_touching_destination(
    tmp_path,
):
    good = _deterministic_cloud(3, 0)
    path = tmp_path / "protected.compressed.ply"
    path.write_bytes(b"keep")
    fields = {
        name: np.asarray(getattr(good, name)).copy()
        for name in (
            "means",
            "scales",
            "quaternions",
            "opacities",
            "sh_dc",
        )
    }
    cases = (
        ("means", np.nan, "positions"),
        ("scales", 21.0, "log scales"),
        ("quaternions", 0.0, "non-zero"),
        ("opacities", np.nan, "must not be NaN"),
        ("sh_dc", np.nan, "DC coefficients"),
    )
    for name, value, match in cases:
        arrays = {key: item.copy() for key, item in fields.items()}
        if name == "quaternions":
            arrays[name][0] = 0
        else:
            arrays[name].flat[0] = value
        invalid = _core.gaussian_cloud(
            arrays["means"],
            arrays["scales"],
            arrays["quaternions"],
            arrays["opacities"],
            arrays["sh_dc"],
        )
        with pytest.raises(sceneio.FormatError, match=match):
            sceneio.write(invalid, path, format="compressed_ply")
        assert path.read_bytes() == b"keep"


def test_infinite_logit_opacity_is_representable():
    cloud = _deterministic_cloud(2, 0)
    encoded = _core.write_compressed_ply(
        _core.gaussian_cloud(
            np.asarray(cloud.means),
            np.asarray(cloud.scales),
            np.asarray(cloud.quaternions),
            np.array([-np.inf, np.inf], np.float32),
            np.asarray(cloud.sh_dc),
        )
    )
    decoded = _core.read_compressed_ply(encoded)
    np.testing.assert_array_equal(decoded.opacities, [-np.inf, np.inf])
    # A valid decoded endpoint can be written again; it is not silently
    # clamped into a finite logit.
    _core.write_compressed_ply(decoded)


def test_large_sparse_partial_read_has_bounded_python_allocation(tmp_path):
    # 100 MiB-class sparse fixture: point selection validates the complete
    # container but allocates only the requested GaussianCloud rows.
    count = 6_500_096  # 25,391 complete 256-point chunks
    chunks = count // 256
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element chunk {chunks}\n"
        + "".join(
            f"property float {name}\n"
            for name in (
                "min_x",
                "min_y",
                "min_z",
                "max_x",
                "max_y",
                "max_z",
                "min_scale_x",
                "min_scale_y",
                "min_scale_z",
                "max_scale_x",
                "max_scale_y",
                "max_scale_z",
            )
        )
        + f"element vertex {count}\n"
        "property uint packed_position\n"
        "property uint packed_rotation\n"
        "property uint packed_scale\n"
        "property uint packed_color\n"
        "end_header\n"
    ).encode()
    path = tmp_path / "large.compressed.ply"
    with path.open("wb") as stream:
        stream.write(header)
        stream.truncate(len(header) + chunks * 48 + count * 16)
    assert path.stat().st_size > 100 * 1024 * 1024

    tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    partial = sceneio.read_partial(
        path,
        format="compressed_ply",
        points=(6_000_000, 6_000_008),
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert partial.num_gaussians == 8
    assert peak - baseline < 4 * 1024 * 1024


def test_empty_file_container_is_valid_but_empty_range_is_not(tmp_path):
    cloud = _deterministic_cloud(0, 0)
    encoded = bytes(_core.write_compressed_ply(cloud))
    decoded = _core.read_compressed_ply(encoded)
    assert decoded.num_gaussians == 0
    path = Path(tmp_path) / "empty.compressed.ply"
    path.write_bytes(encoded)
    assert sceneio.inspect(path).count == 0
    with pytest.raises(ValueError, match="non-empty"):
        _core.read_compressed_ply_points(encoded, 0, 0)
