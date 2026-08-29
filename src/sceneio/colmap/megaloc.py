"""MegaLoc descriptor/pair artifact directory adapter."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PurePosixPath

import numpy as np

from .models import (
    ColmapAdapterError,
    MegaLocArtifacts,
    MegaLocImage,
    MegaLocPair,
)

_SCHEMA = "colmap.megaloc.artifacts"
_VERSION = 1
_PAIR_HEADER = "image_id1\timage_id2\tscore\tis_retrieval\tis_sequential\timage_name1\timage_name2"
_PAIR_COLUMNS = _PAIR_HEADER.split("\t")
_MAX_JSON_BYTES = 64 * 1024 * 1024
_MAX_TEXT_LINE = 1 << 20
_MAX_DESCRIPTOR_VALUES = 1_000_000_000
_MAX_PAIRS = 100_000_000


def _reject_unknown_keys(value: dict, allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ColmapAdapterError(
            f"MegaLoc {label} has unknown fields: " + ", ".join(unknown)
        )


def _metadata_text(value) -> str:
    def validate(item) -> None:
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ColmapAdapterError(
                    "MegaLoc metadata object keys must be text"
                )
            for child in item.values():
                validate(child)
            return
        if isinstance(item, list):
            for child in item:
                validate(child)
            return
        if item is None or isinstance(item, bool | int | str):
            return
        if isinstance(item, float) and np.isfinite(item):
            return
        raise ColmapAdapterError(
            "MegaLoc metadata must contain finite JSON values"
        )

    payload = dict(value)
    validate(payload)
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ColmapAdapterError(
            f"MegaLoc metadata is not JSON-serializable: {exc}"
        ) from exc


def _reject_json_constant(token: str):
    raise ValueError(f"invalid JSON constant {token}")


def _artifact_path(root: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ColmapAdapterError(f"MegaLoc {label} path is missing")
    logical = PurePosixPath(value.replace("\\", "/"))
    if logical.is_absolute() or ".." in logical.parts:
        raise ColmapAdapterError(f"MegaLoc {label} path must stay within the artifact directory")
    candidate = root.joinpath(*logical.parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise ColmapAdapterError(
            f"MegaLoc {label} path must stay within the artifact directory"
        ) from exc
    return candidate


def _require_distinct_paths(paths: list[Path]) -> None:
    if len({path.resolve(strict=False) for path in paths}) != len(paths):
        raise ColmapAdapterError("MegaLoc artifact paths must be distinct")


def _load_manifest(path) -> tuple[Path, dict]:
    supplied = Path(path)
    manifest_path = supplied / "manifest.json" if supplied.is_dir() else supplied
    try:
        size = manifest_path.stat().st_size
        if size > _MAX_JSON_BYTES:
            raise ColmapAdapterError("MegaLoc manifest exceeds 64 MiB")
        value = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except ColmapAdapterError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise ColmapAdapterError(
            f"cannot read MegaLoc manifest {str(manifest_path)!r}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ColmapAdapterError("MegaLoc manifest root must be an object")
    if (
        value.get("schema") != _SCHEMA
        or isinstance(value.get("schema_version"), bool)
        or value.get("schema_version") != _VERSION
    ):
        raise ColmapAdapterError("MegaLoc manifest schema/version is unsupported")
    _reject_unknown_keys(
        value,
        {
            "schema",
            "schema_version",
            "image_root",
            "images",
            "descriptors",
            "pairs",
            "model",
            "metadata",
        },
        "manifest",
    )
    return manifest_path, value


def _images(value) -> tuple[MegaLocImage, ...]:
    if not isinstance(value, list):
        raise ColmapAdapterError("MegaLoc images must be an array")
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ColmapAdapterError(f"MegaLoc image {index} must be an object")
        _reject_unknown_keys(
            item,
            {"image_id", "image_name", "image_path"},
            f"image {index}",
        )
        try:
            result.append(MegaLocImage(item["image_id"], item["image_name"], item["image_path"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ColmapAdapterError(f"MegaLoc image {index} is malformed") from exc
    return tuple(result)


def _read_pairs(path: Path, expected_count: int) -> tuple[MegaLocPair, ...]:
    try:
        stream = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ColmapAdapterError(f"cannot read MegaLoc pair scores {str(path)!r}: {exc}") from exc
    result = []
    with stream:
        header = stream.readline(_MAX_TEXT_LINE + 1).rstrip("\r\n")
        if header != _PAIR_HEADER:
            raise ColmapAdapterError("MegaLoc pair score header is not the v1 schema")
        line_number = 1
        while True:
            line = stream.readline(_MAX_TEXT_LINE + 1)
            if not line:
                break
            line_number += 1
            if len(line) > _MAX_TEXT_LINE:
                raise ColmapAdapterError(f"MegaLoc pair score line {line_number} exceeds its bound")
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 7:
                raise ColmapAdapterError(f"MegaLoc pair score line {line_number} needs 7 fields")
            try:
                retrieval = int(fields[3], 10)
                sequential = int(fields[4], 10)
                if retrieval not in (0, 1) or sequential not in (0, 1):
                    raise ValueError
                result.append(
                    MegaLocPair(
                        int(fields[0], 10),
                        int(fields[1], 10),
                        float(fields[2]),
                        bool(retrieval),
                        bool(sequential),
                        fields[5],
                        fields[6],
                    )
                )
                if len(result) > expected_count or len(result) > _MAX_PAIRS:
                    raise ColmapAdapterError(
                        "MegaLoc pair score row count exceeds its bound"
                    )
            except ValueError as exc:
                raise ColmapAdapterError(
                    f"MegaLoc pair score line {line_number} is malformed"
                ) from exc
    return tuple(result)


def _validate_pair_list(
    path: Path,
    pairs: tuple[MegaLocPair, ...],
) -> None:
    try:
        stream = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ColmapAdapterError(f"cannot read MegaLoc pair list {str(path)!r}: {exc}") from exc
    with stream:
        for index, pair in enumerate(pairs, 1):
            line = stream.readline(_MAX_TEXT_LINE + 1)
            if not line:
                raise ColmapAdapterError("MegaLoc pair list is truncated")
            if len(line) > _MAX_TEXT_LINE:
                raise ColmapAdapterError(f"MegaLoc pair list line {index} exceeds its bound")
            if line.rstrip("\r\n") != (f"{pair.image_name1} {pair.image_name2}"):
                raise ColmapAdapterError(f"MegaLoc pair list line {index} disagrees with scores")
        extra = stream.readline(_MAX_TEXT_LINE + 1)
        if len(extra) > _MAX_TEXT_LINE:
            raise ColmapAdapterError("MegaLoc pair list extra row exceeds its bound")
        if extra:
            raise ColmapAdapterError("MegaLoc pair list has more rows than pair scores")


def read_megaloc_artifacts(
    path,
    *,
    load_descriptors: bool = True,
) -> MegaLocArtifacts:
    """Read and cross-validate one MegaLoc artifact directory."""

    manifest_path, manifest = _load_manifest(path)
    root = manifest_path.parent
    images = _images(manifest.get("images"))
    if len({item.image_id for item in images}) != len(images):
        raise ColmapAdapterError("MegaLoc image ids must be unique")
    if len({item.image_name for item in images}) != len(images):
        raise ColmapAdapterError("MegaLoc image names must be unique")
    pairs_value = manifest.get("pairs")
    if not isinstance(pairs_value, dict):
        raise ColmapAdapterError("MegaLoc pairs manifest entry must be an object")
    _reject_unknown_keys(
        pairs_value,
        {"colmap_file", "scores_file", "count", "scores_columns"},
        "pairs entry",
    )
    if pairs_value.get("scores_columns") != _PAIR_COLUMNS:
        raise ColmapAdapterError("MegaLoc pair score columns are not the v1 schema")
    pair_count = pairs_value.get("count")
    if (
        isinstance(pair_count, bool)
        or not isinstance(pair_count, int)
        or pair_count < 0
        or pair_count > _MAX_PAIRS
    ):
        raise ColmapAdapterError("MegaLoc manifest pair count is outside bounds")
    pair_list_path = _artifact_path(root, pairs_value.get("colmap_file"), "pair list")
    scores_path = _artifact_path(root, pairs_value.get("scores_file"), "pair scores")
    _require_distinct_paths([manifest_path, pair_list_path, scores_path])
    pairs = _read_pairs(scores_path, pair_count)
    if pair_count != len(pairs):
        raise ColmapAdapterError("MegaLoc manifest pair count disagrees with the score file")
    if len(
        {
            (min(item.image_id1, item.image_id2), max(item.image_id1, item.image_id2))
            for item in pairs
        }
    ) != len(pairs):
        raise ColmapAdapterError("MegaLoc image pairs must be unique")
    _validate_pair_list(pair_list_path, pairs)

    by_id = {item.image_id: item.image_name for item in images}
    for index, pair in enumerate(pairs):
        if (
            by_id.get(pair.image_id1) != pair.image_name1
            or by_id.get(pair.image_id2) != pair.image_name2
        ):
            raise ColmapAdapterError(f"MegaLoc pair {index} disagrees with the image table")

    metadata = manifest.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ColmapAdapterError("MegaLoc metadata must be an object")
    _metadata_text(metadata)
    model = manifest.get("model", {})
    if not isinstance(model, dict):
        raise ColmapAdapterError("MegaLoc model entry must be an object")
    _reject_unknown_keys(model, {"onnx_path", "engine_path"}, "model entry")
    image_root = manifest.get("image_root")
    if image_root is not None and not isinstance(image_root, str):
        raise ColmapAdapterError("MegaLoc image_root must be text or null")
    for key in ("onnx_path", "engine_path"):
        if model.get(key) is not None and not isinstance(model.get(key), str):
            raise ColmapAdapterError(f"MegaLoc model {key} must be text or null")

    descriptors_value = manifest.get("descriptors")
    descriptors = None
    owner = None
    normalized = False
    if descriptors_value is not None:
        if not isinstance(descriptors_value, dict):
            raise ColmapAdapterError("MegaLoc descriptors must be null or an object")
        _reject_unknown_keys(
            descriptors_value,
            {"file", "dtype", "layout", "rows", "cols", "normalized"},
            "descriptors entry",
        )
        if (
            descriptors_value.get("dtype") != "float32_le"
            or descriptors_value.get("layout") != "row_major"
        ):
            raise ColmapAdapterError("MegaLoc descriptor dtype/layout is unsupported")
        rows = descriptors_value.get("rows")
        columns = descriptors_value.get("cols")
        if (
            isinstance(rows, bool)
            or not isinstance(rows, int)
            or isinstance(columns, bool)
            or not isinstance(columns, int)
            or rows != len(images)
            or columns < 0
            or columns > _MAX_DESCRIPTOR_VALUES
            or rows * columns > _MAX_DESCRIPTOR_VALUES
        ):
            raise ColmapAdapterError("MegaLoc descriptor dimensions are outside bounds")
        normalized = descriptors_value.get("normalized")
        if not isinstance(normalized, bool):
            raise ColmapAdapterError(
                "MegaLoc descriptor normalized flag must be boolean"
            )
        descriptor_path = _artifact_path(root, descriptors_value.get("file"), "descriptor")
        _require_distinct_paths(
            [manifest_path, descriptor_path, pair_list_path, scores_path]
        )
        try:
            if descriptor_path.stat().st_size != rows * columns * 4:
                raise ColmapAdapterError("MegaLoc descriptor payload size disagrees with manifest")
            if load_descriptors:
                if rows * columns == 0:
                    descriptors = np.empty((rows, columns), dtype=np.float32)
                else:
                    owner = np.memmap(
                        descriptor_path,
                        dtype="<f4",
                        mode="r",
                        shape=(rows, columns),
                        order="C",
                    )
                    descriptors = np.asarray(owner)
                descriptors.setflags(write=False)
        except OSError as exc:
            raise ColmapAdapterError(f"cannot read MegaLoc descriptors: {exc}") from exc
    return MegaLocArtifacts(
        root,
        images,
        pairs,
        descriptors,
        normalized,
        metadata,
        image_root,
        model.get("onnx_path"),
        model.get("engine_path"),
        owner,
    )


def inspect_megaloc_artifacts(path) -> dict[str, int | bool]:
    """Inspect the complete artifact topology without mapping descriptors."""

    value = read_megaloc_artifacts(path, load_descriptors=False)
    _, manifest = _load_manifest(path)
    descriptor = manifest.get("descriptors")
    return {
        "num_images": len(value.images),
        "num_pairs": len(value.pairs),
        "has_descriptors": descriptor is not None,
        "descriptor_rows": 0 if descriptor is None else descriptor["rows"],
        "descriptor_columns": 0 if descriptor is None else descriptor["cols"],
    }


def _json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _score_text(value: float) -> str:
    if np.isnan(value):
        return "nan"
    return format(np.float32(value).item(), ".9g")


def _manifest_text(
    value: MegaLocArtifacts,
    *,
    descriptor_file: str,
    pair_list_file: str,
    pair_scores_file: str,
) -> str:
    lines = ["{", '  "descriptors": ']
    if value.descriptors is None:
        lines[-1] += "null,"
    else:
        lines[-1] += "{"
        lines.extend(
            [
                f'    "cols": {value.descriptors.shape[1]},',
                '    "dtype": "float32_le",',
                f'    "file": {_json_string(descriptor_file)},',
                '    "layout": "row_major",',
                f'    "normalized": {str(value.descriptors_normalized).lower()},',
                f'    "rows": {value.descriptors.shape[0]}',
                "  },",
            ]
        )
    image_root = "null" if value.image_root is None else _json_string(value.image_root)
    lines.extend([f'  "image_root": {image_root},', '  "images": ['])
    for index, image in enumerate(value.images):
        lines.extend(
            [
                "    {",
                f'      "image_id": {image.image_id},',
                f'      "image_name": {_json_string(image.image_name)},',
                f'      "image_path": {_json_string(image.image_path)}',
                "    }" + ("" if index + 1 == len(value.images) else ","),
            ]
        )
    metadata = _metadata_text(value.metadata)
    engine = "null" if value.model_engine_path is None else _json_string(value.model_engine_path)
    model = "null" if value.model_onnx_path is None else _json_string(value.model_onnx_path)
    lines.extend(
        [
            "  ],",
            f'  "metadata": {metadata},',
            '  "model": {',
            f'    "engine_path": {engine},',
            f'    "onnx_path": {model}',
            "  },",
            '  "pairs": {',
            f'    "colmap_file": {_json_string(pair_list_file)},',
            f'    "count": {len(value.pairs)},',
            '    "scores_columns": [',
            '      "image_id1",',
            '      "image_id2",',
            '      "score",',
            '      "is_retrieval",',
            '      "is_sequential",',
            '      "image_name1",',
            '      "image_name2"',
            "    ],",
            f'    "scores_file": {_json_string(pair_scores_file)}',
            "  },",
            f'  "schema": {_json_string(_SCHEMA)},',
            f'  "schema_version": {_VERSION}',
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def _replace_file(path: Path, write) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def write_megaloc_artifacts(
    value: MegaLocArtifacts,
    path,
    *,
    descriptor_file: str = "descriptors.f32",
    pair_list_file: str = "pairs.txt",
    pair_scores_file: str = "pairs.tsv",
    manifest_file: str = "manifest.json",
    overwrite: bool = False,
) -> None:
    """Write canonical v1 descriptor, pair, score, and manifest files."""

    if not isinstance(value, MegaLocArtifacts):
        raise TypeError("value must be MegaLocArtifacts")
    root = Path(path)
    descriptor_path = _artifact_path(root, descriptor_file, "descriptor")
    pair_list_path = _artifact_path(root, pair_list_file, "pair list")
    pair_scores_path = _artifact_path(root, pair_scores_file, "pair scores")
    manifest_path = _artifact_path(root, manifest_file, "manifest")
    owned_targets = [
        descriptor_path,
        pair_list_path,
        pair_scores_path,
        manifest_path,
    ]
    _require_distinct_paths(owned_targets)
    existing = [str(target) for target in owned_targets if target.exists()]
    if existing and not overwrite:
        raise ColmapAdapterError("MegaLoc artifact files already exist: " + ", ".join(existing))

    by_id = {item.image_id: item.image_name for item in value.images}
    for index, pair in enumerate(value.pairs):
        if (
            by_id.get(pair.image_id1) != pair.image_name1
            or by_id.get(pair.image_id2) != pair.image_name2
        ):
            raise ColmapAdapterError(f"MegaLoc pair {index} disagrees with the image table")

    manifest = _manifest_text(
        value,
        descriptor_file=descriptor_file,
        pair_list_file=pair_list_file,
        pair_scores_file=pair_scores_file,
    ).encode("utf-8")
    if len(manifest) > _MAX_JSON_BYTES:
        raise ColmapAdapterError("MegaLoc manifest exceeds 64 MiB")
    if len((_PAIR_HEADER + "\n").encode("utf-8")) > _MAX_TEXT_LINE:
        raise ColmapAdapterError("MegaLoc pair score header exceeds its bound")
    for index, item in enumerate(value.pairs):
        pair_line = f"{item.image_name1} {item.image_name2}\n".encode()
        score_line = (
            f"{item.image_id1}\t{item.image_id2}\t"
            f"{_score_text(item.score)}\t{int(item.is_retrieval)}\t"
            f"{int(item.is_sequential)}\t{item.image_name1}\t"
            f"{item.image_name2}\n"
        ).encode()
        if len(pair_line) > _MAX_TEXT_LINE:
            raise ColmapAdapterError(
                f"MegaLoc pair list row {index} exceeds its bound"
            )
        if len(score_line) > _MAX_TEXT_LINE:
            raise ColmapAdapterError(
                f"MegaLoc pair score row {index} exceeds its bound"
            )

    for target in owned_targets:
        target.parent.mkdir(parents=True, exist_ok=True)

    if value.descriptors is not None:
        descriptors_le = value.descriptors.astype("<f4", copy=False)

        def write_descriptors(stream) -> None:
            if descriptors_le.size:
                stream.write(memoryview(descriptors_le).cast("B"))

        _replace_file(
            descriptor_path,
            write_descriptors,
        )

    def write_pair_list(stream) -> None:
        for item in value.pairs:
            stream.write(f"{item.image_name1} {item.image_name2}\n".encode())

    def write_pair_scores(stream) -> None:
        stream.write((_PAIR_HEADER + "\n").encode("utf-8"))
        for item in value.pairs:
            stream.write(
                (
                    f"{item.image_id1}\t{item.image_id2}\t"
                    f"{_score_text(item.score)}\t{int(item.is_retrieval)}\t"
                    f"{int(item.is_sequential)}\t{item.image_name1}\t"
                    f"{item.image_name2}\n"
                ).encode()
            )

    _replace_file(pair_list_path, write_pair_list)
    _replace_file(pair_scores_path, write_pair_scores)
    _replace_file(manifest_path, lambda stream: stream.write(manifest))
