"""Parity suite for the OpenMVG ``sfm_data.json`` codec -> Reconstruction.

OpenMVG's engine is MPL-2.0 (license-gated per docs/formats_survey.md) and ships
no PyPI bindings, so there is NO installable reference implementation. The oracle
is therefore a self-contained pure-Python ``json`` + ``numpy`` parser defined in
this file (runtime deps stay numpy-only): it walks the cereal wrappers
(ptr_wrapper.data, the polymorphic first-occurrence / back-reference registry)
independently of the C++, converts poses with a Shepperd ``matrix_to_quat`` that
mirrors the C++ branch-for-branch, and computes ``t = -R*C`` with the same scalar
left-to-right association so cross-impl comparisons are exact.

Because a mirror oracle shares blind spots with the codec by construction, the
external anchors are hand-derived pins: the mandated ``R,C -> t`` convention pin
(a permutation extrinsic decoding to exact ``q``/``t``), and the
``write_colmap_txt`` coupling gate (which surfaces the obs/track CSR the
Reconstruction binding does not expose). Everything else — model mapping,
cereal-structure of the writer, malformed-raises, single-byte fuzz, registry — is
pinned around those anchors.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

try:
    from sceneio import _core
except Exception:  # pragma: no cover - exercised only in a non-built tree
    _core = None

pytestmark = pytest.mark.skipif(
    _core is None or not hasattr(_core, "read_openmvg"),
    reason="sceneio._core.read_openmvg not built/wired (compiled-only package)",
)


# ==========================================================================
# pure-Python oracle (independent cereal walk + pose conversion)
# ==========================================================================
def _shepperd_wxyz(R):
    """Shepperd's method — byte-for-byte the same branch selection as the C++
    matrix_to_quat, so exact-arithmetic rotations decode to identical bits."""
    m00, m01, m02 = R[0]
    m10, m11, m12 = R[1]
    m20, m21, m22 = R[2]
    tr = m00 + m11 + m22
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    n = math.sqrt(w * w + x * x + y * y + z * z)
    return [w / n, x / n, y / n, z / n]


def _quat_wxyz_to_R(q):
    w, x, y, z = (float(v) for v in q)
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n > 0.0:
        w, x, y, z = w / n, x / n, y / n, z / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        float,
    )


def _resolve_poly(value, by_id):
    if isinstance(value.get("polymorphic_name"), str):
        name = value["polymorphic_name"]
        if "polymorphic_id" in value:
            by_id[int(value["polymorphic_id"]) & 0x7FFFFFFF] = name
        return name
    if "polymorphic_id" in value:
        pid = int(value["polymorphic_id"]) & 0x7FFFFFFF
        if pid in by_id:
            return by_id[pid]
    raise ValueError("intrinsic has no polymorphic_name and no known polymorphic_id")


def _map_intrinsic(cid, name, data):
    f = float(data["focal_length"])
    ppx, ppy = (float(v) for v in data["principal_point"])
    w, h = int(data["width"]), int(data["height"])
    if name == "pinhole":
        model, params = 0, [f, ppx, ppy]
    elif name == "pinhole_radial_k1":
        k1 = float(data["disto_k1"][0])
        model, params = 2, [f, ppx, ppy, k1]
    elif name == "pinhole_radial_k3":
        k1, k2, k3 = (float(v) for v in data["disto_k3"])
        model, params = 6, [f, f, ppx, ppy, k1, k2, 0.0, 0.0, k3, 0.0, 0.0, 0.0]
    elif name == "pinhole_brown_t2":
        k1, k2, k3, t1, t2 = (float(v) for v in data["disto_t2"])
        model, params = 6, [f, f, ppx, ppy, k1, k2, t1, t2, k3, 0.0, 0.0, 0.0]
    elif name == "fisheye":
        k1, k2, k3, k4 = (float(v) for v in data["fisheye"])
        model, params = 5, [f, f, ppx, ppy, k1, k2, k3, k4]
    else:
        raise ValueError(f"unsupported intrinsic {name!r}")
    return {"id": cid, "model_id": model, "params": params, "w": w, "h": h}


def oracle_read(data: bytes) -> dict:
    d = json.loads(data)
    # intrinsics (array order) + polymorphic registry
    by_id: dict[int, str] = {}
    cams: dict[int, dict] = {}
    ocams = []
    for e in d["intrinsics"]:
        cid = int(e["key"])
        v = e["value"]
        name = _resolve_poly(v, by_id)
        cams[cid] = _map_intrinsic(cid, name, v["ptr_wrapper"]["data"])
        ocams.append(cams[cid])
    # extrinsics -> pose map
    poses: dict[int, tuple] = {}
    for e in d["extrinsics"]:
        v = e["value"]
        R = [[float(x) for x in row] for row in v["rotation"]]
        C = [float(x) for x in v["center"]]
        q = _shepperd_wxyz(R)
        t = [-(R[r][0] * C[0] + R[r][1] * C[1] + R[r][2] * C[2]) for r in range(3)]
        poses[int(e["key"])] = (q, t)
    # views (skip unreconstructed)
    image_ids, names, cam_ids, quats, trans = [], [], [], [], []
    for e in d["views"]:
        iid = int(e["key"])
        data_ = e["value"]["ptr_wrapper"]["data"]
        id_intr, id_pose = int(data_["id_intrinsic"]), int(data_["id_pose"])
        if id_intr == 0xFFFFFFFF or id_pose not in poses:
            continue
        q, t = poses[id_pose]
        image_ids.append(iid)
        fn, lp = data_["filename"], data_.get("local_path", "")
        names.append(fn if not lp else f"{lp}/{fn}")
        cam_ids.append(id_intr)
        quats.append(q)
        trans.append(t)
    # structure
    pt_ids, xyz = [], []
    for e in d.get("structure") or []:
        pt_ids.append(int(e["key"]))
        xyz.append([float(x) for x in e["value"]["X"]])
    return {
        "image_ids": image_ids,
        "names": names,
        "img_cam_ids": cam_ids,
        "quats": np.array(quats, float).reshape(-1, 4),
        "trans": np.array(trans, float).reshape(-1, 3),
        "cameras": ocams,
        "pt_ids": pt_ids,
        "xyz": np.array(xyz, float).reshape(-1, 3),
    }


# ==========================================================================
# fixture builders (cereal-shaped sfm_data.json)
# ==========================================================================
def _view(img_id, filename, id_intrinsic, id_pose, w=640, h=480, local_path="", ptr_id=2147483649):
    data = {
        "local_path": local_path,
        "filename": filename,
        "width": w,
        "height": h,
        "id_view": img_id,
        "id_intrinsic": id_intrinsic,
        "id_pose": id_pose,
    }
    return {
        "key": img_id,
        "value": {"polymorphic_id": 1073741824, "ptr_wrapper": {"id": ptr_id, "data": data}},
    }


def _intr(cam_id, name, focal, ppx, ppy, w=640, h=480, disto=None, poly_id=None, with_name=True,
          ptr_id=2147483650):
    data = {"width": w, "height": h, "focal_length": focal, "principal_point": [ppx, ppy]}
    if disto is not None:
        data[disto[0]] = disto[1]
    val: dict = {}
    if poly_id is not None:
        val["polymorphic_id"] = poly_id
    if with_name:
        val["polymorphic_name"] = name
    val["ptr_wrapper"] = {"id": ptr_id, "data": data}
    return {"key": cam_id, "value": val}


def _extr(pose_id, R, C):
    return {"key": pose_id, "value": {"rotation": [list(r) for r in R], "center": list(C)}}


def _struct(pt_id, X, obs):
    # obs: list of (img_id, id_feat, x, y)
    observations = [{"key": i, "value": {"id_feat": f, "x": [x, y]}} for (i, f, x, y) in obs]
    return {"key": pt_id, "value": {"X": list(X), "observations": observations}}


def _sfm(views, intrinsics, extrinsics, structure=None, control_points=None, root_path=""):
    d = {
        "sfm_data_version": "0.3",
        "root_path": root_path,
        "views": views,
        "intrinsics": intrinsics,
        "extrinsics": extrinsics,
    }
    if structure is not None:
        d["structure"] = structure
    if control_points is not None:
        d["control_points"] = control_points
    return json.dumps(d).encode()


_IDENT = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
_PERM = [[0, 1, 0], [0, 0, 1], [1, 0, 0]]  # -> q=[-0.5,0.5,0.5,0.5], -R*[1,2,3]=[-2,-3,-1]

# A canonical fixture: 3 views (view 2 unposed -> skipped), 2 intrinsics of
# different types (one pinhole, one pinhole_radial_k3 -> FULL_OPENCV), 3 landmarks
# with shared multi-image observations. All poses are exact-arithmetic rotations.
CANONICAL = _sfm(
    views=[
        _view(0, "a.jpg", id_intrinsic=0, id_pose=0),
        _view(1, "b.jpg", id_intrinsic=1, id_pose=1, w=1000, h=750),
        _view(2, "c.jpg", id_intrinsic=0, id_pose=99),  # pose 99 absent -> skipped
    ],
    intrinsics=[
        _intr(0, "pinhole", 800.0, 320.0, 240.0, w=640, h=480, poly_id=2147483649),
        _intr(1, "pinhole_radial_k3", 1000.0, 500.0, 375.0, w=1000, h=750,
              disto=("disto_k3", [0.1, 0.01, 0.001]), poly_id=2147483650),
    ],
    extrinsics=[_extr(0, _IDENT, [0, 0, 0]), _extr(1, _PERM, [1, 2, 3])],
    structure=[
        _struct(0, [1, 2, 3], [(0, 5, 10.0, 20.0), (1, 6, 30.0, 40.0)]),
        _struct(1, [4, 5, 6], [(1, 7, 50.0, 60.0)]),
        _struct(2, [7, 8, 9], [(0, 8, 70.0, 80.0), (1, 9, 90.0, 100.0)]),
    ],
    root_path="/images",
)


def _quat_align(ref, q):
    ref = np.asarray(ref, float).reshape(-1, 4)
    q = np.asarray(q, float).reshape(-1, 4)
    s = np.sign(np.sum(ref * q, axis=1, keepdims=True))
    s[s == 0] = 1.0
    return q * s


# ==========================================================================
# cross-impl parity + the hand-derived convention pins
# ==========================================================================
def test_cross_impl_oracle_parity():
    R = _core.read_openmvg(CANONICAL)
    o = oracle_read(CANONICAL)
    assert [int(x) for x in np.asarray(R.image_ids)] == o["image_ids"]
    assert list(R.image_names) == o["names"]
    assert [int(x) for x in np.asarray(R.image_camera_ids)] == o["img_cam_ids"]
    q, t = np.asarray(R.quaternions), np.asarray(R.translations)
    np.testing.assert_allclose(_quat_align(o["quats"], q), o["quats"], atol=1e-12)
    np.testing.assert_allclose(t, o["trans"], atol=1e-12)
    assert R.num_cameras == len(o["cameras"])
    for c, oc in zip(R.cameras, o["cameras"], strict=True):
        assert int(c.id) == oc["id"]
        assert int(c.model_id) == oc["model_id"]
        assert (int(c.width), int(c.height)) == (oc["w"], oc["h"])
        np.testing.assert_allclose(np.asarray(c.params), oc["params"], atol=1e-12)
    assert [int(x) for x in np.asarray(R.point3D_ids)] == o["pt_ids"]
    np.testing.assert_array_equal(np.asarray(R.xyz), o["xyz"])
    assert np.all(np.asarray(R.rgb) == 0)
    assert np.all(np.asarray(R.errors) == -1.0)


def test_pose_convention_pin_R_center_to_t():
    # THE mandated external pin (hand-derived from X_cam = R*(X - C)):
    #   R = perm, C = (1,2,3) -> q = (-0.5,0.5,0.5,0.5), t = (-2,-3,-1)
    #   R = I,    C = (1,2,3) -> q = (1,0,0,0),          t = (-1,-2,-3)
    fixture = _sfm(
        views=[_view(0, "a.jpg", 0, 0), _view(1, "b.jpg", 0, 1)],
        intrinsics=[_intr(0, "pinhole", 100.0, 0.0, 0.0, poly_id=2147483649)],
        extrinsics=[_extr(0, _PERM, [1, 2, 3]), _extr(1, _IDENT, [1, 2, 3])],
    )
    R = _core.read_openmvg(fixture)
    q, t = np.asarray(R.quaternions), np.asarray(R.translations)
    np.testing.assert_array_equal(q[0], [-0.5, 0.5, 0.5, 0.5])
    np.testing.assert_array_equal(t[0], [-2.0, -3.0, -1.0])
    np.testing.assert_array_equal(q[1], [1.0, 0.0, 0.0, 0.0])
    np.testing.assert_array_equal(t[1], [-1.0, -2.0, -3.0])
    np.testing.assert_allclose(_quat_wxyz_to_R(q[0]), _PERM, atol=1e-15)
    assert R.pose_convention == "world_to_camera"
    assert R.quaternion_order == "wxyz"


@pytest.mark.parametrize(
    ("name", "disto", "exp_model", "exp_params"),
    [
        ("pinhole", None, 0, [800.0, 320.0, 240.0]),
        ("pinhole_radial_k1", ("disto_k1", [0.1]), 2, [800.0, 320.0, 240.0, 0.1]),
        ("pinhole_radial_k3", ("disto_k3", [0.1, 0.01, 0.001]), 6,
         [800.0, 800.0, 320.0, 240.0, 0.1, 0.01, 0.0, 0.0, 0.001, 0.0, 0.0, 0.0]),
        ("pinhole_brown_t2", ("disto_t2", [0.1, 0.01, 0.001, 0.002, 0.003]), 6,
         [800.0, 800.0, 320.0, 240.0, 0.1, 0.01, 0.002, 0.003, 0.001, 0.0, 0.0, 0.0]),
        ("fisheye", ("fisheye", [0.1, 0.01, 0.001, 0.0001]), 5,
         [800.0, 800.0, 320.0, 240.0, 0.1, 0.01, 0.001, 0.0001]),
    ],
)
def test_intrinsic_model_mapping(name, disto, exp_model, exp_params):
    fixture = _sfm(
        views=[_view(0, "a.jpg", 0, 0)],
        intrinsics=[_intr(0, name, 800.0, 320.0, 240.0, w=640, h=480, disto=disto,
                          poly_id=2147483649)],
        extrinsics=[_extr(0, _IDENT, [0, 0, 0])],
    )
    R = _core.read_openmvg(fixture)
    c = R.cameras[0]
    assert int(c.id) == 0
    assert int(c.model_id) == exp_model
    assert (int(c.width), int(c.height)) == (640, 480)
    np.testing.assert_allclose(np.asarray(c.params), exp_params, atol=1e-12)


def test_polymorphic_back_reference():
    # Two same-type intrinsics: only the first carries polymorphic_name; the
    # second is a bare-id cereal back-reference. Both must resolve to pinhole.
    fixture = _sfm(
        views=[_view(0, "a.jpg", 0, 0), _view(1, "b.jpg", 1, 1)],
        intrinsics=[
            _intr(0, "pinhole", 800.0, 320.0, 240.0, poly_id=2147483649, with_name=True),
            _intr(1, "pinhole", 900.0, 450.0, 300.0, poly_id=1, with_name=False, ptr_id=2147483651),
        ],
        extrinsics=[_extr(0, _IDENT, [0, 0, 0]), _extr(1, _IDENT, [0, 0, 0])],
    )
    R = _core.read_openmvg(fixture)
    assert [int(c.model_id) for c in R.cameras] == [0, 0]
    np.testing.assert_allclose(np.asarray(R.cameras[1].params), [900.0, 450.0, 300.0])


def test_intrinsic_no_name_no_known_id_raises():
    fixture = _sfm(
        views=[_view(0, "a.jpg", 0, 0)],
        intrinsics=[_intr(0, "pinhole", 800.0, 0.0, 0.0, poly_id=5, with_name=False)],
        extrinsics=[_extr(0, _IDENT, [0, 0, 0])],
    )
    with pytest.raises(ValueError, match="polymorphic"):
        _core.read_openmvg(fixture)


def test_unposed_and_undefined_views_skipped():
    fixture = _sfm(
        views=[
            _view(0, "posed.jpg", 0, 0),
            _view(1, "nopose.jpg", 0, 77),  # pose 77 absent -> skipped
            _view(2, "nointr.jpg", 0xFFFFFFFF, 0),  # UndefinedIndexT intrinsic -> skipped
        ],
        intrinsics=[_intr(0, "pinhole", 800.0, 0.0, 0.0, poly_id=2147483649)],
        extrinsics=[_extr(0, _IDENT, [0, 0, 0]), _extr(1, _IDENT, [1, 1, 1])],  # pose 1 orphan
    )
    R = _core.read_openmvg(fixture)
    assert R.num_images == 1
    assert [int(x) for x in np.asarray(R.image_ids)] == [0]
    assert list(R.image_names) == ["posed.jpg"]


def test_posed_view_with_dangling_intrinsic_raises():
    fixture = _sfm(
        views=[_view(0, "a.jpg", id_intrinsic=9, id_pose=0)],  # intrinsic 9 does not exist
        intrinsics=[_intr(0, "pinhole", 800.0, 0.0, 0.0, poly_id=2147483649)],
        extrinsics=[_extr(0, _IDENT, [0, 0, 0])],
    )
    with pytest.raises(ValueError, match="missing intrinsic"):
        _core.read_openmvg(fixture)


# ==========================================================================
# observations / tracks CSR (validated through the COLMAP text writer, which the
# Reconstruction binding does not surface)
# ==========================================================================
def test_observations_tracks_csr_via_colmap_text(tmp_path):
    R = _core.read_openmvg(CANONICAL)
    out = tmp_path / "cm"
    out.mkdir()
    _core.write_colmap_txt(R, str(out))
    images = (out / "images.txt").read_bytes()
    points = (out / "points3D.txt").read_bytes()
    # per-image observations in (structure order, per-landmark order):
    assert b"a.jpg\n10 20 0 70 80 2\n" in images
    assert b"b.jpg\n30 40 0 50 60 1 90 100 2\n" in images
    # points: xyz + rgb=0 0 0 + error=-1 + (IMAGE_ID, POINT2D_IDX) tracks:
    assert b"0 1 2 3 0 0 0 -1 0 0 1 0\n" in points
    assert b"1 4 5 6 0 0 0 -1 1 1\n" in points
    assert b"2 7 8 9 0 0 0 -1 0 1 1 2\n" in points


# ==========================================================================
# round-trip + writer spec-correctness
# ==========================================================================
def test_roundtrip_bitexact_crafted(tmp_path):
    R1 = _core.read_openmvg(CANONICAL)
    R2 = _core.read_openmvg(_core.write_openmvg(R1))
    for attr in ("quaternions", "translations", "xyz", "rgb", "errors", "image_ids",
                 "point3D_ids", "image_camera_ids"):
        np.testing.assert_array_equal(np.asarray(getattr(R2, attr)), np.asarray(getattr(R1, attr)))
    assert list(R2.image_names) == list(R1.image_names)
    for c2, c1 in zip(R2.cameras, R1.cameras, strict=True):
        assert (int(c2.model_id), int(c2.width), int(c2.height)) == (
            int(c1.model_id), int(c1.width), int(c1.height))
        np.testing.assert_array_equal(np.asarray(c2.params), np.asarray(c1.params))
    # coupling gate: the obs/track CSR the binding can't surface must survive too.
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _core.write_colmap_txt(R1, str(a))
    _core.write_colmap_txt(R2, str(b))
    for f in ("cameras.txt", "images.txt", "points3D.txt"):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_oracle_reads_our_writer():
    # Writer spec-correctness (parity kind 2): the independent oracle reads our
    # bytes back to the source record, plus cereal-structure assertions.
    R = _core.read_openmvg(CANONICAL)
    out = _core.write_openmvg(R)
    o = oracle_read(out)
    assert o["image_ids"] == [int(x) for x in np.asarray(R.image_ids)]
    assert o["names"] == list(R.image_names)
    assert o["img_cam_ids"] == [int(x) for x in np.asarray(R.image_camera_ids)]
    np.testing.assert_allclose(_quat_align(np.asarray(R.quaternions), o["quats"]),
                               np.asarray(R.quaternions), atol=1e-12)
    np.testing.assert_allclose(o["trans"], np.asarray(R.translations), atol=1e-12)
    np.testing.assert_array_equal(o["xyz"], np.asarray(R.xyz))
    assert o["pt_ids"] == [int(x) for x in np.asarray(R.point3D_ids)]

    d = json.loads(out)
    assert d["sfm_data_version"] == "0.3"
    assert d["root_path"] == ""
    assert d["control_points"] == []
    for v in d["views"]:
        assert v["value"]["polymorphic_id"] == 1073741824
        data = v["value"]["ptr_wrapper"]["data"]
        assert data["id_pose"] == data["id_view"] == v["key"]
    ptr_ids = [v["value"]["ptr_wrapper"]["id"] for v in d["views"]]
    ptr_ids += [i["value"]["ptr_wrapper"]["id"] for i in d["intrinsics"]]
    assert ptr_ids == list(range(2147483649, 2147483649 + len(ptr_ids)))
    # both canonical intrinsics are distinct types, so each names itself once.
    names = [i["value"].get("polymorphic_name") for i in d["intrinsics"]]
    assert names == ["pinhole", "pinhole_radial_k3"]


def test_writer_back_reference_for_repeated_type(tmp_path):
    # Two SIMPLE_PINHOLE cameras -> the second intrinsic is a bare-id cereal
    # back-reference (no polymorphic_name), and both still re-read as pinhole.
    R = _colmap_record(
        tmp_path,
        b"1 SIMPLE_PINHOLE 640 480 800 320 240\n2 SIMPLE_PINHOLE 640 480 900 400 300\n",
        images=b"1 1 0 0 0 0 0 0 1 a.jpg\n\n2 1 0 0 0 0 0 0 2 b.jpg\n\n",
    )
    out = _core.write_openmvg(R)
    d = json.loads(out)
    assert d["intrinsics"][0]["value"]["polymorphic_name"] == "pinhole"
    assert "polymorphic_name" not in d["intrinsics"][1]["value"]
    assert d["intrinsics"][1]["value"]["polymorphic_id"] == 1  # bare back-reference id
    assert [int(c.model_id) for c in _core.read_openmvg(out).cameras] == [0, 0]


# ==========================================================================
# golden writer blob (byte-exact encode-drift guard)
# ==========================================================================
GOLD_IN = _sfm(
    views=[_view(0, "0.jpg", 0, 0, w=640, h=480, ptr_id=42)],
    intrinsics=[_intr(0, "pinhole_radial_k1", 800.0, 320.0, 240.0, w=640, h=480,
                      disto=("disto_k1", [0.5]), poly_id=2147483649, ptr_id=99)],
    extrinsics=[_extr(0, _PERM, [1, 2, 3])],
    structure=[_struct(0, [1.5, -2.5, 3.5], [(0, 7, 10.5, -20.5)])],
    control_points=[],
    root_path="/imgs",  # dropped on read
)


def _golden_expected() -> bytes:
    # The exact writer output for GOLD_IN. Regenerate by reading GOLD_IN and
    # printing _core.write_openmvg(R); every value here is exactly representable
    # so nlohmann's and Python's shortest-round-trip float formatting agree.
    expected = {
        "sfm_data_version": "0.3",
        "root_path": "",
        "views": [{"key": 0, "value": {
            "polymorphic_id": 1073741824,
            "ptr_wrapper": {"id": 2147483649, "data": {
                "local_path": "", "filename": "0.jpg", "width": 640, "height": 480,
                "id_view": 0, "id_intrinsic": 0, "id_pose": 0}}}}],
        "intrinsics": [{"key": 0, "value": {
            "polymorphic_id": 2147483649, "polymorphic_name": "pinhole_radial_k1",
            "ptr_wrapper": {"id": 2147483650, "data": {
                "width": 640, "height": 480, "focal_length": 800.0,
                "principal_point": [320.0, 240.0], "disto_k1": [0.5]}}}}],
        "extrinsics": [{"key": 0, "value": {
            "rotation": [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]],
            "center": [1.0, 2.0, 3.0]}}],
        "structure": [{"key": 0, "value": {
            "X": [1.5, -2.5, 3.5],
            "observations": [{"key": 0, "value": {"id_feat": 0, "x": [10.5, -20.5]}}]}}],
        "control_points": [],
    }
    return json.dumps(expected, separators=(",", ":"), ensure_ascii=False).encode()


def test_golden_writer_blob():
    R = _core.read_openmvg(GOLD_IN)
    assert _core.write_openmvg(R) == _golden_expected()


# ==========================================================================
# writer model mapping + guards (records built through the COLMAP text reader,
# since Reconstruction has no Python constructor)
# ==========================================================================
def _colmap_record(tmp_path, cameras, images=b"1 1 0 0 0 0 0 0 1 a.jpg\n\n",
                   points=b"1 0 0 0 0 0 0 -1\n", sub="m"):
    d = tmp_path / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / "cameras.txt").write_bytes(cameras)
    (d / "images.txt").write_bytes(images)
    (d / "points3D.txt").write_bytes(points)
    return _core.read_colmap_txt(str(d))


def _written_type(data: bytes) -> str:
    return json.loads(data)["intrinsics"][0]["value"]["polymorphic_name"]


@pytest.mark.parametrize(
    ("camera_line", "exp_type"),
    [
        (b"1 SIMPLE_PINHOLE 640 480 800 320 240\n", "pinhole"),
        (b"1 PINHOLE 640 480 800 800 320 240\n", "pinhole"),  # fx==fy
        (b"1 SIMPLE_RADIAL 640 480 800 320 240 0.1\n", "pinhole_radial_k1"),
        (b"1 RADIAL 640 480 800 320 240 0.1 0.01\n", "pinhole_radial_k3"),
        (b"1 OPENCV 640 480 800 800 320 240 0.1 0.01 0.002 0.003\n", "pinhole_brown_t2"),
        (b"1 OPENCV_FISHEYE 640 480 800 800 320 240 0.1 0.01 0.001 0.0001\n", "fisheye"),
        # FULL_OPENCV with tangential -> brown_t2; without -> radial_k3
        (b"1 FULL_OPENCV 640 480 800 800 320 240 0.1 0.01 0.002 0.003 0.001 0 0 0\n",
         "pinhole_brown_t2"),
        (b"1 FULL_OPENCV 640 480 800 800 320 240 0.1 0.01 0 0 0.001 0 0 0\n", "pinhole_radial_k3"),
    ],
)
def test_writer_model_mapping(tmp_path, camera_line, exp_type):
    R = _colmap_record(tmp_path, camera_line)  # unique tmp_path per parametrization
    assert _written_type(_core.write_openmvg(R)) == exp_type


def test_writer_radial_maps_to_k3_with_zero_and_reads_back_full_opencv(tmp_path):
    R = _colmap_record(tmp_path, b"1 RADIAL 640 480 800 320 240 0.1 0.01\n")
    d = json.loads(_core.write_openmvg(R))
    np.testing.assert_array_equal(d["intrinsics"][0]["value"]["ptr_wrapper"]["data"]["disto_k3"],
                                  [0.1, 0.01, 0.0])  # RADIAL k1,k2 with an appended k3=0
    back = _core.read_openmvg(_core.write_openmvg(R))
    assert int(back.cameras[0].model_id) == 6  # documented RADIAL(3) -> FULL_OPENCV(6) asymmetry
    np.testing.assert_allclose(
        np.asarray(back.cameras[0].params),
        [800.0, 800.0, 320.0, 240.0, 0.1, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])


@pytest.mark.parametrize(
    ("camera_line", "match"),
    [
        (b"1 PINHOLE 640 480 800 900 320 240\n", "fx != fy"),
        (b"1 OPENCV 640 480 800 900 320 240 0.1 0.01 0.002 0.003\n", "fx != fy"),
        (b"1 OPENCV_FISHEYE 640 480 800 900 320 240 0.1 0.01 0.001 0.0001\n", "fx != fy"),
        (b"1 FULL_OPENCV 640 480 800 800 320 240 0.1 0.01 0 0 0.001 0.5 0 0\n", "k4"),  # k4!=0
        (b"1 FOV 640 480 800 800 320 240 0.9\n", "not representable"),
        # THIN_PRISM_FISHEYE has 12 COLMAP params (fx fy cx cy k1 k2 p1 p2 k3 k4 sx1 sy1)
        (b"1 THIN_PRISM_FISHEYE 640 480 800 800 320 240 0.1 0.01 0 0 0.001 0 0 0\n",
         "not representable"),
    ],
)
def test_writer_guards_raise(tmp_path, camera_line, match):
    R = _colmap_record(tmp_path, camera_line)  # unique tmp_path per parametrization
    with pytest.raises(ValueError, match=match):
        _core.write_openmvg(R)


# ==========================================================================
# tolerated omissions + local_path join
# ==========================================================================
def test_missing_structure_tolerated():
    fixture = _sfm(
        views=[_view(0, "a.jpg", 0, 0)],
        intrinsics=[_intr(0, "pinhole", 800.0, 0.0, 0.0, poly_id=2147483649)],
        extrinsics=[_extr(0, _IDENT, [0, 0, 0])],
        # no "structure" key at all
    )
    R = _core.read_openmvg(fixture)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (1, 1, 0)


def test_empty_reconstruction_roundtrips():
    fixture = _sfm(views=[], intrinsics=[], extrinsics=[], structure=[], control_points=[])
    R = _core.read_openmvg(fixture)
    assert (R.num_cameras, R.num_images, R.num_points3D) == (0, 0, 0)
    R2 = _core.read_openmvg(_core.write_openmvg(R))
    assert (R2.num_cameras, R2.num_images, R2.num_points3D) == (0, 0, 0)


def test_local_path_join():
    fixture = _sfm(
        views=[_view(0, "a.jpg", 0, 0, local_path="sub")],
        intrinsics=[_intr(0, "pinhole", 800.0, 0.0, 0.0, poly_id=2147483649)],
        extrinsics=[_extr(0, _IDENT, [0, 0, 0])],
    )
    R = _core.read_openmvg(fixture)
    assert list(R.image_names) == ["sub/a.jpg"]
    # writer folds the join into filename (local_path emitted as "")
    d = json.loads(_core.write_openmvg(R))
    data = d["views"][0]["value"]["ptr_wrapper"]["data"]
    assert data["local_path"] == "" and data["filename"] == "sub/a.jpg"
    assert list(_core.read_openmvg(_core.write_openmvg(R)).image_names) == ["sub/a.jpg"]


# ==========================================================================
# malformed input -> ValueError (FormatError-mappable), never crash
# ==========================================================================
_VALID_INTR = [_intr(0, "pinhole", 800.0, 0.0, 0.0, poly_id=2147483649)]
_VALID_EXTR = [_extr(0, _IDENT, [0, 0, 0])]


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"not json{", "OpenMVG"),
        (b"[]", "object"),
        (json.dumps({"intrinsics": [], "extrinsics": []}).encode(), "views"),
        (json.dumps({"views": [], "extrinsics": []}).encode(), "intrinsics"),
        (json.dumps({"views": [], "intrinsics": []}).encode(), "extrinsics"),
        # view without ptr_wrapper
        (json.dumps({"intrinsics": [_VALID_INTR[0]], "extrinsics": [_VALID_EXTR[0]],
                     "views": [{"key": 0, "value": {"polymorphic_id": 1073741824}}]}).encode(),
         "ptr_wrapper"),
        # view without filename
        (_sfm([{"key": 0, "value": {"polymorphic_id": 1073741824, "ptr_wrapper": {"id": 1,
               "data": {"id_intrinsic": 0, "id_pose": 0}}}}], _VALID_INTR, _VALID_EXTR), "filename"),
        # view without id_pose
        (_sfm([{"key": 0, "value": {"polymorphic_id": 1073741824, "ptr_wrapper": {"id": 1,
               "data": {"filename": "a.jpg", "id_intrinsic": 0}}}}], _VALID_INTR, _VALID_EXTR),
         "id_pose"),
        # unknown polymorphic_name
        (_sfm([_view(0, "a.jpg", 0, 0)],
              [_intr(0, "spherical", 800.0, 0.0, 0.0, poly_id=2147483649)], _VALID_EXTR),
         "spherical"),
        # extrinsic missing rotation
        (_sfm([], _VALID_INTR, [{"key": 0, "value": {"center": [0, 0, 0]}}]), "rotation"),
        # rotation not 3x3
        (_sfm([], _VALID_INTR, [_extr(0, [[0, 0, 0], [0, 0, 0]], [0, 0, 0])]), "rotation"),
        # rotation row not length 3
        (_sfm([], _VALID_INTR, [_extr(0, [[0, 0], [0, 0, 0], [0, 0, 0]], [0, 0, 0])]), "rotation"),
        # center not length 3
        (_sfm([], _VALID_INTR, [_extr(0, _IDENT, [0, 0])]), "center"),
        # principal_point not length 2
        (_sfm([], [{"key": 0, "value": {"polymorphic_id": 2147483649,
               "polymorphic_name": "pinhole", "ptr_wrapper": {"id": 1, "data": {"width": 1,
               "height": 1, "focal_length": 800.0, "principal_point": [0]}}}}], _VALID_EXTR),
         "principal_point"),
        # disto_k3 not length 3
        (_sfm([], [_intr(0, "pinhole_radial_k3", 800.0, 0.0, 0.0, disto=("disto_k3", [0, 0]),
               poly_id=2147483649)], _VALID_EXTR), "disto_k3"),
        # landmark X not length 3
        (_sfm([], _VALID_INTR, _VALID_EXTR,
              structure=[{"key": 0, "value": {"X": [1, 2], "observations": []}}]), "landmark X"),
        # observation x not length 2
        (_sfm([_view(0, "a.jpg", 0, 0)], _VALID_INTR, _VALID_EXTR,
              structure=[{"key": 0, "value": {"X": [1, 2, 3],
                          "observations": [{"key": 0, "value": {"id_feat": 0, "x": [1]}}]}}]),
         "observation x"),
        # observation references an unposed / unknown view
        (_sfm([_view(0, "a.jpg", 0, 0)], _VALID_INTR, _VALID_EXTR,
              structure=[_struct(0, [1, 2, 3], [(5, 0, 1.0, 2.0)])]), "posed view"),
        # negative view key
        (_sfm([_view(-1, "a.jpg", 0, 0)], _VALID_INTR, _VALID_EXTR), "uint32"),
        # structure key overflowing int64
        (_sfm([], _VALID_INTR, _VALID_EXTR,
              structure=[{"key": 2 ** 63, "value": {"X": [1, 2, 3], "observations": []}}]), "int64"),
        # negative id_intrinsic
        (_sfm([{"key": 0, "value": {"polymorphic_id": 1073741824, "ptr_wrapper": {"id": 1,
               "data": {"filename": "a.jpg", "id_intrinsic": -1, "id_pose": 0}}}}],
              _VALID_INTR, _VALID_EXTR), "uint32"),
    ],
)
def test_malformed_raises(data, match):
    with pytest.raises(ValueError, match=match):
        _core.read_openmvg(data)


def test_fuzz_single_byte_mutation_no_crash():
    # Every single-byte mutation of a small fixture must parse or raise ValueError
    # -- never crash (nlohmann is bounds-safe and the whole reader body is wrapped).
    base = _sfm(
        views=[_view(0, "a.jpg", 0, 0)],
        intrinsics=[_intr(0, "pinhole_radial_k1", 800.0, 320.0, 240.0,
                          disto=("disto_k1", [0.1]), poly_id=2147483649)],
        extrinsics=[_extr(0, _PERM, [1, 2, 3])],
        structure=[_struct(0, [1, 2, 3], [(0, 0, 10.0, 20.0)])],
    )
    for i in range(len(base)):
        for repl in (0x00, 0x22, 0x7D, 0x39, 0xFF, 0x2D):  # NUL " } 9 0xFF -
            mutated = base[:i] + bytes([repl]) + base[i + 1:]
            try:
                _core.read_openmvg(mutated)
            except ValueError:
                pass


# ==========================================================================
# numpy / torch interop + registry integration
# ==========================================================================
def test_zero_copy_views_and_torch():
    R = _core.read_openmvg(CANONICAL)
    xyz = R.xyz  # zero-copy view; R kept alive by reference_internal
    assert isinstance(xyz, np.ndarray) and xyz.shape == (R.num_points3D, 3)
    assert xyz.dtype == np.float64
    torch = pytest.importorskip("torch")
    assert np.array_equal(torch.from_dlpack(R.xyz).numpy(), np.asarray(R.xyz))


def _find_openmvg_codec():
    try:
        from sceneio.io import registry
    except Exception:
        return None
    for c in registry.REGISTRY.values():
        if "sfm_data.json" in getattr(c, "filenames", ()) and c.record is _core.Reconstruction:
            return c
    return None


def test_registry_detect_and_roundtrip(tmp_path):
    codec = _find_openmvg_codec()
    if codec is None:
        pytest.skip("openmvg codec not wired into the registry yet (integrator step)")
    from sceneio.io import read as io_read
    from sceneio.io import registry
    from sceneio.io import write as io_write

    R = _core.read_openmvg(CANONICAL)
    out = tmp_path / "sfm_data.json"
    io_write(R, str(out), format=codec.id)
    assert registry.detect(str(out)) == codec.id  # filename match
    R2 = io_read(str(out))  # detected by filename, no explicit format
    assert (R2.num_cameras, R2.num_images, R2.num_points3D) == (
        R.num_cameras, R.num_images, R.num_points3D)
    np.testing.assert_array_equal(np.asarray(R2.xyz), np.asarray(R.xyz))
    np.testing.assert_array_equal(np.asarray(R2.quaternions), np.asarray(R.quaternions))
