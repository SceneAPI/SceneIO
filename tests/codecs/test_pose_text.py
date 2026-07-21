"""Parity suite for the plain-text pose codecs (TUM + KITTI).

Same shape as ``test_pfm.py`` (io_implementation_plan.md §6): a tiny
self-contained pure-Python oracle, cross-impl parity in both directions,
round-trip identity, the convention pins the readers RECORD (TUM: XYZW /
camera_to_world; KITTI: WXYZ from a 3x4 [R|t]), and numpy/torch interop.

TUM stores the quaternion verbatim, so its round-trips are *exact*. KITTI
stores a rotation matrix, so quaternions compare up to the sign of the
double cover, and matrix values compare with a float tolerance.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception as exc:  # pragma: no cover - exercised only in a non-built tree
    _core = None
    _import_error = exc

pytestmark = pytest.mark.skipif(
    _core is None,
    reason="sceneio._core not built (compiled-only package — build the extension first)",
)


# --- rotation <-> quaternion (WXYZ), mirroring the C++ codec exactly --------
def mat_to_quat_wxyz(R: np.ndarray) -> np.ndarray:
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float64)
    return q / np.linalg.norm(q)


def quat_wxyz_to_mat(q: np.ndarray) -> np.ndarray:
    w, x, y, z = np.asarray(q, dtype=np.float64) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


# --- oracle: minimal independent TUM + KITTI codecs ------------------------
def oracle_read_tum(data: bytes):
    quats, trans, stamps = [], [], []
    for line in data.decode().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        ts, tx, ty, tz, qx, qy, qz, qw = (float(t) for t in s.split()[:8])
        stamps.append(ts)
        trans.append([tx, ty, tz])
        quats.append([qx, qy, qz, qw])  # XYZW, verbatim
    return np.array(quats, np.float64), np.array(trans, np.float64), np.array(stamps, np.float64)


def oracle_write_tum(quats_xyzw, trans, stamps=None) -> bytes:
    lines = []
    for i in range(len(trans)):
        ts = float(i) if stamps is None else float(stamps[i])
        tx, ty, tz = (float(v) for v in trans[i])
        qx, qy, qz, qw = (float(v) for v in quats_xyzw[i])
        lines.append(" ".join(repr(v) for v in (ts, tx, ty, tz, qx, qy, qz, qw)))
    return ("\n".join(lines) + "\n").encode()


def oracle_read_kitti(data: bytes):
    quats, trans = [], []
    for line in data.decode().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = [float(t) for t in s.split()[:12]]
        R = np.array([m[0:3], m[4:7], m[8:11]], dtype=np.float64)
        trans.append([m[3], m[7], m[11]])
        quats.append(mat_to_quat_wxyz(R))
    return np.array(quats, np.float64), np.array(trans, np.float64)


def oracle_write_kitti(quats_wxyz, trans) -> bytes:
    lines = []
    for i in range(len(trans)):
        R = quat_wxyz_to_mat(quats_wxyz[i])
        t = [float(v) for v in trans[i]]
        row = [
            R[0, 0],
            R[0, 1],
            R[0, 2],
            t[0],
            R[1, 0],
            R[1, 1],
            R[1, 2],
            t[1],
            R[2, 0],
            R[2, 1],
            R[2, 2],
            t[2],
        ]
        lines.append(" ".join(repr(float(v)) for v in row))
    return ("\n".join(lines) + "\n").encode()


# --- comparison helpers ----------------------------------------------------
def assert_quats_upto_sign(a, b, atol=1e-9):
    """Quaternions are a double cover: q and -q are the same rotation."""
    a = np.atleast_2d(np.asarray(a, np.float64))
    b = np.atleast_2d(np.asarray(b, np.float64))
    assert a.shape == b.shape
    flip = np.where(np.sum(a * b, axis=1, keepdims=True) < 0, -1.0, 1.0)
    np.testing.assert_allclose(a, b * flip, atol=atol)


# --- sample builders -------------------------------------------------------
def _rand_quats_xyzw(n, seed):
    rng = np.random.default_rng(seed)
    q = rng.standard_normal((n, 4))
    return (q / np.linalg.norm(q, axis=1, keepdims=True)).astype(np.float64)


def _rand_trans(n, seed):
    return np.random.default_rng(seed).standard_normal((n, 3)).astype(np.float64)


def _rand_rotations(n, seed):
    """Random rotations as (canonical WXYZ quats, matrices). Canonicalizing
    through the matrix makes the quaternion sign match the codec's extraction."""
    q = _rand_quats_xyzw(n, seed)  # xyzw here, reorder to wxyz below
    wxyz = q[:, [3, 0, 1, 2]]
    mats = np.stack([quat_wxyz_to_mat(qi) for qi in wxyz])
    canon = np.stack([mat_to_quat_wxyz(R) for R in mats])
    return canon, mats


def _pvs_tum(quats_xyzw, trans, stamps):
    return _core.posed_view_set(
        quats_xyzw, trans, timestamps=np.asarray(stamps, np.float64), quaternion_order="xyzw"
    )


def _pvs_kitti(quats_wxyz, trans):
    return _core.posed_view_set(quats_wxyz, trans, quaternion_order="wxyz")


# =========================== TUM ===========================================
TUM_TEXT = (
    "# a TUM trajectory\n"
    "\n"
    "0.0 1.0 2.0 3.0 0.0 0.0 0.0 1.0\n"
    "   \n"
    "1.5 -0.5 0.25 4.0 0.1 0.2 0.3 0.9273618495495704\n"
    "# trailing comment\n"
    "2.75 10.0 -20.0 30.0 -0.5 0.5 -0.5 0.5\n"
)


def test_tum_read_matches_oracle():
    data = TUM_TEXT.encode()
    ours = _core.read_tum(data)
    q, t, s = oracle_read_tum(data)
    np.testing.assert_array_equal(np.asarray(ours.quaternions), q)
    np.testing.assert_array_equal(np.asarray(ours.translations), t)
    np.testing.assert_array_equal(np.asarray(ours.timestamps), s)
    assert ours.num_views == 3


def test_tum_reader_skips_comments_and_blanks():
    assert _core.read_tum(TUM_TEXT.encode()).num_views == 3


def test_tum_oracle_write_our_read():
    q = _rand_quats_xyzw(6, 1)
    t = _rand_trans(6, 2)
    s = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    ours = _core.read_tum(oracle_write_tum(q, t, s))
    np.testing.assert_array_equal(np.asarray(ours.quaternions), q)
    np.testing.assert_array_equal(np.asarray(ours.translations), t)
    np.testing.assert_array_equal(np.asarray(ours.timestamps), s)


def test_tum_our_write_oracle_read():
    q = _rand_quats_xyzw(5, 3)
    t = _rand_trans(5, 4)
    s = np.array([1.0, 2.0, 3.5, 4.25, 5.125])
    q2, t2, s2 = oracle_read_tum(_core.write_tum(_pvs_tum(q, t, s)))
    np.testing.assert_array_equal(q2, q)
    np.testing.assert_array_equal(t2, t)
    np.testing.assert_array_equal(s2, s)


def test_tum_roundtrip_identity():
    q = _rand_quats_xyzw(7, 5)
    t = _rand_trans(7, 6)
    s = np.linspace(0.0, 3.0, 7)
    back = _core.read_tum(_core.write_tum(_pvs_tum(q, t, s)))
    np.testing.assert_array_equal(np.asarray(back.quaternions), q)  # verbatim -> exact
    np.testing.assert_array_equal(np.asarray(back.translations), t)
    np.testing.assert_array_equal(np.asarray(back.timestamps), s)


def test_tum_records_conventions():
    p = _core.read_tum(TUM_TEXT.encode())
    assert p.quaternion_order == "xyzw"
    assert p.pose_convention == "camera_to_world"
    assert p.axis_frame == "opencv"
    assert p.scale_to_meters == 1.0


def test_tum_timestamps_preserved_exactly():
    q = _rand_quats_xyzw(4, 7)
    t = _rand_trans(4, 8)
    s = np.array([1234567.891011, 0.000123456789, 42.0, 9.99999999e8])
    back = _core.read_tum(_core.write_tum(_pvs_tum(q, t, s)))
    np.testing.assert_array_equal(np.asarray(back.timestamps), s)


def test_tum_write_defaults_stamps_to_index():
    # a PosedViewSet with no timestamps -> writer emits 0,1,2,... as the stamp
    q = _rand_quats_xyzw(3, 9)
    t = _rand_trans(3, 10)
    pvs = _core.posed_view_set(q, t, quaternion_order="xyzw")  # no timestamps
    _, _, s = oracle_read_tum(_core.write_tum(pvs))
    np.testing.assert_array_equal(s, np.arange(3, dtype=np.float64))


def test_tum_torch_interop():
    torch = pytest.importorskip("torch")
    q = _rand_quats_xyzw(5, 11)
    t = _rand_trans(5, 12)
    s = np.arange(5, dtype=np.float64)
    # build the record from torch tensors (float64), then round-trip
    pvs = _core.posed_view_set(
        torch.from_numpy(q).contiguous(),
        torch.from_numpy(t).contiguous(),
        timestamps=torch.from_numpy(s).contiguous(),
        quaternion_order="xyzw",
    )
    back = _core.read_tum(_core.write_tum(pvs))
    np.testing.assert_array_equal(np.asarray(back.quaternions), q)
    # read output arrays are numpy views, DLPack-exportable to torch
    assert isinstance(back.quaternions, np.ndarray)
    assert np.array_equal(
        torch.from_dlpack(back.translations).numpy(), np.asarray(back.translations)
    )


# =========================== KITTI =========================================
def test_kitti_read_matches_oracle():
    canon, mats = _rand_rotations(6, 20)
    t = _rand_trans(6, 21)
    data = oracle_write_kitti(canon, t)
    ours = _core.read_kitti(data)
    q_oracle, t_oracle = oracle_read_kitti(data)
    assert_quats_upto_sign(np.asarray(ours.quaternions), q_oracle)
    np.testing.assert_allclose(np.asarray(ours.translations), t_oracle, atol=1e-12)


def test_kitti_oracle_write_our_read():
    canon, mats = _rand_rotations(5, 22)
    t = _rand_trans(5, 23)
    ours = _core.read_kitti(oracle_write_kitti(canon, t))
    assert_quats_upto_sign(np.asarray(ours.quaternions), canon)
    np.testing.assert_allclose(np.asarray(ours.translations), t, atol=1e-12)


def test_kitti_our_write_oracle_read():
    canon, mats = _rand_rotations(5, 24)
    t = _rand_trans(5, 25)
    q_back, t_back = oracle_read_kitti(_core.write_kitti(_pvs_kitti(canon, t)))
    assert_quats_upto_sign(q_back, canon)
    np.testing.assert_allclose(t_back, t, atol=1e-12)
    # the reconstructed rotation matrices agree with the inputs
    mats_back = np.stack([quat_wxyz_to_mat(q) for q in q_back])
    for R_back, R_in in zip(mats_back, mats, strict=True):
        np.testing.assert_allclose(R_back, R_in, atol=1e-12)


def test_kitti_roundtrip_identity():
    canon, mats = _rand_rotations(8, 26)
    t = _rand_trans(8, 27)
    back = _core.read_kitti(_core.write_kitti(_pvs_kitti(canon, t)))
    assert_quats_upto_sign(np.asarray(back.quaternions), canon)
    np.testing.assert_allclose(np.asarray(back.translations), t, atol=1e-12)


def test_kitti_records_conventions():
    canon, _ = _rand_rotations(2, 28)
    t = _rand_trans(2, 29)
    p = _core.read_kitti(oracle_write_kitti(canon, t))
    assert p.quaternion_order == "wxyz"
    assert p.pose_convention == "camera_to_world"
    assert p.axis_frame == "opencv"
    assert p.scale_to_meters == 1.0
    assert np.asarray(p.timestamps).size == 0  # KITTI poses.txt has no stamps


R90 = math.cos(math.pi / 4)  # == sin(pi/4)


@pytest.mark.parametrize(
    ("R", "expected_wxyz"),
    [
        (np.eye(3), [1.0, 0.0, 0.0, 0.0]),
        (np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float), [R90, 0.0, 0.0, R90]),  # +90 z
        (np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float), [R90, R90, 0.0, 0.0]),  # +90 x
        (np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float), [R90, 0.0, R90, 0.0]),  # +90 y
        # 180-degree rotations: trace = -1, exercising the three trace<=0 branches
        # of mat_to_quat_wxyz (largest of R[0]/R[4]/R[8]) that the identity/90-deg
        # cases never reach.
        (np.diag([1.0, -1.0, -1.0]), [0.0, 1.0, 0.0, 0.0]),  # 180 x -> R[0] branch
        (np.diag([-1.0, 1.0, -1.0]), [0.0, 0.0, 1.0, 0.0]),  # 180 y -> R[4] branch
        (np.diag([-1.0, -1.0, 1.0]), [0.0, 0.0, 0.0, 1.0]),  # 180 z -> R[8] branch
    ],
)
def test_kitti_known_rotations(R, expected_wxyz):
    row = [
        R[0, 0],
        R[0, 1],
        R[0, 2],
        0.0,
        R[1, 0],
        R[1, 1],
        R[1, 2],
        0.0,
        R[2, 0],
        R[2, 1],
        R[2, 2],
        0.0,
    ]
    data = (" ".join(repr(float(v)) for v in row) + "\n").encode()
    q = np.asarray(_core.read_kitti(data).quaternions)[0]
    assert_quats_upto_sign(q, np.array(expected_wxyz), atol=1e-12)
    # orthonormal-safe: the quaternion reconstructs the exact input rotation
    np.testing.assert_allclose(quat_wxyz_to_mat(q), R, atol=1e-12)


def test_kitti_rotation_is_orthonormal():
    canon, _ = _rand_rotations(10, 30)
    t = _rand_trans(10, 31)
    p = _core.read_kitti(oracle_write_kitti(canon, t))
    for q in np.asarray(p.quaternions):
        R = quat_wxyz_to_mat(q)
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-12)
        np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-12)


def test_kitti_torch_interop():
    torch = pytest.importorskip("torch")
    canon, mats = _rand_rotations(5, 32)
    t = _rand_trans(5, 33)
    pvs = _core.posed_view_set(
        torch.from_numpy(canon).contiguous(),
        torch.from_numpy(t).contiguous(),
        quaternion_order="wxyz",
    )
    back = _core.read_kitti(_core.write_kitti(pvs))
    assert_quats_upto_sign(np.asarray(back.quaternions), canon)
    assert np.array_equal(
        torch.from_dlpack(back.translations).numpy(), np.asarray(back.translations)
    )


def test_pose_records_are_posedviewset():
    assert type(_core.read_tum(TUM_TEXT.encode())).__name__ == "PosedViewSet"
    canon, _ = _rand_rotations(1, 40)
    data = oracle_write_kitti(canon, _rand_trans(1, 41))
    assert type(_core.read_kitti(data)).__name__ == "PosedViewSet"


def test_tum_malformed_line_raises():
    with pytest.raises(ValueError, match="TUM"):
        _core.read_tum(b"0.0 1.0 2.0 3.0 0.0 0.0\n")  # only 6 numbers


def test_kitti_malformed_line_raises():
    with pytest.raises(ValueError, match="KITTI"):
        _core.read_kitti(b"1 0 0 0 0 1 0 0\n")  # only 8 numbers
