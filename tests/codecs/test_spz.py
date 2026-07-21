"""Phase 2 parity suite for the SPZ codec (legacy gzip v1/v2/v3, NGSP v4 zstd).

Oracle: gsply (MIT). SPZ is lossy (fixed-point/byte quantization), so the
check is that OUR decode of a given .spz equals GSPLY's decode of the same
bytes — both apply the identical dequantization. SPZ and PLY decode into the
same GaussianCloud, so `sh_rest` is channel-grouped like the PLY f_rest.

v4 shares v3's per-section quantization but swaps the gzip blob for independent
zstd streams + a TOC. gsply needs the `zstandard` package to (de)code v4, so
gsply-comparison v4 tests importorskip on it; our own v4 read<->write round-trip
needs no zstandard and always runs (oracle = gsply's v3 decode of the same
input, since the dequantized values are identical between v3 and v4).
"""

from __future__ import annotations

import contextlib
import os
import struct
import tempfile

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

from sceneio.testing.parity import assert_fields_close, sh_rest_channel_grouped

gsply = pytest.importorskip("gsply")
pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")


@contextlib.contextmanager
def _gsply_cpp():
    """Use gsply's C++ backend, which reads/writes SPZ v4 via its linked zstd (no
    `zstandard` package needed), then restore the previous backend so v3's
    float32-NEP50 rounding parity is unaffected."""
    if getattr(gsply, "_backend", None) is None or gsply._backend.cpp() is None:
        pytest.skip("gsply C++ backend unavailable (needed for the SPZ v4 oracle)")
    prev = gsply.active_backend()
    gsply.use_backend("cpp")
    try:
        yield
    finally:
        gsply.use_backend(prev)


@pytest.fixture(scope="module")
def spz_paths(tmp_path_factory):
    rng = np.random.default_rng(2)
    n = 8
    g = gsply.GSData.from_arrays(
        means=rng.standard_normal((n, 3)).astype(np.float32),
        scales=rng.standard_normal((n, 3)).astype(np.float32),
        quats=rng.standard_normal((n, 4)).astype(np.float32),
        opacities=rng.standard_normal(n).astype(np.float32),
        sh0=rng.standard_normal((n, 3)).astype(np.float32),
        shN=rng.standard_normal((n, 15, 3)).astype(np.float32),
        format="ply",
    )
    d = str(tmp_path_factory.mktemp("spz"))
    paths = {}
    # v3 = smallest-three, v2 = 3-byte quats (best-effort: v2 skips if this gsply
    # build can't write it). v4 (NGSP/zstd) is cross-checked against gsply's C++
    # backend in test_v4_container_interops_with_gsply.
    for ver in (3, 2):
        p = os.path.join(d, f"v{ver}.spz")
        try:
            gsply.write_spz(p, g, version=ver)
            paths[ver] = p
        except Exception:
            pass
    return paths


@pytest.mark.parametrize("ver", [3, 2])
def test_read_matches_gsply(spz_paths, ver):
    if ver not in spz_paths:
        pytest.skip(f"gsply cannot write SPZ v{ver}")
    p = spz_paths[ver]
    ours = _core.read_spz(open(p, "rb").read())
    ref = gsply.read_spz(p)
    assert_fields_close(
        ours,
        ref,
        {
            "means": "means",
            "scales": "scales",
            "quaternions": "quats",
            "opacities": "opacities",
            "sh_dc": "sh0",
            "sh_rest": ("shN", sh_rest_channel_grouped),
        },
        rtol=1e-5,
        atol=1e-6,
    )


def test_spz_and_ply_same_type(spz_paths):
    g = _core.read_spz(open(spz_paths[3], "rb").read())
    assert type(g).__name__ == "GaussianCloud"
    assert g.sh_degree == 3 and g.num_rest == 45


def test_zero_copy_and_torch(spz_paths):
    g = _core.read_spz(open(spz_paths[3], "rb").read())
    assert isinstance(g.means, np.ndarray) and g.means.shape == (g.num_gaussians, 3)
    torch = pytest.importorskip("torch")
    assert np.array_equal(torch.from_dlpack(g.means).numpy(), np.asarray(g.means))


def test_ngsp_v4_malformed_rejected():
    # v4 is now a supported container; a well-formed NGSP header whose TOC/streams
    # are truncated must be rejected cleanly (ValueError), not crash. Header claims
    # 6 streams (sh_degree 3) with a TOC at offset 32 but no TOC/stream bytes follow.
    header = struct.pack("<IIIBBBBI", 0x5053474E, 4, 8, 3, 12, 0, 6, 32) + b"\x00" * 12
    with pytest.raises(ValueError, match="TOC"):
        _core.read_spz(header)


def _sample_arrays(seed):
    rng = np.random.default_rng(seed)
    n = 16
    return dict(
        means=rng.standard_normal((n, 3)).astype(np.float32),
        scales=rng.standard_normal((n, 3)).astype(np.float32),
        quats=rng.standard_normal((n, 4)).astype(np.float32),
        opacities=rng.standard_normal(n).astype(np.float32),
        sh0=rng.standard_normal((n, 3)).astype(np.float32),
        shN=rng.standard_normal((n, 15, 3)).astype(np.float32),
    )


def _our_cloud(a):
    return _core.gaussian_cloud(
        a["means"],
        a["scales"],
        a["quats"],
        a["opacities"],
        a["sh0"],
        sh_rest_channel_grouped(a["shN"]),
    )


def _gsply_data(a):
    return gsply.GSData.from_arrays(**a, format="ply")


def test_write_matches_gsply_encode(tmp_path):
    """Our SPZ *encoder* quantizes like gsply's: gsply decodes our bytes to
    the same values it decodes its own encoder's bytes to."""
    a = _sample_arrays(7)
    ours = tmp_path / "ours.spz"
    ours.write_bytes(_core.write_spz(_our_cloud(a), version=3, fractional_bits=12))
    ref = tmp_path / "ref.spz"
    gsply.write_spz(str(ref), _gsply_data(a), version=3, fractional_bits=12)

    assert_fields_close(
        gsply.read_spz(str(ours)),
        gsply.read_spz(str(ref)),
        {k: k for k in ("means", "scales", "quats", "opacities", "sh0", "shN")},
        rtol=1e-5,
        atol=1e-6,
    )


def test_write_roundtrips_through_our_codec():
    """read_spz(write_spz(cloud)) recovers gsply's quantized decode of the
    same input — our reader and writer agree end to end."""
    a = _sample_arrays(11)
    back = _core.read_spz(_core.write_spz(_our_cloud(a)))
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ref.spz")
        gsply.write_spz(p, _gsply_data(a), version=3)
        ref = gsply.read_spz(p)
    assert_fields_close(
        back,
        ref,
        {
            "means": "means",
            "scales": "scales",
            "quaternions": "quats",
            "opacities": "opacities",
            "sh_dc": "sh0",
            "sh_rest": ("shN", sh_rest_channel_grouped),
        },
        rtol=1e-5,
        atol=1e-6,
    )


def test_fractional_bits_affects_precision():
    # more fractional bits -> finer position quantization -> smaller error
    a = _sample_arrays(3)
    cloud = _our_cloud(a)
    err = []
    for fb in (8, 20):
        g = _core.read_spz(_core.write_spz(cloud, fractional_bits=fb))
        err.append(float(np.abs(np.asarray(g.means) - a["means"]).max()))
    assert err[1] < err[0]


def test_bad_version_rejected():
    # v3 (gzip) and v4 (zstd) are the writable versions; anything else is rejected.
    with pytest.raises(ValueError, match="version 3"):
        _core.write_spz(_our_cloud(_sample_arrays(1)), version=5)


def test_write_v4_container_framing():
    """v4 is the raw NGSP zstd container: NGSP magic, version==4, a 32-byte header,
    a TOC of (compressed,uncompressed) u64 pairs, then one zstd frame per section.
    Parse the whole structure so a framing bug (TOC field order, endianness,
    stream boundaries) is caught even without an external v4 decoder."""
    n = 16  # _sample_arrays uses n=16, sh_degree 3 -> sh_dim 15 -> 6 sections
    blob = _core.write_spz(_our_cloud(_sample_arrays(5)), version=4)
    assert blob[:2] != b"\x1f\x8b"  # not a gzip stream
    magic, version, nn = struct.unpack_from("<III", blob, 0)
    sh_deg, _frac, _flags, num_streams, toc_off = struct.unpack_from("<BBBBI", blob, 12)
    assert magic == 0x5053474E and version == 4 and nn == n
    assert sh_deg == 3 and toc_off == 32 and num_streams == 6
    # canonical uncompressed section sizes: positions 9N, alphas N, colors 3N,
    # scales 3N, rotations 4N, sh 45N (sh_dim 15 * 3)
    want = [9 * n, n, 3 * n, 3 * n, 4 * n, 45 * n]
    body = 32 + num_streams * 16
    csum = 0
    for i in range(num_streams):
        csize, usize = struct.unpack_from("<QQ", blob, 32 + i * 16)
        assert usize == want[i]
        assert blob[body + csum : body + csum + 4] == b"\x28\xb5\x2f\xfd"  # zstd frame magic
        csum += csize
    assert body + csum == len(blob)


def test_v4_container_interops_with_gsply(tmp_path):
    """Cross-validate the v4 (NGSP/zstd) CONTAINER against gsply's C++ backend (no
    `zstandard` needed): gsply decodes OUR v4 file to the same values we do (writer
    + framing correct), and we decode GSPLY's v4 file to the same values gsply does
    (reader correct). Pins the container to an independent decoder — the coverage
    the skipped python-backend v4 tests could not provide."""
    a = _sample_arrays(7)
    ours = tmp_path / "ours_v4.spz"
    ours.write_bytes(_core.write_spz(_our_cloud(a), version=4, fractional_bits=12))
    ref = tmp_path / "ref_v4.spz"
    mapping = {
        "means": "means",
        "scales": "scales",
        "quaternions": "quats",
        "opacities": "opacities",
        "sh_dc": "sh0",
        "sh_rest": ("shN", sh_rest_channel_grouped),
    }
    with _gsply_cpp():
        gsply.write_spz(str(ref), _gsply_data(a), version=4, fractional_bits=12)
        g_ours = gsply.read_spz(str(ours))  # gsply decodes OUR container
        g_ref = gsply.read_spz(str(ref))  # gsply decodes ITS container
    # our writer + framing: gsply reads our v4 to the same values our reader does
    assert_fields_close(_core.read_spz(ours.read_bytes()), g_ours, mapping, rtol=1e-5, atol=1e-6)
    # our reader: we decode gsply's v4 container to the same values gsply does
    assert_fields_close(_core.read_spz(ref.read_bytes()), g_ref, mapping, rtol=1e-5, atol=1e-6)


def test_write_v4_roundtrips_through_our_codec():
    """read_spz(write_spz(cloud, version=4)) recovers gsply's quantized decode of
    the same input — our v4 zstd writer and reader agree end to end. v4 shares
    v3's quantization, so gsply's v3 decode is the oracle (needs no zstandard)."""
    a = _sample_arrays(11)
    back = _core.read_spz(_core.write_spz(_our_cloud(a), version=4))
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ref.spz")
        gsply.write_spz(p, _gsply_data(a), version=3)
        ref = gsply.read_spz(p)
    assert_fields_close(
        back,
        ref,
        {
            "means": "means",
            "scales": "scales",
            "quaternions": "quats",
            "opacities": "opacities",
            "sh_dc": "sh0",
            "sh_rest": ("shN", sh_rest_channel_grouped),
        },
        rtol=1e-5,
        atol=1e-6,
    )


def test_v4_and_v3_decode_identically():
    """v4 and v3 differ only in framing, not quantization: our read of our v4
    bytes must equal our read of our v3 bytes (byte-exact dequantized values)."""
    cloud = _our_cloud(_sample_arrays(9))
    v3 = _core.read_spz(_core.write_spz(cloud, version=3, fractional_bits=12))
    v4 = _core.read_spz(_core.write_spz(cloud, version=4, fractional_bits=12))
    assert_fields_close(
        v4,
        v3,
        {k: k for k in ("means", "scales", "quaternions", "opacities", "sh_dc", "sh_rest")},
        rtol=0.0,
        atol=0.0,
    )
