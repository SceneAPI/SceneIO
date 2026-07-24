"""O0-O4 I/O benchmark harness for docs/io_optimization_plan.md.

Measures, per codec, encode (write) + decode (read) throughput (MB/s over the raw
payload) and peak Python allocation (tracemalloc), for sceneio._core vs the oracle
library where one exists, on representative payloads for all 23 codecs. Read
measurements retain the legacy whole-file bytes/copy-decode path beside the
public registry mmap path, so their peak delta captures the input copy O1
removes and, for NPY/FLO, the decoded-array copy O2 removes. Write measurements
retain the in-memory bytes encoder beside the public file sink, so their peak
delta captures the output-sized Python allocation O3 removes. Oracle failures
degrade to "-" so the SceneIO measurements always print.

Run: python bench/bench_io.py [--runs N] [--scale S] [--cold-cache]
Synthetic fixtures are generated in a temporary directory and never committed.
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import os
import statistics
import tempfile
import threading
import time
import tracemalloc
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np

import sceneio
from sceneio import _core

# --- optional oracle libs (degrade gracefully) ------------------------------
try:
    from PIL import Image as PILImage
except Exception:
    PILImage = None
try:
    import laspy
except Exception:
    laspy = None
try:
    import gsply
except Exception:
    gsply = None
try:
    import imageio.v3 as iio
except Exception:
    iio = None
try:
    import OpenEXR
except Exception:
    OpenEXR = None
try:
    import psutil
except Exception:
    psutil = None


def _measure(fn: Callable[[], object], runs: int) -> tuple[float, int]:
    """Median wall time (s) and peak traced Python allocation (bytes) over `runs`."""
    fn()  # warm
    times, peak = [], 0
    for _ in range(runs):
        tracemalloc.start()
        t0 = time.perf_counter()
        r = fn()
        dt = time.perf_counter() - t0
        _, pk = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times.append(dt)
        peak = max(peak, pk)
        del r
    return statistics.median(times), peak


def _try(fn):
    """Run an oracle closure; return (median_time, None) sentinel on any failure."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return fn()
    except Exception:
        return None


def _measure_rss(fn):
    """Peak resident-set growth sampled during one call (0 when psutil is absent)."""
    if psutil is None:
        return 0
    gc.collect()
    process = psutil.Process()
    baseline = process.memory_info().rss
    peak = baseline
    running = True

    def sample():
        nonlocal peak
        while running:
            peak = max(peak, process.memory_info().rss)
            time.sleep(0.0005)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        value = fn()
        peak = max(peak, process.memory_info().rss)
        del value
    finally:
        running = False
        sampler.join()
    return max(0, peak - baseline)


# --- payload builders -------------------------------------------------------
def _img_u8(h, w):
    a = np.random.default_rng(0).integers(0, 256, (h, w, 3), dtype=np.uint8)
    return _core.image(a, color_space="srgb"), a


def _img_f32(h, w):
    a = (np.random.default_rng(0).random((h, w, 3), dtype=np.float32) * 10.0).astype(np.float32)
    return _core.image(a, color_space="linear"), a


def _img_webp_palette(h, w):
    palette = np.array(
        [
            [0, 0, 0],
            [255, 255, 255],
            [255, 0, 0],
            [0, 255, 0],
            [0, 0, 255],
            [255, 255, 0],
            [255, 0, 255],
            [0, 255, 255],
        ],
        dtype=np.uint8,
    )
    yy, xx = np.indices((h, w))
    a = palette[((xx // 7) + (yy // 11)) % len(palette)]
    return _core.image(a, color_space="srgb"), a


def _pc(n, color):
    rng = np.random.default_rng(0)
    xyz = (rng.random((n, 3), dtype=np.float32) * 100.0).astype(np.float32)
    kw = {}
    if color:
        kw["colors16"] = (rng.random((n, 3)) * 65535).astype(np.uint16)
        kw["intensity"] = (rng.random(n) * 60000).astype(np.float32)
    return _core.point_cloud(xyz, **kw), xyz


def _gauss(n):
    rng = np.random.default_rng(0)
    f = lambda *s: rng.standard_normal(s).astype(np.float32)  # noqa: E731
    payload = {
        "means": f(n, 3),
        "scales": f(n, 3),
        "quats": f(n, 4),
        "opacities": f(n),
        "sh0": f(n, 3),
    }
    return (
        _core.gaussian_cloud(
            payload["means"],
            payload["scales"],
            payload["quats"],
            payload["opacities"],
            payload["sh0"],
        ),
        payload,
    )


def _poses_and_reconstruction(scale=1.0):
    points = max(1, int(10_000 * scale))
    views = max(1, int(10_000 * scale))
    reconstruction = _core.read_nvm(
        b"NVM_V3\n1\na.jpg 800 0.5 0.5 0.5 0.5 1 2 3 0 0\n"
        + str(points).encode()
        + b"\n"
        + b"1.5 -2.5 3.5 10 20 30 0\n" * points
        + b"0\n"
    )
    frame = b'{"file_path":"a.png","transform_matrix":[[1,0,0,1],[0,1,0,2],[0,0,1,3],[0,0,0,1]]}'
    transforms = _core.read_transforms_json(
        b'{"camera_model":"PINHOLE","fl_x":500,"fl_y":510,"cx":320,"cy":240,'
        b'"w":640,"h":480,"frames":[' + b",".join([frame] * views) + b"]}"
    )
    tum = _core.read_tum(b"0 1 2 3 0 0 0 1\n" * views)
    kitti = _core.read_kitti(b"1 0 0 1 0 1 0 2 0 0 1 3\n" * views)
    return reconstruction, transforms, tum, kitti


def _record_nbytes(record):
    names = (
        "quaternions",
        "translations",
        "camera_indices",
        "timestamps",
        "image_ids",
        "image_camera_ids",
        "point3D_ids",
        "xyz",
        "rgb",
        "errors",
    )
    total = sum(np.asarray(getattr(record, name)).nbytes for name in names if hasattr(record, name))
    total += sum(np.asarray(camera.params).nbytes for camera in getattr(record, "cameras", ()))
    return max(total, 1)


# --- codec specs: (id, build, sio_write, sio_read, oracle_write, oracle_read, payload_bytes) ---
@dataclass
class Spec:
    id: str
    make: Callable
    w: Callable  # record -> bytes
    r: Callable  # bytes -> record
    ow: Callable | None  # oracle: payload -> bytes
    orr: Callable | None  # oracle: bytes -> obj
    nbytes: Callable  # (record, payload) -> logical payload bytes


def _pil_w(mode):
    def enc(a):
        b = io.BytesIO()
        PILImage.fromarray(a).save(
            b, mode, lossless=True
        ) if mode == "WEBP" else PILImage.fromarray(a).save(b, mode)
        return b.getvalue()

    return enc


def _pil_r(data):
    return np.asarray(PILImage.open(io.BytesIO(data)))


def _imageio_w(extension):
    return lambda array: iio.imwrite("<bytes>", array, extension=extension)


def _imageio_r(extension):
    return lambda data: iio.imread(data, extension=extension)


def _openexr_w(array):
    fd, path = tempfile.mkstemp(suffix=".exr")
    os.close(fd)
    try:
        channels = {
            channel: np.ascontiguousarray(array[:, :, index]) for index, channel in enumerate("RGB")
        }
        with OpenEXR.File(
            {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage},
            channels,
        ) as output:
            output.write(path)
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def _openexr_r(data):
    fd, path = tempfile.mkstemp(suffix=".exr")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        with OpenEXR.File(path) as source:
            return {
                key: np.asarray(value.pixels) for key, value in source.parts[0].channels.items()
            }
    finally:
        os.remove(path)


def _gsply_ply_w(payload):
    fd, path = tempfile.mkstemp(suffix=".ply")
    os.close(fd)
    try:
        gsply.plywrite(
            path,
            payload["means"],
            scales=payload["scales"],
            quats=payload["quats"],
            opacities=payload["opacities"],
            sh0=payload["sh0"],
        )
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def _gsply_ply_r(data):
    fd, path = tempfile.mkstemp(suffix=".ply")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        return gsply.plyread(path)
    finally:
        os.remove(path)


def _gsply_spz_w(payload):
    fd, path = tempfile.mkstemp(suffix=".spz")
    os.close(fd)
    try:
        cloud = gsply.GSData.from_arrays(**payload, format="ply")
        gsply.write_spz(path, cloud, version=3)
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def _gsply_spz_r(data):
    fd, path = tempfile.mkstemp(suffix=".spz")
    os.close(fd)
    try:
        Path(path).write_bytes(data)
        return gsply.read_spz(path)
    finally:
        os.remove(path)


def _laspy_w(payload):
    hdr = laspy.LasHeader(version="1.2", point_format=0)
    hdr.scales = [0.001, 0.001, 0.001]
    las = laspy.LasData(hdr)
    las.x, las.y, las.z = payload[:, 0], payload[:, 1], payload[:, 2]
    b = io.BytesIO()
    las.write(b)
    return b.getvalue()


def _laspy_r(data):
    return laspy.read(io.BytesIO(data))


def _np_w(a):
    b = io.BytesIO()
    np.save(b, a)
    return b.getvalue()


def _np_r(d):
    return np.load(io.BytesIO(d))


def _save_npz_oracle(arrays):
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    return buffer.getvalue()


def _load_npz_oracle(data):
    with np.load(io.BytesIO(data)) as archive:
        return {name: np.array(archive[name], copy=True) for name in archive.files}


def _evict_file_cache(path):
    """Best-effort cold-cache hint (effective where POSIX_FADV_DONTNEED exists)."""
    if not hasattr(os, "posix_fadvise") or not hasattr(os, "POSIX_FADV_DONTNEED"):
        return False
    with open(path, "rb") as stream:
        os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    return True


def _specs(scale, pose_bundle=None):
    side = max(1, int(1024 * scale**0.5))
    points = max(1, int(1_000_000 * scale))
    gaussians = max(1, int(200_000 * scale))
    tensor_side = max(1, int(512 * scale**0.5))
    reconstruction, transforms, tum, kitti = pose_bundle or _poses_and_reconstruction(scale)
    flow = np.random.default_rng(4).standard_normal((side, side, 2)).astype(np.float32)
    pfm = np.random.default_rng(5).standard_normal((side, side)).astype(np.float32)
    npz_arrays = {
        "a": np.random.default_rng(6)
        .standard_normal((tensor_side, tensor_side))
        .astype(np.float32),
        "b": np.arange(max(1, tensor_side), dtype=np.int32),
    }
    tensors = _core.tensor_dict(npz_arrays)
    return [
        Spec(
            "png",
            lambda: _img_u8(side, side),
            _core.write_png,
            _core.read_png,
            (_pil_w("PNG") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "jpeg",
            lambda: _img_u8(side, side),
            lambda im: _core.write_jpeg(im, 95),
            _core.read_jpeg,
            (_pil_w("JPEG") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "webp",
            lambda: _img_u8(side, side),
            lambda im: _core.write_webp(im, True),
            _core.read_webp,
            (_pil_w("WEBP") if PILImage else None),
            (_pil_r if PILImage else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "hdr",
            lambda: _img_f32(side, side),
            _core.write_hdr,
            _core.read_hdr,
            (_imageio_w(".hdr") if iio else None),
            (_imageio_r(".hdr") if iio else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "exr",
            lambda: _img_f32(side, side),
            _core.write_exr,
            _core.read_exr,
            (_openexr_w if OpenEXR else None),
            (_openexr_r if OpenEXR else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "netpbm",
            lambda: _img_u8(side, side),
            lambda im: _core.write_netpbm(im, False),
            _core.read_netpbm,
            (_imageio_w(".ppm") if iio else (_pil_w("PPM") if PILImage else None)),
            (_imageio_r(".ppm") if iio else (_pil_r if PILImage else None)),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "xyz",
            lambda: _pc(points, False),
            _core.write_xyz,
            _core.read_xyz,
            None,
            None,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "las",
            lambda: _pc(points, True),
            lambda pc: _core.write_las(pc, 0.001),
            _core.read_las,
            (_laspy_w if laspy else None),
            (_laspy_r if laspy else None),
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "gaussian_ply",
            lambda: _gauss(gaussians),
            _core.write_gaussian_ply,
            _core.read_gaussian_ply,
            (_gsply_ply_w if gsply else None),
            (_gsply_ply_r if gsply else None),
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "spz",
            lambda: _gauss(gaussians),
            _core.write_spz,
            _core.read_spz,
            (_gsply_spz_w if gsply else None),
            (_gsply_spz_r if gsply else None),
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "splat",
            lambda: _gauss(gaussians),
            _core.write_splat,
            _core.read_splat,
            None,
            None,
            lambda rec, p: rec.num_gaussians * 14 * 4,
        ),
        Spec(
            "npy",
            lambda: (lambda a: (a, a))(
                np.ascontiguousarray(
                    np.random.default_rng(0).random((tensor_side, tensor_side, 8), dtype=np.float32)
                )
            ),
            _core.write_npy,
            _core.read_npy,
            _np_w,
            _np_r,
            lambda rec, p: rec.nbytes,
        ),
        Spec(
            "pfm",
            lambda: (pfm, pfm),
            _core.write_pfm,
            _core.read_pfm,
            None,
            None,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "flo",
            lambda: (flow, flow),
            _core.write_flo,
            _core.read_flo,
            None,
            None,
            lambda rec, p: p.nbytes,
        ),
        Spec(
            "npz",
            lambda: (tensors, npz_arrays),
            _core.write_npz,
            _core.read_npz,
            lambda arrays: _save_npz_oracle(arrays),
            _load_npz_oracle,
            lambda rec, p: sum(array.nbytes for array in p.values()),
        ),
        Spec(
            "transforms_json",
            lambda: (transforms, transforms),
            _core.write_transforms_json,
            _core.read_transforms_json,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "tum",
            lambda: (tum, tum),
            _core.write_tum,
            _core.read_tum,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "kitti",
            lambda: (kitti, kitti),
            _core.write_kitti,
            _core.read_kitti,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "bundler",
            lambda: (reconstruction, reconstruction),
            _core.write_bundler,
            _core.read_bundler,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "nvm",
            lambda: (reconstruction, reconstruction),
            _core.write_nvm,
            _core.read_nvm,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
        Spec(
            "openmvg",
            lambda: (reconstruction, reconstruction),
            _core.write_openmvg,
            _core.read_openmvg,
            None,
            None,
            lambda rec, p: _record_nbytes(rec),
        ),
    ]


@dataclass
class DirectorySpec:
    id: str
    w: Callable
    r: Callable


def _directory_specs():
    return [
        DirectorySpec("colmap_sparse", _core.write_colmap_sparse, _core.read_colmap_sparse),
        DirectorySpec("colmap_sparse_txt", _core.write_colmap_txt, _core.read_colmap_txt),
    ]


def _directory_size(path):
    return sum(entry.stat().st_size for entry in Path(path).iterdir() if entry.is_file())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="multiply logical payload sizes (e.g. 32 for generated large fixtures)",
    )
    ap.add_argument(
        "--cold-cache",
        action="store_true",
        help="request POSIX_FADV_DONTNEED before each path read when supported",
    )
    ap.add_argument(
        "--require-o4-gains",
        action="store_true",
        help=(
            "fail unless stable high-signal O4 controls improve and mmap/sink "
            "traced allocations remain bounded"
        ),
    )
    ap.add_argument("--json", type=Path, help="write machine-readable results to this path")
    args = ap.parse_args()
    if args.scale <= 0:
        ap.error("--scale must be positive")
    with tempfile.TemporaryDirectory(prefix="sceneio_bench_") as tmp:
        failures, results = _run_benchmark(args, tmp)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise RuntimeError("benchmark failures: " + ", ".join(failures))


def _run_benchmark(args, tmp):
    pose_bundle = _poses_and_reconstruction(args.scale)
    reconstruction = pose_bundle[0]
    specs = _specs(args.scale, pose_bundle)
    failures = []
    results = []
    write_rows = []
    o4_rows = []

    hdr = (
        f"{'codec':<14}{'payloadMB':>10}{'fileMB':>9}{'sioW':>9}{'sioR':>9}"
        f"{'pathR':>9}{'oraW':>9}{'oraR':>9}{'bPeakMB':>9}{'mPeakMB':>9}"
        f"{'bRSSMB':>9}{'mRSSMB':>9}{'sio/ora':>9}"
    )
    print(hdr)
    print("-" * len(hdr))
    for s in specs:
        try:
            rec, payload = s.make()
            enc = bytes(s.w(rec))
            pbytes = s.nbytes(rec, payload)
            pmb = pbytes / 1e6
            fmb = len(enc) / 1e6

            wt, _ = _measure(lambda: s.w(rec), args.runs)
            rt, _ = _measure(lambda: s.r(enc), args.runs)
            sioW, sioR = pmb / wt, pmb / rt
            o4_metrics = {}

            # O4 controls retain a deterministic one-lane/worker-off reference
            # beside the optimized defaults. WebP separately measures the old
            # forced effort=100 setting and a palette input on which libwebp
            # actually schedules its lossless side worker.
            if s.id == "webp":
                old_webp = partial(
                    _core.write_webp, rec, True, 90.0, False, 100, 4
                )
                old_time, _ = _measure(old_webp, args.runs)
                original = np.asarray(rec.pixels)
                if not np.array_equal(
                    np.asarray(_core.read_webp(old_webp()).pixels), original
                ):
                    raise AssertionError("lower WebP effort changed decoded pixels")

                palette_rec, palette_values = _img_webp_palette(
                    max(32, int(1024 * args.scale**0.5)),
                    max(32, int(1024 * args.scale**0.5)),
                )
                worker_off = partial(
                    _core.write_webp,
                    palette_rec,
                    True,
                    90.0,
                    False,
                )
                worker_on = partial(_core.write_webp, palette_rec)
                worker_off_time, _ = _measure(worker_off, args.runs)
                launch_count = _core._webp_worker_launch_count()
                worker_on_time, _ = _measure(worker_on, args.runs)
                if _core._webp_worker_launch_count() <= launch_count:
                    raise AssertionError("WebP side-worker path was not reached")
                worker_off_bytes = bytes(worker_off())
                worker_on_bytes = bytes(worker_on())
                if worker_off_bytes != worker_on_bytes:
                    raise AssertionError("WebP worker output differs")
                if not np.array_equal(
                    np.asarray(_core.read_webp(worker_on_bytes).pixels),
                    palette_values,
                ):
                    raise AssertionError("WebP worker decode differs")
                palette_mb = palette_values.nbytes / 1e6
                o4_rows.extend(
                    [
                        (
                            "webp",
                            "balanced-config",
                            pmb / old_time,
                            sioW,
                            "pixels",
                        ),
                        (
                            "webp",
                            "workers-palette",
                            palette_mb / worker_off_time,
                            palette_mb / worker_on_time,
                            "bytes",
                        ),
                    ]
                )
                o4_metrics.update(
                    {
                        "write_old_mbps": pmb / old_time,
                        "write_worker_off_mbps": palette_mb
                        / worker_off_time,
                        "write_optimized_mbps": sioW,
                        "write_worker_on_mbps": palette_mb / worker_on_time,
                    }
                )
            elif s.id in {"xyz", "exr", "las"}:
                if s.id == "xyz":
                    one_lane_write = partial(
                        _core.write_xyz, rec, _lanes=1
                    )
                    label = "format"
                elif s.id == "exr":
                    one_lane_write = partial(
                        _core.write_exr, rec, _lanes=1
                    )
                    label = "planar"
                else:
                    one_lane_write = partial(
                        _core.write_las, rec, _lanes=1
                    )
                    label = "points"
                one_write_time, _ = _measure(one_lane_write, args.runs)
                if bytes(one_lane_write()) != enc:
                    raise AssertionError(f"{s.id} lane output differs")
                o4_rows.append(
                    (s.id, f"{label}-write", pmb / one_write_time, sioW, "bytes")
                )
                o4_metrics.update(
                    {
                        "write_one_lane_mbps": pmb / one_write_time,
                        "write_optimized_mbps": sioW,
                    }
                )
                if s.id in {"exr", "las"}:
                    if s.id == "exr":
                        one_lane_read = partial(
                            _core.read_exr, enc, _lanes=1
                        )
                    else:
                        one_lane_read = partial(
                            _core.read_las, enc, _lanes=1
                        )
                    one_read_time, _ = _measure(one_lane_read, args.runs)
                    one_decoded = one_lane_read()
                    optimized_decoded = s.r(enc)
                    if s.id == "exr":
                        same_values = np.array_equal(
                            np.asarray(one_decoded.pixels),
                            np.asarray(optimized_decoded.pixels),
                        )
                        same_metadata = (
                            one_decoded.height,
                            one_decoded.width,
                            one_decoded.channels,
                            one_decoded.dtype,
                            one_decoded.color_space,
                            one_decoded.alpha_mode,
                            one_decoded.maxval,
                        ) == (
                            optimized_decoded.height,
                            optimized_decoded.width,
                            optimized_decoded.channels,
                            optimized_decoded.dtype,
                            optimized_decoded.color_space,
                            optimized_decoded.alpha_mode,
                            optimized_decoded.maxval,
                        )
                    else:
                        same_values = all(
                            np.array_equal(
                                np.asarray(getattr(one_decoded, field)),
                                np.asarray(getattr(optimized_decoded, field)),
                            )
                            for field in (
                                "positions",
                                "colors16",
                                "intensities",
                            )
                        ) and np.array_equal(
                            one_decoded.origin, optimized_decoded.origin
                        )
                        same_metadata = (
                            one_decoded.num_points,
                            one_decoded.coordinate_frame,
                            one_decoded.scale_to_meters,
                            one_decoded.intensity_range,
                        ) == (
                            optimized_decoded.num_points,
                            optimized_decoded.coordinate_frame,
                            optimized_decoded.scale_to_meters,
                            optimized_decoded.intensity_range,
                        )
                    if not same_values or not same_metadata:
                        raise AssertionError(
                            f"{s.id} lane decode differs"
                        )
                    o4_rows.append(
                        (
                            s.id,
                            f"{label}-read",
                            pmb / one_read_time,
                            sioR,
                            "values",
                        )
                    )
                    o4_metrics.update(
                        {
                            "read_one_lane_mbps": pmb / one_read_time,
                            "read_optimized_mbps": sioR,
                        }
                    )

            if s.id == "png":
                u16_side = max(1, int(1024 * args.scale**0.5))
                u16 = (
                    (
                        np.arange(u16_side * u16_side * 3, dtype=np.uint32)
                        * 40503
                    )
                    & 0xFFFF
                ).astype(np.uint16).reshape(u16_side, u16_side, 3)
                u16_image = _core.image(u16, color_space="srgb")
                png16_one_write = partial(
                    _core.write_png, u16_image, _lanes=1
                )
                png16_fast_write = partial(_core.write_png, u16_image)
                png16_one_time, _ = _measure(png16_one_write, args.runs)
                png16_fast_time, _ = _measure(png16_fast_write, args.runs)
                png16_data = bytes(png16_fast_write())
                if bytes(png16_one_write()) != png16_data:
                    raise AssertionError("PNG16 lane output differs")
                png16_one_read = partial(
                    _core.read_png, png16_data, _lanes=1
                )
                png16_fast_read = partial(_core.read_png, png16_data)
                png16_one_read_time, _ = _measure(png16_one_read, args.runs)
                png16_fast_read_time, _ = _measure(
                    png16_fast_read, args.runs
                )
                png16_one_values = np.asarray(png16_one_read().pixels)
                png16_fast_values = np.asarray(png16_fast_read().pixels)
                if not (
                    np.array_equal(png16_one_values, png16_fast_values)
                    and np.array_equal(png16_fast_values, u16)
                ):
                    raise AssertionError("PNG16 lane decode differs")
                png16_mb = u16.nbytes / 1e6
                o4_rows.extend(
                    [
                        (
                            "png16",
                            "swap-write",
                            png16_mb / png16_one_time,
                            png16_mb / png16_fast_time,
                            "bytes",
                        ),
                        (
                            "png16",
                            "swap-read",
                            png16_mb / png16_one_read_time,
                            png16_mb / png16_fast_read_time,
                            "values",
                        ),
                    ]
                )
                o4_metrics.update(
                    {
                        "png16_write_one_lane_mbps": png16_mb
                        / png16_one_time,
                        "png16_write_optimized_mbps": png16_mb
                        / png16_fast_time,
                        "png16_read_one_lane_mbps": png16_mb
                        / png16_one_read_time,
                        "png16_read_optimized_mbps": png16_mb
                        / png16_fast_read_time,
                    }
                )

            # Compare the legacy bytes+Path.write_bytes route with the public O3
            # file sink, then compare whole-file bytes + copy decode with the
            # public mmap path. NPY/FLO also expose the O2 mapped output view.
            fp = os.path.join(tmp, f"{s.id}.bin")

            def _bytes_write(fp=fp, w=s.w, value=rec):
                return Path(fp).write_bytes(w(value))

            def _sink_write(fp=fp, codec_id=s.id, value=rec):
                return sceneio.write(value, fp, format=codec_id)

            bytes_write_time, bytes_write_peak = _measure(
                _bytes_write, args.runs
            )
            bytes_write_rss = _measure_rss(_bytes_write)
            sink_time, sink_write_peak = _measure(_sink_write, args.runs)
            sink_write_rss = _measure_rss(_sink_write)
            with open(fp, "rb") as fh:
                if fh.read() != enc:
                    raise AssertionError("file sink output differs from buffer encoder")
            path_write = pmb / sink_time
            bytes_path_write = pmb / bytes_write_time
            write_rows.append(
                (
                    s.id,
                    pmb,
                    fmb,
                    bytes_path_write,
                    path_write,
                    bytes_write_peak / 1e6,
                    sink_write_peak / 1e6,
                    bytes_write_rss / 1e6,
                    sink_write_rss / 1e6,
                )
            )

            def _bytes_read(fp=fp, r=s.r):
                with open(fp, "rb") as fh:
                    return r(fh.read())

            def _mmap_read(fp=fp, codec_id=s.id):
                if args.cold_cache:
                    _evict_file_cache(fp)
                return sceneio.read(fp, format=codec_id)

            _, bytes_peak = _measure(_bytes_read, args.runs)
            path_time, mmap_peak = _measure(_mmap_read, args.runs)
            bytes_rss = _measure_rss(_bytes_read)
            mmap_rss = _measure_rss(_mmap_read)
            path_read = pmb / path_time

            oraW = oraR = None
            if s.ow and payload is not None:
                ob = _try(lambda: bytes(s.ow(payload)))
                if ob is not None:
                    m = _try(lambda: _measure(lambda: s.ow(payload), args.runs))
                    oraW = pmb / m[0] if m else None
                    mr = _try(lambda: _measure(lambda: s.orr(ob), args.runs))
                    oraR = pmb / mr[0] if mr else None

            ratio = (sioR / oraR) if oraR else None
            results.append(
                {
                    "codec": s.id,
                    "payload_mb": pmb,
                    "file_mb": fmb,
                    "write_mbps": sioW,
                    "bytes_path_write_mbps": bytes_path_write,
                    "path_write_mbps": path_write,
                    "read_mbps": sioR,
                    "path_read_mbps": path_read,
                    "oracle_write_mbps": oraW,
                    "oracle_read_mbps": oraR,
                    "bytes_peak_mb": bytes_peak / 1e6,
                    "mmap_peak_mb": mmap_peak / 1e6,
                    "bytes_rss_mb": bytes_rss / 1e6,
                    "mmap_rss_mb": mmap_rss / 1e6,
                    "bytes_write_peak_mb": bytes_write_peak / 1e6,
                    "sink_write_peak_mb": sink_write_peak / 1e6,
                    "bytes_write_rss_mb": bytes_write_rss / 1e6,
                    "sink_write_rss_mb": sink_write_rss / 1e6,
                    "o4": o4_metrics or None,
                }
            )
            print(
                f"{s.id:<14}{pmb:>10.1f}{fmb:>9.1f}{sioW:>9.0f}{sioR:>9.0f}"
                f"{path_read:>9.0f}{(oraW if oraW else 0):>9.0f}"
                f"{(oraR if oraR else 0):>9.0f}"
                f"{bytes_peak / 1e6:>9.1f}{mmap_peak / 1e6:>9.1f}"
                f"{bytes_rss / 1e6:>9.1f}{mmap_rss / 1e6:>9.1f}"
                f"{(ratio if ratio else 0):>9.2f}"
            )
        except Exception as e:
            failures.append(s.id)
            results.append({"codec": s.id, "error": f"{type(e).__name__}: {e}"})
            print(f"{s.id:<14} ERROR: {type(e).__name__}: {e}")

    for spec in _directory_specs():
        try:
            path = Path(tmp) / spec.id
            path.mkdir()
            spec.w(reconstruction, str(path))
            file_bytes = _directory_size(path)
            payload_bytes = _record_nbytes(reconstruction)
            pmb = payload_bytes / 1e6
            fmb = file_bytes / 1e6
            write_time, write_peak = _measure(
                lambda: spec.w(reconstruction, str(path)), args.runs
            )
            write_rss = _measure_rss(
                lambda: spec.w(reconstruction, str(path))
            )
            write_rows.append(
                (
                    spec.id,
                    pmb,
                    fmb,
                    None,
                    pmb / write_time,
                    None,
                    write_peak / 1e6,
                    None,
                    write_rss / 1e6,
                )
            )

            def _directory_read(path=path, codec_id=spec.id):
                if args.cold_cache:
                    for entry in path.iterdir():
                        if entry.is_file():
                            _evict_file_cache(entry)
                return sceneio.read(path, format=codec_id)

            core_read_time, _ = _measure(lambda: spec.r(str(path)), args.runs)
            path_read_time, read_peak = _measure(_directory_read, args.runs)
            read_rss = _measure_rss(_directory_read)
            results.append(
                {
                    "codec": spec.id,
                    "payload_mb": pmb,
                    "file_mb": fmb,
                    "write_mbps": pmb / write_time,
                    "path_write_mbps": pmb / write_time,
                    "read_mbps": pmb / core_read_time,
                    "path_read_mbps": pmb / path_read_time,
                    "mmap_peak_mb": read_peak / 1e6,
                    "mmap_rss_mb": read_rss / 1e6,
                    "sink_write_peak_mb": write_peak / 1e6,
                    "sink_write_rss_mb": write_rss / 1e6,
                }
            )
            print(
                f"{spec.id:<14}{pmb:>10.1f}{fmb:>9.1f}{pmb / write_time:>9.0f}"
                f"{pmb / core_read_time:>9.0f}{pmb / path_read_time:>9.0f}"
                f"{'-':>9}{'-':>9}{'-':>9}{read_peak / 1e6:>9.1f}"
                f"{'-':>9}{read_rss / 1e6:>9.1f}{'-':>9}"
            )
        except Exception as e:
            failures.append(spec.id)
            results.append({"codec": spec.id, "error": f"{type(e).__name__}: {e}"})
            print(f"{spec.id:<14} ERROR: {type(e).__name__}: {e}")

    assert len(specs) + len(_directory_specs()) == 23
    print("\nMB/s over raw payload; fileMB = encoded size (= the whole-file copy O1/O3 remove).")
    print("sioR = in-memory copy decode; pathR = public registry mmap read/view.")
    print("bPeakMB/mPeakMB = peak Python allocation for bytes/mmap reads (O1 delta).")
    print("bRSSMB/mRSSMB = sampled resident-set growth for bytes/mmap reads.")
    print("\nO3 write-path delta:")
    write_header = (
        f"{'codec':<18}{'payloadMB':>10}{'fileMB':>9}{'bytesW':>9}{'sinkW':>9}"
        f"{'bPeakMB':>9}{'sPeakMB':>9}{'bRSSMB':>9}{'sRSSMB':>9}"
    )
    print(write_header)
    print("-" * len(write_header))
    for row in write_rows:
        codec_id, pmb, fmb, bufw, sinkw, bpeak, speak, brss, srss = row
        print(
            f"{codec_id:<18}{pmb:>10.1f}{fmb:>9.1f}"
            f"{(f'{bufw:.0f}' if bufw is not None else '-'):>9}"
            f"{sinkw:>9.0f}"
            f"{(f'{bpeak:.1f}' if bpeak is not None else '-'):>9}"
            f"{speak:>9.1f}"
            f"{(f'{brss:.1f}' if brss is not None else '-'):>9}"
            f"{srss:>9.1f}"
        )
    print("bytesW/sinkW = legacy bytes+file/public file-sink write MB/s.")
    print("bPeakMB/sPeakMB = peak Python allocation for bytes/file-sink writes (O3 delta).")
    print("bRSSMB/sRSSMB = sampled resident-set growth for bytes/file-sink writes.")
    print("\nO4 one-lane/old-setting delta:")
    o4_header = (
        f"{'codec':<12}{'operation':<18}{'base MB/s':>12}"
        f"{'opt MB/s':>12}{'gain':>9}{'identity':>11}"
    )
    print(o4_header)
    print("-" * len(o4_header))
    for codec_id, operation, base, optimized, identity in o4_rows:
        print(
            f"{codec_id:<12}{operation:<18}{base:>12.0f}"
            f"{optimized:>12.0f}{optimized / base:>8.2f}x"
            f"{identity:>11}"
        )
    print(
        "Identity is encoded bytes where compression settings are unchanged; "
        "otherwise decoded values/pixels."
    )
    if args.require_o4_gains:
        guarded = {
            ("webp", "balanced-config"),
            ("webp", "workers-palette"),
            ("xyz", "format-write"),
            ("las", "points-write"),
            ("las", "points-read"),
        }
        measured = {
            (codec_id, operation): (base, optimized)
            for codec_id, operation, base, optimized, _ in o4_rows
        }
        for key in sorted(guarded):
            base, optimized = measured[key]
            if optimized <= base:
                failures.append(f"o4-regression:{key[0]}:{key[1]}")

        for result in results:
            if "error" in result or "bytes_peak_mb" not in result:
                continue
            bytes_peak = result["bytes_peak_mb"]
            mmap_peak = result["mmap_peak_mb"]
            if bytes_peak >= 0.5 and mmap_peak >= bytes_peak * 0.25:
                failures.append(
                    f"mmap-memory-regression:{result['codec']}"
                )
            bytes_write_peak = result["bytes_write_peak_mb"]
            sink_write_peak = result["sink_write_peak_mb"]
            if (
                bytes_write_peak >= 0.5
                and sink_write_peak >= bytes_write_peak * 0.25
            ):
                failures.append(
                    f"sink-memory-regression:{result['codec']}"
                )
        if not failures:
            print(
                "CI regression guard: stable O4 gains and mmap/sink memory "
                "bounds passed."
            )
    if args.cold_cache and not (
        hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED")
    ):
        print("WARNING: this platform has no POSIX_FADV_DONTNEED; cold-cache hint was unavailable.")
    return failures, results


if __name__ == "__main__":
    main()
