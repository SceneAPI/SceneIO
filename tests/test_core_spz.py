"""Phase 2 parity suite for the SPZ codec (legacy gzip v1/v2/v3).

Oracle: gsply (MIT). SPZ is lossy (fixed-point/byte quantization), so the
check is that OUR decode of a given .spz equals GSPLY's decode of the same
bytes — both apply the identical dequantization. SPZ and PLY decode into the
same GaussianCloud, so `sh_rest` is channel-grouped like the PLY f_rest.
"""

from __future__ import annotations

import os
import struct

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

gsply = pytest.importorskip("gsply")
pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")


def _rest_file_order(shN):
    n = shN.shape[0]
    return np.ascontiguousarray(shN.transpose(0, 2, 1).reshape(n, -1))


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
    tol = dict(rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(np.asarray(ours.means), np.asarray(ref.means), **tol)
    np.testing.assert_allclose(np.asarray(ours.scales), np.asarray(ref.scales), **tol)
    np.testing.assert_allclose(np.asarray(ours.quaternions), np.asarray(ref.quats), **tol)
    np.testing.assert_allclose(np.asarray(ours.opacities), np.asarray(ref.opacities).reshape(-1), **tol)
    np.testing.assert_allclose(np.asarray(ours.sh_dc), np.asarray(ref.sh0), **tol)
    np.testing.assert_allclose(np.asarray(ours.sh_rest), _rest_file_order(np.asarray(ref.shN)), **tol)


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
    with pytest.raises(Exception):
        _core.read_spz(struct.pack("<I", 0x5053474E) + b"\x00" * 40)
