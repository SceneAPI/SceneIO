"""The public sceneio.io API: registry, format detection, read/write dispatch,
and error normalization. Codec-specific parity lives under tests/codecs/.
"""

from __future__ import annotations

import numpy as np
import pytest

import sceneio
from sceneio import _core


def test_registry_has_builtins():
    assert {
        "pfm",
        "colmap_sparse",
        "gaussian_ply",
        "sog",
        "ksplat",
        "spz",
        "transforms_json",
        "tum",
        "kitti",
        "npy",
        "npz",
        "netpbm",
    } <= set(sceneio.codecs())


def test_npy_roundtrip_via_public_api(tmp_path):
    arr = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    p = tmp_path / "a.npy"
    sceneio.write(arr, p)  # dispatch by .npy extension
    assert sceneio.detect(p) == "npy"
    np.testing.assert_array_equal(sceneio.read(p), arr)


def test_npy_detected_by_magic(tmp_path):
    p = tmp_path / "noext"
    sceneio.write(np.zeros(3, np.float32), p, format="npy")  # extensionless -> magic sniff
    assert sceneio.detect(p) == "npy"


def test_npz_roundtrip_via_public_api(tmp_path):
    arrays = {"x": np.arange(6, dtype=np.int16).reshape(2, 3), "y": np.ones(4, np.uint8)}
    p = tmp_path / "a.npz"
    sceneio.write(arrays, p)  # a plain {name: array} dict -> TensorDict
    td = sceneio.read(p)
    assert isinstance(td, sceneio.TensorDict) and list(td.keys()) == ["x", "y"]
    np.testing.assert_array_equal(np.asarray(td["x"]), arrays["x"])


def test_safetensors_roundtrip_via_public_api(tmp_path):
    arrays = {
        "x": np.arange(12, dtype=np.float32).reshape(3, 4),
        "y": np.arange(5, dtype=np.uint16),
    }
    path = tmp_path / "weights.safetensors"
    sceneio.write(arrays, path)
    assert sceneio.detect(path) == "safetensors"
    actual = sceneio.read(path)
    assert isinstance(actual, sceneio.TensorDict)
    for name, expected in arrays.items():
        np.testing.assert_array_equal(actual[name], expected)
        assert not actual[name].flags.writeable


def test_netpbm_roundtrip_via_public_api(tmp_path):
    p = tmp_path / "a.ppm"
    p.write_bytes(b"P6\n2 1\n255\n" + bytes([10, 20, 30, 40, 50, 60]))
    assert sceneio.detect(p) == "netpbm"
    img = sceneio.read(p)
    assert isinstance(img, sceneio.Image)
    out = tmp_path / "b.ppm"
    sceneio.write(img, out)  # dispatch by .ppm + record=Image
    np.testing.assert_array_equal(np.asarray(sceneio.read(out).pixels), np.asarray(img.pixels))


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
    # A codec with write=None rejects writes, while its optional third-party
    # inspection hook participates in the public metadata API.
    from sceneio.io import registry

    expected = sceneio.Inspection(
        "ro_test", "depth_map", 0, shape=(2, 3), dtype="float32"
    )
    ro = registry.Codec(
        "ro_test",
        (".rotest",),
        lambda p: None,
        None,
        record=None,
        datatype="depth_map",
        inspect=lambda path: expected,
    )
    registry.REGISTRY["ro_test"] = ro
    try:
        with pytest.raises(sceneio.FormatError, match="read-only"):
            sceneio.write(object(), tmp_path / "x.rotest", format="ro_test")
        assert sceneio.inspect(tmp_path / "x.rotest", format="ro_test") == expected
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


# --- E2E dispatch for the vendored image/point codecs -----------------------
# The per-codec parity suites (tests/codecs/) call _core.read_X/write_X DIRECTLY
# and never touch the public path: extension/magic detection -> registry lookup
# -> the mmap reader/file-sink writer adapters -> _core.*. These round-trip through
# the real sceneio.write/detect/read on disk, so a wrong reader/extension/magic in
# a registry entry is caught. Fidelity itself is the parity suites' job, so lossy
# codecs (jpeg/hdr) only assert the record shape/dtype survived the round-trip.
def _img_u8():
    a = np.random.default_rng(1).integers(0, 256, (6, 8, 3), dtype=np.uint8)
    return _core.image(a, color_space="srgb"), a


def _img_f32():
    a = (np.random.default_rng(2).random((6, 8, 3), dtype=np.float32) * 10.0).astype(np.float32)
    return _core.image(a, color_space="linear"), a


def _pc():
    a = (np.random.default_rng(3).random((20, 3), dtype=np.float32) * 100.0).astype(np.float32)
    return _core.point_cloud(a), a


def _mesh():
    positions = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        dtype=np.float32,
    )
    return (
        _core.mesh(
            positions,
            np.array([0, 4], np.uint64),
            np.array([0, 1, 2, 3], np.uint64),
        ),
        positions,
    )


@pytest.mark.parametrize(
    ("fmt", "ext", "build", "lossless"),
    [
        ("png", ".png", _img_u8, True),
        ("jpeg", ".jpg", _img_u8, False),  # lossy: dispatch-only
        ("hdr", ".hdr", _img_f32, False),  # lossy: dispatch-only
        ("exr", ".exr", _img_f32, True),
        ("webp", ".webp", _img_u8, True),  # write defaults to lossless
        ("ply", ".ply", _pc, True),
        ("pcd", ".pcd", _pc, True),
        ("las", ".las", _pc, None),
    ],
)
def test_image_point_codec_roundtrip_via_public_api(tmp_path, fmt, ext, build, lossless):
    record, original = build()
    p = tmp_path / f"x{ext}"
    sceneio.write(record, p)          # dispatch by extension -> the codec's writer
    assert sceneio.detect(p) == fmt   # extension/magic detection routes back to it
    back = sceneio.read(p)            # public read via the registry adapter
    if fmt == "las":
        assert isinstance(back, sceneio.PointCloud) and back.num_points == len(original)
        true = np.asarray(back.positions).astype(np.float64) + np.asarray(back.origin)
        np.testing.assert_allclose(true, original, atol=0.001)  # i32 grid, within scale/2
    elif fmt in {"ply", "pcd"}:
        assert isinstance(back, sceneio.PointCloud) and back.num_points == len(original)
        np.testing.assert_array_equal(back.positions, original)
    else:
        assert isinstance(back, sceneio.Image) and back.channels == 3
        px = np.asarray(back.pixels)
        assert px.shape == original.shape and px.dtype == original.dtype
        if lossless:
            np.testing.assert_array_equal(px, original)  # png/exr/webp are byte-exact


def test_mesh_ply_roundtrip_via_public_api(tmp_path):
    mesh, positions = _mesh()
    path = tmp_path / "mesh.ply"
    sceneio.write(mesh, path)
    assert sceneio.detect(path) == "ply_mesh"
    decoded = sceneio.read(path)
    assert isinstance(decoded, sceneio.Mesh)
    np.testing.assert_array_equal(decoded.positions, positions)
    np.testing.assert_array_equal(decoded.face_offsets, [0, 4])
    np.testing.assert_array_equal(decoded.face_indices, [0, 1, 2, 3])
