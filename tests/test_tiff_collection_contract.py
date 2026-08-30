"""Machine checks for the versioned bounded TIFF collection contract."""

from __future__ import annotations

import inspect
import tomllib
from dataclasses import fields
from pathlib import Path

import sceneio
from sceneio import (
    RASTER_AXES,
    RASTER_DTYPES,
    RASTER_PAYLOAD_KINDS,
    RasterCollection,
    RasterLevel,
    RasterSeries,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/tiff_collections_v1.toml").read_text(
        encoding="utf-8"
    )
)


def test_tiff_collection_contract_matches_records_and_public_api():
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["format_id"] == "tiff"
    records = CONTRACT["records"]
    assert [field.name for field in fields(RasterLevel)] == records["level_fields"]
    assert [field.name for field in fields(RasterSeries)] == records["series_fields"]
    assert [field.name for field in fields(RasterCollection)] == records[
        "collection_fields"
    ]
    assert set(records["axes"]) == RASTER_AXES
    assert set(records["dtypes"]) == RASTER_DTYPES
    assert set(records["payload_kinds"]) == RASTER_PAYLOAD_KINDS

    parameters = inspect.signature(sceneio.read_tiff_collection).parameters
    assert tuple(parameters) == (
        "path",
        "series_index",
        "level_index",
        "page_range",
        "window",
    )
    assert set(CONTRACT["selectors"]) >= set(parameters) - {"path"}
    assert sceneio.RasterCollection is RasterCollection
    assert sceneio.RasterLevel is RasterLevel
    assert sceneio.RasterSeries is RasterSeries


def test_tiff_collection_contract_matches_dependencies_and_capabilities():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]["tiff"]
    assert CONTRACT["provider"] in extras
    assert CONTRACT["selection_provider"] in extras

    capabilities = sceneio.capabilities("tiff")
    assert capabilities.requires_features == ("tifffile", "zarr")
    assert {
        "typed_raster_collection",
        "multiple_series",
        "pyramids",
        "series_selection",
        "level_selection",
        "page_range_selection",
        "window_selection",
    } <= set(capabilities.supported_features)
    assert {"legacy_multiple_series", "legacy_pyramids", "ome_semantics"} <= set(
        capabilities.unsupported_features
    )


def test_tiff_collection_contract_has_live_benchmark_and_documentation():
    source = (ROOT / "src/sceneio/io/_tiff.py").read_text(encoding="utf-8")
    assert ".aszarr(level=level_index)" in source
    assert "os.replace(temporary, destination)" in source
    assert (ROOT / "bench/io_bench/tiff_collections.py").is_file()
    document = (ROOT / "docs/tiff_collection_benchmark.md").read_text(
        encoding="utf-8"
    )
    assert "98.65%" in document
    assert "64 MiB" in document
    benchmark = CONTRACT["benchmark"]
    assert benchmark["large_fixture_logical_bytes"] == 64 * 1024 * 1024
    assert benchmark["fresh_process_protocol"] == (
        "sceneio-fresh-child-memory-v1"
    )
    assert benchmark["fresh_process_samples"] == 3
    assert benchmark["operations"] == [
        "typed_full_read",
        "typed_selected_read",
        "typed_inspect",
    ]
