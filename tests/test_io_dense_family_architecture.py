"""Architecture contract for the COLMAP dense codec family and workspace."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import sceneio
from sceneio import _core
from sceneio.io import registry
from sceneio.io._builtin_manifest import FAMILY_MEMBERS
from sceneio.io._registry.families.dense import DENSE_CODECS

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "tests/contracts/io_dense_family_v1.json").read_text(
        encoding="utf-8"
    )
)


def test_dense_family_members_records_and_selectors_are_exact():
    ids = tuple(CONTRACT["ids"])
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["family"] == "dense"
    assert FAMILY_MEMBERS["dense"] == ids
    assert tuple(codec.id for codec in DENSE_CODECS) == ids
    for codec_id in ids:
        codec = registry.REGISTRY[codec_id]
        capabilities = codec.capabilities()
        assert capabilities.record_type == CONTRACT["records"][codec_id]
        assert list(capabilities.partial_selectors) == (
            CONTRACT["partial_selectors"][codec_id]
        )
        assert capabilities.streams_read
        assert capabilities.streams_write
        assert capabilities.can_inspect


def test_dense_detection_is_topology_bounded():
    for codec_id in CONTRACT["explicit_only_ids"]:
        codec = registry.REGISTRY[codec_id]
        assert not codec.extensions
        assert not codec.filenames
        assert not codec.magic
    for filename, codec_id in CONTRACT["exact_filename_detection"].items():
        assert registry.REGISTRY[codec_id].filenames == (filename,)


def test_dense_native_and_python_ownership_sources_are_present():
    for relative in (
        *CONTRACT["native_sources"],
        *CONTRACT["python_sources"],
    ):
        assert (ROOT / relative).is_file(), relative
    assert all(
        registry.REGISTRY[codec_id].record is getattr(
            _core,
            CONTRACT["records"][codec_id],
        )
        for codec_id in CONTRACT["ids"]
    )
    codec_source = (
        ROOT / "src/cpp/codecs/dense/colmap_mvs.cpp"
    ).read_text(encoding="utf-8")
    record_header = (
        ROOT / "src/cpp/records/dense_mvs.hpp"
    ).read_text(encoding="utf-8")
    assert "image_indices.reserve(word_count)" not in codec_source
    assert "maximum_entries" not in codec_source
    assert "(size - position -" not in codec_source
    assert (
        "const GraphStats stats =\n"
        "            scan_consistency(bytes.data(), bytes.size(), info, nullptr);"
    ) in codec_source
    assert (
        "const VisibilityStats stats =\n"
        "            scan_visibility(bytes.data(), bytes.size(), nullptr);"
    ) in codec_source
    assert codec_source.count(
        "result.image_indices.reserve(stats.links);"
    ) == 2
    consistency_reader = codec_source[
        codec_source.index("ConsistencyGraph read_consistency(") :
        codec_source.index("nb::tuple inspect_consistency(")
    ]
    visibility_reader = codec_source[
        codec_source.index("PointVisibility read_visibility(") :
        codec_source.index("nb::tuple inspect_visibility(")
    ]
    for reader_source in (consistency_reader, visibility_reader):
        assert reader_source.count("image_indices.reserve(") == 1
        assert (
            "result.image_indices.reserve(stats.links);"
            in reader_source
        )
    for cap in (
        "kColmapMvsDimensionCap",
        "kColmapMvsEntryCap",
        "kColmapMvsListValueCap",
    ):
        assert cap in record_header
        assert cap in codec_source
    assert codec_source.count("std::optional<EncodedOutput> output;") == 4
    assert codec_source.count("nb::gil_scoped_release release;") >= 12
    assert "checked_mul(graph.rows.size(), 3" in codec_source
    assert "checked_add(\n            visibility.point_count()" in codec_source


def test_workspace_is_public_but_not_a_directory_codec():
    workspace = sceneio.colmap_mvs
    assert workspace.open_workspace
    assert workspace.inspect_workspace
    assert workspace.open_pmvs_workspace
    assert workspace.open_cmp_mvs_workspace
    assert not (
        set(sceneio.codecs())
        & {
            "colmap_mvs_workspace",
            "pmvs_workspace",
            "cmp_mvs_workspace",
        }
    )
    assert CONTRACT["workspace_registry_ids"] == []
    record = _core.consistency_graph(
        1,
        1,
        np.empty((0,), np.uint32),
        np.empty((0,), np.uint32),
        np.array([0], np.uint64),
        np.empty((0,), np.uint32),
    )
    assert record.index_domain == CONTRACT["index_domain"]
