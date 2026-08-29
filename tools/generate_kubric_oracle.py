"""Generate or verify the tiny procedural Kubric oracle vector.

Normal repository tests verify the checked-in output without installing
Kubric or Blender. ``generate`` is an explicit operation that verifies the
pinned checkout, invokes the exact worker recipe, validates the complete
result, and atomically replaces the fixture and its hashes. The checked-in
output is procedural and never contains bytes copied from a hosted MOVi file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata as importlib_metadata
from pathlib import Path, PureWindowsPath
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests" / "fixtures" / "kubric_procedural_tiny_v1.json"
UPSTREAM_REVISION = "61f2422c84bab75006df33c6989e0b483db3ccfe"
SCHEMA = "sceneio.kubric_oracle/1"
_SHA256_LENGTH = 64
_RENDER_LAYERS = ("rgba", "forward_flow", "depth", "segmentation")
_CAMERA_POSITION = (3.0, -6.0, 3.5)
_CAMERA_LOOK_AT = (0.0, 0.0, 0.5)
_OBJECT_POSITION_TRACKS = {
    "cube": ((-0.8, 0.0, 0.6), (-0.45, 0.0, 0.6)),
    "sphere": ((0.8, 0.0, 0.65), (0.45, 0.0, 0.65)),
}
_SOURCE_REFERENCES = [
    "kubric/renderer/blender.py",
    "kubric/renderer/blender_utils.py",
    "kubric/file_io.py",
    "kubric/post_processing.py",
    "kubric/utils.py",
    "kubric/core/traits.py",
    "kubric/core/cameras.py",
    "kubric/core/objects.py",
]


def load_manifest(
    path: Path = DEFAULT_MANIFEST,
    *,
    allow_generated: bool = True,
) -> dict[str, Any]:
    """Load and validate the compact recipe manifest."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Kubric oracle manifest must be a JSON object")
    check_manifest(document, allow_generated=allow_generated)
    return document


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _safe_relative_path(value: object, name: str) -> Path:
    _require(isinstance(value, str) and value, f"{name} must be a relative path")
    path = Path(value)
    windows_path = PureWindowsPath(value)
    _require(
        bool(path.parts)
        and not path.is_absolute()
        and not path.root
        and not path.drive
        and not windows_path.is_absolute()
        and not windows_path.root
        and not windows_path.drive,
        f"{name} must be relative",
    )
    _require(
        ".." not in path.parts and ".." not in windows_path.parts,
        f"{name} must not escape the output directory",
    )
    return path


def _check_artifact_hash(value: object, name: str) -> None:
    if value is not None:
        _require(
            isinstance(value, str)
            and len(value) == _SHA256_LENGTH
            and all(character in "0123456789abcdef" for character in value),
            f"{name} must be null or a lowercase SHA-256 digest",
        )


def _check_shape(value: object, name: str) -> None:
    _require(isinstance(value, list) and value, f"{name} must be a non-empty shape")
    for dimension in value:
        _require(
            isinstance(dimension, int) and not isinstance(dimension, bool) and dimension > 0,
            f"{name} dimensions must be positive integers",
        )


def check_manifest(document: dict[str, Any], *, allow_generated: bool = False) -> None:
    """Validate recipe identity, output conventions, and hash policy offline."""

    _require(document.get("schema") == SCHEMA, f"expected schema {SCHEMA}")
    if allow_generated and document.get("generated") is True:
        _require(document.get("status") == "generated", "generated manifest status drifted")
    else:
        _require(document.get("status") == "recipe_only", "manifest must remain recipe_only")
        _require(document.get("generated") is False, "checked-in manifest must not claim generated data")
    upstream = document.get("upstream")
    _require(isinstance(upstream, dict), "manifest upstream must be an object")
    _require(
        upstream.get("repository") == "https://github.com/google-research/kubric",
        "Kubric repository drifted",
    )
    _require(upstream.get("revision") == UPSTREAM_REVISION, "Kubric revision drifted")
    _require(upstream.get("license") == "Apache-2.0", "Kubric license drifted")
    _require(
        upstream.get("generator_entrypoint")
        == "tools/generate_kubric_oracle.py:_render_scene",
        "Kubric generator entrypoint drifted",
    )
    _require(
        upstream.get("source_references") == _SOURCE_REFERENCES,
        "Kubric source references drifted",
    )
    runtime = document.get("runtime")
    _require(isinstance(runtime, dict), "manifest runtime must be an object")
    _require(runtime.get("blender_version") == "4.3.0", "Blender version drifted")
    _require(runtime.get("python_version") == "3.11", "Kubric Python version drifted")
    _require(
        runtime.get("provenance_artifact") == "runtime.json",
        "Kubric runtime provenance path drifted",
    )

    recipe = document.get("recipe")
    _require(isinstance(recipe, dict), "manifest recipe must be an object")
    expected_recipe = {
        "variant": "SceneIO procedural FC2",
        "seed": 20260804,
        "frame_start": 0,
        "frame_end": 1,
        "frame_rate": 12,
        "resolution": "32x32",
        "object_count": 2,
        "objects": ["cube", "sphere"],
        "camera": "fixed_perspective",
        "camera_position": list(_CAMERA_POSITION),
        "camera_look_at": list(_CAMERA_LOOK_AT),
        "object_position_tracks": {
            name: [list(position) for position in positions]
            for name, positions in _OBJECT_POSITION_TRACKS.items()
        },
    }
    for key, expected in expected_recipe.items():
        _require(recipe.get(key) == expected, f"Kubric recipe {key!r} drifted")
    assets = recipe.get("assets")
    _require(isinstance(assets, dict), "Kubric recipe assets must be an object")
    _require(assets.get("mode") == "procedural_only", "Kubric assets must be procedural")
    _require(assets.get("external_manifest") is None, "Kubric recipe must not use an asset manifest")
    _require(assets.get("redistributed") is False, "Kubric assets must not be redistributed")
    _require(assets.get("license") == "Apache-2.0", "Kubric primitive license drifted")
    command = recipe.get("command")
    _require(isinstance(command, list) and command, "Kubric recipe command must be non-empty")
    _require("tools/generate_kubric_oracle.py" in command, "recipe must name the generator")
    _require("generate" in command, "recipe command must use the generate operation")
    _require("--upstream=<kubric-checkout>" in command, "recipe command must bind Kubric")
    _require("--output=<output>" in command, "recipe command must bind output")
    _require("gs://" not in json.dumps(document), "Kubric recipe must not use hosted assets")

    artifacts = document.get("artifacts")
    _require(isinstance(artifacts, list) and artifacts, "manifest artifacts must be non-empty")
    artifact_ids: set[str] = set()
    artifact_paths: set[Path] = set()
    for index, artifact in enumerate(artifacts):
        _require(isinstance(artifact, dict), f"artifact {index} must be an object")
        artifact_id = artifact.get("id")
        _require(
            isinstance(artifact_id, str) and artifact_id not in artifact_ids,
            f"artifact {index} has a duplicate id",
        )
        artifact_ids.add(artifact_id)
        artifact_path = _safe_relative_path(artifact.get("path"), f"artifact {artifact_id} path")
        _require(artifact_path not in artifact_paths, f"artifact {artifact_id} has a duplicate path")
        artifact_paths.add(artifact_path)
        _check_artifact_hash(artifact.get("sha256"), f"artifact {artifact_id} sha256")
        if "shape" in artifact:
            _check_shape(artifact["shape"], f"artifact {artifact_id} shape")
    expected_artifacts = {
        "rgba": ("rgba_00000.png", "uint8", [32, 32, 4], 0),
        "rgba_frame1": ("rgba_00001.png", "uint8", [32, 32, 4], 1),
        "depth": ("depth_00000.tiff", "float32", [32, 32, 1], 0),
        "depth_frame1": ("depth_00001.tiff", "float32", [32, 32, 1], 1),
        "renderer_segmentation": (
            "segmentation_00000.png",
            "uint8",
            [32, 32, 1],
            0,
        ),
        "renderer_segmentation_frame1": (
            "segmentation_00001.png",
            "uint8",
            [32, 32, 1],
            1,
        ),
        "forward_flow": ("forward_flow_00000.png", "float32", [32, 32, 2], 0),
        "forward_flow_frame1": (
            "forward_flow_00001.png",
            "float32",
            [32, 32, 2],
            1,
        ),
        "flow_ranges": ("data_ranges.json", "json", None, None),
        "runtime_provenance": ("runtime.json", "json", None, None),
        "scene_metadata": ("metadata.json", "json", None, None),
    }
    _require(artifact_ids == set(expected_artifacts), "Kubric artifact inventory drifted")
    by_id = {artifact["id"]: artifact for artifact in artifacts}
    for artifact in artifacts:
        expected_path, expected_dtype, expected_shape, expected_frame = expected_artifacts[
            artifact["id"]
        ]
        _require(artifact.get("path") == expected_path, f"artifact {artifact['id']} path drifted")
        _require(artifact.get("dtype") == expected_dtype, f"artifact {artifact['id']} dtype drifted")
        if expected_shape is not None:
            _require(artifact.get("shape") == expected_shape, f"artifact {artifact['id']} shape drifted")
            _require(artifact.get("frame") == expected_frame, f"artifact {artifact['id']} frame drifted")
    for artifact_id in ("rgba", "rgba_frame1"):
        artifact = by_id[artifact_id]
        _require(artifact.get("channels") == "RGBA", f"artifact {artifact_id} channels drifted")
        _require(artifact.get("row_order") == "top_to_bottom", f"artifact {artifact_id} row order drifted")
    for artifact_id in ("depth", "depth_frame1"):
        artifact = by_id[artifact_id]
        _require(artifact.get("encoded_shape") == [32, 32], f"artifact {artifact_id} encoded shape drifted")
        _require(artifact.get("unit") == "scene_units", f"artifact {artifact_id} unit drifted")
    for artifact_id in ("renderer_segmentation", "renderer_segmentation_frame1"):
        artifact = by_id[artifact_id]
        _require(artifact.get("encoded_shape") == [32, 32], f"artifact {artifact_id} encoded shape drifted")
        _require(artifact.get("background_id") == 0, f"artifact {artifact_id} background drifted")
    for artifact_id in ("forward_flow", "forward_flow_frame1"):
        artifact = by_id[artifact_id]
        _require(artifact.get("encoded_dtype") == "uint16", f"artifact {artifact_id} encoding drifted")
        _require(artifact.get("encoded_shape") == [32, 32, 3], f"artifact {artifact_id} encoded shape drifted")
        _require(artifact.get("encoded_padding") == "channel 2 is zero and discarded", f"artifact {artifact_id} padding drifted")
        _require(artifact.get("component_order") == "delta_row_delta_column", f"artifact {artifact_id} component order drifted")
        _require(artifact.get("range_source") == "data_ranges.json#/forward_flow", f"artifact {artifact_id} range source drifted")
    _require(
        by_id["flow_ranges"].get("fields") == ["forward_flow.min", "forward_flow.max"],
        "Kubric flow-range fields drifted",
    )
    _require(
        by_id["runtime_provenance"].get("fields")
        == [
            "schema",
            "kubric_revision",
            "kubric_module",
            "blender_version",
            "python_version",
            "dependency_versions",
            "render_layers",
            "samples_per_pixel",
        ],
        "Kubric runtime fields drifted",
    )
    _require(
        by_id["scene_metadata"].get("fields")
        == [
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
        ],
        "Kubric metadata fields drifted",
    )
    if document.get("generated") is True:
        _require(
            all(artifact.get("sha256") is not None for artifact in artifacts),
            "generated Kubric manifest requires every artifact hash",
        )
    else:
        _require(
            all(artifact.get("sha256") is None for artifact in artifacts),
            "recipe-only Kubric manifest must not contain artifact hashes",
        )

    derived = document.get("derived_fields")
    _require(isinstance(derived, dict), "manifest derived_fields must be an object")
    for field in (
        "semantic_ids",
        "instance_ids",
        "camera_poses",
        "object_poses",
        "forward_flow_uv",
    ):
        _require(field in derived and isinstance(derived[field], dict), f"missing derived field {field}")
    semantic = derived["semantic_ids"]
    _require(semantic.get("dtype") == "int32", "semantic ids must be int32")
    _require(semantic.get("void_id") == -1, "semantic void id drifted")
    _require(
        semantic.get("taxonomy_identity")
        == "org.sceneio.kubric-procedural-fc2",
        "semantic taxonomy identity drifted",
    )
    _require(
        semantic.get("taxonomy_version") == UPSTREAM_REVISION,
        "semantic taxonomy version drifted",
    )
    _require(semantic.get("renderer_to_semantic") == {"0": 0, "1": 4, "2": 9}, "renderer mapping drifted")
    instance = derived["instance_ids"]
    _require(instance.get("dtype") == "int64", "instance ids must be int64")
    _require(instance.get("background_id") == 0, "instance background id drifted")
    flow = derived["forward_flow_uv"]
    _require(
        flow.get("canonical_transform") == "u = delta_column; v = delta_row",
        "Kubric flow component conversion drifted",
    )
    for field in ("camera_poses", "object_poses"):
        _require(
            derived[field].get("quaternion_order") == "wxyz",
            f"Kubric {field} quaternion order drifted",
        )

    hand = document.get("hand_evaluated_label_vector")
    _require(isinstance(hand, dict), "hand_evaluated_label_vector must be an object")
    _require(
        hand.get("purpose")
        == "independent rule vector; not claimed to be a rendered crop from this recipe",
        "hand-evaluated vector provenance drifted",
    )
    for key in ("renderer_ids", "semantic_ids", "instance_ids", "valid"):
        rows = hand.get(key)
        _require(
            isinstance(rows, list) and len(rows) == 3 and all(isinstance(row, list) and len(row) == 4 for row in rows),
            f"hand-evaluated {key} must be a 3x4 matrix",
        )
    _require(hand.get("void_id") == -1 and hand.get("background_id") == 0, "hand-evaluated ids drifted")
    taxonomy = hand.get("taxonomy")
    _require(isinstance(taxonomy, dict), "hand-evaluated taxonomy must be an object")
    _require(taxonomy.get("semantic_ids") == [0, 4, 9], "hand-evaluated taxonomy ids drifted")
    _require(taxonomy.get("names") == ["background", "cube", "sphere"], "hand-evaluated taxonomy names drifted")
    _require(
        taxonomy.get("identity") == "org.sceneio.kubric-procedural-fc2",
        "hand-evaluated taxonomy identity drifted",
    )
    _require(
        taxonomy.get("version") == UPSTREAM_REVISION,
        "hand-evaluated taxonomy version drifted",
    )


def _git_revision(upstream: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=upstream,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"could not inspect Kubric checkout {upstream}") from exc


def _require_pinned_clean_checkout(upstream: Path) -> None:
    actual = _git_revision(upstream)
    _require(
        actual == UPSTREAM_REVISION,
        f"expected Kubric {UPSTREAM_REVISION}, found {actual}",
    )
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=upstream,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"could not inspect Kubric checkout {upstream}") from exc
    _require(not status.strip(), "Kubric checkout must be clean before generation")


def _artifact_path(output: Path, artifact: dict[str, Any]) -> Path:
    relative = _safe_relative_path(artifact["path"], f"artifact {artifact['id']} path")
    target = (output / relative).resolve()
    _require(target.is_relative_to(output.resolve()), f"artifact {artifact['id']} escapes output")
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{context} must be valid UTF-8 JSON") from exc
    _require(isinstance(value, dict), f"{context} must be a JSON object")
    return value


def _read_png(path: Path, context: str) -> tuple[np.ndarray, int]:
    try:
        import png
    except ModuleNotFoundError as exc:
        raise RuntimeError("Kubric output validation requires pypng") from exc
    try:
        width, height, rows, info = png.Reader(filename=str(path)).read()
        planes = int(info["planes"])
        bitdepth = int(info["bitdepth"])
        flattened = np.vstack(
            [np.asarray(row, dtype=np.uint16) for row in rows]
        )
        values = flattened.reshape(height, width, planes)
    except Exception as exc:
        raise ValueError(f"{context} must be a decodable PNG") from exc
    _require((height, width) == (32, 32), f"{context} must be 32x32")
    return values, bitdepth


def _require_finite_numeric_shape(
    value: object,
    shape: tuple[int, ...],
    context: str,
) -> np.ndarray:
    try:
        array = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} must be a finite numeric array") from exc
    _require(array.shape == shape, f"{context} shape drifted")
    _require(np.issubdtype(array.dtype, np.number), f"{context} must be numeric")
    _require(bool(np.all(np.isfinite(array))), f"{context} must be finite")
    return array.astype(np.float64, copy=False)


def _require_unit_quaternions(
    value: object,
    shape: tuple[int, ...],
    context: str,
) -> np.ndarray:
    quaternions = _require_finite_numeric_shape(value, shape, context)
    norms = np.linalg.norm(quaternions, axis=-1)
    _require(
        bool(np.allclose(norms, 1.0, rtol=0.0, atol=1e-5)),
        f"{context} must contain unit WXYZ quaternions",
    )
    return quaternions


def _normalized(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    _require(norm > 1e-12, "Kubric recipe direction must be nonzero")
    return vector / norm


def _recipe_camera_rotation() -> np.ndarray:
    """Reproduce pinned Kubric ``look_at_quat`` as a rotation matrix."""

    position = np.asarray(_CAMERA_POSITION, dtype=np.float64)
    target = np.asarray(_CAMERA_LOOK_AT, dtype=np.float64)
    world_up = np.array([0.0, 0.0, 1.0])
    world_right = np.array([1.0, 0.0, 0.0])
    up = np.array([0.0, 1.0, 0.0])
    front = np.array([0.0, 0.0, -1.0])
    right = np.cross(up, front)
    look_at_front = _normalized(target - position)
    candidate_right = np.cross(world_up, look_at_front)
    look_at_right = (
        world_right
        if float(np.linalg.norm(candidate_right)) <= 1e-12
        else _normalized(candidate_right)
    )
    look_at_up = _normalized(np.cross(look_at_front, look_at_right))
    world_basis = np.stack([look_at_right, look_at_up, look_at_front])
    camera_basis = np.stack([right, up, front])
    return world_basis.T @ camera_basis


def _rotation_wxyz(rotation: np.ndarray) -> np.ndarray:
    """Convert this recipe's positive-trace rotation to a WXYZ quaternion."""

    trace = float(np.trace(rotation))
    _require(trace > 0.0, "Kubric recipe camera rotation branch drifted")
    w = math.sqrt(1.0 + trace) / 2.0
    scale = 4.0 * w
    quaternion = np.array(
        [
            w,
            (rotation[2, 1] - rotation[1, 2]) / scale,
            (rotation[0, 2] - rotation[2, 0]) / scale,
            (rotation[1, 0] - rotation[0, 1]) / scale,
        ],
        dtype=np.float64,
    )
    return _normalized(quaternion)


def _recipe_image_positions() -> np.ndarray:
    """Project the two declared object tracks using pinned Kubric camera math."""

    rotation = _recipe_camera_rotation()
    world_to_camera = rotation.T
    camera_position = np.asarray(_CAMERA_POSITION, dtype=np.float64)
    intrinsics = np.array(
        [
            [50.0 / 36.0, 0.0, -0.5],
            [0.0, -50.0 / 36.0, -0.5],
            [0.0, 0.0, -1.0],
        ],
        dtype=np.float64,
    )
    projected_tracks = []
    for name in ("cube", "sphere"):
        projected_frames = []
        for position in _OBJECT_POSITION_TRACKS[name]:
            camera_point = world_to_camera @ (
                np.asarray(position, dtype=np.float64) - camera_position
            )
            projected = intrinsics @ camera_point
            _require(projected[2] > 0.0, "Kubric recipe object must face the camera")
            projected_frames.append(projected[:2] / projected[2])
        projected_tracks.append(projected_frames)
    return np.asarray(projected_tracks, dtype=np.float64)


def _validate_generated_output(document: dict[str, Any], output: Path) -> None:
    expected_paths = {
        _safe_relative_path(artifact["path"], f"artifact {artifact['id']} path")
        for artifact in document["artifacts"]
    }
    observed_paths = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    expected_strings = {path.as_posix() for path in expected_paths}
    if observed_paths != expected_strings:
        missing = sorted(expected_strings - observed_paths)
        unexpected = sorted(observed_paths - expected_strings)
        raise ValueError(
            "Kubric output inventory disagrees"
            + (f"; missing {missing}" if missing else "")
            + (f"; unexpected {unexpected}" if unexpected else "")
        )

    segmentation_ids: set[int] = set()
    segmentation_frames: list[np.ndarray] = []
    encoded_flows: list[np.ndarray] = []
    rgba_frames: list[np.ndarray] = []
    for frame in range(2):
        rgba, rgba_depth = _read_png(
            output / f"rgba_{frame:05d}.png", f"Kubric RGBA frame {frame}"
        )
        _require(rgba.shape == (32, 32, 4), "Kubric RGBA must have four channels")
        _require(rgba_depth == 8, "Kubric RGBA must be uint8 PNG")
        _require(
            bool(np.all(rgba[..., 3] == 255)),
            "Kubric RGBA must be opaque for the configured renderer",
        )
        rgba_frames.append(rgba)

        segmentation, segmentation_depth = _read_png(
            output / f"segmentation_{frame:05d}.png",
            f"Kubric segmentation frame {frame}",
        )
        _require(
            segmentation.shape == (32, 32, 1),
            "Kubric segmentation must have one channel",
        )
        _require(segmentation_depth == 8, "Kubric segmentation must be uint8 PNG")
        frame_ids = {int(value) for value in np.unique(segmentation)}
        _require(
            frame_ids <= {0, 1, 2},
            "Kubric segmentation contains an unexpected instance id",
        )
        segmentation_ids.update(frame_ids)
        segmentation_frames.append(segmentation[..., 0])

        flow, flow_depth = _read_png(
            output / f"forward_flow_{frame:05d}.png",
            f"Kubric forward-flow frame {frame}",
        )
        _require(flow.shape == (32, 32, 3), "Kubric flow PNG must have three stored channels")
        _require(flow_depth == 16, "Kubric flow PNG must be uint16")
        _require(
            not np.any(flow[..., 2]),
            "Kubric flow PNG padding channel must be zero",
        )
        encoded_flows.append(flow[..., :2])

    _require(
        segmentation_ids == {0, 1, 2},
        "Kubric segmentation must contain background, cube, and sphere ids",
    )
    expected_image_positions = _recipe_image_positions()
    for object_index, renderer_id in enumerate((1, 2)):
        for frame in range(2):
            rows, columns = np.nonzero(
                segmentation_frames[frame] == renderer_id
            )
            _require(
                bool(rows.size),
                f"Kubric renderer id {renderer_id} must be visible in frame {frame}",
            )
            pixel_centers = np.column_stack(
                ((columns + 0.5) / 32.0, (rows + 0.5) / 32.0)
            )
            distance = np.linalg.norm(
                pixel_centers - expected_image_positions[object_index, frame],
                axis=1,
            )
            _require(
                float(distance.min()) <= 1.5 / 32.0,
                "Kubric renderer ids disagree with cube/sphere recipe order",
            )
    rgb = np.stack(rgba_frames, axis=0)[..., :3].reshape(-1, 3)
    _require(
        bool(np.any(rgb != rgb[0])),
        "Kubric RGBA must contain rendered color variation",
    )

    try:
        import tifffile
    except ModuleNotFoundError as exc:
        raise RuntimeError("Kubric output validation requires tifffile") from exc
    for frame in range(2):
        with tifffile.TiffFile(output / f"depth_{frame:05d}.tiff") as tiff:
            _require(len(tiff.pages) == 1, "Kubric depth TIFF must have one page")
            depth = np.asarray(tiff.pages[0].asarray())
        _require(depth.shape == (32, 32), "Kubric depth TIFF must be 32x32")
        _require(depth.dtype == np.dtype("float32"), "Kubric depth TIFF must be float32")
        _require(
            bool(np.all(np.isfinite(depth))) and bool(np.all(depth > 0)),
            "Kubric depth values must be finite and positive",
        )

    ranges = _read_json_object(output / "data_ranges.json", "Kubric flow ranges")
    _require(set(ranges) == {"forward_flow"}, "Kubric flow ranges must be exact")
    flow_range = ranges["forward_flow"]
    _require(isinstance(flow_range, dict), "Kubric forward-flow range must be an object")
    minimum = flow_range.get("min")
    maximum = flow_range.get("max")
    _require(
        isinstance(minimum, (int, float))
        and not isinstance(minimum, bool)
        and isinstance(maximum, (int, float))
        and not isinstance(maximum, bool)
        and math.isfinite(float(minimum))
        and math.isfinite(float(maximum))
        and float(maximum) > float(minimum),
        "Kubric forward-flow range must contain finite increasing bounds",
    )
    minimum_value = float(minimum)
    maximum_value = float(maximum)
    _require(
        minimum_value < 0.0 < maximum_value,
        "Kubric forward-flow range must span zero for the opposing motions",
    )
    encoded_flow = np.stack(encoded_flows, axis=0)
    _require(
        int(encoded_flow.min()) == 0 and int(encoded_flow.max()) >= 65534,
        "Kubric forward-flow encoding must span the declared uint16 range",
    )
    decoded_flow = (
        encoded_flow.astype(np.float64) / 65535.0
    ) * (maximum_value - minimum_value) + minimum_value
    quantization_tolerance = max(
        1e-9,
        (maximum_value - minimum_value) * 1.5 / 65535.0,
    )
    _require(
        bool(np.all(np.isfinite(decoded_flow)))
        and math.isclose(
            float(decoded_flow.min()),
            minimum_value,
            rel_tol=0.0,
            abs_tol=quantization_tolerance,
        )
        and math.isclose(
            float(decoded_flow.max()),
            maximum_value,
            rel_tol=0.0,
            abs_tol=quantization_tolerance,
        ),
        "Kubric forward-flow samples disagree with the declared range",
    )
    for object_index, renderer_id in enumerate((1, 2)):
        selected = decoded_flow[0][segmentation_frames[0] == renderer_id]
        _require(
            bool(selected.size),
            f"Kubric renderer id {renderer_id} has no flow samples",
        )
        observed_delta_row_column = np.median(selected, axis=0)
        expected_xy = (
            expected_image_positions[object_index, 1]
            - expected_image_positions[object_index, 0]
        ) * 32.0
        expected_delta_row_column = expected_xy[[1, 0]]
        _require(
            bool(
                np.allclose(
                    observed_delta_row_column,
                    expected_delta_row_column,
                    rtol=0.0,
                    atol=0.75,
                )
            ),
            "Kubric forward-flow component order or direction disagrees with the recipe",
        )

    metadata = _read_json_object(output / "metadata.json", "Kubric metadata")
    _require(set(metadata) == {"metadata", "camera", "instances"}, "Kubric metadata fields drifted")
    scene_metadata = metadata["metadata"]
    camera = metadata["camera"]
    instances = metadata["instances"]
    _require(isinstance(scene_metadata, dict), "Kubric scene metadata must be an object")
    _require(scene_metadata.get("seed") == 20260804, "Kubric metadata seed drifted")
    _require(scene_metadata.get("resolution") == [32, 32], "Kubric metadata resolution drifted")
    _require(scene_metadata.get("frame_rate") == 12, "Kubric metadata frame rate drifted")
    _require(scene_metadata.get("num_frames") == 2, "Kubric metadata frame count drifted")
    _require(isinstance(camera, dict), "Kubric camera metadata must be an object")
    camera_positions = _require_finite_numeric_shape(
        camera.get("positions"), (2, 3), "Kubric camera positions"
    )
    camera_quaternions = _require_unit_quaternions(
        camera.get("quaternions"), (2, 4), "Kubric camera quaternions"
    )
    camera_matrix = _require_finite_numeric_shape(
        camera.get("R"), (4, 4), "Kubric camera matrix"
    )
    _require(
        bool(
            np.allclose(
                camera_positions,
                np.repeat(
                    np.asarray(_CAMERA_POSITION, dtype=np.float64)[None, :],
                    2,
                    axis=0,
                ),
                rtol=0.0,
                atol=1e-6,
            )
        ),
        "Kubric camera positions disagree with the fixed recipe",
    )
    _require(
        bool(np.allclose(camera_quaternions[0], camera_quaternions[1], rtol=0.0, atol=1e-6)),
        "Kubric camera quaternion must remain fixed across frames",
    )
    expected_camera_rotation = _recipe_camera_rotation()
    expected_camera_target = np.asarray(_CAMERA_LOOK_AT, dtype=np.float64)
    rotation = camera_matrix[:3, :3]
    _require(
        bool(np.allclose(camera_matrix[3], [0.0, 0.0, 0.0, 1.0], rtol=0.0, atol=1e-6)),
        "Kubric camera matrix must be homogeneous",
    )
    _require(
        bool(np.allclose(rotation @ rotation.T, np.eye(3), rtol=0.0, atol=1e-6))
        and math.isclose(float(np.linalg.det(rotation)), 1.0, rel_tol=0.0, abs_tol=1e-6),
        "Kubric camera matrix rotation must be orthonormal",
    )
    _require(
        bool(np.allclose(camera_matrix[:3, 3], camera_positions[0], rtol=0.0, atol=1e-6)),
        "Kubric camera matrix translation disagrees with positions",
    )
    _require(
        bool(np.allclose(rotation, expected_camera_rotation, rtol=0.0, atol=1e-5)),
        "Kubric camera matrix disagrees with the fixed look-at recipe",
    )
    look_at_direction = _normalized(expected_camera_target - camera_positions[0])
    _require(
        float(np.dot(-rotation[:, 2], look_at_direction)) >= 1.0 - 1e-5,
        "Kubric camera matrix does not point at the fixed look-at target",
    )
    expected_camera_quaternion = _rotation_wxyz(_recipe_camera_rotation())
    _require(
        bool(
            np.allclose(
                camera_quaternions[0],
                expected_camera_quaternion,
                rtol=0.0,
                atol=1e-5,
            )
            or np.allclose(
                camera_quaternions[0],
                -expected_camera_quaternion,
                rtol=0.0,
                atol=1e-5,
            )
        ),
        "Kubric camera WXYZ quaternion disagrees with the fixed look-at recipe",
    )
    _require(isinstance(instances, list) and len(instances) == 2, "Kubric instance count drifted")
    expected_positions = (
        np.asarray(_OBJECT_POSITION_TRACKS["cube"], dtype=np.float64),
        np.asarray(_OBJECT_POSITION_TRACKS["sphere"], dtype=np.float64),
    )
    expected_quaternions = np.array(
        [[1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]]
    )
    for index, instance in enumerate(instances):
        _require(isinstance(instance, dict), f"Kubric instance {index} must be an object")
        positions = _require_finite_numeric_shape(
            instance.get("positions"), (2, 3), f"Kubric instance {index} positions"
        )
        quaternions = _require_unit_quaternions(
            instance.get("quaternions"), (2, 4), f"Kubric instance {index} quaternions"
        )
        _require(
            bool(np.allclose(positions, expected_positions[index], rtol=0.0, atol=1e-6)),
            f"Kubric instance {index} positions disagree with the recipe",
        )
        _require(
            bool(np.allclose(quaternions, expected_quaternions, rtol=0.0, atol=1e-6)),
            f"Kubric instance {index} quaternion disagrees with the recipe",
        )
        renderer_id = instance.get("renderer_id")
        _require(
            isinstance(renderer_id, int) and not isinstance(renderer_id, bool)
            and renderer_id == index + 1,
            f"Kubric instance {index} renderer id disagrees with foreground order",
        )
        visibility = _require_finite_numeric_shape(
            instance.get("visibility"), (2,), f"Kubric instance {index} visibility"
        )
        _require(
            bool(np.allclose(visibility, np.rint(visibility), rtol=0.0, atol=1e-6)),
            f"Kubric instance {index} visibility must contain integer counts",
        )
        expected_visibility = np.array(
            [np.count_nonzero(frame == renderer_id) for frame in segmentation_frames],
            dtype=np.float64,
        )
        _require(
            bool(np.array_equal(np.rint(visibility).astype(np.int64), expected_visibility.astype(np.int64))),
            f"Kubric instance {index} visibility disagrees with renderer id {renderer_id}",
        )
        image_positions = _require_finite_numeric_shape(
            instance.get("image_positions"),
            (2, 2),
            f"Kubric instance {index} image positions",
        )
        _require(
            bool(
                np.allclose(
                    image_positions,
                    expected_image_positions[index],
                    rtol=0.0,
                    atol=1e-5,
                )
            ),
            f"Kubric instance {index} image positions disagree with the recipe",
        )

    runtime = _read_json_object(output / "runtime.json", "Kubric runtime provenance")
    _require(
        set(runtime)
        == {
            "schema",
            "kubric_revision",
            "kubric_module",
            "blender_version",
            "python_version",
            "dependency_versions",
            "render_layers",
            "samples_per_pixel",
        },
        "Kubric runtime fields drifted",
    )
    _require(runtime.get("schema") == "sceneio.kubric_runtime/1", "Kubric runtime schema drifted")
    _require(runtime.get("kubric_revision") == UPSTREAM_REVISION, "Kubric runtime revision drifted")
    _require(runtime.get("kubric_module") == "kubric/__init__.py", "Kubric runtime module drifted")
    _require(runtime.get("blender_version") == "4.3.0", "Kubric Blender runtime drifted")
    _require(str(runtime.get("python_version", "")).startswith("3.11."), "Kubric Python runtime drifted")
    _require(runtime.get("render_layers") == list(_RENDER_LAYERS), "Kubric render layers drifted")
    _require(runtime.get("samples_per_pixel") == 64, "Kubric sample count drifted")
    _require(isinstance(runtime.get("dependency_versions"), dict), "Kubric dependency versions are missing")


def collect_hashes(document: dict[str, Any], output: Path) -> dict[str, str]:
    output = output.resolve()
    _require(output.is_dir(), f"Kubric output does not exist: {output}")
    _validate_generated_output(document, output)
    hashes: dict[str, str] = {}
    for artifact in document["artifacts"]:
        target = _artifact_path(output, artifact)
        _require(target.is_file(), f"missing Kubric artifact {target}")
        hashes[artifact["id"]] = _sha256(target)
    return hashes


def _write_generated_manifest(
    manifest_path: Path,
    document: dict[str, Any],
    hashes: dict[str, str],
) -> None:
    for artifact in document["artifacts"]:
        artifact["sha256"] = hashes[artifact["id"]]
    document["generated"] = True
    document["status"] = "generated"
    check_manifest(document, allow_generated=True)
    manifest_path = manifest_path.resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=manifest_path.parent,
            prefix=f".{manifest_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(document, stream, indent=2, sort_keys=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, manifest_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def verify_hashes(document: dict[str, Any], output: Path) -> dict[str, str]:
    observed = collect_hashes(document, output)
    missing = [artifact["id"] for artifact in document["artifacts"] if artifact["sha256"] is None]
    if missing:
        raise RuntimeError(
            "manifest hashes are intentionally unrecorded for "
            + ", ".join(missing)
            + "; run the opt-in generate command"
        )
    mismatches = [
        artifact["id"]
        for artifact in document["artifacts"]
        if artifact["sha256"] != observed[artifact["id"]]
    ]
    if mismatches:
        raise RuntimeError("Kubric artifact hashes disagree: " + ", ".join(mismatches))
    return observed


def _dependency_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for distribution in (
        "bpy",
        "imageio",
        "numpy",
        "OpenEXR",
        "pypng",
        "pyquaternion",
        "tensorflow-cpu",
        "tifffile",
        "traitlets",
        "trimesh",
    ):
        try:
            versions[distribution] = importlib_metadata.version(distribution)
        except importlib_metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions


def _render_scene(output: Path, upstream: Path) -> None:
    """Render the deterministic procedural scene in a pinned Kubric environment."""

    upstream = upstream.resolve()
    _require(upstream.is_dir(), f"Kubric checkout does not exist: {upstream}")
    _require_pinned_clean_checkout(upstream)
    _require(
        sys.version_info[:2] == (3, 11),
        "Kubric oracle generation requires Python 3.11",
    )
    try:
        import bpy
        import kubric as kb
        from kubric.renderer import Blender
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Kubric oracle generation requires Kubric and Blender outside normal CI"
        ) from exc
    module_path = Path(kb.__file__).resolve()
    _require(
        module_path.is_relative_to(upstream),
        "Kubric import does not come from the pinned checkout",
    )
    _require(
        tuple(bpy.app.version[:3]) == (4, 3, 0),
        "Kubric oracle generation requires Blender 4.3.0",
    )

    output = output.resolve()
    _require(not output.exists() or not any(output.iterdir()), "refusing a non-empty generation output")
    output.mkdir(parents=True, exist_ok=True)
    scene = kb.Scene(resolution=(32, 32))
    scene.frame_start = 0
    scene.frame_end = 1
    scene.frame_rate = 12
    scene.metadata["seed"] = 20260804
    scene.metadata["recipe"] = "sceneio-procedural-fc2-v1"

    with tempfile.TemporaryDirectory(prefix="sceneio-kubric-") as scratch:
        renderer = Blender(
            scene,
            scratch_dir=scratch,
            adaptive_sampling=False,
            use_denoising=False,
            samples_per_pixel=64,
            background_transparency=False,
        )
        floor = kb.Cube(
            name="floor",
            scale=(4.0, 4.0, 0.1),
            position=(0.0, 0.0, -0.1),
            background=True,
        )
        cube = kb.Cube(name="cube", scale=0.6, position=(-0.8, 0.0, 0.6))
        sphere = kb.Sphere(name="sphere", scale=0.65, position=(0.8, 0.0, 0.65))
        scene += floor
        scene += cube
        scene += sphere
        scene += kb.DirectionalLight(
            name="sun",
            position=(-3.0, -4.0, 6.0),
            look_at=(0.0, 0.0, 0.5),
            intensity=2.0,
        )
        scene += kb.PerspectiveCamera(
            name="camera",
            position=(3.0, -6.0, 3.5),
            look_at=(0.0, 0.0, 0.5),
        )
        cube.keyframe_insert("position", 0)
        cube.position = (-0.45, 0.0, 0.6)
        cube.keyframe_insert("position", 1)
        sphere.keyframe_insert("position", 0)
        sphere.position = (0.45, 0.0, 0.65)
        sphere.keyframe_insert("position", 1)
        data_stack = renderer.render(return_layers=_RENDER_LAYERS)

    foreground = (cube, sphere)
    kb.compute_visibility(data_stack["segmentation"], scene.assets)
    data_stack["segmentation"] = kb.post_processing.adjust_segmentation_idxs(
        data_stack["segmentation"], scene.assets, foreground
    )
    kb.write_image_dict(data_stack, output)
    instances = kb.get_instance_info(scene, foreground)
    for renderer_id, instance in enumerate(instances, start=1):
        instance["renderer_id"] = renderer_id
    kb.write_json(
        filename=output / "metadata.json",
        data={
            "metadata": kb.get_scene_metadata(scene),
            "camera": kb.get_camera_info(scene.camera),
            "instances": instances,
        },
    )
    (output / "runtime.json").write_text(
        json.dumps(
            {
                "schema": "sceneio.kubric_runtime/1",
                "kubric_revision": UPSTREAM_REVISION,
                "kubric_module": module_path.relative_to(upstream).as_posix(),
                "blender_version": str(bpy.app.version_string),
                "python_version": sys.version.split()[0],
                "dependency_versions": _dependency_versions(),
                "render_layers": list(_RENDER_LAYERS),
                "samples_per_pixel": 64,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _recover_interrupted_publication(
    document: dict[str, Any],
    output: Path,
) -> None:
    """Restore or finish the single prior output swap, if one exists."""

    prefix = f".{output.name}.backup."
    backups = [
        path
        for path in output.parent.iterdir()
        if path.name.startswith(prefix)
    ]
    _require(len(backups) <= 1, "multiple interrupted Kubric output backups exist")
    if not backups:
        return
    backup = backups[0]
    _require(
        backup.is_dir() and not backup.is_symlink(),
        "interrupted Kubric output backup must be a directory",
    )
    if not output.exists():
        os.replace(backup, output)
        return
    _require(
        output.is_dir() and not output.is_symlink(),
        "existing generation output must be a directory",
    )
    try:
        verify_hashes(document, output)
    except (RuntimeError, ValueError):
        try:
            verify_hashes(document, backup)
        except (RuntimeError, ValueError) as exc:
            raise RuntimeError(
                "neither interrupted Kubric output matches the recorded manifest"
            ) from exc
        displaced = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.displaced.",
                dir=output.parent,
            )
        )
        displaced.rmdir()
        os.replace(output, displaced)
        try:
            os.replace(backup, output)
        except Exception:
            os.replace(displaced, output)
            raise
        shutil.rmtree(displaced, ignore_errors=True)
    else:
        shutil.rmtree(backup)


def generate(
    manifest_path: Path,
    upstream: Path,
    output: Path,
    python: str,
) -> dict[str, str]:
    document = load_manifest(manifest_path)
    manifest_path = manifest_path.resolve()
    upstream = upstream.resolve()
    output = output.resolve()
    _require(upstream.is_dir(), f"Kubric checkout does not exist: {upstream}")
    _require_pinned_clean_checkout(upstream)
    output.parent.mkdir(parents=True, exist_ok=True)
    _recover_interrupted_publication(document, output)
    replacing_output = output.exists()
    if replacing_output:
        _require(output.is_dir(), "existing generation output must be a directory")
        verify_hashes(document, output)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    staged_output = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent)
    )
    staged_manifest: Path | None = None
    backup_output: Path | None = None
    output_published = False
    manifest_published = False
    environment = dict(os.environ)
    existing_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(upstream) + (
        os.pathsep + existing_path if existing_path else ""
    )
    command = [
        str(python),
        str(Path(__file__).resolve()),
        "_render",
        "--upstream",
        str(upstream),
        "--output",
        str(staged_output),
    ]
    try:
        subprocess.run(command, cwd=upstream, check=True, env=environment)
        hashes = collect_hashes(document, staged_output)
        with tempfile.NamedTemporaryFile(
            dir=manifest_path.parent,
            prefix=f".{manifest_path.name}.",
            suffix=".staged",
            delete=False,
        ) as stream:
            staged_manifest = Path(stream.name)
        staged_manifest.unlink()
        _write_generated_manifest(staged_manifest, document, hashes)
        if replacing_output:
            backup_output = Path(
                tempfile.mkdtemp(
                    prefix=f".{output.name}.backup.",
                    dir=output.parent,
                )
            )
            backup_output.rmdir()
            os.replace(output, backup_output)
        os.replace(staged_output, output)
        output_published = True
        os.replace(staged_manifest, manifest_path)
        manifest_published = True
        staged_manifest = None
        return hashes
    except Exception:
        if backup_output is not None and backup_output.exists():
            if output_published and output.exists():
                shutil.rmtree(output)
            os.replace(backup_output, output)
            backup_output = None
        elif output_published and not manifest_published:
            shutil.rmtree(output, ignore_errors=True)
        raise
    finally:
        if staged_manifest is not None:
            staged_manifest.unlink(missing_ok=True)
        if staged_output.exists():
            shutil.rmtree(staged_output, ignore_errors=True)
        if manifest_published and backup_output is not None:
            shutil.rmtree(backup_output, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    check = subparsers.add_parser("check", help="validate the recipe without Kubric")
    check.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    generate_parser = subparsers.add_parser(
        "generate", help="run the pinned procedural Kubric scene"
    )
    generate_parser.add_argument("--upstream", required=True, type=Path)
    generate_parser.add_argument("--output", required=True, type=Path)
    generate_parser.add_argument("--python", default="python3")
    generate_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    verify = subparsers.add_parser("verify", help="verify recorded artifact hashes")
    verify.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    verify.add_argument("--output", required=True, type=Path)
    render = subparsers.add_parser("_render", help=argparse.SUPPRESS)
    render.add_argument("--upstream", required=True, type=Path)
    render.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.operation == "check":
        document = load_manifest(args.manifest)
        print(json.dumps({"schema": document["schema"], "revision": document["upstream"]["revision"], "artifacts": len(document["artifacts"])}, sort_keys=True))
    elif args.operation == "generate":
        print(
            json.dumps(
                generate(args.manifest, args.upstream, args.output, args.python),
                sort_keys=True,
            )
        )
    elif args.operation == "_render":
        _render_scene(args.output, args.upstream)
    else:
        document = load_manifest(args.manifest, allow_generated=True)
        print(json.dumps(verify_hashes(document, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
