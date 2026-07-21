"""Phase 2 parity suite for the SPZ codec (legacy gzip v1/v2/v3).

Oracle: gsply (MIT). SPZ is lossy (fixed-point/byte quantization), so the
check is that OUR decode of a given .spz equals GSPLY's decode of the same
bytes — both apply the identical dequantization. SPZ and PLY decode into the
same GaussianCloud, so `sh_rest` is channel-grouped like the PLY f_rest.
"""

from __future__ import annotations

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
    for ver in (3, 2):  # v3 = smallest-three, v2 = 3-byte quats (best-effort)
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


def test_ngsp_v4_rejected_cleanly():
    # a raw NGSP magic (uncompressed v4 zstd container) is rejected, not crashed
    with pytest.raises(ValueError, match="v4"):
        _core.read_spz(struct.pack("<I", 0x5053474E) + b"\x00" * 40)


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
    with pytest.raises(ValueError, match="version 3"):
        _core.write_spz(_our_cloud(_sample_arrays(1)), version=4)
