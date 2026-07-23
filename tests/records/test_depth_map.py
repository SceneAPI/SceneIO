"""Record-level suite for the DepthMap scalar record (depth HxW f32 + optional
confidence HxW f32 + recorded unit / scale_to_meters / invalid_policy
conventions).

Mirrors tests/records/test_image.py: numpy is the self-contained oracle (the
``depth_map`` factory + the ``depth``/``confidence`` accessors must reproduce
the source arrays bit-exactly), plus hand-derived convention pins (TUM 5000 *
1/5000 == 1.0 m; ScanNet 1500 mm * 0.001 == 1.5 m), zero-copy/lifetime checks,
and numpy/torch interop.

This is a *record* (not a codec), so there are no read_*/write_* here -- the
three codec-tier parity kinds ride on this record once its first codec lands
(16-bit depth PNG / .dmb / EXR-depth, later work items). Optical flow (.flo) is
a SEPARATE bare-(H,W,2)-ndarray codec and intentionally does NOT use this
scalar record. Note the deliberate cross-namespace name split: this is
_core.DepthMap (policy-tagged sentinels + raw unscrubbed values), distinct from
sceneio.data.DepthMap (the frozen validation contract: bool valid mask, strict
>0/[0,1]).
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
    reason="sceneio._core not built (compiled-only package -- build the extension first)",
)


def _stamp_specials(arr: np.ndarray) -> np.ndarray:
    """Splice hand-stamped IEEE-754 float32 special bit patterns into the first
    six elements (payload qNaN, negative qNaN with payload, sNaN with payload,
    -0.0, smallest positive denormal, +inf) so a ``.tobytes()`` compare pins
    bit-exact preservation -- ``assert_array_equal`` alone is blind to NaN
    payload bits and the sign of zero. (test_image.py samples() precedent.)
    Same-dtype assignment is a bit copy, so the sNaN is not quieted."""
    flat = np.ascontiguousarray(arr, dtype=np.float32).reshape(-1).copy()
    assert flat.size >= 6
    flat[:6] = np.array(
        [0x7FC00ABC, 0xFFC00001, 0x7F800001, 0x80000000, 0x00000001, 0x7F800000],
        np.uint32,
    ).view(np.float32)
    return flat.reshape(arr.shape)


# --- factory round-trip identity (numpy is the oracle) ---------------------
def test_factory_roundtrip():
    rng = np.random.default_rng(0)
    for h, w in [(1, 1), (4, 6), (5, 7), (13, 3)]:
        arr = rng.standard_normal((h, w)).astype(np.float32)
        if arr.size >= 6:
            arr = _stamp_specials(arr)  # pin bit-exact float-special preservation
        rec = _core.depth_map(arr)
        assert (rec.height, rec.width) == (h, w)
        assert rec.depth.dtype == np.float32
        assert rec.depth.shape == (h, w)
        np.testing.assert_array_equal(rec.depth, arr)  # values (NaN-position aware)
        assert rec.depth.tobytes() == arr.tobytes()  # bit-exact incl. NaN payloads / -0.0


def test_noncontiguous_input_is_copied():
    # nanobind's c_contig conversion copies strided / reversed views; the
    # logical values must survive the copy, not be read with the wrong strides.
    base = np.arange(48, dtype=np.float32).reshape(4, 12)
    for nc in (base[:, ::2], base[::-1]):  # strided columns; reversed rows
        np.testing.assert_array_equal(_core.depth_map(nc).depth, nc)


# --- optional confidence ---------------------------------------------------
def test_confidence_optional():
    rng = np.random.default_rng(1)
    depth = rng.standard_normal((5, 7)).astype(np.float32)

    rec = _core.depth_map(depth)  # absent
    assert rec.has_confidence is False
    assert rec.confidence is None  # shaped-empty is NOT used -- absent means None

    conf = rng.standard_normal((5, 7)).astype(np.float32)
    rec = _core.depth_map(depth, confidence=conf)  # present
    assert rec.has_confidence is True
    assert rec.confidence.dtype == np.float32
    assert rec.confidence.shape == (5, 7)
    np.testing.assert_array_equal(rec.confidence, conf)
    assert rec.confidence.tobytes() == conf.tobytes()  # bit-exact

    # shape mismatch (must be exactly (H,W)) raises
    for bad in [
        np.zeros((5, 8), np.float32),
        np.zeros((6, 7), np.float32),
        np.zeros((35,), np.float32),
        np.zeros((5, 7, 1), np.float32),
    ]:
        with pytest.raises(ValueError, match="confidence"):
            _core.depth_map(depth, confidence=bad)
    # dtype mismatch (must be float32) raises
    for bad in [np.zeros((5, 7), np.float64), np.zeros((5, 7), np.int32)]:
        with pytest.raises(ValueError, match="confidence"):
            _core.depth_map(depth, confidence=bad)


# --- unit / scale_to_meters resolution -------------------------------------
def test_unit_scale_defaults_and_derivation():
    depth = np.zeros((2, 2), np.float32)

    # neither given -> struct defaults
    rec = _core.depth_map(depth)
    assert rec.unit == "meters"
    assert rec.scale_to_meters == 1.0

    # unit only -> derive scale
    assert _core.depth_map(depth, unit="meters").scale_to_meters == 1.0
    assert _core.depth_map(depth, unit="millimeters").scale_to_meters == 0.001
    assert _core.depth_map(depth, unit="unitless").scale_to_meters == 0.0
    assert _core.depth_map(depth, unit="unknown").scale_to_meters == 0.0

    # scale only -> derive unit
    assert _core.depth_map(depth, scale_to_meters=1.0).unit == "meters"
    assert _core.depth_map(depth, scale_to_meters=0.001).unit == "millimeters"
    assert _core.depth_map(depth, scale_to_meters=0.0002).unit == "custom"
    assert _core.depth_map(depth, scale_to_meters=0.0).unit == "unknown"

    # both given + consistent -> recorded verbatim
    for u, s in [
        ("meters", 1.0),
        ("millimeters", 0.001),
        ("custom", 0.0002),
        ("unitless", 0.0),
        ("unknown", 0.0),
    ]:
        rec = _core.depth_map(depth, unit=u, scale_to_meters=s)
        assert (rec.unit, rec.scale_to_meters) == (u, s)


def test_unit_scale_pairing_guards():
    depth = np.zeros((2, 2), np.float32)

    with pytest.raises(ValueError, match="custom"):  # custom needs an explicit scale
        _core.depth_map(depth, unit="custom")

    # inconsistent unit/scale pairs raise (the Image dtype<->maxval guard, transposed)
    for u, s in [
        ("meters", 0.001),
        ("meters", 2.0),
        ("millimeters", 1.0),
        ("unitless", 1.0),
        ("unknown", 0.001),
        ("custom", 0.0),
        ("custom", -1.0),
        # non-finite custom scale via the both-given path pins the isfinite()
        # conjunct in depth_map_unit_scale_consistent (s > 0.0 alone accepts +inf).
        ("custom", float("inf")),
        ("custom", float("nan")),
    ]:
        with pytest.raises(ValueError, match="mismatch"):
            _core.depth_map(depth, unit=u, scale_to_meters=s)

    # both-given with an out-of-vocabulary unit raises the VOCAB error (not the
    # pairing error), pinning that the both-given branch validates the token and
    # does so BEFORE the pairing check. Match "unit must" (not bare "unit": the
    # "unit/scale mismatch" message also contains "unit" and would not
    # discriminate). scale 0.0 kills a dropped vocab check (the pairing fallthrough
    # would accept any token at s==0.0); the nonzero feet/0.3048 case kills a
    # reordering that ran the pairing check first.
    for tok, s in [("mm", 0.0), ("feet", 0.0), ("Meters", 0.0), ("feet", 0.3048)]:
        with pytest.raises(ValueError, match="unit must"):
            _core.depth_map(depth, unit=tok, scale_to_meters=s)

    # negative / NaN / inf scale (scale-only branch) is not a usable scale
    for bad in (-1.0, -0.5, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="scale_to_meters"):
            _core.depth_map(depth, scale_to_meters=bad)

    # unknown unit tokens raise (closed vocabulary, case-sensitive)
    for tok in ("mm", "feet", "Meters", "metres", ""):
        with pytest.raises(ValueError, match="unit"):
            _core.depth_map(depth, unit=tok)


# --- invalid_policy vocabulary + no-scrub guarantee ------------------------
def test_invalid_policy_vocabulary_and_no_scrub():
    depth = np.zeros((2, 2), np.float32)
    for pol in ("none", "zero", "nonfinite", "negative"):
        assert _core.depth_map(depth, invalid_policy=pol).invalid_policy == pol
    for bad in ("nan", "Zero", "invalid", "sentinel", ""):
        with pytest.raises(ValueError, match="invalid_policy"):
            _core.depth_map(depth, invalid_policy=bad)

    # reader RECORDS, never judges: a raster with +0/+inf/-inf/qNaN/-1/-0/denormal/sNaN
    # survives BIT-EXACT under every policy (no scan, no scrub).
    hostile = np.array(
        [
            [0x00000000, 0x7F800000, 0xFF800000, 0x7FC00000],  # +0.0, +inf, -inf, qNaN
            [0xBF800000, 0x80000000, 0x00000001, 0x7F800001],
        ],  # -1.0, -0.0, denormal, sNaN
        np.uint32,
    ).view(np.float32)
    expected = hostile.tobytes()
    for pol in ("none", "zero", "nonfinite", "negative"):
        rec = _core.depth_map(hostile, invalid_policy=pol)
        assert rec.depth.tobytes() == expected  # never rescaled / scrubbed, bit-exact


# --- hand-derived convention pins (external ground truth, no oracle file) ---
def test_convention_pin_hand_derived():
    # TUM RGB-D: 16-bit PNG stores raw counts, metric depth = count / 5000.
    tum = np.full((3, 4), 5000.0, np.float32)
    rec = _core.depth_map(tum, unit="custom", scale_to_meters=1 / 5000)
    assert rec.unit == "custom"
    assert rec.scale_to_meters == 1 / 5000  # recorded verbatim, no re-derivation
    assert 5000.0 * rec.scale_to_meters == 1.0  # hand-derived: exactly 1.0 m (IEEE-exact)

    # ScanNet / Azure Kinect: depth stored in millimeters, metric = mm / 1000.
    scannet = np.full((3, 4), 1500.0, np.float32)
    rec = _core.depth_map(scannet, unit="millimeters")
    assert rec.scale_to_meters == 0.001  # derived from the unit
    assert 1500.0 * rec.scale_to_meters == 1.5  # hand-derived: exactly 1.5 m (IEEE-exact)


# --- fixed canonical row_order + origin -------------------------------------
def test_row_order_fixed_and_origin():
    # asymmetric ramp: a row-flip bug would move the 0 off the top-left corner
    # (the PFM bottom-up-rows trap, transposed to this record).
    ramp = np.arange(3 * 4, dtype=np.float32).reshape(3, 4)  # ramp[0,0] == 0
    rec = _core.depth_map(ramp)
    assert rec.row_order == "top_to_bottom"  # always fixed canon
    assert rec.depth[0, 0] == 0.0  # top-left origin preserved
    assert rec.depth[-1, -1] == 11.0
    np.testing.assert_array_equal(rec.depth, ramp)
    # fixed regardless of the recorded conventions
    assert _core.depth_map(ramp, unit="unknown", scale_to_meters=0.0).row_order == "top_to_bottom"


# --- zero-copy + lifetime (the sio::view owner keepalive gate) -------------
def test_zero_copy_two_views_share_buffer():
    rng = np.random.default_rng(2)
    depth = rng.standard_normal((5, 7)).astype(np.float32)
    conf = rng.standard_normal((5, 7)).astype(np.float32)
    rec = _core.depth_map(depth, confidence=conf)

    a, b = rec.depth, rec.depth
    assert a.ctypes.data == b.ctypes.data  # no copy; both view the record's buffer
    c1, c2 = rec.confidence, rec.confidence
    assert c1.ctypes.data == c2.ctypes.data  # confidence view is zero-copy too

    # a mutation through one view is visible through the other and a fresh view
    # -> they alias the record's storage, not a per-call cached copy.
    a[0, 0] = 42.0
    assert b[0, 0] == 42.0
    assert float(np.asarray(rec.depth)[0, 0]) == 42.0


def test_views_keep_record_alive_after_gc():
    # The record is never bound to a name -- only the returned view references it
    # (through the sio::view owner). If the keepalive is wrong, gc frees the
    # record and the view then reads freed memory. (test_pixels_keeps_image_alive
    # precedent; depth AND confidence exercise the owner independently.)
    rng = np.random.default_rng(3)
    depth = _stamp_specials(rng.standard_normal((16, 16)).astype(np.float32))
    conf = rng.standard_normal((16, 16)).astype(np.float32)
    expected_d, expected_c = depth.tobytes(), conf.tobytes()

    dv = _core.depth_map(depth, confidence=conf).depth
    cv = _core.depth_map(depth, confidence=conf).confidence
    gc.collect()
    gc.collect()
    assert dv.tobytes() == expected_d  # buffer intact after collection
    assert cv.tobytes() == expected_c

    # A multi-MiB buffer is returned to the OS on free (VirtualFree on Windows),
    # so a missing owner faults deterministically instead of reading stale heap.
    big = np.arange(1 << 20, dtype=np.float32).reshape(1024, 1024)  # 4 MiB, values < 2**24 exact
    expected_big = big.copy()
    px = _core.depth_map(big).depth
    del big
    gc.collect()
    gc.collect()
    scribble = [np.full(1 << 20, 0xAB, np.uint8) for _ in range(4)]  # churn the heap
    np.testing.assert_array_equal(px, expected_big)
    assert scribble[0][0] == 0xAB  # keep the churn alive until after the compare

    # Same deterministic big-buffer gate for the .confidence accessor -- a
    # DISTINCT owner-attachment path (nb::cast(sio::view(self, ...)) inside an
    # nb::object-returning lambda), so the depth gate above does NOT cover it. A
    # broken confidence owner (lost handle / wrong owner) faults here instead of
    # passing by luck on a small freed heap block.
    big_d = np.zeros((1024, 1024), np.float32)
    big_c = np.arange(1 << 20, dtype=np.float32).reshape(1024, 1024)  # 4 MiB, < 2**24 exact
    expected_bc = big_c.copy()
    cv2 = _core.depth_map(big_d, confidence=big_c).confidence
    del big_d, big_c
    gc.collect()
    gc.collect()
    scribble2 = [np.full(1 << 20, 0xAB, np.uint8) for _ in range(4)]  # churn the heap
    np.testing.assert_array_equal(cv2, expected_bc)
    assert scribble2[0][0] == 0xAB  # keep the churn alive until after the compare


# --- factory validation -----------------------------------------------------
def test_validation_errors():
    # shape: exactly (H,W) with H,W >= 1 (no (H,W,1) squeeze -- unlike Image)
    with pytest.raises(ValueError, match=r"H,W"):  # 1-D
        _core.depth_map(np.zeros((12,), np.float32))
    with pytest.raises(ValueError, match=r"H,W"):  # 3-D
        _core.depth_map(np.zeros((3, 4, 1), np.float32))
    with pytest.raises(ValueError, match=r"H,W"):  # zero-size, H == 0
        _core.depth_map(np.zeros((0, 4), np.float32))
    with pytest.raises(ValueError, match=r"H,W"):  # zero-size, W == 0
        _core.depth_map(np.zeros((4, 0), np.float32))

    # dtype: float32 only, NO silent convert -> the clear "must be float32" message
    for dt in (np.float64, np.int32, np.uint16, np.uint8, np.int16, np.float16):
        with pytest.raises(ValueError, match="must be float32"):
            _core.depth_map(np.zeros((3, 4), dt))


def test_confidence_range_unconstrained():
    # Confidence carries RAW stored scores -- values outside [0,1] are accepted
    # verbatim, pinning the intentional divergence from sceneio.data.ConfidenceMap
    # (which requires [0,1]). Reader records, never normalizes.
    depth = np.zeros((2, 3), np.float32)
    conf = np.array([[3.7, -0.2, 100.0], [-5.0, 0.5, 1e9]], np.float32)
    rec = _core.depth_map(depth, confidence=conf)
    np.testing.assert_array_equal(rec.confidence, conf)
    assert rec.confidence.tobytes() == conf.tobytes()


# --- cross-framework interop (torch, optional) -----------------------------
def test_torch_interop():
    torch = pytest.importorskip("torch")
    rng = np.random.default_rng(4)
    depth = rng.standard_normal((5, 7)).astype(np.float32)
    conf = rng.standard_normal((5, 7)).astype(np.float32)

    # factory accepts torch float32 tensors for depth AND confidence
    rec = _core.depth_map(
        torch.from_numpy(depth).contiguous(),
        confidence=torch.from_numpy(conf).contiguous(),
    )
    np.testing.assert_array_equal(rec.depth, depth)
    np.testing.assert_array_equal(rec.confidence, conf)

    # read output -> torch via DLPack, values agree with numpy (zero-copy CPU)
    out = rec.depth
    back = torch.from_dlpack(out)
    assert np.array_equal(back.numpy(), np.asarray(out))


# --- repr pin ---------------------------------------------------------------
def test_repr():
    depth = np.zeros((4, 6), np.float32)
    conf = np.zeros((4, 6), np.float32)
    assert repr(_core.depth_map(depth)) == "<DepthMap 4x6 meters invalid=none>"
    assert (
        repr(_core.depth_map(depth, confidence=conf))
        == "<DepthMap 4x6 meters invalid=none +confidence>"
    )
    assert (
        repr(_core.depth_map(depth, unit="millimeters", invalid_policy="zero"))
        == "<DepthMap 4x6 millimeters invalid=zero>"
    )
    assert (
        repr(
            _core.depth_map(
                depth,
                unit="custom",
                scale_to_meters=0.0002,
                invalid_policy="nonfinite",
                confidence=conf,
            )
        )
        == "<DepthMap 4x6 custom invalid=nonfinite +confidence>"
    )


# --- big-endian input (endianness cannot silently byteswap-misread) ---------
def test_big_endian_input_rejected_or_byte_preserved():
    # '>f4' is exactly what np.frombuffer on big-endian float depth data
    # produces. The factory's DLPack dtype guard compares {code,bits,lanes},
    # which carries NO endianness, so protection against memcpy'ing byte-swapped
    # values relies entirely on numpy refusing the non-native export; if a future
    # numpy/nanobind accepted it, the values must be preserved (native), never
    # silently byteswap-misread. (test_image.py precedent.)
    depth = np.arange(3 * 4, dtype=np.float32).reshape(3, 4)
    be = depth.astype(">f4")
    try:
        rec = _core.depth_map(be)
    except (TypeError, ValueError):
        pass  # rejection is the pinned-safe outcome
    else:
        np.testing.assert_array_equal(rec.depth, depth)  # never a byteswap misread


# --- public re-export identity (the item's scaffold seam) -------------------
def test_reexport_identity():
    # The suite otherwise uses only _core, so a wrong-class typo in the io
    # re-export or the flat sceneio forward would pass everything. Pin that both
    # bind THIS record and that the deliberate cross-namespace name split is
    # intact: sceneio.data.DepthMap (the frozen validation contract) is a DISTINCT
    # class, not this raw-values record.
    import sceneio
    import sceneio.data
    import sceneio.io

    assert sceneio.io.DepthMap is _core.DepthMap
    assert sceneio.DepthMap is _core.DepthMap  # flat forward off sceneio
    assert sceneio.data.DepthMap is not _core.DepthMap  # distinct validation contract
    assert isinstance(_core.depth_map(np.zeros((1, 1), np.float32)), sceneio.io.DepthMap)
