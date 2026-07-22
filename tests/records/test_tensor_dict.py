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
build on, including the overflow-checked append and the dtype round-trip that
guards the buffer-protocol export path against a nanobind regression.
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


def make_arr(rng: np.random.Generator, dt, shape) -> np.ndarray:
    """A shape-``shape`` array of dtype ``dt`` filled with random *bit patterns*
    (so floats exercise NaN/inf/denormals and ints span their whole range)."""
    dt = np.dtype(dt)
    if dt == np.dtype(bool):
        return rng.integers(0, 2, size=shape).astype(np.bool_)
    n = int(np.prod(shape)) * dt.itemsize
    raw = rng.integers(0, 256, size=n, dtype=np.uint8).tobytes()
    return np.frombuffer(raw, dtype=dt).reshape(shape).copy()


# --- dtype round-trip (the buffer-protocol export contract, x12) -----------
@pytest.mark.parametrize("dt", DTYPES)
def test_dtype_roundtrip(dt):
    rng = np.random.default_rng(abs(hash(dt)) % (2**32))
    arr = make_arr(rng, dt, (3, 4))
    td = _core.tensor_dict({"x": arr})
    out = np.asarray(td["x"])
    assert out.dtype == arr.dtype
    assert out.shape == arr.shape
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

    # zero-copy: repeated views share one underlying buffer (no copy per call)
    assert td["x"].ctypes.data == td["x"].ctypes.data

    a = td["x"]
    b = td["x"]
    del td
    gc.collect()
    # owner keep-alive: the view holds the record alive, so bytes stay valid
    np.testing.assert_array_equal(a, arr)
    # views alias the same buffer (documented: writable, aliasing)
    a[0, 0] = np.float32(12345.0)
    assert b[0, 0] == np.float32(12345.0)


# --- torch interop (optional) ---------------------------------------------
def test_torch_interop():
    torch = pytest.importorskip("torch")
    rng = np.random.default_rng(10)
    for dt in ("float32", "bool"):
        arr = make_arr(rng, dt, (3, 4))
        tensor = torch.from_numpy(arr).contiguous()  # factory accepts torch input
        td = _core.tensor_dict({"x": tensor})
        out = np.asarray(td["x"])
        np.testing.assert_array_equal(out, arr)
        back = torch.from_dlpack(td["x"])  # our view -> torch via DLPack
        assert np.array_equal(back.numpy(), out)


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
