"""Parity suite for the transforms.json codec (NeRF / Instant-NGP / Nerfstudio).

Follows the reference pattern (io_implementation_plan.md §6): an independent,
self-contained pure-Python oracle (stdlib ``json`` + numpy 4x4 math), then
cross-impl parity, round-trip identity, a convention pin (the recorded
wxyz / camera_to_world / opengl tags), an intrinsics -> Camera check, and
numpy/torch interop. transforms.json RECORDS the source convention (poses are
camera-to-world in OpenGL axes) rather than canonicalizing it.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover - exercised only in a non-built tree
    _core = None

pytestmark = pytest.mark.skipif(
    _core is None,
    reason="sceneio._core not built (compiled-only package — build the extension first)",
)


# --- oracle: an independent pure-Python transforms.json codec --------------
def _quat_wxyz_to_matrix(q: np.ndarray) -> np.ndarray:
    w, x, y, z = np.asarray(q, float) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        float,
    )


def _matrix_to_quat_wxyz(R: np.ndarray) -> np.ndarray:
    """Shepperd's method, byte-for-byte the same branch selection as the C++."""
    m00, m01, m02 = R[0]
    m10, m11, m12 = R[1]
    m20, m21, m22 = R[2]
    tr = m00 + m11 + m22
    if tr > 0.0:
        s = np.sqrt(tr + 1.0) * 2.0
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = np.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = np.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = np.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    q = np.array([w, x, y, z], float)
    return q / np.linalg.norm(q)


def _oracle_parse_intr(src: dict, top: dict) -> dict:
    """Read intrinsics from ``src`` (a frame or the root), falling back to the
    root ``top``, into a COLMAP {model_id, params, w, h} dict."""

    def g(k, d=None):
        if src.get(k) is not None:
            return src[k]
        if top.get(k) is not None:
            return top[k]
        return d

    cm = g("camera_model", "")
    dist = any(g(k) is not None for k in ("k1", "k2", "p1", "p2"))
    if cm == "SIMPLE_PINHOLE":
        model = 0
    elif cm == "PINHOLE":
        model = 1
    elif cm == "OPENCV" or dist:
        model = 4
    elif g("fl_y") is not None:
        model = 1
    else:
        model = 0
    fx = float(g("fl_x", 0.0))
    fy = float(g("fl_y", fx))
    cx, cy = float(g("cx", 0.0)), float(g("cy", 0.0))
    w, h = int(g("w", 0)), int(g("h", 0))
    if model == 0:
        params = [fx, cx, cy]
    elif model == 1:
        params = [fx, fy, cx, cy]
    else:
        params = [fx, fy, cx, cy, *(float(g(k, 0.0)) for k in ("k1", "k2", "p1", "p2"))]
    return {"model_id": model, "params": params, "w": w, "h": h}


def oracle_read(data: bytes):
    """(quats (N,4) wxyz, trans (N,3), intrinsics) from transforms.json bytes."""
    d = json.loads(data)
    frames = d["frames"]
    top_has = ("fl_x" in d) or ("fl_y" in d)
    any_frame = any(("fl_x" in f) or ("fl_y" in f) for f in frames)
    shared = top_has and not any_frame
    quats, trans, cams, cam_idx = [], [], [], []
    if shared:
        cams.append(_oracle_parse_intr(d, d))
    for i, f in enumerate(frames):
        M = np.array(f["transform_matrix"], float)
        quats.append(_matrix_to_quat_wxyz(M[:3, :3]))
        trans.append(M[:3, 3])
        if any_frame:
            cams.append(_oracle_parse_intr(f, d))
            cam_idx.append(i)
        elif shared:
            cam_idx.append(0)
    intr = {"cameras": cams, "cam_idx": cam_idx}
    return np.array(quats, float), np.array(trans, float), intr


def _oracle_write_intr(o: dict, c: dict) -> None:
    p = c["params"]
    if c["model_id"] == 0:
        o.update(camera_model="SIMPLE_PINHOLE", fl_x=p[0], fl_y=p[0], cx=p[1], cy=p[2])
    elif c["model_id"] == 1:
        o.update(camera_model="PINHOLE", fl_x=p[0], fl_y=p[1], cx=p[2], cy=p[3])
    elif c["model_id"] == 4:
        o.update(
            camera_model="OPENCV",
            fl_x=p[0],
            fl_y=p[1],
            cx=p[2],
            cy=p[3],
            k1=p[4],
            k2=p[5],
            p1=p[6],
            p2=p[7],
        )
    else:
        raise ValueError(f"unrepresentable camera model {c['model_id']}")
    o.update(w=c["w"], h=c["h"])


def oracle_write(quats, trans, cameras=None, cam_idx=None, names=None) -> bytes:
    quats, trans = np.asarray(quats, float), np.asarray(trans, float)
    n = len(trans)
    cameras = cameras or []
    shared = len(cameras) == 1 and (not len(cam_idx or []) or all(c == 0 for c in cam_idx))
    per_frame = len(cameras) > 0 and not shared
    d: dict = {}
    if shared:
        _oracle_write_intr(d, cameras[0])
    frames = []
    for i in range(n):
        f: dict = {"file_path": names[i] if names is not None and i < len(names) else ""}
        M = np.eye(4)
        M[:3, :3] = _quat_wxyz_to_matrix(quats[i])
        M[:3, 3] = trans[i]
        f["transform_matrix"] = M.tolist()
        if per_frame:
            ci = cam_idx[i] if cam_idx and i < len(cam_idx) else 0
            _oracle_write_intr(f, cameras[ci])
        frames.append(f)
    d["frames"] = frames
    return json.dumps(d).encode()


# --- helpers ---------------------------------------------------------------
def _rot_from_rand(rng: np.random.Generator) -> np.ndarray:
    q = rng.standard_normal(4)
    return _quat_wxyz_to_matrix(q / np.linalg.norm(q))


def _intr_fields(model: str, fx, fy, cx, cy, w, h) -> dict:
    d = {"camera_model": model, "cx": cx, "cy": cy, "w": w, "h": h}
    if model == "SIMPLE_PINHOLE":
        d["fl_x"] = fx  # a single focal length -> COLMAP model 0
    else:
        d["fl_x"], d["fl_y"] = fx, fy
    if model == "OPENCV":
        d.update(k1=0.021, k2=-0.0034, p1=0.0011, p2=-0.0007)
    return d


def build_transforms(rng, model="PINHOLE", per_frame=False, n=4) -> bytes:
    frames = []
    for i in range(n):
        M = np.eye(4)
        M[:3, :3] = _rot_from_rand(rng)
        M[:3, 3] = rng.standard_normal(3) * 2.5
        f = {"file_path": f"images/frame_{i:04d}.png", "transform_matrix": M.tolist()}
        if per_frame:
            f.update(_intr_fields(model, 700.0 + i, 701.0 + i, 320.0 + i, 240.0 + i, 640, 480))
        frames.append(f)
    d: dict = {}
    if not per_frame:
        d.update(_intr_fields(model, 720.5, 721.25, 400.0, 300.0, 800, 600))
    d["frames"] = frames
    return json.dumps(d).encode()


def _quat_align(a, b):
    """Fold the quaternion double-cover: return b with per-row sign matched to a."""
    a, b = np.asarray(a, float).reshape(-1, 4), np.asarray(b, float).reshape(-1, 4)
    sign = np.sign(np.sum(a * b, axis=1, keepdims=True))
    sign[sign == 0] = 1.0
    return b * sign


def assert_quat_close(a, b, atol=1e-6):
    a = np.asarray(a, float).reshape(-1, 4)
    np.testing.assert_allclose(a, _quat_align(a, b), atol=atol)


def _core_cam_dict(c) -> dict:
    return {
        "model_id": int(c.model_id),
        "params": [float(x) for x in np.asarray(c.params)],
        "w": int(c.width),
        "h": int(c.height),
    }


def assert_cameras_equal(core_cams, oracle_cams, atol=1e-9):
    assert len(core_cams) == len(oracle_cams)
    for c, o in zip(core_cams, oracle_cams, strict=True):
        cd = _core_cam_dict(c)
        assert cd["model_id"] == o["model_id"]
        assert cd["w"] == o["w"] and cd["h"] == o["h"]
        np.testing.assert_allclose(cd["params"], o["params"], atol=atol)


@pytest.fixture
def rng():
    return np.random.default_rng(0)


# --- tests -----------------------------------------------------------------
# Hand-derived (rotation -> WXYZ) known answers anchor the quaternion math to an
# EXTERNAL ground truth (the oracle mirrors the C++ Shepperd branches, so it
# cannot catch a shared convention bug). The 180-degree cases (trace = -1)
# exercise the three trace<=0 branches identity/90-degree never reach.
_R90 = float(np.cos(np.pi / 4))
_KNOWN_ROTS = [
    (np.eye(3), [1.0, 0.0, 0.0, 0.0]),
    (np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float), [_R90, 0.0, 0.0, _R90]),  # +90 z
    (np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float), [_R90, _R90, 0.0, 0.0]),  # +90 x
    (np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float), [_R90, 0.0, _R90, 0.0]),  # +90 y
    (np.diag([1.0, -1.0, -1.0]), [0.0, 1.0, 0.0, 0.0]),  # 180 x
    (np.diag([-1.0, 1.0, -1.0]), [0.0, 0.0, 1.0, 0.0]),  # 180 y
    (np.diag([-1.0, -1.0, 1.0]), [0.0, 0.0, 0.0, 1.0]),  # 180 z
]


@pytest.mark.parametrize(("R", "expected_wxyz"), _KNOWN_ROTS)
def test_read_known_rotations(R, expected_wxyz):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = [0.1, 0.2, 0.3]
    data = json.dumps({"frames": [{"file_path": "a.png", "transform_matrix": M.tolist()}]}).encode()
    pvs = _core.read_transforms_json(data)
    assert_quat_close(pvs.quaternions, np.array([expected_wxyz]), atol=1e-9)
    np.testing.assert_allclose(np.asarray(pvs.translations)[0], [0.1, 0.2, 0.3], atol=1e-12)


@pytest.mark.parametrize("bad", [b"", b"not json", b"{", b'{"frames": 5}'])
def test_bad_input_raises_valueerror(bad):
    # malformed JSON / wrong shape -> ValueError, not RuntimeError (cf. the pfm
    # and spz bad-input tests).
    with pytest.raises(ValueError, match="transforms"):
        _core.read_transforms_json(bad)


@pytest.mark.parametrize("model", ["PINHOLE", "OPENCV", "SIMPLE_PINHOLE"])
def test_read_matches_oracle(rng, model):
    data = build_transforms(rng, model)
    pvs = _core.read_transforms_json(data)
    q_ref, t_ref, intr = oracle_read(data)
    assert_quat_close(pvs.quaternions, q_ref)  # poses within 1e-6
    np.testing.assert_allclose(np.asarray(pvs.translations), t_ref, atol=1e-9)
    assert_cameras_equal(pvs.cameras, intr["cameras"])
    np.testing.assert_array_equal(np.asarray(pvs.camera_indices), intr["cam_idx"])
    assert list(pvs.names) == [f"images/frame_{i:04d}.png" for i in range(4)]


def test_write_then_oracle_read_is_input(rng):
    pvs = _core.read_transforms_json(build_transforms(rng, "OPENCV"))
    q_ref, t_ref, intr = oracle_read(_core.write_transforms_json(pvs))
    assert_quat_close(pvs.quaternions, q_ref)
    np.testing.assert_allclose(np.asarray(pvs.translations), t_ref, atol=1e-9)
    assert_cameras_equal(pvs.cameras, intr["cameras"])


def test_oracle_write_then_our_read(rng):
    # our *reader* matches an independent writer's bytes (poses + intrinsics).
    src = _core.read_transforms_json(build_transforms(rng, "PINHOLE"))
    cams = [_core_cam_dict(c) for c in src.cameras]
    data = oracle_write(
        np.asarray(src.quaternions),
        np.asarray(src.translations),
        cams,
        list(np.asarray(src.camera_indices)),
        list(src.names),
    )
    got = _core.read_transforms_json(data)
    assert_quat_close(src.quaternions, got.quaternions)
    np.testing.assert_allclose(
        np.asarray(got.translations), np.asarray(src.translations), atol=1e-9
    )
    assert_cameras_equal(got.cameras, cams)


@pytest.mark.parametrize("model", ["PINHOLE", "OPENCV", "SIMPLE_PINHOLE"])
def test_roundtrip_identity(rng, model):
    pvs = _core.read_transforms_json(build_transforms(rng, model))
    back = _core.read_transforms_json(_core.write_transforms_json(pvs))
    assert_quat_close(pvs.quaternions, back.quaternions)
    np.testing.assert_allclose(
        np.asarray(back.translations), np.asarray(pvs.translations), atol=1e-9
    )
    assert back.num_cameras == pvs.num_cameras
    assert_cameras_equal(back.cameras, [_core_cam_dict(c) for c in pvs.cameras])
    np.testing.assert_array_equal(np.asarray(back.camera_indices), np.asarray(pvs.camera_indices))
    assert list(back.names) == list(pvs.names)


def test_convention_tags(rng):
    pvs = _core.read_transforms_json(build_transforms(rng, "PINHOLE"))
    assert pvs.quaternion_order == "wxyz"
    assert pvs.pose_convention == "camera_to_world"
    assert pvs.axis_frame == "opengl"
    assert pvs.scale_to_meters == 1.0


def test_pinhole_camera_params(rng):
    pvs = _core.read_transforms_json(build_transforms(rng, "PINHOLE"))
    assert pvs.num_cameras == 1
    c = pvs.cameras[0]
    assert c.model == "PINHOLE" and c.model_id == 1
    np.testing.assert_allclose(np.asarray(c.params), [720.5, 721.25, 400.0, 300.0])
    assert int(c.width) == 800 and int(c.height) == 600
    np.testing.assert_array_equal(np.asarray(pvs.camera_indices), np.zeros(4, dtype=np.int32))


def test_opencv_camera_params(rng):
    pvs = _core.read_transforms_json(build_transforms(rng, "OPENCV"))
    c = pvs.cameras[0]
    assert c.model == "OPENCV" and c.model_id == 4
    np.testing.assert_allclose(
        np.asarray(c.params), [720.5, 721.25, 400.0, 300.0, 0.021, -0.0034, 0.0011, -0.0007]
    )


def test_simple_pinhole_camera_params(rng):
    pvs = _core.read_transforms_json(build_transforms(rng, "SIMPLE_PINHOLE"))
    c = pvs.cameras[0]
    assert c.model == "SIMPLE_PINHOLE" and c.model_id == 0
    np.testing.assert_allclose(np.asarray(c.params), [720.5, 400.0, 300.0])


def test_per_frame_intrinsics(rng):
    pvs = _core.read_transforms_json(build_transforms(rng, "OPENCV", per_frame=True, n=3))
    assert pvs.num_cameras == 3
    np.testing.assert_array_equal(np.asarray(pvs.camera_indices), [0, 1, 2])
    for i, c in enumerate(pvs.cameras):
        assert c.model == "OPENCV"
        np.testing.assert_allclose(
            np.asarray(c.params),
            [700.0 + i, 701.0 + i, 320.0 + i, 240.0 + i, 0.021, -0.0034, 0.0011, -0.0007],
        )
    # per-frame intrinsics survive a round-trip as one Camera per frame
    back = _core.read_transforms_json(_core.write_transforms_json(pvs))
    assert back.num_cameras == 3
    assert_cameras_equal(back.cameras, [_core_cam_dict(c) for c in pvs.cameras])


def test_no_intrinsics(rng):
    # a poses-only file: no top-level or per-frame intrinsics -> empty cameras.
    frames = []
    for i in range(3):
        M = np.eye(4)
        M[:3, :3] = _rot_from_rand(rng)
        M[:3, 3] = rng.standard_normal(3)
        frames.append({"file_path": f"{i}.png", "transform_matrix": M.tolist()})
    data = json.dumps({"frames": frames}).encode()
    pvs = _core.read_transforms_json(data)
    assert pvs.num_cameras == 0
    assert np.asarray(pvs.camera_indices).size == 0
    # round-trips with intrinsics still absent
    back = _core.read_transforms_json(_core.write_transforms_json(pvs))
    assert back.num_cameras == 0
    assert_quat_close(pvs.quaternions, back.quaternions)


def test_missing_frames_raises():
    with pytest.raises(ValueError, match="frames"):
        _core.read_transforms_json(b"{}")


def test_quaternions_are_numpy(rng):
    pvs = _core.read_transforms_json(build_transforms(rng, "PINHOLE"))
    q = pvs.quaternions
    assert isinstance(q, np.ndarray)
    assert q.dtype == np.float64 and q.shape == (4, 4)


def test_torch_interop(rng):
    torch = pytest.importorskip("torch")
    pvs = _core.read_transforms_json(build_transforms(rng, "PINHOLE"))
    q = pvs.quaternions
    assert isinstance(q, np.ndarray)
    # zero-copy CPU handoff via DLPack agrees with the numpy view
    assert np.array_equal(torch.from_dlpack(q).numpy(), np.asarray(q))
