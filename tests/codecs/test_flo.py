"""Parity suite for the canonical Middlebury ``.flo`` / ``FlowField`` codec."""

from __future__ import annotations

import struct

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


def _flow(values) -> object:
    return _core.flow_field(values)


def _encode(values) -> bytes:
    return _core.write_flo(_flow(values))


def _decode(data) -> np.ndarray:
    return np.asarray(_core.read_flo(data).vectors)


# --- oracle: a minimal, independent pure-Python .flo codec ------------------
def oracle_write_flo(flow: np.ndarray) -> bytes:
    flow = np.ascontiguousarray(flow, dtype=np.float32)
    h, w, c = flow.shape
    assert c == 2
    # magic float32 202021.25, then int32 width, int32 height (all little-endian)
    return struct.pack("<fii", 202021.25, w, h) + flow.astype("<f4").tobytes()


def oracle_read_flo(data: bytes) -> np.ndarray:
    magic, w, h = struct.unpack_from("<fii", data, 0)
    assert magic == 202021.25, "bad .flo magic"
    arr = np.frombuffer(data, dtype="<f4", count=h * w * 2, offset=12)
    return arr.reshape(h, w, 2).copy()  # top-to-bottom, no flip


@pytest.fixture
def samples() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(0)
    return {
        "random": rng.standard_normal((5, 7, 2)).astype(np.float32),
        # an asymmetric ramp: catches a row-flip / u<->v transpose bug
        "ramp": np.arange(3 * 4 * 2, dtype=np.float32).reshape(3, 4, 2),
        "single": rng.standard_normal((1, 1, 2)).astype(np.float32),
    }


# --- parity kind 3: round-trip identity (ours.read(ours.write)) -------------
def test_roundtrip_identity(samples):
    for arr in samples.values():
        got = np.asarray(_decode(_encode(arr)))
        np.testing.assert_array_equal(got, arr)
        assert got.dtype == np.float32 and got.shape == arr.shape
        assert got.tobytes() == arr.tobytes()  # bit-exact


# --- parity kind 1: cross-impl (oracle writes, our reader recovers) ---------
def test_parity_oracle_write_ours_read(samples):
    for arr in samples.values():
        got = np.asarray(_decode(oracle_write_flo(arr)))
        np.testing.assert_array_equal(got, arr)
        assert got.tobytes() == arr.tobytes()


# --- parity kind 2: writer spec-correctness (ours writes, oracle recovers) --
def test_parity_ours_write_oracle_read(samples):
    for arr in samples.values():
        got = oracle_read_flo(_encode(arr))
        np.testing.assert_array_equal(got, arr)
        assert got.tobytes() == arr.tobytes()


# --- convention pins (hand-derived external ground truth) -------------------
def test_pin_magic_value(samples):
    out = _encode(samples["random"])
    assert out[:4] == b"PIEH"
    # the 4 magic bytes are exactly float32 202021.25 (exactly representable)
    assert struct.unpack("<f", out[:4])[0] == 202021.25
    # a minimal valid 1x1 file (magic + w=1 + h=1 + one (u,v)=(0,0)) decodes
    data = b"PIEH" + struct.pack("<ii", 1, 1) + struct.pack("<ff", 0.0, 0.0)
    got = np.asarray(_decode(data))
    assert got.shape == (1, 1, 2)
    np.testing.assert_array_equal(got, np.zeros((1, 1, 2), np.float32))


def test_pin_uv_channel_order_and_row_order():
    # (W=2, H=1): two pixels, each u then v interleaved -> pin channel order.
    data = b"PIEH" + struct.pack("<ii", 2, 1) + struct.pack("<4f", 1.5, -0.5, -2.0, 3.0)
    flow = np.asarray(_decode(data))
    assert flow.shape == (1, 2, 2)
    assert tuple(flow[0, 0]) == (1.5, -0.5)  # u first, then v
    assert tuple(flow[0, 1]) == (-2.0, 3.0)
    # (W=1, H=2): the FIRST payload pixel is the top row -> rows top-to-bottom,
    # NO PFM-style flip (a self-round-trip would hide a symmetric flip; this is
    # hand-built reader bytes with an asymmetric top<->bottom).
    data2 = b"PIEH" + struct.pack("<ii", 1, 2) + struct.pack("<4f", 10.0, 11.0, 20.0, 21.0)
    flow2 = np.asarray(_decode(data2))
    assert flow2.shape == (2, 1, 2)
    assert tuple(flow2[0, 0]) == (10.0, 11.0)  # first payload pixel == top row
    assert tuple(flow2[1, 0]) == (20.0, 21.0)


def test_golden_writer_blob():
    # Byte-exact encode-drift guard (roadmap §1.4): shape (1,2,2) -> W=2, H=1.
    arr = np.arange(4, dtype=np.float32).reshape(1, 2, 2)
    expected = b"PIEH" + struct.pack("<ii", 2, 1) + struct.pack("<4f", 0, 1, 2, 3)
    assert _encode(arr) == expected


def test_output_is_canonical_flow_field(samples):
    out = _core.read_flo(_encode(samples["random"]))
    assert isinstance(out, _core.FlowField)
    assert out.vectors.dtype == np.float32
    assert out.vectors.shape == (5, 7, 2)
    assert (
        out.component_order,
        out.u_axis,
        out.v_axis,
        out.row_order,
        out.unit,
        out.invalid_policy,
    ) == (
        "uv",
        "right",
        "down",
        "top_to_bottom",
        "pixels",
        "component_abs_gt_1e9",
    )


def test_nan_and_unknown_flow_passthrough():
    # NaN/Inf and the |value|>1e9 unknown-flow sentinel are DATA: passed through
    # bit-exact, never masked (reader records, does not judge).
    arr = np.array(
        [[[np.nan, np.inf], [-np.inf, 1e10]], [[-1e10, 0.0], [1.0, -1.0]]],
        dtype=np.float32,
    )
    out = _encode(arr)
    got = np.asarray(_decode(out))
    # assert_array_equal treats NaN==NaN but ignores payload bits -> compare bytes.
    assert got.tobytes() == arr.tobytes()
    # an independent reader sees the specials at the same positions (no masking).
    oracle = oracle_read_flo(out)
    assert np.isnan(oracle[0, 0, 0])
    assert np.isposinf(oracle[0, 0, 1]) and np.isneginf(oracle[0, 1, 0])
    assert abs(oracle[0, 1, 1]) > 1e9 and abs(oracle[1, 0, 0]) > 1e9  # unknown-flow sentinels


def test_noncanonical_bit_patterns_passthrough():
    # Canonical specials (np.nan/+-inf/-0.0) alone cannot catch a payload-
    # canonicalizing or sNaN-quieting regression (e.g. a stray float->double->float
    # round-trip): for canonical inputs the buggy output is byte-identical. Stamp
    # NON-canonical 32-bit patterns so any bit-mangling on either path is caught.
    specials = (
        np.array(
            [
                0x7FC01234,  # qNaN with a non-zero payload
                0xFFC00000,  # negative qNaN (sign-set)
                0x7F800001,  # signaling NaN (top mantissa bit clear)
                0x00000001,  # smallest positive denormal
                0x80000000,  # -0.0
                0x7F7FFFFF,  # FLT_MAX (largest finite, exact bit pattern)
            ],
            np.uint32,
        )
        .view(np.float32)
        .reshape(1, 3, 2)
    )  # deterministic literals; (H,W,2)=(1,3,2)
    out = _encode(specials)
    # writer pinned: the payload after the 12-byte header is the input's bytes
    # verbatim (no canonicalization) — assert_array_equal would miss NaN payloads.
    assert out[12:] == specials.tobytes()
    # reader pinned: round-trip preserves every payload bit incl. the -0.0 sign
    # and the sNaN signaling bit (0.0 == -0.0 and NaN == NaN under value compares).
    got = np.asarray(_decode(out))
    assert got.tobytes() == specials.tobytes()


# --- malformed input raises (FormatError-mappable ValueError), never crashes -
@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"", "truncated header"),
        (b"PIEH", "truncated header"),  # magic only, no dims
        (b"PEIH" + struct.pack("<ii", 1, 1) + b"\x00" * 8, "bad magic"),  # scrambled magic
        (struct.pack("<f", 202021.24) + struct.pack("<ii", 1, 1) + b"\x00" * 8, "bad magic"),
        (b"PIEH" + struct.pack("<ii", -1, 1), "non-positive"),  # negative width
        (b"PIEH" + struct.pack("<ii", 0, 5), "non-positive"),  # zero width
        (b"PIEH" + struct.pack("<ii", 5, 0), "non-positive"),  # zero height (twin of zero width)
        (
            b"PIEH" + struct.pack("<ii", 1, -1),
            "non-positive",
        ),  # negative height (twin of neg width)
        # cap branch: dims in (1e9, INT32_MAX] must raise BEFORE any allocation
        # (kills a mutant that drops/mistypes the kDimCap check or caps one axis only)
        (b"PIEH" + struct.pack("<ii", 1000000001, 1), "out of range"),  # width just over 1e9 cap
        (
            b"PIEH" + struct.pack("<ii", 1, 2000000000),
            "out of range",
        ),  # height over cap, < INT32_MAX
        (b"PIEH" + struct.pack("<ii", 999999999, 999999999), "truncated"),  # huge: must not alloc
        (b"PIEH" + struct.pack("<ii", 2, 2) + b"\x00" * 31, "truncated"),  # payload one byte short
    ],
)
def test_malformed_raises(data, match):
    with pytest.raises(ValueError, match=match):
        _decode(data)


def test_trailing_bytes_ignored(samples):
    valid = _encode(samples["random"])
    a = np.asarray(_decode(valid))
    b = np.asarray(_decode(valid + b"junk"))
    np.testing.assert_array_equal(a, b)
    assert a.tobytes() == b.tobytes()


# --- construction/writer guards (refuse semantics .flo cannot hold) ---------
def test_writer_guards():
    for bad in (
        np.zeros((4, 5), np.float32),  # 2-D
        np.zeros((4, 5, 3), np.float32),  # 3 channels
        np.zeros((4, 5, 1), np.float32),  # 1 channel
    ):
        with pytest.raises(ValueError, match=r"vectors must be \(H,W,2\)"):
            _flow(bad)
    for shape in ((0, 5, 2), (5, 0, 2), (0, 0, 2)):
        with pytest.raises(ValueError, match=r"vectors must be \(H,W,2\)"):
            _flow(np.zeros(shape, np.float32))

    for keyword, value in (
        ("component_order", "vu"),
        ("u_axis", "left"),
        ("v_axis", "up"),
        ("row_order", "bottom_to_top"),
        ("unit", "unknown"),
        ("invalid_policy", "none"),
    ):
        field = _core.flow_field(
            np.zeros((2, 3, 2), np.float32),
            **{keyword: value},
        )
        with pytest.raises(ValueError, match=keyword):
            _core.write_flo(field)


# --- registry dispatch through the public API -------------------------------
def test_registry_dispatch(tmp_path):
    import sceneio

    arr = np.arange(3 * 4 * 2, dtype=np.float32).reshape(3, 4, 2)
    p = tmp_path / "flow.flo"
    field = _flow(arr)
    sceneio.write(field, p)  # dispatch by .flo extension
    assert sceneio.detect(p) == "flo"
    decoded = sceneio.read(p)
    assert isinstance(decoded, _core.FlowField)
    np.testing.assert_array_equal(decoded.vectors, arr)
    # extensionless file whose bytes start b"PIEH" sniffs to flo via magic.
    q = tmp_path / "noext"
    sceneio.write(field, q, format="flo")
    assert sceneio.detect(q) == "flo"


# --- numpy/torch interop (test_pfm.py:100 pattern) --------------------------
def test_torch_interop(samples):
    torch = pytest.importorskip("torch")
    arr = samples["random"]
    # FlowField construction accepts a contiguous torch tensor through DLPack.
    tensor = torch.from_numpy(arr).contiguous()
    np.testing.assert_array_equal(np.asarray(_decode(_encode(tensor))), arr)
    out = _core.read_flo(_encode(arr))
    back = torch.from_dlpack(out.vectors)
    assert np.array_equal(back.numpy(), np.asarray(out.vectors))


# --- optional secondary named oracle: OpenCV (Apache-2.0, test-only) --------
def test_cv2_cross_check(samples, tmp_path):
    cv2 = pytest.importorskip("cv2")
    arr = samples["random"]
    p = str(tmp_path / "ours.flo")
    with open(p, "wb") as fh:
        fh.write(_encode(arr))
    np.testing.assert_array_equal(cv2.readOpticalFlow(p), arr)  # cv2 reads our bytes
    q = str(tmp_path / "cv2.flo")
    cv2.writeOpticalFlow(q, arr)
    with open(q, "rb") as fh:
        got = np.asarray(_decode(fh.read()))  # we read cv2's bytes
    np.testing.assert_array_equal(got, arr)
