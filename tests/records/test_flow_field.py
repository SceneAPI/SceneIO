"""Record contract for the compiled typed optical-flow representation."""

from __future__ import annotations

import gc

import numpy as np
import pytest

from sceneio import _core


def _special_flow(height: int = 3, width: int = 4) -> np.ndarray:
    values = np.arange(height * width * 2, dtype=np.float32).reshape(
        height, width, 2
    )
    bits = values.reshape(-1).view(np.uint32)
    bits[:8] = np.array(
        [
            0x00000000,  # +0
            0x80000000,  # -0
            0x7F800000,  # +inf
            0xFF800000,  # -inf
            0x7FC00ABC,  # qNaN with payload
            0xFFC00001,  # negative qNaN
            0x00000001,  # smallest positive subnormal
            0x501502F9,  # Middlebury 1e10 sentinel
        ],
        dtype=np.uint32,
    )
    return values


def test_factory_preserves_values_and_default_conventions():
    source = _special_flow()
    flow = _core.flow_field(source)

    assert (flow.height, flow.width) == source.shape[:2]
    assert flow.vectors.shape == source.shape
    assert flow.vectors.dtype == np.float32
    assert flow.vectors.tobytes() == source.tobytes()
    assert flow.component_order == "uv"
    assert flow.u_axis == "right"
    assert flow.v_axis == "down"
    assert flow.row_order == "top_to_bottom"
    assert flow.unit == "pixels"
    assert flow.invalid_policy == "component_abs_gt_1e9"


def test_factory_owns_copy_and_accepts_noncontiguous_input():
    source = np.arange(5 * 12 * 2, dtype=np.float32).reshape(5, 12, 2)
    noncontiguous = source[:, ::2]
    expected = noncontiguous.copy()
    flow = _core.flow_field(noncontiguous)

    source.fill(-99)
    np.testing.assert_array_equal(flow.vectors, expected)


@pytest.mark.parametrize(
    ("keyword", "values"),
    [
        ("component_order", ("uv", "vu")),
        ("u_axis", ("right", "left")),
        ("v_axis", ("down", "up")),
        ("row_order", ("top_to_bottom", "bottom_to_top")),
        ("unit", ("pixels", "unknown")),
        (
            "invalid_policy",
            ("none", "component_abs_gt_1e9", "nonfinite"),
        ),
    ],
)
def test_metadata_closed_vocabularies(keyword, values):
    vectors = np.zeros((2, 3, 2), np.float32)
    for value in values:
        flow = _core.flow_field(vectors, **{keyword: value})
        assert getattr(flow, keyword) == value

    with pytest.raises(ValueError, match=keyword):
        _core.flow_field(vectors, **{keyword: "invalid-token"})


def test_values_are_never_scrubbed_by_invalid_policy():
    source = _special_flow()
    for policy in ("none", "component_abs_gt_1e9", "nonfinite"):
        assert (
            _core.flow_field(source, invalid_policy=policy).vectors.tobytes()
            == source.tobytes()
        )


def test_shape_dtype_and_empty_guards():
    for bad in (
        np.zeros((4, 5), np.float32),
        np.zeros((4, 5, 1), np.float32),
        np.zeros((4, 5, 3), np.float32),
        np.zeros((0, 5, 2), np.float32),
        np.zeros((4, 0, 2), np.float32),
    ):
        with pytest.raises(ValueError, match=r"H,W,2"):
            _core.flow_field(bad)

    for dtype in (
        np.float64,
        np.float16,
        np.int32,
        np.uint16,
        np.uint8,
    ):
        with pytest.raises(ValueError, match="must be float32"):
            _core.flow_field(np.zeros((2, 3, 2), dtype=dtype))


def test_views_alias_record_and_keep_it_alive():
    flow = _core.flow_field(_special_flow(16, 16))
    first = flow.vectors
    second = flow.vectors
    assert first.ctypes.data == second.ctypes.data
    first[1, 2, 0] = np.float32(123.5)
    assert second[1, 2, 0] == np.float32(123.5)

    source = np.arange(512 * 1024 * 2, dtype=np.float32).reshape(512, 1024, 2)
    expected = source.copy()
    view = _core.flow_field(source).vectors
    del source
    gc.collect()
    gc.collect()
    churn = [np.full(1 << 20, 0xAB, np.uint8) for _ in range(4)]
    np.testing.assert_array_equal(view, expected)
    assert churn[0][0] == 0xAB

    derived = _core.flow_field(expected).vectors[::2, 1::3]
    expected_derived = expected[::2, 1::3].copy()
    gc.collect()
    gc.collect()
    np.testing.assert_array_equal(derived, expected_derived)


def test_semantic_metadata_is_read_only():
    flow = _core.flow_field(np.zeros((2, 3, 2), np.float32))
    for name in (
        "component_order",
        "u_axis",
        "v_axis",
        "row_order",
        "unit",
        "invalid_policy",
    ):
        with pytest.raises(AttributeError):
            setattr(flow, name, "replacement")


def test_torch_dlpack_aliases_record_when_available():
    torch = pytest.importorskip("torch")
    expected = np.arange(512 * 1024 * 2, dtype=np.float32).reshape(512, 1024, 2)
    tensor = torch.from_dlpack(_core.flow_field(expected).vectors)
    gc.collect()
    gc.collect()
    churn = [np.full(1 << 20, 0xCD, np.uint8) for _ in range(4)]
    assert np.array_equal(tensor.numpy(), expected)
    tensor[0, 0, 0] = 17.0
    assert tensor[0, 0, 0].item() == 17.0
    assert churn[0][0] == 0xCD


def test_big_endian_input_is_rejected_or_value_preserved():
    expected = np.arange(3 * 4 * 2, dtype=np.float32).reshape(3, 4, 2)
    big_endian = expected.astype(">f4")
    try:
        flow = _core.flow_field(big_endian)
    except (TypeError, ValueError):
        return
    np.testing.assert_array_equal(flow.vectors, expected)


def test_repr_and_public_reexports():
    flow = _core.flow_field(np.zeros((4, 6, 2), np.float32))
    assert (
        repr(flow)
        == "<FlowField 4x6 uv pixels u+right v+down "
        "invalid=component_abs_gt_1e9>"
    )

    import sceneio
    import sceneio.io

    assert sceneio.FlowField is _core.FlowField
    assert sceneio.io.FlowField is _core.FlowField
    assert "FlowField" in sceneio.__all__
    assert "FlowField" in sceneio.io.__all__
