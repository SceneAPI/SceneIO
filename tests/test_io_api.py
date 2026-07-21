"""The public sceneio.io API: registry, format detection, read/write dispatch,
and error normalization. Codec-specific parity lives under tests/codecs/.
"""

from __future__ import annotations

import numpy as np
import pytest

import sceneio


def test_registry_has_builtins():
    assert {"pfm", "colmap_sparse", "gaussian_ply", "spz"} <= set(sceneio.codecs())


def test_pfm_roundtrip_via_public_api(tmp_path):
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    p = tmp_path / "d.pfm"
    sceneio.write(arr, p)  # dispatch by .pfm extension
    assert sceneio.detect(p) == "pfm"
    np.testing.assert_array_equal(sceneio.read(p), arr)


def test_explicit_format_overrides_detection(tmp_path):
    arr = np.zeros((2, 2), np.float32)
    p = tmp_path / "noext"
    sceneio.write(arr, p, format="pfm")
    np.testing.assert_array_equal(sceneio.read(p, format="pfm"), arr)


def test_unknown_format_raises(tmp_path):
    p = tmp_path / "x.unknown"
    p.write_bytes(b"junk")
    with pytest.raises(sceneio.FormatError):
        sceneio.detect(p)


def test_read_only_codec_rejects_write(tmp_path):
    gsply = pytest.importorskip("gsply")
    rng = np.random.default_rng(0)
    n = 3
    p = tmp_path / "g.ply"
    gsply.plywrite(
        str(p),
        rng.standard_normal((n, 3)).astype(np.float32),
        scales=rng.standard_normal((n, 3)).astype(np.float32),
        quats=rng.standard_normal((n, 4)).astype(np.float32),
        opacities=rng.standard_normal(n).astype(np.float32),
        sh0=rng.standard_normal((n, 3)).astype(np.float32),
    )
    cloud = sceneio.read(p)
    with pytest.raises(sceneio.FormatError, match=r"no writer|read-only"):
        sceneio.write(cloud, tmp_path / "out.spz")


def test_conventions_are_metadata(tmp_path):
    gsply = pytest.importorskip("gsply")
    rng = np.random.default_rng(0)
    n = 3
    p = tmp_path / "g.ply"
    gsply.plywrite(
        str(p),
        rng.standard_normal((n, 3)).astype(np.float32),
        scales=rng.standard_normal((n, 3)).astype(np.float32),
        quats=rng.standard_normal((n, 4)).astype(np.float32),
        opacities=rng.standard_normal(n).astype(np.float32),
        sh0=rng.standard_normal((n, 3)).astype(np.float32),
    )
    g = sceneio.read(p)
    assert isinstance(g, sceneio.GaussianCloud)
    assert (g.quaternion_order, g.scale_space, g.opacity_space, g.sh_layout) == (
        "wxyz",
        "log",
        "logit",
        "channel_grouped",
    )


def test_colmap_directory_detected_and_read(tmp_path):
    pycolmap = pytest.importorskip("pycolmap")
    opts = pycolmap.SyntheticDatasetOptions()
    opts.num_points3D = 12
    rec = pycolmap.synthesize_dataset(opts)
    d = tmp_path / "sparse"
    d.mkdir()
    rec.write_binary(str(d))
    assert sceneio.detect(d) == "colmap_sparse"
    R = sceneio.read(d)
    assert isinstance(R, sceneio.Reconstruction)
    assert R.num_points3D == rec.num_points3D()
    assert R.quaternion_order == "wxyz" and R.pose_convention == "world_to_camera"
