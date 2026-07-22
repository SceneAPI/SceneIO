"""Record-level suite for the TensorDict container (dict-like, insertion
ordered, dtype-erased named tensors + ordered str->str attrs).

Mirrors tests/codecs/test_pfm.py: numpy is the self-contained oracle. Because a
TensorDict only moves bytes (dtype is metadata riding beside the buffer), the
contract is *bit-exact* per key — we compare ``.tobytes()`` (not allclose) so
float16/32/64 NaN and denormal payloads are pinned rather than spuriously
failing NaN != NaN.

This is a *record*, not a codec: there are no read_*/write_* here. The three
codec-tier parity kinds ride on this record once the .npy/.npz codec lands
(tests/codecs/test_npy_npz.py); this file pins the record contract those codecs
build on, including the dtype round-trip that guards the buffer-protocol export
path against a nanobind regression.

TensorDict::add's overflow-checked sizing (the "single anti-OOB seam") is
defense-in-depth the Python factory cannot reach — factory shapes come from real
allocated arrays, never a hostile length — so it is exercised only through the
codec paths with crafted huge-shape headers (tests/codecs/test_npy_npz.py),
mirroring the honest deferral note on the duplicate-name guard below.
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


# The 12 dtypes the record round-trips, as (numpy name) -> tested here x-wise.
DTYPES = [
    "bool",
    "int8",
    "int16",
    "int32",
    "int64",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "float16",
    "float32",
    "float64",
]


# Hand-picked special float bit patterns per dtype — sNaN-with-payload,
# qNaN-with-payload, -inf, -0.0, smallest denormal — stored as their raw integer
# encodings. make_arr stamps these into the leading elements of every float array
# so payload preservation is pinned *bit-for-bit every run* (compared via
# .tobytes()), not left to whether a random draw happens to contain a NaN.
_FLOAT_SPECIAL_BITS = {
    np.dtype("float16"): np.array([0x7C01, 0x7E01, 0xFC00, 0x8000, 0x0001], np.uint16),
    np.dtype("float32"): np.array(
        [0x7F800001, 0x7FC00001, 0xFF800000, 0x80000000, 0x00000001], np.uint32
    ),
    np.dtype("float64"): np.array(
        [
            0x7FF0000000000001,
            0x7FF8000000000001,
            0xFFF0000000000000,
            0x8000000000000000,
            0x0000000000000001,
        ],
        np.uint64,
    ),
}


def make_arr(rng: np.random.Generator, dt, shape) -> np.ndarray:
    """A shape-``shape`` array of dtype ``dt`` filled with random *bit patterns*
    (so floats exercise NaN/inf/denormals and ints span their whole range), with
    hand-picked special float payloads stamped into the leading elements so
    NaN/denormal/-0.0 preservation is pinned deterministically, not by chance."""
    dt = np.dtype(dt)
    if dt == np.dtype(bool):
        return rng.integers(0, 2, size=shape).astype(np.bool_)
    n = int(np.prod(shape)) * dt.itemsize
    raw = rng.integers(0, 256, size=n, dtype=np.uint8).tobytes()
    arr = np.frombuffer(raw, dtype=dt).reshape(shape).copy()
    if dt in _FLOAT_SPECIAL_BITS and arr.size:
        specials = _FLOAT_SPECIAL_BITS[dt].view(dt)  # reinterpret bits as float
        k = min(arr.size, specials.size)
        arr.flat[:k] = specials[:k]  # bit-exact same-dtype assignment
    return arr


# --- dtype round-trip (the buffer-protocol export contract, x12) -----------
@pytest.mark.parametrize("dt", DTYPES)
def test_dtype_roundtrip(dt):
    # deterministic seed (str hash is PYTHONHASHSEED-salted): failures replay
    # bit-for-bit, and the stamped special payloads are the same every run
    rng = np.random.default_rng(DTYPES.index(dt))
    arr = make_arr(rng, dt, (3, 4))
    td = _core.tensor_dict({"x": arr})
    out = np.asarray(td["x"])
    assert out.dtype == arr.dtype
    assert out.shape == arr.shape
    # the parametrized name is exactly the table's numpy-name column, so this
    # pins all 12 rows of kDTypes.name (not just float32)
    assert td.dtype_of("x") == dt
    # bit-exact: catches endianness/format mislabels AND NaN-payload loss
    assert out.tobytes() == arr.tobytes()


def test_heterogeneous_roundtrip_identity():
    rng = np.random.default_rng(1)
    src = {
        "a": make_arr(rng, "float32", (2, 3)),
        "b": make_arr(rng, "uint8", (5,)),
        "c": make_arr(rng, "bool", (4, 4)),
        "d": make_arr(rng, "float16", (1,)),
    }
    td = _core.tensor_dict(src)
    assert len(td) == 4
    for k, arr in src.items():
        out = np.asarray(td[k])
        assert out.dtype == arr.dtype and out.shape == arr.shape
        assert out.tobytes() == arr.tobytes()


# --- convention pins -------------------------------------------------------
def test_insertion_order_preserved():
    rng = np.random.default_rng(2)
    td = _core.tensor_dict(
        {
            "z": make_arr(rng, "float32", (2,)),
            "a": make_arr(rng, "float32", (2,)),
            "m": make_arr(rng, "float32", (2,)),
        }
    )
    assert td.keys() == ["z", "a", "m"]  # NOT sorted; future npz member order depends on it


def test_canonical_form_conventions():
    rng = np.random.default_rng(3)
    td = _core.tensor_dict({"x": make_arr(rng, "float32", (3, 4))})
    assert td.byte_order == "little"
    assert td.order == "C"


def test_big_endian_input_rejected_or_value_preserved():
    # The canonical form is native little-endian. A big-endian input must be
    # either rejected (today nanobind's buffer import raises TypeError) or
    # value-preserved as native LE — never silently stored byte-swapped and
    # mislabeled native. Pins the invariant against a future nanobind that
    # accepts '>'-format buffers.
    arr = np.arange(4, dtype=">u2")
    try:
        td = _core.tensor_dict({"x": arr})
    except TypeError:
        pass  # rejection is the pinned-safe outcome
    else:
        np.testing.assert_array_equal(np.asarray(td["x"]), arr.astype("<u2"))


def test_noncontiguous_input_is_accepted_via_copy():
    rng = np.random.default_rng(4)
    base = rng.standard_normal((4, 6)).astype(np.float32)
    sl = base[:, ::2]  # a non-C-contiguous (4,3) view
    assert not sl.flags["C_CONTIGUOUS"]
    td = _core.tensor_dict({"s": sl})
    out = np.asarray(td["s"])
    assert out.shape == (4, 3)
    np.testing.assert_array_equal(out, np.ascontiguousarray(sl))


# --- attrs -----------------------------------------------------------------
def test_attrs_roundtrip():
    rng = np.random.default_rng(5)
    arr = make_arr(rng, "float32", (2, 2))
    td = _core.tensor_dict({"x": arr}, attrs={"unit": "m", "frame": "opencv"})
    assert td.attrs == {"unit": "m", "frame": "opencv"}


def test_attrs_order_preserved():
    # ordered str->str attrs (npz/safetensors want byte-deterministic round-trips):
    # deliberately non-sorted keys, pinned with order-sensitive .items() so an
    # unordered_map-backed reimplementation would fail here.
    rng = np.random.default_rng(14)
    arr = make_arr(rng, "float32", (2, 2))
    td = _core.tensor_dict({"x": arr}, attrs={"z": "1", "a": "2", "m": "3"})
    assert list(td.attrs.items()) == [("z", "1"), ("a", "2"), ("m", "3")]


def test_attrs_default_empty():
    rng = np.random.default_rng(6)
    td = _core.tensor_dict({"x": make_arr(rng, "float32", (2, 2))})
    assert td.attrs == {}


# --- dict protocol ---------------------------------------------------------
def test_dict_protocol():
    rng = np.random.default_rng(7)
    td = _core.tensor_dict({"x": make_arr(rng, "float32", (3, 4))})
    assert "x" in td
    assert "nope" not in td
    with pytest.raises(KeyError):
        _ = td["nope"]
    with pytest.raises(KeyError):
        td.dtype_of("nope")
    assert td.dtype_of("x") == "float32"
    assert tuple(td.shape_of("x")) == (3, 4)
    assert list(iter(td)) == td.keys()


def test_items():
    # items() has its own conversion path (vector<pair<str, ndarray>>) where each
    # view carries its own baked-in owner. Pin values AND the per-element
    # keep-alive: the held pairs must survive the record being dropped.
    rng = np.random.default_rng(12)
    src = {
        "a": make_arr(rng, "float32", (2, 3)),
        "b": make_arr(rng, "uint8", (5,)),
        "c": make_arr(rng, "float16", (4,)),
    }
    td = _core.tensor_dict(src)
    pairs = td.items()
    assert [k for k, _ in pairs] == td.keys()
    for k, v in pairs:
        assert np.asarray(v).tobytes() == src[k].tobytes()
    del td
    gc.collect()
    # each element's baked-in owner keeps the record alive individually
    for k, v in pairs:
        assert np.asarray(v).tobytes() == src[k].tobytes()


def test_repr_smoke():
    rng = np.random.default_rng(8)
    td = _core.tensor_dict(
        {"a": make_arr(rng, "float32", (2, 3)), "b": make_arr(rng, "uint8", (4,))}
    )
    r = repr(td)
    assert "TensorDict" in r and "n=2" in r


# --- zero-copy + lifetime + aliasing --------------------------------------
def test_zero_copy_lifetime_and_aliasing():
    rng = np.random.default_rng(9)
    arr = make_arr(rng, "float32", (3, 4))
    td = _core.tensor_dict({"x": arr})

    # zero-copy: bind BOTH views before comparing pointers. Comparing
    # td["x"].ctypes.data to td["x"].ctypes.data is vacuous — the first temporary
    # is freed before the second exists, so a copying getter passes via allocator
    # address reuse. Holding both forces distinct live buffers if a copy is made.
    a = td["x"]
    b = td["x"]
    assert a.ctypes.data == b.ctypes.data

    # owner keep-alive checked against the pristine source before we mutate
    assert a.tobytes() == arr.tobytes()

    # record-storage aliasing (not a cached lone copy): mutate through one view
    # and observe it in a FRESH fetch off the still-live record
    a[0, 0] = np.float32(12345.0)
    assert np.asarray(td["x"])[0, 0] == np.float32(12345.0)

    del td
    gc.collect()
    # owner keep-alive + aliasing survive the record being dropped: the second
    # view sees the mutation, and a still holds the whole buffer bit-exactly
    assert b[0, 0] == np.float32(12345.0)
    expect = arr.copy()
    expect[0, 0] = np.float32(12345.0)
    assert a.tobytes() == expect.tobytes()


# --- torch interop (optional) ---------------------------------------------
def test_torch_interop():
    torch = pytest.importorskip("torch")
    rng = np.random.default_rng(10)
    for dt in ("float32", "bool"):
        arr = make_arr(rng, dt, (3, 4))
        tensor = torch.from_numpy(arr).contiguous()  # factory accepts torch input
        td = _core.tensor_dict({"x": tensor})
        out = np.asarray(td["x"])
        # bit-exact on both legs (arr carries stamped NaN/denormal payloads):
        # array_equal/assert_array_equal are blind to NaN payload bits
        assert out.tobytes() == arr.tobytes()
        back = torch.from_dlpack(td["x"])  # our view -> torch via DLPack
        assert back.numpy().tobytes() == out.tobytes()


# --- error paths (raise, never crash) --------------------------------------
def test_unsupported_dtype_raises():
    # complex imports fine as an array, then the dtype table rejects it -> ValueError
    with pytest.raises(ValueError, match="unsupported dtype"):
        _core.tensor_dict({"x": np.zeros((2, 2), np.complex64)})


@pytest.mark.parametrize(
    "value",
    [
        np.array(["abcd", "efgh"], dtype="<U4"),  # unicode string array
        np.array([object(), object()], dtype=object),  # object array
    ],
)
def test_unrepresentable_array_raises(value):
    # str/object arrays are not importable as numeric buffers; must raise
    # cleanly (dtype-rejected ValueError or import-rejected TypeError), not crash.
    with pytest.raises((TypeError, ValueError)):
        _core.tensor_dict({"x": value})


def test_non_array_value_raises_type_error():
    with pytest.raises(TypeError):
        _core.tensor_dict({"x": "hello"})


# --- edge shapes -----------------------------------------------------------
def test_scalar_0d_roundtrip():
    td = _core.tensor_dict({"s": np.asarray(3.5)})  # 0-d float64
    out = np.asarray(td["s"])
    assert out.shape == ()
    assert out.dtype == np.float64
    assert out.tobytes() == np.asarray(3.5).tobytes()


def test_empty_array_roundtrip_no_null_crash():
    empty = np.zeros((0, 3), np.float32)
    td = _core.tensor_dict({"e": empty})
    out = np.asarray(td["e"])
    assert out.shape == (0, 3)
    assert out.dtype == np.float32
    assert tuple(td.shape_of("e")) == (0, 3)


def test_empty_dict():
    td = _core.tensor_dict({})
    assert len(td) == 0
    assert td.keys() == []
    assert list(iter(td)) == []


# --- duplicate-name guard --------------------------------------------------
def test_duplicate_name_guard_is_internal():
    """TensorDict::add() raises std::invalid_argument on a repeated name (the
    anti-overwrite guard a hostile npz with two ``x.npy`` members must hit).

    A Python dict cannot express a duplicate key, so the factory can never
    trigger it; this guard is exercised end-to-end by the .npz reader in
    tests/codecs/test_npy_npz.py once that codec lands. Recorded here so the
    contract is discoverable from the record's own suite.
    """
    # Sanity: distinct keys build the expected two-entry record.
    rng = np.random.default_rng(11)
    td = _core.tensor_dict({"x": make_arr(rng, "uint8", (2,)), "y": make_arr(rng, "uint8", (2,))})
    assert len(td) == 2 and td.keys() == ["x", "y"]
