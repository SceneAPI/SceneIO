"""Tests for the sceneio.formats registry."""

from __future__ import annotations

import pytest

from sceneio.errors import ContractViolation
from sceneio.formats import (
    CORE_FORMAT_IDS,
    CORE_FORMATS,
    FormatSpec,
    get_format,
    is_core_format,
)

# The exact id strings of the core's artifacts vocabulary
# (sceneapi/server/core/artifacts.py::CORE_ARTIFACT_FORMATS). Wire
# identity is untouched: this seed must never drift from the core.
EXPECTED_CORE_IDS = {
    "sfmapi.features.local.v1",
    "sfmapi.features.global.v1",
    "sfmapi.pairs.image_names.v1",
    "sfmapi.matches.indexed.v1",
    "sfmapi.matches.coordinates.v1",
    "sfmapi.matches.dense.v1",
    "sfmapi.matches.verified.v1",
    "sfmapi.reconstruction.sparse.v1",
    "sfmapi.reconstruction.snapshot.v1",
    "sfmapi.reconstruction.submodel.v1",
    "sfmapi.projection.images.v1",
}


def test_core_format_ids_mirror_core_artifacts_vocabulary() -> None:
    assert CORE_FORMAT_IDS == EXPECTED_CORE_IDS


def test_registry_keys_match_spec_ids() -> None:
    for format_id, spec in CORE_FORMATS.items():
        assert spec.id == format_id


def test_kinds_use_core_datatype_vocabulary() -> None:
    kinds = {spec.kind for spec in CORE_FORMATS.values()}
    assert kinds == {"feature_set", "pair_set", "match_graph", "sparse_model", "projection"}


def test_get_format() -> None:
    spec = get_format("sfmapi.matches.indexed.v1")
    assert spec is not None
    assert spec.kind == "match_graph"
    assert get_format("sfmapi.nope.v9") is None


def test_is_core_format() -> None:
    assert is_core_format("sfmapi.reconstruction.sparse.v1")
    assert not is_core_format("sfmapi.reconstruction.sparse.v2")


def test_manifest_formats_have_no_single_media_type() -> None:
    # The core artifact formats are multi-file manifest formats; a single
    # canonical media type would be lossy, so they register None.
    assert all(spec.media_type is None for spec in CORE_FORMATS.values())


class TestFormatSpecValidation:
    def test_valid(self) -> None:
        FormatSpec(id="x.y.v1", kind="feature_set", media_type="application/json", description="d")

    @pytest.mark.parametrize("bad", ["", None, 3])
    def test_bad_id_raises(self, bad: object) -> None:
        with pytest.raises(ContractViolation, match=r"FormatSpec\.id"):
            FormatSpec(id=bad, kind="k", media_type=None, description="d")  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", ["", None])
    def test_bad_kind_raises(self, bad: object) -> None:
        with pytest.raises(ContractViolation, match=r"FormatSpec\.kind"):
            FormatSpec(id="x", kind=bad, media_type=None, description="d")  # type: ignore[arg-type]

    def test_empty_media_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"FormatSpec\.media_type"):
            FormatSpec(id="x", kind="k", media_type="", description="d")

    def test_empty_description_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"FormatSpec\.description"):
            FormatSpec(id="x", kind="k", media_type=None, description="")
