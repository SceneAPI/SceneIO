"""Offline contract tests for the large-file source catalog and cache."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType

import pytest

from bench.io_bench.large import sources


def _spec(payload: bytes = b"offline-source") -> sources.SourceSpec:
    return sources.SourceSpec(
        id="offline_fixture",
        use="source helper test",
        repository="https://example.invalid/source",
        revision="0123456789abcdef0123456789abcdef01234567",
        revision_type="git_commit",
        source_path="fixtures/offline.bin",
        url="https://example.invalid/offline.bin",
        filename="offline.bin",
        license="MIT",
        license_url="https://opensource.org/license/mit/",
        attribution="SceneIO test fixture",
        expected_size_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        media_type="application/octet-stream",
        acquisition="test_only",
        derivation="none",
        sceneio_direct_supported=True,
        sceneio_direct_reason="offline helper fixture",
    )


def test_manifest_records_four_pinned_licensed_sources() -> None:
    catalog = sources.load_sources()
    assert tuple(catalog) == (
        "niantic_racoonfamily_spz",
        "pdal_autzen_laz",
        "khronos_box_vertex_colors_glb",
        "tum_freiburg1_xyz_groundtruth",
    )
    assert all(source.expected_size_bytes > 0 for source in catalog.values())
    assert all(len(source.expected_sha256) == 64 for source in catalog.values())
    assert (
        catalog["niantic_racoonfamily_spz"].expected_size_bytes,
        catalog["niantic_racoonfamily_spz"].expected_sha256,
    ) == (
        24202962,
        "2e068d893730955c09aee324ff170c559f71c0e8758c1b14c3811a5969333cfe",
    )
    assert (
        catalog["pdal_autzen_laz"].expected_size_bytes,
        catalog["pdal_autzen_laz"].expected_sha256,
    ) == (
        56350988,
        "944b947501156e45df1b3b9d25bc1dc04ff5ef377e7e169576ba59231c2896ba",
    )
    assert (
        catalog["khronos_box_vertex_colors_glb"].expected_size_bytes,
        catalog["khronos_box_vertex_colors_glb"].expected_sha256,
    ) == (
        1924,
        "9c48227f33b0ba2fbcf23b98ebf60d1c8ae0c6e6c5281e0aa3cc58affee10382",
    )
    assert (
        catalog["tum_freiburg1_xyz_groundtruth"].expected_size_bytes,
        catalog["tum_freiburg1_xyz_groundtruth"].expected_sha256,
    ) == (
        201100,
        "aac0319a6ef4e1cdf61e779d2152b95aa7e9f7b1749d6d18717b43ddabffede2",
    )
    assert catalog["niantic_racoonfamily_spz"].revision == (
        "5bf2945de1a003cee07133b1e495fe9c6ffdc7e7"
    )
    assert catalog["pdal_autzen_laz"].acquisition == "git_lfs_media"
    assert catalog["khronos_box_vertex_colors_glb"].license == "CC0-1.0"
    assert catalog["tum_freiburg1_xyz_groundtruth"].revision.startswith(
        "content-sha256:"
    )
    assert not catalog["niantic_racoonfamily_spz"].sceneio_direct_supported
    assert not catalog["pdal_autzen_laz"].sceneio_direct_supported
    assert not catalog["khronos_box_vertex_colors_glb"].sceneio_direct_supported
    assert catalog["tum_freiburg1_xyz_groundtruth"].sceneio_direct_supported
    assert "omit unsupported antialias metadata" in catalog[
        "niantic_racoonfamily_spz"
    ].derivation
    assert "laspy/lazrs" in catalog["pdal_autzen_laz"].derivation
    assert "normalized uint8" in catalog["khronos_box_vertex_colors_glb"].derivation
    assert "reconstruction seed" in catalog[
        "tum_freiburg1_xyz_groundtruth"
    ].derivation


def test_acquire_uses_verified_cache_layout_without_network(monkeypatch, tmp_path) -> None:
    payload = b"streamed fixture bytes"
    spec = _spec(payload)
    monkeypatch.setattr(
        sources,
        "load_sources",
        lambda manifest_path=None: MappingProxyType({spec.id: spec}),
    )
    calls: list[str] = []

    def fake_download(url: str, destination: Path) -> None:
        calls.append(url)
        destination.write_bytes(payload)

    monkeypatch.setattr(sources, "_download_to", fake_download)
    acquired = sources.acquire_sources(tmp_path)
    item = acquired[spec.id]
    assert calls == [spec.url]
    assert item.path == (tmp_path / spec.id / spec.filename).resolve()
    assert item.size_bytes == len(payload)
    assert item.sha256 == spec.expected_sha256
    with pytest.raises(TypeError):
        acquired["other"] = item  # type: ignore[index]

    def fail_if_network(*_args, **_kwargs):
        raise AssertionError("verify_sources must not access the network")

    monkeypatch.setattr(sources, "_download_to", fail_if_network)
    verified = sources.verify_sources(tmp_path)
    assert verified[spec.id] == item


def test_acquire_rejects_wrong_download_and_cleans_partial(monkeypatch, tmp_path) -> None:
    spec = _spec(b"expected bytes")
    monkeypatch.setattr(
        sources,
        "load_sources",
        lambda manifest_path=None: MappingProxyType({spec.id: spec}),
    )
    monkeypatch.setattr(
        sources,
        "_download_to",
        lambda _url, destination: destination.write_bytes(b"wrong bytes"),
    )
    with pytest.raises(sources.SourceIntegrityError, match="offline_fixture"):
        sources.acquire_sources(tmp_path)
    destination = tmp_path / spec.id / spec.filename
    assert not destination.exists()
    assert not destination.with_name(f".{destination.name}.part").exists()


def test_verify_reports_missing_cache_without_network(monkeypatch, tmp_path) -> None:
    spec = _spec()
    monkeypatch.setattr(
        sources,
        "load_sources",
        lambda manifest_path=None: MappingProxyType({spec.id: spec}),
    )
    monkeypatch.setattr(
        sources,
        "_download_to",
        lambda *_args, **_kwargs: pytest.fail("verify_sources attempted a download"),
    )
    with pytest.raises(FileNotFoundError, match="offline_fixture"):
        sources.verify_sources(tmp_path)


def test_only_rejects_unknown_source_ids(monkeypatch, tmp_path) -> None:
    spec = _spec()
    monkeypatch.setattr(
        sources,
        "load_sources",
        lambda manifest_path=None: MappingProxyType({spec.id: spec}),
    )
    with pytest.raises(KeyError, match="not-a-source"):
        sources.verify_sources(tmp_path, only=["not-a-source"])
