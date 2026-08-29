"""Parity suite for the antimatter15 .splat codec (splat.cpp -> GaussianCloud).

Oracle: a tiny self-contained pure-Python numpy implementation (the .splat
reference loaders are JS; a numpy oracle keeps the exact quantization pinned and
deterministic, the test_pfm/test_netpbm precedent). .splat is lossy (8-bit
color/alpha/rotation), so the checks are: our READER decodes a given .splat to
the same values the oracle does; our WRITER is byte-identical to the oracle's
float32 quantization; and read->write->read is stable. sh_degree is always 0.
"""

from __future__ import annotations

import math
import struct

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")

SH_C0 = np.float32(0.28209479177387814)
EPS = np.float32(1e-6)


# --- pure-Python numpy oracle (float32, matching the C++ nearbyintf/NEP50) ----
def _roundb(x):  # round-half-to-even (== nearbyintf), clip to a u8
    return np.clip(np.round(x), 0, 255).astype(np.uint8)


def oracle_write_splat(means, scales_log, quats_wxyz, opac_logit, sh_dc) -> bytes:
    n = len(means)
    out = bytearray()
    for i in range(n):
        out += np.asarray(means[i], np.float32).tobytes()
        out += np.exp(np.asarray(scales_log[i], np.float32)).astype(np.float32).tobytes()
        dc = np.asarray(sh_dc[i], np.float32)
        out += _roundb((np.float32(0.5) + SH_C0 * dc) * np.float32(255.0)).tobytes()
        a = np.float32(255.0) / (np.float32(1.0) + np.exp(-np.float32(opac_logit[i])))
        out.append(int(_roundb(a)))
        q = np.asarray(quats_wxyz[i], np.float32)
        q = q / np.float32(np.linalg.norm(q))
        out += _roundb(q * np.float32(128.0) + np.float32(128.0)).tobytes()
    return bytes(out)


def oracle_read_splat(data: bytes) -> dict:
    assert len(data) % 32 == 0
    n = len(data) // 32
    means = np.empty((n, 3), np.float32)
    scales = np.empty((n, 3), np.float32)
    quats = np.empty((n, 4), np.float32)
    opac = np.empty(n, np.float32)
    sh_dc = np.empty((n, 3), np.float32)
    for i in range(n):
        rec = data[i * 32 : (i + 1) * 32]
        f = np.frombuffer(rec[:24], "<f4")
        if not np.all(np.isfinite(f)) or np.any(f[3:6] <= 0):
            raise ValueError("splat: non-finite or non-positive linear scale")
        means[i] = f[:3]
        scales[i] = np.log(f[3:6])
        col = np.frombuffer(rec[24:28], np.uint8).astype(np.float32)
        sh_dc[i] = (col[:3] / np.float32(255.0) - np.float32(0.5)) / SH_C0
        a = np.clip(col[3] / np.float32(255.0), EPS, np.float32(1.0) - EPS)
        opac[i] = np.log(a / (np.float32(1.0) - a))
        rot = (np.frombuffer(rec[28:32], np.uint8).astype(np.float32) - np.float32(128.0)) / np.float32(128.0)
        nrm = np.float32(np.linalg.norm(rot))
        quats[i] = rot / nrm if nrm > 0 else np.array([1, 0, 0, 0], np.float32)
    return {"means": means, "scales": scales, "quaternions": quats, "opacities": opac, "sh_dc": sh_dc}


def _sample(seed, n=16):
    rng = np.random.default_rng(seed)
    return dict(
        means=rng.standard_normal((n, 3)).astype(np.float32),
        scales=rng.standard_normal((n, 3)).astype(np.float32),  # log-space
        quats=rng.standard_normal((n, 4)).astype(np.float32),  # wxyz, un-normalized
        opac=rng.standard_normal(n).astype(np.float32),  # logit-space
        sh0=(rng.standard_normal((n, 3)) * 0.5).astype(np.float32),
    )


def _cloud(a):
    return _core.gaussian_cloud(a["means"], a["scales"], a["quats"], a["opac"], a["sh0"])


def _fields(g):
    return {
        k: np.asarray(getattr(g, k))
        for k in ("means", "scales", "quaternions", "opacities", "sh_dc")
    }


# --- parity kind 1: our reader vs the oracle on the same bytes ---------------
def test_read_matches_oracle():
    a = _sample(1)
    data = oracle_write_splat(a["means"], a["scales"], a["quats"], a["opac"], a["sh0"])
    got = _fields(_core.read_splat(data))
    ref = oracle_read_splat(data)
    for k, v in ref.items():
        np.testing.assert_allclose(got[k], v, rtol=1e-5, atol=1e-5, err_msg=k)


# --- parity kind 2: our writer is byte-identical to the oracle's quantization -
def test_write_matches_oracle_bytes():
    # position, color, alpha and rotation quantize byte-for-byte identically to
    # the numpy oracle; only the LINEAR scale is exp(), where libm (C++) and numpy
    # agree to f32 ULPs, not bit-exactly (an unavoidable transcendental mismatch).
    a = _sample(2)
    ours = np.frombuffer(bytes(_core.write_splat(_cloud(a))), np.uint8).reshape(-1, 32)
    ref = np.frombuffer(
        oracle_write_splat(a["means"], a["scales"], a["quats"], a["opac"], a["sh0"]),
        np.uint8,
    ).reshape(-1, 32)
    np.testing.assert_array_equal(ours[:, 0:12], ref[:, 0:12])  # position f32
    np.testing.assert_array_equal(ours[:, 24:32], ref[:, 24:32])  # rgba + quat u8
    np.testing.assert_allclose(  # linear scale exp(): agree to f32 rounding
        np.frombuffer(ours[:, 12:24].tobytes(), "<f4"),
        np.frombuffer(ref[:, 12:24].tobytes(), "<f4"),
        rtol=1e-6,
    )


# --- parity kind 3: read->write->read is stable (quantization is idempotent) --
def test_roundtrip_stable():
    # read.write is a near-fixed-point: byte-derived fields (means/opacity/sh_dc)
    # recover exactly; scale drifts within an exp/log ULP; the 8-bit rotation
    # wobbles within one quantization step (it is normalized, then re-quantized).
    a = _sample(3)
    g1 = _core.read_splat(_core.write_splat(_cloud(a)))
    g2 = _core.read_splat(_core.write_splat(g1))
    f1, f2 = _fields(g1), _fields(g2)
    for k in ("means", "opacities", "sh_dc"):
        np.testing.assert_array_equal(f1[k], f2[k])
    np.testing.assert_allclose(f1["scales"], f2["scales"], rtol=1e-6)
    np.testing.assert_allclose(f1["quaternions"], f2["quaternions"], atol=1 / 127)
    assert g1.sh_degree == 0 and g1.num_rest == 0


def test_writer_is_spec_correct():
    # our bytes, decoded by the independent oracle, recover the cloud within 8-bit
    # quantization; positions/scales are near-lossless (f32), color/alpha/quat coarse.
    # Keep the lossy channels inside their representable range (no saturation) so the
    # bound is the pure 8-bit step: sh_dc in +-1.5 (< +-1/(2*SH_C0)), opacity in +-6.
    a = _sample(4)
    a["sh0"] = np.clip(a["sh0"], -1.5, 1.5).astype(np.float32)
    a["opac"] = np.clip(a["opac"], -6.0, 6.0).astype(np.float32)
    dec = oracle_read_splat(bytes(_core.write_splat(_cloud(a))))
    np.testing.assert_allclose(dec["means"], a["means"], rtol=0, atol=1e-6)
    np.testing.assert_allclose(dec["scales"], a["scales"], rtol=1e-4, atol=1e-4)
    np.testing.assert_allclose(dec["sh_dc"], a["sh0"], atol=0.5 / 255 / float(SH_C0) + 1e-4)
    da = 1.0 / (1.0 + np.exp(-a["opac"]))
    dd = 1.0 / (1.0 + np.exp(-dec["opacities"]))
    np.testing.assert_allclose(dd, da, atol=1.0 / 255 + 1e-4)  # alpha within one 8-bit step
    qn = a["quats"] / np.linalg.norm(a["quats"], axis=1, keepdims=True)
    assert np.abs((qn * dec["quaternions"]).sum(1)).min() > 0.999  # rotation direction preserved


# --- external anchors: spec-derived expected values computed WITHOUT the oracle
# (which is a numpy mirror of the C++), plus the reader guard branches (alpha-0
# clamp / degenerate quat) that no random-sample seed reaches. ---
def test_external_anchor():
    sqrt_pi = float(np.sqrt(np.pi))  # 0.5/SH_C0 == 0.5*(2*sqrt(pi)) == sqrt(pi): anchors color independently of SH_C0
    rec0 = (
        struct.pack("<3f", 1.0, 2.0, 3.0)  # position
        + struct.pack("<3f", 1.0, math.e, 1.0 / math.e)  # LINEAR -> log 0, 1, -1 (pins the natural-log base)
        + bytes([255, 0, 0, 255])  # sh_dc R=+sqrt(pi), G=B=-sqrt(pi); alpha 255 -> logit ~ +13.8
        + bytes([255, 128, 128, 128])  # w byte 255, x=y=z centered -> identity after normalize
    )
    rec1 = (  # extremes that exercise the alpha and quaternion reader guards
        struct.pack("<3f", 0.0, 0.0, 0.0)
        + struct.pack("<3f", 1e-30, 1e-30, 1e-30)
        + bytes([0, 0, 0, 0])  # alpha 0 -> logit(EPS clamp) ~ -13.8
        + bytes([128, 128, 128, 128])  # all-zero quat -> degenerate -> identity
    )
    g = _core.read_splat(rec0 + rec1)
    assert g.num_gaussians == 2 and g.sh_degree == 0
    me, sc, sh, op, q = (np.asarray(getattr(g, k)) for k in ("means", "scales", "sh_dc", "opacities", "quaternions"))
    np.testing.assert_array_equal(me[0], [1.0, 2.0, 3.0])
    np.testing.assert_allclose(sc[0], [0.0, 1.0, -1.0], atol=1e-5)
    np.testing.assert_allclose(sh[0], [sqrt_pi, -sqrt_pi, -sqrt_pi], rtol=1e-5)
    assert 13.5 < op[0] < 14.0  # logit(1-1e-6); EPS=1e-5 would give ~11.5
    np.testing.assert_allclose(q[0], [1.0, 0.0, 0.0, 0.0], atol=1e-6)
    np.testing.assert_allclose(sc[1], [math.log(1e-30)] * 3, atol=1e-2)
    assert -14.0 < op[1] < -13.5  # alpha-0 EPS-clamp branch
    np.testing.assert_allclose(q[1], [1.0, 0.0, 0.0, 0.0], atol=1e-6)  # degenerate-quat branch


@pytest.mark.parametrize("linear_scale", [0.0, -1.0])
def test_reader_rejects_nonpositive_linear_scales(linear_scale):
    rec = struct.pack("<3f", 0.0, 0.0, 0.0) + struct.pack(
        "<3f", linear_scale, 1.0, 1.0
    ) + bytes([128, 128, 128, 255]) + bytes([255, 128, 128, 128])
    with pytest.raises(ValueError, match="linear scale must be positive"):
        _core.read_splat(rec)


def test_writer_saturates():
    # clampb must saturate both ends: identity quat w=+1 -> 1*128+128 = 256 -> 255;
    # sh_dc=+-10 and opacity=+-20 push color/alpha well past [0,255].
    z = np.zeros((2, 3), np.float32)
    cloud = _core.gaussian_cloud(
        z, z,
        np.array([[1, 0, 0, 0], [-1, 0, 0, 0]], np.float32),
        np.array([20.0, -20.0], np.float32),
        np.array([[10, 10, 10], [-10, -10, -10]], np.float32),
    )
    b = np.frombuffer(bytes(_core.write_splat(cloud)), np.uint8).reshape(2, 32)
    np.testing.assert_array_equal(b[0, 24:32], [255, 255, 255, 255, 255, 128, 128, 128])  # high sat + w=+1
    np.testing.assert_array_equal(b[1, 24:32], [0, 0, 0, 0, 0, 128, 128, 128])  # low sat + w=-1


def test_writer_refuses_unrepresentable_sh_rest():
    a = _sample(7)
    rest = np.random.default_rng(70).standard_normal((16, 45)).astype(np.float32)  # degree-3 rest
    g3 = _core.gaussian_cloud(a["means"], a["scales"], a["quats"], a["opac"], a["sh0"], rest)
    assert g3.sh_degree == 3 and _cloud(a).sh_degree == 0
    with pytest.raises(ValueError, match="only SH degree 0"):
        _core.write_splat(g3)


def test_nonfinite_write_refuses_instead_of_substituting_values():
    z = np.zeros((1, 3), np.float32)
    cloud = _core.gaussian_cloud(
        z, z,
        np.array([[np.inf, 0, 0, 0]], np.float32),
        np.array([np.nan], np.float32),
        np.array([[np.nan, 1.0, 1.0]], np.float32),
    )
    with pytest.raises(ValueError, match="must be finite"):
        _core.write_splat(cloud)


def test_zero_quaternion_write_refuses_instead_of_substituting_identity():
    a = _sample(8, n=1)
    a["quats"][:] = 0

    with pytest.raises(ValueError, match="non-zero finite norm"):
        _core.write_splat(_cloud(a))


def test_large_finite_quaternion_normalizes_without_overflow():
    a = _sample(9, n=1)
    maximum = np.finfo(np.float32).max
    a["quats"][:] = [maximum, maximum, 0, 0]

    back = _core.read_splat(_core.write_splat(_cloud(a)))
    expected = np.array([np.sqrt(0.5), np.sqrt(0.5), 0, 0])
    assert abs(float(np.dot(back.quaternions[0], expected))) > 0.999


@pytest.mark.parametrize("log_scale", [-200.0, 100.0])
def test_writer_refuses_scales_outside_linear_float32_domain(log_scale):
    a = _sample(10, n=1)
    a["scales"][:] = log_scale

    with pytest.raises(ValueError, match="linearized scales"):
        _core.write_splat(_cloud(a))


def test_malformed_raises():
    with pytest.raises(ValueError, match="multiple"):
        _core.read_splat(b"\x00" * 31)  # not a multiple of 32
    with pytest.raises(ValueError, match="multiple"):
        _core.read_splat(b"\x00" * 33)


def test_empty_is_legal():
    g = _core.read_splat(b"")
    assert g.num_gaussians == 0
    assert bytes(_core.write_splat(g)) == b""


def test_torch_interop():
    torch = pytest.importorskip("torch")
    g = _core.read_splat(_core.write_splat(_cloud(_sample(5))))
    assert np.array_equal(torch.from_dlpack(g.means).numpy(), np.asarray(g.means))
