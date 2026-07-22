"""Record-level suite for the PointCloud record (SoA, zero-copy: required
positions (N,3) f32 + optional colors (N,3) u8 / normals (N,3) f32 / intensity
(N,) f32, with recorded coordinate_frame/scale_to_meters/intensity_range
conventions).

Mirrors tests/records/test_image.py: numpy is the self-contained oracle (the
``point_cloud(...)`` factory + the four views must reproduce the source arrays
bit-exactly), plus convention pins, presence-flag combinations, zero-copy /
gc-lifetime checks, and numpy/torch interop.

This is a *record* (not a codec), so there are no read_*/write_* here. The three
codec-tier parity kinds ride on this record once the .xyz/.pts codec lands; this
file pins the record contract that codec builds on. Float fields are compared
via ``.tobytes()`` (with hand-stamped NaN/-0.0/denormal payloads) because
``assert_array_equal`` alone is blind to NaN payload bits and the sign of zero.
"""

from __future__ import annotations

import gc

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


# Hand-picked special float32 bit patterns: payload qNaN, negative qNaN with
# payload, sNaN with payload, -0.0, smallest positive denormal, +inf. Stamped
# into the leading elements of every float field so bit-exact preservation is
# pinned deterministically (via .tobytes()) rather than left to a random draw.
_F32_SPECIAL_BITS = np.array(
    [0x7FC00ABC, 0xFFC00001, 0x7F800001, 0x80000000, 0x00000001, 0x7F800000],
    np.uint32,
)


def _stamp(flat: np.ndarray) -> np.ndarray:
    """Stamp the special float32 payloads into the leading elements of a 1-D
    float32 buffer (in place), returning it."""
    specials = _F32_SPECIAL_BITS.view(np.float32)
    k = min(flat.size, specials.size)
    flat[:k] = specials[:k]
    return flat


@pytest.fixture
def sample() -> dict:
    """One populated cloud: N=5, all four fields, float fields carrying stamped
    special payloads so the round-trip pins bit-exact float preservation."""
    n = 5
    rng = np.random.default_rng(0)
    xyz = _stamp(rng.standard_normal(n * 3).astype(np.float32)).reshape(n, 3)
    normals = _stamp(rng.standard_normal(n * 3).astype(np.float32)).reshape(n, 3)
    intensity = _stamp(rng.standard_normal(n).astype(np.float32))
    rgb = rng.integers(0, 256, size=(n, 3)).astype(np.uint8)
    return {"n": n, "xyz": xyz, "rgb": rgb, "normals": normals, "intensity": intensity}


# --- factory round-trip identity (numpy is the oracle) ---------------------
def test_factory_roundtrip_all_fields(sample):
    n, xyz, rgb, normals, intensity = (
        sample["n"],
        sample["xyz"],
        sample["rgb"],
        sample["normals"],
        sample["intensity"],
    )
    pc = _core.point_cloud(xyz, colors=rgb, normals=normals, intensity=intensity)
    assert pc.num_points == n
    # bit-exact (NaN-payload / -0.0 aware) via .tobytes(); assert_array_equal is
    # blind to those, so pin both.
    np.testing.assert_array_equal(pc.positions, xyz)
    assert pc.positions.tobytes() == xyz.tobytes()
    np.testing.assert_array_equal(pc.colors, rgb)
    assert pc.colors.tobytes() == rgb.tobytes()
    np.testing.assert_array_equal(pc.normals, normals)
    assert pc.normals.tobytes() == normals.tobytes()
    np.testing.assert_array_equal(pc.intensities, intensity)
    assert pc.intensities.tobytes() == intensity.tobytes()
    # dtypes + shapes pinned to the canonical layout
    assert pc.positions.dtype == np.float32 and pc.positions.shape == (n, 3)
    assert pc.colors.dtype == np.uint8 and pc.colors.shape == (n, 3)
    assert pc.normals.dtype == np.float32 and pc.normals.shape == (n, 3)
    assert pc.intensities.dtype == np.float32 and pc.intensities.shape == (n,)
    assert pc.has_rgb and pc.has_normals and pc.has_intensity


def test_minimal_positions_only(sample):
    pc = _core.point_cloud(sample["xyz"])
    assert not pc.has_rgb and not pc.has_normals and not pc.has_intensity
    # absent optionals surface as shaped-empty arrays, never None
    # (PosedViewSet.timestamps precedent)
    assert pc.colors.shape == (0, 3) and pc.colors.dtype == np.uint8
    assert pc.normals.shape == (0, 3) and pc.normals.dtype == np.float32
    assert pc.intensities.shape == (0,) and pc.intensities.dtype == np.float32
    assert pc.positions.tobytes() == sample["xyz"].tobytes()
    assert pc.num_points == sample["n"]


def test_presence_flag_combinations(sample):
    xyz, rgb, normals, intensity = (
        sample["xyz"],
        sample["rgb"],
        sample["normals"],
        sample["intensity"],
    )
    # rgb only
    pc = _core.point_cloud(xyz, colors=rgb)
    assert pc.has_rgb and not pc.has_normals and not pc.has_intensity
    np.testing.assert_array_equal(pc.colors, rgb)
    assert pc.normals.shape == (0, 3) and pc.intensities.shape == (0,)
    # normals only
    pc = _core.point_cloud(xyz, normals=normals)
    assert not pc.has_rgb and pc.has_normals and not pc.has_intensity
    assert pc.normals.tobytes() == normals.tobytes()
    assert pc.colors.shape == (0, 3) and pc.intensities.shape == (0,)
    # intensity only
    pc = _core.point_cloud(xyz, intensity=intensity)
    assert not pc.has_rgb and not pc.has_normals and pc.has_intensity
    assert pc.intensities.tobytes() == intensity.tobytes()
    assert pc.colors.shape == (0, 3) and pc.normals.shape == (0, 3)


# --- factory validation (raise, never crash) -------------------------------
def test_validation_errors(sample):
    n, good = sample["n"], sample["xyz"]  # good positions (N,3) f32
    # match= pins each error to the check that must raise it.
    with pytest.raises(ValueError, match="positions"):  # (N,4)
        _core.point_cloud(np.zeros((n, 4), np.float32))
    with pytest.raises(ValueError, match="positions"):  # 1-D (N,)
        _core.point_cloud(np.zeros((n,), np.float32))
    with pytest.raises(ValueError, match="positions"):  # 3-D
        _core.point_cloud(np.zeros((n, 3, 1), np.float32))
    with pytest.raises(ValueError, match="colors"):  # row mismatch (N-1,3)
        _core.point_cloud(good, colors=np.zeros((n - 1, 3), np.uint8))
    with pytest.raises(ValueError, match="colors"):  # (N,4)
        _core.point_cloud(good, colors=np.zeros((n, 4), np.uint8))
    with pytest.raises(ValueError, match="normals"):  # (N,2)
        _core.point_cloud(good, normals=np.zeros((n, 2), np.float32))
    with pytest.raises(ValueError, match="intensity must be"):  # (N+1,)
        _core.point_cloud(good, intensity=np.zeros((n + 1,), np.float32))
    with pytest.raises(ValueError, match="intensity must be"):  # 2-D (N,1)
        _core.point_cloud(good, intensity=np.zeros((n, 1), np.float32))
    with pytest.raises(ValueError, match="coordinate_frame"):  # bad vocab
        _core.point_cloud(good, coordinate_frame="blender")
    with pytest.raises(ValueError, match="intensity_range"):  # bad vocab
        _core.point_cloud(good, intensity_range="u32")


# --- convention recording (metadata, PosedViewSet flavor) ------------------
def test_convention_defaults_and_recording(sample):
    xyz = sample["xyz"]
    pc = _core.point_cloud(xyz)
    assert pc.coordinate_frame == "unknown"
    assert pc.scale_to_meters == 1.0
    assert pc.intensity_range == "unknown"
    # overrides recorded verbatim (0.3048 = survey feet -> meters)
    pc2 = _core.point_cloud(
        xyz, coordinate_frame="opencv", scale_to_meters=0.3048, intensity_range="u16"
    )
    assert pc2.coordinate_frame == "opencv"
    assert pc2.scale_to_meters == 0.3048
    assert pc2.intensity_range == "u16"
    # every vocabulary token is accepted and echoed
    for f in ("unknown", "opencv", "opengl", "enu", "ned"):
        assert _core.point_cloud(xyz, coordinate_frame=f).coordinate_frame == f
    for r in ("unknown", "unit", "u8", "u16"):
        assert _core.point_cloud(xyz, intensity_range=r).intensity_range == r


# --- edge shapes -----------------------------------------------------------
def test_empty_cloud_is_legal():
    empty = np.zeros((0, 3), np.float32)
    pc = _core.point_cloud(empty)
    assert pc.num_points == 0
    assert pc.positions.shape == (0, 3) and pc.positions.dtype == np.float32
    assert not pc.has_rgb and not pc.has_normals and not pc.has_intensity
    assert pc.colors.shape == (0, 3)
    assert pc.normals.shape == (0, 3)
    assert pc.intensities.shape == (0,)
    # N==0 optionals collapse to empty vectors, so has_* stays False even when a
    # (0,3) array is passed — has_* derives from vector emptiness, not the arg.
    pc2 = _core.point_cloud(empty, colors=np.zeros((0, 3), np.uint8))
    assert not pc2.has_rgb
    assert pc2.colors.shape == (0, 3)


def test_noncontiguous_input_is_copied():
    # farr/carr declare c_contig, so nanobind copies a strided source (image.cpp:
    # "non-contiguous input is copied by nb"); logical values must survive.
    base = np.arange(30, dtype=np.float32).reshape(5, 6)
    xyz = base[:, ::2]  # (5,3), non-contiguous
    assert not xyz.flags["C_CONTIGUOUS"]
    np.testing.assert_array_equal(_core.point_cloud(xyz).positions, xyz)
    cbase = np.arange(30, dtype=np.uint8).reshape(5, 6)
    rgb = cbase[:, ::2]
    pc = _core.point_cloud(np.ascontiguousarray(xyz), colors=rgb)
    np.testing.assert_array_equal(pc.colors, rgb)


# --- zero-copy + lifetime (the vw + reference_internal keepalive gate) ------
def test_zero_copy_two_views_share_buffer(sample):
    pc = _core.point_cloud(sample["xyz"], colors=sample["rgb"])
    a = pc.positions
    b = pc.positions
    assert a.ctypes.data == b.ctypes.data  # no copy; both view the record buffer
    np.testing.assert_array_equal(a, b)
    ca = pc.colors
    cb = pc.colors
    assert ca.ctypes.data == cb.ctypes.data
    # a mutation through one view is visible through the other and a fresh fetch
    # -> they alias the record's storage, not a per-call cached copy
    before = int(np.asarray(pc.colors)[0, 0])
    sentinel = (before + 1) & 0xFF  # guaranteed != before
    ca[0, 0] = sentinel
    assert cb[0, 0] == sentinel
    assert int(np.asarray(pc.colors)[0, 0]) == sentinel


def test_views_keep_record_alive_after_gc(sample):
    # The record is never bound to a name — only the returned view references it
    # through the reference_internal keepalive. A broken keepalive frees the
    # record and the view then reads freed memory.
    expected_xyz = sample["xyz"].copy()
    expected_rgb = sample["rgb"].copy()
    px = _core.point_cloud(sample["xyz"], colors=sample["rgb"]).positions
    cx = _core.point_cloud(sample["xyz"], colors=sample["rgb"]).colors
    gc.collect()
    gc.collect()
    assert px.tobytes() == expected_xyz.tobytes()  # bit-exact incl. stamped NaNs
    np.testing.assert_array_equal(cx, expected_rgb)

    # A multi-MiB buffer is returned to the OS on free (VirtualFree), so a
    # missing owner faults deterministically instead of reading stale heap.
    big = np.arange(3 << 20, dtype=np.float32).reshape(1 << 20, 3)
    expected_big = big.copy()
    px = _core.point_cloud(big).positions
    del big
    gc.collect()
    gc.collect()
    scribble = [np.full(1 << 20, 0xAB, np.uint8) for _ in range(4)]  # churn the heap
    np.testing.assert_array_equal(px, expected_big)
    assert scribble[0][0] == 0xAB  # keep the churn alive until after the compare


# --- repr pin --------------------------------------------------------------
def test_repr_pin(sample):
    pc = _core.point_cloud(
        sample["xyz"],
        colors=sample["rgb"],
        normals=sample["normals"],
        intensity=sample["intensity"],
    )
    assert repr(pc) == "<PointCloud n=5 rgb normals intensity unknown>"
    pc_min = _core.point_cloud(np.zeros((3, 3), np.float32))
    assert repr(pc_min) == "<PointCloud n=3 unknown>"
    # single optional + non-default frame: only that token appears, in the frame slot
    pc_partial = _core.point_cloud(
        np.zeros((3, 3), np.float32),
        intensity=np.zeros((3,), np.float32),
        coordinate_frame="ned",
    )
    assert repr(pc_partial) == "<PointCloud n=3 intensity ned>"


# --- cross-framework interop (torch, optional) -----------------------------
def test_torch_from_dlpack(sample):
    torch = pytest.importorskip("torch")
    pc = _core.point_cloud(
        sample["xyz"],
        colors=sample["rgb"],
        normals=sample["normals"],
        intensity=sample["intensity"],
    )
    for view, src in (
        (pc.positions, sample["xyz"]),
        (pc.colors, sample["rgb"]),
        (pc.normals, sample["normals"]),
        (pc.intensities, sample["intensity"]),
    ):
        back = torch.from_dlpack(view)
        # bit-exact (NaN-payload / -0.0 aware), unlike np.array_equal
        assert back.numpy().tobytes() == np.asarray(view).tobytes()
        assert np.asarray(view).tobytes() == src.tobytes()


def test_factory_accepts_torch_input(sample):
    torch = pytest.importorskip("torch")
    xyz_t = torch.from_numpy(sample["xyz"]).contiguous()
    rgb_t = torch.from_numpy(sample["rgb"]).contiguous()
    normals_t = torch.from_numpy(sample["normals"]).contiguous()
    intensity_t = torch.from_numpy(sample["intensity"]).contiguous()
    pc = _core.point_cloud(xyz_t, colors=rgb_t, normals=normals_t, intensity=intensity_t)
    assert pc.positions.tobytes() == sample["xyz"].tobytes()
    np.testing.assert_array_equal(pc.colors, sample["rgb"])
    assert pc.normals.tobytes() == sample["normals"].tobytes()
    assert pc.intensities.tobytes() == sample["intensity"].tobytes()


# --- foreign-dtype caster behavior pin -------------------------------------
def test_foreign_dtype_input_behavior_pin():
    # The typed caster either copy-converts a foreign dtype to the canonical
    # dtype (the make_pvs precedent) or rejects it — pin whichever the built
    # extension does so the semantic is documented and cannot silently corrupt
    # (mirrors test_image.py::test_big_endian_input_rejected_or_byte_preserved).
    rng = np.random.default_rng(7)
    xyz = rng.standard_normal((5, 3)).astype(np.float32)
    rgb = rng.integers(0, 256, size=(5, 3)).astype(np.uint8)

    try:
        pc = _core.point_cloud(xyz.astype(np.float64))
    except (TypeError, ValueError):
        pass  # rejection is a pinned-safe outcome
    else:
        assert pc.positions.dtype == np.float32  # canonical, never float64
        # f32->f64->f32 is lossless for these normal values
        np.testing.assert_array_equal(pc.positions, xyz)

    try:
        pc = _core.point_cloud(xyz, colors=rgb.astype(np.int32))
    except (TypeError, ValueError):
        pass  # rejection is a pinned-safe outcome
    else:
        assert pc.colors.dtype == np.uint8
        np.testing.assert_array_equal(pc.colors, rgb)
