"""Phase 1/2 parity suite for the 3DGS Gaussian .ply codec.

Oracle: gsply (MIT). The Gaussian PLY stores raw/pre-activation values; we
check that our reader recovers gsply's arrays, that gsply reads what our
writer emits, and that our read->write->read round-trip is exact. `f_rest`
is channel-grouped in the file ([R.. G.. B..]), which equals gsply's
``shN`` (N,K,3) transposed to (N,3,K) then flattened.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

gsply = pytest.importorskip("gsply")
pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")


@pytest.fixture
def ref():
    rng = np.random.default_rng(1)
    n = 6
    return dict(
        means=rng.standard_normal((n, 3)).astype(np.float32),
        scales=rng.standard_normal((n, 3)).astype(np.float32),
        quats=rng.standard_normal((n, 4)).astype(np.float32),
        opacities=rng.standard_normal(n).astype(np.float32),
        sh0=rng.standard_normal((n, 3)).astype(np.float32),
        shN=rng.standard_normal((n, 15, 3)).astype(np.float32),
    )


def _rest_file_order(shN):
    # gsply (N,K,3) -> file's channel-grouped f_rest (N, 3K): [R.. G.. B..]
    n = shN.shape[0]
    return np.ascontiguousarray(shN.transpose(0, 2, 1).reshape(n, -1))


def _gsply_ply(ref, tmp, degree=3):
    p = os.path.join(tmp, "g.ply")
    kw = dict(scales=ref["scales"], quats=ref["quats"], opacities=ref["opacities"], sh0=ref["sh0"])
    coefficient_count = (degree + 1) ** 2 - 1
    if coefficient_count:
        kw["shN"] = ref["shN"][:, :coefficient_count]
    gsply.plywrite(p, ref["means"], **kw)
    return p


@pytest.mark.parametrize("degree", [0, 1, 2, 3])
def test_read_matches_gsply(ref, tmp_path, degree):
    data = open(_gsply_ply(ref, str(tmp_path), degree), "rb").read()
    g = _core.read_gaussian_ply(data)
    assert g.num_gaussians == len(ref["means"])
    coefficient_count = (degree + 1) ** 2 - 1
    assert g.sh_degree == degree and g.num_rest == coefficient_count * 3
    np.testing.assert_allclose(np.asarray(g.means), ref["means"])
    np.testing.assert_allclose(np.asarray(g.scales), ref["scales"])
    np.testing.assert_allclose(np.asarray(g.quaternions), ref["quats"])
    np.testing.assert_allclose(np.asarray(g.opacities), ref["opacities"])
    np.testing.assert_allclose(np.asarray(g.sh_dc), ref["sh0"])
    np.testing.assert_allclose(
        np.asarray(g.sh_rest),
        _rest_file_order(ref["shN"][:, :coefficient_count]),
    )


def test_writer_readable_by_gsply(ref, tmp_path):
    gc = _core.gaussian_cloud(
        ref["means"],
        ref["scales"],
        ref["quats"],
        ref["opacities"],
        ref["sh0"],
        _rest_file_order(ref["shN"]),
    )
    p = os.path.join(str(tmp_path), "ours.ply")
    open(p, "wb").write(_core.write_gaussian_ply(gc))
    g2 = gsply.plyread(p)
    np.testing.assert_allclose(np.asarray(g2.means), ref["means"])
    np.testing.assert_allclose(np.asarray(g2.scales), ref["scales"])
    np.testing.assert_allclose(np.asarray(g2.quats), ref["quats"])
    np.testing.assert_allclose(np.asarray(g2.opacities).reshape(-1), ref["opacities"])
    np.testing.assert_allclose(np.asarray(g2.sh0), ref["sh0"])
    np.testing.assert_allclose(np.asarray(g2.shN), ref["shN"])


def test_roundtrip_identity(ref, tmp_path):
    data = open(_gsply_ply(ref, str(tmp_path)), "rb").read()
    g = _core.read_gaussian_ply(data)
    g2 = _core.read_gaussian_ply(_core.write_gaussian_ply(g))
    for f in ("means", "scales", "quaternions", "opacities", "sh_dc", "sh_rest"):
        np.testing.assert_array_equal(np.asarray(getattr(g, f)), np.asarray(getattr(g2, f)))


def test_degree0_no_rest(ref, tmp_path):
    data = open(_gsply_ply(ref, str(tmp_path), degree=0), "rb").read()
    g = _core.read_gaussian_ply(data)
    assert g.sh_degree == 0 and g.num_rest == 0
    assert np.asarray(g.sh_rest).shape == (len(ref["means"]), 0)
    np.testing.assert_allclose(np.asarray(g.means), ref["means"])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: data.replace(
                b"property float x\n",
                b"property float x\nproperty float x\n",
                1,
            ),
            "duplicate vertex property",
        ),
        (
            lambda data: data.replace(
                b"end_header\n", b"element face 1\nend_header\n", 1
            ),
            "nonzero non-vertex elements",
        ),
        (
            lambda data: data.replace(
                b"end_header\n", b"element vertex 0\nend_header\n", 1
            ),
            "duplicate vertex element",
        ),
        (
            lambda data: data.replace(b"f_rest_1\n", b"f_rest_9\n", 1),
            "consecutive from zero",
        ),
        (lambda data: data + b"\x00", "trailing bytes"),
    ],
)
def test_malformed_gaussian_ply_structure_refuses(
    ref, tmp_path, mutate, message
):
    data = open(_gsply_ply(ref, str(tmp_path), degree=1), "rb").read()

    with pytest.raises(ValueError, match=message):
        _core.read_gaussian_ply(mutate(data))


def test_zero_copy_and_torch(ref, tmp_path):
    data = open(_gsply_ply(ref, str(tmp_path)), "rb").read()
    g = _core.read_gaussian_ply(data)
    m = g.means
    assert isinstance(m, np.ndarray) and m.shape == (g.num_gaussians, 3)
    torch = pytest.importorskip("torch")
    assert np.array_equal(torch.from_dlpack(g.means).numpy(), np.asarray(g.means))
