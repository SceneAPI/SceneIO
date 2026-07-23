"""bench/bench_io.py — O0 baseline harness for docs/io_optimization_plan.md.

Measures, per codec, encode (write) + decode (read) throughput (MB/s over the raw
payload) and peak Python allocation (tracemalloc), for sceneio._core vs the oracle
library where one exists, on representative in-memory payloads. The read-peak is
measured on the FULL path (Path.read_bytes -> decode), so it captures the
whole-file `bytes` copy that O1 (mmap) targets; the encoded size is the write-peak
the writer materializes (the O3 target). Oracle failures degrade to "-" so the
sceneio baseline always prints.

Run:  python bench/bench_io.py [--runs N] [--scale S]
It writes/reads through temp files only for the read-peak measurement; throughput
is timed in memory to keep disk noise out of the codec numbers.
"""

from __future__ import annotations

import argparse
import io
import os
import statistics
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

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
        return fn()
    except Exception:
        return None


# --- payload builders -------------------------------------------------------
def _img_u8(h, w):
    a = np.random.default_rng(0).integers(0, 256, (h, w, 3), dtype=np.uint8)
    return _core.image(a, color_space="srgb"), a


def _img_f32(h, w):
    a = (np.random.default_rng(0).random((h, w, 3), dtype=np.float32) * 10.0).astype(np.float32)
    return _core.image(a, color_space="linear"), a


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
    return _core.gaussian_cloud(f(n, 3), f(n, 3), f(n, 4), f(n), f(n, 3)), None


# --- codec specs: (id, build, sio_write, sio_read, oracle_write, oracle_read, payload_bytes) ---
@dataclass
class Spec:
    id: str
    make: Callable
    w: Callable          # record -> bytes
    r: Callable          # bytes -> record
    ow: Callable | None  # oracle: payload -> bytes
    orr: Callable | None  # oracle: bytes -> obj
    nbytes: Callable     # (record, payload) -> logical payload bytes


def _pil_w(mode):
    def enc(a):
        b = io.BytesIO()
        PILImage.fromarray(a).save(b, mode, lossless=True) if mode == "WEBP" else PILImage.fromarray(a).save(b, mode)
        return b.getvalue()
    return enc


def _pil_r(data):
    return np.asarray(PILImage.open(io.BytesIO(data)))


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


SPECS = [
    Spec("png", lambda: _img_u8(1024, 1024), _core.write_png, _core.read_png,
         (_pil_w("PNG") if PILImage else None), (_pil_r if PILImage else None),
         lambda rec, p: p.nbytes),
    Spec("jpeg", lambda: _img_u8(1024, 1024), lambda im: _core.write_jpeg(im, 95), _core.read_jpeg,
         (_pil_w("JPEG") if PILImage else None), (_pil_r if PILImage else None),
         lambda rec, p: p.nbytes),
    Spec("webp", lambda: _img_u8(1024, 1024), lambda im: _core.write_webp(im, True), _core.read_webp,
         (_pil_w("WEBP") if PILImage else None), (_pil_r if PILImage else None),
         lambda rec, p: p.nbytes),
    Spec("hdr", lambda: _img_f32(1024, 1024), _core.write_hdr, _core.read_hdr, None, None,
         lambda rec, p: p.nbytes),
    Spec("exr", lambda: _img_f32(1024, 1024), _core.write_exr, _core.read_exr, None, None,
         lambda rec, p: p.nbytes),
    Spec("netpbm", lambda: _img_u8(1024, 1024), lambda im: _core.write_netpbm(im, False), _core.read_netpbm,
         None, None, lambda rec, p: p.nbytes),
    Spec("xyz", lambda: _pc(1_000_000, False), _core.write_xyz, _core.read_xyz, None, None,
         lambda rec, p: p.nbytes),
    Spec("las", lambda: _pc(1_000_000, True), lambda pc: _core.write_las(pc, 0.001), _core.read_las,
         (_laspy_w if laspy else None), (_laspy_r if laspy else None),
         lambda rec, p: p.nbytes),
    Spec("gaussian_ply", lambda: _gauss(200_000), _core.write_gaussian_ply, _core.read_gaussian_ply,
         None, None, lambda rec, p: rec.num_gaussians * 14 * 4),
    Spec("spz", lambda: _gauss(200_000), _core.write_spz, _core.read_spz, None, None,
         lambda rec, p: rec.num_gaussians * 14 * 4),
    Spec("splat", lambda: _gauss(200_000), _core.write_splat, _core.read_splat, None, None,
         lambda rec, p: rec.num_gaussians * 14 * 4),
    Spec("npy", lambda: (lambda a: (a, a))(np.ascontiguousarray(np.random.default_rng(0).random((512, 512, 8), dtype=np.float32))),
         _core.write_npy, _core.read_npy, _np_w, _np_r,
         lambda rec, p: rec.nbytes),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=7)
    args = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="sceneio_bench_")

    hdr = f"{'codec':<14}{'payloadMB':>10}{'fileMB':>9}{'sioW':>9}{'sioR':>9}{'oraW':>9}{'oraR':>9}{'rPeakMB':>9}{'sio/ora':>9}"
    print(hdr)
    print("-" * len(hdr))
    for s in SPECS:
        try:
            rec, payload = s.make()
            enc = bytes(s.w(rec))
            pbytes = s.nbytes(rec, payload)
            pmb = pbytes / 1e6
            fmb = len(enc) / 1e6

            wt, _ = _measure(lambda: s.w(rec), args.runs)
            rt, _ = _measure(lambda: s.r(enc), args.runs)
            sioW, sioR = pmb / wt, pmb / rt

            # read-peak on the FULL path (read_bytes -> decode): captures the O1 target
            fp = os.path.join(tmp, f"{s.id}.bin")
            with open(fp, "wb") as fh:
                fh.write(enc)

            def _full_read(fp=fp, r=s.r):
                with open(fp, "rb") as fh:
                    return r(fh.read())

            _, rpeak = _measure(_full_read, args.runs)

            oraW = oraR = None
            if s.ow and payload is not None:
                ob = _try(lambda: bytes(s.ow(payload)))
                if ob is not None:
                    m = _try(lambda: _measure(lambda: s.ow(payload), args.runs))
                    oraW = pmb / m[0] if m else None
                    mr = _try(lambda: _measure(lambda: s.orr(ob), args.runs))
                    oraR = pmb / mr[0] if mr else None

            ratio = (sioR / oraR) if oraR else None
            print(f"{s.id:<14}{pmb:>10.1f}{fmb:>9.1f}{sioW:>9.0f}{sioR:>9.0f}"
                  f"{(oraW if oraW else 0):>9.0f}{(oraR if oraR else 0):>9.0f}"
                  f"{rpeak/1e6:>9.1f}{(ratio if ratio else 0):>9.2f}")
        except Exception as e:
            print(f"{s.id:<14} ERROR: {type(e).__name__}: {e}")
    print("\nMB/s over raw payload; fileMB = encoded size (= the whole-file copy O1/O3 remove).")
    print("rPeakMB = peak Python alloc on read_bytes->decode (should track fileMB -> O1 target).")


if __name__ == "__main__":
    main()
