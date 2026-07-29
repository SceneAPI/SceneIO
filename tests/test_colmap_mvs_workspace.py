"""COLMAP dense-workspace topology, configuration, and lazy I/O coverage."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.colmap_mvs import (
    ColmapMvsError,
    PatchMatchProblem,
    PmvsVisibilityGraph,
    ProjectionMatrix,
    inspect_workspace,
    open_cmp_mvs_workspace,
    open_pmvs_workspace,
    open_workspace,
    read_fusion_config,
    read_image_name_list,
    read_patch_match_config,
    read_pmvs_visibility,
    read_projection_matrix,
    write_fusion_config,
    write_image_name_list,
    write_patch_match_config,
    write_pmvs_visibility,
    write_projection_matrix,
)


def _reconstruction():
    return _core.read_nvm(
        b"NVM_V3\n2\n"
        b"nested/a.jpg 800 1 0 0 0 0 0 0 0 0\n"
        b"b.jpg 810 1 0 0 0 1 2 3 0 0\n"
        b"0\n0\n"
    )


def _workspace_root(tmp_path: Path, *, numbered_sparse: bool = False) -> Path:
    root = tmp_path / "workspace"
    sparse = root / "sparse"
    if numbered_sparse:
        sparse /= "0"
    sparse.mkdir(parents=True)
    sceneio.write(_reconstruction(), sparse, format="colmap_sparse")
    for name in ("nested/a.jpg", "b.jpg"):
        target = root / "images" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"opaque-image-payload")
    for directory in (
        "depth_maps",
        "normal_maps",
        "consistency_graphs",
    ):
        (root / "stereo" / directory).mkdir(parents=True)
    problems = (
        PatchMatchProblem(
            "nested/a.jpg",
            "explicit",
            source_images=("b.jpg",),
        ),
        PatchMatchProblem("b.jpg", "auto", max_source_images=20),
    )
    write_patch_match_config(
        problems,
        root / "stereo" / "patch-match.cfg",
        image_names=("nested/a.jpg", "b.jpg"),
    )
    write_fusion_config(
        ("b.jpg", "nested/a.jpg"),
        root / "stereo" / "fusion.cfg",
        known_image_names=("nested/a.jpg", "b.jpg"),
    )
    return root


def _dense_records():
    depth = _core.depth_map(
        np.array([[1.0, 2.0], [3.0, 4.0]], np.float32),
        unit="unknown",
        invalid_policy="nonpositive",
        depth_convention="camera_z",
    )
    normal = _core.normal_map(
        np.array(
            [
                [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                [[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0]],
            ],
            np.float32,
        )
    )
    consistency = _core.consistency_graph(
        2,
        2,
        np.array([0, 1], np.uint32),
        np.array([1, 0], np.uint32),
        np.array([0, 2, 3], np.uint64),
        np.array([1, 0, 1], np.uint32),
    )
    return depth, normal, consistency


def test_patch_match_config_exact_modes_comments_and_guarded_write(tmp_path):
    source = tmp_path / "patch-match.cfg"
    source.write_text(
        "# generated\n\n"
        "nested/a.jpg\n"
        "__all__\n"
        "b.jpg\n"
        "__auto__, 7\n"
        "c.jpg\n"
        ", nested/a.jpg; ; b.jpg,,\n",
        encoding="utf-8",
    )
    problems = read_patch_match_config(source)
    assert problems == (
        PatchMatchProblem("nested/a.jpg", "all"),
        PatchMatchProblem("b.jpg", "auto", max_source_images=7),
        PatchMatchProblem(
            "c.jpg",
            "explicit",
            source_images=("nested/a.jpg", "b.jpg"),
        ),
    )
    output = tmp_path / "roundtrip.cfg"
    write_patch_match_config(problems, output)
    assert output.read_bytes() == (
        b"nested/a.jpg\n__all__\n"
        b"b.jpg\n__auto__, 7\n"
        b"c.jpg\nnested/a.jpg, b.jpg\n"
    )

    output.write_bytes(b"sentinel")
    with pytest.raises(ColmapMvsError, match="positive limit"):
        write_patch_match_config(
            (PatchMatchProblem("a.jpg", "auto", max_source_images=-1),),
            output,
        )
    assert output.read_bytes() == b"sentinel"

    source.write_text("a.jpg\n", encoding="utf-8")
    with pytest.raises(ColmapMvsError, match="without a source line"):
        read_patch_match_config(source)

    for problem, match in (
        (PatchMatchProblem("a.jpg", "auto", max_source_images=0), "positive"),
        (
            PatchMatchProblem(
                "a.jpg",
                "explicit",
                source_images=("b.jpg", "b.jpg"),
            ),
            "unique",
        ),
        (
            PatchMatchProblem(
                "a.jpg",
                "explicit",
                source_images=("a.jpg",),
            ),
            "cannot also be a source",
        ),
    ):
        with pytest.raises(ColmapMvsError, match=match):
            write_patch_match_config((problem,), output)
    with pytest.raises(ColmapMvsError, match="resolve at least one"):
        write_patch_match_config(
            (PatchMatchProblem("a.jpg", "all"),),
            output,
            image_names=("a.jpg",),
        )


def test_fusion_config_preserves_order_and_rejects_unknown_names(tmp_path):
    path = tmp_path / "fusion.cfg"
    write_fusion_config(("b.jpg", "nested/a.jpg", "b.jpg"), path)
    assert read_fusion_config(path) == (
        "b.jpg",
        "nested/a.jpg",
        "b.jpg",
    )
    with pytest.raises(ColmapMvsError, match="not in the sparse model"):
        read_fusion_config(path, image_names=("nested/a.jpg",))


@pytest.mark.parametrize("numbered_sparse", [False, True])
def test_workspace_is_lazy_maps_nested_names_and_exact_roundtrips(
    tmp_path,
    numbered_sparse,
):
    root = _workspace_root(tmp_path, numbered_sparse=numbered_sparse)
    workspace = open_workspace(root)
    assert workspace.image_names == ("nested/a.jpg", "b.jpg")
    assert workspace.image_ids == (1, 2)
    assert workspace.fusion_images == ("b.jpg", "nested/a.jpg")
    assert len(workspace.patch_match_problems) == 2
    assert workspace.map_set("nested/a.jpg").depth_path == (
        root
        / "stereo"
        / "depth_maps"
        / "nested"
        / "a.jpg.geometric.bin"
    )

    depth, normal, consistency = _dense_records()
    workspace.write_depth("nested/a.jpg", depth)
    workspace.write_normal(0, normal)
    workspace.write_consistency(0, consistency)
    np.testing.assert_array_equal(workspace.read_depth(0).depth, depth.depth)
    np.testing.assert_array_equal(workspace.read_normal(0).normals, normal.normals)
    decoded_graph = workspace.read_consistency(0)
    np.testing.assert_array_equal(
        decoded_graph.image_indices,
        consistency.image_indices,
    )

    # Opening touches neither the opaque media payload nor dense payloads.
    lazy_maps = workspace.map_set(1)
    lazy_maps.depth_path.write_bytes(b"not-a-dense-map")
    lazy_maps.normal_path.write_bytes(b"not-a-dense-map")
    reopened = open_workspace(root)
    assert reopened.num_images == 2
    with pytest.raises(sceneio.FormatError):
        reopened.validate()


def test_workspace_validation_checks_dimensions_indices_and_fused_counts(tmp_path):
    root = _workspace_root(tmp_path)
    workspace = open_workspace(root)
    depth, normal, consistency = _dense_records()
    workspace.write_depth(0, depth)
    workspace.write_normal(0, normal)
    workspace.write_consistency(0, consistency)

    points = _core.point_cloud(
        np.array([[1, 2, 3], [4, 5, 6]], np.float32)
    )
    sceneio.write(points, workspace.fused_path, format="ply")
    visibility = _core.point_visibility(
        np.array([0, 1, 2], np.uint64),
        np.array([0, 1], np.uint32),
    )
    workspace.write_visibility(visibility)

    shallow = workspace.validate()
    assert (
        shallow.num_images,
        shallow.num_map_sets,
        shallow.num_depth_maps,
        shallow.num_normal_maps,
        shallow.num_consistency_graphs,
        shallow.fused_point_count,
        shallow.visibility_point_count,
        shallow.deep,
    ) == (2, 1, 1, 1, 1, 2, 2, False)
    assert workspace.validate(deep=True).deep
    inspection = inspect_workspace(root, deep=True)
    assert inspection.num_images == 2
    assert len(inspection.map_sets) == 1
    assert inspection.fused_path == workspace.fused_path

    invalid_graph = _core.consistency_graph(
        2,
        2,
        np.array([0], np.uint32),
        np.array([0], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([2], np.uint32),
    )
    target = workspace.map_set(0).consistency_path
    sentinel = target.read_bytes()
    with pytest.raises(ColmapMvsError, match=r"outside 0\.\.1"):
        workspace.write_consistency(0, invalid_graph)
    assert target.read_bytes() == sentinel

    wrong_count = _core.point_visibility(
        np.array([0, 0], np.uint64),
        np.empty((0,), np.uint32),
    )
    with pytest.raises(ColmapMvsError, match=r"does not match fused\.ply"):
        workspace.write_visibility(wrong_count)


def test_modern_workspace_uses_registered_frame_camera_order(tmp_path):
    root = tmp_path / "modern"
    sparse = root / "sparse"
    sparse.mkdir(parents=True)
    (sparse / "cameras.txt").write_bytes(
        b"1 SIMPLE_PINHOLE 640 480 500 320 240\n"
        b"2 SIMPLE_PINHOLE 640 480 500 320 240\n"
    )
    (sparse / "images.txt").write_bytes(
        b"100 1 0 0 0 0 0 0 1 first.jpg\n\n"
        b"200 1 0 0 0 0 0 0 2 second.jpg\n\n"
    )
    (sparse / "points3D.txt").write_bytes(b"")
    (sparse / "rigs.txt").write_bytes(
        b"7 2 CAMERA 1 CAMERA 2 0\n"
    )
    (sparse / "frames.txt").write_bytes(
        b"11 7 1 0 0 0 0 0 0 1 CAMERA 2 200\n"
        b"12 7 1 0 0 0 0 0 0 1 CAMERA 1 100\n"
    )
    (root / "images").mkdir()
    (root / "stereo").mkdir()

    workspace = open_workspace(root)
    assert tuple(workspace.reconstruction.image_names) == (
        "first.jpg",
        "second.jpg",
    )
    assert workspace.image_ids == (200, 100)
    assert workspace.image_names == ("second.jpg", "first.jpg")
    assert workspace.map_set(0).image_id == 200
    assert workspace.map_set(1).image_id == 100


def test_workspace_deep_read_rejects_out_of_domain_visibility(tmp_path):
    root = _workspace_root(tmp_path)
    workspace = open_workspace(root)
    points = _core.point_cloud(np.array([[1, 2, 3]], np.float32))
    sceneio.write(points, workspace.fused_path, format="ply")
    invalid = _core.point_visibility(
        np.array([0, 1], np.uint64),
        np.array([2], np.uint32),
    )
    sceneio.write(
        invalid,
        workspace.visibility_path,
        format="colmap_fused_visibility",
    )
    assert workspace.validate().visibility_point_count == 1
    with pytest.raises(ColmapMvsError, match=r"outside 0\.\.1"):
        workspace.validate(deep=True)


def test_workspace_rejects_ambiguous_sparse_models_and_unsafe_names(tmp_path):
    root = _workspace_root(tmp_path, numbered_sparse=True)
    second = root / "sparse" / "1"
    second.mkdir()
    sceneio.write(_reconstruction(), second, format="colmap_sparse")
    with pytest.raises(ColmapMvsError, match="one complete COLMAP sparse model"):
        open_workspace(root)

    unsafe = tmp_path / "unsafe"
    (unsafe / "sparse").mkdir(parents=True)
    reconstruction = _core.read_nvm(
        b"NVM_V3\n1\n../a.jpg 800 1 0 0 0 0 0 0 0 0\n0\n0\n"
    )
    sceneio.write(
        reconstruction,
        unsafe / "sparse",
        format="colmap_sparse",
    )
    (unsafe / "images").mkdir()
    (unsafe / "stereo").mkdir()
    with pytest.raises(ColmapMvsError, match="safe relative path"):
        open_workspace(unsafe)


def test_colmap_mvs_namespace_is_lazy_and_public():
    assert sceneio.colmap_mvs.open_workspace is open_workspace
    assert "colmap_mvs" in sceneio.__all__


def test_projection_matrix_preserves_source_text_and_guards_values(tmp_path):
    source = tmp_path / "00000000.txt"
    payload = (
        b"CONTOUR\r\n"
        b"1.0 0 -0 4.5\r\n"
        b"0 2.0 0 -3\r\n"
        b"0 0 1 7\r\n"
    )
    source.write_bytes(payload)
    projection = read_projection_matrix(source)
    assert projection.values.dtype == np.float64
    assert not projection.values.flags.writeable
    np.testing.assert_array_equal(
        projection.values,
        np.array(
            [[1, 0, -0.0, 4.5], [0, 2, 0, -3], [0, 0, 1, 7]],
            np.float64,
        ),
    )
    output = tmp_path / "unchanged.txt"
    write_projection_matrix(projection, output)
    assert output.read_bytes() == payload

    changed = ProjectionMatrix(
        np.array(
            [[2, 0, 0, 4.5], [0, 2, 0, -3], [0, 0, 1, 7]],
            np.float64,
        )
    )
    write_projection_matrix(changed, output)
    assert read_projection_matrix(output).values[0, 0] == 2
    output.write_bytes(b"sentinel")
    invalid = ProjectionMatrix(np.zeros((4, 3), np.float64))
    with pytest.raises(ColmapMvsError, match=r"shape \(3,4\)"):
        write_projection_matrix(invalid, output)
    assert output.read_bytes() == b"sentinel"


def test_pmvs_workspace_keeps_media_opaque_and_visibility_domain_raw(tmp_path):
    export = tmp_path / "export" / "pmvs"
    (export / "visualize").mkdir(parents=True)
    (export / "txt").mkdir()
    projection = ProjectionMatrix(
        np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
            np.float64,
        )
    )
    for index in range(2):
        (export / "visualize" / f"{index:08d}.jpg").write_bytes(
            b"opaque-not-jpeg"
        )
        write_projection_matrix(
            projection,
            export / "txt" / f"{index:08d}.txt",
        )
    graph = PmvsVisibilityGraph(
        2,
        np.array([1, 0], np.uint32),
        np.array([0, 2, 3], np.uint64),
        np.array([7, 3, 9], np.uint32),
    )
    write_pmvs_visibility(graph, export / "vis.dat")
    (export / "option-all").write_text("timages 2 0 1\n", encoding="utf-8")
    write_image_name_list(
        ("nested/a.jpg", "b.jpg"),
        export / "bundle.rd.out.list.txt",
    )

    workspace = open_pmvs_workspace(tmp_path / "export")
    assert workspace.profile == "pmvs"
    assert workspace.model_source == "raw_pmvs"
    assert workspace.num_images == 2
    assert workspace.images[0].image_path.read_bytes() == b"opaque-not-jpeg"
    np.testing.assert_array_equal(
        workspace.read_projection(1).values,
        projection.values,
    )
    decoded = workspace.read_visibility()
    assert decoded.value_domain == "raw_colmap_image_id_or_mvs_index"
    np.testing.assert_array_equal(decoded.row_indices, [1, 0])
    np.testing.assert_array_equal(decoded.visible_values, [7, 3, 9])
    assert workspace.option_paths == (export / "option-all",)
    assert workspace.read_bundle_image_names() == ("nested/a.jpg", "b.jpg")

    canonical = tmp_path / "vis.dat"
    write_pmvs_visibility(decoded, canonical)
    reread = read_pmvs_visibility(canonical)
    np.testing.assert_array_equal(reread.offsets, decoded.offsets)
    np.testing.assert_array_equal(
        reread.visible_values,
        decoded.visible_values,
    )
    assert read_image_name_list(export / "bundle.rd.out.list.txt") == (
        "nested/a.jpg",
        "b.jpg",
    )


def test_pmvs_visibility_literal_domain_bounds_and_numeric_errors(tmp_path):
    source = tmp_path / "vis.dat"
    source.write_bytes(
        b"VISDATA\r\n"
        b"2\r\n"
        b"1 2 4294967294 0\r\n"
        b"0 0\r\n"
    )
    graph = read_pmvs_visibility(source)
    np.testing.assert_array_equal(graph.row_indices, [1, 0])
    np.testing.assert_array_equal(graph.offsets, [0, 2, 2])
    np.testing.assert_array_equal(graph.visible_values, [4294967294, 0])
    canonical = tmp_path / "canonical.dat"
    write_pmvs_visibility(graph, canonical)
    assert canonical.read_bytes() == (
        b"VISDATA\n2\n1 2 4294967294 0\n0 0\n"
    )

    source.write_bytes(b"VISDATA\n1\n0 1 4294967295\n")
    with pytest.raises(ColmapMvsError, match="invalid image sentinel"):
        read_pmvs_visibility(source)
    source.write_bytes(b"VISDATA\n1\n00000000000 0\n")
    with pytest.raises(ColmapMvsError, match="numeric token exceeds uint32"):
        read_pmvs_visibility(source)

    invalid = PmvsVisibilityGraph(
        1,
        np.array([0], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([0xFFFFFFFF], np.uint32),
    )
    canonical.write_bytes(b"sentinel")
    with pytest.raises(ColmapMvsError, match="invalid image sentinel"):
        write_pmvs_visibility(invalid, canonical)
    assert canonical.read_bytes() == b"sentinel"

    import json
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import json
        import pathlib
        import tempfile
        import threading
        import time

        import numpy as np
        import psutil

        from sceneio.colmap_mvs import (
            ColmapMvsError,
            PmvsVisibilityGraph,
            write_pmvs_visibility,
        )

        count = 2_000_000
        rows = np.arange(count, dtype=np.uint32)
        rows[-1] = 0
        graph = PmvsVisibilityGraph(
            count,
            rows,
            np.zeros((count + 1,), np.uint64),
            np.empty((0,), np.uint32),
        )
        process = psutil.Process()
        baseline = process.memory_info().rss
        peak = [baseline]
        stop = threading.Event()

        def sample():
            while not stop.is_set():
                peak[0] = max(peak[0], process.memory_info().rss)
                time.sleep(0.001)

        thread = threading.Thread(target=sample)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                try:
                    write_pmvs_visibility(
                        graph, pathlib.Path(directory) / "vis.dat"
                    )
                except ColmapMvsError:
                    pass
                else:
                    raise AssertionError("duplicate row was accepted")
        finally:
            stop.set()
            thread.join()
        print(json.dumps({"delta": peak[0] - baseline}))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["delta"] < 64 * 1024 * 1024


def test_pmvs_bundler_profile_does_not_require_projection_files(tmp_path):
    root = tmp_path / "pmvs"
    (root / "visualize").mkdir(parents=True)
    (root / "visualize" / "00000000.jpg").write_bytes(b"opaque")
    (root / "bundle.rd.out").write_bytes(
        b"# Bundle file v0.3\n"
        b"1 0\n"
        b"1000 0 0\n"
        b"1 0 0\n"
        b"0 1 0\n"
        b"0 0 1\n"
        b"0 0 0\n"
    )

    workspace = open_pmvs_workspace(root)
    assert workspace.model_source == "bundler"
    assert workspace.num_images == 1
    assert workspace.images[0].projection_path is None
    with pytest.raises(ColmapMvsError, match="Bundler-profile"):
        workspace.read_projection(0)
    assert workspace.read_bundle().num_images == 1

    (root / "bundle.rd.out").write_bytes(b"# Bundle file v0.3\n0 0\n")
    with pytest.raises(ColmapMvsError, match="declares 0 images"):
        open_pmvs_workspace(root)


def test_cmp_mvs_workspace_requires_contiguous_numbered_pairs(tmp_path):
    root = tmp_path / "cmp"
    root.mkdir()
    projection = ProjectionMatrix(
        np.array(
            [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3]],
            np.float64,
        )
    )
    for index in (1, 2):
        (root / f"{index:05d}.jpg").write_bytes(b"opaque")
        write_projection_matrix(
            projection,
            root / f"{index:05d}_P.txt",
        )
    workspace = open_cmp_mvs_workspace(root)
    assert workspace.profile == "cmp_mvs"
    assert workspace.model_source == "projection_files"
    assert workspace.num_images == 2
    np.testing.assert_array_equal(
        workspace.read_projection(0).values,
        projection.values,
    )
    with pytest.raises(ColmapMvsError, match="available only for a PMVS"):
        workspace.read_visibility()

    (root / "00002.jpg").rename(root / "00003.jpg")
    with pytest.raises(ColmapMvsError, match="numbering must be contiguous"):
        open_cmp_mvs_workspace(root)
