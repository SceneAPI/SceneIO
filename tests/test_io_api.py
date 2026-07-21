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


def test_splat_roundtrips_ply_to_spz(tmp_path):
    # end-to-end through the public API: PLY -> GaussianCloud -> SPZ -> back.
    gsply = pytest.importorskip("gsply")
    rng = np.random.default_rng(0)
    n = 5
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
    out = tmp_path / "out.spz"
    sceneio.write(cloud, out)  # dispatch by .spz extension
    assert sceneio.detect(out) == "spz"
    back = sceneio.read(out)
    assert isinstance(back, sceneio.GaussianCloud)
    assert back.num_gaussians == n and back.sh_degree == cloud.sh_degree


def test_write_unsupported_extension_raises(tmp_path):
    with pytest.raises(sceneio.FormatError, match="no writer"):
        sceneio.write(np.zeros((2, 2), np.float32), tmp_path / "x.bogus")


def test_write_to_read_only_format_raises(tmp_path):
    # a codec with write=None rejects an explicit write() cleanly.
    from sceneio.io import registry

    ro = registry.Codec(
        "ro_test", (".rotest",), lambda p: None, None, record=None, datatype="depth_map"
    )
    registry.REGISTRY["ro_test"] = ro
    try:
        with pytest.raises(sceneio.FormatError, match="read-only"):
            sceneio.write(object(), tmp_path / "x.rotest", format="ro_test")
    finally:
        del registry.REGISTRY["ro_test"]


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
