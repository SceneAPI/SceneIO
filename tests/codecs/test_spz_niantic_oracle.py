"""Cross-check the SPZ codec against Niantic's official implementation.

The optional ``spz`` module is built from the pinned Niantic Labs repository in
``.github/workflows/oracle-spz.yml``.  It is intentionally not a SceneIO
runtime dependency.  The suite exercises every SH degree supported by
SceneIO (0--3) in both directions:

* official writer -> SceneIO reader for legacy v2/v3 and NGSP v4; and
* SceneIO writer -> official reader for the containers SceneIO writes (v3/v4).

SPZ is quantized.  Comparisons therefore use the bounds declared by the
upstream implementation (12 fractional position bits, 8-bit scale/color/
alpha fields, and the default 5/4-bit SH quantization in the official writer).
Quaternion comparisons are sign-invariant because ``q`` and ``-q`` describe
the same orientation.

Niantic documents v1 as an obsolete legacy profile.  The v3.0.0 writer emits
the 24-bit position layout while its v1 reader interprets the profile as the
never-released float16 layout, so v1 is deliberately excluded from this
*executable* claim.  SceneIO's existing v1 evidence remains covered by its
independent parity vectors; this suite does not relabel or remove that support.

The official library stores SPZ data in RUB (right/up/back) by default.  This
suite compares the raw default profile without claiming an implicit SceneIO
coordinate conversion; a focused test exercises the official RDF<->RUB
conversion separately and verifies that SceneIO preserves the resulting bytes.
Vendor extension profiles are outside this bounded core claim.
"""

from __future__ import annotations

import gzip
import os
from pathlib import Path

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover - exercised only in source-only installs
    _core = None


spz = pytest.importorskip("spz", reason="official Niantic SPZ oracle is not installed")
pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core is not built")

_PINNED_REVISION = "5bf2945de1a003cee07133b1e495fe9c6ffdc7e7"
_SH_DIM = {0: 0, 1: 3, 2: 8, 3: 15}
_EXECUTABLE_VERSIONS = (2, 3, 4)
_SCENEIO_WRITE_VERSIONS = (3, 4)
_UPSTREAM_LIMITATIONS = {
    "v1": (
        "Niantic v3.0.0 describes v1 as an obsolete float16 legacy profile; "
        "its writer/reader pair is not interoperable, so v1 is not an "
        "executable oracle claim."
    )
}


@pytest.fixture(scope="module", autouse=True)
def _require_pinned_revision() -> None:
    """Require the revision pin in the hosted oracle lane.

    Local developers may install the optional package without setting the
    environment marker.  The focused workflow sets both variables, turning a
    stale or unpinned install into a visible test failure instead of a false
    pass.
    """

    if os.environ.get("SCENEIO_REQUIRE_NIANTIC_SPZ") == "1":
        actual = os.environ.get("SCENEIO_NIANTIC_SPZ_REVISION")
        if actual != _PINNED_REVISION:
            pytest.fail(
                "SCENEIO_NIANTIC_SPZ_REVISION must equal the pinned official "
                f"revision {_PINNED_REVISION}, got {actual!r}"
            )


def _source_cloud(degree: int):
    """Create an asymmetric, finite cloud that exercises every stored field."""

    rng = np.random.default_rng(0x5A17 + degree)
    n = 13
    means = rng.uniform(-3.5, 3.5, size=(n, 3)).astype(np.float32)
    scales = rng.uniform(-2.0, 2.0, size=(n, 3)).astype(np.float32)
    quaternions = rng.normal(size=(n, 4)).astype(np.float32)
    quaternions /= np.linalg.norm(quaternions, axis=1, keepdims=True)
    opacities = np.linspace(-3.25, 3.25, n, dtype=np.float32)
    sh_dc = rng.uniform(-1.75, 1.75, size=(n, 3)).astype(np.float32)
    rest = _SH_DIM[degree]
    sh_rest = (
        rng.uniform(-0.95, 0.95, size=(n, 3, rest))
        .astype(np.float32)
        .reshape(n, 3 * rest)
    )
    return _core.gaussian_cloud(
        means,
        scales,
        quaternions,
        opacities,
        sh_dc,
        sh_rest,
    )


def _official_cloud(scene_cloud, degree: int):
    """Convert SceneIO's WXYZ/channel-grouped record to Niantic's layout."""

    n = scene_cloud.num_gaussians
    rest = _SH_DIM[degree]
    result = spz.GaussianCloud()
    result.sh_degree = degree
    result.positions = np.asarray(scene_cloud.means, dtype=np.float32).reshape(-1)
    result.scales = np.asarray(scene_cloud.scales, dtype=np.float32).reshape(-1)
    # SceneIO stores WXYZ; Niantic stores XYZW.
    quaternions = np.asarray(scene_cloud.quaternions, dtype=np.float32).reshape(n, 4)
    result.rotations = quaternions[:, [1, 2, 3, 0]].reshape(-1)
    result.alphas = np.asarray(scene_cloud.opacities, dtype=np.float32).reshape(-1)
    result.colors = np.asarray(scene_cloud.sh_dc, dtype=np.float32).reshape(-1)
    if rest:
        # SceneIO: [R coefficients][G coefficients][B coefficients].
        # Niantic: [coefficient RGB][coefficient RGB]...
        grouped = np.asarray(scene_cloud.sh_rest, dtype=np.float32).reshape(n, 3, rest)
        result.sh = grouped.transpose(0, 2, 1).reshape(-1)
    else:
        result.sh = np.empty(0, dtype=np.float32)
    return result


def _sceneio_cloud(official_cloud):
    """Convert Niantic's XYZW/coefficient-major record to SceneIO layout."""

    degree = int(official_cloud.sh_degree)
    n = int(official_cloud.num_points)
    rest = _SH_DIM[degree]
    rotations = np.asarray(official_cloud.rotations, dtype=np.float32).reshape(n, 4)
    quaternions = rotations[:, [3, 0, 1, 2]]
    if rest:
        coefficient_major = np.asarray(official_cloud.sh, dtype=np.float32).reshape(n, rest, 3)
        sh_rest = coefficient_major.transpose(0, 2, 1).reshape(n, 3 * rest)
    else:
        sh_rest = np.empty((n, 0), dtype=np.float32)
    return _core.gaussian_cloud(
        np.asarray(official_cloud.positions, dtype=np.float32).reshape(n, 3),
        np.asarray(official_cloud.scales, dtype=np.float32).reshape(n, 3),
        quaternions,
        np.asarray(official_cloud.alphas, dtype=np.float32),
        np.asarray(official_cloud.colors, dtype=np.float32).reshape(n, 3),
        sh_rest,
    )


def _official_options(version: int, *, from_coord=None):
    options = spz.PackOptions()
    options.version = version
    options.from_coord = (
        spz.CoordinateSystem.UNSPECIFIED if from_coord is None else from_coord
    )
    return options


def _official_write(scene_cloud, degree: int, version: int, path: Path, *, from_coord=None):
    assert spz.save_spz(
        _official_cloud(scene_cloud, degree),
        _official_options(version, from_coord=from_coord),
        str(path),
    )


def _official_read(path: Path, *, to_coord=None):
    options = spz.UnpackOptions()
    options.to_coord = (
        spz.CoordinateSystem.UNSPECIFIED if to_coord is None else to_coord
    )
    return spz.load_spz(str(path), options)


def _sigmoid(value):
    with np.errstate(over="ignore"):
        return 1.0 / (1.0 + np.exp(-value))


def _assert_quaternions_equivalent(actual, expected, *, cosine_error: float) -> None:
    left = np.asarray(actual, dtype=np.float64).reshape(-1, 4)
    right = np.asarray(expected, dtype=np.float64).reshape(-1, 4)
    left /= np.linalg.norm(left, axis=1, keepdims=True)
    right /= np.linalg.norm(right, axis=1, keepdims=True)
    error = 1.0 - np.abs(np.sum(left * right, axis=1))
    assert float(np.max(error)) <= cosine_error


def _assert_decode_equal(actual, expected) -> None:
    assert actual.num_gaussians == expected.num_gaussians
    assert actual.sh_degree == expected.sh_degree
    for field in ("means", "scales", "opacities", "sh_dc", "sh_rest"):
        np.testing.assert_allclose(
            np.asarray(getattr(actual, field)),
            np.asarray(getattr(expected, field)),
            rtol=0.0,
            atol=2e-6,
        )
    _assert_quaternions_equivalent(
        actual.quaternions,
        expected.quaternions,
        cosine_error=2e-7,
    )


def _assert_quantization_bounds(actual, source, *, sh1_bits: int, sh_rest_bits: int) -> None:
    """Check source-to-decoded error against SPZ's documented quantizers."""

    means_error = np.max(np.abs(np.asarray(actual.means) - np.asarray(source.means)))
    assert float(means_error) <= 0.5 / 4096.0 + 2e-6

    scales_error = np.max(np.abs(np.asarray(actual.scales) - np.asarray(source.scales)))
    assert float(scales_error) <= 0.5 / 16.0 + 2e-6

    opacity_error = np.max(
        np.abs(_sigmoid(np.asarray(actual.opacities)) - _sigmoid(np.asarray(source.opacities)))
    )
    assert float(opacity_error) <= 0.5 / 255.0 + 2e-6

    dc_error = np.max(np.abs(np.asarray(actual.sh_dc) - np.asarray(source.sh_dc)))
    assert float(dc_error) <= 0.5 / (0.15 * 255.0) + 2e-6

    degree = int(source.sh_degree)
    rest = _SH_DIM[degree]
    if rest:
        actual_sh = np.asarray(actual.sh_rest).reshape(source.num_gaussians, 3, rest)
        source_sh = np.asarray(source.sh_rest).reshape(source.num_gaussians, 3, rest)
        bits = np.full(rest, sh_rest_bits, dtype=np.int32)
        bits[:3] = sh1_bits
        # quantizeSH first rounds to the 8-bit grid and then rounds to the
        # bucket center, so include one half 8-bit step in addition to the
        # bucket half-width.
        bucket_size = 2 ** (8 - bits)
        bounds = 0.5 * (bucket_size + 1) / 128.0 + 2e-6
        assert float(np.max(np.abs(actual_sh - source_sh) - bounds[None, None, :])) <= 0.0


def test_niantic_executable_claim_excludes_obsolete_v1() -> None:
    """Keep the upstream v1 limitation explicit in the executable claim."""

    assert _EXECUTABLE_VERSIONS == (2, 3, 4)
    assert 1 not in _EXECUTABLE_VERSIONS
    assert "float16" in _UPSTREAM_LIMITATIONS["v1"]


def test_official_quantization_defaults_match_declared_bounds() -> None:
    options = spz.PackOptions()
    assert options.sh1_bits == 5
    assert options.sh_rest_bits == 4


@pytest.mark.parametrize("degree", range(4))
@pytest.mark.parametrize("version", _EXECUTABLE_VERSIONS)
def test_niantic_writer_to_sceneio_reader(tmp_path, degree: int, version: int) -> None:
    source = _source_cloud(degree)
    path = tmp_path / f"official-v{version}-d{degree}.spz"
    _official_write(source, degree, version, path)

    actual = _core.read_spz(path.read_bytes())
    expected = _sceneio_cloud(_official_read(path))
    _assert_decode_equal(actual, expected)
    _assert_quantization_bounds(actual, source, sh1_bits=5, sh_rest_bits=4)
    _assert_quaternions_equivalent(
        actual.quaternions,
        source.quaternions,
        cosine_error=1e-2 if version == 2 else 5e-5,
    )


@pytest.mark.parametrize("degree", range(4))
@pytest.mark.parametrize("version", _SCENEIO_WRITE_VERSIONS)
def test_sceneio_writer_to_niantic_reader(tmp_path, degree: int, version: int) -> None:
    source = _source_cloud(degree)
    path = tmp_path / f"sceneio-v{version}-d{degree}.spz"
    path.write_bytes(_core.write_spz(source, version=version, fractional_bits=12))

    actual = _core.read_spz(path.read_bytes())
    expected = _sceneio_cloud(_official_read(path))
    _assert_decode_equal(actual, expected)
    _assert_quantization_bounds(actual, source, sh1_bits=8, sh_rest_bits=8)
    _assert_quaternions_equivalent(
        actual.quaternions,
        source.quaternions,
        cosine_error=5e-5,
    )


def test_default_rub_profile_is_preserved_without_implicit_conversion(tmp_path) -> None:
    source = _source_cloud(2)
    path = tmp_path / "official-rdf-input.spz"
    _official_write(
        source,
        2,
        4,
        path,
        from_coord=spz.CoordinateSystem.RDF,
    )

    # Niantic converts RDF input to its default RUB storage.  SceneIO's raw
    # reader must preserve that RUB payload; it does not claim an axis relabel.
    stored = _sceneio_cloud(_official_read(path))
    rdf = _sceneio_cloud(
        _official_read(path, to_coord=spz.CoordinateSystem.RDF)
    )
    actual = _core.read_spz(path.read_bytes())
    _assert_decode_equal(actual, stored)
    assert np.allclose(
        np.asarray(stored.means)[:, 0],
        np.asarray(rdf.means)[:, 0],
        atol=2e-6,
    )
    np.testing.assert_allclose(
        np.asarray(stored.means)[:, 1:],
        -np.asarray(rdf.means)[:, 1:],
        atol=2e-6,
        rtol=0.0,
    )


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (0x1, "antialiased splats are unsupported"),
        (0x2, "header extensions are unsupported"),
        (0x80, "unsupported header flags"),
    ],
)
def test_v4_unsupported_header_flags_are_refused(flags: int, message: str) -> None:
    """Do not silently discard v4 flags absent from GaussianCloud."""

    blob = bytearray(_core.write_spz(_source_cloud(0), version=4))
    # NgspFileHeader.flags is byte 14; antialiasing and extensions are not
    # represented by SceneIO's GaussianCloud record.
    blob[14] = flags
    with pytest.raises(ValueError, match=message):
        _core.read_spz(bytes(blob))


def test_v4_nonzero_reserved_header_bytes_are_refused() -> None:
    blob = bytearray(_core.write_spz(_source_cloud(0), version=4))
    # NgspFileHeader.reserved starts at byte 20 and is required to be zero.
    blob[20] = 1
    with pytest.raises(ValueError, match="reserved header bytes must be zero"):
        _core.read_spz(bytes(blob))


@pytest.mark.parametrize(
    ("header_byte", "message"),
    [
        (0x1, "antialiased splats are unsupported"),
        (0x2, "header extensions are unsupported"),
        (0x80, "unsupported header flags"),
    ],
)
def test_legacy_unsupported_header_flags_are_refused(header_byte: int, message: str) -> None:
    """Legacy v1-v3 use the same flags byte and must not drop its semantics."""

    blob = gzip.decompress(bytes(_core.write_spz(_source_cloud(0), version=3)))
    payload = bytearray(blob)
    # LegacyPackedGaussiansHeader.flags is byte 14.
    payload[14] = header_byte
    with pytest.raises(ValueError, match=message):
        _core.read_spz(gzip.compress(bytes(payload), mtime=0))


def test_legacy_nonzero_reserved_header_byte_is_refused() -> None:
    payload = bytearray(gzip.decompress(bytes(_core.write_spz(_source_cloud(0), version=3))))
    # LegacyPackedGaussiansHeader.reserved is byte 15.
    payload[15] = 1
    with pytest.raises(ValueError, match="non-zero reserved header byte"):
        _core.read_spz(gzip.compress(bytes(payload), mtime=0))
