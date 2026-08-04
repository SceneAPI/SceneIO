"""Offline integrity checks for the procedural Kubric oracle fixture."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import png
import pytest
import tifffile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "kubric_procedural_tiny_v1.json"
TOOL_PATH = ROOT / "tools" / "generate_kubric_oracle.py"
OUTPUT_PATH = ROOT / "tests" / "fixtures" / "kubric_procedural_tiny_v1"
REVISION = "61f2422c84bab75006df33c6989e0b483db3ccfe"
_CAMERA_ROTATION = np.array(
    [
        [0.894427190999916, -0.182574185835055, 0.408248290463863],
        [0.447213595499958, 0.365148371670111, -0.816496580927726],
        [0.0, 0.912870929175277, 0.408248290463863],
    ],
    dtype=np.float64,
)
_CAMERA_QUATERNION = [
    0.816673718986642,
    0.529393645802899,
    0.124972887265930,
    0.192790513118408,
]
_IMAGE_POSITIONS = np.array(
    [
        [[0.369822327390335, 0.456819840006689], [0.425378398160059, 0.467843406318123]],
        [[0.642775511894471, 0.501821495582844], [0.578695769756490, 0.489290862176725]],
    ],
    dtype=np.float64,
)


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _write_png(path: Path, values: np.ndarray, *, bitdepth: int) -> None:
    height, width, planes = values.shape
    writer = png.Writer(
        width,
        height,
        greyscale=planes in {1, 2},
        alpha=planes in {2, 4},
        bitdepth=bitdepth,
    )
    with path.open("wb") as stream:
        writer.write(stream, values.reshape(height, width * planes).tolist())


def _read_png_for_test(path: Path) -> tuple[np.ndarray, int]:
    width, height, rows, info = png.Reader(filename=str(path)).read()
    planes = int(info["planes"])
    values = np.vstack([np.asarray(row, dtype=np.uint16) for row in rows])
    return values.reshape(height, width, planes), int(info["bitdepth"])


def _write_structurally_valid_output(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    rgba = np.zeros((32, 32, 4), dtype=np.uint8)
    rgba[..., 0] = np.arange(32, dtype=np.uint8)[None, :]
    rgba[..., 1] = np.arange(32, dtype=np.uint8)[:, None]
    rgba[..., 3] = 255
    segmentation = np.zeros((32, 32, 1), dtype=np.uint8)
    segmentation[11:20, 8:17, 0] = 1
    segmentation[13:21, 18:26, 0] = 2
    image_positions = _IMAGE_POSITIONS
    minimum, maximum = -3.0, 3.0
    flow = np.zeros((32, 32, 3), dtype=np.uint16)
    for object_index, renderer_id in enumerate((1, 2)):
        delta_row_column = (
            image_positions[object_index, 1] - image_positions[object_index, 0]
        )[[1, 0]] * 32.0
        encoded = np.rint(
            (delta_row_column - minimum) / (maximum - minimum) * 65535.0
        ).astype(np.uint16)
        flow[segmentation[..., 0] == renderer_id, :2] = encoded
    flow[0, 0, 0] = np.iinfo(np.uint16).min
    flow[0, 1, 1] = np.iinfo(np.uint16).max
    for frame in range(2):
        _write_png(output / f"rgba_{frame:05d}.png", rgba, bitdepth=8)
        _write_png(
            output / f"segmentation_{frame:05d}.png",
            segmentation,
            bitdepth=8,
        )
        _write_png(
            output / f"forward_flow_{frame:05d}.png",
            flow,
            bitdepth=16,
        )
        tifffile.imwrite(
            output / f"depth_{frame:05d}.tiff",
            np.full((32, 32), 2.0 + frame, dtype=np.float32),
        )
    (output / "data_ranges.json").write_text(
        json.dumps({"forward_flow": {"min": minimum, "max": maximum}}),
        encoding="utf-8",
    )
    camera_rotation = _CAMERA_ROTATION
    camera_matrix = np.eye(4, dtype=np.float64)
    camera_matrix[:3, :3] = camera_rotation
    camera_matrix[:3, 3] = [3.0, -6.0, 3.5]
    camera_quaternion = _CAMERA_QUATERNION
    visibility = [
        int(np.count_nonzero(segmentation[..., 0] == renderer_id))
        for renderer_id in (1, 2)
    ]
    (output / "metadata.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "seed": 20260804,
                    "resolution": [32, 32],
                    "frame_rate": 12,
                    "num_frames": 2,
                },
                "camera": {
                    "positions": [[3.0, -6.0, 3.5]] * 2,
                    "quaternions": [camera_quaternion] * 2,
                    "R": camera_matrix.tolist(),
                },
                "instances": [
                    {
                        "positions": [[-0.8, 0.0, 0.6], [-0.45, 0.0, 0.6]],
                        "quaternions": [[1.0, 0.0, 0.0, 0.0]] * 2,
                        "renderer_id": 1,
                        "visibility": [visibility[0]] * 2,
                        "image_positions": image_positions[0].tolist(),
                    },
                    {
                        "positions": [[0.8, 0.0, 0.65], [0.45, 0.0, 0.65]],
                        "quaternions": [[1.0, 0.0, 0.0, 0.0]] * 2,
                        "renderer_id": 2,
                        "visibility": [visibility[1]] * 2,
                        "image_positions": image_positions[1].tolist(),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (output / "runtime.json").write_text(
        json.dumps(
            {
                "schema": "sceneio.kubric_runtime/1",
                "kubric_revision": REVISION,
                "kubric_module": "kubric/__init__.py",
                "blender_version": "4.3.0",
                "python_version": "3.11.13",
                "dependency_versions": {},
                "render_layers": [
                    "rgba",
                    "forward_flow",
                    "depth",
                    "segmentation",
                ],
                "samples_per_pixel": 64,
            }
        ),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _generated_manifest(output: Path) -> dict[str, object]:
    document = _manifest()
    document["generated"] = True
    document["status"] = "generated"
    for artifact in document["artifacts"]:
        artifact["sha256"] = _sha256(output / artifact["path"])
    return document


def _run_verify(output: Path, manifest: Path = MANIFEST_PATH) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(TOOL_PATH),
            "verify",
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )


def test_kubric_fixture_is_pinned_compact_and_materialized() -> None:
    document = _manifest()
    assert document["schema"] == "sceneio.kubric_oracle/1"
    assert document["status"] == "generated"
    assert document["generated"] is True
    assert document["upstream"]["revision"] == REVISION
    assert document["upstream"]["license"] == "Apache-2.0"
    assert document["recipe"]["seed"] == 20260804
    assert document["recipe"]["resolution"] == "32x32"
    assert document["recipe"]["object_count"] == 2
    assert document["recipe"]["objects"] == ["cube", "sphere"]
    assert document["recipe"]["assets"]["mode"] == "procedural_only"
    assert document["recipe"]["assets"]["external_manifest"] is None
    assert document["recipe"]["assets"]["license"] == "Apache-2.0"
    assert document["recipe"]["assets"]["redistributed"] is False
    assert all(
        isinstance(item["sha256"], str) and len(item["sha256"]) == 64
        for item in document["artifacts"]
    )
    assert MANIFEST_PATH.stat().st_size < 32_000
    assert sum(path.stat().st_size for path in OUTPUT_PATH.iterdir()) < 64_000
    assert "gs://" not in json.dumps(document)
    assert document["runtime"]["blender_version"] == "4.3.0"
    assert document["runtime"]["python_version"] == "3.11"
    assert _run_verify(OUTPUT_PATH).returncode == 0


def test_offline_checker_needs_no_kubric_or_blender() -> None:
    result = subprocess.run(
        [sys.executable, str(TOOL_PATH), "check"],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)
    assert summary == {
        "artifacts": 11,
        "revision": REVISION,
        "schema": "sceneio.kubric_oracle/1",
    }


def test_hand_evaluated_renderer_mapping_is_independent() -> None:
    vector = _manifest()["hand_evaluated_label_vector"]
    assert vector["purpose"].startswith("independent rule vector")
    assert vector["taxonomy"]["identity"] == (
        "org.sceneio.kubric-procedural-fc2"
    )
    assert vector["taxonomy"]["version"] == REVISION
    renderer = np.asarray(vector["renderer_ids"], dtype=np.int32)
    expected_semantic = np.asarray(vector["semantic_ids"], dtype=np.int32)
    expected_instance = np.asarray(vector["instance_ids"], dtype=np.int64)
    valid = np.asarray(vector["valid"], dtype=np.bool_)
    mapping = {0: 0, 1: 4, 2: 9}
    semantic = np.full(renderer.shape, -1, dtype=np.int32)
    for renderer_id, semantic_id in mapping.items():
        semantic[renderer == renderer_id] = semantic_id

    np.testing.assert_array_equal(semantic, expected_semantic)
    np.testing.assert_array_equal(renderer.astype(np.int64), expected_instance)
    assert valid.shape == renderer.shape
    assert not bool(valid[2, 0])
    assert set(np.unique(semantic[valid])) <= set(mapping.values())


def test_verify_requires_a_generated_manifest_and_detects_hash_drift(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / MANIFEST_PATH.name
    recipe_only = _manifest()
    recipe_only["generated"] = False
    recipe_only["status"] = "recipe_only"
    for artifact in recipe_only["artifacts"]:
        artifact["sha256"] = None
    manifest_path.write_text(json.dumps(recipe_only), encoding="utf-8")
    output = tmp_path / "generated"
    _write_structurally_valid_output(output)

    unrecorded = _run_verify(output, manifest_path)
    assert unrecorded.returncode != 0
    assert "intentionally unrecorded" in (unrecorded.stderr + unrecorded.stdout)

    manifest_path.write_text(
        json.dumps(_generated_manifest(output)),
        encoding="utf-8",
    )
    assert _run_verify(output, manifest_path).returncode == 0
    changed = np.zeros((32, 32, 4), dtype=np.uint8)
    changed[..., 0] = 1
    changed[..., 3] = 255
    _write_png(output / "rgba_00000.png", changed, bitdepth=8)
    failed = _run_verify(output, manifest_path)
    assert failed.returncode != 0
    assert "hashes disagree" in (failed.stderr + failed.stdout)


def test_standalone_record_operation_is_not_available(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    _write_structurally_valid_output(output)
    failed = subprocess.run(
        [sys.executable, str(TOOL_PATH), "record", "--output", str(output)],
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "invalid choice" in (failed.stderr + failed.stdout)


def test_verify_refuses_structurally_invalid_or_extra_output(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    _write_structurally_valid_output(output)
    flow = np.zeros((32, 32, 3), dtype=np.uint16)
    flow[..., 2] = 1
    _write_png(output / "forward_flow_00000.png", flow, bitdepth=16)

    failed = _run_verify(output)
    assert failed.returncode != 0
    assert "padding channel" in (failed.stderr + failed.stdout)

    _write_structurally_valid_output(tmp_path / "second")
    (tmp_path / "second" / "unexpected.txt").write_text("extra", encoding="utf-8")
    failed = _run_verify(tmp_path / "second")
    assert failed.returncode != 0
    assert "unexpected" in (failed.stderr + failed.stdout)

    _write_structurally_valid_output(tmp_path / "third")
    runtime_path = tmp_path / "third" / "runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["unexpected"] = True
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    failed = _run_verify(tmp_path / "third")
    assert failed.returncode != 0
    assert "runtime fields" in (failed.stderr + failed.stdout)

    _write_structurally_valid_output(tmp_path / "fourth")
    metadata_path = tmp_path / "fourth" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["unexpected"] = True
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    failed = _run_verify(tmp_path / "fourth")
    assert failed.returncode != 0
    assert "metadata fields" in (failed.stderr + failed.stdout)

    _write_structurally_valid_output(tmp_path / "fifth")
    metadata_path = tmp_path / "fifth" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["camera"]["positions"][0][0] = float("nan")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    failed = _run_verify(tmp_path / "fifth")
    assert failed.returncode != 0
    assert "camera positions must be finite" in (failed.stderr + failed.stdout)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing-instance-ids", "background, cube, and sphere"),
        ("flow-range", "must span zero"),
        ("flow-extent", "span the declared uint16 range"),
        ("flow-order", "component order or direction"),
        ("flow-direction", "component order or direction"),
        ("camera-quaternion", "unit WXYZ"),
        ("camera-orientation", "fixed look-at recipe"),
        ("camera-look-at", "fixed look-at recipe"),
        ("camera-position", "fixed recipe"),
        ("renderer-id", "renderer id disagrees"),
        ("renderer-raster-order", "renderer ids disagree"),
        ("object-position", "instance 0 positions"),
        ("object-quaternion", "instance 1 quaternion"),
    ],
)
def test_verify_refuses_semantically_inconsistent_output(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    output = tmp_path / mutation
    _write_structurally_valid_output(output)
    if mutation == "missing-instance-ids":
        segmentation = np.zeros((32, 32, 1), dtype=np.uint8)
        for frame in range(2):
            _write_png(
                output / f"segmentation_{frame:05d}.png",
                segmentation,
                bitdepth=8,
            )
    elif mutation == "flow-range":
        (output / "data_ranges.json").write_text(
            json.dumps({"forward_flow": {"min": 100.0, "max": 200.0}}),
            encoding="utf-8",
        )
    elif mutation == "flow-extent":
        flow = np.full((32, 32, 3), 32768, dtype=np.uint16)
        flow[..., 2] = 0
        for frame in range(2):
            _write_png(output / f"forward_flow_{frame:05d}.png", flow, bitdepth=16)
    elif mutation in {"flow-order", "flow-direction"}:
        for frame in range(2):
            flow_path = output / f"forward_flow_{frame:05d}.png"
            flow, _ = _read_png_for_test(flow_path)
            if mutation == "flow-order":
                flow[..., :2] = flow[..., [1, 0]]
            else:
                flow[..., :2] = np.iinfo(np.uint16).max - flow[..., :2]
            _write_png(flow_path, flow, bitdepth=16)
    elif mutation == "renderer-raster-order":
        for frame in range(2):
            segmentation_path = output / f"segmentation_{frame:05d}.png"
            segmentation, _ = _read_png_for_test(segmentation_path)
            swapped = segmentation.copy()
            swapped[segmentation == 1] = 2
            swapped[segmentation == 2] = 1
            _write_png(segmentation_path, swapped, bitdepth=8)
    else:
        metadata_path = output / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if mutation == "camera-quaternion":
            metadata["camera"]["quaternions"][0] = [0.0, 0.0, 0.0, 0.0]
        elif mutation == "camera-orientation":
            metadata["camera"]["quaternions"] = [[0.0, 1.0, 0.0, 0.0]] * 2
        elif mutation == "camera-look-at":
            matrix = [
                [-1.0, 0.0, 0.0, 3.0],
                [0.0, 1.0, 0.0, -6.0],
                [0.0, 0.0, -1.0, 3.5],
                [0.0, 0.0, 0.0, 1.0],
            ]
            metadata["camera"]["R"] = matrix
            metadata["camera"]["quaternions"] = [[0.0, 0.0, 1.0, 0.0]] * 2
        elif mutation == "camera-position":
            metadata["camera"]["positions"][1][0] = 4.0
        elif mutation == "renderer-id":
            metadata["instances"][0]["renderer_id"] = 2
        elif mutation == "object-position":
            metadata["instances"][0]["positions"][1][0] = -0.8
        else:
            metadata["instances"][1]["quaternions"][0] = [0.0, 1.0, 0.0, 0.0]
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    failed = _run_verify(output)
    assert failed.returncode != 0
    assert message in (failed.stderr + failed.stdout)


def test_generate_validates_then_atomically_records_hashes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = importlib.util.spec_from_file_location("sceneio_kubric_tool", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest_path = tmp_path / MANIFEST_PATH.name
    manifest_path.write_text(MANIFEST_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    upstream = tmp_path / "kubric"
    upstream.mkdir()
    output = tmp_path / "generated"
    monkeypatch.setattr(module, "_require_pinned_clean_checkout", lambda _path: None)

    def fake_render(command, *, cwd, check, env):
        assert "_render" in command
        assert cwd == upstream.resolve()
        assert check is True
        assert env["PYTHONPATH"].split(module.os.pathsep)[0] == str(upstream.resolve())
        staged_output = Path(command[command.index("--output") + 1])
        _write_structurally_valid_output(staged_output)

    monkeypatch.setattr(module.subprocess, "run", fake_render)
    hashes = module.generate(manifest_path, upstream, output, sys.executable)

    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert recorded["generated"] is True
    assert recorded["status"] == "generated"
    assert hashes == {item["id"]: item["sha256"] for item in recorded["artifacts"]}
    assert not tuple(tmp_path.glob(f".{MANIFEST_PATH.name}.*.tmp"))
    assert not tuple(tmp_path.glob(f".{output.name}.*"))
    interrupted_backup = tmp_path / f".{output.name}.backup.interrupted"
    module.os.replace(output, interrupted_backup)
    _write_structurally_valid_output(output)
    changed_rgba, _ = _read_png_for_test(output / "rgba_00000.png")
    changed_rgba[0, 0, 2] = 1
    _write_png(output / "rgba_00000.png", changed_rgba, bitdepth=8)
    regenerated = module.generate(
        manifest_path,
        upstream,
        output,
        sys.executable,
    )
    assert regenerated == module.verify_hashes(
        module.load_manifest(manifest_path),
        output,
    )
    assert not interrupted_backup.exists()
    assert not tuple(tmp_path.glob(f".{output.name}.*"))


def test_generate_cleans_staged_output_after_render_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = importlib.util.spec_from_file_location("sceneio_kubric_tool", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest_path = tmp_path / MANIFEST_PATH.name
    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest_path.write_bytes(manifest_bytes)
    upstream = tmp_path / "kubric"
    upstream.mkdir()
    output = tmp_path / "generated"
    monkeypatch.setattr(module, "_require_pinned_clean_checkout", lambda _path: None)

    def fail_render(command, *, cwd, check, env):
        staged_output = Path(command[command.index("--output") + 1])
        staged_output.joinpath("partial.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("render failed")

    monkeypatch.setattr(module.subprocess, "run", fail_render)
    with pytest.raises(RuntimeError, match="render failed"):
        module.generate(manifest_path, upstream, output, sys.executable)

    assert not output.exists()
    assert manifest_path.read_bytes() == manifest_bytes
    assert not tuple(tmp_path.glob(f".{output.name}.*"))
    assert not tuple(tmp_path.glob(f".{manifest_path.name}.*"))


def test_generate_cleans_staged_output_after_manifest_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = importlib.util.spec_from_file_location("sceneio_kubric_tool", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest_path = tmp_path / MANIFEST_PATH.name
    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest_path.write_bytes(manifest_bytes)
    upstream = tmp_path / "kubric"
    upstream.mkdir()
    output = tmp_path / "generated"
    shutil.copytree(OUTPUT_PATH, output)
    old_files = {path.name: path.read_bytes() for path in output.iterdir()}
    monkeypatch.setattr(module, "_require_pinned_clean_checkout", lambda _path: None)

    def fake_render(command, *, cwd, check, env):
        staged_output = Path(command[command.index("--output") + 1])
        _write_structurally_valid_output(staged_output)

    original_replace = module.os.replace

    def fail_manifest_publish(source, destination):
        if Path(destination) == manifest_path.resolve():
            raise RuntimeError("manifest failed")
        original_replace(source, destination)

    monkeypatch.setattr(module.subprocess, "run", fake_render)
    monkeypatch.setattr(module.os, "replace", fail_manifest_publish)
    with pytest.raises(RuntimeError, match="manifest failed"):
        module.generate(manifest_path, upstream, output, sys.executable)

    assert {path.name: path.read_bytes() for path in output.iterdir()} == old_files
    assert manifest_path.read_bytes() == manifest_bytes
    assert not tuple(tmp_path.glob(f".{output.name}.*"))
    assert not tuple(tmp_path.glob(f".{manifest_path.name}.*"))


@pytest.mark.parametrize(
    "unsafe_path",
    [
        ".",
        "../escape.png",
        r"..\escape.png",
        r"C:escape.png",
        r"\escape.png",
        r"C:\escape.png",
    ],
    ids=(
        "dot",
        "posix-parent",
        "windows-parent",
        "drive-relative",
        "windows-rooted",
        "drive-rooted",
    ),
)
def test_manifest_rejects_unsafe_artifact_paths(tmp_path: Path, unsafe_path: str) -> None:
    document = _manifest()
    document["artifacts"][0]["path"] = unsafe_path
    manifest_path = tmp_path / MANIFEST_PATH.name
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    failed = subprocess.run(
        [
            sys.executable,
            str(TOOL_PATH),
            "check",
            "--manifest",
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "artifact rgba path" in (failed.stderr + failed.stdout)


@pytest.mark.parametrize(
    "artifact_name",
    ["rgba", "depth", "renderer_segmentation", "forward_flow"],
)
def test_output_conventions_are_explicit(artifact_name: str) -> None:
    artifacts = {item["id"]: item for item in _manifest()["artifacts"]}
    artifact = artifacts[artifact_name]
    assert artifact["path"]
    assert artifact["dtype"]
    assert artifact["shape"]


def test_pose_and_flow_conversions_are_explicit_and_evaluable() -> None:
    derived = _manifest()["derived_fields"]
    assert derived["camera_poses"]["frame"] == "world_from_camera"
    assert derived["camera_poses"]["quaternion_order"] == "wxyz"
    assert derived["object_poses"]["frame"] == "world_from_object"
    assert derived["object_poses"]["quaternion_order"] == "wxyz"

    encoded = np.array([[[0, 65535], [32768, 16384]]], dtype=np.uint16)
    minimum, maximum = -2.0, 6.0
    delta_row_column = (
        encoded.astype(np.float32) / np.float32(65535)
    ) * np.float32(maximum - minimum) + np.float32(minimum)
    uv = delta_row_column[..., [1, 0]]
    np.testing.assert_allclose(uv[0, 0], [6.0, -2.0], rtol=0, atol=1e-6)
    assert derived["forward_flow_uv"]["canonical_transform"] == (
        "u = delta_column; v = delta_row"
    )


def test_manifest_matches_pinned_kubric_output_names_and_metadata_fields() -> None:
    document = _manifest()
    artifacts = {item["id"]: item for item in document["artifacts"]}
    assert artifacts["rgba"]["path"] == "rgba_00000.png"
    assert artifacts["forward_flow"]["range_source"] == (
        "data_ranges.json#/forward_flow"
    )
    assert artifacts["forward_flow"]["encoded_shape"] == [32, 32, 3]
    assert artifacts["forward_flow"]["encoded_padding"] == (
        "channel 2 is zero and discarded"
    )
    assert artifacts["scene_metadata"]["fields"] == [
        "metadata.seed",
        "metadata.resolution",
        "metadata.frame_rate",
        "metadata.num_frames",
        "camera.positions",
        "camera.quaternions",
        "camera.R",
        "instances.positions",
        "instances.quaternions",
        "instances.renderer_id",
        "instances.visibility",
        "instances.image_positions",
    ]
