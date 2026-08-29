"""Focused benchmark for the versioned dense-label carrier adapters."""

from __future__ import annotations

import gc
import io
import json
import statistics
import time
import tracemalloc
import zipfile
from pathlib import Path

import numpy as np

import sceneio
from bench.io_bench.memory_protocol import (
    MemoryCase,
    MemoryOperation,
    measure_memory_cases,
)
from sceneio import _core
from sceneio.data import LabelTaxonomy, SemanticMap


def label_map_fixture(side: int) -> SemanticMap:
    """Build a deterministic semantic raster with a small explicit taxonomy."""

    if isinstance(side, bool) or not isinstance(side, int) or side < 1:
        raise ValueError("side must be a positive integer")
    class_ids = np.arange(side * side, dtype=np.int32).reshape(side, side)
    np.remainder(class_ids, 23, out=class_ids)
    taxonomy = LabelTaxonomy(
        np.arange(23, dtype=np.int32),
        tuple(f"class-{index}" for index in range(23)),
        "sceneio.generated.label-benchmark",
        "v1",
        np.column_stack(
            (
                np.arange(23, dtype=np.uint8),
                np.arange(23, dtype=np.uint8) * np.uint8(7),
                np.arange(23, dtype=np.uint8) * np.uint8(13),
            )
        ),
        np.arange(23) % 3 != 0,
    )
    return SemanticMap(class_ids, -1, taxonomy=taxonomy)


def _oracle_arrays(value: SemanticMap) -> dict[str, np.ndarray]:
    taxonomy = value.taxonomy
    assert taxonomy is not None
    encoded = [name.encode("utf-8") for name in taxonomy.names]
    lengths = np.fromiter((len(name) for name in encoded), dtype=np.int64)
    offsets = np.empty(len(encoded) + 1, dtype=np.int64)
    offsets[0] = 0
    np.cumsum(lengths, out=offsets[1:])
    arrays = {
        "__sceneio_label_map_v1__": np.array(1, np.uint8),
        "semantic_ids": value.class_ids,
        "semantic_void_id": np.array(value.void_id, np.int32),
        "taxonomy_semantic_ids": taxonomy.semantic_ids,
        "taxonomy_names_utf8": np.frombuffer(b"".join(encoded), np.uint8).copy(),
        "taxonomy_name_offsets": offsets,
        "taxonomy_identity_utf8": np.frombuffer(
            taxonomy.identity.encode("utf-8"), np.uint8
        ).copy(),
        "taxonomy_version_utf8": np.frombuffer(
            taxonomy.version.encode("utf-8"), np.uint8
        ).copy(),
    }
    if taxonomy.display_colors is not None:
        arrays["taxonomy_display_colors"] = taxonomy.display_colors
    if taxonomy.is_thing is not None:
        arrays["taxonomy_is_thing"] = taxonomy.is_thing
    if value.valid is not None:
        arrays["valid"] = value.valid
    return arrays


def _measure(operation, runs: int) -> tuple[float, int]:
    elapsed_samples: list[float] = []
    peak = 0
    for _ in range(runs):
        gc.collect()
        tracemalloc.start()
        start = time.perf_counter()
        value = operation()
        elapsed_samples.append(time.perf_counter() - start)
        _, sample_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak = max(peak, sample_peak)
        del value
    return statistics.median(elapsed_samples), peak


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _npz_oracle_write(path: Path, arrays: dict[str, np.ndarray]) -> None:
    np.savez(path, **arrays)


def _npz_oracle_read(path: Path) -> np.ndarray:
    with np.load(path, allow_pickle=False) as archive:
        return np.array(archive["semantic_ids"], copy=True, order="C")


def _npz_oracle_arrays(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        return {name: np.array(archive[name], copy=True) for name in archive.files}


def _npy_header(stream) -> tuple[tuple[int, ...], np.dtype]:
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, _fortran, dtype = np.lib.format.read_array_header_1_0(stream)
    else:
        shape, _fortran, dtype = np.lib.format.read_array_header_2_0(stream)
    return tuple(shape), np.dtype(dtype)


def _npz_oracle_inspect(path: Path) -> tuple[tuple[int, ...], str]:
    with zipfile.ZipFile(path) as archive:
        with archive.open("semantic_ids.npy") as stream:
            shape, dtype = _npy_header(stream)
        for name, expected in (
            ("__sceneio_label_map_v1__.npy", np.uint8),
            ("semantic_void_id.npy", np.int32),
        ):
            payload = archive.read(name)
            array = np.load(io.BytesIO(payload), allow_pickle=False)
            if array.shape != () or array.dtype != np.dtype(expected):
                raise AssertionError(f"oracle metadata {name!r} is malformed")
    return shape, dtype.name


def _require_zarr():
    try:
        import zarr
    except ImportError:
        raise RuntimeError(
            "Zarr benchmark requested; install the sceneio[zarr] extra"
        ) from None
    return zarr


def _zarr_oracle_write(
    path: Path,
    arrays: dict[str, np.ndarray],
    *,
    zarr_format: int,
    chunks: tuple[int, int],
) -> None:
    zarr = _require_zarr()
    group = zarr.open_group(path, mode="w", zarr_format=zarr_format)
    for name, array in arrays.items():
        options = {"data": array}
        if name == "semantic_ids":
            options["chunks"] = chunks
        group.create_array(name, **options)


def _zarr_oracle_read(path: Path) -> np.ndarray:
    group = _require_zarr().open_group(path, mode="r", use_consolidated=None)
    return np.asarray(group["semantic_ids"][:])


def _zarr_oracle_arrays(path: Path) -> dict[str, np.ndarray]:
    group = _require_zarr().open_group(path, mode="r", use_consolidated=None)
    return {
        name: np.asarray(array[...])
        for name, array in group.arrays()
    }


def _zarr_oracle_inspect(path: Path) -> tuple[tuple[int, ...], str]:
    group = _require_zarr().open_group(path, mode="r", use_consolidated=None)
    array = group["semantic_ids"]
    return tuple(array.shape), np.dtype(array.dtype).name


def _require_tifffile():
    try:
        import tifffile
    except ImportError:
        raise RuntimeError(
            "TIFF benchmark requested; install the sceneio[tiff] extra"
        ) from None
    return tifffile


def _tiff_description(value: SemanticMap) -> str:
    taxonomy = value.taxonomy
    assert taxonomy is not None
    taxonomy_document: dict[str, object] = {
        "semantic_ids": [int(item) for item in taxonomy.semantic_ids],
        "names": list(taxonomy.names),
        "identity": taxonomy.identity,
        "version": taxonomy.version,
    }
    if taxonomy.display_colors is not None:
        taxonomy_document["display_colors"] = taxonomy.display_colors.tolist()
    if taxonomy.is_thing is not None:
        taxonomy_document["is_thing"] = taxonomy.is_thing.tolist()
    return json.dumps(
        {
            "schema": "sceneio.label_map/1",
            "kind": "semantic",
            "roles": ["semantic_ids"],
            "role": "semantic_ids",
            "shape": list(value.shape),
            "dtypes": {"semantic_ids": "int32"},
            "void_id": int(value.void_id),
            "taxonomy": taxonomy_document,
            "table_instance_ids": None,
            "table_semantic_ids": None,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _tiff_oracle_write(path: Path, value: SemanticMap) -> None:
    _require_tifffile().imwrite(
        path,
        value.class_ids,
        photometric="minisblack",
        metadata=None,
        description=_tiff_description(value),
    )


def _tiff_oracle_read(path: Path) -> np.ndarray:
    with _require_tifffile().TiffFile(path) as tiff:
        return np.array(tiff.pages[0].asarray(), copy=True, order="C")


def _tiff_oracle_arrays(path: Path) -> dict[str, np.ndarray]:
    with _require_tifffile().TiffFile(path) as tiff:
        page = tiff.pages[0]
        document = json.loads(page.description)
        pixels = np.array(page.asarray(), copy=True, order="C")
    taxonomy = document["taxonomy"]
    value = SemanticMap(
        pixels,
        int(document["void_id"]),
        taxonomy=LabelTaxonomy(
            np.asarray(taxonomy["semantic_ids"], dtype=np.int32),
            tuple(taxonomy["names"]),
            taxonomy["identity"],
            taxonomy["version"],
            None
            if "display_colors" not in taxonomy
            else np.asarray(taxonomy["display_colors"], dtype=np.uint8),
            None
            if "is_thing" not in taxonomy
            else np.asarray(taxonomy["is_thing"], dtype=bool),
        ),
    )
    return _oracle_arrays(value)


def _tiff_oracle_inspect(path: Path) -> tuple[tuple[int, ...], str]:
    with _require_tifffile().TiffFile(path) as tiff:
        page = tiff.pages[0]
        return tuple(page.shape), np.dtype(page.dtype).name


def _assert_sceneio_read(value: object, expected: SemanticMap) -> None:
    if not isinstance(value, SemanticMap):
        raise AssertionError("typed label read did not return SemanticMap")
    np.testing.assert_array_equal(value.class_ids, expected.class_ids)
    if value.valid is not expected.valid:
        if value.valid is None or expected.valid is None:
            raise AssertionError("typed label read changed validity presence")
        np.testing.assert_array_equal(value.valid, expected.valid)
    if value.void_id != expected.void_id:
        raise AssertionError("typed label read changed the void id")
    actual_taxonomy = value.taxonomy
    expected_taxonomy = expected.taxonomy
    if actual_taxonomy is None or expected_taxonomy is None:
        if actual_taxonomy is not expected_taxonomy:
            raise AssertionError("typed label read changed taxonomy presence")
        return
    np.testing.assert_array_equal(
        actual_taxonomy.semantic_ids, expected_taxonomy.semantic_ids
    )
    if (
        actual_taxonomy.names != expected_taxonomy.names
        or actual_taxonomy.identity != expected_taxonomy.identity
        or actual_taxonomy.version != expected_taxonomy.version
    ):
        raise AssertionError("typed label read changed taxonomy text")
    np.testing.assert_array_equal(
        actual_taxonomy.display_colors, expected_taxonomy.display_colors
    )
    np.testing.assert_array_equal(
        actual_taxonomy.is_thing, expected_taxonomy.is_thing
    )


def _assert_array_mapping(
    actual: dict[str, np.ndarray], expected: dict[str, np.ndarray]
) -> None:
    if set(actual) != set(expected):
        raise AssertionError("oracle carrier array names differ from the schema")
    for name, expected_array in expected.items():
        np.testing.assert_array_equal(actual[name], expected_array)


def _result(
    *,
    carrier: str,
    value: SemanticMap,
    path: Path,
    oracle_path: Path,
    runs: int,
    write,
    oracle_write,
    oracle_read,
    oracle_arrays,
    oracle_inspect,
    rss_samples: int,
    adapter_baseline_path: Path | None = None,
    adapter_baseline_write=None,
) -> dict[str, object]:
    write()
    oracle_write()
    expected_arrays = _oracle_arrays(value)
    _assert_array_mapping(oracle_arrays(path), expected_arrays)
    _assert_array_mapping(oracle_arrays(oracle_path), expected_arrays)
    if (adapter_baseline_path is None) is not (adapter_baseline_write is None):
        raise AssertionError("adapter baseline path and writer must be paired")
    if adapter_baseline_write is not None:
        adapter_baseline_write()
        _assert_array_mapping(
            oracle_arrays(adapter_baseline_path), expected_arrays
        )
    _assert_sceneio_read(sceneio.read_label_map(path), value)
    _assert_sceneio_read(sceneio.read_label_map(oracle_path), value)
    np.testing.assert_array_equal(oracle_read(path), value.class_ids)
    inspection = sceneio.inspect_label_map(path)
    if inspection.shape != value.shape or inspection.dtype != "int32":
        raise AssertionError("typed label inspection changed shape or dtype")
    if oracle_inspect(path) != (value.shape, "int32"):
        raise AssertionError("oracle inspection changed shape or dtype")

    sceneio_write_s, sceneio_write_peak = _measure(write, runs)
    oracle_write_s, oracle_write_peak = _measure(oracle_write, runs)
    sceneio_read_s, sceneio_read_peak = _measure(
        lambda: sceneio.read_label_map(path), runs
    )
    oracle_read_s, oracle_read_peak = _measure(lambda: oracle_read(path), runs)
    sceneio_inspect_s, sceneio_inspect_peak = _measure(
        lambda: sceneio.inspect_label_map(path), runs
    )
    oracle_inspect_s, oracle_inspect_peak = _measure(
        lambda: oracle_inspect(path), runs
    )
    logical_bytes = value.class_ids.nbytes

    rss_metrics: dict[str, float | None] = {}
    if rss_samples:
        format_id = carrier.split("-")[0]
        memory_samples = measure_memory_cases(
            (
                MemoryCase(
                    f"{carrier}-typed-read",
                    logical_bytes,
                    MemoryOperation(
                        "sceneio_read_label_map",
                        {"path": str(path), "format": format_id},
                    ),
                ),
                MemoryCase(
                    f"{carrier}-typed-inspect",
                    logical_bytes,
                    MemoryOperation(
                        "sceneio_inspect_label_map",
                        {"path": str(path), "format": format_id},
                    ),
                ),
            ),
            samples=rss_samples,
        )
        by_label: dict[str, list[int]] = {}
        for sample in memory_samples:
            if sample.status == "available" and sample.delta_rss_bytes is not None:
                by_label.setdefault(sample.case_label, []).append(
                    sample.delta_rss_bytes
                )
        for operation in ("read", "inspect"):
            values = by_label.get(f"{carrier}-typed-{operation}", [])
            rss_metrics[f"sceneio_{operation}_fresh_rss_mib"] = (
                statistics.median(values) / (1024 * 1024) if values else None
            )

    def metrics(prefix: str, elapsed: float, peak: int) -> dict[str, float]:
        return {
            f"{prefix}_ms": elapsed * 1000,
            f"{prefix}_mbps": logical_bytes / elapsed / 1_000_000,
            f"{prefix}_traced_peak_mib": peak / (1024 * 1024),
        }

    adapter_metrics = {}
    if adapter_baseline_write is not None:
        baseline_s, baseline_peak = _measure(adapter_baseline_write, runs)
        adapter_metrics = metrics(
            "adapter_baseline_write", baseline_s, baseline_peak
        )

    return {
        "carrier": carrier,
        "schema": sceneio.LABEL_MAP_SCHEMA,
        "side": value.shape[0],
        "runs": runs,
        "logical_mib": logical_bytes / (1024 * 1024),
        "sceneio_file_mib": _path_size(path) / (1024 * 1024),
        "oracle_file_mib": _path_size(oracle_path) / (1024 * 1024),
        **metrics("sceneio_write", sceneio_write_s, sceneio_write_peak),
        **metrics("oracle_write", oracle_write_s, oracle_write_peak),
        **metrics("sceneio_read", sceneio_read_s, sceneio_read_peak),
        **metrics("oracle_read", oracle_read_s, oracle_read_peak),
        **metrics("sceneio_inspect", sceneio_inspect_s, sceneio_inspect_peak),
        **metrics("oracle_inspect", oracle_inspect_s, oracle_inspect_peak),
        **adapter_metrics,
        **rss_metrics,
    }


def run_benchmark(
    root: str | Path,
    *,
    side: int = 4096,
    runs: int = 3,
    carriers: tuple[str, ...] = ("npz", "zarr", "tiff"),
    zarr_format: int = 3,
    chunk_side: int = 1024,
    rss_samples: int = 3,
) -> list[dict[str, object]]:
    """Measure typed writes, reads, and metadata-only inspection."""

    if runs < 1:
        raise ValueError("runs must be positive")
    if chunk_side < 1:
        raise ValueError("chunk_side must be positive")
    if isinstance(rss_samples, bool) or not isinstance(rss_samples, int):
        raise TypeError("rss_samples must be a non-negative integer")
    if rss_samples < 0:
        raise ValueError("rss_samples must be a non-negative integer")
    if not carriers or any(item not in {"npz", "tiff", "zarr"} for item in carriers):
        raise ValueError("carriers must contain npz, tiff, and/or zarr")
    value = label_map_fixture(side)
    arrays = _oracle_arrays(value)
    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    if "npz" in carriers:
        path = destination / "sceneio-labels.npz"
        oracle_path = destination / "oracle-labels.npz"
        results.append(
            _result(
                carrier="npz-stored",
                value=value,
                path=path,
                oracle_path=oracle_path,
                runs=runs,
                write=lambda: sceneio.write_label_map(value, path),
                oracle_write=lambda: _npz_oracle_write(oracle_path, arrays),
                oracle_read=_npz_oracle_read,
                oracle_arrays=_npz_oracle_arrays,
                oracle_inspect=_npz_oracle_inspect,
                rss_samples=rss_samples,
            )
        )
    if "zarr" in carriers:
        chunks = (min(side, chunk_side), min(side, chunk_side))
        path = destination / "sceneio-labels.zarr"
        oracle_path = destination / "oracle-labels.zarr"
        adapter_baseline_path = destination / "tensordict-labels.zarr"
        results.append(
            _result(
                carrier=f"zarr-v{zarr_format}",
                value=value,
                path=path,
                oracle_path=oracle_path,
                runs=runs,
                write=lambda: sceneio.write_label_map(
                    value,
                    path,
                    zarr_format=zarr_format,
                    chunks=chunks,
                ),
                oracle_write=lambda: _zarr_oracle_write(
                    oracle_path,
                    arrays,
                    zarr_format=zarr_format,
                    chunks=chunks,
                ),
                oracle_read=_zarr_oracle_read,
                oracle_arrays=_zarr_oracle_arrays,
                oracle_inspect=_zarr_oracle_inspect,
                rss_samples=rss_samples,
                adapter_baseline_path=adapter_baseline_path,
                adapter_baseline_write=lambda: sceneio.write_zarr(
                    _core.tensor_dict(arrays),
                    adapter_baseline_path,
                    zarr_format=zarr_format,
                    chunks={"semantic_ids": chunks},
                ),
            )
        )
    if "tiff" in carriers:
        path = destination / "sceneio-labels.tiff"
        oracle_path = destination / "oracle-labels.tiff"
        results.append(
            _result(
                carrier="tiff",
                value=value,
                path=path,
                oracle_path=oracle_path,
                runs=runs,
                write=lambda: sceneio.write_label_map(value, path),
                oracle_write=lambda: _tiff_oracle_write(oracle_path, value),
                oracle_read=_tiff_oracle_read,
                oracle_arrays=_tiff_oracle_arrays,
                oracle_inspect=_tiff_oracle_inspect,
                rss_samples=rss_samples,
            )
        )
    return results


__all__ = ["label_map_fixture", "run_benchmark"]
