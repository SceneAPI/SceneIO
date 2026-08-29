"""Parity suite for the Bundler v0.3 `.out` sparse-model codec
(read_bundler / write_bundler -> the shared Reconstruction record).

There is no permissive reference reader for Bundler (pycolmap has no importer),
so the primary oracle is a tiny, self-contained pure-Python token-stream parser
defined at the top of this file — the fscanf-equivalent grammar, implemented
independently of the C++. It returns RAW Bundler-frame values; the tests apply
the documented frame conversion F = diag(1,-1,-1) on the ORACLE side and compare
to our record. The conversion itself is anchored by hand-derived external pins
(identity Bundler cam -> WXYZ (0,1,0,0), t (1,2,3) -> (1,-2,-3)) and an
end-to-end projection-consistency pin, NOT by the oracle alone.

The Reconstruction binding exposes no observation/track arrays, so observation
attribution is validated the way test_colmap_txt.py does it — by writing the
record back and oracle-parsing OUR bytes (the writer emits (X-cx, cy-Y), so a
cx=cy=0 record's view-list coordinate returns to the original Bundler (x, y)).

A secondary, OPTIONAL oracle (pycolmap.Reconstruction.export_bundler) is
importorskip + hasattr guarded so API drift only skips.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover - exercised only in a non-built tree
    _core = None

pytestmark = pytest.mark.skipif(
    _core is None or not hasattr(_core, "read_bundler"),
    reason="sceneio._core not built with the bundler codec (build the extension first)",
)

# diag(1,-1,-1): the self-inverse Bundler<->COLMAP camera-frame flip.
F = np.diag([1.0, -1.0, -1.0])


# --- rotation -> matrix (WXYZ), normalized, mirroring the C++ codec ----------
def quat_wxyz_to_mat(q) -> np.ndarray:
    w, x, y, z = np.asarray(q, dtype=np.float64) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def assert_quats_upto_sign(a, b, atol=1e-9):
    """q and -q are the same rotation (the quaternion double cover)."""
    a = np.atleast_2d(np.asarray(a, np.float64))
    b = np.atleast_2d(np.asarray(b, np.float64))
    assert a.shape == b.shape
    flip = np.where(np.sum(a * b, axis=1, keepdims=True) < 0, -1.0, 1.0)
    np.testing.assert_allclose(a, b * flip, atol=atol)


# --- oracle: an independent pure-Python Bundler v0.3 token-stream parser -----
def oracle_read_bundler(data: bytes) -> dict:
    first_nl = data.index(b"\n")
    header = data[:first_nl].decode().strip()
    assert header == "# Bundle file v0.3", f"bad header {header!r}"
    toks = data[first_nl + 1 :].decode().split()  # everything after line 1 is tokens
    it = iter(toks)
    ncam, npts = int(next(it)), int(next(it))
    cams = []
    for _ in range(ncam):
        f, k1, k2 = float(next(it)), float(next(it)), float(next(it))
        R = np.array([[float(next(it)) for _ in range(3)] for _ in range(3)], np.float64)
        t = np.array([float(next(it)) for _ in range(3)], np.float64)
        cams.append(dict(f=f, k1=k1, k2=k2, R=R, t=t))
    pts = []
    for _ in range(npts):
        xyz = np.array([float(next(it)) for _ in range(3)], np.float64)
        rgb = np.array([int(next(it)) for _ in range(3)], np.int64)
        m = int(next(it))
        views = [(int(next(it)), int(next(it)), float(next(it)), float(next(it))) for _ in range(m)]
        pts.append(dict(xyz=xyz, rgb=rgb, views=views))
    exhausted = False
    try:
        next(it)
    except StopIteration:
        exhausted = True
    assert exhausted, "oracle: trailing tokens after the last point"
    return dict(ncam=ncam, npts=npts, cams=cams, pts=pts)


# --- fixture builder (full-precision repr; ws-agnostic reader accepts it) ----
def _fmt(v) -> str:
    return repr(float(v))


def bundler_build(cams, pts) -> bytes:
    """cams: [(f, k1, k2, R(3x3), t(3,))]; pts: [(xyz(3,), rgb(3,), [(cam,key,x,y)])]."""
    lines = ["# Bundle file v0.3", f"{len(cams)} {len(pts)}"]
    for f, k1, k2, R, t in cams:
        R, t = np.asarray(R, np.float64), np.asarray(t, np.float64)
        lines.append(f"{_fmt(f)} {_fmt(k1)} {_fmt(k2)}")
        for row in range(3):
            lines.append(f"{_fmt(R[row, 0])} {_fmt(R[row, 1])} {_fmt(R[row, 2])}")
        lines.append(f"{_fmt(t[0])} {_fmt(t[1])} {_fmt(t[2])}")
    for xyz, rgb, views in pts:
        xyz = np.asarray(xyz, np.float64)
        lines.append(f"{_fmt(xyz[0])} {_fmt(xyz[1])} {_fmt(xyz[2])}")
        lines.append(f"{int(rgb[0])} {int(rgb[1])} {int(rgb[2])}")
        parts = [str(len(views))]
        for cam, key, x, y in views:
            parts += [str(int(cam)), str(int(key)), _fmt(x), _fmt(y)]
        lines.append(" ".join(parts))
    return ("\n".join(lines) + "\n").encode()


def _recon_from_colmap_txt(tmp_path, name, cameras, images, points):
    """Build a Reconstruction through the colmap_txt reader (the record has no
    Python constructor) — the route for writer-guard / cross-codec fixtures."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "cameras.txt").write_bytes(cameras)
    (d / "images.txt").write_bytes(images)
    (d / "points3D.txt").write_bytes(points)
    return _core.read_colmap_txt(str(d))


# --- the canonical hand-authored fixture ------------------------------------
# Two cameras (SIMPLE_RADIAL k2==0 + RADIAL k2!=0), three points with multi-entry
# view lists. Camera 1's R_b = F @ perm gives the EXACT quaternion (.5,.5,.5,.5),
# and every value is a dyadic rational, so "%.17g" is short/stable AND the file
# round-trips byte-exact (its view-list keys already equal the compact per-image
# observation indices). This doubles as the golden writer blob.
FIXTURE_A = (
    b"# Bundle file v0.3\n"
    b"2 3\n"
    b"800 0.25 0\n"  # camera 0: f k1 k2  (k2==0 -> SIMPLE_RADIAL)
    b"1 0 0\n"
    b"0 1 0\n"
    b"0 0 1\n"  # R_b = I
    b"1 2 3\n"  # t_b
    b"1000 0.5 0.125\n"  # camera 1: f k1 k2  (k2!=0 -> RADIAL)
    b"0 0 1\n"
    b"-1 0 0\n"
    b"0 -1 0\n"  # R_b = F @ [[0,0,1],[1,0,0],[0,1,0]]
    b"4 5 6\n"  # t_b
    b"1.5 -2.5 3.5\n"  # point 0
    b"10 20 30\n"
    b"2 0 0 10.5 20.25 1 0 -3.5 4.5\n"
    b"0.5 0.25 -0.5\n"  # point 1
    b"40 50 60\n"
    b"1 0 1 1.25 -2.5\n"
    b"-1 2 0\n"  # point 2
    b"70 80 90\n"
    b"2 1 1 5 6 0 2 -7.5 8.5\n"
)

# A minimal golden fixture whose view-list key (500) is a real SIFT index; on
# write it is renumbered to the compact observation index 0.
GOLD_IN = (
    b"# Bundle file v0.3\n"
    b"1 1\n"
    b"800 0.5 0.25\n"
    b"1 0 0\n"
    b"0 1 0\n"
    b"0 0 1\n"
    b"1 2 3\n"
    b"1.5 -2.5 3.5\n"
    b"10 20 30\n"
    b"1 0 500 10.5 20.25\n"
)
GOLD_OUT = (
    b"# Bundle file v0.3\n"
    b"1 1\n"
    b"800 0.5 0.25\n"
    b"1 0 0\n"
    b"0 1 0\n"
    b"0 0 1\n"
    b"1 2 3\n"
    b"1.5 -2.5 3.5\n"
    b"10 20 30\n"
    b"1 0 0 10.5 20.25\n"  # key 500 -> 0
)


# ==========================================================================
# parity kind 1: cross-impl read parity (ours vs the oracle, F-flip oracle-side)
# ==========================================================================
def test_cross_impl_read_parity():
    R = _core.read_bundler(FIXTURE_A)
    o = oracle_read_bundler(FIXTURE_A)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (o["ncam"], o["ncam"], o["npts"])

    quats, trans = np.asarray(R.quaternions), np.asarray(R.translations)
    for i, cam in enumerate(o["cams"]):
        c = R.cameras[i]
        assert c.model == ("SIMPLE_RADIAL" if cam["k2"] == 0.0 else "RADIAL")
        expect = [cam["f"], 0.0, 0.0, cam["k1"]]
        if cam["k2"] != 0.0:
            expect.append(cam["k2"])
        np.testing.assert_array_equal(np.asarray(c.params), expect)
        assert (c.width, c.height) == (0, 0)
        # pose: quat-rebuilt R == F @ R_b; trans == F @ t_b (exact — pure negation)
        np.testing.assert_allclose(quat_wxyz_to_mat(quats[i]), F @ cam["R"], atol=1e-12)
        np.testing.assert_array_equal(trans[i], F @ cam["t"])

    xyz, rgb = np.asarray(R.xyz), np.asarray(R.rgb)
    for j, pt in enumerate(o["pts"]):
        np.testing.assert_array_equal(xyz[j], pt["xyz"])
        np.testing.assert_array_equal(rgb[j], pt["rgb"])
    assert xyz.dtype == np.float64 and rgb.dtype == np.uint8
    np.testing.assert_array_equal(np.asarray(R.errors), np.full(o["npts"], -1.0))
    np.testing.assert_array_equal(np.asarray(R.point3D_ids), np.arange(1, o["npts"] + 1))
    np.testing.assert_array_equal(np.asarray(R.image_ids), np.arange(1, o["ncam"] + 1))


# ==========================================================================
# parity kind 2: the oracle reads OUR writer (writer spec-correctness)
# ==========================================================================
def test_oracle_reads_our_writer():
    R = _core.read_bundler(FIXTURE_A)
    ours = oracle_read_bundler(bytes(_core.write_bundler(R)))
    orig = oracle_read_bundler(FIXTURE_A)
    assert (ours["ncam"], ours["npts"]) == (orig["ncam"], orig["npts"])
    for a, b in zip(ours["cams"], orig["cams"], strict=True):
        assert (a["f"], a["k1"], a["k2"]) == (b["f"], b["k1"], b["k2"])
        np.testing.assert_allclose(a["R"], b["R"], atol=1e-12)  # R_b passes through quat
        np.testing.assert_array_equal(a["t"], b["t"])  # pure negation -> exact
    for a, b in zip(ours["pts"], orig["pts"], strict=True):
        np.testing.assert_array_equal(a["xyz"], b["xyz"])
        np.testing.assert_array_equal(a["rgb"], b["rgb"])
        assert a["views"] == b["views"]  # cam, key, x, y all exact (canonical keys)


# ==========================================================================
# parity kind 3: byte-exact round-trip
# ==========================================================================
def test_roundtrip_bitexact():
    R = _core.read_bundler(FIXTURE_A)
    b1 = bytes(_core.write_bundler(R))
    assert b1 == FIXTURE_A  # canonical fixture -> byte-identical writer output
    R2 = _core.read_bundler(b1)
    b2 = bytes(_core.write_bundler(R2))
    assert b2 == b1
    for attr in ("quaternions", "translations", "xyz", "rgb", "errors", "image_ids", "point3D_ids"):
        np.testing.assert_array_equal(np.asarray(getattr(R2, attr)), np.asarray(getattr(R, attr)))
    assert list(R2.image_names) == list(R.image_names)
    for c2, c1 in zip(R2.cameras, R.cameras, strict=True):
        assert c2.model == c1.model and (c2.width, c2.height) == (c1.width, c1.height)
        np.testing.assert_array_equal(np.asarray(c2.params), np.asarray(c1.params))


def test_empty_model_roundtrip():
    data = b"# Bundle file v0.3\n0 0\n"
    R = _core.read_bundler(data)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (0, 0, 0)
    assert bytes(_core.write_bundler(R)) == data


# ==========================================================================
# THE convention pin — hand-derived external ground truth (unfakeable)
# ==========================================================================
FLIP_FIXTURE = bundler_build(
    cams=[
        (800.0, 0.0, 0.0, np.eye(3), [1.0, 2.0, 3.0]),
        (600.0, 0.0, 0.0, np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float), [0.0, 0.0, 0.0]),
        # camera 2 — ASYMMETRIC flip: R_b = [[0,0,1],[-1,0,0],[0,-1,0]] gives
        # R' = F @ R_b = the cyclic permutation [[0,0,1],[1,0,0],[0,1,0]], which is
        # NOT symmetric (R' != R'^T), so its quaternion discriminates a transposed /
        # conjugated (camera_to_world-stored) implementation that cams 0 and 1 — both
        # with symmetric R' — cannot. Hand-derived q = (0.5,0.5,0.5,0.5) (120 deg
        # about (1,1,1)/sqrt3, Shepperd z-branch with s=2 -> every quotient dyadic).
        (700.0, 0.0, 0.0, np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]], float), [0.0, 0.0, 0.0]),
    ],
    pts=[],
)


def test_axis_flip_pin():
    R = _core.read_bundler(FLIP_FIXTURE)
    assert R.quaternion_order == "wxyz"
    assert R.pose_convention == "world_to_camera"
    quats, trans = np.asarray(R.quaternions), np.asarray(R.translations)

    # camera 0: R_b = I, t_b = (1,2,3)  ->  q = (0,1,0,0) EXACT, t = (1,-2,-3) EXACT
    np.testing.assert_array_equal(quats[0], [0.0, 1.0, 0.0, 0.0])
    np.testing.assert_array_equal(trans[0], [1.0, -2.0, -3.0])

    # camera 1: R_b = Rz(90) -> R' = F @ Rz(90) = [[0,-1,0],[-1,0,0],[0,0,-1]],
    # q = ±(0, -sqrt(2)/2, sqrt(2)/2, 0)
    Rp = np.array([[0, -1, 0], [-1, 0, 0], [0, 0, -1]], float)
    np.testing.assert_allclose(quat_wxyz_to_mat(quats[1]), Rp, atol=1e-12)
    s = np.sqrt(2.0) / 2.0
    assert_quats_upto_sign(quats[1], np.array([0.0, -s, s, 0.0]), atol=1e-12)

    # camera 2: asymmetric R' = [[0,0,1],[1,0,0],[0,1,0]] -> q = (0.5,0.5,0.5,0.5)
    # BIT-EXACT (Shepperd z-branch, s=2). A camera_to_world (transposed) impl would
    # store q = (-0.5,0.5,0.5,0.5), which fails this even up to sign, so this pin —
    # not just the allclose-vs-oracle parity test — anchors R vs R^T directly.
    np.testing.assert_array_equal(quats[2], [0.5, 0.5, 0.5, 0.5])


# ==========================================================================
# end-to-end projection-consistency pin (pose + intrinsics + obs frame)
# ==========================================================================
def _bundler_project(X, R_b, t_b, f, k1, k2=0.0):
    P = R_b @ X + t_b
    p = -P[:2] / P[2]
    r = 1.0 + k1 * (p @ p) + k2 * (p @ p) ** 2
    return f * r * p  # (x_b, y_b), center-origin y-up


def _colmap_simple_radial_project(X, R_c, t_c, f, k1, cx=0.0, cy=0.0):
    Pc = R_c @ X + t_c
    u, v = Pc[0] / Pc[2], Pc[1] / Pc[2]
    d = 1.0 + k1 * (u * u + v * v)
    return np.array([f * u * d + cx, f * v * d + cy])


def test_projection_consistency_pin():
    # X is IN FRONT of the Bundler camera: P = R_b @ X + t_b = (0.6, -0.4, -2.3) has
    # P.z < 0 (Bundler looks down -Z), so this models a real, visible observation
    # (COLMAP-frame depth +2.3). R_b = Rx(90) is chosen so R' = F @ Rx90 =
    # [[1,0,0],[0,0,1],[0,-1,0]] is NON-symmetric — the end-to-end pin then also
    # discriminates a transposed rotation (R vs R^T), not only sign/flip errors.
    X = np.array([0.5, -0.3, 0.6])
    R_b = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)  # Rx(90)
    t_b = np.array([0.1, 0.2, -2.0])
    f, k1 = 1000.0, 0.01
    xb, yb = _bundler_project(X, R_b, t_b, f, k1)

    data = bundler_build(cams=[(f, k1, 0.0, R_b, t_b)], pts=[(X, (10, 20, 30), [(0, 0, xb, yb)])])
    R = _core.read_bundler(data)
    q = np.asarray(R.quaternions)[0]
    t_c = np.asarray(R.translations)[0]
    params = np.asarray(R.cameras[0].params)  # {f, 0, 0, k1}

    # Reproject X through COLMAP SIMPLE_RADIAL using OUR converted record: it must
    # equal the observation the reader stored, (x_b, -y_b).
    pred = _colmap_simple_radial_project(X, quat_wxyz_to_mat(q), t_c, params[0], params[3])
    np.testing.assert_allclose(pred, [xb, -yb], atol=1e-9)

    # And the writer folds it back to the original Bundler view coordinate.
    o = oracle_read_bundler(bytes(_core.write_bundler(R)))
    _, _, wx, wy = o["pts"][0]["views"][0]
    np.testing.assert_allclose([wx, wy], [xb, yb], atol=1e-9)


# ==========================================================================
# observation / id / model conventions
# ==========================================================================
def test_obs_and_ids_pin():
    R = _core.read_bundler(FIXTURE_A)
    np.testing.assert_array_equal(np.asarray(R.point3D_ids), [1, 2, 3])  # 1-based
    np.testing.assert_array_equal(np.asarray(R.image_ids), [1, 2])
    np.testing.assert_array_equal(np.asarray(R.image_camera_ids), [1, 2])
    np.testing.assert_array_equal(np.asarray(R.errors), [-1.0, -1.0, -1.0])  # sentinel
    assert list(R.image_names) == ["", ""]  # names live in list.txt
    assert R.cameras[0].model == "SIMPLE_RADIAL"  # k2 == 0
    assert R.cameras[1].model == "RADIAL"  # k2 != 0
    assert all((c.width, c.height) == (0, 0) for c in R.cameras)

    # point 0 / camera 0 view (10.5, 20.25) is stored (10.5, -20.25); the writer
    # (cx=cy=0) returns it to (10.5, 20.25).
    o = oracle_read_bundler(bytes(_core.write_bundler(R)))
    cam, _, x, y = o["pts"][0]["views"][0]
    assert (cam, x, y) == (0, 10.5, 20.25)


def test_observations_via_colmap_txt(tmp_path):
    # The Reconstruction binding exposes no obs/track arrays, and the bundler
    # writer never reads obs_pt3d, so route the record through the already-wired,
    # INDEPENDENT colmap_txt writer to pin what the bundler suite otherwise can't
    # see: the per-image CSR obs order, the stored y-flip (x, -y), AND the 1-based
    # obs->point3D_id back-references (obs_pt3d) — scrambling or zeroing them would
    # silently corrupt bundler->COLMAP exports yet pass every other test here.
    R = _core.read_bundler(FIXTURE_A)
    _core.write_colmap_txt(R, str(tmp_path))
    img_txt = (tmp_path / "images.txt").read_bytes()
    # image 1 CSR: (10.5,-20.25)->pt 1, (1.25,2.5)->pt 2, (-7.5,-8.5)->pt 3
    assert b"10.5 -20.25 1 1.25 2.5 2 -7.5 -8.5 3" in img_txt
    # image 2 CSR: (-3.5,-4.5)->pt 1, (5,-6)->pt 3
    assert b"-3.5 -4.5 1 5 -6 3" in img_txt


# ==========================================================================
# golden writer blob + documented key renumbering
# ==========================================================================
def test_golden_writer_blob():
    R = _core.read_bundler(GOLD_IN)
    assert bytes(_core.write_bundler(R)) == GOLD_OUT


def test_foreign_key_is_renumbered_to_compact_index():
    o = oracle_read_bundler(bytes(_core.write_bundler(_core.read_bundler(GOLD_IN))))
    assert o["pts"][0]["views"][0][1] == 0  # SIFT key 500 -> compact obs index 0


# ==========================================================================
# unregistered (all-zero) camera blocks
# ==========================================================================
def _three_cam_middle_unregistered(views):
    return bundler_build(
        cams=[
            (800.0, 0.0, 0.0, np.eye(3), [0, 0, 0]),
            (0.0, 0.0, 0.0, np.zeros((3, 3)), [0, 0, 0]),  # all-zero -> unregistered
            (700.0, 0.0, 0.0, np.eye(3), [1, 1, 1]),
        ],
        pts=[(np.array([0.0, 0.0, 5.0]), (1, 2, 3), views)],
    )


def test_unregistered_camera_skip():
    # point sees the two registered cameras (file indices 0 and 2)
    R = _core.read_bundler(_three_cam_middle_unregistered([(0, 0, 1.0, 2.0), (2, 0, 3.0, 4.0)]))
    assert R.num_images == 2
    np.testing.assert_array_equal(np.asarray(R.image_ids), [1, 3])  # 1-based file position
    assert [c.id for c in R.cameras] == [1, 3]

    # write-side COMPACTION: the 3-camera file (with a hole at file position 1)
    # re-writes as a DENSE 2-camera file, so the point's view-list camera indices
    # must remap to the compact record rows [0, 1] — NOT the original file
    # positions [0, 2]. A writer emitting img_id-1 would put camera index 2 in a
    # 2-camera file (an invalid .out); this pins the remap to the record row.
    written = bytes(_core.write_bundler(R))
    o = oracle_read_bundler(written)
    assert o["ncam"] == 2
    assert sorted(v[0] for v in o["pts"][0]["views"]) == [0, 1]
    R2 = _core.read_bundler(written)  # the compacted file re-reads with dense ids
    np.testing.assert_array_equal(np.asarray(R2.image_ids), [1, 2])


def test_view_list_references_unregistered_raises():
    with pytest.raises(ValueError, match="unregistered"):
        _core.read_bundler(_three_cam_middle_unregistered([(1, 0, 1.0, 2.0)]))  # cam 1 == skipped


def test_zero_focal_with_nonzero_block_raises():
    data = bundler_build(cams=[(0.0, 0.0, 0.0, np.eye(3), [1, 2, 3])], pts=[])  # f=0, R=I nonzero
    with pytest.raises(ValueError, match="zero focal"):
        _core.read_bundler(data)


def test_nonfinite_pose_reader_accepts_writer_rejects():
    # fast_float accepts "nan"/"inf" tokens, so a foreign .out reads a non-finite
    # translation into the record VERBATIM (documented acceptance) ...
    data = bundler_build(cams=[(800.0, 0.0, 0.0, np.eye(3), [float("nan"), 2.0, 3.0])], pts=[])
    R = _core.read_bundler(data)
    assert np.isnan(np.asarray(R.translations)[0, 0])
    # ... but the writer REFUSES to serialize it rather than emitting MSVC's
    # unparseable "nan(ind)" via "%.17g" (refuse-not-convert, forcing the decision).
    with pytest.raises(ValueError, match="non-finite"):
        _core.write_bundler(R)


# ==========================================================================
# malformed input raises ValueError (FormatError-mappable), never crashes
# ==========================================================================
_BASE_CAM = b"800 0 0\n1 0 0\n0 1 0\n0 0 1\n0 0 0\n"  # f=800, R=I, t=0 (registered)


def _one_cam_one_pt(pt_body: bytes) -> bytes:
    return b"# Bundle file v0.3\n1 1\n" + _BASE_CAM + pt_body


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"2 3\n800 0 0\n", "header"),  # missing header line
        (b"# Bundle file v0.4\n0 0\n", "unsupported"),  # wrong version
        (b"# Bundle file v0.3\nfoo 0\n", "bad integer"),  # non-integer count
        (
            b"# Bundle file v0.3\n5000000000 0\n",
            "too large",
        ),  # ncam > 0xFFFFFFFE (uint32 id overflow)
        (b"# Bundle file v0.3\n999999999 1\n800 0 0\n", "exceed file size"),  # count bomb
        (b"# Bundle file v0.3\n1 0\n800 0 0\n1 0 0\n0 1 0\n", "missing field"),  # truncated mid-R
        (
            b"# Bundle file v0.3\n1 0\nfoo 0 0\n1 0 0\n0 1 0\n0 0 1\n0 0 0\n",
            "bad number",
        ),  # non-numeric focal
        (_one_cam_one_pt(b"1.5 -2.5 3.5\n300 20 30\n1 0 0 10.5 20.25\n"), "0..255"),  # rgb 300
        (_one_cam_one_pt(b"1.5 -2.5 3.5\n-1 20 30\n1 0 0 10.5 20.25\n"), "bad integer"),  # rgb -1
        (
            _one_cam_one_pt(b"1.5 -2.5 3.5\n12.5 20 30\n1 0 0 10.5 20.25\n"),
            "bad integer",
        ),  # rgb float
        (
            _one_cam_one_pt(b"1.5 -2.5 3.5\n10 20 30\n5 0 0 10.5 20.25\n"),
            "missing field",
        ),  # m>entries
        (
            _one_cam_one_pt(b"1.5 -2.5 3.5\n10 20 30\n1 1 0 10.5 20.25\n"),
            "out of range",
        ),  # cam>=ncam
        (b"# Bundle file v0.3\n# 0\n", "bad integer"),  # '#' token where a count is expected
        (
            _one_cam_one_pt(b"1.5 -2.5 3.5\n10 20 30\n0\nEXTRA\n"),
            "trailing data",
        ),  # junk after last
    ],
)
def test_malformed_raises(data, match):
    with pytest.raises(ValueError, match=match):
        _core.read_bundler(data)


def test_fuzz_single_byte_mutation_no_crash():
    base = GOLD_IN
    for i in range(len(base)):
        for repl in (0x00, 0x23, 0x39, 0x20, 0xFF, 0x0A):  # NUL '#' '9' ' ' 0xFF '\n'
            try:
                _core.read_bundler(base[:i] + bytes([repl]) + base[i + 1 :])
            except ValueError:
                pass


# ==========================================================================
# writer guards (refusable records built through the colmap_txt reader)
# ==========================================================================
_IMG_1OBS = b"1 1 0 0 0 0 0 0 1 a.png\n100 200 5\n"  # image 1, one observation at (100,200)
_IMG_0OBS = b"1 1 0 0 0 0 0 0 1 a.png\n\n"


def test_writer_guard_unsupported_model(tmp_path):
    R = _recon_from_colmap_txt(
        tmp_path,
        "opencv",
        b"1 OPENCV 640 480 500 500 320 240 0.1 0.2 0.001 0.002\n",
        _IMG_0OBS,
        b"5 1 2 3 10 20 30 0.5\n",
    )
    with pytest.raises(ValueError, match="not representable"):
        _core.write_bundler(R)


def test_writer_guard_pinhole_fx_ne_fy(tmp_path):
    R = _recon_from_colmap_txt(
        tmp_path,
        "pin_ne",
        b"1 PINHOLE 640 480 500 510 320 240\n",
        _IMG_0OBS,
        b"5 1 2 3 10 20 30 0.5\n",
    )
    with pytest.raises(ValueError, match="fx != fy"):
        _core.write_bundler(R)


def test_writer_guard_non_positive_focal(tmp_path):
    R = _recon_from_colmap_txt(
        tmp_path,
        "zerof",
        b"1 SIMPLE_PINHOLE 640 480 0 320 240\n",
        _IMG_0OBS,
        b"5 1 2 3 10 20 30 0.5\n",
    )
    with pytest.raises(ValueError, match="focal"):
        _core.write_bundler(R)


def test_writer_guard_track_out_of_range_observation(tmp_path):
    R = _recon_from_colmap_txt(
        tmp_path,
        "oor",
        b"1 SIMPLE_PINHOLE 640 480 500 320 240\n",
        _IMG_1OBS,
        b"5 1 2 3 10 20 30 0.5 1 99\n",  # track (image 1, point2D_idx 99) but image 1 has 1 obs
    )
    with pytest.raises(ValueError, match="out-of-range observation"):
        _core.write_bundler(R)


def test_writer_guard_track_unknown_image(tmp_path):
    R = _recon_from_colmap_txt(
        tmp_path,
        "unk",
        b"1 SIMPLE_PINHOLE 640 480 500 320 240\n",
        _IMG_1OBS,
        b"5 1 2 3 10 20 30 0.5 7 0\n",  # track references image 7 (does not exist)
    )
    with pytest.raises(ValueError, match="unknown image"):
        _core.write_bundler(R)


# ==========================================================================
# COLMAP -> Bundler cross-codec: the writer-side principal-point fold
# ==========================================================================
def test_colmap_to_bundler_principal_point_fold(tmp_path):
    # PINHOLE fx==fy with a nonzero principal point; identity pose; one obs.
    R = _recon_from_colmap_txt(
        tmp_path,
        "c2b",
        b"1 PINHOLE 640 480 500 500 320 240\n",
        _IMG_1OBS,  # obs (100, 200) -> point 5
        b"5 1.5 -2.5 3.5 10 20 30 0.5 1 0\n",  # track (image 1, point2D_idx 0)
    )
    o = oracle_read_bundler(bytes(_core.write_bundler(R)))
    assert (o["ncam"], o["npts"]) == (1, 1)
    cam = o["cams"][0]
    assert (cam["f"], cam["k1"], cam["k2"]) == (500.0, 0.0, 0.0)

    q = np.asarray(R.quaternions)[0]
    t = np.asarray(R.translations)[0]
    np.testing.assert_allclose(cam["R"], F @ quat_wxyz_to_mat(q), atol=1e-12)  # R_b = F @ R'
    np.testing.assert_allclose(cam["t"], F @ t, atol=1e-12)  # t_b = F @ t

    # (X - cx, cy - Y) = (100 - 320, 240 - 200) = (-220, 40)
    _, _, x, y = o["pts"][0]["views"][0]
    np.testing.assert_allclose([x, y], [100.0 - 320.0, 240.0 - 200.0], atol=1e-9)


# ==========================================================================
# optional secondary oracle: pycolmap's own ExportBundler
# ==========================================================================
def test_pycolmap_export_parity(tmp_path):
    pycolmap = pytest.importorskip("pycolmap")
    opts = pycolmap.SyntheticDatasetOptions()
    opts.num_points3D = 30
    rec = pycolmap.synthesize_dataset(opts)
    if not hasattr(rec, "export_bundler"):
        pytest.skip("this pycolmap has no Reconstruction.export_bundler")

    out = tmp_path / "b"
    out.mkdir()
    bundle_path, list_path = str(out / "bundle.out"), str(out / "list.txt")
    try:
        rec.export_bundler(bundle_path, list_path)
    except Exception as exc:  # API/signature drift -> skip, per the optional-oracle contract
        pytest.skip(f"export_bundler unavailable/failed: {exc}")

    R = _core.read_bundler(Path(bundle_path).read_bytes())
    names = [ln.split()[0] for ln in Path(list_path).read_text().split("\n") if ln.strip()]
    assert R.num_cameras == len(names) > 0

    # point-cloud parity (order-independent): sorted xyz + rgb.
    theirs = np.array([np.asarray(p.xyz) for p in rec.points3D.values()], np.float64)
    ours = np.asarray(R.xyz)
    assert ours.shape == theirs.shape
    np.testing.assert_allclose(ours[np.lexsort(ours.T)], theirs[np.lexsort(theirs.T)], atol=1e-4)

    # pose parity, aligned by list.txt order: our stored R' == pycolmap's
    # cam_from_world rotation (Bundler stores R_b = F @ R'); guarded on name lookup.
    by_name = {im.name: im for im in rec.images.values()}
    quats, trans = np.asarray(R.quaternions), np.asarray(R.translations)
    checked = 0
    for k, nm in enumerate(names):
        im = by_name.get(nm)
        if im is None:
            continue
        M = np.asarray(im.cam_from_world().matrix())[:3]  # 3x4 [R'|t']
        np.testing.assert_allclose(quat_wxyz_to_mat(quats[k]), M[:, :3], atol=1e-4)
        np.testing.assert_allclose(trans[k], M[:, 3], atol=1e-4)
        checked += 1
    if checked == 0:  # list.txt name format did not align to rec image names -> convention drift
        pytest.skip("could not align list.txt names to pycolmap image names")


# ==========================================================================
# registry integration (skips until the integrator wires the codec)
# ==========================================================================
def _bundler_codec():
    try:
        from sceneio.io import registry
    except Exception:
        return None
    return registry.REGISTRY.get("bundler")


def test_registry_detect_and_roundtrip(tmp_path):
    if _bundler_codec() is None:
        pytest.skip("bundler codec not wired into the registry yet (integrator step)")
    from sceneio.io import read as io_read
    from sceneio.io import registry
    from sceneio.io import write as io_write

    p = tmp_path / "model.out"
    p.write_bytes(FIXTURE_A)
    assert registry.detect(str(p)) == "bundler"  # by extension

    pm = tmp_path / "bundle_noext"
    pm.write_bytes(FIXTURE_A)
    assert registry.detect(str(pm)) == "bundler"  # extensionless -> b"# Bundle file" magic

    R = io_read(str(p), format="bundler")
    out = tmp_path / "rt.out"
    io_write(R, str(out), format="bundler")
    R2 = io_read(str(out), format="bundler")
    np.testing.assert_array_equal(np.asarray(R2.xyz), np.asarray(R.xyz))
    np.testing.assert_array_equal(np.asarray(R2.quaternions), np.asarray(R.quaternions))


# ==========================================================================
# numpy / torch interop
# ==========================================================================
def test_zero_copy_views_and_torch():
    R = _core.read_bundler(FIXTURE_A)
    xyz = R.xyz  # zero-copy view; R kept alive by reference_internal
    assert isinstance(xyz, np.ndarray) and xyz.shape == (R.num_points3D, 3)
    assert xyz.dtype == np.float64
    torch = pytest.importorskip("torch")
    t = torch.from_dlpack(R.xyz)
    assert np.array_equal(t.numpy(), np.asarray(R.xyz))
