"""Pinned tifffile/Zarr behaviors relied on by typed TIFF collections."""

from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path

import numpy as np
import pytest
import tifffile
import zarr

import sceneio

_OME_4D_SHA256 = "caf707ca2ba6c42c40ded92245432d350a781fcdd03c0b178834f5eb5e5b96f3"


def test_tiff_collection_provider_versions_and_selection_surface_are_qualified():
    assert tuple(int(part) for part in tifffile.__version__.split(".")) >= (
        2025,
        5,
    )
    assert tuple(int(part) for part in zarr.__version__.split(".")) >= (3, 1)
    assert "level" in inspect.signature(tifffile.TiffPageSeries.aszarr).parameters
    assert "selection" in inspect.signature(tifffile.imread).parameters


def test_tifffile_ome_frames_use_keyframe_metadata_and_sceneio_refuses_deliberately(
    tmp_path,
):
    path = tmp_path / "four-dimensional.ome.tif"
    values = np.arange(2 * 3 * 16 * 20, dtype=np.uint16).reshape(2, 3, 16, 20)
    tifffile.imwrite(
        path,
        values,
        ome=True,
        photometric="minisblack",
        metadata={"axes": "TZYX"},
    )

    with tifffile.TiffFile(path) as provider:
        assert provider.is_ome
        assert provider.series[0].axes == "TZYX"
        assert isinstance(provider.series[0].pages[0], tifffile.TiffPage)
        assert isinstance(provider.series[0].pages[1], tifffile.TiffFrame)
        frame = provider.series[0].pages[1]
        assert not hasattr(frame, "tags")
        assert hasattr(frame.keyframe, "tags")

    with pytest.raises(
        sceneio.FormatError,
        match="OME-XML and OME axes 'TZYX' are outside the bounded CV profile",
    ):
        sceneio.inspect_tiff_collection(path)
    with pytest.raises(
        sceneio.FormatError,
        match="OME-XML and OME axes 'TZYX' are outside the bounded CV profile",
    ):
        sceneio.read_tiff_collection(path)
    with pytest.raises(sceneio.FormatError, match="unsupported or ambiguous axes"):
        sceneio.inspect(path)


def test_pinned_public_ome_4d_fixture_reaches_the_same_deliberate_boundary():
    configured = os.environ.get("SCENEIO_OME_TIFF_FIXTURE")
    if not configured:
        pytest.skip("set SCENEIO_OME_TIFF_FIXTURE to the pinned public OME-TIFF")
    path = Path(configured)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == _OME_4D_SHA256

    with tifffile.TiffFile(path) as provider:
        assert provider.is_ome
        assert provider.series[0].axes == "TCZYX"
        assert len(provider.series[0].pages) == 105
        assert any(
            isinstance(page, tifffile.TiffFrame)
            for page in provider.series[0].pages
        )

    with pytest.raises(
        sceneio.FormatError,
        match="OME-XML and OME axes 'TCZYX' are outside the bounded CV profile",
    ):
        sceneio.inspect_tiff_collection(path)


def test_tifffile_subifd_base_aszarr_is_group_unless_level_is_selected(tmp_path):
    path = tmp_path / "pyramid.tif"
    full = np.arange(32 * 48, dtype=np.uint16).reshape(32, 48)
    reduced = full[::2, ::2].copy()
    with tifffile.TiffWriter(path) as writer:
        writer.write(
            full,
            photometric="minisblack",
            metadata=None,
            tile=(16, 16),
            subifds=1,
        )
        writer.write(
            reduced,
            photometric="minisblack",
            metadata=None,
            tile=(16, 16),
            subfiletype=1,
        )

    with tifffile.TiffFile(path) as provider:
        group_store = provider.series[0].levels[0].aszarr()
        try:
            assert isinstance(zarr.open(group_store, mode="r"), zarr.Group)
        finally:
            group_store.close()

        array_store = provider.series[0].aszarr(level=0)
        try:
            selected = zarr.open(array_store, mode="r")
            assert isinstance(selected, zarr.Array)
            np.testing.assert_array_equal(selected[3:19, 7:31], full[3:19, 7:31])
        finally:
            array_store.close()
