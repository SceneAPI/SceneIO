"""Parity suite for the numpy .npy / .npz codec.

Follows the pattern established by tests/codecs/test_pfm.py (io_implementation_plan
§6): the three parity kinds against an oracle, round-trip identity, byte-exact
golden + convention pins, and numpy/torch interop. The oracle is numpy itself
(np.save / np.load / np.savez / np.savez_compressed over io.BytesIO) — already
the hard runtime dep, used strictly test-only.

Note: the TensorDict record (records/tensor_dict.hpp) covers the 12 numpy dtypes
bool/int8..64/uint8..64/float16/32/64. Complex (c8/c16) is *not* part of that
table, so — unlike the codec's original design sketch — it is neither stored nor
tested here; a complex descr is rejected by the reader as an unsupported dtype.
"""

from __future__ import annotations

import io
import struct
import zipfile

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


# --- the dtype x shape matrix ----------------------------------------------
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
SHAPES = [(), (0,), (7,), (3, 4), (2, 3, 4)]


def _rand(dtype, shape, rng) -> np.ndarray:
    dt = np.dtype(dtype)
    n = int(np.prod(shape, dtype=np.int64)) if shape else 1
    if dt.kind == "b":
        flat = rng.integers(0, 2, size=n, dtype=np.uint8).astype(bool)
    elif dt.kind in "iu":
        info = np.iinfo(dt)
        lo, hi = max(int(info.min), -1000), min(int(info.max), 1000)
        flat = rng.integers(lo, hi + 1, size=n).astype(dt)
    else:  # float16/32/64
        flat = rng.standard_normal(n).astype(dt)
    return flat.reshape(shape)


def _sample_td_arrays(rng) -> dict[str, np.ndarray]:
    return {
        "a": _rand("float32", (2, 3), rng),
        "b": _rand("uint8", (5,), rng),
        "c": _rand("bool", (4, 4), rng),
        "d": _rand("float16", (1,), rng),
        "e": _rand("int64", (), rng),  # 0-d member
    }


# --- oracle: numpy over in-memory buffers ----------------------------------
def _save_npy(arr: np.ndarray) -> bytes:
    bio = io.BytesIO()
    np.save(bio, arr, allow_pickle=False)
    return bio.getvalue()


def _load_npy(data: bytes) -> np.ndarray:
    return np.load(io.BytesIO(data), allow_pickle=False)


def _save_npz(compress: bool, **arrays: np.ndarray) -> bytes:
    bio = io.BytesIO()
    (np.savez_compressed if compress else np.savez)(bio, **arrays)
    return bio.getvalue()


def _make_npy(descr_repr: str, shape_repr: str, payload: bytes = b"") -> bytes:
    """Hand-build a .npy from raw header pieces (external ground truth / fuzz seeds)."""
    dict_str = f"{{'descr': {descr_repr}, 'fortran_order': False, 'shape': {shape_repr}, }}"
    hlen = len(dict_str) + 1
    padlen = 64 - ((10 + hlen) % 64)
    full = dict_str + " " * padlen + "\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(full)) + full.encode("latin1") + payload


def _assert_same(out: np.ndarray, ref: np.ndarray, ctx=None) -> None:
    assert out.dtype == ref.dtype, ctx
    assert out.shape == ref.shape, ctx
    assert out.tobytes() == ref.tobytes(), ctx  # bit-exact incl. float NaN payloads


# --- parity kind 1: oracle writes, we read ---------------------------------
def test_parity_oracle_write_ours_read():
    rng = np.random.default_rng(0)
    for dtype in DTYPES:
        for shape in SHAPES:
            arr = _rand(dtype, shape, rng)
            out = _core.read_npy(_save_npy(arr))
            _assert_same(out, arr, (dtype, shape))


# --- parity kind 2: we write, oracle reads ---------------------------------
def test_parity_ours_write_oracle_read():
    rng = np.random.default_rng(1)
    for dtype in DTYPES:
        for shape in SHAPES:
            arr = _rand(dtype, shape, rng)
            _assert_same(_load_npy(_core.write_npy(arr)), arr, (dtype, shape))


def test_parity_npz_ours_write_oracle_read():
    rng = np.random.default_rng(2)
    arrays = _sample_td_arrays(rng)
    td = _core.tensor_dict(arrays)
    for compress in (False, True):
        with np.load(io.BytesIO(_core.write_npz(td, compress))) as npz:
            assert list(npz.files) == list(arrays.keys())
            for k, v in arrays.items():
                _assert_same(npz[k], v, (k, compress))


# --- parity kind 3: round-trip identity ------------------------------------
def test_roundtrip_identity_npy():
    rng = np.random.default_rng(3)
    for dtype in DTYPES:
        for shape in SHAPES:
            arr = _rand(dtype, shape, rng)
            _assert_same(_core.read_npy(_core.write_npy(arr)), arr, (dtype, shape))


def test_roundtrip_identity_npz():
    rng = np.random.default_rng(4)
    arrays = _sample_td_arrays(rng)
    td = _core.tensor_dict(arrays)
    for compress in (False, True):
        back = _core.read_npz(_core.write_npz(td, compress))
        assert list(back.keys()) == list(arrays.keys())
        for k, v in arrays.items():
            _assert_same(np.asarray(back[k]), v, (k, compress))


def test_parity_npz_oracle_write_ours_read():
    rng = np.random.default_rng(5)
    arrays = _sample_td_arrays(rng)
    for compress in (False, True):
        td = _core.read_npz(_save_npz(compress, **arrays))
        assert list(td.keys()) == list(arrays.keys())  # savez preserves kwargs order
        for k, v in arrays.items():
            _assert_same(np.asarray(td[k]), v, (k, compress))


# --- byte-exact golden ------------------------------------------------------
def test_write_npy_golden_header():
    # Hand-derived external ground truth for np.zeros((2,3), '<f4'): a 128-byte
    # v1.0 header (dict is 59 bytes -> padlen 58 -> stored length 118 = 0x76)
    # followed by 24 zero payload bytes.
    expected = (
        b"\x93NUMPY\x01\x00\x76\x00"
        b"{'descr': '<f4', 'fortran_order': False, 'shape': (2, 3), }" + b" " * 58 + b"\n"
    )
    out = _core.write_npy(np.zeros((2, 3), dtype="<f4"))
    assert out[:6] == b"\x93NUMPY"
    assert out == expected + b"\x00" * 24


@pytest.mark.skipif(
    getattr(np.lib.format, "ARRAY_ALIGN", 0) != 64,
    reason="byte-exact vs np.save assumes numpy ARRAY_ALIGN == 64 (numpy >= 1.22)",
)
def test_write_npy_matches_numpy_bytes():
    rng = np.random.default_rng(6)
    for dtype in DTYPES:
        for shape in SHAPES:
            arr = _rand(dtype, shape, rng)
            assert _core.write_npy(arr) == _save_npy(arr), (dtype, shape)


# --- convention pins --------------------------------------------------------
def test_convention_read_is_c_contiguous():
    arr = _rand("float64", (3, 4), np.random.default_rng(7))
    assert _core.read_npy(_save_npy(arr)).flags["C_CONTIGUOUS"]


def test_convention_write_header_fields():
    b = _core.write_npy(_rand("float32", (2, 2), np.random.default_rng(8)))
    assert b[6:8] == b"\x01\x00"  # format version 1.0
    assert b"'fortran_order': False" in b  # writer never emits Fortran order


def test_convention_big_endian_read():
    arr = _rand("float32", (3, 5), np.random.default_rng(9))
    data = _save_npy(arr.astype(">f4"))  # numpy writes a '>f4' descr
    out = _core.read_npy(data)
    assert out.dtype == np.dtype(np.float32)  # canonicalized to native, not '>f4'
    assert out.dtype.byteorder in ("=", "<")
    assert np.array_equal(out, np.load(io.BytesIO(data)))
    assert out.tobytes() == arr.tobytes()  # bit-identical native little-endian


def test_convention_hand_big_endian_fixture():
    # External ground truth: a hand-built '>f4' file must decode to the exact floats.
    vals = np.array([1.0, 2.0, -3.5], dtype=np.float32)
    data = _make_npy("'>f4'", "(3,)", vals.astype(">f4").tobytes())
    out = _core.read_npy(data)
    assert out.dtype == np.dtype(np.float32)
    assert np.array_equal(out, vals)
    assert out.tobytes() == vals.tobytes()


def test_convention_fortran_order_read():
    arr = np.asfortranarray(_rand("float64", (3, 4), np.random.default_rng(10)))
    data = _save_npy(arr)
    assert b"'fortran_order': True" in data  # numpy marked the F-contiguous array
    out = _core.read_npy(data)
    assert out.flags["C_CONTIGUOUS"]  # we de-permute to C order
    assert np.array_equal(out, np.load(io.BytesIO(data)))


def test_version_tolerance():
    arr = _rand("float32", (3, 4), np.random.default_rng(11))
    for version in ((2, 0), (3, 0)):
        bio = io.BytesIO()
        np.lib.format.write_array(bio, arr, version=version)
        _assert_same(_core.read_npy(bio.getvalue()), arr, version)


# --- npz specifics ----------------------------------------------------------
def test_npz_insertion_order_preserved():
    rng = np.random.default_rng(12)
    arrays = {
        "z": _rand("float32", (2,), rng),
        "a": _rand("uint8", (3,), rng),
        "m": _rand("int32", (1,), rng),
    }
    td = _core.read_npz(_core.write_npz(_core.tensor_dict(arrays)))
    assert list(td.keys()) == ["z", "a", "m"]  # not sorted


def test_npz_empty():
    td = _core.read_npz(_save_npz(False))  # np.savez() with no arrays
    assert len(td) == 0
    assert list(td.keys()) == []


def test_npz_zero_d_member():
    back = _core.read_npz(_core.write_npz(_core.tensor_dict({"s": np.asarray(3.5)})))
    got = np.asarray(back["s"])
    assert got.shape == () and got.dtype == np.dtype(np.float64)
    assert float(got) == 3.5


def test_tensor_dict_factory_roundtrip():
    rng = np.random.default_rng(13)
    arrays = _sample_td_arrays(rng)
    td = _core.tensor_dict(arrays)
    assert list(td.keys()) == list(arrays.keys())
    for k, v in arrays.items():
        _assert_same(np.asarray(td[k]), v, k)


def test_npz_duplicate_member_raises():
    rng = np.random.default_rng(14)
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:  # numpy keeps the last dupe; we are strict
        zf.writestr("x.npy", _save_npy(_rand("float32", (2,), rng)))
        zf.writestr("x.npy", _save_npy(_rand("float32", (3,), rng)))
    with pytest.raises(ValueError):
        _core.read_npz(bio.getvalue())


# --- error paths (raise, never crash) --------------------------------------
def test_error_bad_magic():
    with pytest.raises(ValueError, match="magic"):
        _core.read_npy(b"XXXXXXXXXXXXXXXX")


def test_error_truncated_payload():
    data = _save_npy(_rand("float64", (100,), np.random.default_rng(15)))
    with pytest.raises(ValueError):
        _core.read_npy(data[:-100])  # 100 payload bytes short


def test_error_header_len_past_eof():
    with pytest.raises(ValueError):
        _core.read_npy(b"\x93NUMPY\x01\x00\xff\xff")  # claims a 65535-byte header, has none


@pytest.mark.parametrize(
    ("descr_repr", "shape_repr", "payload"),
    [
        ("'<U5'", "(1,)", b"\x00" * 20),  # unicode string
        ("'|O8'", "(1,)", b"\x00" * 8),  # object
        ("'<c8'", "(1,)", b"\x00" * 8),  # complex64 (not in the record's dtype table)
        ("[('a', '<f4')]", "(1,)", b"\x00" * 4),  # structured
    ],
)
def test_error_unsupported_dtype(descr_repr, shape_repr, payload):
    with pytest.raises(ValueError):
        _core.read_npy(_make_npy(descr_repr, shape_repr, payload))


def test_error_npz_not_a_zip():
    with pytest.raises(ValueError):
        _core.read_npz(b"this is definitely not a zip archive")


def test_error_npz_corrupt_tail():
    good = _save_npz(False, x=_rand("float32", (4,), np.random.default_rng(16)))
    # 1) truncated so the end-of-central-directory record is gone
    with pytest.raises(ValueError):
        _core.read_npz(good[: len(good) // 2])
    # 2) byte-mutated tail (EOCD + central directory) raises cleanly, never crashes
    bad = bytearray(good)
    for i in range(1, min(40, len(bad)) + 1):
        bad[-i] ^= 0xA5
    with pytest.raises(ValueError):
        _core.read_npz(bytes(bad))


@pytest.mark.parametrize(
    "bad",
    [
        np.array([1, 2, 3], dtype=object),  # no buffer -> nanobind cast TypeError
        np.array([1 + 2j, 3 + 4j], dtype=np.complex128),  # complex -> our ValueError
    ],
)
def test_error_write_unrepresentable(bad):
    with pytest.raises((TypeError, ValueError)):
        _core.write_npy(bad)


# --- cross-framework (torch) ------------------------------------------------
def test_torch_interop():
    torch = pytest.importorskip("torch")
    arr = _rand("float32", (3, 4), np.random.default_rng(17))
    # read output -> torch via DLPack, values agree (zero-copy CPU)
    out = _core.read_npy(_save_npy(arr))
    assert np.array_equal(torch.from_dlpack(out).numpy(), out)
    # write path accepts a torch tensor
    tensor = torch.from_numpy(arr).contiguous()
    assert np.array_equal(np.load(io.BytesIO(_core.write_npy(tensor))), arr)
