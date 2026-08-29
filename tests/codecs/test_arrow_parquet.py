from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

import sceneio
from sceneio import _core


def _fixture(rows: int = 31):
    arrays = {
        "image_id": np.arange(rows, dtype=np.uint32),
        "xy": (
            np.arange(rows * 2, dtype=np.float32).reshape(rows, 2) / 7
        ),
        "descriptor": (
            np.arange(rows * 8, dtype=np.float32).reshape(rows, 8) / 13
        ),
        "inlier": np.arange(rows, dtype=np.uint8) % 3 == 0,
    }
    return _core.tensor_dict(
        arrays,
        attrs={"coordinate_order": "xy", "role": "features"},
    ), arrays


def _assert_tensor_dict(actual, arrays):
    assert tuple(actual.keys()) == tuple(arrays)
    for name, expected in arrays.items():
        np.testing.assert_array_equal(actual[name], expected)


@pytest.mark.parametrize(
    ("format_id", "extension"),
    [("parquet", ".parquet"), ("arrow_ipc", ".arrow")],
)
def test_sceneio_columnar_writes_are_exact_for_direct_arrow_oracle(
    tmp_path, format_id, extension
):
    tensors, arrays = _fixture()
    path = tmp_path / f"sceneio{extension}"

    sceneio.write(tensors, path, format=format_id)

    assert sceneio.detect(path) == format_id
    if format_id == "parquet":
        table = pq.read_table(path)
    else:
        with pa.memory_map(str(path), "r") as source:
            table = ipc.open_file(source).read_all()
    assert table.column_names == list(arrays)
    for name, expected in arrays.items():
        column = table[name].combine_chunks()
        if expected.ndim == 2:
            actual = column.values.to_numpy().reshape(expected.shape)
        else:
            actual = column.to_numpy(zero_copy_only=False)
        np.testing.assert_array_equal(actual, expected)
    metadata = table.schema.metadata
    assert metadata[b"sceneio.schema"] == b"sceneio.numeric_table.v1"
    assert metadata[b"sceneio.attr.role"] == b"features"


@pytest.mark.parametrize(
    ("format_id", "extension"),
    [("parquet", ".parquet"), ("arrow_ipc", ".arrow")],
)
def test_sceneio_reads_direct_arrow_oracle_tables_exactly(
    tmp_path, format_id, extension
):
    _tensors, arrays = _fixture()
    table = pa.table(
        {
            "image_id": pa.array(arrays["image_id"]),
            "xy": pa.FixedSizeListArray.from_arrays(
                pa.array(arrays["xy"].reshape(-1)),
                2,
            ),
            "descriptor": pa.FixedSizeListArray.from_arrays(
                pa.array(arrays["descriptor"].reshape(-1)),
                8,
            ),
            "inlier": pa.array(arrays["inlier"]),
        }
    ).replace_schema_metadata(
        {
            b"sceneio.schema": b"sceneio.numeric_table.v1",
            b"sceneio.attr.coordinate_order": b"xy",
            b"sceneio.attr.role": b"features",
        }
    )
    path = tmp_path / f"oracle{extension}"
    if format_id == "parquet":
        pq.write_table(table, path, compression="zstd", use_dictionary=False)
    else:
        with (
            pa.OSFile(str(path), "wb") as sink,
            ipc.new_file(sink, table.schema) as writer,
        ):
            writer.write_table(table)

    decoded = sceneio.read(path)

    _assert_tensor_dict(decoded, arrays)
    assert dict(decoded.attrs) == {
        "coordinate_order": "xy",
        "role": "features",
    }


def test_parquet_named_column_read_is_provider_bounded(tmp_path, monkeypatch):
    tensors, arrays = _fixture()
    path = tmp_path / "selected.parquet"
    sceneio.write(tensors, path)
    original = pq.read_table
    observed = []

    def instrumented(*args, **kwargs):
        observed.append(kwargs.get("columns"))
        return original(*args, **kwargs)

    monkeypatch.setattr(pq, "read_table", instrumented)
    selected = sceneio.read_partial(
        path,
        tensors=("image_id", "xy"),
    )

    assert observed == [["image_id", "xy"]]
    _assert_tensor_dict(
        selected,
        {"image_id": arrays["image_id"], "xy": arrays["xy"]},
    )


@pytest.mark.parametrize(
    ("format_id", "extension"),
    [("parquet", ".parquet"), ("arrow_ipc", ".arrow")],
)
def test_columnar_inspection_does_not_decode_table(
    tmp_path, monkeypatch, format_id, extension
):
    tensors, arrays = _fixture()
    path = tmp_path / f"inspect{extension}"
    sceneio.write(tensors, path, format=format_id)

    def fail_decode(*_args, **_kwargs):
        raise AssertionError("full table decode was called")

    monkeypatch.setattr(pq, "read_table", fail_decode)
    monkeypatch.setattr(ipc.RecordBatchFileReader, "read_all", fail_decode)
    info = sceneio.inspect(path)

    assert info.format == format_id
    assert info.count == len(arrays["image_id"])
    assert info.shape == (len(arrays["image_id"]), len(arrays))
    assert [item.name for item in info.arrays] == list(arrays)


def test_arrow_ipc_array_lifetime_survives_reader_and_file_removal(tmp_path):
    tensors, arrays = _fixture(8)
    path = tmp_path / "lifetime.arrow"
    sceneio.write(tensors, path)

    decoded = sceneio.read(path)
    path.unlink()
    gc.collect()

    _assert_tensor_dict(decoded, arrays)


@pytest.mark.parametrize(
    ("table", "message"),
    [
        (
            pa.table({"label": pa.array(["a", "b"])}),
            "unsupported type",
        ),
        (
            pa.table({"value": pa.array([1, None], type=pa.int32())}),
            "null values",
        ),
    ],
)
def test_parquet_rejects_unsupported_oracle_columns(tmp_path, table, message):
    path = tmp_path / "unsupported.parquet"
    pq.write_table(table, path)

    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read(path)


def test_columnar_writer_rejects_unequal_rows_and_unsupported_shapes(tmp_path):
    unequal = _core.tensor_dict(
        {
            "a": np.arange(3, dtype=np.float32),
            "b": np.arange(4, dtype=np.float32),
        }
    )
    rank3 = _core.tensor_dict(
        {"volume": np.zeros((2, 3, 4), dtype=np.float32)}
    )

    with pytest.raises(sceneio.FormatError, match="equal row count"):
        sceneio.write(unequal, tmp_path / "unequal.parquet")
    with pytest.raises(sceneio.FormatError, match="rank 1 or 2"):
        sceneio.write(rank3, tmp_path / "rank3.arrow")


@pytest.mark.parametrize(
    ("format_id", "extension", "target"),
    [
        ("parquet", ".parquet", "write_table"),
        ("arrow_ipc", ".arrow", "new_file"),
    ],
)
def test_columnar_failed_provider_write_preserves_destination(
    tmp_path, monkeypatch, format_id, extension, target
):
    tensors, _arrays = _fixture(3)
    path = tmp_path / f"preserve{extension}"
    path.write_bytes(b"previous")

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("injected provider failure")

    module = pq if format_id == "parquet" else ipc
    monkeypatch.setattr(module, target, fail_write)
    with pytest.raises(sceneio.FormatError, match="injected provider failure"):
        sceneio.write(tensors, path, format=format_id)

    assert path.read_bytes() == b"previous"
    assert not tuple(tmp_path.glob(f".preserve{extension}.*.tmp"))


def test_columnar_capabilities_and_open_license_notice():
    parquet = sceneio.capabilities("parquet")
    arrow = sceneio.capabilities("arrow_ipc")
    assert parquet.available and arrow.available
    assert parquet.partial_selectors == ("tensors",)
    assert arrow.partial_selectors == ()
    assert parquet.requires_features == arrow.requires_features == ("pyarrow",)

    root = Path(__file__).resolve().parents[2] / "LICENSES"
    assert "Apache Arrow" in (root / "apache-arrow-notice.txt").read_text(
        encoding="utf-8"
    )
    assert "Apache License" in (root / "apache-arrow-license.txt").read_text(
        encoding="utf-8"
    )
