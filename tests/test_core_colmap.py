"""Phase 1 parity suite for the COLMAP binary sparse-model codec.

Oracle: pycolmap (BSD). We generate a synthetic reconstruction, write it
with pycolmap, then check our reader/writer against it four ways
(io_implementation_plan.md §6):

  * counts + field parity (cameras, points, names),
  * **byte-identity** of our writer vs pycolmap's .bin (the strongest check),
  * the pose convention pin (our WXYZ, world->camera quaternion rebuilds
    pycolmap's pose matrix), and
  * zero-copy ndarray views + torch interop.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover
    _core = None

pycolmap = pytest.importorskip("pycolmap")
pytestmark = pytest.mark.skipif(_core is None, reason="sceneio._core not built")


@pytest.fixture(scope="module")
def ref(tmp_path_factory):
    opts = pycolmap.SyntheticDatasetOptions()
    opts.num_points3D = 40
    rec = pycolmap.synthesize_dataset(opts)
    d = str(tmp_path_factory.mktemp("colmap_ref"))
    rec.write_binary(d)
    return rec, d


def _quat_wxyz_to_R(q):
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def test_counts_match(ref):
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (
        rec.num_cameras(),
        rec.num_images(),
        rec.num_points3D(),
    )


def test_writer_byte_identical_to_pycolmap(ref, tmp_path):
    # read pycolmap's bytes, write ours, compare byte-for-byte.
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    out = str(tmp_path)
    _core.write_colmap_sparse(R, out)
    for f in ("cameras.bin", "images.bin", "points3D.bin"):
        a = open(os.path.join(d, f), "rb").read()
        b = open(os.path.join(out, f), "rb").read()
        assert a == b, f"{f} is not byte-identical"


def test_pycolmap_reads_our_output(ref, tmp_path):
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    out = str(tmp_path)
    _core.write_colmap_sparse(R, out)
    rec2 = pycolmap.Reconstruction(out)
    assert rec2.num_images() == rec.num_images()
    assert rec2.num_points3D() == rec.num_points3D()


def test_camera_parity(ref):
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    ours = {c.id: c for c in R.cameras}
    for cid, cam in rec.cameras.items():
        c = ours[int(cid)]
        assert (c.width, c.height) == (cam.width, cam.height)
        assert c.model == cam.model_name
        np.testing.assert_array_equal(np.asarray(c.params), np.asarray(cam.params))


def test_points_parity(ref):
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    xyz, rgb, err = np.asarray(R.xyz), np.asarray(R.rgb), np.asarray(R.errors)
    row = {int(i): k for k, i in enumerate(np.asarray(R.point3D_ids))}
    assert xyz.dtype == np.float64 and rgb.dtype == np.uint8
    for pid, p in rec.points3D.items():
        k = row[int(pid)]
        np.testing.assert_array_equal(xyz[k], np.asarray(p.xyz))
        np.testing.assert_array_equal(rgb[k], np.asarray(p.color, dtype=np.uint8))
        assert err[k] == p.error


def test_pose_convention_pin(ref):
    # our quaternions are WXYZ and world->camera: rebuilding R|t must match
    # pycolmap's cam_from_world pose matrix exactly.
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    quats, trans = np.asarray(R.quaternions), np.asarray(R.translations)
    names = R.image_names
    row = {int(i): k for k, i in enumerate(np.asarray(R.image_ids))}
    for iid, im in rec.images.items():
        k = row[int(iid)]
        M = np.asarray(im.cam_from_world().matrix())[:3]  # 3x4 [R|t]
        np.testing.assert_allclose(_quat_wxyz_to_R(quats[k]), M[:, :3], atol=1e-9)
        np.testing.assert_allclose(trans[k], M[:, 3], atol=1e-12)
        assert im.name == names[k]


def test_zero_copy_views_and_torch(ref):
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    xyz = R.xyz  # a zero-copy view; R is kept alive by reference_internal
    assert isinstance(xyz, np.ndarray) and xyz.shape == (R.num_points3D, 3)
    torch = pytest.importorskip("torch")
    t = torch.from_dlpack(R.xyz)
    assert np.array_equal(t.numpy(), np.asarray(R.xyz))
