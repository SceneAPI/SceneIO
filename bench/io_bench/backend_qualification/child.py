"""Isolated installed-wheel worker for JPEG backend qualification.

The controller copies this file to a temporary directory and launches it with
the backend environment's absolute Python executable and ``-I``.  Keep this
module self-contained: it must not import SceneIO benchmark modules from the
checkout.
"""

from __future__ import annotations

import base64
import gc
import hashlib
import importlib.metadata
import io
import json
import math
import mmap
import os
import platform
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
WORKER_ACTIONS = frozenset(
    {
        "probe",
        "prepare_corpus",
        "session",
        "startup",
        "determinism",
        "memory",
    }
)
_START_NS = time.perf_counter_ns()
_RUNTIME: dict[str, Any] | None = None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _installed_package_members(
    package_root: Path, core_path: Path
) -> dict[str, str]:
    members: dict[str, str] = {}
    resolved_core = core_path.resolve()
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or path.resolve() == resolved_core:
            continue
        relative = path.relative_to(package_root)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        members[f"sceneio/{relative.as_posix()}"] = _sha256_file(path)
    return members


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _runtime() -> dict[str, Any]:
    global _RUNTIME
    if _RUNTIME is None:
        import_start = time.perf_counter_ns()
        import sceneio
        from sceneio import _core

        sceneio_import_ns = time.perf_counter_ns() - import_start
        import numpy as np
        from PIL import Image
        from PIL import __version__ as pillow_version

        _RUNTIME = {
            "np": np,
            "sceneio": sceneio,
            "core": _core,
            "Image": Image,
            "pillow_version": pillow_version,
            "import_ns": sceneio_import_ns,
        }
    return _RUNTIME


def _backend_marker(core: Any) -> str | None:
    marker = getattr(core, "_jpeg_backend_id", None)
    return None if marker is None else str(marker())


def _verify_marker(expected: str) -> dict[str, Any]:
    runtime = _runtime()
    marker = _backend_marker(runtime["core"])
    if marker != expected:
        raise RuntimeError(
            f"installed JPEG backend marker is {marker!r}, expected {expected!r}"
        )
    return runtime


def _fixture_pixels(
    fixture_id: str,
    height: int,
    width: int,
    seed: int,
) -> Any:
    runtime = _runtime()
    np = runtime["np"]
    x = np.arange(width, dtype=np.uint32)[None, :]
    y = np.arange(height, dtype=np.uint32)[:, None]
    pixels = np.empty((height, width, 3), dtype=np.uint8)
    if fixture_id == "chroma_odd":
        tile = ((x // 8) + (y // 8) + seed) & 3
        pixels[..., 0] = ((tile == 0) * 255 + (tile == 3) * 32).astype(
            np.uint8
        )
        pixels[..., 1] = ((tile == 1) * 255 + (tile == 3) * 64).astype(
            np.uint8
        )
        pixels[..., 2] = ((tile == 2) * 255 + (tile == 3) * 128).astype(
            np.uint8
        )
    elif fixture_id == "texture_4k":
        pixels[..., 0] = (
            x * 73 + y * 151 + ((x ^ (y * 17)) * 19) + seed
        ).astype(np.uint8)
        pixels[..., 1] = (
            x * 199 + y * 29 + (((x * 7) ^ y) * 43) + seed * 3
        ).astype(np.uint8)
        pixels[..., 2] = (
            x * 11 + y * 239 + (((x + y) ^ (x * 13)) * 61) + seed * 5
        ).astype(np.uint8)
    else:
        low_noise = ((x * 17 + y * 31 + seed * 13) >> 3) & 15
        pixels[..., 0] = (
            x * 255 // max(1, width - 1) + low_noise
        ).astype(np.uint8)
        pixels[..., 1] = (
            y * 255 // max(1, height - 1) + low_noise * 3
        ).astype(np.uint8)
        pixels[..., 2] = (
            (x + y) * 255 // max(1, width + height - 2)
            + low_noise * 5
        ).astype(np.uint8)
    return pixels


def _jpeg_header(data: bytes) -> dict[str, Any]:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG stream")
    offset = 2
    sof: dict[str, Any] | None = None
    restart_interval = 0
    adobe_transform: int | None = None
    scan_offset = len(data)
    while offset < len(data):
        if data[offset] != 0xFF:
            raise ValueError("invalid JPEG marker alignment")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker == 0xD9:
            break
        if marker in {0x01, *range(0xD0, 0xD8)}:
            continue
        if offset + 2 > len(data):
            raise ValueError("truncated JPEG segment length")
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > len(data):
            raise ValueError("invalid JPEG segment length")
        payload = data[offset + 2 : offset + length]
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if len(payload) < 6:
                raise ValueError("truncated JPEG SOF")
            components = payload[5]
            if len(payload) != 6 + 3 * components:
                raise ValueError("invalid JPEG SOF component table")
            sampling = []
            for index in range(components):
                base = 6 + index * 3
                value = payload[base + 1]
                sampling.append(
                    {
                        "id": payload[base],
                        "h": value >> 4,
                        "v": value & 15,
                    }
                )
            sof = {
                "marker": f"0x{marker:02x}",
                "progressive": marker == 0xC2,
                "precision": payload[0],
                "height": int.from_bytes(payload[1:3], "big"),
                "width": int.from_bytes(payload[3:5], "big"),
                "components": components,
                "sampling": sampling,
            }
        elif marker == 0xDD:
            if len(payload) != 2:
                raise ValueError("invalid JPEG DRI")
            restart_interval = int.from_bytes(payload, "big")
        elif marker == 0xEE and payload.startswith(b"Adobe"):
            if len(payload) < 12:
                raise ValueError("truncated JPEG Adobe marker")
            adobe_transform = payload[11]
        elif marker == 0xDA:
            scan_offset = offset + length
            break
        offset += length
    if sof is None:
        raise ValueError("JPEG has no SOF marker")
    restart_markers = sum(
        data[scan_offset:].count(bytes((0xFF, value)))
        for value in range(0xD0, 0xD8)
    )
    return {
        **sof,
        "restart_interval": restart_interval,
        "restart_markers": restart_markers,
        "adobe_transform": adobe_transform,
    }


def _assert_header(
    header: dict[str, Any],
    *,
    profile: dict[str, Any],
    fixture: dict[str, Any] | None,
) -> None:
    if fixture is not None and (
        header["height"] != fixture["height"]
        or header["width"] != fixture["width"]
    ):
        raise ValueError("JPEG dimensions differ from the declared fixture")
    if header["progressive"] != profile["progressive"]:
        raise ValueError("JPEG progressive mode differs from the profile")
    kind = profile["kind"]
    sampling = [(item["h"], item["v"]) for item in header["sampling"]]
    if kind == "grayscale":
        if header["components"] != 1 or sampling != [(1, 1)]:
            raise ValueError("grayscale JPEG component layout is incorrect")
    elif kind in {"rgb", "ycck"}:
        expected = (
            [(2, 2), (1, 1), (1, 1)]
            if profile["subsampling"] == "420"
            else [(1, 1), (1, 1), (1, 1)]
        )
        if kind == "ycck":
            expected.append((2, 2))
        if sampling != expected:
            raise ValueError(
                f"JPEG sampling is {sampling!r}, expected {expected!r}"
            )
    elif kind == "cmyk" and header["components"] != 4:
        raise ValueError("CMYK JPEG must contain four components")
    if profile["restart_marker_blocks"]:
        if (
            header["restart_interval"] <= 0
            or header["restart_markers"] <= 0
        ):
            raise ValueError("restart-marker fixture has no restart markers")
    elif header["restart_interval"] != 0:
        raise ValueError("unexpected restart interval")
    if kind == "ycck" and header["adobe_transform"] != 2:
        raise ValueError("YCCK fixture must use Adobe transform 2")
    if kind == "cmyk" and header["adobe_transform"] != 0:
        raise ValueError("CMYK fixture must use Adobe transform 0")


def _psnr(left: Any, right: Any) -> float:
    runtime = _runtime()
    np = runtime["np"]
    delta = left.astype(np.float64) - right.astype(np.float64)
    mse = float(np.mean(delta * delta))
    return 999.0 if mse == 0 else 10.0 * math.log10(255.0**2 / mse)


def _save_pillow_jpeg(
    pixels: Any,
    *,
    profile: dict[str, Any],
) -> bytes:
    runtime = _runtime()
    Image = runtime["Image"]
    buffer = io.BytesIO()
    kind = profile["kind"]
    if kind == "grayscale":
        np = runtime["np"]
        source = (
            (
                pixels[..., 0].astype(np.uint16) * 77
                + pixels[..., 1].astype(np.uint16) * 150
                + pixels[..., 2].astype(np.uint16) * 29
            )
            >> 8
        ).astype(np.uint8)
        image = Image.fromarray(source, "L")
        subsampling: int | str = 0
    elif kind == "cmyk":
        np = runtime["np"]
        height, width, _ = pixels.shape
        source = np.empty((height, width, 4), dtype=np.uint8)
        source[..., :3] = 255 - pixels
        y, x = np.ogrid[:height, :width]
        source[..., 3] = ((x * 11 + y * 23 + 17) & 255).astype(np.uint8)
        image = Image.fromarray(source, "CMYK")
        subsampling = 0
    else:
        image = Image.fromarray(pixels, "RGB")
        subsampling = 2 if profile["subsampling"] == "420" else 0
    settings: dict[str, Any] = {
        "quality": profile["quality"],
        "subsampling": subsampling,
        "progressive": profile["progressive"],
        "optimize": False,
    }
    if profile["restart_marker_blocks"]:
        settings["restart_marker_blocks"] = profile[
            "restart_marker_blocks"
        ]
    image.save(buffer, "JPEG", **settings)
    return buffer.getvalue()


def _reference_pixels(
    data: bytes,
    *,
    reference: str,
) -> Any:
    runtime = _runtime()
    np = runtime["np"]
    if reference == "retained_decode":
        return np.asarray(runtime["core"].read_jpeg(data).pixels).copy()
    with runtime["Image"].open(io.BytesIO(data)) as image:
        if reference == "pillow_rgb":
            return np.asarray(image.convert("RGB")).copy()
        if reference == "pillow_native":
            return np.asarray(image).copy()
    raise ValueError(f"unknown reference {reference!r}")


def _prepare_corpus(request: dict[str, Any]) -> dict[str, Any]:
    runtime = _verify_marker(request["expected_marker"])
    np = runtime["np"]
    output = Path(request["output_dir"]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = request["config"]
    fixtures = {item["id"]: item for item in config["fixtures"]}
    raw_entries: list[dict[str, Any]] = []
    pixels_by_id: dict[str, Any] = {}
    for fixture in config["fixtures"]:
        pixels = _fixture_pixels(
            fixture["id"],
            fixture["height"],
            fixture["width"],
            fixture["seed"],
        )
        raw_name = f"raw-{fixture['id']}.npy"
        raw_path = output / raw_name
        np.save(raw_path, pixels, allow_pickle=False)
        raw_bytes = pixels.tobytes(order="C")
        raw_entries.append(
            {
                "id": fixture["id"],
                "class": fixture["class"],
                "height": fixture["height"],
                "width": fixture["width"],
                "dtype": "uint8",
                "channels": 3,
                "seed": fixture["seed"],
                "generator": "sceneio-integer-pattern-v1",
                "raw_sha256": _sha256_bytes(raw_bytes),
                "raw_bytes": len(raw_bytes),
                "npy_path": raw_name,
                "npy_sha256": _sha256_file(raw_path),
            }
        )
        pixels_by_id[fixture["id"]] = pixels

    entries: list[dict[str, Any]] = []
    for profile in config["decode_profiles"]:
        for fixture_id in profile["fixtures"]:
            if fixture_id == "ycck_16x16":
                encoded = base64.b64decode(
                    Path(request["ycck_base64_path"]).read_bytes(),
                    validate=False,
                )
                fixture = None
                raw_sha256 = (
                    "sceneio-generated-cmyk-formula-v1:"
                    "c13y3-m5y17-y19y7-k11y23"
                )
            else:
                fixture = fixtures[fixture_id]
                pixels = pixels_by_id[fixture_id]
                raw_sha256 = next(
                    item["raw_sha256"]
                    for item in raw_entries
                    if item["id"] == fixture_id
                )
            for producer in profile["producers"]:
                if producer == "retained":
                    image = runtime["core"].image(
                        pixels, color_space="srgb"
                    )
                    encoded = bytes(
                        runtime["core"].write_jpeg(
                            image, profile["quality"]
                        )
                    )
                    producer_version = request["source_commit"]
                    provenance = (
                        "retained SceneIO qualification wheel writer"
                    )
                elif producer == "pillow":
                    encoded = _save_pillow_jpeg(
                        pixels, profile=profile
                    )
                    producer_version = runtime["pillow_version"]
                    provenance = "Pillow JPEG writer"
                elif (
                    producer
                    == "sceneio_generated_libjpeg_turbo_3_2_0"
                ):
                    producer_version = "3.2.0"
                    provenance = (
                        "SceneIO-generated TurboJPEG CMYK input fixture; "
                        "see bench/fixtures/jpeg/README.md"
                    )
                else:
                    raise ValueError(
                        f"unknown corpus producer {producer!r}"
                    )
                header = _jpeg_header(encoded)
                _assert_header(
                    header, profile=profile, fixture=fixture
                )
                entry_id = (
                    f"{profile['id']}--{producer}--{fixture_id}"
                )
                encoded_name = f"{entry_id}.jpg"
                encoded_path = output / encoded_name
                encoded_path.write_bytes(encoded)
                reference = _reference_pixels(
                    encoded, reference=profile["reference"]
                )
                reference_name = f"{entry_id}.reference.npy"
                reference_path = output / reference_name
                np.save(reference_path, reference, allow_pickle=False)
                entries.append(
                    {
                        "id": entry_id,
                        "profile": profile["id"],
                        "kind": profile["kind"],
                        "producer": producer,
                        "producer_version": producer_version,
                        "provenance": provenance,
                        "settings": {
                            "quality": profile["quality"],
                            "subsampling": profile["subsampling"],
                            "progressive": profile["progressive"],
                            "restart_marker_blocks": profile[
                                "restart_marker_blocks"
                            ],
                        },
                        "accepted_subset": profile["id"],
                        "fixture": fixture_id,
                        "raw_sha256": raw_sha256,
                        "encoded_path": encoded_name,
                        "encoded_sha256": _sha256_bytes(encoded),
                        "encoded_bytes": len(encoded),
                        "reference": profile["reference"],
                        "reference_path": reference_name,
                        "reference_sha256": _sha256_file(reference_path),
                        "reference_shape": list(reference.shape),
                        "reference_dtype": str(reference.dtype),
                        "header": header,
                    }
                )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": request["decision_id"],
        "source_commit": request["source_commit"],
        "config_sha256": request["config_sha256"],
        "producer_backend": request["expected_marker"],
        "pillow_version": runtime["pillow_version"],
        "raw_fixtures": raw_entries,
        "encoded_fixtures": entries,
    }
    manifest_path = output / "corpus_manifest.json"
    manifest_path.write_bytes(_canonical_bytes(manifest))
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "raw_fixture_count": len(raw_entries),
        "encoded_fixture_count": len(entries),
    }


def _validate_corpus(path: Path, expected_sha256: str) -> dict[str, Any]:
    if _sha256_file(path) != expected_sha256:
        raise ValueError("corpus manifest hash mismatch")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported corpus manifest schema")
    for fixture in manifest["raw_fixtures"]:
        source = root / fixture["npy_path"]
        if _sha256_file(source) != fixture["npy_sha256"]:
            raise ValueError(
                f"raw corpus fixture hash mismatch: {fixture['id']}"
            )
    for fixture in manifest["encoded_fixtures"]:
        encoded = root / fixture["encoded_path"]
        reference = root / fixture["reference_path"]
        if (
            _sha256_file(encoded) != fixture["encoded_sha256"]
            or _sha256_file(reference) != fixture["reference_sha256"]
        ):
            raise ValueError(
                f"encoded corpus fixture hash mismatch: {fixture['id']}"
            )
    return manifest


def _load_record(corpus_root: Path, manifest: dict[str, Any], fixture_id: str):
    runtime = _runtime()
    fixture = next(
        item for item in manifest["raw_fixtures"] if item["id"] == fixture_id
    )
    pixels = runtime["np"].load(
        corpus_root / fixture["npy_path"], allow_pickle=False
    )
    return pixels, runtime["core"].image(pixels, color_space="srgb")


def _encoded_fixture(
    corpus_root: Path,
    manifest: dict[str, Any],
    *,
    profile: str,
    producer: str,
    fixture: str,
) -> tuple[dict[str, Any], Path]:
    entry = next(
        item
        for item in manifest["encoded_fixtures"]
        if item["profile"] == profile
        and item["producer"] == producer
        and item["fixture"] == fixture
    )
    return entry, corpus_root / entry["encoded_path"]


def _timed_samples(
    operation,
    *,
    warmups: int,
    samples: int,
    iterations: int,
) -> tuple[list[dict[str, int]], object]:
    for _ in range(warmups):
        value = operation()
        del value
    observations: list[dict[str, int]] = []
    last: object = None
    for sample_index in range(samples):
        if sample_index:
            last = None
        start = time.perf_counter_ns()
        for iteration in range(iterations):
            value = operation()
            if iteration + 1 == iterations:
                last = value
            del value
        total = time.perf_counter_ns() - start
        observations.append(
            {
                "total_ns": total,
                "iterations": iterations,
                "per_operation_ns": max(1, round(total / iterations)),
            }
        )
    return observations, last


def _trace_peak(operation) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        value = operation()
        _, peak = tracemalloc.get_traced_memory()
        del value
        return peak
    finally:
        tracemalloc.stop()


def _encode_cell(
    cell: dict[str, Any],
    *,
    fixture: dict[str, Any],
    profile: dict[str, Any],
    corpus_root: Path,
    manifest: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    runtime = _runtime()
    pixels, record = _load_record(
        corpus_root, manifest, cell["fixture"]
    )
    quality = profile["quality"]
    output_path = output_dir / (
        hashlib.sha256(cell["id"].encode()).hexdigest() + ".jpg"
    )
    path = cell["path"]
    if path == "core_buffer":
        def operation():
            return runtime["core"].write_jpeg(record, quality)
    elif path == "core_sink":
        if quality != 95:
            raise ValueError("core direct sink exposes only default quality 95")

        def operation():
            return runtime["core"]._write_to_file(
                runtime["core"].write_jpeg, record, output_path
            )
    elif path == "public_sink":
        if quality != 95:
            raise ValueError("public JPEG sink exposes only quality 95")

        def operation():
            return runtime["sceneio"].write(
                record, output_path, format="jpeg"
            )
    else:
        raise ValueError(f"unknown encode path {path!r}")
    samples, last = _timed_samples(
        operation,
        warmups=fixture["warmups"],
        samples=fixture["samples"],
        iterations=fixture["iterations_per_sample"],
    )
    del last
    trace_peak = _trace_peak(operation)
    canonical = bytes(runtime["core"].write_jpeg(record, quality))
    if path != "core_buffer":
        operation()
        sink_bytes = output_path.read_bytes()
        if sink_bytes != canonical:
            raise ValueError("sink output differs from core-buffer output")
    with runtime["Image"].open(io.BytesIO(canonical)) as image:
        decoded = runtime["np"].asarray(image.convert("RGB")).copy()
    header = _jpeg_header(canonical)
    header_profile = {
        "kind": "rgb",
        "subsampling": profile["subsampling"],
        "progressive": False,
        "restart_marker_blocks": 0,
    }
    _assert_header(header, profile=header_profile, fixture=fixture)
    return {
        "cell": cell["id"],
        "operation": "encode",
        "profile": profile["id"],
        "fixture": fixture["id"],
        "fixture_class": fixture["class"],
        "path": path,
        "effective_backend": _backend_marker(runtime["core"]),
        "samples": samples,
        "traced_peak_bytes": trace_peak,
        "raw_bytes": int(pixels.nbytes),
        "encoded_bytes": len(canonical),
        "encoded_sha256": _sha256_bytes(canonical),
        "psnr_db": _psnr(decoded, pixels),
        "header": header,
    }


def _decode_cell(
    cell: dict[str, Any],
    *,
    fixture: dict[str, Any],
    profile: dict[str, Any],
    corpus_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    runtime = _runtime()
    np = runtime["np"]
    entry, encoded_path = _encoded_fixture(
        corpus_root,
        manifest,
        profile=profile["id"],
        producer=cell["producer"],
        fixture=cell["fixture"],
    )
    reference = np.load(
        corpus_root / entry["reference_path"], allow_pickle=False
    )
    path = cell["path"]
    mapped = None
    stream = None
    if path == "core_bytes":
        data = encoded_path.read_bytes()

        def operation():
            return runtime["core"].read_jpeg(data)
    elif path == "core_mmap":
        stream = encoded_path.open("rb")
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)

        def operation():
            return runtime["core"].read_jpeg(mapped)
    elif path == "public_path":
        def operation():
            return runtime["sceneio"].read(
                encoded_path, format="jpeg"
            )
    else:
        raise ValueError(f"unknown decode path {path!r}")
    try:
        samples, last = _timed_samples(
            operation,
            warmups=fixture["warmups"],
            samples=fixture["samples"],
            iterations=fixture["iterations_per_sample"],
        )
        del last
        trace_peak = _trace_peak(operation)
        verification = operation()
        pixels = np.asarray(verification.pixels).copy()
        metadata = {
            "height": verification.height,
            "width": verification.width,
            "channels": verification.channels,
            "dtype": verification.dtype,
            "color_space": verification.color_space,
            "alpha_mode": verification.alpha_mode,
        }
        del verification
    finally:
        if mapped is not None:
            mapped.close()
        if stream is not None:
            stream.close()
    if pixels.shape != reference.shape or pixels.dtype != reference.dtype:
        raise ValueError("decoded pixels differ in shape or dtype")
    difference = np.abs(
        pixels.astype(np.int16) - reference.astype(np.int16)
    )
    fallback = profile["kind"] in {"cmyk", "ycck"}
    return {
        "cell": cell["id"],
        "operation": "decode",
        "profile": profile["id"],
        "producer": cell["producer"],
        "fixture": cell["fixture"],
        "fixture_class": fixture["class"],
        "path": path,
        "effective_backend": (
            "stb-fallback" if fallback else _backend_marker(runtime["core"])
        ),
        "samples": samples,
        "traced_peak_bytes": trace_peak,
        "raw_bytes": int(pixels.nbytes),
        "encoded_bytes": entry["encoded_bytes"],
        "encoded_sha256": entry["encoded_sha256"],
        "pixel_sha256": _sha256_bytes(pixels.tobytes(order="C")),
        "max_abs_vs_reference": int(difference.max(initial=0)),
        "psnr_vs_reference_db": _psnr(pixels, reference),
        "metadata": metadata,
    }


def _session(request: dict[str, Any]) -> dict[str, Any]:
    runtime = _verify_marker(request["expected_marker"])
    manifest_path = Path(request["corpus_manifest_path"]).resolve()
    manifest = _validate_corpus(
        manifest_path, request["corpus_manifest_sha256"]
    )
    if manifest["config_sha256"] != request["config_sha256"]:
        raise ValueError("corpus and session configuration differ")
    output_dir = Path(request["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    fixtures = {item["id"]: item for item in request["config"]["fixtures"]}
    fixtures["ycck_16x16"] = {
        "id": "ycck_16x16",
        "class": "small",
        "height": 16,
        "width": 16,
        "seed": 0,
        "warmups": 1 if request["config"]["quick"] else 3,
        "samples": 1 if request["config"]["quick"] else 15,
        "iterations_per_sample": (
            1 if request["config"]["quick"] else 32
        ),
        "remote_only": False,
    }
    encode_profiles = {
        item["id"]: item for item in request["config"]["encode_profiles"]
    }
    decode_profiles = {
        item["id"]: item for item in request["config"]["decode_profiles"]
    }
    results = []
    for cell in request["cells"]:
        fixture = fixtures[cell["fixture"]]
        if cell["operation"] == "encode":
            result = _encode_cell(
                cell,
                fixture=fixture,
                profile=encode_profiles[cell["profile"]],
                corpus_root=manifest_path.parent,
                manifest=manifest,
                output_dir=output_dir,
            )
        elif cell["operation"] == "decode":
            result = _decode_cell(
                cell,
                fixture=fixture,
                profile=decode_profiles[cell["profile"]],
                corpus_root=manifest_path.parent,
                manifest=manifest,
            )
        else:
            raise ValueError(f"unknown cell operation {cell['operation']!r}")
        results.append(result)
    return {
        "pid": os.getpid(),
        "backend": request["backend"],
        "marker": _backend_marker(runtime["core"]),
        "round": request["round"],
        "cell_order": [cell["id"] for cell in request["cells"]],
        "results": results,
        "import_ns": runtime["import_ns"],
    }


def _startup(request: dict[str, Any]) -> dict[str, Any]:
    runtime = _verify_marker(request["expected_marker"])
    manifest_path = Path(request["corpus_manifest_path"]).resolve()
    manifest = _validate_corpus(
        manifest_path, request["corpus_manifest_sha256"]
    )
    corpus_root = manifest_path.parent
    fixture_id = request["fixture"]
    _, record = _load_record(corpus_root, manifest, fixture_id)
    entry, encoded_path = _encoded_fixture(
        corpus_root,
        manifest,
        profile="baseline_rgb_420",
        producer="pillow",
        fixture=fixture_id,
    )
    data = encoded_path.read_bytes()

    operation = request["operation"]
    if operation == "encode":
        start = time.perf_counter_ns()
        value = runtime["core"].write_jpeg(record, 95)
        first_call_ns = time.perf_counter_ns() - start
        output_sha256 = _sha256_bytes(bytes(value))
    elif operation == "decode":
        start = time.perf_counter_ns()
        value = runtime["core"].read_jpeg(data)
        first_call_ns = time.perf_counter_ns() - start
        pixels = runtime["np"].asarray(value.pixels)
        output_sha256 = _sha256_bytes(pixels.tobytes(order="C"))
    else:
        raise ValueError(f"unknown startup operation {operation!r}")
    del value
    return {
        "pid": os.getpid(),
        "marker": _backend_marker(runtime["core"]),
        "fixture": fixture_id,
        "encoded_sha256": entry["encoded_sha256"],
        "import_ns": runtime["import_ns"],
        "operation": operation,
        "first_call_ns": first_call_ns,
        "output_sha256": output_sha256,
    }


def _determinism(request: dict[str, Any]) -> dict[str, Any]:
    runtime = _verify_marker(request["expected_marker"])
    manifest_path = Path(request["corpus_manifest_path"]).resolve()
    manifest = _validate_corpus(
        manifest_path, request["corpus_manifest_sha256"]
    )
    corpus_root = manifest_path.parent
    fixture_id = request["fixture"]
    _, record = _load_record(corpus_root, manifest, fixture_id)
    repeats = request["repeats"]
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 2:
        raise ValueError("determinism repeats must be at least two")
    output_dir = Path(request["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    encoders = []
    for profile in request["config"]["encode_profiles"]:
        hashes = [
            _sha256_bytes(
                bytes(
                    runtime["core"].write_jpeg(
                        record, profile["quality"]
                    )
                )
            )
            for _ in range(repeats)
        ]
        result: dict[str, Any] = {
            "profile": profile["id"],
            "quality": profile["quality"],
            "hashes": hashes,
        }
        if profile["quality"] == 95:
            canonical = bytes(runtime["core"].write_jpeg(record, 95))
            core_sink = output_dir / "core-sink.jpg"
            public_sink = output_dir / "public-sink.jpg"
            runtime["core"]._write_to_file(
                runtime["core"].write_jpeg, record, core_sink
            )
            runtime["sceneio"].write(
                record, public_sink, format="jpeg"
            )
            result["core_sink_sha256"] = _sha256_file(core_sink)
            result["public_sink_sha256"] = _sha256_file(public_sink)
            result["buffer_sha256"] = _sha256_bytes(canonical)
        encoders.append(result)

    decoders = []
    selected = [
        entry
        for entry in manifest["encoded_fixtures"]
        if entry["fixture"] in {fixture_id, "ycck_16x16"}
    ]
    for entry in selected:
        data = (corpus_root / entry["encoded_path"]).read_bytes()
        hashes = []
        for _ in range(repeats):
            decoded = runtime["core"].read_jpeg(data)
            pixels = runtime["np"].asarray(decoded.pixels)
            hashes.append(
                _sha256_bytes(pixels.tobytes(order="C"))
            )
        decoders.append(
            {
                "fixture": entry["id"],
                "encoded_sha256": entry["encoded_sha256"],
                "pixel_hashes": hashes,
            }
        )
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError(
            "determinism plateau measurement requires psutil"
        ) from exc
    process = psutil.Process()
    encode_rss = []
    for _ in range(50):
        value = runtime["core"].write_jpeg(record, 95)
        del value
        encode_rss.append(int(process.memory_info().rss))
    plateau_entry = next(
        entry
        for entry in selected
        if entry["profile"] == "baseline_rgb_420"
        and entry["producer"] == "pillow"
        and entry["fixture"] == fixture_id
    )
    plateau_data = (
        corpus_root / plateau_entry["encoded_path"]
    ).read_bytes()
    decode_rss = []
    for _ in range(50):
        value = runtime["core"].read_jpeg(plateau_data)
        del value
        decode_rss.append(int(process.memory_info().rss))
    return {
        "pid": os.getpid(),
        "marker": _backend_marker(runtime["core"]),
        "fixture": fixture_id,
        "repeats": repeats,
        "encoders": encoders,
        "decoders": decoders,
        "rss_plateau": {
            "encode_q95_core_buffer": encode_rss,
            "decode_420_core_bytes": decode_rss,
        },
    }


def _memory_operation(
    request: dict[str, Any],
    *,
    fixture_override: str | None = None,
    output_label: str = "measured",
) -> tuple[Any, list[Any], dict[str, Any]]:
    runtime = _verify_marker(request["expected_marker"])
    manifest_path = Path(request["corpus_manifest_path"]).resolve()
    manifest = _validate_corpus(
        manifest_path, request["corpus_manifest_sha256"]
    )
    corpus_root = manifest_path.parent
    case = dict(request["case"])
    if fixture_override is not None:
        case["fixture"] = fixture_override
    config = request["config"]
    retained: list[Any] = []
    output_dir = (
        Path(request["output_dir"]).resolve() / output_label
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    if case["operation"] == "encode":
        _, record = _load_record(
            corpus_root, manifest, case["fixture"]
        )
        retained.append(record)
        profile = next(
            item
            for item in config["encode_profiles"]
            if item["id"] == case["profile"]
        )
        quality = profile["quality"]
        if case["path"] == "core_buffer":
            def operation():
                return runtime["core"].write_jpeg(record, quality)
        elif case["path"] == "public_sink":
            destination = output_dir / "memory.jpg"

            def operation():
                return runtime["sceneio"].write(
                    record, destination, format="jpeg"
                )
        else:
            raise ValueError("unsupported encode memory path")
        metadata = {
            "logical_bytes": record.height * record.width * record.channels,
            "encoded_bytes": None,
        }
    elif case["operation"] == "decode":
        entry, encoded_path = _encoded_fixture(
            corpus_root,
            manifest,
            profile=case["profile"],
            producer=case["producer"],
            fixture=case["fixture"],
        )
        if case["path"] == "core_mmap":
            stream = encoded_path.open("rb")
            mapped = mmap.mmap(
                stream.fileno(), 0, access=mmap.ACCESS_READ
            )
            retained.extend((mapped, stream))

            def operation():
                return runtime["core"].read_jpeg(mapped)
        elif case["path"] == "public_path":
            def operation():
                return runtime["sceneio"].read(
                    encoded_path, format="jpeg"
                )
        else:
            raise ValueError("unsupported decode memory path")
        metadata = {
            "logical_bytes": (
                entry["reference_shape"][0]
                * entry["reference_shape"][1]
                * (
                    1
                    if len(entry["reference_shape"]) == 2
                    else entry["reference_shape"][2]
                )
            ),
            "encoded_bytes": entry["encoded_bytes"],
        }
    else:
        raise ValueError("unsupported memory operation")
    return operation, retained, metadata


def _memory(request: dict[str, Any]) -> dict[str, Any]:
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError(
            "memory qualification requires psutil in the backend environment"
        ) from exc
    warm_operation, warm_retained, _ = _memory_operation(
        request,
        fixture_override="small_odd",
        output_label="warmup",
    )
    retained: list[Any] = []
    try:
        try:
            warm = warm_operation()
            del warm
        finally:
            for resource in warm_retained:
                if hasattr(resource, "close"):
                    resource.close()
        gc.collect()
        operation, retained, metadata = _memory_operation(request)
        process = psutil.Process()
        baseline = int(process.memory_info().rss)
        ready = {
            "schema_version": SCHEMA_VERSION,
            "action": "memory",
            "status": "ready",
            "pid": os.getpid(),
            "baseline_rss_bytes": baseline,
        }
        print(_canonical_bytes(ready).decode("utf-8"), end="", flush=True)
        command = json.loads(sys.stdin.readline())
        if command != {"command": "go"}:
            raise ValueError("memory controller did not send the go command")
        start = time.perf_counter_ns()
        value = operation()
        duration = time.perf_counter_ns() - start
        after = int(process.memory_info().rss)
        del value
        result = {
            "pid": os.getpid(),
            "marker": _backend_marker(_runtime()["core"]),
            "case": request["case"]["id"],
            "operation": request["case"]["operation"],
            "profile": request["case"]["profile"],
            "producer": request["case"].get("producer"),
            "fixture": request["case"]["fixture"],
            "path": request["case"]["path"],
            "duration_ns": duration,
            "worker_baseline_rss_bytes": baseline,
            "worker_after_rss_bytes": after,
            **metadata,
        }
    finally:
        for resource in retained:
            if hasattr(resource, "close"):
                resource.close()
    return result


def _probe(request: dict[str, Any]) -> dict[str, Any]:
    runtime = _verify_marker(request["expected_marker"])
    core_path = Path(runtime["core"].__file__).resolve()
    sceneio_path = Path(runtime["sceneio"].__file__).resolve()
    package_members = _installed_package_members(
        sceneio_path.parent, core_path
    )
    return {
        "pid": os.getpid(),
        "python_executable": str(Path(sys.executable).resolve()),
        "isolated": bool(sys.flags.isolated),
        "sceneio_path": str(sceneio_path),
        "core_path": str(core_path),
        "core_sha256": _sha256_file(core_path),
        "package_members_sha256": package_members,
        "marker": _backend_marker(runtime["core"]),
        "package_version": importlib.metadata.version("sceneio"),
        "numpy_version": runtime["np"].__version__,
        "pillow_version": runtime["pillow_version"],
        "import_ns": runtime["import_ns"],
        "worker_elapsed_ns": time.perf_counter_ns() - _START_NS,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "cpu_count": os.cpu_count(),
        },
        "dispatch_environment": {
            key: os.environ[key]
            for key in sorted(os.environ)
            if key.startswith(("JSIMD_", "TJ", "SCENEIO_"))
        },
    }


def _validate_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("worker request must be an object")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported worker schema")
    action = request.get("action")
    if action not in WORKER_ACTIONS:
        raise ValueError(f"unknown worker action {action!r}")
    expected = request.get("expected_marker")
    if not isinstance(expected, str) or not expected:
        raise ValueError("expected_marker must be a non-empty string")
    return request


def _run(request: dict[str, Any]) -> dict[str, Any]:
    action = request["action"]
    if action == "probe":
        payload = _probe(request)
    elif action == "prepare_corpus":
        payload = _prepare_corpus(request)
    elif action == "session":
        payload = _session(request)
    elif action == "startup":
        payload = _startup(request)
    elif action == "determinism":
        payload = _determinism(request)
    else:
        payload = _memory(request)
    return {
        "schema_version": SCHEMA_VERSION,
        "action": action,
        "status": "ok",
        **payload,
    }


def main() -> int:
    try:
        request = _validate_request(json.loads(sys.stdin.readline()))
        response = _run(request)
    except Exception as exc:
        response = {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        print(_canonical_bytes(response).decode("utf-8"), end="")
        return 2
    print(_canonical_bytes(response).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
