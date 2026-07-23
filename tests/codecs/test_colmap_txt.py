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
    b"# Number of images: 3, mean observations per image: 0.66666666666666663\n"
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
    # Force some 2D points to lack a 3D point so the -1 sentinel and the
    # triangulated-only mean-observations stat are exercised regardless of the
    # pycolmap default.
    if hasattr(opts, "num_points2D_without_point3D"):
        opts.num_points2D_without_point3D = 10
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


def test_text_reader_matches_binary_ground_truth(ref, tmp_path):
    # One-sided EXTERNAL anchor for the text READER. The self-inverse bin->txt->bin
    # gate above cannot catch a both-sides-consistent transposition of observation
    # X/Y or track pairs; this can. pycolmap wrote tdir (text) and bdir (binary)
    # from ONE rec in one process, so their record order is identical and "%.17g"
    # round-trips doubles bit-exactly — therefore our binary, written from the text
    # we read, must be byte-identical to pycolmap's binary. Pins obs X/Y order, the
    # -1 sentinel, and track (IMAGE_ID, POINT2D_IDX) order against ground truth.
    _, tdir, bdir = ref
    R = _core.read_colmap_txt(tdir)
    out = tmp_path / "txt2bin"
    out.mkdir()
    _core.write_colmap_sparse(R, str(out))
    for f in ("cameras.bin", "images.bin", "points3D.bin"):
        a = (Path(bdir) / f).read_bytes()
        b = (out / f).read_bytes()
        assert a == b, f"{f}: text reader disagrees with binary ground truth"


def test_images_header_matches_pycolmap(ref, tmp_path):
    # The "mean observations per image" header stat must equal COLMAP's
    # ComputeMeanObservationsPerRegImage (triangulated points only): compare our
    # emitted header line to pycolmap's for the same reconstruction.
    _, tdir, _ = ref
    R = _core.read_colmap_txt(tdir)
    out = tmp_path / "hdr"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))

    def mean_obs_line(raw: bytes) -> bytes:
        for ln in raw.replace(b"\r\n", b"\n").split(b"\n"):
            if ln.startswith(b"# Number of images:"):
                return ln
        raise AssertionError("no image-count header line found")

    ours = mean_obs_line((out / "images.txt").read_bytes())
    theirs = mean_obs_line((Path(tdir) / "images.txt").read_bytes())
    assert ours == theirs


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
        b"10   0.125 0.25 0.375 0.5\t1 2 3   2 frame_a.png\r\n"
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
    np.testing.assert_array_equal(
        q[0], [0.125, 0.25, 0.375, 0.5]
    )  # asymmetric: pins each WXYZ slot; stored raw
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
        # truncated image pose line (only 7 fields -> translation cut short)
        (_GOOD_CAM, b"1 1 0 0 0 0 0\n", _GOOD_PTS, "missing field"),
        # points3D line missing the ERROR field
        (_GOOD_CAM, _GOOD_IMG, b"5 1 2 3 10 20 30\n", "missing field"),
        # observation POINT3D_ID that is negative but not the -1 sentinel
        (_GOOD_CAM, b"1 1 0 0 0 0 0 0 1 a.png\n1.5 2.5 -2\n", _GOOD_PTS, "bad integer"),
        # a '#' line in the observations slot is DATA, not a skipped comment
        (_GOOD_CAM, b"1 1 0 0 0 0 0 0 1 a.png\n# not obs\n", _GOOD_PTS, "bad number"),
        # observation POINT3D_ID overflowing int64 (2^63) must raise, not wrap to a
        # negative id (which the writer would then emit and a re-read reject)
        (
            _GOOD_CAM,
            b"1 1 0 0 0 0 0 0 1 a.png\n1.5 2.5 9223372036854775808\n",
            _GOOD_PTS,
            "int64 range",
        ),
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


def test_special_and_full_precision_doubles(tmp_path):
    # %.17g precision (a regression to %.15g/%.16g drops digits) and IEEE-754
    # special values (nan bit-pattern, +/-inf, -0.0 sign) must survive the reader
    # and the writer round-trip byte-exactly. .tobytes() catches the -0.0 sign loss
    # that assert_array_equal (0.0 == -0.0) cannot, and pins the nan bit-pattern.
    cameras = b"1 PINHOLE 640 480 500 500 320 240\n"
    images = b"1 1 0 0 0 -0 inf -inf 1 a.png\n\n"  # translation = [-0.0, +inf, -inf]
    points = b"5 0.1 nan -0 10 20 30 inf\n"  # xyz = [0.1, nan, -0.0], error = +inf
    d = _write_model(tmp_path / "special_src", cameras, images, points)
    R = _core.read_colmap_txt(d)

    # Reader pins (byte-exact, independent of the writer):
    assert np.asarray(R.xyz)[0].tobytes() == np.array([0.1, np.nan, -0.0]).tobytes()
    assert np.asarray(R.translations)[0].tobytes() == np.array([-0.0, np.inf, -np.inf]).tobytes()
    assert np.isposinf(np.asarray(R.errors)[0])

    out = tmp_path / "special_out"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))
    # Full-precision %.17g pin: 0.1 renders with all 17 significant digits.
    assert b"0.10000000000000001" in (out / "points3D.txt").read_bytes()

    # Writer round-trip: every special re-reads to identical bits.
    R2 = _core.read_colmap_txt(str(out))
    for attr in ("xyz", "translations", "errors"):
        assert np.asarray(getattr(R2, attr)).tobytes() == np.asarray(getattr(R, attr)).tobytes()


# COLMAP's camera-model table hand-copied from the COLMAP docs (external ground
# truth): every MODEL name and its parameter count. The .txt codec is the first
# consumer of the table's name STRINGS (the .bin codec only round-trips numeric
# ids), so a typo'd name or wrong nparams in reconstruction.hpp would mis-read or
# reject real COLMAP files using that model while the rest of the suite stays green.
_COLMAP_MODELS = [
    ("SIMPLE_PINHOLE", 3),
    ("PINHOLE", 4),
    ("SIMPLE_RADIAL", 4),
    ("RADIAL", 5),
    ("OPENCV", 8),
    ("OPENCV_FISHEYE", 8),
    ("FULL_OPENCV", 12),
    ("FOV", 5),
    ("SIMPLE_RADIAL_FISHEYE", 4),
    ("RADIAL_FISHEYE", 5),
    ("THIN_PRISM_FISHEYE", 12),
]


@pytest.mark.parametrize(("model", "nparams"), _COLMAP_MODELS)
def test_camera_model_name_id_roundtrip(tmp_path, model, nparams):
    params = " ".join(str(i + 1) for i in range(nparams))
    cameras = f"1 {model} 640 480 {params}\n".encode()
    d = _write_model(tmp_path / f"m_{model}", cameras, _GOOD_IMG, _GOOD_PTS)
    R = _core.read_colmap_txt(d)
    cam = R.cameras[0]
    assert cam.model == model
    assert len(np.asarray(cam.params)) == nparams
    out = tmp_path / f"o_{model}"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))
    assert f"1 {model} 640 480".encode() in (out / "cameras.txt").read_bytes()


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
    # Beyond counts: the values must survive the registry round-trip too, so a
    # value-corrupting path adapter cannot stay green.
    np.testing.assert_array_equal(np.asarray(R2.xyz), np.asarray(R.xyz))
    np.testing.assert_array_equal(np.asarray(R2.quaternions), np.asarray(R.quaternions))


def test_registry_detect_binary_precedence(tmp_path):
    # A directory holding BOTH cameras.bin and cameras.txt must detect as the
    # binary codec (colmap_sparse), never the text twin — registry insertion order
    # (binary registered first) encodes that precedence. Skips until both wired.
    try:
        from sceneio.io import registry
    except Exception:
        pytest.skip("registry not importable")
    if "colmap_sparse" not in registry.REGISTRY or _find_text_codec() is None:
        pytest.skip("COLMAP binary+text codecs not both wired yet")
    d = _write_model(tmp_path / "both", GOLD_CAMERAS_IN, GOLD_IMAGES_IN, GOLD_POINTS_IN)
    (Path(d) / "cameras.bin").write_bytes(b"\x00")  # binary marker alongside the text files
    assert registry.detect(d) == "colmap_sparse"


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
