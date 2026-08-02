"""Direct Pillow/libavif comparison provider for path-native AVIF I/O."""

from __future__ import annotations

import numpy as np

try:
    from PIL import Image, features

    AVIF_AVAILABLE = features.check_module("avif")
except (ImportError, ModuleNotFoundError):
    Image = None
    AVIF_AVAILABLE = False


def _avif_oracle_write(payload, path) -> None:
    image = Image.fromarray(np.asarray(payload, np.uint8), "RGB")
    image.save(
        path,
        "AVIF",
        quality=90,
        speed=6,
        subsampling="4:4:4",
        range="full",
        autotiling=True,
    )


def _avif_oracle_read(path):
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB")).copy()


def _animated_avif_oracle_write(payload, path) -> None:
    frames = [Image.fromarray(frame, "RGBA") for frame in payload["frames"]]
    frames[0].save(
        path,
        "AVIF",
        save_all=True,
        append_images=frames[1:],
        duration=(np.asarray(payload["durations_ns"]) // 1_000_000).tolist(),
        quality=90,
        speed=6,
        subsampling="4:4:4",
        range="full",
        autotiling=True,
    )


def _animated_avif_oracle_read(path):
    return _animated_avif_oracle_read_range(path, 0, None)


def _animated_avif_oracle_inspect(path):
    with Image.open(path) as image:
        return {
            "shape": (
                int(image.n_frames),
                int(image.height),
                int(image.width),
                len(image.getbands()),
            ),
            "count": int(image.n_frames),
        }


def _animated_avif_oracle_read_range(path, start, stop):
    with Image.open(path) as image:
        frames = []
        timestamps_ns = []
        durations_ns = []
        end = int(image.n_frames) if stop is None else int(stop)
        for index in range(int(start), end):
            image.seek(index)
            frames.append(np.asarray(image.convert("RGBA")).copy())
            timestamps_ns.append(int(image.info["timestamp"]) * 1_000_000)
            durations_ns.append(int(image.info["duration"]) * 1_000_000)
    return {
        "frames": np.stack(frames),
        "timestamps_ns": np.asarray(timestamps_ns, np.int64),
        "durations_ns": np.asarray(durations_ns, np.int64),
    }


__all__ = [
    "AVIF_AVAILABLE",
    "_animated_avif_oracle_inspect",
    "_animated_avif_oracle_read",
    "_animated_avif_oracle_read_range",
    "_animated_avif_oracle_write",
    "_avif_oracle_read",
    "_avif_oracle_write",
]
