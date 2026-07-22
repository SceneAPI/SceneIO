"""Parity suite for the .xyz point-cloud text codec (-> PointCloud record).

Follows the reference pattern of tests/codecs/test_pfm.py / test_netpbm.py: a
tiny self-contained pure-Python numpy oracle (primary), the three
io_implementation_plan.md §6 parity kinds (cross-impl both directions +
round-trip identity), hand-derived convention pins (rgb stored raw, the
first-data-line-sets-the-schema rule, exact decimal values), column-count edge
cases, grammar edge cases (comments / blanks / CRLF / comma & tab separators),
malformed-input raises + single-byte fuzz, golden writer blobs, writer guards,
and numpy/torch interop.

The record is the SoA PointCloud (records/point_cloud.hpp): required positions
(N,3) f32, optional colors (N,3) u8 / normals (N,3) f32 / intensities (N,) f32,
with recorded coordinate_frame/scale_to_meters/intensity_range conventions.

Column schema, auto-detected from the first data line's column count C:
    3 -> x y z          4 -> x y z i        6 -> x y z r g b
    7 -> x y z i r g b  9 -> x y z r g b nx ny nz
The 6-column form is always rgb. The writer emits only "x y z [r g b]" and
refuses records carrying normals or intensity.

Float fields are compared via ``.tobytes()`` where bit-exactness matters: our
reader parses decimal -> double -> float32 (single narrowing), matching numpy's
``float()`` -> ``np.float32`` path, and our writer's ``%.17g`` reparses to the
identical float -- so every value round-trips bit-for-bit with zero epsilon.
"""

from __future__ import annotations

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception as exc:  # pragma: no cover - exercised only in a non-built tree
    _core = None
    _import_error = exc

pytestmark = pytest.mark.skipif(
    _core is None,
    reason="sceneio._core not built (compiled-only package -- build the extension first)",
)


# --- oracle: a minimal, independent pure-Python .xyz codec ------------------
def _fmt(v) -> str:
    # repr(float(v)) is the shortest decimal that round-trips the float32 value
    # through a double; our reader recovers the identical float32 from it.
    return repr(float(v))


def oracle_write_xyz(xyz, rgb=None, intensity=None, normals=None) -> bytes:
    """Emit .xyz text in canonical column order: x y z [i] [rgb] [n]."""
    xyz = np.asarray(xyz, np.float32)
    n = xyz.shape[0]
    lines = []
    for i in range(n):
        parts = [_fmt(xyz[i, 0]), _fmt(xyz[i, 1]), _fmt(xyz[i, 2])]
        if intensity is not None:
            parts.append(_fmt(np.float32(intensity[i])))
        if rgb is not None:
            parts += [str(int(rgb[i, 0])), str(int(rgb[i, 1])), str(int(rgb[i, 2]))]
        if normals is not None:
            parts += [_fmt(np.float32(normals[i, k])) for k in range(3)]
        lines.append(" ".join(parts))
    return ("\n".join(lines) + ("\n" if n else "")).encode()


def oracle_read_xyz(data: bytes) -> dict:
    """Decode .xyz bytes into {xyz f32 (N,3), rgb u8 (N,3)|None,
    normals f32 (N,3)|None, intensity f32 (N,)|None}."""
    rows = []
    for raw in data.split(b"\n"):
        lead = raw.lstrip(b" \t\r")
        if not lead or lead.startswith(b"#"):
            continue
        toks = raw.replace(b",", b" ").split()
        if not toks:
            continue
        rows.append([float(t) for t in toks])
    out = {"xyz": np.zeros((0, 3), np.float32), "rgb": None, "normals": None, "intensity": None}
    if not rows:
        return out
    C = len(rows[0])
    for i, r in enumerate(rows):
        if len(r) != C:
            raise ValueError(f"line {i + 1}: expected {C} numbers")
    a = np.array(rows, dtype=np.float64)  # (N, C)
    out["xyz"] = a[:, 0:3].astype(np.float32)
    if C == 4:  # xyzi
        out["intensity"] = a[:, 3].astype(np.float32)
    elif C == 6:  # xyzrgb
        out["rgb"] = a[:, 3:6].astype(np.uint8)
    elif C == 7:  # xyzirgb
        out["intensity"] = a[:, 3].astype(np.float32)
        out["rgb"] = a[:, 4:7].astype(np.uint8)
    elif C == 9:  # xyzrgbn
        out["rgb"] = a[:, 3:6].astype(np.uint8)
        out["normals"] = a[:, 6:9].astype(np.float32)
    elif C != 3:
        raise ValueError(f"unsupported column count {C}")
    return out


# --- samples: one cloud, presented under every auto-detected layout ---------
@pytest.fixture
def samples() -> dict[str, dict]:
    rng = np.random.default_rng(0)
    n = 6
    xyz = rng.standard_normal((n, 3)).astype(np.float32)
    rgb = rng.integers(0, 256, (n, 3), dtype=np.uint8)
    intensity = rng.standard_normal(n).astype(np.float32)
    normals = rng.standard_normal((n, 3)).astype(np.float32)
    return {
        "xyz3": {"xyz": xyz},
        "xyz4": {"xyz": xyz, "intensity": intensity},
        "xyz6": {"xyz": xyz, "rgb": rgb},
        "xyz7": {"xyz": xyz, "intensity": intensity, "rgb": rgb},
        "xyz9": {"xyz": xyz, "rgb": rgb, "normals": normals},
    }


def _assert_optionals(rec, s: dict) -> None:
    """Compare a decoded record's optional fields against a sample dict."""
    if s.get("rgb") is not None:
        assert rec.has_rgb
        np.testing.assert_array_equal(np.asarray(rec.colors), s["rgb"])
        assert np.asarray(rec.colors).dtype == np.uint8
    else:
        assert not rec.has_rgb
    if s.get("normals") is not None:
        assert rec.has_normals
        assert np.asarray(rec.normals).tobytes() == s["normals"].tobytes()
    else:
        assert not rec.has_normals
    if s.get("intensity") is not None:
        assert rec.has_intensity
        assert np.asarray(rec.intensities).tobytes() == s["intensity"].tobytes()
    else:
        assert not rec.has_intensity


# --- parity kind 1: cross-impl (oracle writes, our reader recovers) ---------
def test_parity_oracle_write_ours_read(samples):
    for s in samples.values():
        data = oracle_write_xyz(s["xyz"], s.get("rgb"), s.get("intensity"), s.get("normals"))
        rec = _core.read_xyz(data)
        assert rec.num_points == s["xyz"].shape[0]
        assert np.asarray(rec.positions).tobytes() == s["xyz"].tobytes()  # bit-exact f32
        assert np.asarray(rec.positions).dtype == np.float32
        assert np.asarray(rec.positions).shape == s["xyz"].shape
        _assert_optionals(rec, s)


# --- parity kind 2: writer spec-correctness (ours writes, oracle recovers) --
# The writer emits only x y z [r g b], so only the 3- and 6-column layouts.
def test_parity_ours_write_oracle_read(samples):
    for name in ("xyz3", "xyz6"):
        s = samples[name]
        pc = (
            _core.point_cloud(s["xyz"], colors=s["rgb"])
            if "rgb" in s
            else _core.point_cloud(s["xyz"])
        )
        got = oracle_read_xyz(_core.write_xyz(pc))
        assert got["xyz"].tobytes() == s["xyz"].tobytes()
        if "rgb" in s:
            np.testing.assert_array_equal(got["rgb"], s["rgb"])
        else:
            assert got["rgb"] is None


# --- parity kind 3: round-trip identity (ours.read(ours.write)) -------------
def test_roundtrip_identity(samples):
    for name in ("xyz3", "xyz6"):
        s = samples[name]
        pc = (
            _core.point_cloud(s["xyz"], colors=s["rgb"])
            if "rgb" in s
            else _core.point_cloud(s["xyz"])
        )
        rec = _core.read_xyz(_core.write_xyz(pc))
        assert rec.num_points == s["xyz"].shape[0]
        assert np.asarray(rec.positions).tobytes() == s["xyz"].tobytes()
        if "rgb" in s:
            np.testing.assert_array_equal(np.asarray(rec.colors), s["rgb"])


def test_roundtrip_random_and_negative_zero():
    # %.17g of a float (promoted to double) reparses to the identical float, so
    # a large random cloud round-trips bit-exactly -- including a stamped -0.0
    # whose sign must survive the text -> float path.
    rng = np.random.default_rng(3)
    xyz = rng.standard_normal((64, 3)).astype(np.float32)
    xyz[0, 0] = np.float32(-0.0)
    xyz[1, 0] = np.float32(1e-30)  # tiny magnitude, exponent formatting
    xyz[2, 0] = np.float32(-123456.78)
    pc = _core.point_cloud(xyz)
    rec = _core.read_xyz(_core.write_xyz(pc))
    assert np.asarray(rec.positions).tobytes() == xyz.tobytes()


# --- convention pins (hand-derived external ground truth) -------------------
def test_pin_rgb_stored_raw():
    # rgb is kept as the file's raw 0..255 integers -- never normalized to 0-1.
    rec = _core.read_xyz(b"0 0 0 12 34 56\n")
    assert rec.has_rgb
    assert not rec.has_normals and not rec.has_intensity
    got = np.asarray(rec.colors)
    assert got.dtype == np.uint8
    np.testing.assert_array_equal(got, np.array([[12, 34, 56]], np.uint8))
    assert np.asarray(rec.positions).tobytes() == np.zeros((1, 3), np.float32).tobytes()


def test_pin_first_line_sets_schema():
    # The first DATA line fixes the schema; leading comments/blank lines do not
    # change it, and 6 columns is rgb (not normals).
    body = b"1 2 3 10 20 30\n4 5 6 40 50 60\n"
    prefixed = b"# header\n\n   \n" + body
    ra = _core.read_xyz(body)
    rb = _core.read_xyz(prefixed)
    assert ra.has_rgb and rb.has_rgb
    assert not ra.has_normals and not rb.has_normals
    assert ra.num_points == rb.num_points == 2
    assert np.asarray(ra.positions).tobytes() == np.asarray(rb.positions).tobytes()
    np.testing.assert_array_equal(np.asarray(ra.colors), np.asarray(rb.colors))
    np.testing.assert_array_equal(
        np.asarray(ra.colors), np.array([[10, 20, 30], [40, 50, 60]], np.uint8)
    )


def test_pin_hand_derived_decimals():
    # Exact decimal -> float32 values (all exactly representable), incl. an
    # exponent token, a negative, and a fraction.
    rec = _core.read_xyz(b"1.5 -2.25 3e2\n")
    np.testing.assert_array_equal(
        np.asarray(rec.positions), np.array([[1.5, -2.25, 300.0]], np.float32)
    )


def test_pin_reader_records_default_conventions():
    # .xyz declares no frame/unit/intensity-range, so the reader records the
    # "unknown"/1.0 defaults (reader records what it knows).
    rec = _core.read_xyz(b"1 2 3\n")
    assert rec.coordinate_frame == "unknown"
    assert rec.scale_to_meters == 1.0
    assert rec.intensity_range == "unknown"


# --- column-count auto-detection -------------------------------------------
def test_column_count_four_is_intensity():
    rec = _core.read_xyz(b"1 2 3 7\n")
    assert rec.has_intensity and not rec.has_rgb and not rec.has_normals
    np.testing.assert_array_equal(np.asarray(rec.intensities), np.array([7.0], np.float32))
    assert np.asarray(rec.intensities).shape == (1,)


def test_column_count_seven_is_intensity_rgb():
    rec = _core.read_xyz(b"1 2 3 9 10 20 30\n")
    assert rec.has_intensity and rec.has_rgb and not rec.has_normals
    np.testing.assert_array_equal(np.asarray(rec.intensities), np.array([9.0], np.float32))
    np.testing.assert_array_equal(np.asarray(rec.colors), np.array([[10, 20, 30]], np.uint8))


def test_column_count_nine_is_rgb_normals():
    rec = _core.read_xyz(b"1 2 3 10 20 30 0.5 -0.25 0.75\n")
    assert rec.has_rgb and rec.has_normals and not rec.has_intensity
    np.testing.assert_array_equal(np.asarray(rec.colors), np.array([[10, 20, 30]], np.uint8))
    np.testing.assert_array_equal(
        np.asarray(rec.normals), np.array([[0.5, -0.25, 0.75]], np.float32)
    )


@pytest.mark.parametrize(
    "data",
    [
        b"1 2\n",  # 2
        b"1 2 3 4 5\n",  # 5
        b"1 2 3 4 5 6 7 8\n",  # 8
        b"1 2 3 4 5 6 7 8 9 10\n",  # 10
    ],
)
def test_unsupported_column_count_raises(data):
    with pytest.raises(ValueError, match="unsupported column count"):
        _core.read_xyz(data)


def test_mid_file_column_change_raises():
    # line 1 fixes C=3; line 3 has 6 columns -> raises with the 1-based line no.
    with pytest.raises(ValueError, match="line 3: expected 3 numbers"):
        _core.read_xyz(b"1 2 3\n4 5 6\n7 8 9 10 11 12\n")


def test_extra_trailing_token_raises():
    with pytest.raises(ValueError, match="line 2: expected 3 numbers"):
        _core.read_xyz(b"1 2 3\n4 5 6 7\n")


def test_too_few_tokens_raises():
    with pytest.raises(ValueError, match="line 2: expected 6 numbers"):
        _core.read_xyz(b"1 2 3 10 20 30\n4 5 6 40 50\n")


# --- grammar edge cases -----------------------------------------------------
def test_crlf_and_missing_final_newline():
    rec = _core.read_xyz(b"1 2 3\r\n4 5 6")  # CRLF + no trailing newline
    assert rec.num_points == 2
    np.testing.assert_array_equal(
        np.asarray(rec.positions), np.array([[1, 2, 3], [4, 5, 6]], np.float32)
    )


def test_blank_and_comment_lines_anywhere():
    data = b"\n# lead comment\n1 2 3\n\n  \n2 3 4\n# trailing comment\n"
    rec = _core.read_xyz(data)
    assert rec.num_points == 2
    np.testing.assert_array_equal(
        np.asarray(rec.positions), np.array([[1, 2, 3], [2, 3, 4]], np.float32)
    )


def test_comma_and_tab_separators():
    rec = _core.read_xyz(b"1,2,3\n4\t5\t6\n")
    np.testing.assert_array_equal(
        np.asarray(rec.positions), np.array([[1, 2, 3], [4, 5, 6]], np.float32)
    )
    # runs of commas collapse (still 3 tokens)
    rec2 = _core.read_xyz(b"1,,2,3\n")
    np.testing.assert_array_equal(np.asarray(rec2.positions), np.array([[1, 2, 3]], np.float32))


@pytest.mark.parametrize("data", [b"", b"\n\n", b"   \n", b"# only comments\n#more\n"])
def test_empty_or_comment_only_is_empty_cloud(data):
    rec = _core.read_xyz(data)
    assert rec.num_points == 0
    assert np.asarray(rec.positions).shape == (0, 3)
    assert np.asarray(rec.positions).dtype == np.float32
    assert not rec.has_rgb and not rec.has_normals and not rec.has_intensity


# --- malformed input raises (FormatError-mappable ValueError), never crashes -
@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"1 2 foo\n", "could not parse"),  # non-numeric token
        (b"1 2 3.4.5\n", "could not parse"),  # not a full number
        (b"1 2 3 10 20 256\n", "0..255"),  # rgb above range
        (b"1 2 3 10 20 -1\n", "0..255"),  # rgb below range
        (b"1 2 3 10 20 2.5\n", "0..255"),  # rgb not integral
        (b"1 2\n", "unsupported column count"),  # bad first-line width
    ],
)
def test_malformed_raises(data, match):
    with pytest.raises(ValueError, match=match):
        _core.read_xyz(data)


def test_single_byte_mutation_never_crashes():
    # Every single-byte mutation of a valid fixture must either parse or raise
    # ValueError -- never crash / read out of bounds (test_netpbm fuzz style).
    base = b"# hdr\n1 2 3 10 20 30\n4 5 6 40 50 60\n"
    for i in range(len(base)):
        for b in (0x00, 0x20, 0x23, 0x2C, 0x41, 0xFF, 0x2E, 0x2D, 0x0A):
            mutated = base[:i] + bytes([b]) + base[i + 1 :]
            try:
                _core.read_xyz(mutated)
            except ValueError:
                pass


# --- golden writer blobs (encode-drift guard, platform-stable) --------------
def test_golden_writer_blobs():
    pc_rgb = _core.point_cloud(
        np.array([[1, 2, 3]], np.float32), colors=np.array([[10, 20, 30]], np.uint8)
    )
    assert _core.write_xyz(pc_rgb) == b"1 2 3 10 20 30\n"
    pc_xyz = _core.point_cloud(np.array([[1, 2, 3]], np.float32))
    assert _core.write_xyz(pc_xyz) == b"1 2 3\n"
    # an empty cloud writes empty bytes (and reads back empty)
    pc_empty = _core.point_cloud(np.zeros((0, 3), np.float32))
    assert _core.write_xyz(pc_empty) == b""
    assert _core.read_xyz(b"").num_points == 0


# --- writer guards (refuse what the layout cannot carry) --------------------
def test_writer_guard_normals():
    pc = _core.point_cloud(np.zeros((2, 3), np.float32), normals=np.ones((2, 3), np.float32))
    with pytest.raises(ValueError, match="normals"):
        _core.write_xyz(pc)


def test_writer_guard_intensity():
    pc = _core.point_cloud(np.zeros((2, 3), np.float32), intensity=np.ones((2,), np.float32))
    with pytest.raises(ValueError, match="intensity"):
        _core.write_xyz(pc)


# --- numpy/torch interop (test_pfm.py:100 pattern) --------------------------
def test_torch_interop():
    torch = pytest.importorskip("torch")
    rng = np.random.default_rng(0)
    xyz = rng.standard_normal((4, 3)).astype(np.float32)
    # factory accepts a torch tensor; write -> read round-trips bit-exactly
    pc = _core.point_cloud(torch.from_numpy(xyz).contiguous())
    rec = _core.read_xyz(_core.write_xyz(pc))
    assert np.asarray(rec.positions).tobytes() == xyz.tobytes()
    # read output -> torch via DLPack, values agree with numpy (zero-copy CPU)
    view = np.asarray(rec.positions)
    back = torch.from_dlpack(rec.positions)
    assert np.array_equal(back.numpy(), view)
