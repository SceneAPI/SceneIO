"""Strict COLMAP feature, pair, match, and similarity text adapters."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

import numpy as np

from sceneio import (
    CorrespondenceGraph,
    FeatureSet,
    PairCorrespondences,
    Sim3,
    feature_set,
)
from sceneio.errors import ContractViolation

from .models import (
    ColmapAdapterError,
)

_MAX_LINE_BYTES = 2 << 20
_MAX_RECORDS = 100_000_000
_UINT32_MAX = (1 << 32) - 1


def _lines(path, *, comments: bool = False):
    source = Path(path)
    try:
        stream = source.open("rb")
    except OSError as exc:
        raise ColmapAdapterError(f"cannot read {str(source)!r}: {exc}") from exc
    with stream:
        line_number = 0
        while True:
            payload = stream.readline(_MAX_LINE_BYTES + 1)
            if not payload:
                break
            line_number += 1
            if len(payload) > _MAX_LINE_BYTES:
                raise ColmapAdapterError(f"{source.name} line {line_number} exceeds 2 MiB")
            try:
                line = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ColmapAdapterError(
                    f"{source.name} line {line_number} is not UTF-8"
                ) from exc
            value = line.strip()
            if comments and (not value or value.startswith("#")):
                continue
            yield line_number, value


def _atomic_text(path, writer) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _finite(token: str, label: str) -> float:
    try:
        value = float(token)
    except ValueError as exc:
        raise ColmapAdapterError(f"{label} is not numeric") from exc
    if not math.isfinite(value):
        raise ColmapAdapterError(f"{label} must be finite")
    return value


def _uint(token: str, label: str, maximum: int = _UINT32_MAX) -> int:
    try:
        value = int(token, 10)
    except ValueError as exc:
        raise ColmapAdapterError(f"{label} is not an integer") from exc
    if value < 0 or value > maximum:
        raise ColmapAdapterError(f"{label} is outside its unsigned domain")
    return value


def _sift_descriptor(token: str, label: str) -> int:
    value = _finite(token, label)
    if value < 0 or value > 255:
        raise ColmapAdapterError(f"{label} must be in [0, 255]")
    # Explicitly match the reference importer's TruncateCast<float, uint8_t>.
    # Canonical SceneIO output is integral, so this conversion is never hidden.
    return int(value)


def read_similarity_transform(path, *, convention: str) -> Sim3:
    """Read COLMAP's one-line ``scale qw qx qy qz tx ty tz`` format.

    The format carries no frame-direction metadata, so callers must name the
    convention explicitly.
    """

    rows = [(line_number, value) for line_number, value in _lines(path) if value]
    if len(rows) != 1:
        raise ColmapAdapterError("Sim3 file must contain exactly one nonempty line")
    fields = rows[0][1].split()
    if len(fields) != 8:
        raise ColmapAdapterError("Sim3 line must contain exactly 8 values")
    values = np.asarray(
        [_finite(field, f"Sim3 field {index}") for index, field in enumerate(fields)],
        dtype=np.float64,
    )
    try:
        return Sim3.from_quaternion_wxyz(
            values[0],
            values[1:5],
            values[5:8],
            convention=convention,
        )
    except ContractViolation as exc:
        raise ColmapAdapterError(f"invalid Sim3 record: {exc}") from exc


def write_similarity_transform(value: Sim3, path) -> None:
    """Write COLMAP's locale-independent precision-17 Sim3 text."""

    if not isinstance(value, Sim3):
        raise TypeError("value must be Sim3")
    values = (
        value.scale,
        *value.to_quaternion_wxyz().tolist(),
        *value.translation.tolist(),
    )
    _atomic_text(
        path,
        lambda stream: stream.write(
            " ".join(format(float(item), ".17g") for item in values) + "\n"
        ),
    )


def read_sift_features(path) -> FeatureSet:
    """Read one COLMAP SIFT text file with exact uint8 descriptors."""

    iterator = iter(_lines(path))
    try:
        try:
            file_size = Path(path).stat().st_size
        except OSError as exc:
            raise ColmapAdapterError(f"cannot inspect SIFT file: {exc}") from exc
        return _read_sift_rows(iterator, file_size)
    finally:
        iterator.close()


def _read_sift_rows(iterator, file_size: int) -> FeatureSet:
    try:
        header_line, header = next(iterator)
    except StopIteration as exc:
        raise ColmapAdapterError("SIFT file is empty") from exc
    header_fields = header.split()
    if len(header_fields) != 2:
        raise ColmapAdapterError(f"SIFT header line {header_line} needs 2 fields")
    count = _uint(header_fields[0], "SIFT feature count", _MAX_RECORDS)
    if _uint(header_fields[1], "SIFT descriptor dimension") != 128:
        raise ColmapAdapterError("SIFT descriptor dimension must be 128")
    if count and file_size < count * 263:
        raise ColmapAdapterError("SIFT feature count exceeds the text payload")
    keypoints = np.empty((count, 4), dtype=np.float32)
    descriptors = np.empty((count, 128), dtype=np.uint8)
    for index in range(count):
        try:
            line_number, line = next(iterator)
        except StopIteration as exc:
            raise ColmapAdapterError("SIFT feature rows are truncated") from exc
        fields = line.split()
        if len(fields) != 132:
            raise ColmapAdapterError(f"SIFT line {line_number} must contain 132 fields")
        keypoints[index] = [
            _finite(field, f"SIFT line {line_number} keypoint") for field in fields[:4]
        ]
        descriptors[index] = [
            _sift_descriptor(field, f"SIFT line {line_number} descriptor") for field in fields[4:]
        ]
    for line_number, value in iterator:
        if value:
            raise ColmapAdapterError(f"SIFT line {line_number} follows the declared feature rows")
    return feature_set(keypoints, descriptors)


def write_sift_features(value: FeatureSet, path) -> None:
    """Stream a canonical SIFT text file."""

    if not isinstance(value, FeatureSet):
        raise TypeError("value must be FeatureSet")
    keypoints = np.asarray(value.keypoints)
    descriptors = value.descriptors
    if keypoints.ndim != 2 or keypoints.shape[1:] != (4,):
        raise ColmapAdapterError("SIFT keypoints must have shape (N, 4)")
    if (
        descriptors is None
        or descriptors.dtype != np.uint8
        or descriptors.shape != (keypoints.shape[0], 128)
    ):
        raise ColmapAdapterError(
            "SIFT descriptors must have dtype uint8 and shape (N, 128)"
        )
    if value.scores is not None or value.keypoint_colors is not None or value.quality is not None:
        raise ColmapAdapterError(
            "SIFT text cannot encode feature scores, colors, or quality"
        )

    def write(stream) -> None:
        stream.write(f"{value.keypoints.shape[0]} 128\n")
        for keypoint, descriptor in zip(keypoints, descriptors, strict=True):
            fields = [
                *(format(float(item), ".9g") for item in keypoint),
                *(str(int(item)) for item in descriptor),
            ]
            stream.write(" ".join(fields) + "\n")

    _atomic_text(path, write)


def read_image_pairs(
    path,
    *,
    cap_path=None,
) -> tuple[tuple[tuple[str, str], ...], np.ndarray | None]:
    """Read strict image pairs and an optional positional positive-cap sidecar."""

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    rows = iter(_lines(path, comments=True))
    try:
        for line_number, line in rows:
            fields = line.split()
            if len(fields) != 2:
                raise ColmapAdapterError(
                    f"pair line {line_number} must contain exactly two names"
                )
            if fields[0] == fields[1]:
                raise ColmapAdapterError(f"pair line {line_number} is a self-pair")
            key = tuple(sorted(fields))
            if key in seen:
                raise ColmapAdapterError(f"pair line {line_number} is duplicated")
            seen.add(key)
            pairs.append((fields[0], fields[1]))
            if len(pairs) > _MAX_RECORDS:
                raise ColmapAdapterError("pair file has too many rows")
    finally:
        rows.close()
    if cap_path is None:
        return tuple(pairs), None
    caps = []
    rows = iter(_lines(cap_path, comments=True))
    try:
        for line_number, line in rows:
            fields = line.split()
            if len(fields) != 1:
                raise ColmapAdapterError(
                    f"cap line {line_number} must contain exactly one integer"
                )
            value = _uint(fields[0], f"cap line {line_number}", (1 << 31) - 1)
            if value == 0:
                raise ColmapAdapterError(
                    f"cap line {line_number} must be positive"
                )
            caps.append(value)
    finally:
        rows.close()
    if len(caps) != len(pairs):
        raise ColmapAdapterError("cap row count must equal the image-pair count")
    result = np.asarray(caps, dtype=np.uint32)
    result.setflags(write=False)
    return tuple(pairs), result


def read_stock_image_pairs(path) -> tuple[tuple[str, str], ...]:
    """Read the stock pairing grammar with one ASCII-space separator."""

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    rows = iter(_lines(path, comments=True))
    try:
        for line_number, line in rows:
            fields = line.split(" ")
            if len(fields) != 2 or not all(fields):
                raise ColmapAdapterError(
                    f"stock pair line {line_number} needs one ASCII-space separator"
                )
            if fields[0] == fields[1]:
                raise ColmapAdapterError(
                    f"stock pair line {line_number} is a self-pair"
                )
            key = tuple(sorted(fields))
            if key in seen:
                raise ColmapAdapterError(
                    f"stock pair line {line_number} is duplicated"
                )
            seen.add(key)
            pairs.append((fields[0], fields[1]))
            if len(pairs) > _MAX_RECORDS:
                raise ColmapAdapterError("stock pair file has too many rows")
    finally:
        rows.close()
    return tuple(pairs)


def write_image_pairs(
    pairs: tuple[tuple[str, str], ...],
    path,
    *,
    caps: np.ndarray | None = None,
    cap_path=None,
) -> None:
    """Write a canonical image-pair list and optional cap sidecar."""

    normalized: list[tuple[str, str]] = []
    seen = set()
    for index, pair in enumerate(pairs):
        if len(pair) != 2 or any(
            not isinstance(name, str) or not name or any(character.isspace() for character in name)
            for name in pair
        ):
            raise ColmapAdapterError(f"pair {index} must contain two valid names")
        if pair[0] == pair[1]:
            raise ColmapAdapterError(f"pair {index} is a self-pair")
        key = tuple(sorted(pair))
        if key in seen:
            raise ColmapAdapterError(f"pair {index} is duplicated")
        seen.add(key)
        normalized.append(pair)

    def write_pairs(stream) -> None:
        for first, second in normalized:
            stream.write(f"{first} {second}\n")

    if caps is None:
        if cap_path is not None:
            raise ColmapAdapterError("cap_path requires caps")
        _atomic_text(path, write_pairs)
        return
    if cap_path is None:
        raise ColmapAdapterError("caps require cap_path")
    if Path(path).resolve(strict=False) == Path(cap_path).resolve(strict=False):
        raise ColmapAdapterError("pair and cap paths must be distinct")
    cap_values = np.asarray(caps)
    if cap_values.dtype != np.uint32 or cap_values.shape != (len(normalized),):
        raise ColmapAdapterError("caps must be positive int32-range uint32 values per pair")
    for start in range(0, cap_values.size, 65_536):
        chunk = cap_values[start : start + 65_536]
        if bool(np.any(chunk == 0)) or bool(np.any(chunk > (1 << 31) - 1)):
            raise ColmapAdapterError(
                "caps must be positive int32-range uint32 values per pair"
            )

    def write_caps(stream) -> None:
        for value in cap_values:
            stream.write(f"{int(value)}\n")

    _atomic_text(path, write_pairs)
    _atomic_text(cap_path, write_caps)


def read_feature_matches(path) -> CorrespondenceGraph:
    """Read strict COLMAP feature-match blocks separated by blank lines."""

    rows = iter(_lines(path))
    try:
        return _read_feature_match_rows(rows)
    finally:
        rows.close()


def _read_feature_match_rows(rows) -> CorrespondenceGraph:
    result: dict[tuple[str, str], PairCorrespondences] = {}
    seen = set()
    while True:
        try:
            line_number, line = next(rows)
        except StopIteration:
            break
        if not line:
            continue
        names = line.split()
        if len(names) != 2:
            raise ColmapAdapterError(f"match header line {line_number} needs two image names")
        key = tuple(sorted(names))
        if names[0] == names[1] or key in seen:
            raise ColmapAdapterError(f"match header line {line_number} is duplicate or self-paired")
        seen.add(key)
        values = []
        for match_line, match in rows:
            if not match:
                break
            fields = match.split()
            if len(fields) != 2:
                raise ColmapAdapterError(f"match line {match_line} needs two indices")
            values.append(
                (
                    _uint(fields[0], f"match line {match_line} first index"),
                    _uint(fields[1], f"match line {match_line} second index"),
                )
            )
            if len(values) > _MAX_RECORDS:
                raise ColmapAdapterError("match block has too many rows")
        matches = np.asarray(values, dtype=np.uint32).reshape(-1, 2)
        result[(names[0], names[1])] = PairCorrespondences.from_indices(matches)
    return CorrespondenceGraph({}, result, index_validation="deferred")


def write_feature_matches(value: CorrespondenceGraph, path) -> None:
    """Stream canonical blank-line-delimited COLMAP match blocks."""

    if not isinstance(value, CorrespondenceGraph):
        raise TypeError("value must be CorrespondenceGraph")
    if value.verified_pairs:
        raise ColmapAdapterError("feature-match text cannot encode a verified channel")
    for index, (key, pair) in enumerate(value.pairs.items()):
        if any(any(character.isspace() for character in name) for name in key):
            raise ColmapAdapterError(f"match block {index} image names cannot contain whitespace")
        if pair.mode != "indexed" or pair.indices is None:
            raise ColmapAdapterError("feature-match text requires indexed correspondences")
        if pair.scores is not None or pair.geometry is not None:
            raise ColmapAdapterError(
                "feature-match text cannot encode scores or two-view geometry"
            )

    def write(stream) -> None:
        for (image_name1, image_name2), pair in value.pairs.items():
            stream.write(f"{image_name1} {image_name2}\n")
            assert pair.indices is not None
            for first, second in pair.indices:
                stream.write(f"{int(first)} {int(second)}\n")
            stream.write("\n")

    _atomic_text(path, write)
