"""Parity suite for the COLMAP *text* sparse-model codec (cameras.txt /
images.txt / points3D.txt -> Reconstruction) — the text twin of
tests/codecs/test_colmap.py.

Oracle: pycolmap (BSD). VALUE parity, not byte-exact: COLMAP/pycolmap write
text via std::ofstream in text mode with ostream precision(17), so byte
identity vs the oracle is platform-dependent — but "%.17g" round-trips every
IEEE-754 double bit-exactly, so all VALUE comparisons are exact. The
byte-exact gate is instead the twin loop read(.bin) -> write(.txt) ->
read(.txt) -> write(.bin) == the original .bin bytes (test_bin_txt_bin_byte_
identity), which pins reader AND writer against the already-byte-exact binary
codec, and simultaneously validates observations (which the Reconstruction
binding does not surface directly).

pycolmap-independent coverage (runs in any built tree): a hand-authored
convention pin (comments, CRLF, tab/multi-space separators, an empty
observations line, a -1 sentinel, EOF after a pose line), a golden writer
blob, round-trip identity, empty-reconstruction round-trip, malformed-raises,
single-byte-mutation fuzz, and numpy/torch interop.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover - exercised only in a non-built tree
    _core = None

pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")


# --- helpers ----------------------------------------------------------------
def _write_model(d: Path, cameras: bytes, images: bytes, points: bytes) -> str:
    d.mkdir(parents=True, exist_ok=True)
    (d / "cameras.txt").write_bytes(cameras)
    (d / "images.txt").write_bytes(images)
    (d / "points3D.txt").write_bytes(points)
    return str(d)


def _quat_wxyz_to_R(q):  # identical to tests/codecs/test_colmap.py
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


# --- fixtures shared by the pycolmap-free tests -----------------------------
# Deterministic, all values exactly representable in float64 so "%.17g" yields
# short, platform-stable strings (no exponent notation, no trailing zeros).
GOLD_CAMERAS_IN = b"# c\n1 PINHOLE 640 480 500 500 320 240\n"
GOLD_IMAGES_IN = (
    b"# i\n"
    b"1 1 0 0 0 0 0 0 1 img1.png\n"
    b"100.5 200.5 5 150.25 250.75 -1 10.5 20.5 5\n"  # 3 observations, one a -1 sentinel
    b"2 1 0 0 0 1 2 3 1 img2.png\n"
    b"\n"  # image 2: empty observations line (0 obs) followed by image 3
    b"3 1 0 0 0 4 5 6 1 img3.png\n"  # image 3: EOF after the pose line (0 obs)
)
GOLD_POINTS_IN = b"# p\n5 1.5 -2.5 3.5 10 20 30 0.75 1 0\n"

# What write_colmap_txt must emit for the Reconstruction parsed from the above.
GOLD_CAMERAS_OUT = (
    b"# Camera list with one line of data per camera:\n"
    b"#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n"
    b"# Number of cameras: 1\n"
    b"1 PINHOLE 640 480 500 500 320 240\n"
)
GOLD_IMAGES_OUT = (
    b"# Image list with two lines of data per image:\n"
    b"#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n"
    b"#   POINTS2D[] as (X, Y, POINT3D_ID)\n"
    b"# Number of images: 3, mean observations per image: 1\n"
    b"1 1 0 0 0 0 0 0 1 img1.png\n"
    b"100.5 200.5 5 150.25 250.75 -1 10.5 20.5 5\n"
    b"2 1 0 0 0 1 2 3 1 img2.png\n"
    b"\n"  # image 2: zero-observation empty line
    b"3 1 0 0 0 4 5 6 1 img3.png\n"
    b"\n"  # image 3: zero-observation empty line (writer always emits line 2)
)
GOLD_POINTS_OUT = (
    b"# 3D point list with one line of data per point:\n"
    b"#   POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)\n"
    b"# Number of points: 1, mean track length: 1\n"
    b"5 1.5 -2.5 3.5 10 20 30 0.75 1 0\n"
)


# ==========================================================================
# pycolmap oracle (value parity, four ways) + the bin<->txt byte-identity gate
# ==========================================================================
@pytest.fixture(scope="module")
def ref(tmp_path_factory):
    pycolmap = pytest.importorskip("pycolmap")
    opts = pycolmap.SyntheticDatasetOptions()
    opts.num_points3D = 40
    rec = pycolmap.synthesize_dataset(opts)
    base = tmp_path_factory.mktemp("colmap_txt")
    tdir = base / "text"
    bdir = base / "bin"
    tdir.mkdir()
    bdir.mkdir()
    rec.write_text(str(tdir))
    rec.write_binary(str(bdir))
    return rec, str(tdir), str(bdir)


def test_counts_match(ref):
    rec, tdir, _ = ref
    R = _core.read_colmap_txt(tdir)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (
        rec.num_cameras(),
        rec.num_images(),
        rec.num_points3D(),
    )


def test_camera_parity(ref):
    rec, tdir, _ = ref
    R = _core.read_colmap_txt(tdir)
    ours = {c.id: c for c in R.cameras}
    for cid, cam in rec.cameras.items():
        c = ours[int(cid)]
        assert (c.width, c.height) == (cam.width, cam.height)
        assert c.model == cam.model_name
        np.testing.assert_array_equal(np.asarray(c.params), np.asarray(cam.params))


def test_points_parity(ref):
    rec, tdir, _ = ref
    R = _core.read_colmap_txt(tdir)
    xyz, rgb, err = np.asarray(R.xyz), np.asarray(R.rgb), np.asarray(R.errors)
    row = {int(i): k for k, i in enumerate(np.asarray(R.point3D_ids))}
    assert xyz.dtype == np.float64 and rgb.dtype == np.uint8
    for pid, p in rec.points3D.items():
        k = row[int(pid)]
        np.testing.assert_array_equal(xyz[k], np.asarray(p.xyz))
        np.testing.assert_array_equal(rgb[k], np.asarray(p.color, dtype=np.uint8))
        assert err[k] == p.error


def test_pose_convention_pin(ref):
    # WXYZ, world->camera: rebuilding R|t must match pycolmap's cam_from_world.
    rec, tdir, _ = ref
    R = _core.read_colmap_txt(tdir)
    quats, trans = np.asarray(R.quaternions), np.asarray(R.translations)
    names = R.image_names
    row = {int(i): k for k, i in enumerate(np.asarray(R.image_ids))}
    assert R.quaternion_order == "wxyz"
    assert R.pose_convention == "world_to_camera"
    for iid, im in rec.images.items():
        k = row[int(iid)]
        M = np.asarray(im.cam_from_world().matrix())[:3]  # 3x4 [R|t]
        np.testing.assert_allclose(_quat_wxyz_to_R(quats[k]), M[:, :3], atol=1e-9)
        np.testing.assert_allclose(trans[k], M[:, 3], atol=1e-12)
        assert im.name == names[k]


def test_pycolmap_reads_our_text(ref, tmp_path):
    # Writer spec-correctness (parity kind 2): the independent oracle reads it.
    pycolmap = pytest.importorskip("pycolmap")
    rec, tdir, _ = ref
    R = _core.read_colmap_txt(tdir)
    out = tmp_path / "ours"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))
    rec2 = pycolmap.Reconstruction(str(out))
    assert rec2.num_cameras() == rec.num_cameras()
    assert rec2.num_images() == rec.num_images()
    assert rec2.num_points3D() == rec.num_points3D()


def test_bin_txt_bin_byte_identity(ref, tmp_path):
    # The strongest gate: couple our text reader+writer to the byte-exact binary
    # codec. read(.bin) -> write(.txt) -> read(.txt) -> write(.bin) must
    # reproduce the original .bin bytes exactly. This also validates observation
    # parity (incl. the -1 sentinel and the CSR offsets), which the binding does
    # not expose directly.
    _, _, bdir = ref
    R = _core.read_colmap_sparse(bdir)
    t2 = tmp_path / "t2"
    t2.mkdir()
    _core.write_colmap_txt(R, str(t2))
    R2 = _core.read_colmap_txt(str(t2))
    b2 = tmp_path / "b2"
    b2.mkdir()
    _core.write_colmap_sparse(R2, str(b2))
    for f in ("cameras.bin", "images.bin", "points3D.bin"):
        a = (Path(bdir) / f).read_bytes()
        b = (b2 / f).read_bytes()
        assert a == b, f"{f} is not byte-identical after bin->txt->bin"


# ==========================================================================
# pycolmap-free coverage (runs in any built tree)
# ==========================================================================
def test_hand_authored_pin(tmp_path):
    # Comments, CRLF endings, tab/multi-space separators, a -1 observation
    # sentinel, an empty observations line (image 20) followed by another image,
    # and EOF right after a pose line (image 30) — the subtle line-2 grammar.
    cameras = b"# hdr\r\n1\tSIMPLE_PINHOLE  640   480\t100 320 240\r\n"
    images = (
        b"# Image list\r\n"
        b"#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\r\n"
        b"10   0.5 0.5 0.5 0.5\t1 2 3   2 frame_a.png\r\n"
        b"1.5 2.5 -1\r\n"  # image 10: one observation, POINT3D_ID == -1
        b"20 1 0 0 0 4 5 6 2 frame_b.png\r\n"
        b"\r\n"  # image 20: empty observations line
        b"30 1 0 0 0 7 8 9 2 frame_c.png\r\n"  # image 30: EOF after the pose line
    )
    points = b"# pts\r\n5 1 2 3 100 150 200 0.5 10 0\r\n"
    d = _write_model(tmp_path / "hand", cameras, images, points)
    R = _core.read_colmap_txt(d)

    assert (R.num_cameras, R.num_images, R.num_points3D) == (1, 3, 1)
    cam = R.cameras[0]
    assert cam.model == "SIMPLE_PINHOLE"
    assert (cam.width, cam.height) == (640, 480)
    np.testing.assert_array_equal(np.asarray(cam.params), np.array([100.0, 320.0, 240.0]))

    np.testing.assert_array_equal(np.asarray(R.image_ids), np.array([10, 20, 30]))
    assert list(R.image_names) == ["frame_a.png", "frame_b.png", "frame_c.png"]
    np.testing.assert_array_equal(np.asarray(R.image_camera_ids), np.array([2, 2, 2]))
    q, t = np.asarray(R.quaternions), np.asarray(R.translations)
    np.testing.assert_array_equal(q[0], [0.5, 0.5, 0.5, 0.5])  # stored raw (not normalized)
    np.testing.assert_array_equal(q[1], [1, 0, 0, 0])
    np.testing.assert_array_equal(t, [[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    np.testing.assert_array_equal(np.asarray(R.xyz)[0], [1, 2, 3])
    np.testing.assert_array_equal(np.asarray(R.rgb)[0], [100, 150, 200])
    assert np.asarray(R.errors)[0] == 0.5

    # Re-emit and pin the observation attribution the binding can't surface:
    # image 10 keeps its -1 observation; 20 & 30 emit empty observation lines.
    out = tmp_path / "hand_out"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))
    img_txt = (out / "images.txt").read_bytes()
    assert b"frame_a.png\n1.5 2.5 -1\n" in img_txt  # -1 sentinel survived CRLF/tab lexing
    assert b"frame_b.png\n\n" in img_txt  # empty observations line mid-file
    assert b"frame_c.png\n\n" in img_txt  # EOF-after-pose-line -> 0 obs, empty line emitted


def test_golden_writer_blob(tmp_path):
    # Byte-exact encode-drift guard (roadmap §1.4): read a literal fixture, write
    # it back, compare all three files to the hand-derived expected bytes. Pins
    # the '#' headers, count/mean stats, "%.17g" clean formatting, the -1
    # sentinel, and the zero-observation empty lines.
    d = _write_model(tmp_path / "src", GOLD_CAMERAS_IN, GOLD_IMAGES_IN, GOLD_POINTS_IN)
    R = _core.read_colmap_txt(d)
    out = tmp_path / "out"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))
    assert (out / "cameras.txt").read_bytes() == GOLD_CAMERAS_OUT
    assert (out / "images.txt").read_bytes() == GOLD_IMAGES_OUT
    assert (out / "points3D.txt").read_bytes() == GOLD_POINTS_OUT


def test_roundtrip_bitexact(tmp_path):
    # Parity kind 3: read_colmap_txt(write_colmap_txt(R)) reproduces every
    # exposed array bit-exactly (no eps — doubles survive "%.17g").
    d = _write_model(tmp_path / "r0", GOLD_CAMERAS_IN, GOLD_IMAGES_IN, GOLD_POINTS_IN)
    R = _core.read_colmap_txt(d)
    out = tmp_path / "r1"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))
    R2 = _core.read_colmap_txt(str(out))
    for attr in ("quaternions", "translations", "xyz", "rgb", "errors", "image_ids", "point3D_ids"):
        np.testing.assert_array_equal(np.asarray(getattr(R2, attr)), np.asarray(getattr(R, attr)))
    assert list(R2.image_names) == list(R.image_names)
    for c2, c1 in zip(R2.cameras, R.cameras, strict=True):
        assert c2.model == c1.model and (c2.width, c2.height) == (c1.width, c1.height)
        np.testing.assert_array_equal(np.asarray(c2.params), np.asarray(c1.params))


def test_empty_reconstruction_roundtrip(tmp_path):
    d = _write_model(
        tmp_path / "empty",
        b"# Number of cameras: 0\n",
        b"# Number of images: 0\n",
        b"# Number of points: 0\n",
    )
    R = _core.read_colmap_txt(d)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (0, 0, 0)
    out = tmp_path / "empty_out"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))
    assert b"# Number of cameras: 0\n" in (out / "cameras.txt").read_bytes()
    assert (
        b"# Number of images: 0, mean observations per image: 0\n"
        in (out / "images.txt").read_bytes()
    )
    assert b"# Number of points: 0, mean track length: 0\n" in (out / "points3D.txt").read_bytes()
    R2 = _core.read_colmap_txt(str(out))
    assert (R2.num_cameras, R2.num_images, R2.num_points3D) == (0, 0, 0)


# --- malformed input raises ValueError (FormatError-mappable), never crashes -
_GOOD_CAM = b"1 PINHOLE 640 480 500 500 320 240\n"
_GOOD_IMG = b"1 1 0 0 0 0 0 0 1 a.png\n\n"
_GOOD_PTS = b"5 1 2 3 10 20 30 0.5\n"


@pytest.mark.parametrize(
    ("cameras", "images", "points", "match"),
    [
        (b"1 WOBBLE 640 480 500\n", _GOOD_IMG, _GOOD_PTS, "unknown camera model"),
        (b"1 PINHOLE 640 480 500 500 320\n", _GOOD_IMG, _GOOD_PTS, "params"),  # wrong count
        (b"1 PINHOLE 640 480 foo 500 320 240\n", _GOOD_IMG, _GOOD_PTS, "bad number"),
        (b"1.5 PINHOLE 640 480 500 500 320 240\n", _GOOD_IMG, _GOOD_PTS, "bad integer"),
        (_GOOD_CAM, b"1 1 0 0 0 0 0 0 1 a.png\n1.0 2.0\n", _GOOD_PTS, "multiple of 3"),
        (_GOOD_CAM, _GOOD_IMG, b"5 1 2 3 10 20 30 0.5 7\n", "multiple of 2"),  # odd track
        (_GOOD_CAM, _GOOD_IMG, b"5 1 2 3 300 20 30 0.5\n", "0..255"),  # rgb overflow
        (_GOOD_CAM, _GOOD_IMG, b"5 1 2 3 -1 20 30 0.5\n", "bad integer"),  # rgb negative
    ],
)
def test_malformed_raises(tmp_path, cameras, images, points, match):
    d = _write_model(tmp_path / "bad", cameras, images, points)
    with pytest.raises(ValueError, match=match):
        _core.read_colmap_txt(d)


def test_missing_file_raises(tmp_path):
    d = tmp_path / "partial"
    d.mkdir()
    (d / "cameras.txt").write_bytes(_GOOD_CAM)
    (d / "points3D.txt").write_bytes(_GOOD_PTS)  # images.txt absent
    with pytest.raises(ValueError, match="cannot open"):
        _core.read_colmap_txt(str(d))


def test_fuzz_single_byte_mutation_no_crash(tmp_path):
    # Every single-byte mutation of a small images.txt must parse or raise
    # ValueError — never crash / read out of bounds (from_chars is end-bounded).
    base = b"1 1 0 0 0 0 0 0 1 a.png\n100.5 200.5 5 150.25 250.75 -1\n2 1 0 0 0 1 2 3 1 b.png\n\n"
    d = tmp_path / "fuzz"
    d.mkdir()
    (d / "cameras.txt").write_bytes(_GOOD_CAM)
    (d / "points3D.txt").write_bytes(_GOOD_PTS)
    img = d / "images.txt"
    for i in range(len(base)):
        for repl in (0x00, 0x23, 0x39, 0x20, 0xFF, 0x0A):  # NUL '#' '9' ' ' 0xFF '\n'
            img.write_bytes(base[:i] + bytes([repl]) + base[i + 1 :])
            try:
                _core.read_colmap_txt(str(d))
            except ValueError:
                pass


# --- registry integration (skips until the integrator wires the codec) ------
def _find_text_codec():
    try:
        from sceneio.io import registry
    except Exception:
        return None
    for c in registry.REGISTRY.values():
        if (
            getattr(c, "is_directory", False)
            and c.record is _core.Reconstruction
            and c.id != "colmap_sparse"
        ):
            return c
    return None


def test_registry_roundtrip(tmp_path):
    codec = _find_text_codec()
    if codec is None:
        pytest.skip("COLMAP text codec not wired into the registry yet (integrator step)")
    from sceneio.io import read as io_read
    from sceneio.io import write as io_write

    d = _write_model(tmp_path / "reg_src", GOLD_CAMERAS_IN, GOLD_IMAGES_IN, GOLD_POINTS_IN)
    R = _core.read_colmap_txt(d)
    out = tmp_path / "reg_out"
    out.mkdir()
    io_write(R, str(out), format=codec.id)
    R2 = io_read(str(out), format=codec.id)
    assert (R2.num_cameras, R2.num_images, R2.num_points3D) == (
        R.num_cameras,
        R.num_images,
        R.num_points3D,
    )


# --- numpy/torch interop (test_colmap.py pattern) ---------------------------
def test_zero_copy_views_and_torch(tmp_path):
    d = _write_model(tmp_path / "zc", GOLD_CAMERAS_IN, GOLD_IMAGES_IN, GOLD_POINTS_IN)
    R = _core.read_colmap_txt(d)
    xyz = R.xyz  # zero-copy view; R kept alive by reference_internal
    assert isinstance(xyz, np.ndarray) and xyz.shape == (R.num_points3D, 3)
    assert xyz.dtype == np.float64
    torch = pytest.importorskip("torch")
    t = torch.from_dlpack(R.xyz)
    assert np.array_equal(t.numpy(), np.asarray(R.xyz))
