from __future__ import annotations

import gc
import json
from pathlib import Path

import numpy as np
import pytest
import tifffile

import sceneio
from sceneio import _core
from sceneio.data import InstanceMap, LabelTaxonomy, Mask, PanopticMap, SemanticMap
from sceneio.io import _tiff


def _pixels(image) -> np.ndarray:
    return np.asarray(image.pixels)


def test_tiff_record_outlives_closed_and_removed_source(tmp_path):
    values = np.arange(7 * 9 * 3, dtype=np.uint16).reshape(7, 9, 3)
    path = tmp_path / "lifetime.tiff"
    sceneio.write(_core.image(values, color_space="srgb"), path)

    decoded = sceneio.read(path)
    path.unlink()
    gc.collect()

    np.testing.assert_array_equal(_pixels(decoded), values)


@pytest.mark.parametrize(
    ("shape", "dtype"),
    [
        ((7, 9), np.uint8),
        ((7, 9), np.uint16),
        ((7, 9), np.float32),
        ((7, 9, 3), np.uint8),
        ((7, 9, 3), np.uint16),
        ((7, 9, 4), np.uint8),
    ],
)
def test_sceneio_tiff_write_is_exact_for_independent_oracle(
    tmp_path, shape, dtype
):
    values = np.arange(np.prod(shape), dtype=np.float64).reshape(shape)
    if dtype == np.float32:
        values = (values / max(values.size - 1, 1)).astype(dtype)
    else:
        values = values.astype(dtype)
    image = _core.image(values)
    path = tmp_path / "sceneio.tiff"

    sceneio.write(image, path)

    oracle = tifffile.imread(path)
    np.testing.assert_array_equal(oracle, values)
    assert sceneio.detect(path) == "tiff"
    decoded = sceneio.read(path)
    assert isinstance(decoded, _core.Image)
    np.testing.assert_array_equal(_pixels(decoded), values)
    assert decoded.color_space == image.color_space
    assert decoded.alpha_mode == image.alpha_mode


@pytest.mark.parametrize("byteorder", ["<", ">"])
def test_sceneio_reads_oracle_tiff_endianness_exactly(tmp_path, byteorder):
    path = tmp_path / f"oracle-{byteorder == '>'}.tif"
    values = np.array(
        [[0, 1, 255, 256], [4096, 32768, 60000, 65535]],
        dtype=np.dtype(f"{byteorder}u2"),
    )
    tifffile.imwrite(
        path,
        values,
        byteorder=byteorder,
        photometric="minisblack",
        metadata=None,
    )

    decoded = sceneio.read(path)

    np.testing.assert_array_equal(_pixels(decoded), values)
    assert _pixels(decoded).dtype.isnative


def test_tiff_boolean_mask_roundtrip_and_oracle(tmp_path):
    path = tmp_path / "mask.tif"
    values = (np.indices((8, 11)).sum(axis=0) % 3) == 0

    sceneio.write(Mask(values), path)

    np.testing.assert_array_equal(tifffile.imread(path), values)
    decoded = sceneio.read(path)
    assert isinstance(decoded, Mask)
    np.testing.assert_array_equal(decoded.mask, values)
    info = sceneio.inspect(path)
    assert info.datatype == "mask"
    assert info.shape == values.shape
    assert info.dtype == "bool"


@pytest.mark.parametrize("axes", ["ZYX", "TYX"])
def test_tiff_grayscale_stack_roundtrip_and_oracle(tmp_path, axes):
    path = tmp_path / "stack.tiff"
    values = np.arange(4 * 6 * 8, dtype=np.float32).reshape(4, 6, 8)
    stack = _core.tensor_dict({"pages": values}, attrs={"axes": axes})

    sceneio.write(stack, path)

    np.testing.assert_array_equal(tifffile.imread(path), values)
    with tifffile.TiffFile(path) as oracle:
        assert oracle.series[0].axes == axes
    decoded = sceneio.read(path)
    assert isinstance(decoded, _core.TensorDict)
    np.testing.assert_array_equal(decoded["pages"], values)
    assert dict(decoded.attrs) == {"axes": axes}
    info = sceneio.inspect(path)
    assert info.datatype == "image_stack"
    assert info.shape == values.shape
    assert info.count == values.shape[0]
    assert info.arrays[0].name == "pages"


def test_tiff_bigtiff_profile_is_oracle_readable(tmp_path):
    path = tmp_path / "small-bigtiff.tif"
    values = np.arange(30, dtype=np.uint16).reshape(5, 6)

    sceneio.write_tiff(_core.image(values), path, bigtiff=True)

    with tifffile.TiffFile(path) as oracle:
        assert oracle.is_bigtiff
        np.testing.assert_array_equal(oracle.asarray(), values)
    assert path.read_bytes()[:4] in {b"II+\x00", b"MM\x00+"}
    assert sceneio.inspect(path).metadata["bigtiff"] is True


@pytest.mark.parametrize(
    ("alpha_mode", "expected_extra"),
    [("straight", 2), ("premultiplied", 1)],
)
def test_tiff_alpha_semantics_roundtrip(tmp_path, alpha_mode, expected_extra):
    path = tmp_path / f"{alpha_mode}.tif"
    values = np.arange(5 * 6 * 4, dtype=np.uint8).reshape(5, 6, 4)
    image = _core.image(values, alpha_mode=alpha_mode)

    sceneio.write(image, path)

    with tifffile.TiffFile(path) as oracle:
        assert tuple(int(item) for item in oracle.pages[0].extrasamples) == (
            expected_extra,
        )
    decoded = sceneio.read(path)
    assert decoded.alpha_mode == alpha_mode
    np.testing.assert_array_equal(_pixels(decoded), values)


def test_tiff_inspect_does_not_decode_pixels(tmp_path, monkeypatch):
    path = tmp_path / "metadata.tif"
    values = np.arange(12, dtype=np.uint8).reshape(3, 4)
    tifffile.imwrite(path, values, photometric="minisblack", metadata=None)

    def fail_decode(*_args, **_kwargs):
        raise AssertionError("pixel decode was called")

    monkeypatch.setattr(tifffile.TiffPageSeries, "asarray", fail_decode)
    info = sceneio.inspect(path)

    assert info.shape == values.shape
    assert info.dtype == "uint8"
    assert info.channels == 1


def test_tiff_rejects_multiple_series_without_decoding(tmp_path):
    path = tmp_path / "multi-series.tif"
    first = np.arange(4 * 5, dtype=np.uint8).reshape(4, 5)
    second = (np.arange(3 * 7, dtype=np.uint8) + 100).reshape(3, 7)
    with tifffile.TiffWriter(path) as writer:
        writer.write(
            first,
            photometric="minisblack",
            metadata=None,
        )
        writer.write(
            second,
            photometric="minisblack",
            metadata=None,
        )

    with tifffile.TiffFile(path) as oracle:
        assert len(oracle.series) == 2
        assert [tuple(series.shape) for series in oracle.series] == [
            (4, 5),
            (3, 7),
        ]
        np.testing.assert_array_equal(oracle.series[0].asarray(), first)
        np.testing.assert_array_equal(oracle.series[1].asarray(), second)
    with pytest.raises(sceneio.FormatError, match="exactly one image series"):
        sceneio.read(path)


def test_tifffile_provider_pyramid_surface_and_sceneio_boundary(tmp_path):
    path = tmp_path / "pyramid.tif"
    full = np.arange(8 * 10, dtype=np.uint8).reshape(8, 10)
    reduced = full[::2, ::2].copy()
    with tifffile.TiffWriter(path) as writer:
        writer.write(
            full,
            photometric="minisblack",
            metadata=None,
            subifds=1,
        )
        writer.write(
            reduced,
            photometric="minisblack",
            metadata=None,
            subfiletype=1,
        )

    with tifffile.TiffFile(path) as oracle:
        assert len(oracle.series) == 1
        assert len(oracle.series[0].levels) == 2
        np.testing.assert_array_equal(oracle.series[0].levels[0].asarray(), full)
        np.testing.assert_array_equal(
            oracle.series[0].levels[1].asarray(), reduced
        )
    with pytest.raises(sceneio.FormatError, match="pyramidal image series"):
        sceneio.read(path)


def test_tiff_rejects_ambiguous_channel_and_stack_layouts(tmp_path):
    path = tmp_path / "two-channel.tif"
    tifffile.imwrite(
        path,
        np.zeros((4, 5, 2), dtype=np.uint8),
        photometric="minisblack",
        metadata={"axes": "YXS"},
    )

    with pytest.raises(sceneio.FormatError, match="unsupported or ambiguous"):
        sceneio.read(path)

    bad_stack = _core.tensor_dict(
        {"pages": np.zeros((2, 3, 4), dtype=np.float32)},
        attrs={"axes": "YXS"},
    )
    with pytest.raises(sceneio.FormatError, match="supported 'axes'"):
        sceneio.write(bad_stack, tmp_path / "bad-stack.tif")


def test_tiff_rejects_nondefault_image_conventions(tmp_path):
    linear = _core.image(
        np.zeros((3, 4, 3), dtype=np.float32),
        color_space="linear",
    )
    limited = _core.image(
        np.zeros((3, 4), dtype=np.uint16),
        color_space="gray",
        maxval=1000,
    )

    with pytest.raises(sceneio.FormatError, match="requires srgb"):
        sceneio.write(linear, tmp_path / "linear.tif")
    with pytest.raises(sceneio.FormatError, match="full-range maxval"):
        sceneio.write(limited, tmp_path / "limited.tif")


def test_tiff_failed_provider_write_preserves_destination(
    tmp_path, monkeypatch
):
    path = tmp_path / "preserve.tif"
    path.write_bytes(b"previous")

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("injected provider failure")

    monkeypatch.setattr(tifffile, "imwrite", fail_write)
    with pytest.raises(sceneio.FormatError, match="injected provider failure"):
        sceneio.write(_core.image(np.zeros((2, 3), np.uint8)), path)

    assert path.read_bytes() == b"previous"
    assert not tuple(tmp_path.glob(".preserve.tif.*.tmp"))


def test_tiff_capabilities_and_license_contract():
    capabilities = sceneio.capabilities("tiff")
    assert capabilities.available
    assert capabilities.requires_features == ("tifffile", "zarr")
    assert capabilities.streams_read
    assert capabilities.streams_write
    assert "bigtiff" in capabilities.supported_features
    assert "pyramids" in capabilities.supported_features
    assert "window_selection" in capabilities.supported_features
    assert "legacy_pyramids" in capabilities.unsupported_features

    license_text = (
        Path(__file__).resolve().parents[2] / "LICENSES" / "tifffile.txt"
    ).read_text(encoding="utf-8")
    assert "BSD-3-Clause" in license_text
    assert "Christoph Gohlke" in license_text


def _typed_tiff_maps() -> tuple[SemanticMap, InstanceMap, PanopticMap]:
    semantic_ids = np.array([[0, 4, -1], [4, 4, 0]], np.int32)
    valid = np.array([[True, True, False], [True, True, True]], np.bool_)
    taxonomy = LabelTaxonomy(
        np.array([0, 4], np.int32),
        ("background", "object"),
        "example.taxonomy",
        "v1",
        np.array([[0, 0, 0], [220, 20, 60]], np.uint8),
        np.array([False, True], np.bool_),
    )
    semantic = SemanticMap(semantic_ids, -1, valid, taxonomy)
    instance = InstanceMap(
        np.array([[0, 7, 0], [9, 7, 0]], np.int64),
        0,
        valid,
        np.array([7, 9], np.int64),
        np.array([4, 4], np.int32),
    )
    return semantic, instance, PanopticMap(semantic, instance)


def _assert_typed_map(actual, expected) -> None:
    if isinstance(expected, SemanticMap):
        assert isinstance(actual, SemanticMap)
        np.testing.assert_array_equal(actual.class_ids, expected.class_ids)
        np.testing.assert_array_equal(actual.valid, expected.valid)
        assert actual.void_id == expected.void_id
        assert actual.taxonomy is not None
        assert expected.taxonomy is not None
        np.testing.assert_array_equal(
            actual.taxonomy.semantic_ids, expected.taxonomy.semantic_ids
        )
        assert actual.taxonomy.names == expected.taxonomy.names
        assert actual.taxonomy.identity == expected.taxonomy.identity
        assert actual.taxonomy.version == expected.taxonomy.version
        np.testing.assert_array_equal(
            actual.taxonomy.display_colors, expected.taxonomy.display_colors
        )
        np.testing.assert_array_equal(
            actual.taxonomy.is_thing, expected.taxonomy.is_thing
        )
        return
    if isinstance(expected, InstanceMap):
        assert isinstance(actual, InstanceMap)
        np.testing.assert_array_equal(actual.instance_ids, expected.instance_ids)
        np.testing.assert_array_equal(actual.valid, expected.valid)
        np.testing.assert_array_equal(actual.table_instance_ids, expected.table_instance_ids)
        np.testing.assert_array_equal(actual.table_semantic_ids, expected.table_semantic_ids)
        assert actual.background_id == expected.background_id
        return
    assert isinstance(actual, PanopticMap)
    _assert_typed_map(actual.semantic, expected.semantic)
    _assert_typed_map(actual.instance, expected.instance)


@pytest.mark.parametrize("index", range(3), ids=("semantic", "instance", "panoptic"))
def test_typed_tiff_roundtrip_and_tifffile_oracle(tmp_path, index):
    expected = _typed_tiff_maps()[index]
    path = tmp_path / "labels.tiff"

    _tiff.write_tiff_label_map(expected, path)

    with tifffile.TiffFile(path) as oracle:
        descriptions = [json.loads(page.description) for page in oracle.pages]
        assert descriptions[0]["schema"] == "sceneio.label_map/1"
        assert descriptions[0]["kind"] == ("semantic", "instance", "panoptic")[index]
        assert len(oracle.pages) == (2 if index < 2 else 3)
        assert [page.asarray().dtype.name for page in oracle.pages] == (
            ["int32", "bool"]
            if index == 0
            else ["int64", "bool"]
            if index == 1
            else ["int32", "int64", "bool"]
        )
        if isinstance(expected, SemanticMap):
            oracle_arrays = (expected.class_ids, expected.valid)
        elif isinstance(expected, InstanceMap):
            oracle_arrays = (expected.instance_ids, expected.valid)
        else:
            oracle_arrays = (
                expected.semantic.class_ids,
                expected.instance.instance_ids,
                expected.semantic.valid,
            )
        for page, expected_array in zip(oracle.pages, oracle_arrays, strict=True):
            np.testing.assert_array_equal(page.asarray(), expected_array)

    _assert_typed_map(_tiff.read_tiff_label_map(path), expected)
    info = _tiff.inspect_tiff_label_map(path)
    assert info.metadata["schema"] == "sceneio.label_map/1"
    assert info.metadata["kind"] == ("semantic", "instance", "panoptic")[index]


def test_typed_tiff_untagged_integer_requires_explicit_contract(tmp_path):
    values = np.array([[0, 7], [9, 1]], np.uint16)
    path = tmp_path / "ordinary.tif"
    tifffile.imwrite(path, values, photometric="minisblack", metadata=None)

    decoded = sceneio.read(path)
    assert isinstance(decoded, _core.Image)
    np.testing.assert_array_equal(decoded.pixels, values)
    with pytest.raises(ValueError, match="does not declare"):
        _tiff.read_tiff_label_map(path)

    typed = _tiff.read_tiff_label_map(
        path,
        label_contract={"kind": "semantic", "void_id": -1},
    )
    assert isinstance(typed, SemanticMap)
    np.testing.assert_array_equal(typed.class_ids, values)


def test_typed_tiff_validates_and_decodes_through_one_open_handle(
    tmp_path, monkeypatch
):
    path = tmp_path / "labels.tif"
    expected = _typed_tiff_maps()[2]
    _tiff.write_tiff_label_map(expected, path)
    original = tifffile.TiffFile
    opened = 0

    def counted_open(*args, **kwargs):
        nonlocal opened
        opened += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(tifffile, "TiffFile", counted_open)
    actual = _tiff.read_tiff_label_map(path)

    assert opened == 1
    _assert_typed_map(actual, expected)
    path.unlink()
    gc.collect()
    _assert_typed_map(actual, expected)


def test_typed_tiff_rejects_unknown_description_fields(tmp_path):
    expected = _typed_tiff_maps()[0]
    path = tmp_path / "unknown-field.tif"
    _tiff.write_tiff_label_map(expected, path)
    with tifffile.TiffFile(path, mode="r+") as oracle:
        tag = oracle.pages[0].tags[270]
        description = json.loads(tag.value)
        description["future_field"] = 1
        tag.overwrite(json.dumps(description).encode("ascii"))

    with pytest.raises(ValueError, match="unknown fields"):
        _tiff.read_tiff_label_map(path)


def test_typed_tiff_inspect_does_not_decode_raster(tmp_path, monkeypatch):
    path = tmp_path / "labels.tif"
    _tiff.write_tiff_label_map(_typed_tiff_maps()[2], path)

    def fail_decode(*_args, **_kwargs):
        raise AssertionError("typed TIFF inspection decoded samples")

    monkeypatch.setattr(tifffile.TiffPage, "asarray", fail_decode)
    info = _tiff.inspect_tiff_label_map(path)
    assert info.datatype == "panoptic_map"
    assert info.shape == (2, 3)


@pytest.mark.parametrize("index", range(3), ids=("semantic", "instance", "panoptic"))
def test_typed_tiff_public_dispatch_roundtrip(tmp_path, index):
    expected = _typed_tiff_maps()[index]
    path = tmp_path / "labels.tif"

    sceneio.write_label_map(expected, path, bigtiff=False)

    assert sceneio.detect(path) == "tiff"
    _assert_typed_map(sceneio.read_label_map(path), expected)
    info = sceneio.inspect_label_map(path)
    assert info.format == "tiff"
    assert info.datatype == f"{('semantic', 'instance', 'panoptic')[index]}_map"
    assert info.shape == expected.shape


def test_typed_tiff_public_contract_and_error_wrapping(tmp_path):
    values = np.array([[0, 7], [9, 1]], np.uint16)
    path = tmp_path / "ordinary.tiff"
    tifffile.imwrite(path, values, photometric="minisblack", metadata=None)

    with pytest.raises(sceneio.FormatError, match="does not declare"):
        sceneio.read_label_map(path)
    contract = {"kind": "semantic", "void_id": -1}
    typed = sceneio.read_label_map(path, label_contract=contract)
    np.testing.assert_array_equal(typed.class_ids, values)
    info = sceneio.inspect_label_map(path, label_contract=contract)
    assert info.metadata["schema"] == "sceneio.label_map/1"
    assert info.metadata["schema_source"] == "caller_contract"
    assert info.metadata["void_id"] == -1


@pytest.mark.parametrize(
    "contract",
    [
        {
            "kind": "semantic",
            "void_id": -1,
            "background_id": 0,
        },
        {
            "kind": "semantic",
            "void_id": -1,
            "table_instance_ids": [1],
            "table_semantic_ids": [4],
        },
        {
            "kind": "instance",
            "background_id": 0,
            "void_id": -1,
        },
        {
            "kind": "instance",
            "background_id": 0,
            "taxonomy": {
                "semantic_ids": [4],
                "names": ["cube"],
                "identity": "org.example",
                "version": "1",
            },
        },
    ],
)
def test_typed_tiff_untagged_contract_rejects_incompatible_fields(
    tmp_path, contract
):
    path = tmp_path / "ordinary.tif"
    tifffile.imwrite(
        path,
        np.array([[0, 1]], dtype=np.uint16),
        photometric="minisblack",
        metadata=None,
    )

    with pytest.raises(sceneio.FormatError, match="incompatible fields"):
        sceneio.read_label_map(path, label_contract=contract)


def test_typed_tiff_public_bigtiff_roundtrip(tmp_path):
    expected = _typed_tiff_maps()[2]
    path = tmp_path / "labels-bigtiff.tif"

    sceneio.write_label_map(expected, path, bigtiff=True)

    with tifffile.TiffFile(path) as oracle:
        assert oracle.is_bigtiff
    _assert_typed_map(sceneio.read_label_map(path), expected)
    assert sceneio.inspect_label_map(path).metadata["bigtiff"] is True


@pytest.mark.parametrize(
    ("page_index", "field", "bad_value", "message"),
    [
        (0, "dtypes", {"semantic_ids": "uint16", "valid": "bool"}, "dtypes"),
        (1, "shape", [99, 99], "shape"),
        (1, "dtype", "uint8", "dtype"),
    ],
)
def test_typed_tiff_description_matches_every_page(
    tmp_path, page_index, field, bad_value, message
):
    path = tmp_path / "bad-description.tif"
    _tiff.write_tiff_label_map(_typed_tiff_maps()[0], path)
    with tifffile.TiffFile(path, mode="r+") as oracle:
        tag = oracle.pages[page_index].tags[270]
        description = json.loads(tag.value)
        description[field] = bad_value
        tag.overwrite(json.dumps(description, separators=(",", ":")).encode("ascii"))

    with pytest.raises(ValueError, match=message):
        _tiff.read_tiff_label_map(path)


def test_typed_tiff_rejects_duplicate_and_oversized_descriptions(tmp_path):
    semantic = _typed_tiff_maps()[0]
    value = SemanticMap(
        semantic.class_ids,
        semantic.void_id,
        taxonomy=semantic.taxonomy,
    )
    tagged = tmp_path / "tagged.tif"
    _tiff.write_tiff_label_map(value, tagged)
    with tifffile.TiffFile(tagged) as oracle:
        description = oracle.pages[0].description
    duplicate = description.replace(
        '"kind":"semantic"',
        '"kind":"semantic","kind":"semantic"',
        1,
    )
    duplicate_path = tmp_path / "duplicate.tif"
    tifffile.imwrite(
        duplicate_path,
        value.class_ids,
        photometric="minisblack",
        metadata=None,
        description=duplicate,
    )
    with pytest.raises(ValueError, match="repeats key"):
        _tiff.read_tiff_label_map(duplicate_path)

    oversized_path = tmp_path / "oversized.tif"
    oversized = '{"schema":"sceneio.label_map/1","padding":"' + (
        "x" * ((1 << 20) + 1)
    ) + '"}'
    tifffile.imwrite(
        oversized_path,
        np.zeros((1, 1), np.int32),
        photometric="minisblack",
        metadata=None,
        description=oversized,
    )
    with pytest.raises(ValueError, match="exceeds 1 MiB"):
        _tiff.inspect_tiff_label_map(oversized_path)

    oversized_taxonomy = LabelTaxonomy(
        np.array([4], np.int32),
        ("x" * ((1 << 20) + 1),),
        "org.example",
        "1",
    )
    oversized_value = SemanticMap(
        np.array([[4]], np.int32),
        -1,
        taxonomy=oversized_taxonomy,
    )
    destination = tmp_path / "oversized-write.tif"
    destination.write_bytes(b"existing")
    with pytest.raises(ValueError, match="exceeds 1 MiB"):
        _tiff.write_tiff_label_map(oversized_value, destination)
    assert destination.read_bytes() == b"existing"
    assert not tuple(tmp_path.glob(".oversized-write.tif.*.tmp"))


def test_typed_tiff_rejects_hidden_pyramid_subifd(tmp_path):
    source = _typed_tiff_maps()[0]
    value = SemanticMap(
        source.class_ids,
        source.void_id,
        taxonomy=source.taxonomy,
    )
    reference = tmp_path / "reference.tif"
    _tiff.write_tiff_label_map(value, reference)
    with tifffile.TiffFile(reference) as oracle:
        description = oracle.pages[0].description

    path = tmp_path / "pyramid-labels.tif"
    with tifffile.TiffWriter(path) as writer:
        writer.write(
            value.class_ids,
            photometric="minisblack",
            metadata=None,
            description=description,
            subifds=1,
        )
        writer.write(
            value.class_ids[:1, :2],
            photometric="minisblack",
            metadata=None,
            subfiletype=1,
        )

    with pytest.raises(ValueError, match="pyramid SubIFDs"):
        _tiff.read_tiff_label_map(path)


def test_typed_tiff_contract_cannot_override_tagged_instance_table(tmp_path):
    path = tmp_path / "labels.tif"
    _tiff.write_tiff_label_map(_typed_tiff_maps()[1], path)
    contract = {
        "kind": "instance",
        "background_id": 0,
        "table_instance_ids": [7, 8],
        "table_semantic_ids": [4, 4],
    }
    with pytest.raises(sceneio.FormatError, match="contract table_instance_ids"):
        sceneio.read_label_map(path, label_contract=contract)


def test_typed_tiff_explicit_contract_ignores_unrelated_description(tmp_path):
    path = tmp_path / "scanner-export.tif"
    values = np.array([[0, 4], [4, 0]], np.uint16)
    tifffile.imwrite(
        path,
        values,
        photometric="minisblack",
        metadata=None,
        description="ordinary scanner provenance",
    )
    actual = sceneio.read_label_map(
        path,
        label_contract={"kind": "semantic", "void_id": -1},
    )
    np.testing.assert_array_equal(actual.class_ids, values)


def test_typed_tiff_accepts_oracle_big_endian_page(tmp_path):
    semantic = _typed_tiff_maps()[0]
    value = SemanticMap(
        semantic.class_ids,
        semantic.void_id,
        taxonomy=semantic.taxonomy,
    )
    reference = tmp_path / "reference.tif"
    _tiff.write_tiff_label_map(value, reference)
    with tifffile.TiffFile(reference) as oracle:
        description = oracle.pages[0].description

    path = tmp_path / "big-endian.tif"
    with tifffile.TiffWriter(path, byteorder=">") as oracle:
        oracle.write(
            value.class_ids,
            photometric="minisblack",
            metadata=None,
            description=description,
        )
    actual = _tiff.read_tiff_label_map(path)
    np.testing.assert_array_equal(actual.class_ids, value.class_ids)


def test_typed_tiff_failed_write_preserves_destination(tmp_path, monkeypatch):
    path = tmp_path / "labels.tif"
    path.write_bytes(b"existing destination")

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("oracle write failure")

    monkeypatch.setattr(tifffile.TiffWriter, "write", fail_write)
    with pytest.raises(sceneio.FormatError, match="oracle write failure"):
        sceneio.write_label_map(_typed_tiff_maps()[0], path)
    assert path.read_bytes() == b"existing destination"
    assert not tuple(tmp_path.glob(".labels.tif.*.tmp"))
