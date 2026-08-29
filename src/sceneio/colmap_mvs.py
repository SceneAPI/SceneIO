"""Lazy, repository-owned access to a COLMAP dense workspace.

The adapter owns workspace topology and cross-file conventions. Image payloads
remain opaque paths: SceneIO never decodes or rewrites media while opening or
validating a workspace. Dense map and visibility payloads are delegated to the
compiled ``colmap_mvs_*`` codecs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

import numpy as np

from sceneio.errors import SceneIoError

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sceneio import _core

InputType = Literal["photometric", "geometric"]
SourceMode = Literal["all", "auto", "explicit"]

_INPUT_TYPES: tuple[InputType, ...] = ("photometric", "geometric")
_MAP_DIRECTORIES = {
    "depth": "depth_maps",
    "normal": "normal_maps",
    "consistency": "consistency_graphs",
}


class ColmapMvsError(SceneIoError):
    """A COLMAP dense workspace or configuration is inconsistent."""


@dataclass(frozen=True)
class PatchMatchProblem:
    """One two-line ``patch-match.cfg`` problem."""

    reference_image: str
    source_mode: SourceMode
    source_images: tuple[str, ...] = ()
    max_source_images: int | None = None


@dataclass(frozen=True)
class DenseMapSet:
    """Paths for one image and one COLMAP dense input type."""

    image_index: int
    image_id: int
    image_name: str
    input_type: InputType
    image_path: Path
    depth_path: Path
    normal_path: Path
    consistency_path: Path

    @property
    def has_depth(self) -> bool:
        return self.depth_path.is_file()

    @property
    def has_normal(self) -> bool:
        return self.normal_path.is_file()

    @property
    def has_consistency(self) -> bool:
        return self.consistency_path.is_file()


@dataclass(frozen=True)
class WorkspaceValidation:
    """Successful structural/deep validation summary."""

    num_images: int
    num_map_sets: int
    num_depth_maps: int
    num_normal_maps: int
    num_consistency_graphs: int
    fused_point_count: int | None
    visibility_point_count: int | None
    deep: bool


@dataclass(frozen=True)
class WorkspaceInspection:
    """Lazy inventory for a COLMAP dense workspace."""

    root: Path
    sparse_path: Path
    sparse_format: str
    num_images: int
    image_names: tuple[str, ...]
    patch_match_problem_count: int
    fusion_image_count: int
    map_sets: tuple[DenseMapSet, ...]
    fused_path: Path | None
    visibility_path: Path | None
    validation: WorkspaceValidation


@dataclass(frozen=True)
class ProjectionMatrix:
    """A ``CONTOUR`` 3x4 camera projection text payload."""

    values: np.ndarray
    source_text: str | None = None


@dataclass(frozen=True)
class PmvsVisibilityGraph:
    """Raw PMVS ``vis.dat`` rows.

    ``visible_values`` deliberately does not claim an image-index domain.
    ``colmap_mod`` writes persisted COLMAP image IDs but its raw-PMVS reader
    interprets the same values as zero-based positions.
    """

    num_images: int
    row_indices: np.ndarray
    offsets: np.ndarray
    visible_values: np.ndarray
    value_domain: str = "raw_colmap_image_id_or_mvs_index"


@dataclass(frozen=True)
class LegacyMvsImageRef:
    """One opaque encoded image and its projection companion."""

    index: int
    image_path: Path
    projection_path: Path | None


@dataclass(frozen=True)
class LegacyMvsWorkspace:
    """Lazy PMVS or CMP-MVS export inventory."""

    profile: Literal["pmvs", "cmp_mvs"]
    model_source: Literal["raw_pmvs", "bundler", "projection_files"]
    root: Path
    images: tuple[LegacyMvsImageRef, ...]
    visibility_path: Path | None = None
    bundle_path: Path | None = None
    bundle_list_path: Path | None = None
    option_paths: tuple[Path, ...] = ()

    @property
    def num_images(self) -> int:
        return len(self.images)

    def image(self, index: int) -> LegacyMvsImageRef:
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("legacy MVS image index must be an integer")
        if index < 0 or index >= self.num_images:
            raise IndexError(
                f"legacy MVS image index {index} is outside "
                f"0..{self.num_images - 1}"
            )
        return self.images[index]

    def read_projection(self, index: int) -> ProjectionMatrix:
        path = self.image(index).projection_path
        if path is None:
            raise ColmapMvsError(
                "projection files are not present in this Bundler-profile "
                "PMVS workspace"
            )
        return read_projection_matrix(path)

    def write_projection(
        self,
        index: int,
        projection: ProjectionMatrix,
    ) -> None:
        path = self.image(index).projection_path
        if path is None:
            raise ColmapMvsError(
                "projection files are not present in this Bundler-profile "
                "PMVS workspace"
            )
        write_projection_matrix(projection, path)

    def read_visibility(self) -> PmvsVisibilityGraph:
        if self.profile != "pmvs" or self.visibility_path is None:
            raise ColmapMvsError(
                "visibility data is available only for a PMVS workspace"
            )
        graph = read_pmvs_visibility(self.visibility_path)
        if graph.num_images != self.num_images:
            raise ColmapMvsError(
                f"PMVS visibility declares {graph.num_images} images but "
                f"the workspace contains {self.num_images}"
            )
        return graph

    def write_visibility(self, graph: PmvsVisibilityGraph) -> None:
        if self.profile != "pmvs" or self.visibility_path is None:
            raise ColmapMvsError(
                "visibility data is available only for a PMVS workspace"
            )
        if graph.num_images != self.num_images:
            raise ColmapMvsError(
                f"PMVS visibility declares {graph.num_images} images but "
                f"the workspace contains {self.num_images}"
            )
        write_pmvs_visibility(graph, self.visibility_path)

    def read_bundle(self):
        if self.profile != "pmvs" or self.bundle_path is None:
            raise ColmapMvsError(
                "a Bundler model is available only for a PMVS workspace"
            )
        if not self.bundle_path.is_file():
            raise ColmapMvsError(
                f"PMVS bundle {str(self.bundle_path)!r} is missing"
            )
        from sceneio.io import read

        return read(self.bundle_path, format="bundler")

    def read_bundle_image_names(self) -> tuple[str, ...]:
        if self.profile != "pmvs" or self.bundle_list_path is None:
            raise ColmapMvsError(
                "a Bundler image list is available only for a PMVS workspace"
            )
        names = read_image_name_list(self.bundle_list_path)
        if len(names) != self.num_images:
            raise ColmapMvsError(
                f"PMVS Bundler list contains {len(names)} names but the "
                f"workspace contains {self.num_images} images"
            )
        return names

    def write_bundle_image_names(self, names: Iterable[str]) -> None:
        if self.profile != "pmvs" or self.bundle_list_path is None:
            raise ColmapMvsError(
                "a Bundler image list is available only for a PMVS workspace"
            )
        values = tuple(names)
        if len(values) != self.num_images:
            raise ColmapMvsError(
                f"PMVS Bundler list contains {len(values)} names but the "
                f"workspace contains {self.num_images} images"
            )
        write_image_name_list(values, self.bundle_list_path)


@dataclass(frozen=True)
class ColmapMvsWorkspace:
    """A lazy COLMAP dense workspace.

    Opening the workspace decodes only the sparse reconstruction and the two
    small text configurations. Dense maps, fused points, and visibility lists
    are loaded on demand.
    """

    root: Path
    sparse_path: Path
    sparse_format: str
    images_path: Path
    stereo_path: Path
    reconstruction: object
    image_ids: tuple[int, ...]
    image_names: tuple[str, ...]
    patch_match_problems: tuple[PatchMatchProblem, ...]
    fusion_images: tuple[str, ...]
    has_patch_match_config: bool
    has_fusion_config: bool

    @property
    def num_images(self) -> int:
        return len(self.image_names)

    @property
    def patch_match_config_path(self) -> Path:
        return self.stereo_path / "patch-match.cfg"

    @property
    def fusion_config_path(self) -> Path:
        return self.stereo_path / "fusion.cfg"

    @property
    def fused_path(self) -> Path:
        return self.root / "fused.ply"

    @property
    def visibility_path(self) -> Path:
        return self.root / "fused.ply.vis"

    def image_index(self, image: int | str) -> int:
        if isinstance(image, str):
            try:
                return self.image_names.index(image)
            except ValueError as exc:
                raise ColmapMvsError(
                    f"image {image!r} is not present in the sparse model"
                ) from exc
        if isinstance(image, bool) or not isinstance(image, int):
            raise TypeError("image must be a sequential index or image name")
        if image < 0 or image >= self.num_images:
            raise IndexError(
                f"MVS image index {image} is outside 0..{self.num_images - 1}"
            )
        return image

    def map_set(
        self,
        image: int | str,
        input_type: InputType = "geometric",
    ) -> DenseMapSet:
        index = self.image_index(image)
        selected_type = _input_type(input_type)
        image_name = self.image_names[index]
        relative = _relative_image_path(image_name)
        filename = relative.name + f".{selected_type}.bin"

        def map_path(kind: str) -> Path:
            return (
                self.stereo_path
                / _MAP_DIRECTORIES[kind]
                / relative.parent
                / filename
            )

        return DenseMapSet(
            image_index=index,
            image_id=self.image_ids[index],
            image_name=image_name,
            input_type=selected_type,
            image_path=self.images_path / relative,
            depth_path=map_path("depth"),
            normal_path=map_path("normal"),
            consistency_path=map_path("consistency"),
        )

    def map_sets(self) -> tuple[DenseMapSet, ...]:
        return tuple(
            self.map_set(index, input_type)
            for index in range(self.num_images)
            for input_type in _INPUT_TYPES
        )

    def read_depth(
        self,
        image: int | str,
        input_type: InputType = "geometric",
    ) -> _core.DepthMap:
        from sceneio.io import read

        return read(
            self.map_set(image, input_type).depth_path,
            format="colmap_mvs_depth",
        )

    def read_normal(
        self,
        image: int | str,
        input_type: InputType = "geometric",
    ) -> _core.NormalMap:
        from sceneio.io import read

        return read(
            self.map_set(image, input_type).normal_path,
            format="colmap_mvs_normal",
        )

    def read_consistency(
        self,
        image: int | str,
        input_type: InputType = "geometric",
    ) -> _core.ConsistencyGraph:
        from sceneio.io import read

        result = read(
            self.map_set(image, input_type).consistency_path,
            format="colmap_mvs_consistency",
        )
        _validate_image_indices(
            result.image_indices,
            self.num_images,
            "consistency graph",
        )
        return result

    def read_fused_points(self) -> _core.PointCloud:
        from sceneio.io import read

        return read(self.fused_path, format="ply")

    def read_visibility(self) -> _core.PointVisibility:
        from sceneio.io import read

        result = read(
            self.visibility_path,
            format="colmap_fused_visibility",
        )
        _validate_image_indices(
            result.image_indices,
            self.num_images,
            "fused visibility",
        )
        if self.fused_path.is_file():
            fused_count = _fused_point_count(self.fused_path)
            if result.num_points != fused_count:
                raise ColmapMvsError(
                    "fused visibility point count "
                    f"{result.num_points} does not match fused.ply count "
                    f"{fused_count}"
                )
        return result

    def write_depth(
        self,
        image: int | str,
        value: _core.DepthMap,
        input_type: InputType = "geometric",
    ) -> None:
        from sceneio.io import write

        target = self.map_set(image, input_type).depth_path
        target.parent.mkdir(parents=True, exist_ok=True)
        write(value, target, format="colmap_mvs_depth")

    def write_normal(
        self,
        image: int | str,
        value: _core.NormalMap,
        input_type: InputType = "geometric",
    ) -> None:
        from sceneio.io import write

        target = self.map_set(image, input_type).normal_path
        target.parent.mkdir(parents=True, exist_ok=True)
        write(value, target, format="colmap_mvs_normal")

    def write_consistency(
        self,
        image: int | str,
        value: _core.ConsistencyGraph,
        input_type: InputType = "geometric",
    ) -> None:
        from sceneio.io import write

        _validate_image_indices(
            value.image_indices,
            self.num_images,
            "consistency graph",
        )
        target = self.map_set(image, input_type).consistency_path
        target.parent.mkdir(parents=True, exist_ok=True)
        write(value, target, format="colmap_mvs_consistency")

    def write_visibility(self, value: _core.PointVisibility) -> None:
        from sceneio.io import write

        _validate_image_indices(
            value.image_indices,
            self.num_images,
            "fused visibility",
        )
        if self.fused_path.is_file():
            fused_count = _fused_point_count(self.fused_path)
            if value.num_points != fused_count:
                raise ColmapMvsError(
                    "fused visibility point count "
                    f"{value.num_points} does not match fused.ply count "
                    f"{fused_count}"
                )
        write(
            value,
            self.visibility_path,
            format="colmap_fused_visibility",
        )

    def validate(self, *, deep: bool = False) -> WorkspaceValidation:
        return validate_workspace(self, deep=deep)


def _input_type(value: str) -> InputType:
    if value not in _INPUT_TYPES:
        raise ValueError(
            "input_type must be 'photometric' or 'geometric'"
        )
    return value


def _relative_image_path(name: str) -> Path:
    if not isinstance(name, str) or not name:
        raise ColmapMvsError("sparse image names must be non-empty strings")
    if "\0" in name:
        raise ColmapMvsError("sparse image names cannot contain NUL")
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    raw_parts = normalized.split("/")
    if (
        pure.is_absolute()
        or not raw_parts
        or any(part in {"", ".", ".."} for part in raw_parts)
        or (raw_parts and raw_parts[0].endswith(":"))
    ):
        raise ColmapMvsError(
            f"sparse image name {name!r} is not a safe relative path"
        )
    return Path(*raw_parts)


def _validate_unique_image_paths(names: Sequence[str]) -> None:
    normalized: dict[str, str] = {}
    for name in names:
        key = _relative_image_path(name).as_posix().casefold()
        previous = normalized.get(key)
        if previous is not None:
            raise ColmapMvsError(
                f"image names {previous!r} and {name!r} map to the same path"
            )
        normalized[key] = name


def read_image_name_list(path) -> tuple[str, ...]:
    """Read a Bundler/PMVS one-name-per-line companion."""

    source = Path(path)
    try:
        names = tuple(source.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError) as exc:
        raise ColmapMvsError(
            f"cannot read image-name list {str(source)!r}: {exc}"
        ) from exc
    if any(not name for name in names):
        raise ColmapMvsError("image-name list contains an empty name")
    _validate_unique_image_paths(names)
    return names


def write_image_name_list(names: Iterable[str], path) -> None:
    """Write a portable one-name-per-line image companion."""

    values = tuple(names)
    if any(not isinstance(name, str) or not name for name in values):
        raise ColmapMvsError("image-name list values must be non-empty strings")
    _validate_unique_image_paths(values)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(f"{name}\n" for name in values),
        encoding="utf-8",
        newline="\n",
    )


def _projection_values(value: ProjectionMatrix) -> np.ndarray:
    if not isinstance(value, ProjectionMatrix):
        raise TypeError("projection must be a ProjectionMatrix")
    matrix = np.asarray(value.values)
    if (
        matrix.dtype != np.float64
        or matrix.shape != (3, 4)
        or not matrix.flags.c_contiguous
    ):
        raise ColmapMvsError(
            "projection values must be a C-contiguous float64 array "
            "with shape (3,4)"
        )
    if not np.isfinite(matrix).all():
        raise ColmapMvsError("projection values must be finite")
    return matrix


def _parse_projection_text(text: str) -> np.ndarray:
    lines = text.splitlines()
    if len(lines) != 4 or lines[0].strip() != "CONTOUR":
        raise ColmapMvsError(
            "projection file must contain CONTOUR and exactly three rows"
        )
    values: list[float] = []
    for row in lines[1:]:
        tokens = row.split()
        if len(tokens) != 4:
            raise ColmapMvsError(
                "each projection matrix row must contain four numbers"
            )
        try:
            values.extend(float(token) for token in tokens)
        except ValueError as exc:
            raise ColmapMvsError(
                "projection matrix contains a non-numeric token"
            ) from exc
    result = np.array(values, dtype=np.float64).reshape(3, 4)
    if not np.isfinite(result).all():
        raise ColmapMvsError("projection values must be finite")
    return result


def read_projection_matrix(path) -> ProjectionMatrix:
    """Read a PMVS/CMP-MVS ``CONTOUR`` projection matrix."""

    source = Path(path)
    try:
        text = source.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ColmapMvsError(
            f"cannot read projection matrix {str(source)!r}: {exc}"
        ) from exc
    values = _parse_projection_text(text)
    values.setflags(write=False)
    return ProjectionMatrix(values=values, source_text=text)


def write_projection_matrix(value: ProjectionMatrix, path) -> None:
    """Write a projection matrix, preserving unchanged source text exactly."""

    matrix = _projection_values(value)
    text = None
    if value.source_text is not None:
        source_values = _parse_projection_text(value.source_text)
        if np.array_equal(
            source_values.view(np.uint64),
            matrix.view(np.uint64),
        ):
            text = value.source_text
    if text is None:
        rows = (
            " ".join(format(float(item), ".17g") for item in row)
            for row in matrix
        )
        text = "CONTOUR\n" + "".join(f"{row}\n" for row in rows)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def _validate_visibility_row_permutation(
    rows: np.ndarray,
    num_images: int,
) -> None:
    if not rows.size:
        return
    if int(rows.max()) >= num_images:
        raise ColmapMvsError(
            "PMVS visibility rows must be a permutation of 0..N-1"
        )
    seen = np.zeros((num_images,), dtype=np.bool_)
    for start in range(0, rows.size, 65_536):
        seen[rows[start : start + 65_536]] = True
    if not bool(np.all(seen)):
        raise ColmapMvsError(
            "PMVS visibility rows must be a permutation of 0..N-1"
        )


def _visibility_arrays(
    graph: PmvsVisibilityGraph,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not isinstance(graph, PmvsVisibilityGraph):
        raise TypeError("visibility must be a PmvsVisibilityGraph")
    if (
        isinstance(graph.num_images, bool)
        or not isinstance(graph.num_images, int)
        or graph.num_images < 0
        or graph.num_images > 10_000_000
    ):
        raise ColmapMvsError("PMVS visibility image count is outside bounds")
    rows = np.asarray(graph.row_indices)
    offsets = np.asarray(graph.offsets)
    visible = np.asarray(graph.visible_values)
    if rows.dtype != np.uint32 or rows.shape != (graph.num_images,):
        raise ColmapMvsError(
            "PMVS visibility row_indices must be uint32 with one row per image"
        )
    if offsets.dtype != np.uint64 or offsets.shape != (graph.num_images + 1,):
        raise ColmapMvsError(
            "PMVS visibility offsets must be uint64 with N+1 entries"
        )
    if visible.dtype != np.uint32 or visible.ndim != 1:
        raise ColmapMvsError("PMVS visibility values must be one-dimensional uint32")
    if visible.size > 250_000_000:
        raise ColmapMvsError(
            "PMVS visibility aggregate reference count is outside bounds"
        )
    if (
        not offsets.size
        or int(offsets[0]) != 0
        or np.any(offsets[1:] < offsets[:-1])
        or int(offsets[-1]) != visible.size
    ):
        raise ColmapMvsError("PMVS visibility offsets are inconsistent")
    _validate_visibility_row_permutation(rows, graph.num_images)
    if graph.value_domain != "raw_colmap_image_id_or_mvs_index":
        raise ColmapMvsError("PMVS visibility value domain is unsupported")
    if visible.size and int(visible.max()) == 0xFFFFFFFF:
        raise ColmapMvsError(
            "PMVS visibility values cannot use COLMAP's invalid image sentinel"
        )
    return rows, offsets, visible


_PMVS_ROW_END = object()


def _pmvs_header_line(stream, limit: int, label: str) -> bytes:
    line = stream.readline(limit + 1)
    if not line:
        raise ColmapMvsError(f"PMVS visibility {label} is missing")
    if len(line) > limit:
        raise ColmapMvsError(f"PMVS visibility {label} exceeds its bound")
    return line.rstrip(b"\r\n")


def _pmvs_numeric_tokens(stream):
    value = 0
    digits = 0
    line_has_token = False
    pending_cr = False

    def flush():
        nonlocal value, digits, line_has_token
        if not digits:
            return None
        result = value
        value = 0
        digits = 0
        line_has_token = True
        return result

    while True:
        chunk = stream.read(64 * 1024)
        if not chunk:
            break
        for byte in chunk:
            if pending_cr:
                pending_cr = False
                if byte == 10:
                    continue
            if 48 <= byte <= 57:
                if digits >= 10:
                    raise ColmapMvsError(
                        "PMVS visibility numeric token exceeds uint32"
                    )
                value = value * 10 + (byte - 48)
                digits += 1
                if value > 0xFFFFFFFF:
                    raise ColmapMvsError(
                        "PMVS visibility numeric token exceeds uint32"
                    )
            elif byte in (9, 11, 12, 32):
                item = flush()
                if item is not None:
                    yield item
            elif byte in (10, 13):
                item = flush()
                if item is not None:
                    yield item
                yield _PMVS_ROW_END
                line_has_token = False
                pending_cr = byte == 13
            else:
                raise ColmapMvsError(
                    "PMVS visibility rows must contain unsigned decimal "
                    "integers"
                )
    item = flush()
    if item is not None:
        yield item
    if line_has_token:
        yield _PMVS_ROW_END


def _scan_pmvs_visibility(
    stream,
    *,
    rows: np.ndarray | None = None,
    offsets: np.ndarray | None = None,
    visible: np.ndarray | None = None,
) -> tuple[int, int]:
    if _pmvs_header_line(stream, 16, "magic") != b"VISDATA":
        raise ColmapMvsError("PMVS visibility magic must be VISDATA")
    count_line = _pmvs_header_line(stream, 16, "image count")
    if not count_line or any(byte < 48 or byte > 57 for byte in count_line):
        raise ColmapMvsError("PMVS visibility image count is invalid")
    num_images = 0
    for byte in count_line:
        num_images = num_images * 10 + (byte - 48)
        if num_images > 10_000_000:
            raise ColmapMvsError(
                "PMVS visibility image count is outside bounds"
            )

    tokens = iter(_pmvs_numeric_tokens(stream))
    total = 0
    if offsets is not None:
        offsets[0] = 0
    for row_number in range(num_images):
        try:
            row_index = next(tokens)
            row_count = next(tokens)
        except StopIteration as exc:
            raise ColmapMvsError(
                f"PMVS visibility row {row_number} is missing"
            ) from exc
        if row_index is _PMVS_ROW_END or row_count is _PMVS_ROW_END:
            raise ColmapMvsError(
                f"PMVS visibility row {row_number} is malformed"
            )
        if total + row_count > 250_000_000:
            raise ColmapMvsError(
                "PMVS visibility aggregate reference count is outside bounds"
            )
        if rows is not None:
            rows[row_number] = row_index
        for index in range(row_count):
            try:
                item = next(tokens)
            except StopIteration as exc:
                raise ColmapMvsError(
                    f"PMVS visibility row {row_number} is truncated"
                ) from exc
            if item is _PMVS_ROW_END:
                raise ColmapMvsError(
                    f"PMVS visibility row {row_number} count is inconsistent"
                )
            if item == 0xFFFFFFFF:
                raise ColmapMvsError(
                    "PMVS visibility values cannot use COLMAP's invalid "
                    "image sentinel"
                )
            if visible is not None:
                visible[total + index] = item
        total += row_count
        if offsets is not None:
            offsets[row_number + 1] = total
        try:
            terminator = next(tokens)
        except StopIteration as exc:
            raise ColmapMvsError(
                f"PMVS visibility row {row_number} is unterminated"
            ) from exc
        if terminator is not _PMVS_ROW_END:
            raise ColmapMvsError(
                f"PMVS visibility row {row_number} count is inconsistent"
            )
    if any(item is not _PMVS_ROW_END for item in tokens):
        raise ColmapMvsError("PMVS visibility has trailing rows")
    return num_images, total


def read_pmvs_visibility(path) -> PmvsVisibilityGraph:
    """Read raw ``vis.dat`` without guessing the ambiguous value domain."""

    source = Path(path)
    try:
        stream = source.open("rb")
    except OSError as exc:
        raise ColmapMvsError(
            f"cannot read PMVS visibility {str(source)!r}: {exc}"
        ) from exc
    with stream:
        num_images, total = _scan_pmvs_visibility(stream)
        rows = np.empty((num_images,), np.uint32)
        offsets = np.empty((num_images + 1,), np.uint64)
        visible = np.empty((total,), np.uint32)
        stream.seek(0)
        repeated = _scan_pmvs_visibility(
            stream,
            rows=rows,
            offsets=offsets,
            visible=visible,
        )
        if repeated != (num_images, total):
            raise ColmapMvsError(
                "PMVS visibility changed while it was being read"
            )
    graph = PmvsVisibilityGraph(
        num_images=num_images,
        row_indices=rows,
        offsets=offsets,
        visible_values=visible,
    )
    _visibility_arrays(graph)
    rows.setflags(write=False)
    offsets.setflags(write=False)
    visible.setflags(write=False)
    return graph


def write_pmvs_visibility(graph: PmvsVisibilityGraph, path) -> None:
    """Write canonical raw ``vis.dat`` with bounded per-row output."""

    rows, offsets, visible = _visibility_arrays(graph)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("VISDATA\n")
        stream.write(f"{graph.num_images}\n")
        for row_number, row_index in enumerate(rows):
            start = int(offsets[row_number])
            stop = int(offsets[row_number + 1])
            stream.write(f"{int(row_index)} {stop - start}")
            for chunk_start in range(start, stop, 4096):
                chunk_stop = min(stop, chunk_start + 4096)
                values = " ".join(
                    str(int(item))
                    for item in visible[chunk_start:chunk_stop]
                )
                stream.write(f" {values}")
            stream.write("\n")


def _legacy_image_refs(
    image_directory: Path,
    projection_directory: Path,
    *,
    profile: Literal["pmvs", "cmp_mvs"],
    projections_required: bool,
) -> tuple[LegacyMvsImageRef, ...]:
    if not image_directory.is_dir():
        raise ColmapMvsError(
            f"{profile} workspace encoded-image directory is missing"
        )
    if projections_required and not projection_directory.is_dir():
        raise ColmapMvsError(
            f"{profile} workspace projection directory is missing"
        )
    pattern = (
        re.compile(r"([0-9]{8})\.jpg")
        if profile == "pmvs"
        else re.compile(r"([0-9]{5})\.jpg")
    )
    base = 0 if profile == "pmvs" else 1
    indexed: list[tuple[int, Path]] = []
    for path in image_directory.iterdir():
        match = pattern.fullmatch(path.name)
        if path.is_file() and match is not None:
            indexed.append((int(match.group(1), 10), path))
    indexed.sort()
    expected = list(range(base, base + len(indexed)))
    if [index for index, _ in indexed] != expected:
        raise ColmapMvsError(
            f"{profile} encoded-image numbering must be contiguous"
        )
    refs = []
    for logical_index, (disk_index, image_path) in enumerate(indexed):
        projection_name = (
            f"{disk_index:08d}.txt"
            if profile == "pmvs"
            else f"{disk_index:05d}_P.txt"
        )
        projection_path = projection_directory / projection_name
        if projections_required and not projection_path.is_file():
            raise ColmapMvsError(
                f"{profile} projection {str(projection_path)!r} is missing"
            )
        refs.append(
            LegacyMvsImageRef(
                index=logical_index,
                image_path=image_path,
                projection_path=(
                    projection_path if projection_path.is_file() else None
                ),
            )
        )
    return tuple(refs)


def open_pmvs_workspace(path) -> LegacyMvsWorkspace:
    """Open a PMVS export without decoding its encoded images."""

    supplied = Path(path).resolve()
    root = (
        supplied / "pmvs"
        if (supplied / "pmvs" / "visualize").is_dir()
        else supplied
    )
    bundle_path = root / "bundle.rd.out"
    uses_bundle = bundle_path.is_file()
    refs = _legacy_image_refs(
        root / "visualize",
        root / "txt",
        profile="pmvs",
        projections_required=not uses_bundle,
    )
    if uses_bundle:
        from sceneio.io import inspect

        declared_images = int(
            inspect(bundle_path, format="bundler").metadata["num_images"]
        )
        if declared_images != len(refs):
            raise ColmapMvsError(
                f"PMVS bundle declares {declared_images} images but "
                f"visualize contains {len(refs)}"
            )
    option_paths = tuple(
        sorted(
            path
            for path in root.iterdir()
            if path.is_file() and path.name.startswith("option-")
        )
    )
    return LegacyMvsWorkspace(
        profile="pmvs",
        model_source="bundler" if uses_bundle else "raw_pmvs",
        root=root,
        images=refs,
        visibility_path=root / "vis.dat",
        bundle_path=bundle_path,
        bundle_list_path=root / "bundle.rd.out.list.txt",
        option_paths=option_paths,
    )


def open_cmp_mvs_workspace(path) -> LegacyMvsWorkspace:
    """Open a CMP-MVS numbered image/projection export lazily."""

    root = Path(path).resolve()
    refs = _legacy_image_refs(
        root,
        root,
        profile="cmp_mvs",
        projections_required=True,
    )
    return LegacyMvsWorkspace(
        profile="cmp_mvs",
        model_source="projection_files",
        root=root,
        images=refs,
    )


def _validate_image_indices(values, num_images: int, label: str) -> None:
    indices = np.asarray(values)
    if indices.size and int(indices.max()) >= num_images:
        raise ColmapMvsError(
            f"{label} contains an MVS sequential image index outside "
            f"0..{num_images - 1}"
        )


def _validate_problem(
    problem: PatchMatchProblem,
    image_names: frozenset[str] | None,
) -> None:
    if not isinstance(problem, PatchMatchProblem):
        raise TypeError("patch-match problems must be PatchMatchProblem values")
    if not problem.reference_image:
        raise ColmapMvsError("patch-match reference image cannot be empty")
    if image_names is not None and problem.reference_image not in image_names:
        raise ColmapMvsError(
            f"patch-match reference {problem.reference_image!r} is not in "
            "the sparse model"
        )
    if problem.source_mode == "all":
        if problem.source_images or problem.max_source_images is not None:
            raise ColmapMvsError(
                "'all' patch-match sources cannot carry names or a limit"
            )
        if image_names is not None and len(image_names) < 2:
            raise ColmapMvsError(
                "'all' patch-match sources must resolve at least one source"
            )
    elif problem.source_mode == "auto":
        if problem.source_images or (
            problem.max_source_images is None
            or isinstance(problem.max_source_images, bool)
            or problem.max_source_images <= 0
        ):
            raise ColmapMvsError(
                "'auto' patch-match sources require a positive limit"
            )
        if image_names is not None and len(image_names) < 2:
            raise ColmapMvsError(
                "'auto' patch-match sources must resolve at least one source"
            )
    elif problem.source_mode == "explicit":
        if not problem.source_images or problem.max_source_images is not None:
            raise ColmapMvsError(
                "explicit patch-match sources require names and no limit"
            )
        if any(not name for name in problem.source_images):
            raise ColmapMvsError("patch-match source names cannot be empty")
        if len(set(problem.source_images)) != len(problem.source_images):
            raise ColmapMvsError(
                "patch-match source names must be unique"
            )
        if problem.reference_image in problem.source_images:
            raise ColmapMvsError(
                "patch-match reference image cannot also be a source"
            )
        if image_names is not None:
            unknown = [
                name for name in problem.source_images if name not in image_names
            ]
            if unknown:
                raise ColmapMvsError(
                    f"patch-match source {unknown[0]!r} is not in the sparse model"
                )
    else:
        raise ColmapMvsError(
            f"unknown patch-match source mode {problem.source_mode!r}"
        )


def read_patch_match_config(
    path,
    *,
    image_names: Iterable[str] | None = None,
) -> tuple[PatchMatchProblem, ...]:
    """Read the COLMAP two-line patch-match problem configuration."""

    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ColmapMvsError(
            f"cannot read patch-match configuration {str(source)!r}: {exc}"
        ) from exc
    active = [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(active) % 2:
        raise ColmapMvsError(
            "patch-match configuration ends without a source line"
        )
    known = frozenset(image_names) if image_names is not None else None
    problems: list[PatchMatchProblem] = []
    for index in range(0, len(active), 2):
        reference = active[index]
        source_tokens = tuple(
            token
            for token in (
                item.strip()
                for item in re.split(r"[,;]", active[index + 1])
            )
            if token
        )
        if source_tokens == ("__all__",):
            problem = PatchMatchProblem(reference, "all")
        elif len(source_tokens) == 2 and source_tokens[0] == "__auto__":
            try:
                limit = int(source_tokens[1], 10)
            except ValueError as exc:
                raise ColmapMvsError(
                    "patch-match __auto__ limit must be an integer"
                ) from exc
            problem = PatchMatchProblem(
                reference,
                "auto",
                max_source_images=limit,
            )
        else:
            if (
                not source_tokens
                or any(token.startswith("__") for token in source_tokens)
            ):
                raise ColmapMvsError(
                    "invalid patch-match source specification"
                )
            problem = PatchMatchProblem(
                reference,
                "explicit",
                source_images=source_tokens,
            )
        _validate_problem(problem, known)
        problems.append(problem)
    return tuple(problems)


def write_patch_match_config(
    problems: Iterable[PatchMatchProblem],
    path,
    *,
    image_names: Iterable[str] | None = None,
) -> None:
    """Write canonical COLMAP patch-match configuration text."""

    values = tuple(problems)
    known = frozenset(image_names) if image_names is not None else None
    lines: list[str] = []
    for problem in values:
        _validate_problem(problem, known)
        lines.append(problem.reference_image)
        if problem.source_mode == "all":
            lines.append("__all__")
        elif problem.source_mode == "auto":
            lines.append(f"__auto__, {problem.max_source_images}")
        else:
            lines.append(", ".join(problem.source_images))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(f"{line}\n" for line in lines),
        encoding="utf-8",
        newline="\n",
    )


def read_fusion_config(
    path,
    *,
    image_names: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Read ordered image names from ``fusion.cfg``."""

    source = Path(path)
    try:
        names = tuple(source.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError) as exc:
        raise ColmapMvsError(
            f"cannot read fusion configuration {str(source)!r}: {exc}"
        ) from exc
    if any(not name for name in names):
        raise ColmapMvsError("fusion configuration contains an empty image name")
    if image_names is not None:
        known = frozenset(image_names)
        unknown = [name for name in names if name not in known]
        if unknown:
            raise ColmapMvsError(
                f"fusion image {unknown[0]!r} is not in the sparse model"
            )
    return names


def write_fusion_config(
    image_names: Iterable[str],
    path,
    *,
    known_image_names: Iterable[str] | None = None,
) -> None:
    """Write ordered image names to canonical ``fusion.cfg`` text."""

    names = tuple(image_names)
    if any(not isinstance(name, str) or not name for name in names):
        raise ColmapMvsError("fusion image names must be non-empty strings")
    if known_image_names is not None:
        known = frozenset(known_image_names)
        unknown = [name for name in names if name not in known]
        if unknown:
            raise ColmapMvsError(
                f"fusion image {unknown[0]!r} is not in the sparse model"
            )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(f"{name}\n" for name in names),
        encoding="utf-8",
        newline="\n",
    )


def _sparse_model(root: Path, sparse_folder: str) -> tuple[Path, str]:
    sparse_root = root / sparse_folder

    def format_at(path: Path) -> str | None:
        binary = all(
            (path / name).is_file()
            for name in ("cameras.bin", "images.bin", "points3D.bin")
        )
        text = all(
            (path / name).is_file()
            for name in ("cameras.txt", "images.txt", "points3D.txt")
        )
        if binary:
            return "colmap_sparse"
        if text:
            return "colmap_sparse_txt"
        return None

    direct = format_at(sparse_root)
    if direct is not None:
        return sparse_root, direct
    candidates = [
        (path, selected)
        for path in sorted(sparse_root.iterdir())
        if path.is_dir() and (selected := format_at(path)) is not None
    ] if sparse_root.is_dir() else []
    if len(candidates) != 1:
        raise ColmapMvsError(
            f"{str(sparse_root)!r} must contain one complete COLMAP sparse model"
        )
    return candidates[0]


def _mvs_image_identity(
    reconstruction,
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    sparse_ids = tuple(
        int(value) for value in np.asarray(reconstruction.image_ids)
    )
    sparse_names = tuple(reconstruction.image_names)
    if (
        len(sparse_ids) != len(sparse_names)
        or len(set(sparse_ids)) != len(sparse_ids)
        or len(set(sparse_names)) != len(sparse_names)
    ):
        raise ColmapMvsError("sparse model image identity is inconsistent")
    if not reconstruction.has_rig_frame_model:
        return sparse_ids, sparse_names

    offsets = np.asarray(reconstruction.frame_data_offsets)
    sensor_types = np.asarray(reconstruction.frame_sensor_types)
    data_ids = np.asarray(reconstruction.frame_data_ids)
    if (
        offsets.dtype != np.uint64
        or sensor_types.dtype != np.int32
        or data_ids.dtype != np.uint64
        or offsets.shape != (reconstruction.num_frames + 1,)
        or sensor_types.shape != data_ids.shape
        or int(offsets[0]) != 0
        or int(offsets[-1]) != data_ids.size
        or np.any(offsets[1:] < offsets[:-1])
    ):
        raise ColmapMvsError("modern sparse frame data is inconsistent")

    names_by_id = dict(zip(sparse_ids, sparse_names, strict=True))
    ordered_ids: list[int] = []
    for frame in range(reconstruction.num_frames):
        start = int(offsets[frame])
        stop = int(offsets[frame + 1])
        for data in range(start, stop):
            if int(sensor_types[data]) != 0:
                continue
            image_id = int(data_ids[data])
            if image_id not in names_by_id:
                raise ColmapMvsError(
                    f"modern sparse frame references missing image {image_id}"
                )
            ordered_ids.append(image_id)
    if (
        len(ordered_ids) != len(sparse_ids)
        or len(set(ordered_ids)) != len(ordered_ids)
        or set(ordered_ids) != set(sparse_ids)
    ):
        raise ColmapMvsError(
            "modern sparse frame order must contain every image exactly once"
        )
    return (
        tuple(ordered_ids),
        tuple(names_by_id[image_id] for image_id in ordered_ids),
    )


def open_workspace(
    path,
    *,
    sparse_folder: str = "sparse",
    images_folder: str = "images",
    stereo_folder: str = "stereo",
) -> ColmapMvsWorkspace:
    """Open a COLMAP dense workspace without decoding dense payloads or media."""

    from sceneio.io import read

    root = Path(path).resolve()
    if not root.is_dir():
        raise ColmapMvsError(f"workspace {str(root)!r} is not a directory")
    sparse_path, sparse_format = _sparse_model(root, sparse_folder)
    images_path = root / images_folder
    stereo_path = root / stereo_folder
    if not images_path.is_dir():
        raise ColmapMvsError(
            f"workspace image directory {str(images_path)!r} is missing"
        )
    if not stereo_path.is_dir():
        raise ColmapMvsError(
            f"workspace stereo directory {str(stereo_path)!r} is missing"
        )
    reconstruction = read(sparse_path, format=sparse_format)
    image_ids, image_names = _mvs_image_identity(reconstruction)
    _validate_unique_image_paths(image_names)

    patch_path = stereo_path / "patch-match.cfg"
    fusion_path = stereo_path / "fusion.cfg"
    problems = (
        read_patch_match_config(patch_path, image_names=image_names)
        if patch_path.is_file()
        else ()
    )
    fusion_images = (
        read_fusion_config(fusion_path, image_names=image_names)
        if fusion_path.is_file()
        else ()
    )
    return ColmapMvsWorkspace(
        root=root,
        sparse_path=sparse_path,
        sparse_format=sparse_format,
        images_path=images_path,
        stereo_path=stereo_path,
        reconstruction=reconstruction,
        image_ids=image_ids,
        image_names=image_names,
        patch_match_problems=problems,
        fusion_images=fusion_images,
        has_patch_match_config=patch_path.is_file(),
        has_fusion_config=fusion_path.is_file(),
    )


def _fused_point_count(path: Path) -> int:
    from sceneio.io import inspect

    result = inspect(path, format="ply")
    if result.count is None:
        raise ColmapMvsError("fused.ply inspection did not report a point count")
    return result.count


def validate_workspace(
    workspace: ColmapMvsWorkspace,
    *,
    deep: bool = False,
) -> WorkspaceValidation:
    """Validate map dimensions and cross-file index/count domains.

    ``deep=False`` performs nonmaterializing structural scans (matrix headers
    and complete graph/visibility wire validation). ``deep=True`` additionally
    decodes consistency and visibility lists to validate every MVS image
    index.
    """

    from sceneio.io import inspect

    if not isinstance(workspace, ColmapMvsWorkspace):
        raise TypeError("workspace must be a ColmapMvsWorkspace")
    map_sets = workspace.map_sets()
    depth_count = normal_count = consistency_count = 0
    for maps in map_sets:
        present = (
            maps.depth_path.is_file(),
            maps.normal_path.is_file(),
            maps.consistency_path.is_file(),
        )
        if present[0] != present[1]:
            raise ColmapMvsError(
                f"{maps.image_name!r} {maps.input_type} depth/normal maps "
                "must be present together"
            )
        shapes: list[tuple[int, ...]] = []
        if present[0]:
            depth_count += 1
            depth_info = inspect(
                maps.depth_path,
                format="colmap_mvs_depth",
            )
            shapes.append(depth_info.shape)
        if present[1]:
            normal_count += 1
            normal_info = inspect(
                maps.normal_path,
                format="colmap_mvs_normal",
            )
            shapes.append(normal_info.shape[:2])
        if present[2]:
            consistency_count += 1
            consistency_info = inspect(
                maps.consistency_path,
                format="colmap_mvs_consistency",
            )
            shapes.append(consistency_info.shape)
            if deep:
                workspace.read_consistency(
                    maps.image_index,
                    maps.input_type,
                )
        if shapes and any(shape != shapes[0] for shape in shapes[1:]):
            raise ColmapMvsError(
                f"{maps.image_name!r} {maps.input_type} dense map "
                "dimensions disagree"
            )

    fused_count = (
        _fused_point_count(workspace.fused_path)
        if workspace.fused_path.is_file()
        else None
    )
    visibility_count = None
    if workspace.visibility_path.is_file():
        visibility_info = inspect(
            workspace.visibility_path,
            format="colmap_fused_visibility",
        )
        visibility_count = visibility_info.count
        if fused_count is not None and visibility_count != fused_count:
            raise ColmapMvsError(
                "fused visibility point count "
                f"{visibility_count} does not match fused.ply count "
                f"{fused_count}"
            )
        if deep:
            workspace.read_visibility()

    return WorkspaceValidation(
        num_images=workspace.num_images,
        num_map_sets=sum(
            maps.has_depth or maps.has_normal or maps.has_consistency
            for maps in map_sets
        ),
        num_depth_maps=depth_count,
        num_normal_maps=normal_count,
        num_consistency_graphs=consistency_count,
        fused_point_count=fused_count,
        visibility_point_count=visibility_count,
        deep=deep,
    )


def inspect_workspace(path, *, deep: bool = False, **folders) -> WorkspaceInspection:
    """Return a lazy workspace inventory plus validation summary."""

    workspace = open_workspace(path, **folders)
    validation = workspace.validate(deep=deep)
    map_sets = tuple(
        maps
        for maps in workspace.map_sets()
        if maps.has_depth or maps.has_normal or maps.has_consistency
    )
    return WorkspaceInspection(
        root=workspace.root,
        sparse_path=workspace.sparse_path,
        sparse_format=workspace.sparse_format,
        num_images=workspace.num_images,
        image_names=workspace.image_names,
        patch_match_problem_count=len(workspace.patch_match_problems),
        fusion_image_count=len(workspace.fusion_images),
        map_sets=map_sets,
        fused_path=workspace.fused_path if workspace.fused_path.is_file() else None,
        visibility_path=(
            workspace.visibility_path
            if workspace.visibility_path.is_file()
            else None
        ),
        validation=validation,
    )


__all__ = [
    "ColmapMvsError",
    "ColmapMvsWorkspace",
    "DenseMapSet",
    "InputType",
    "LegacyMvsImageRef",
    "LegacyMvsWorkspace",
    "PatchMatchProblem",
    "PmvsVisibilityGraph",
    "ProjectionMatrix",
    "SourceMode",
    "WorkspaceInspection",
    "WorkspaceValidation",
    "inspect_workspace",
    "open_cmp_mvs_workspace",
    "open_pmvs_workspace",
    "open_workspace",
    "read_fusion_config",
    "read_image_name_list",
    "read_patch_match_config",
    "read_pmvs_visibility",
    "read_projection_matrix",
    "validate_workspace",
    "write_fusion_config",
    "write_image_name_list",
    "write_patch_match_config",
    "write_pmvs_visibility",
    "write_projection_matrix",
]
