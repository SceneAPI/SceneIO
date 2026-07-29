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

import gc
import json
import os
import shutil
import struct
import subprocess
import sys
import textwrap

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


@pytest.fixture(scope="module")
def multi_camera_ref(tmp_path_factory):
    opts = pycolmap.SyntheticDatasetOptions()
    opts.num_rigs = 1
    opts.num_cameras_per_rig = 2
    opts.num_frames_per_rig = 3
    opts.num_points3D = 20
    rec = pycolmap.synthesize_dataset(opts)
    base = tmp_path_factory.mktemp("colmap_multi_camera")
    binary = base / "binary"
    text = base / "text"
    binary.mkdir()
    text.mkdir()
    rec.write_binary(str(binary))
    rec.write_text(str(text))
    return rec, binary, text


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
    # Read pycolmap's modern five-file model, write ours, compare every file.
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    out = str(tmp_path)
    _core.write_colmap_sparse(R, out)
    assert R.has_rig_frame_model
    assert sorted(os.listdir(out)) == [
        "cameras.bin",
        "frames.bin",
        "images.bin",
        "points3D.bin",
        "rigs.bin",
    ]
    for f in ("rigs.bin", "cameras.bin", "frames.bin", "images.bin", "points3D.bin"):
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


def test_modern_rig_frame_parity(ref):
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    rig_ids = np.asarray(R.rig_ids)
    frame_ids = np.asarray(R.frame_ids)
    assert R.has_rig_frame_model
    assert R.num_rigs == rec.num_rigs()
    assert R.num_frames == rec.num_reg_frames()
    np.testing.assert_array_equal(rig_ids, sorted(rec.rigs))
    np.testing.assert_array_equal(frame_ids, sorted(rec.reg_frame_ids()))
    np.testing.assert_array_equal(
        R.rig_reference_sensor_types, np.zeros(R.num_rigs, dtype=np.int32)
    )
    np.testing.assert_array_equal(
        R.rig_reference_sensor_ids, rig_ids.astype(np.uint32)
    )
    np.testing.assert_array_equal(R.rig_sensor_offsets, np.zeros(R.num_rigs + 1))

    offsets = np.asarray(R.frame_data_offsets)
    np.testing.assert_array_equal(np.diff(offsets), np.ones(R.num_frames))
    np.testing.assert_array_equal(
        R.frame_sensor_types, np.zeros(R.num_frames, dtype=np.int32)
    )
    np.testing.assert_array_equal(R.frame_sensor_ids, R.frame_rig_ids)
    np.testing.assert_array_equal(R.frame_data_ids, frame_ids)

    for index, frame_id in enumerate(frame_ids):
        frame = rec.frames[int(frame_id)]
        xyzw = np.asarray(frame.rig_from_world.rotation.quat)
        np.testing.assert_array_equal(
            np.asarray(R.frame_quaternions)[index],
            xyzw[[3, 0, 1, 2]],
        )
        np.testing.assert_array_equal(
            np.asarray(R.frame_translations)[index],
            np.asarray(frame.rig_from_world.translation),
        )


def test_modern_partial_image_keeps_its_frame_and_rig(ref):
    _, directory = ref
    full = _core.read_colmap_sparse(directory)
    full_frame_ids = np.asarray(full.frame_ids)
    full_rig_ids = np.asarray(full.rig_ids)
    for image_id in np.asarray(full.image_ids):
        partial = _core.read_colmap_sparse_image(directory, int(image_id))
        assert partial.has_rig_frame_model
        assert partial.num_rigs == partial.num_frames == 1
        assert int(image_id) in np.asarray(partial.frame_data_ids)

        frame_id = int(np.asarray(partial.frame_ids)[0])
        frame_row = int(np.flatnonzero(full_frame_ids == frame_id)[0])
        rig_id = int(np.asarray(partial.frame_rig_ids)[0])
        rig_row = int(np.flatnonzero(full_rig_ids == rig_id)[0])
        np.testing.assert_array_equal(
            partial.frame_quaternions,
            np.asarray(full.frame_quaternions)[frame_row : frame_row + 1],
        )
        np.testing.assert_array_equal(
            partial.frame_translations,
            np.asarray(full.frame_translations)[frame_row : frame_row + 1],
        )
        np.testing.assert_array_equal(
            partial.rig_reference_sensor_types,
            np.asarray(full.rig_reference_sensor_types)[rig_row : rig_row + 1],
        )
        np.testing.assert_array_equal(
            partial.rig_reference_sensor_ids,
            np.asarray(full.rig_reference_sensor_ids)[rig_row : rig_row + 1],
        )


def test_legacy_three_file_inventory_is_preserved(ref, tmp_path):
    _, modern = ref
    source = tmp_path / "legacy-source"
    source.mkdir()
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        shutil.copyfile(os.path.join(modern, name), source / name)

    R = _core.read_colmap_sparse(str(source))
    assert not R.has_rig_frame_model
    assert R.num_rigs == R.num_frames == 0
    out = tmp_path / "legacy-out"
    out.mkdir()
    _core.write_colmap_sparse(R, str(out))
    assert sorted(path.name for path in out.iterdir()) == [
        "cameras.bin",
        "images.bin",
        "points3D.bin",
    ]
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        assert (source / name).read_bytes() == (out / name).read_bytes()

    invalid_image = _core.read_colmap_sparse(str(source))
    np.asarray(invalid_image.image_ids)[0] = 2**32 - 1
    invalid_image_out = tmp_path / "legacy-invalid-image"
    invalid_image_out.mkdir()
    with pytest.raises(ValueError, match="invalid sentinel"):
        _core.write_colmap_sparse(invalid_image, str(invalid_image_out))

    invalid_point = _core.read_colmap_sparse(str(source))
    np.asarray(invalid_point.point3D_ids)[0] = 2**64 - 1
    invalid_point_out = tmp_path / "legacy-invalid-point"
    invalid_point_out.mkdir()
    with pytest.raises(ValueError, match="invalid sentinel"):
        _core.write_colmap_sparse(invalid_point, str(invalid_point_out))


@pytest.mark.parametrize("missing", ["rigs.bin", "frames.bin"])
def test_modern_layout_requires_both_rig_frame_files(ref, tmp_path, missing):
    _, modern = ref
    source = tmp_path / missing
    source.mkdir()
    for name in ("rigs.bin", "cameras.bin", "frames.bin", "images.bin", "points3D.bin"):
        if name != missing:
            shutil.copyfile(os.path.join(modern, name), source / name)
    with pytest.raises(ValueError, match="requires both"):
        _core.read_colmap_sparse(str(source))


def test_multi_sensor_rig_and_frame_binary_roundtrip(tmp_path):
    source = tmp_path / "multi-source"
    source.mkdir()
    pose = (0.5, -0.5, 0.5, -0.5, 1.25, -2.5, 3.75)
    rigs = bytearray(struct.pack("<QIIiI", 1, 7, 3, 0, 1))
    rigs += struct.pack("<iIB7d", 0, 2, 1, *pose)
    rigs += struct.pack("<iIB", 1, 9, 0)
    frame_pose = (1.0, 0.0, 0.0, 0.0, 4.0, 5.0, 6.0)
    frames = bytearray(struct.pack("<QII7dI", 1, 11, 7, *frame_pose, 2))
    frames += struct.pack("<iIQ", 0, 1, 100)
    frames += struct.pack("<iIQ", 1, 9, 200)
    (source / "rigs.bin").write_bytes(rigs)
    (source / "frames.bin").write_bytes(frames)
    cameras = bytearray(struct.pack("<Q", 2))
    for camera_id in (1, 2):
        cameras += struct.pack(
            "<IiQQ3d", camera_id, 0, 640, 480, 500.0, 320.0, 240.0
        )
    images = bytearray(struct.pack("<Q", 1))
    images += struct.pack(
        "<I7dI", 100, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1
    )
    images += b"frame.png\0" + struct.pack("<Q", 0)
    (source / "cameras.bin").write_bytes(cameras)
    (source / "images.bin").write_bytes(images)
    (source / "points3D.bin").write_bytes(struct.pack("<Q", 0))

    R = _core.read_colmap_sparse(str(source))
    assert R.has_rig_frame_model
    np.testing.assert_array_equal(R.rig_ids, [7])
    np.testing.assert_array_equal(R.rig_reference_sensor_types, [0])
    np.testing.assert_array_equal(R.rig_reference_sensor_ids, [1])
    np.testing.assert_array_equal(R.rig_sensor_offsets, [0, 2])
    np.testing.assert_array_equal(R.rig_sensor_types, [0, 1])
    np.testing.assert_array_equal(R.rig_sensor_ids, [2, 9])
    np.testing.assert_array_equal(R.rig_sensor_has_pose, [1, 0])
    np.testing.assert_array_equal(np.asarray(R.rig_sensor_quaternions)[0], pose[:4])
    np.testing.assert_array_equal(np.asarray(R.rig_sensor_translations)[0], pose[4:])
    np.testing.assert_array_equal(
        np.asarray(R.rig_sensor_quaternions)[1], [1.0, 0.0, 0.0, 0.0]
    )
    np.testing.assert_array_equal(R.frame_ids, [11])
    np.testing.assert_array_equal(R.frame_rig_ids, [7])
    np.testing.assert_array_equal(R.frame_data_offsets, [0, 2])
    np.testing.assert_array_equal(R.frame_sensor_types, [0, 1])
    np.testing.assert_array_equal(R.frame_sensor_ids, [1, 9])
    np.testing.assert_array_equal(R.frame_data_ids, [100, 200])

    out = tmp_path / "multi-out"
    out.mkdir()
    _core.write_colmap_sparse(R, str(out))
    for name in ("rigs.bin", "cameras.bin", "frames.bin", "images.bin", "points3D.bin"):
        assert (source / name).read_bytes() == (out / name).read_bytes()
    oracle = pycolmap.Reconstruction(str(out))
    assert oracle.num_rigs() == oracle.num_reg_frames() == 1
    assert oracle.num_cameras() == 2
    assert oracle.num_images() == 1


def test_multi_camera_partial_is_a_writable_oracle_model(
    multi_camera_ref, tmp_path
):
    _, binary, _ = multi_camera_ref
    full = _core.read_colmap_sparse(str(binary))
    assert full.num_cameras == 2
    image_id = int(np.asarray(full.image_ids)[0])
    partial = _core.read_colmap_sparse_image(str(binary), image_id)
    assert partial.num_images == 1
    assert partial.num_frames == partial.num_rigs == 1
    assert partial.num_cameras == 2
    np.testing.assert_array_equal(
        np.diff(partial.frame_data_offsets), [1]
    )
    output = tmp_path / "multi-camera-partial"
    output.mkdir()
    _core.write_colmap_sparse(partial, str(output))
    oracle = pycolmap.Reconstruction(str(output))
    assert oracle.num_images() == 1
    assert oracle.num_cameras() == 2
    assert oracle.num_reg_frames() == 1

    malformed = tmp_path / "multi-camera-malformed"
    shutil.copytree(binary, malformed)
    frames = bytearray((malformed / "frames.bin").read_bytes())
    frame_count = struct.unpack_from("<Q", frames)[0]
    offset = 8
    changed = False
    for _ in range(frame_count):
        data_count = struct.unpack_from("<I", frames, offset + 64)[0]
        offset += 68
        for _ in range(data_count):
            sensor_type, _, data_id = struct.unpack_from(
                "<iIQ", frames, offset
            )
            if sensor_type == 0 and data_id == image_id:
                struct.pack_into("<I", frames, offset + 4, 999_999)
                changed = True
            offset += 16
    assert changed
    (malformed / "frames.bin").write_bytes(frames)
    with pytest.raises(ValueError, match="does not belong"):
        _core.read_colmap_sparse_image(str(malformed), image_id)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("frame_rig_ids", 2**32 - 2, "missing rig"),
        (
            "rig_reference_sensor_ids",
            2**32 - 2,
            "missing camera",
        ),
        ("frame_sensor_ids", 2**32 - 2, "does not belong"),
        ("frame_data_ids", 2**32 - 2, "missing image"),
    ],
)
def test_writer_rejects_invalid_modern_associations(
    multi_camera_ref, tmp_path, field, value, match
):
    _, binary, _ = multi_camera_ref
    reconstruction = _core.read_colmap_sparse(str(binary))
    values = np.asarray(getattr(reconstruction, field))
    values[0] = value
    output = tmp_path / field
    output.mkdir()
    with pytest.raises(ValueError, match=match):
        _core.write_colmap_sparse(reconstruction, str(output))

    if field == "frame_rig_ids":
        invalid = _core.read_colmap_sparse(str(binary))
        np.asarray(invalid.rig_ids)[0] = 2**32 - 1
        np.asarray(invalid.frame_rig_ids)[0] = 2**32 - 1
        sentinel_output = tmp_path / "invalid-sentinel"
        sentinel_output.mkdir()
        with pytest.raises(ValueError, match="invalid sentinel"):
            _core.write_colmap_sparse(invalid, str(sentinel_output))


def test_modern_zero_count_inventory_roundtrip(tmp_path):
    source = tmp_path / "modern-empty"
    source.mkdir()
    for name in (
        "rigs.bin",
        "cameras.bin",
        "frames.bin",
        "images.bin",
        "points3D.bin",
    ):
        (source / name).write_bytes(struct.pack("<Q", 0))
    reconstruction = _core.read_colmap_sparse(str(source))
    assert reconstruction.has_rig_frame_model
    assert reconstruction.num_rigs == reconstruction.num_frames == 0
    output = tmp_path / "modern-empty-output"
    output.mkdir()
    _core.write_colmap_sparse(reconstruction, str(output))
    assert sorted(path.name for path in output.iterdir()) == [
        "cameras.bin",
        "frames.bin",
        "images.bin",
        "points3D.bin",
        "rigs.bin",
    ]
    for name in (
        "rigs.bin",
        "cameras.bin",
        "frames.bin",
        "images.bin",
        "points3D.bin",
    ):
        assert (output / name).read_bytes() == struct.pack("<Q", 0)


def test_legacy_writer_refuses_stale_modern_pair(ref, tmp_path):
    _, modern = ref
    source = tmp_path / "legacy-with-stale-pair"
    source.mkdir()
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        shutil.copyfile(os.path.join(modern, name), source / name)
    reconstruction = _core.read_colmap_sparse(str(source))
    (source / "rigs.bin").write_bytes(struct.pack("<Q", 0))
    (source / "frames.bin").write_bytes(struct.pack("<Q", 0))
    with pytest.raises(ValueError, match="stale"):
        _core.write_colmap_sparse(reconstruction, str(source))


@pytest.mark.parametrize(
    ("writer", "format_name"),
    [
        (_core.write_bundler, "Bundler"),
        (_core.write_bal, "BAL"),
        (_core.write_nvm, "NVM"),
        (_core.write_openmvg, "OpenMVG"),
    ],
)
def test_other_reconstruction_formats_refuse_rig_frame_loss(
    ref, writer, format_name
):
    _, directory = ref
    reconstruction = _core.read_colmap_sparse(directory)
    with pytest.raises(
        ValueError,
        match=rf"{format_name}: cannot represent COLMAP rig/frame",
    ):
        writer(reconstruction)


@pytest.mark.parametrize(
    "sidecar",
    [
        "markers.bin",
        "marker_projections.bin",
        "charuco_boards.bin",
        "charuco_calibrations.bin",
        "time_frames.bin",
        "image_times.bin",
        "points3D_frames.bin",
        "markers.txt",
        "marker_projections.txt",
        "charuco_boards.txt",
        "charuco_calibrations.txt",
        "time_frames.txt",
        "image_times.txt",
        "points3D_frames.txt",
    ],
)
def test_unrepresented_binary_sidecars_are_not_silently_ignored(
    ref, tmp_path, sidecar
):
    _, directory = ref
    reconstruction = _core.read_colmap_sparse(directory)
    target = tmp_path / sidecar
    target.mkdir()
    (target / sidecar).write_bytes(b"extension sentinel")
    with pytest.raises(ValueError, match=sidecar):
        _core.write_colmap_sparse(reconstruction, str(target))

    for name in (
        "rigs.bin",
        "cameras.bin",
        "frames.bin",
        "images.bin",
        "points3D.bin",
    ):
        shutil.copyfile(os.path.join(directory, name), target / name)
    with pytest.raises(ValueError, match=sidecar):
        _core.read_colmap_sparse(str(target))


def test_zero_copy_views_and_torch(ref):
    rec, d = ref
    R = _core.read_colmap_sparse(d)
    xyz = R.xyz  # a zero-copy view; R is kept alive by reference_internal
    assert isinstance(xyz, np.ndarray) and xyz.shape == (R.num_points3D, 3)
    torch = pytest.importorskip("torch")
    t = torch.from_dlpack(R.xyz)
    assert np.array_equal(t.numpy(), np.asarray(R.xyz))


def test_rig_frame_views_outlive_the_reconstruction(ref):
    _, directory = ref
    reconstruction = _core.read_colmap_sparse(directory)
    rig_ids = reconstruction.rig_ids
    frame_ids = reconstruction.frame_ids
    frame_poses = reconstruction.frame_quaternions
    expected = (
        np.asarray(rig_ids).copy(),
        np.asarray(frame_ids).copy(),
        np.asarray(frame_poses).copy(),
    )
    del reconstruction
    gc.collect()
    _ = [bytearray(4096) for _ in range(256)]
    np.testing.assert_array_equal(rig_ids, expected[0])
    np.testing.assert_array_equal(frame_ids, expected[1])
    np.testing.assert_array_equal(frame_poses, expected[2])


def test_binary_writer_rss_does_not_scale_with_encoded_size():
    script = textwrap.dedent(
        """
        import gc
        import json
        import psutil
        import sys
        import tempfile
        import threading
        import time

        from sceneio import _core

        points = int(sys.argv[1])
        payload = (
            b"NVM_V3\\n1\\na.jpg 800 1 0 0 0 0 0 0 0 0\\n"
            + str(points).encode()
            + b"\\n"
            + b"1.5 -2.5 3.5 10 20 30 0\\n" * points
            + b"0\\n"
        )
        record = _core.read_nvm(payload)
        del payload
        gc.collect()
        process = psutil.Process()
        baseline = process.memory_info().rss
        peak = baseline
        stop = threading.Event()

        def sample():
            global peak
            while not stop.is_set():
                peak = max(peak, process.memory_info().rss)
                time.sleep(0.0005)

        sampler = threading.Thread(target=sample)
        sampler.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                _core.write_colmap_sparse(record, directory)
                encoded = sum(
                    entry.stat().st_size
                    for entry in __import__("pathlib").Path(directory).iterdir()
                )
        finally:
            stop.set()
            sampler.join()
        peak = max(peak, process.memory_info().rss)
        print(json.dumps({"encoded": encoded, "delta": peak - baseline}))
        """
    )

    def measure(points):
        result = subprocess.run(
            [sys.executable, "-c", script, str(points)],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    small = measure(100_000)
    large = measure(600_000)
    assert large["encoded"] > small["encoded"] * 5
    assert large["delta"] < large["encoded"] * 0.5
    assert large["delta"] <= small["delta"] + 8 * 1024 * 1024


@pytest.mark.parametrize(
    ("filename", "payload", "match"),
    [
        ("cameras.bin", struct.pack("<Q", 2**64 - 1), "oversized cameras"),
        ("images.bin", struct.pack("<Q", 2**64 - 1), "oversized images"),
        ("points3D.bin", struct.pack("<Q", 2**64 - 1), "oversized points3D"),
        ("cameras.bin", struct.pack("<Q", 0) + b"x", "trailing bytes"),
        ("images.bin", struct.pack("<Q", 0) + b"x", "trailing bytes"),
        ("points3D.bin", struct.pack("<Q", 0) + b"x", "trailing bytes"),
    ],
)
def test_full_reader_rejects_impossible_counts_and_trailing_data(
    tmp_path, filename, payload, match
):
    source = tmp_path / filename.replace(".", "-")
    source.mkdir()
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        (source / name).write_bytes(struct.pack("<Q", 0))
    (source / filename).write_bytes(payload)
    with pytest.raises(ValueError, match=match):
        _core.read_colmap_sparse(str(source))

    if filename == "cameras.bin" and match == "oversized cameras":
        camera = struct.pack(
            "<IiQQ3d", 1, 0, 640, 480, 500.0, 320.0, 240.0
        )
        image = struct.pack(
            "<I7dI", 1, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1
        )
        image += b"frame.png\0" + struct.pack("<Q", 0)

        bad_images = tmp_path / "partial-bad-images"
        bad_images.mkdir()
        (bad_images / "cameras.bin").write_bytes(
            struct.pack("<Q", 1) + camera
        )
        (bad_images / "images.bin").write_bytes(
            struct.pack("<Q", 2**64 - 1) + image
        )
        (bad_images / "points3D.bin").write_bytes(struct.pack("<Q", 0))
        with pytest.raises(ValueError, match="oversized images"):
            _core.read_colmap_sparse_image(str(bad_images), 1)

        bad_cameras = tmp_path / "partial-bad-cameras"
        bad_cameras.mkdir()
        (bad_cameras / "cameras.bin").write_bytes(
            struct.pack("<Q", 2**64 - 1) + camera
        )
        (bad_cameras / "images.bin").write_bytes(
            struct.pack("<Q", 1) + image
        )
        (bad_cameras / "points3D.bin").write_bytes(struct.pack("<Q", 0))
        with pytest.raises(ValueError, match="oversized cameras"):
            _core.read_colmap_sparse_image(str(bad_cameras), 1)

        invalid_payloads = (
            (
                "camera",
                struct.pack("<QIiQQ3d", 1, 2**32 - 1, 0, 640, 480,
                            500.0, 320.0, 240.0),
                struct.pack("<Q", 0),
                struct.pack("<Q", 0),
            ),
            (
                "image",
                struct.pack("<Q", 1) + camera,
                struct.pack("<Q", 1)
                + struct.pack(
                    "<I7dI",
                    2**32 - 1,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1,
                )
                + b"frame.png\0"
                + struct.pack("<Q", 0),
                struct.pack("<Q", 0),
            ),
            (
                "point",
                struct.pack("<Q", 0),
                struct.pack("<Q", 0),
                struct.pack(
                    "<QQ3d3BdQ",
                    1,
                    2**64 - 1,
                    1.0,
                    2.0,
                    3.0,
                    10,
                    20,
                    30,
                    0.5,
                    0,
                ),
            ),
        )
        for label, cameras_payload, images_payload, points_payload in (
            invalid_payloads
        ):
            invalid = tmp_path / f"legacy-invalid-{label}-read"
            invalid.mkdir()
            (invalid / "cameras.bin").write_bytes(cameras_payload)
            (invalid / "images.bin").write_bytes(images_payload)
            (invalid / "points3D.bin").write_bytes(points_payload)
            with pytest.raises(ValueError, match="invalid sentinel"):
                _core.read_colmap_sparse(str(invalid))


@pytest.mark.parametrize(
    ("rigs", "frames", "match"),
    [
        (struct.pack("<Q", 1), struct.pack("<Q", 0), "oversized rigs"),
        (
            struct.pack("<QIIiI", 1, 7, 2, 0, 1)
            + struct.pack("<iIB", 0, 2, 2),
            struct.pack("<Q", 0),
            "pose flag",
        ),
        (
            struct.pack("<Q", 0) + b"x",
            struct.pack("<Q", 0),
            "trailing bytes",
        ),
        (
            struct.pack("<Q", 0),
            struct.pack("<Q", 0) + b"x",
            "trailing bytes",
        ),
    ],
)
def test_malformed_modern_binary_metadata_is_rejected(
    tmp_path, rigs, frames, match
):
    source = tmp_path / f"bad-modern-{len(rigs)}-{len(frames)}"
    source.mkdir()
    (source / "rigs.bin").write_bytes(rigs)
    (source / "frames.bin").write_bytes(frames)
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        (source / name).write_bytes(struct.pack("<Q", 0))
    with pytest.raises(ValueError, match=match):
        _core.read_colmap_sparse(str(source))
