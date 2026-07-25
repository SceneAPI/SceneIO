"""Parity and hardening suite for PlayCanvas SOG v2.

The independent oracle uses only stdlib ZIP/JSON plus Pillow's separately
packaged libwebp and NumPy implementations of the published texture equations.
It neither calls the SceneIO SOG decoder nor shares its C++ helpers.
"""

from __future__ import annotations

import io
import json
import mmap
import tracemalloc
import warnings
import zipfile

import numpy as np
import pytest
from PIL import Image as PilImage

import sceneio
from sceneio import _core

SH_COEFFICIENTS = (0, 3, 8, 15)
QUATERNION_INDICES = (
    (1, 2, 3),
    (0, 2, 3),
    (0, 1, 3),
    (0, 1, 2),
)


def _cloud(n: int = 73, degree: int = 2):
    i = np.arange(n, dtype=np.int64)
    means = np.stack(
        [
            ((i * 17) % 101 - 50) / 7,
            ((i * 31) % 97 - 48) / 9,
            ((i * 43) % 89 - 44) / 11,
        ],
        axis=1,
    ).astype(np.float32)
    scales = np.stack(
        [
            ((i * 7) % 37 - 18) / 8,
            ((i * 11) % 41 - 20) / 9,
            ((i * 13) % 43 - 21) / 10,
        ],
        axis=1,
    ).astype(np.float32)
    quaternions = np.stack(
        [
            ((i * 3) % 31 - 15) / 17,
            ((i * 5) % 29 - 14) / 19,
            ((i * 7) % 23 - 11) / 13,
            np.where(i % 2, 1, -1) / 5,
        ],
        axis=1,
    ).astype(np.float32)
    opacities = (((i * 19) % 127 - 63) / 9).astype(np.float32)
    sh_dc = np.stack(
        [
            ((i * 23) % 137 - 68) / 32,
            ((i * 29) % 131 - 65) / 33,
            ((i * 37) % 139 - 69) / 34,
        ],
        axis=1,
    ).astype(np.float32)
    rest = (0, 9, 24, 45)[degree]
    if rest:
        j = np.arange(rest, dtype=np.int64)
        sh_rest = (
            ((i[:, None] * 17 + j[None, :] * 37) % 249 - 124) / 31
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


def _shape(count: int) -> tuple[int, int]:
    width = ((int(np.ceil(np.sqrt(count))) + 3) // 4) * 4
    height = ((int(np.ceil(count / width)) + 3) // 4) * 4
    return width, height


def _webp(rgba: np.ndarray, *, lossless: bool = True) -> bytes:
    stream = io.BytesIO()
    PilImage.fromarray(rgba, "RGBA").save(
        stream,
        format="WEBP",
        lossless=lossless,
        quality=100,
        exact=True,
    )
    return stream.getvalue()


def _rgba(data: bytes) -> np.ndarray:
    with PilImage.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGBA")).copy()


def _members(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {item.filename: archive.read(item) for item in archive.infolist()}


def _bundle(members: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return stream.getvalue()


def _oracle_decode(data: bytes) -> dict[str, np.ndarray | int]:
    members = _members(data)
    meta = json.loads(members["meta.json"])
    count = meta["count"]
    low = _rgba(members[meta["means"]["files"][0]]).reshape(-1, 4)
    high = _rgba(members[meta["means"]["files"][1]]).reshape(-1, 4)
    scales_image = _rgba(members[meta["scales"]["files"][0]]).reshape(-1, 4)
    quats_image = _rgba(members[meta["quats"]["files"][0]]).reshape(-1, 4)
    sh0_image = _rgba(members[meta["sh0"]["files"][0]]).reshape(-1, 4)

    positions = np.empty((count, 3), np.float32)
    means_min = np.asarray(meta["means"]["mins"], np.float64)
    means_range = (
        np.asarray(meta["means"]["maxs"], np.float64) - means_min
    )
    means_range[means_range == 0] = 1
    for axis in range(3):
        quantized = (
            low[:count, axis].astype(np.uint16)
            | (high[:count, axis].astype(np.uint16) << 8)
        )
        transformed = means_min[axis] + means_range[axis] * (
            quantized.astype(np.float64) / 65535
        )
        positions[:, axis] = (
            np.sign(transformed) * np.expm1(np.abs(transformed))
        ).astype(np.float32)

    scales_codebook = np.asarray(meta["scales"]["codebook"], np.float32)
    scales = scales_codebook[scales_image[:count, :3]]
    dc_codebook = np.asarray(meta["sh0"]["codebook"], np.float32)
    sh_dc = dc_codebook[sh0_image[:count, :3]]

    quaternions = np.zeros((count, 4), np.float32)
    for row in range(count):
        largest = int(quats_image[row, 3]) - 252
        assert 0 <= largest <= 3
        packed = (
            (quats_image[row, :3].astype(np.float64) / 255 * 2 - 1)
            / np.sqrt(2)
        )
        quaternions[row, list(QUATERNION_INDICES[largest])] = packed
        quaternions[row, largest] = np.sqrt(
            max(0, 1 - float(np.dot(packed, packed)))
        )

    alpha = np.clip(
        sh0_image[:count, 3].astype(np.float64) / 255,
        1e-6,
        1 - 1e-6,
    )
    opacities = np.log(alpha / (1 - alpha)).astype(np.float32)

    bands = meta.get("shN", {}).get("bands", 0)
    coefficients = SH_COEFFICIENTS[bands]
    rest = coefficients * 3
    sh_rest = np.empty((count, rest), np.float32)
    if rest:
        shn = meta["shN"]
        codebook = np.asarray(shn["codebook"], np.float32)
        centroids = _rgba(members[shn["files"][0]])
        labels = _rgba(members[shn["files"][1]]).reshape(-1, 4)
        for row in range(count):
            label = int(labels[row, 0]) | (int(labels[row, 1]) << 8)
            cy, slot = divmod(label, 64)
            for coefficient in range(coefficients):
                values = centroids[
                    cy, slot * coefficients + coefficient, :3
                ]
                for channel in range(3):
                    sh_rest[row, channel * coefficients + coefficient] = (
                        codebook[values[channel]]
                    )
    return {
        "count": count,
        "bands": bands,
        "means": positions,
        "scales": scales,
        "quaternions": quaternions,
        "opacities": opacities,
        "sh_dc": sh_dc,
        "sh_rest": sh_rest,
    }


def _assert_oracle(cloud, expected) -> None:
    assert cloud.num_gaussians == expected["count"]
    assert cloud.sh_degree == expected["bands"]
    np.testing.assert_array_equal(cloud.means, expected["means"])
    np.testing.assert_array_equal(cloud.scales, expected["scales"])
    np.testing.assert_allclose(
        cloud.quaternions,
        expected["quaternions"],
        rtol=0,
        atol=1e-7,
    )
    np.testing.assert_allclose(
        cloud.opacities,
        expected["opacities"],
        rtol=0,
        atol=1e-6,
    )
    np.testing.assert_array_equal(cloud.sh_dc, expected["sh_dc"])
    np.testing.assert_array_equal(cloud.sh_rest, expected["sh_rest"])


def _external_vector(degree: int) -> bytes:
    count = 7
    width, height = _shape(count)
    shape = (height, width, 4)
    low = np.zeros(shape, np.uint8)
    high = np.zeros(shape, np.uint8)
    scales = np.zeros(shape, np.uint8)
    quats = np.zeros(shape, np.uint8)
    sh0 = np.zeros(shape, np.uint8)
    pixels = np.arange(count)
    for axis in range(3):
        values = (pixels * (9173 + axis * 377) + axis * 101) % 65536
        low.reshape(-1, 4)[:count, axis] = values & 255
        high.reshape(-1, 4)[:count, axis] = values >> 8
        scales.reshape(-1, 4)[:count, axis] = (pixels * 17 + axis * 31) % 256
        sh0.reshape(-1, 4)[:count, axis] = (pixels * 29 + axis * 47) % 256
    low[..., 3] = 255
    high[..., 3] = 255
    scales[..., 3] = 255
    sh0.reshape(-1, 4)[:count, 3] = np.array(
        [0, 1, 64, 127, 128, 254, 255], np.uint8
    )
    for row in range(count):
        quats.reshape(-1, 4)[row] = (
            20 + row * 13,
            100 + row * 7,
            230 - row * 11,
            252 + row % 4,
        )

    scale_codebook = np.linspace(-4, 5, 256, dtype=np.float32)
    dc_codebook = np.linspace(-2, 3, 256, dtype=np.float32)
    members = {
        "means_l.webp": _webp(low),
        "means_u.webp": _webp(high),
        "scales.webp": _webp(scales),
        "quats.webp": _webp(quats),
        "sh0.webp": _webp(sh0),
    }
    meta = {
        "version": 2,
        "asset": {"generator": "independent-test-oracle"},
        "count": count,
        "means": {
            "mins": [-1.234567890123, -0.456789012345, 0.234567890123],
            "maxs": [1.543210987654, 2.012345678901, 2.765432109876],
            "files": ["means_l.webp", "means_u.webp"],
        },
        "scales": {
            "codebook": scale_codebook.tolist(),
            "files": ["scales.webp"],
        },
        "quats": {"files": ["quats.webp"]},
        "sh0": {
            "codebook": dc_codebook.tolist(),
            "files": ["sh0.webp"],
        },
    }
    if degree:
        coefficients = SH_COEFFICIENTS[degree]
        palette_count = 3
        centroids = np.zeros((1, 64 * coefficients, 4), np.uint8)
        for label in range(palette_count):
            for coefficient in range(coefficients):
                centroids[0, label * coefficients + coefficient] = (
                    (label * 41 + coefficient * 7) % 256,
                    (label * 59 + coefficient * 11) % 256,
                    (label * 71 + coefficient * 13) % 256,
                    255,
                )
        labels = np.zeros(shape, np.uint8)
        labels.reshape(-1, 4)[:count, 0] = pixels % palette_count
        labels[..., 3] = 255
        shn_codebook = np.linspace(-1.5, 1.75, 256, dtype=np.float32)
        members["shN_centroids.webp"] = _webp(centroids)
        members["shN_labels.webp"] = _webp(labels)
        meta["shN"] = {
            "count": palette_count,
            "bands": degree,
            "codebook": shn_codebook.tolist(),
            "files": ["shN_centroids.webp", "shN_labels.webp"],
        }
    members["meta.json"] = json.dumps(meta, separators=(",", ":")).encode()
    return _bundle(members)


@pytest.mark.parametrize("degree", range(4))
def test_independent_vector_decode_all_sh_degrees(degree):
    encoded = _external_vector(degree)
    _assert_oracle(_core.read_sog(encoded), _oracle_decode(encoded))


@pytest.mark.parametrize("degree", range(4))
def test_writer_is_deterministic_and_independently_decodable(degree):
    cloud = _cloud(degree=degree)
    encoded = bytes(_core.write_sog(cloud))
    assert bytes(_core.write_sog(cloud)) == encoded
    with zipfile.ZipFile(io.BytesIO(encoded)) as archive:
        assert all(item.compress_type == zipfile.ZIP_STORED for item in archive.infolist())
        assert set(archive.namelist()) == (
            {
                "means_l.webp",
                "means_u.webp",
                "quats.webp",
                "scales.webp",
                "sh0.webp",
                "meta.json",
            }
            | (
                {"shN_centroids.webp", "shN_labels.webp"}
                if degree
                else set()
            )
        )
    _assert_oracle(_core.read_sog(encoded), _oracle_decode(encoded))


def test_public_bundle_and_unbundled_directory_parity(tmp_path):
    cloud = _cloud(79, 3)
    bundle = tmp_path / "scene.sog"
    sceneio.write(cloud, bundle)
    assert sceneio.detect(bundle) == "sog"
    bundled = sceneio.read(bundle)
    bundle_info = sceneio.inspect(bundle)
    assert bundle_info.count == 79
    assert bundle_info.metadata["packaging"] == "zip"
    assert bundle_info.metadata["sh_degree"] == 3

    directory = tmp_path / "scene"
    sceneio.write(cloud, directory)
    assert sceneio.detect(directory) == "sog"
    assert sceneio.detect(directory / "meta.json") == "sog"
    unbundled = sceneio.read(directory)
    unbundled_meta = sceneio.read(directory / "meta.json")
    directory_info = sceneio.inspect(directory)
    assert directory_info.count == 79
    assert directory_info.metadata["packaging"] == "directory"
    for name in (
        "means",
        "scales",
        "quaternions",
        "opacities",
        "sh_dc",
        "sh_rest",
    ):
        np.testing.assert_array_equal(
            getattr(unbundled, name), getattr(bundled, name)
        )
        np.testing.assert_array_equal(
            getattr(unbundled_meta, name), getattr(bundled, name)
        )

    archive_members = _members(bundle.read_bytes())
    for name, data in archive_members.items():
        assert (directory / name).read_bytes() == data


def test_point_selection_equals_full_slice_for_both_packagings(tmp_path):
    cloud = _cloud(91, 2)
    bundle = tmp_path / "scene.sog"
    directory = tmp_path / "scene"
    sceneio.write(cloud, bundle)
    sceneio.write(cloud, directory)
    for path in (bundle, directory, directory / "meta.json"):
        full = sceneio.read(path)
        partial = sceneio.read_partial(path, points=(7, 31))
        assert partial.num_gaussians == 24
        assert partial.sh_degree == full.sh_degree
        for name in (
            "means",
            "scales",
            "quaternions",
            "opacities",
            "sh_dc",
            "sh_rest",
        ):
            np.testing.assert_array_equal(
                getattr(partial, name), getattr(full, name)[7:31]
            )


def test_readonly_buffer_mmap_and_source_mutation_isolation(tmp_path):
    encoded = bytes(_core.write_sog(_cloud()))
    expected = _core.read_sog(encoded)
    readonly = memoryview(encoded)
    from_view = _core.read_sog(readonly)
    path = tmp_path / "scene.sog"
    path.write_bytes(encoded)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        from_mmap = _core.read_sog(mapped)
    mutable = bytearray(encoded)
    isolated = _core.read_sog(memoryview(mutable).toreadonly())
    mutable[:] = b"\0" * len(mutable)
    for value in (from_view, from_mmap, isolated):
        np.testing.assert_array_equal(value.means, expected.means)
        np.testing.assert_array_equal(value.sh_rest, expected.sh_rest)


def _rewrite(
    encoded: bytes,
    mutate,
    *,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    members = _members(encoded)
    mutate(members)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return stream.getvalue()


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda members: members.pop("means_l.webp"),
            "missing|exactly match",
        ),
        (
            lambda members: members.__setitem__("extra.webp", b"x"),
            "exactly match",
        ),
        (
            lambda members: members.__setitem__(
                "meta.json",
                json.dumps(
                    {
                        **json.loads(members["meta.json"]),
                        "version": 3,
                    }
                ).encode(),
            ),
            "version 2",
        ),
        (
            lambda members: members.__setitem__(
                "meta.json",
                json.dumps(
                    {
                        **json.loads(members["meta.json"]),
                        "count": 0,
                    }
                ).encode(),
            ),
            "at least one",
        ),
        (
            lambda members: members.__setitem__(
                "meta.json",
                json.dumps(
                    {
                        **json.loads(members["meta.json"]),
                        "unknownLayer": {},
                    }
                ).encode(),
            ),
            "unsupported root",
        ),
        (
            lambda members: members.__setitem__(
                "meta.json",
                json.dumps(
                    {
                        **json.loads(members["meta.json"]),
                        "means": {
                            **json.loads(members["meta.json"])["means"],
                            "mins": [2, 0, 0],
                            "maxs": [1, 1, 1],
                        },
                    }
                ).encode(),
            ),
            "minima exceed",
        ),
        (
            lambda members: members.__setitem__(
                "meta.json",
                json.dumps(
                    {
                        **json.loads(members["meta.json"]),
                        "scales": {
                            **json.loads(members["meta.json"])["scales"],
                            "codebook": [0] * 255,
                        },
                    }
                ).encode(),
            ),
            "exactly 256",
        ),
        (
            lambda members: members.__setitem__(
                "meta.json",
                json.dumps(
                    {
                        **json.loads(members["meta.json"]),
                        "quats": {"files": ["../quats.webp"]},
                    }
                ).encode(),
            ),
            "invalid quats",
        ),
    ],
)
def test_rejects_malformed_metadata_and_member_sets(mutate, match):
    damaged = _rewrite(bytes(_core.write_sog(_cloud())), mutate)
    with pytest.raises(ValueError, match=match):
        _core.read_sog(damaged)


def test_rejects_lossy_and_mismatched_webp_layers():
    encoded = bytes(_core.write_sog(_cloud()))

    def lossy(members):
        pixels = _rgba(members["means_l.webp"])
        members["means_l.webp"] = _webp(pixels, lossless=False)

    with pytest.raises(ValueError, match="lossless"):
        _core.read_sog(_rewrite(encoded, lossy))

    def wrong_shape(members):
        pixels = _rgba(members["means_l.webp"])
        members["means_l.webp"] = _webp(pixels[:, :-1])

    with pytest.raises(ValueError, match="dimensions"):
        _core.read_sog(_rewrite(encoded, wrong_shape))

    def invalid_quaternion_tag(members):
        pixels = _rgba(members["quats.webp"])
        pixels.reshape(-1, 4)[0, 3] = 251
        members["quats.webp"] = _webp(pixels)

    with pytest.raises(ValueError, match="largest-component tag"):
        _core.read_sog(_rewrite(encoded, invalid_quaternion_tag))

    def invalid_sh_label(members):
        pixels = _rgba(members["shN_labels.webp"])
        pixels.reshape(-1, 4)[0, :2] = 255
        members["shN_labels.webp"] = _webp(pixels)

    with pytest.raises(ValueError, match="label exceeds"):
        _core.read_sog(_rewrite(encoded, invalid_sh_label))


def test_rejects_duplicate_zip_member():
    encoded = bytes(_core.write_sog(_cloud()))
    members = _members(encoded)
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(
            stream, "w", compression=zipfile.ZIP_STORED
        ) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
            archive.writestr("means_l.webp", members["means_l.webp"])
    with pytest.raises(ValueError, match="duplicate"):
        _core.read_sog(stream.getvalue())


def test_rejects_truncated_trailing_and_deflated_corruption(tmp_path):
    encoded = bytes(_core.write_sog(_cloud()))
    for index, damaged in enumerate((encoded[:-1], encoded + b"x")):
        with pytest.raises(ValueError, match=r"ZIP|archive|trailing"):
            _core.read_sog(damaged)
        path = tmp_path / f"damaged-{index}.sog"
        path.write_bytes(damaged)
        with pytest.raises(sceneio.FormatError, match=r"ZIP|archive|trailing"):
            sceneio.inspect(path)
    deflated = _rewrite(encoded, lambda members: None, compression=zipfile.ZIP_DEFLATED)
    decoded = _core.read_sog(deflated)
    assert decoded.num_gaussians == 73
    damaged = bytearray(deflated)
    damaged[len(damaged) // 2] ^= 0x40
    with pytest.raises(ValueError):
        _core.read_sog(bytes(damaged))


def test_writer_guards_unrepresentable_clouds(tmp_path):
    base = _cloud(7, 1)
    fields = {
        "means": np.array(base.means),
        "scales": np.array(base.scales),
        "quaternions": np.array(base.quaternions),
        "opacities": np.array(base.opacities),
        "sh_dc": np.array(base.sh_dc),
        "sh_rest": np.array(base.sh_rest),
    }
    cases = (
        ("means", np.nan, "positions"),
        ("scales", np.inf, "scales"),
        ("quaternions", np.nan, "quaternions"),
        ("opacities", np.nan, "opacities"),
        ("sh_dc", np.inf, "DC"),
        ("sh_rest", np.nan, "SH"),
    )
    for field, value, match in cases:
        changed = {name: data.copy() for name, data in fields.items()}
        changed[field].flat[0] = value
        invalid = _core.gaussian_cloud(
            changed["means"],
            changed["scales"],
            changed["quaternions"],
            changed["opacities"],
            changed["sh_dc"],
            changed["sh_rest"],
        )
        destination = tmp_path / f"{field}.sog"
        destination.write_bytes(b"unchanged")
        with pytest.raises(sceneio.FormatError, match=match):
            sceneio.write(invalid, destination)
        assert destination.read_bytes() == b"unchanged"

    changed = {name: data.copy() for name, data in fields.items()}
    changed["quaternions"][0] = 0
    zero_quaternion = _core.gaussian_cloud(
        changed["means"],
        changed["scales"],
        changed["quaternions"],
        changed["opacities"],
        changed["sh_dc"],
        changed["sh_rest"],
    )
    with pytest.raises(ValueError, match="non-zero"):
        _core.write_sog(zero_quaternion)


def test_opacity_endpoints_and_empty_cloud_policy():
    cloud = _cloud(2, 0)
    endpoints = _core.gaussian_cloud(
        np.array(cloud.means),
        np.array(cloud.scales),
        np.array(cloud.quaternions),
        np.array([-np.inf, np.inf], np.float32),
        np.array(cloud.sh_dc),
    )
    decoded = _core.read_sog(_core.write_sog(endpoints))
    np.testing.assert_allclose(
        decoded.opacities,
        np.array(
            [
                np.log(1e-6 / (1 - 1e-6)),
                np.log((1 - 1e-6) / 1e-6),
            ],
            np.float32,
        ),
        rtol=0,
        atol=1e-6,
    )
    empty = _core.gaussian_cloud(
        np.empty((0, 3), np.float32),
        np.empty((0, 3), np.float32),
        np.empty((0, 4), np.float32),
        np.empty(0, np.float32),
        np.empty((0, 3), np.float32),
    )
    with pytest.raises(ValueError, match="at least one"):
        _core.write_sog(empty)


def test_unbundled_writer_replaces_existing_set_without_partial_guard_damage(
    tmp_path,
):
    destination = tmp_path / "layers"
    sceneio.write(_cloud(11, 3), destination)
    before = {
        item.name: item.read_bytes() for item in destination.iterdir()
    }
    invalid = _cloud(11, 3)
    bad_means = np.array(invalid.means)
    bad_means[0, 0] = np.nan
    invalid = _core.gaussian_cloud(
        bad_means,
        np.array(invalid.scales),
        np.array(invalid.quaternions),
        np.array(invalid.opacities),
        np.array(invalid.sh_dc),
        np.array(invalid.sh_rest),
    )
    with pytest.raises(sceneio.FormatError, match="positions"):
        sceneio.write(invalid, destination)
    after = {
        item.name: item.read_bytes() for item in destination.iterdir()
    }
    assert after == before
    assert not any(".sceneio-sog-" in name for name in after)


def test_unbundled_writer_rejects_non_file_layer_target(tmp_path):
    destination = tmp_path / "layers"
    conflict = destination / "means_l.webp"
    conflict.mkdir(parents=True)
    marker = conflict / "owned.txt"
    marker.write_text("unchanged")
    with pytest.raises(sceneio.FormatError, match="not a regular file"):
        sceneio.write(_cloud(7, 0), destination)
    assert marker.read_text() == "unchanged"
    assert set(destination.iterdir()) == {conflict}


def test_partial_range_validation_precedes_layer_decode():
    encoded = bytes(_core.write_sog(_cloud()))
    for start, stop in ((0, 0), (5, 4), (0, 74)):
        with pytest.raises(ValueError, match="range"):
            _core.read_sog_points(encoded, start, stop)


def test_generated_100m_logical_partial_fixture_bounds_python_allocation():
    count = 1_900_000  # 106.4 MB of canonical degree-0 Gaussian values
    width, height = _shape(count)
    pixels = np.zeros((height, width, 4), np.uint8)
    pixels[..., 3] = 255
    opaque_zero = _webp(pixels)
    pixels[...] = (128, 128, 128, 252)
    quaternions = _webp(pixels)
    pixels[...] = (0, 0, 0, 128)
    sh0 = _webp(pixels)
    codebook = [0.0] * 256
    meta = {
        "version": 2,
        "count": count,
        "means": {
            "mins": [0.0, 0.0, 0.0],
            "maxs": [0.0, 0.0, 0.0],
            "files": ["means_l.webp", "means_u.webp"],
        },
        "scales": {
            "codebook": codebook,
            "files": ["scales.webp"],
        },
        "quats": {"files": ["quats.webp"]},
        "sh0": {"codebook": codebook, "files": ["sh0.webp"]},
    }
    encoded = _bundle(
        {
            "means_l.webp": opaque_zero,
            "means_u.webp": opaque_zero,
            "scales.webp": opaque_zero,
            "quats.webp": quaternions,
            "sh0.webp": sh0,
            "meta.json": json.dumps(meta, separators=(",", ":")).encode(),
        }
    )
    assert count * 14 * 4 > 100 * 1024 * 1024
    tracemalloc.start()
    selected = _core.read_sog_points(encoded, count - 8, count)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert selected.num_gaussians == 8
    assert peak < 4 * 1024 * 1024
