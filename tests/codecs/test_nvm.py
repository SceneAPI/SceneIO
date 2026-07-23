"""Parity suite for the VisualSFM NVM_V3 codec (nvm.cpp -> Reconstruction).

Oracle: a tiny self-contained pure-Python parser (VisualSFM ships no pip
bindings and pycolmap has no NVM reader), mirroring the whitespace token-stream
grammar independently of the C++. The pose convention is the crux and is pinned
against HAND-DERIVED external ground truth (not the mirror): the NVM quaternion
is the WXYZ world_to_camera rotation (== COLMAP qvec, stored verbatim) and NVM
stores the camera CENTER C, so t = -R*C on read / C = -R^T*t on write.

Everything stored verbatim (quats, xyz, rgb, focal, radial, obs, names) compares
BIT-EXACT; only ``translations`` is derived (-R*C) so its cross-impl / round-trip
comparisons use a documented eps, except the convention-pin cameras whose R has
exact-FP (0/+-1) entries — those assert bit-exact.

The Reconstruction binding exposes no observation/track accessors, so the obs/
track CSR is validated end-to-end through the writer (oracle-parse ``write_nvm``
output) and cross-checked through the independent ``write_colmap_txt`` writer.
"""

from __future__ import annotations

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover - exercised only in a non-built tree
    _core = None

pytestmark = pytest.mark.skipif(
    _core is None,
    reason="sceneio._core not built (compiled-only package — build the extension first)",
)


# --- rotation from a WXYZ quaternion, formula-identical to the C++ codec -----
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


# --- pure-Python oracle: an independent NVM_V3 parser / emitter --------------
def oracle_read_nvm(data: bytes) -> dict:
    toks = data.decode().split()
    i = 0

    def nxt() -> str:
        nonlocal i
        v = toks[i]
        i += 1
        return v

    assert nxt() == "NVM_V3"
    ncam = int(nxt())
    cams = []
    for _ in range(ncam):
        name = nxt()
        f = float(nxt())
        q = np.array([float(nxt()) for _ in range(4)], np.float64)
        c = np.array([float(nxt()) for _ in range(3)], np.float64)
        radial = float(nxt())
        float(nxt())  # placeholder token
        cams.append({"name": name, "f": f, "q": q, "C": c, "r": radial})
    npts = int(nxt())
    pts = []
    for _ in range(npts):
        xyz = np.array([float(nxt()) for _ in range(3)], np.float64)
        rgb = np.array([int(nxt()) for _ in range(3)], np.uint8)
        m = int(nxt())
        meas = [(int(nxt()), int(nxt()), float(nxt()), float(nxt())) for _ in range(m)]
        pts.append({"xyz": xyz, "rgb": rgb, "meas": meas})
    return {"ncam": ncam, "cams": cams, "npts": npts, "pts": pts}


def oracle_write_nvm(cams, pts) -> bytes:
    """Emit NVM with its OWN formatting (repr floats) — the ws-agnostic reader
    must accept it; used to synthesize parity inputs."""
    lines = ["NVM_V3", str(len(cams))]
    for c in cams:
        parts = [c["name"], repr(float(c["f"]))]
        parts += [repr(float(v)) for v in c["q"]]
        parts += [repr(float(v)) for v in c["C"]]
        parts += [repr(float(c["r"])), "0"]
        lines.append(" ".join(parts))
    lines.append(str(len(pts)))
    for p in pts:
        parts = [repr(float(v)) for v in p["xyz"]]
        parts += [str(int(v)) for v in p["rgb"]]
        parts.append(str(len(p["meas"])))
        for img, feat, x, y in p["meas"]:
            parts += [str(int(img)), str(int(feat)), repr(float(x)), repr(float(y))]
        lines.append(" ".join(parts))
    lines.append("0")
    return ("\n".join(lines) + "\n").encode()


# --- helpers ----------------------------------------------------------------
def _meas_no_feat(pts) -> list:
    """Per-point measurements (img, x, y), dropping the re-based feature index."""
    return [[(img, x, y) for (img, _feat, x, y) in p["meas"]] for p in pts]


def our_measurements(R) -> list:
    """Re-derive per-point (img, x, y) by writing to NVM and oracle-parsing —
    the only way to inspect the obs/track CSR the binding does not surface."""
    return _meas_no_feat(oracle_read_nvm(bytes(_core.write_nvm(R)))["pts"])


def assert_measurements_equal(a, b) -> None:
    assert len(a) == len(b)
    for ma, mb in zip(a, b, strict=True):
        assert len(ma) == len(mb)
        for (ia, xa, ya), (ib, xb, yb) in zip(ma, mb, strict=True):
            assert ia == ib
            assert xa == xb and ya == yb  # verbatim obs -> %.17g -> exact round-trip


def _colmap_record(tmp_path, name: str, cameras: bytes, images: bytes, points: bytes):
    """Build a Reconstruction through the COLMAP-text reader (the record has no
    Python constructor) — the established path for writer-guard fixtures."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "cameras.txt").write_bytes(cameras)
    (d / "images.txt").write_bytes(images)
    (d / "points3D.txt").write_bytes(points)
    return _core.read_colmap_txt(str(d))


def _synth(ncam=6, npts=40, seed=0):
    rng = np.random.default_rng(seed)
    cams = []
    for k in range(ncam):
        q = rng.standard_normal(4)
        # Non-unit norm on purpose: the codec MUST normalize before deriving t = -R*C,
        # so a non-normalizing reader diverges here too (not only at the exact-FP pin).
        q = q / np.linalg.norm(q) * (2.0 + k)
        cams.append(
            {
                "name": f"img{k}.jpg",
                "f": float(500 + k),
                "q": q,
                "C": rng.standard_normal(3),
                "r": 0.0 if k % 2 == 0 else float(rng.uniform(-0.1, 0.1)),
            }
        )
    pts = []
    for j in range(npts):
        nm = int(rng.integers(1, min(4, ncam + 1)))
        imgs = rng.choice(ncam, size=nm, replace=False)
        meas = [
            (int(im), int(j * 100 + e), float(rng.standard_normal()), float(rng.standard_normal()))
            for e, im in enumerate(imgs)
        ]
        pts.append({"xyz": rng.standard_normal(3), "rgb": rng.integers(0, 256, 3), "meas": meas})
    return cams, pts


# A hand fixture exercising tabs / CRLF / blank lines / multi-token-per-line.
HAND_NVM = (
    b"NVM_V3\r\n"
    b"2\r\n"
    b"a.jpg 800 0.5 0.5 0.5 0.5 1 2 3 0 0\r\n"
    b"b.jpg\t700\t1 0 0 0   4 5 6 0.25 0\r\n"  # r != 0 -> SIMPLE_RADIAL
    b"\r\n"
    b"3\r\n"
    b"1.5 -2.5 3.5 10 20 30 2  0 7 4.5 -5.5  1 9 6.5 -7.5\r\n"  # seen by cam 0 and cam 1
    b"0.25 0.75 -1.25 40 50 60 1  1 3 8.5 -9.5\r\n"
    b"10 11 12 200 100 50 1  0 5 0.5 0.5\r\n"
    b"0\r\n"
)

# The golden fixture: exactly-representable doubles so %.17g emits short, stable
# strings; read -> write must reproduce it byte-for-byte (canonical layout).
GOLDEN_NVM = (
    b"NVM_V3\n1\na.jpg 800 0.5 0.5 0.5 0.5 1 2 3 0 0\n1\n1.5 -2.5 3.5 10 20 30 1 0 0 4.5 -5.5\n0\n"
)


# ==========================================================================
# cross-impl parity (kind 1)
# ==========================================================================
def _check_against_oracle(data: bytes) -> None:
    parsed = oracle_read_nvm(data)
    R = _core.read_nvm(data)
    assert R.num_cameras == parsed["ncam"]
    assert R.num_images == parsed["ncam"]
    assert R.num_points3D == parsed["npts"]

    q, t = np.asarray(R.quaternions), np.asarray(R.translations)
    names = list(R.image_names)
    cams = {c.id: c for c in R.cameras}
    for k, oc in enumerate(parsed["cams"]):
        assert names[k] == oc["name"]
        np.testing.assert_array_equal(q[k], oc["q"])  # verbatim
        cam = cams[k + 1]
        assert (cam.width, cam.height) == (0, 0)
        params = np.asarray(cam.params)
        assert params[0] == oc["f"]
        if oc["r"] == 0.0:
            assert cam.model == "SIMPLE_PINHOLE"
            np.testing.assert_array_equal(params, [oc["f"], 0.0, 0.0])
        else:
            assert cam.model == "SIMPLE_RADIAL"
            np.testing.assert_array_equal(params, [oc["f"], 0.0, 0.0, oc["r"]])
        # translation is the one derived field: t = -R*C
        np.testing.assert_allclose(
            t[k], -quat_wxyz_to_mat(oc["q"]) @ oc["C"], rtol=1e-13, atol=1e-15
        )

    xyz, rgb, err = np.asarray(R.xyz), np.asarray(R.rgb), np.asarray(R.errors)
    for j, op in enumerate(parsed["pts"]):
        np.testing.assert_array_equal(xyz[j], op["xyz"])
        np.testing.assert_array_equal(rgb[j], op["rgb"])
    assert xyz.dtype == np.float64 and rgb.dtype == np.uint8
    assert err.size == parsed["npts"] and np.all(err == -1.0)

    # obs/track CSR: our writer's measurements must reproduce the fixture's
    # (img, x, y) per point (feature indices are re-based, so dropped).
    assert_measurements_equal(our_measurements(R), _meas_no_feat(parsed["pts"]))


def test_cross_impl_equality_hand_fixture():
    _check_against_oracle(HAND_NVM)


def test_cross_impl_equality_synthesized():
    cams, pts = _synth()
    _check_against_oracle(oracle_write_nvm(cams, pts))


# ==========================================================================
# THE convention pin — hand-derived exact-FP ground truth
# ==========================================================================
def test_center_to_translation_pin():
    data = (
        b"NVM_V3\n4\n"
        b"a.jpg 800 0.5 0.5 0.5 0.5 1 2 3 0 0\n"  # R = perm [[0,0,1],[1,0,0],[0,1,0]]
        b"b.jpg 700 1 0 0 0 4 5 6 0 0\n"  # identity
        b"c.jpg 600 2 0 0 0 7 8 9 0 0\n"  # unnormalized scalar quat (still R = I)
        b"d.jpg 500 0 2 0 0 11 12 13 0 0\n"  # scaled VECTOR quat: norm 2 -> q_hat=(0,1,0,0)
        b"0\n0\n"
    )
    R = _core.read_nvm(data)
    q, t = np.asarray(R.quaternions), np.asarray(R.translations)

    # quaternions stored VERBATIM (including the unnormalized [2,0,0,0] / [0,2,0,0]).
    np.testing.assert_array_equal(q[0], [0.5, 0.5, 0.5, 0.5])
    np.testing.assert_array_equal(q[1], [1.0, 0.0, 0.0, 0.0])
    np.testing.assert_array_equal(q[2], [2.0, 0.0, 0.0, 0.0])
    np.testing.assert_array_equal(q[3], [0.0, 2.0, 0.0, 0.0])

    # t = -R(q_hat)*C, BIT-EXACT for these exact-arithmetic rotations.
    np.testing.assert_array_equal(t[0], [-3.0, -1.0, -2.0])
    np.testing.assert_array_equal(t[1], [-4.0, -5.0, -6.0])
    np.testing.assert_array_equal(t[2], [-7.0, -8.0, -9.0])
    # NORMALIZE-BEFORE-DERIVE (non-vacuous): q=(0,2,0,0) normalizes to (0,1,0,0) so
    # R = diag(1,-1,-1) and t = -R*(11,12,13) = (-11, 12, 13). An impl that derives R
    # from the RAW quat gets diag(1,-7,-7) -> t = (-11, 84, 91) and FAILS this line.
    np.testing.assert_array_equal(t[3], [-11.0, 12.0, 13.0])

    # writer inverse: emitted centers reappear verbatim. Centers are DISTINCT per camera
    # (d uses 11,12,13, not 1,2,3) so b" 1 2 3 " stays a genuine camera-a discriminator:
    # d's symmetric R=diag(1,-1,-1) would otherwise satisfy b" 1 2 3 " under a transpose.
    out = bytes(_core.write_nvm(R))
    assert b" 1 2 3 " in out and b" 4 5 6 " in out and b" 7 8 9 " in out
    assert b" 11 12 13 " in out


def test_projection_consistency_pin():
    # End-to-end pin tying pose CONVENTION + focal + the image-center 2D anchor: the
    # 3D point projected through the RECORD's (q, t, f) must reproduce the stored
    # measurement. Uses an ASYMMETRIC rotation (cyclic permutation, R != R^T), so a
    # transposed/conjugated pose fails here. q=(0.5,0.5,0.5,0.5) -> R = (x->y->z->x);
    # C=(1,2,3) -> t=(-3,-1,-2); X=(3,6,4) -> P = R@X + t = (1,2,4); obs = 800*(1/4, 2/4).
    data = b"NVM_V3\n1\na.jpg 800 0.5 0.5 0.5 0.5 1 2 3 0 0\n1\n3 6 4 10 20 30 1 0 0 200 400\n0\n"
    R = _core.read_nvm(data)
    q = np.asarray(R.quaternions)[0]
    t = np.asarray(R.translations)[0]
    f = np.asarray({c.id: c for c in R.cameras}[1].params)[0]

    X = np.array([3.0, 6.0, 4.0])
    P = quat_wxyz_to_mat(q) @ X + t  # (1, 2, 4), exact (R has 0/1 entries, t integral)
    predicted = np.array([f * P[0] / P[2], f * P[1] / P[2]])
    np.testing.assert_array_equal(predicted, [200.0, 400.0])  # 800*1/4, 800*2/4 -> exact
    # and the stored measurement recovered through the independent writer matches.
    assert our_measurements(R) == [[(0, 200.0, 400.0)]]


def test_pose_convention_metadata_and_identity():
    assert _core.read_nvm(GOLDEN_NVM).quaternion_order == "wxyz"
    assert _core.read_nvm(GOLDEN_NVM).pose_convention == "world_to_camera"
    # defining property for every camera of the synthesized file: R*C + t == 0.
    cams, pts = _synth()
    data = oracle_write_nvm(cams, pts)
    R = _core.read_nvm(data)
    t = np.asarray(R.translations)
    for k, c in enumerate(cams):
        np.testing.assert_allclose(quat_wxyz_to_mat(c["q"]) @ c["C"] + t[k], 0.0, atol=1e-12)


# ==========================================================================
# intrinsics, round-trips, writer spec-correctness
# ==========================================================================
def test_model_mapping():
    data = (
        b"NVM_V3\n2\n"
        b"p.jpg 500 1 0 0 0 0 0 0 0 0\n"  # r == 0 -> SIMPLE_PINHOLE
        b"r.jpg 600 1 0 0 0 0 0 0 0.1 0\n"  # r != 0 -> SIMPLE_RADIAL
        b"0\n0\n"
    )
    R = _core.read_nvm(data)
    cams = {c.id: c for c in R.cameras}
    assert cams[1].model == "SIMPLE_PINHOLE"
    np.testing.assert_array_equal(np.asarray(cams[1].params), [500.0, 0.0, 0.0])
    assert cams[2].model == "SIMPLE_RADIAL"
    np.testing.assert_array_equal(np.asarray(cams[2].params), [600.0, 0.0, 0.0, 0.1])


def test_roundtrip_ours():
    cams, pts = _synth(seed=3)
    R = _core.read_nvm(oracle_write_nvm(cams, pts))
    R2 = _core.read_nvm(bytes(_core.write_nvm(R)))
    for attr in ("quaternions", "xyz", "point3D_ids", "image_ids", "image_camera_ids", "errors"):
        np.testing.assert_array_equal(np.asarray(getattr(R2, attr)), np.asarray(getattr(R, attr)))
    np.testing.assert_array_equal(np.asarray(R2.rgb), np.asarray(R.rgb))
    assert list(R2.image_names) == list(R.image_names)
    for c2, c1 in zip(R2.cameras, R.cameras, strict=True):
        assert c2.model == c1.model
        np.testing.assert_array_equal(np.asarray(c2.params), np.asarray(c1.params))
    # trans: derived, so eps in general.
    np.testing.assert_allclose(
        np.asarray(R2.translations), np.asarray(R.translations), rtol=1e-13, atol=1e-15
    )
    assert_measurements_equal(our_measurements(R2), our_measurements(R))


def test_write_read_write_is_value_stable():
    # NVM stores the camera CENTER while the record stores translation, so the
    # C = -R^T*t <-> t = -R*C round-trip is value-stable but NOT byte-stable across
    # cycles (R R^T != I to the ULP). Assert VALUE parity, not byte identity.
    cams, pts = _synth(seed=7)
    R = _core.read_nvm(oracle_write_nvm(cams, pts))
    R2 = _core.read_nvm(_core.write_nvm(R))
    # quaternions are stored VERBATIM and round-trip bit-exact through %.17g, so this
    # is an EXACT equality -- strictly stronger than the old atol=1e-12, which would
    # have let a small quaternion corruption slip past unnoticed.
    np.testing.assert_array_equal(np.asarray(R2.quaternions), np.asarray(R.quaternions))
    np.testing.assert_allclose(
        np.asarray(R2.translations), np.asarray(R.translations), rtol=0, atol=1e-9
    )


def test_oracle_reads_our_writer():
    # parity kind 2: the independent oracle parses our bytes and recovers the
    # record, including centers == -R^T*t.
    cams, pts = _synth(seed=5)
    R = _core.read_nvm(oracle_write_nvm(cams, pts))
    parsed = oracle_read_nvm(bytes(_core.write_nvm(R)))
    q, t = np.asarray(R.quaternions), np.asarray(R.translations)
    names = list(R.image_names)
    for k, oc in enumerate(parsed["cams"]):
        assert oc["name"] == names[k]
        np.testing.assert_array_equal(oc["q"], q[k])
        # center recovered from our writer equals -R^T*t.
        np.testing.assert_allclose(
            oc["C"], -quat_wxyz_to_mat(q[k]).T @ t[k], rtol=1e-13, atol=1e-12
        )
    assert_measurements_equal(_meas_no_feat(parsed["pts"]), our_measurements(R))


def test_golden_writer_blob():
    R = _core.read_nvm(GOLDEN_NVM)
    assert bytes(_core.write_nvm(R)) == GOLDEN_NVM


def test_observations_via_colmap_txt(tmp_path):
    # Independent-writer cross-check of the obs CSR: read NVM, write COLMAP text,
    # and confirm the per-image observation lines carry the centered (x, y) and
    # the back-referenced point id.
    R = _core.read_nvm(GOLDEN_NVM)
    out = tmp_path / "as_colmap"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))
    img_txt = (out / "images.txt").read_bytes()
    assert b"a.jpg\n4.5 -5.5 1\n" in img_txt  # image 1's sole obs -> (4.5, -5.5), point id 1

    # HAND_NVM (2 images, 3 points, 4 INTERLEAVED measurements) pins the parts the
    # Reconstruction binding cannot surface: per-image bucket attribution, in-bucket
    # file-scan order, AND the obs_pt3d point back-references -- all through the
    # INDEPENDENT colmap_txt writer. write_nvm re-emits per-point so it is blind to a
    # reader that scrambled obs_pt3d or mis-ordered a multi-obs bucket; this is not.
    Rh = _core.read_nvm(HAND_NVM)
    outh = tmp_path / "hand_colmap"
    outh.mkdir()
    _core.write_colmap_txt(Rh, str(outh))
    img_txt_h = (outh / "images.txt").read_bytes()
    # a.jpg bucket: point 0's (4.5,-5.5)->id 1, then point 2's (0.5,0.5)->id 3.
    assert b"a.jpg\n4.5 -5.5 1 0.5 0.5 3\n" in img_txt_h
    # b.jpg bucket: point 0's (6.5,-7.5)->id 1, then point 1's (8.5,-9.5)->id 2.
    assert b"b.jpg\n6.5 -7.5 1 8.5 -9.5 2\n" in img_txt_h


# ==========================================================================
# tail grammar, empty model
# ==========================================================================
def test_tail_grammar_unregistered_model_discarded():
    # A trailing model with cameras but 0 points (VisualSFM's unregistered
    # images) parses model 1 only and discards those cameras.
    data = (
        b"NVM_V3\n1\n"
        b"a.jpg 800 1 0 0 0 1 2 3 0 0\n"
        b"0\n"  # 0 points in model 1
        b"2\n"  # a second model: 2 cameras...
        b"u1.jpg 1 1 0 0 0 0 0 0 0 0\n"
        b"u2.jpg 1 1 0 0 0 0 0 0 0 0\n"
        b"0\n"  # ...but 0 points -> discarded
        b"0\n"  # terminator
    )
    R = _core.read_nvm(data)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (1, 1, 0)


def test_tail_grammar_second_model_with_points_raises():
    data = (
        b"NVM_V3\n1\n"
        b"a.jpg 800 1 0 0 0 1 2 3 0 0\n"
        b"0\n"
        b"1\n"  # a genuine second model: 1 camera...
        b"b.jpg 800 1 0 0 0 0 0 0 0 0\n"
        b"1\n"  # ...and 1 point -> refuse
        b"9 9 9 0 0 0 0\n"
        b"0\n"
    )
    with pytest.raises(ValueError, match="multi-model"):
        _core.read_nvm(data)


def test_tail_grammar_ply_section_ignored():
    data = GOLDEN_NVM + b"# comment\n1 0\nply\nblah blah 123 not numbers\n"
    R = _core.read_nvm(data)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (1, 1, 1)


def test_tail_grammar_no_terminator_ok():
    data = (
        b"NVM_V3\n1\n"
        b"a.jpg 800 1 0 0 0 1 2 3 0 0\n"
        b"1\n1 2 3 10 20 30 0\n"  # a point with 0 measurements, then EOF
    )
    R = _core.read_nvm(data)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (1, 1, 1)


def test_empty_reconstruction():
    R = _core.read_nvm(b"NVM_V3\n0\n0\n")
    assert (R.num_cameras, R.num_images, R.num_points3D) == (0, 0, 0)
    out = bytes(_core.write_nvm(R))
    assert out == b"NVM_V3\n0\n0\n0\n"
    R2 = _core.read_nvm(out)
    assert (R2.num_cameras, R2.num_images, R2.num_points3D) == (0, 0, 0)


# ==========================================================================
# malformed input raises ValueError (never crashes)
# ==========================================================================
_CAM = b"a.jpg 800 1 0 0 0 0 0 0 0 0\n"


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"NVM_V2\n1\n", "header"),
        (b"", "header"),
        (b"NVM_V3_R9T\n1\n", "R9T"),
        (b"NVM_V3\nFixedK 500 320 500 240\n2\n", "calibration"),
        (b"NVM_V3\n2.5\n", "calibration"),  # non-integer camera count
        (b"NVM_V3\n1\na.jpg foo 1 0 0 0 0 0 0 0 0\n0\n", "bad number"),  # focal
        (b"NVM_V3\n1\na.jpg 800 1 0 0\n", "missing field"),  # EOF mid-camera
        (b"NVM_V3\n5\n" + _CAM, "missing field"),  # count exceeds actual cameras
        (b"NVM_V3\n4000000000\n", "missing field"),  # hostile count (reserve-cap, no OOM)
        (b"NVM_V3\n1\na.jpg 800 0 0 0 0 1 2 3 0 0\n0\n", "quaternion"),  # zero quaternion
        (b"NVM_V3\n1\na.jpg 800 nan 0 0 0 1 2 3 0 0\n0\n", "quaternion"),  # nan quaternion
        (b"NVM_V3\n1\n" + _CAM + b"1\n1 2 3 300 20 30 0\n0\n", "0..255"),  # rgb overflow
        (b"NVM_V3\n1\n" + _CAM + b"1\n1 2 3 -1 20 30 0\n0\n", "bad integer"),  # rgb negative
        (b"NVM_V3\n1\n" + _CAM + b"1\n1 2 3 10 20 30 1 1 0 5 6\n0\n", "out of range"),  # img idx
        (b"NVM_V3\n1\n" + _CAM + b"1\n1 2 3 10 20 30 5 0 0 5 6\n0\n", "missing field"),  # #meas
        (b"NVM_V3\n1\n" + _CAM + b"0\nGARBAGE\n", "trailing garbage"),  # junk after model
        # overflow / edge-guard branches (each exercises a distinct code guard)
        (b"NVM_V3\n4294967295\n", "too large"),  # ncam == 0xFFFFFFFF -> camera-id overflow guard
        (b"NVM_V3\n99999999999999999999\n", "calibration"),  # uint64-overflow count -> calib path
        (b"NVM_V3\n0\n4000000000\n", "missing field"),  # hostile POINT count (reserve-cap, no OOM)
        (b"NVM_V3\n1\na.jpg 800 inf 0 0 0 1 2 3 0 0\n0\n", "quaternion"),  # non-finite (inf) quat
    ],
)
def test_malformed_raises(data, match):
    with pytest.raises(ValueError, match=match):
        _core.read_nvm(data)


# ==========================================================================
# writer guards (refuse-not-convert) via COLMAP-text-built records
# ==========================================================================
_IMG_EMPTY = b"1 1 0 0 0 0 0 0 1 a.png\n\n"


def test_writer_guard_pinhole_model(tmp_path):
    R = _colmap_record(tmp_path, "g1", b"1 PINHOLE 0 0 500 500 0 0\n", _IMG_EMPTY, b"")
    with pytest.raises(ValueError, match="not representable"):
        _core.write_nvm(R)


def test_writer_guard_principal_point(tmp_path):
    R = _colmap_record(tmp_path, "g2", b"1 SIMPLE_RADIAL 0 0 500 320 240 0.1\n", _IMG_EMPTY, b"")
    with pytest.raises(ValueError, match="principal point"):
        _core.write_nvm(R)


def test_writer_guard_dimensions(tmp_path):
    R = _colmap_record(tmp_path, "g3", b"1 SIMPLE_RADIAL 640 0 500 0 0 0.1\n", _IMG_EMPTY, b"")
    with pytest.raises(ValueError, match="dimensions"):
        _core.write_nvm(R)


def test_writer_guard_name_whitespace(tmp_path):
    R = _colmap_record(
        tmp_path,
        "g4",
        b"1 SIMPLE_PINHOLE 0 0 500 0 0\n",
        b"1 1 0 0 0 0 0 0 1 my image.png\n\n",
        b"",
    )
    with pytest.raises(ValueError, match="whitespace"):
        _core.write_nvm(R)


def test_writer_guard_untriangulated_obs(tmp_path):
    # A COLMAP-borne record with a -1 observation sentinel is refused, not
    # silently mislabeled as NVM.
    R = _colmap_record(
        tmp_path,
        "g5",
        b"1 SIMPLE_PINHOLE 0 0 500 0 0\n",
        b"1 1 0 0 0 0 0 0 1 a.png\n100 200 -1\n",
        b"",
    )
    with pytest.raises(ValueError, match="3D point"):
        _core.write_nvm(R)


def test_writer_guard_unknown_image_id(tmp_path):
    R = _colmap_record(
        tmp_path,
        "g6",
        b"1 SIMPLE_PINHOLE 0 0 500 0 0\n",
        _IMG_EMPTY,
        b"5 1 2 3 10 20 30 0.5 99 0\n",  # track references image 99 (does not exist)
    )
    with pytest.raises(ValueError, match="unknown image"):
        _core.write_nvm(R)


def test_writer_guard_point2d_out_of_range(tmp_path):
    R = _colmap_record(
        tmp_path,
        "g7",
        b"1 SIMPLE_PINHOLE 0 0 500 0 0\n",
        b"1 1 0 0 0 0 0 0 1 a.png\n10 20 5\n",  # image 1 has exactly 1 observation
        b"5 1 2 3 10 20 30 0.5 1 99\n",  # track point2D idx 99 is out of range
    )
    with pytest.raises(ValueError, match="out of range"):
        _core.write_nvm(R)


def test_writer_guard_zero_quaternion(tmp_path):
    # A COLMAP-borne record with an all-zero quaternion has no rotation, so the NVM
    # camera center C = -R^T*t is undefined. The writer must refuse (mirroring the
    # reader) rather than silently fabricate R = I and emit C = -t.
    R = _colmap_record(
        tmp_path, "gqz", b"1 SIMPLE_PINHOLE 0 0 500 0 0\n", b"1 0 0 0 0 0 0 0 1 a.png\n\n", b""
    )
    with pytest.raises(ValueError, match="quaternion"):
        _core.write_nvm(R)


def test_writer_guard_nonfinite_quaternion(tmp_path):
    # A NaN quaternion is likewise refused instead of emitting 'nan ... -nan' centers.
    R = _colmap_record(
        tmp_path, "gqn", b"1 SIMPLE_PINHOLE 0 0 500 0 0\n", b"1 nan 0 0 0 0 0 0 1 a.png\n\n", b""
    )
    with pytest.raises(ValueError, match="quaternion"):
        _core.write_nvm(R)


# ==========================================================================
# fuzz, special values, interop, registry
# ==========================================================================
def test_fuzz_single_byte_mutation_no_crash():
    base = (
        b"NVM_V3\n2\n"
        b"a.jpg 800 1 0 0 0 1 2 3 0 0\n"
        b"b.jpg 600 1 0 0 0 4 5 6 0.1 0\n"
        b"2\n"
        b"1 2 3 10 20 30 1 0 0 4.5 -5.5\n"
        b"7 8 9 40 50 60 1 1 0 1.5 2.5\n"
        b"0\n"
    )
    for i in range(len(base)):
        for repl in (0x00, 0x23, 0x39, 0x20, 0xFF, 0x0A):  # NUL '#' '9' ' ' 0xFF '\n'
            try:
                _core.read_nvm(base[:i] + bytes([repl]) + base[i + 1 :])
            except ValueError:
                pass


def test_special_double_values():
    # Non-finite center/xyz read verbatim and re-write as canonical spellings —
    # never MSVC's "-nan(ind)"/"1.#INF" — and re-parse cleanly.
    data = (
        b"NVM_V3\n1\n"
        b"a.jpg 800 1 0 0 0 inf 2 3 0 0\n"  # camera center with inf
        b"1\n0.5 nan -inf 10 20 30 0\n0\n"  # xyz with nan / -inf
    )
    R = _core.read_nvm(data)
    out = bytes(_core.write_nvm(R))
    assert b"inf" in out and b"nan" in out
    assert b"nan(ind)" not in out and b"1.#" not in out
    _core.read_nvm(out)  # re-parses without error


def test_zero_copy_views_and_torch():
    R = _core.read_nvm(oracle_write_nvm(*_synth(seed=9)))
    xyz = R.xyz
    assert isinstance(xyz, np.ndarray) and xyz.dtype == np.float64
    assert xyz.shape == (R.num_points3D, 3)
    torch = pytest.importorskip("torch")
    assert np.array_equal(torch.from_dlpack(R.xyz).numpy(), np.asarray(R.xyz))


def test_registry(tmp_path):
    try:
        from sceneio.io import registry
    except Exception:
        pytest.skip("registry not importable")
    if "nvm" not in registry.REGISTRY:
        pytest.skip("nvm codec not wired into the registry yet (integrator step)")
    from sceneio.io import read as io_read
    from sceneio.io import write as io_write

    f = tmp_path / "model.nvm"
    f.write_bytes(GOLDEN_NVM)
    assert registry.detect(str(f)) == "nvm"
    noext = tmp_path / "model_noext"
    noext.write_bytes(GOLDEN_NVM)
    assert registry.detect(str(noext)) == "nvm"  # magic sniff

    R = io_read(str(f))
    out = tmp_path / "out.nvm"
    io_write(R, str(out))
    R2 = io_read(str(out))
    np.testing.assert_array_equal(np.asarray(R2.xyz), np.asarray(R.xyz))
    np.testing.assert_array_equal(np.asarray(R2.quaternions), np.asarray(R.quaternions))
