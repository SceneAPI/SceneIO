"""Phase 0 parity suite for the nanobind core's reference codec (PFM).

Establishes the pattern every later codec follows (io_implementation_plan.md
§6): cross-impl parity vs an oracle, round-trip identity, a convention pin
(PFM's bottom-to-top rows), and numpy/torch interop. The oracle here is a
tiny self-contained pure-Python PFM implementation.
"""

from __future__ import annotations

import io

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


# --- oracle: a minimal, independent pure-Python PFM codec ------------------
def oracle_write_pfm(img: np.ndarray) -> bytes:
    img = np.ascontiguousarray(img, dtype=np.float32)
    if img.ndim == 2:
        color, (h, w) = False, img.shape
    elif img.ndim == 3 and img.shape[2] == 3:
        color, (h, w, _) = True, img.shape
    else:
        raise ValueError("PFM: expected (H,W) or (H,W,3)")
    header = f"{'PF' if color else 'Pf'}\n{w} {h}\n-1.0\n".encode()
    raster = np.flipud(img).astype("<f4").tobytes()  # bottom-to-top, little-endian
    return header + raster


def oracle_read_pfm(data: bytes) -> np.ndarray:
    buf = io.BytesIO(data)
    color = buf.readline().strip() == b"PF"
    w, h = (int(t) for t in buf.readline().split())
    little = float(buf.readline()) < 0
    channels = 3 if color else 1
    arr = np.frombuffer(buf.read(w * h * channels * 4), dtype="<f4" if little else ">f4")
    arr = arr.astype(np.float32).reshape((h, w, 3) if color else (h, w))
    return np.flipud(arr).copy()  # PFM is bottom-to-top -> canonicalize top-to-bottom


@pytest.fixture
def samples() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(0)
    return {
        "gray": rng.standard_normal((5, 7)).astype(np.float32),
        "color": rng.standard_normal((4, 6, 3)).astype(np.float32),
        # a monotone ramp: asymmetric top<->bottom, so a row-flip bug is caught
        "ramp": np.arange(3 * 4, dtype=np.float32).reshape(3, 4),
    }


def test_roundtrip_identity(samples):
    for arr in samples.values():
        got = _core.read_pfm(_core.write_pfm(arr))
        np.testing.assert_array_equal(got, arr)


def test_parity_ours_write_oracle_read(samples):
    # our *writer* is spec-correct: an independent reader recovers the array.
    for arr in samples.values():
        np.testing.assert_array_equal(oracle_read_pfm(_core.write_pfm(arr)), arr)


def test_parity_oracle_write_ours_read(samples):
    # our *reader* matches an independent writer's bytes.
    for arr in samples.values():
        np.testing.assert_array_equal(_core.read_pfm(oracle_write_pfm(arr)), arr)


def test_convention_rows_top_to_bottom(samples):
    arr = samples["ramp"]  # arr[0,0] == 0 in the top-left
    got = _core.read_pfm(_core.write_pfm(arr))
    assert got[0, 0] == 0.0
    assert got[-1, -1] == arr[-1, -1]


def test_output_is_numpy_float32(samples):
    out = _core.read_pfm(_core.write_pfm(samples["gray"]))
    assert isinstance(out, np.ndarray)
    assert out.dtype == np.float32


def test_bad_magic_raises():
    with pytest.raises(ValueError, match="bad magic"):
        _core.read_pfm(b"XX\n2 2\n-1.0\n" + b"\x00" * 16)


def test_torch_interop(samples):
    torch = pytest.importorskip("torch")
    arr = samples["color"]
    # write path accepts a torch tensor (numpy OR torch on input)
    tensor = torch.from_numpy(arr).contiguous()
    np.testing.assert_array_equal(_core.read_pfm(_core.write_pfm(tensor)), arr)
    # read output -> torch via DLPack, values agree with numpy (zero-copy CPU)
    out = _core.read_pfm(_core.write_pfm(arr))
    back = torch.from_dlpack(out)
    assert np.array_equal(back.numpy(), out)
