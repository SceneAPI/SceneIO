"""Smoke contracts for the large Gaussian/mesh/reconstruction cases."""

from __future__ import annotations

import numpy as np
import pytest

from bench.io_bench.large import cases_scene
from sceneio import _core


def _spz_seed(tmp_path):
    cloud = _core.gaussian_cloud(
        np.asarray([[0, 1, 2], [1, 2, 3]], dtype=np.float32),
        np.zeros((2, 3), dtype=np.float32),
        np.asarray([[1, 0, 0, 0], [0.5, 0.5, 0.5, 0.5]], dtype=np.float32),
        np.asarray([0, 1], dtype=np.float32),
        np.zeros((2, 3), dtype=np.float32),
    )
    path = tmp_path / "seed.spz"
    path.write_bytes(bytes(_core.write_spz(cloud, version=3)))
    return path


def _glb_seed(tmp_path):
    trimesh = pytest.importorskip("trimesh")
    mesh = trimesh.Trimesh(
        vertices=np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
        faces=np.asarray([[0, 1, 2]], dtype=np.uint32),
        vertex_colors=np.asarray(
            [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]],
            dtype=np.uint8,
        ),
        process=False,
    )
    path = tmp_path / "BoxVertexColors.glb"
    path.write_bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene(mesh)))
    return path


def _tum_seed(tmp_path):
    path = tmp_path / "freiburg1_xyz.txt"
    path.write_text(
        "0.0 0 0 0 0 0 0 1\n"
        "1.0 0.1 0 0 0 0 0 1\n"
        "2.0 0.2 0 0 0 0 0 1\n",
        encoding="utf-8",
    )
    return path


def test_scene_case_definitions_are_runner_compatible():
    definitions = cases_scene.case_definitions()
    assert set(definitions) == {"spz_racoon_v4", "glb_box_grid", "colmap_tum_tracks"}
    assert all(definition.standard_logical_bytes == 256 * 1024 * 1024 for definition in definitions.values())
    assert definitions["spz_racoon_v4"].providers == ("sceneio", "niantic_spz", "gsply")


def test_spz_smoke_is_derived_and_semantically_validated(tmp_path):
    artifact = cases_scene.prepare_case(
        "spz_racoon_v4",
        tier="smoke",
        cache=tmp_path / "cache",
        sources=_spz_seed(tmp_path),
    )
    assert artifact.logical_bytes >= cases_scene.SMOKE_LOGICAL_BYTES
    assert artifact.logical_bytes < 2 * cases_scene.SMOKE_LOGICAL_BYTES
    assert artifact.acquisition_mode == "derived_fixture"
    assert artifact.derivation["output_profile"] == "SPZ v4 flags=0"
    assert artifact.metadata["coordinate_profile"] == (
        "unspecified:spatial/raw-preserved"
    )
    validation = cases_scene.validate_common_input(artifact)
    assert validation["status"] in {"pass", "unavailable"}
    assert cases_scene.provider_fixture("spz_racoon_v4", "sceneio", artifact).num_gaussians


def test_trimesh_native_fixture_can_be_written(tmp_path):
    artifact = cases_scene.prepare_case(
        "glb_box_grid",
        tier="smoke",
        cache=tmp_path / "cache",
        sources=_glb_seed(tmp_path),
    )
    value = cases_scene.provider_fixture("glb_box_grid", "trimesh", artifact)
    output = tmp_path / "trimesh.glb"
    cases_scene.provider_adapters("glb_box_grid")["trimesh"].write(value, output)
    assert output.stat().st_size > 0


def test_glb_smoke_uses_trimesh_common_input(tmp_path):
    artifact = cases_scene.prepare_case(
        "glb_box_grid",
        tier="smoke",
        cache=tmp_path / "cache",
        sources=_glb_seed(tmp_path),
    )
    assert artifact.metadata["color_dtype"] == "uint8"
    assert artifact.metadata["grid_repeats"] > 1
    assert artifact.metadata["common_writer"] == "trimesh"
    assert artifact.metadata["coordinate_frame"] == "opengl"
    assert artifact.metadata["instance_translation"] == [0.75, -1.25, 2.5]
    scene = cases_scene.provider_fixture("glb_box_grid", "sceneio", artifact)
    node_names = list(scene.node_names)
    instance_index = node_names.index("box_grid")
    np.testing.assert_allclose(
        np.asarray(scene.node_local_transforms)[instance_index, :3, 3],
        artifact.metadata["instance_translation"],
        rtol=0,
        atol=0,
    )
    assert int(np.asarray(scene.node_meshes)[instance_index]) == 0
    validation = cases_scene.validate_common_input(artifact)
    assert validation["status"] == "pass"


def test_colmap_smoke_has_two_observation_tracks_and_pose_contract(tmp_path):
    artifact = cases_scene.prepare_case(
        "colmap_tum_tracks",
        tier="smoke",
        cache=tmp_path / "cache",
        sources=_tum_seed(tmp_path),
    )
    assert artifact.metadata["track_length"] == 2
    assert artifact.metadata["quaternion_order"] == "wxyz"
    assert artifact.metadata["pose_convention"] == "world_to_camera"
    assert artifact.metadata["camera_frame"] == "opencv"
    assert artifact.metadata["tum_parser"] == "independent_text_v1"
    pycolmap = pytest.importorskip("pycolmap")
    reference = pycolmap.Reconstruction(str(artifact.path))
    assert reference.num_points3D() > 0
    assert all(point.track.length() == 2 for point in reference.points3D.values())
    canonical = cases_scene._canonical_colmap(reference)
    assert canonical["obs_xy"].shape[0] == 2 * reference.num_points3D()
    assert canonical["obs_off"][-1] == canonical["obs_xy"].shape[0]
    assert cases_scene.validate_common_input(artifact)["status"] == "pass"
    import sceneio

    selected = sceneio.read_partial(
        artifact.path, format="colmap_sparse", image_id=1
    )
    assert selected.num_images == 1
    assert cases_scene.partial_read_check(artifact)["status"] == "pass"


def test_scene_cross_matrix_is_directional_and_propagates_mismatch(
    tmp_path, monkeypatch
):
    common = tmp_path / "common.glb"
    common.write_text("expected", encoding="utf-8")
    sceneio_output = tmp_path / "sceneio.glb"
    reference_output = tmp_path / "trimesh.glb"
    sceneio_output.write_text("expected", encoding="utf-8")
    reference_output.write_text("expected", encoding="utf-8")
    artifact = cases_scene.CaseArtifact(
        case_id="glb_box_grid",
        tier="smoke",
        path=common,
        logical_bytes=8,
        encoded_bytes=8,
    )

    def read(path):
        return path.read_text(encoding="utf-8")

    adapters = {
        name: cases_scene.ProviderAdapter(name, read, lambda value, path: None)
        for name in ("sceneio", "trimesh")
    }

    def compare(case_id, left, right):
        assert case_id == "glb_box_grid"
        if left != right:
            raise AssertionError("semantic mismatch")

    monkeypatch.setattr(cases_scene, "provider_adapters", lambda case_id: adapters)
    monkeypatch.setattr(cases_scene, "compare_case", compare)
    outputs = {"sceneio": sceneio_output, "trimesh": reference_output}
    rows = cases_scene.cross_read_matrix(artifact, outputs)
    assert {
        (row["writer_provider"], row["reader_provider"])
        for row in rows
    } == {
        ("sceneio", "sceneio"),
        ("sceneio", "trimesh"),
        ("trimesh", "sceneio"),
        ("trimesh", "trimesh"),
    }
    assert all(row["status"] == "pass" for row in rows)

    reference_output.write_text("wrong", encoding="utf-8")
    rows = cases_scene.cross_read_matrix(artifact, outputs)
    assert {
        row["reader_provider"]
        for row in rows
        if row["writer_provider"] == "trimesh" and row["status"] == "fail"
    } == {"sceneio", "trimesh"}
