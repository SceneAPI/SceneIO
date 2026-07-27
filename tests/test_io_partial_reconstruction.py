"""Reconstruction-family O5 partial-read behavior coverage."""

from __future__ import annotations

import gc
import json
import os
import struct
import subprocess
import sys
import tracemalloc
from statistics import median

import numpy as np
import pytest
from _support.partial_read import _fresh_process_partial_rss

import sceneio
from sceneio import _core
from sceneio.io import FormatError


def _three_view_reconstruction():
    return _core.read_nvm(
        b"NVM_V3\n3\n"
        b"a.jpg 800 1 0 0 0 0 0 0 0 0\n"
        b"b.jpg 810 1 0 0 0 1 2 3 0 0\n"
        b"c.jpg 820 1 0 0 0 4 5 6 0 0\n"
        b"1\n1.5 -2.5 3.5 10 20 30 3 "
        b"0 0 4.5 -5.5 1 0 6.5 -7.5 2 0 8.5 -9.5\n0\n"
    )


@pytest.mark.parametrize("format_id", ["colmap_sparse", "colmap_sparse_txt"])
def test_single_colmap_image_equals_full_image_slice(tmp_path, format_id):
    directory = tmp_path / format_id
    directory.mkdir()
    source = _three_view_reconstruction()
    writer = (
        _core.write_colmap_sparse
        if format_id == "colmap_sparse"
        else _core.write_colmap_txt
    )
    writer(source, str(directory))
    full = sceneio.read(directory, format=format_id)
    for row in range(full.num_images):
        image_id = int(np.asarray(full.image_ids)[row])
        partial = sceneio.read_partial(
            directory, format=format_id, image_id=image_id
        )
        assert (
            partial.num_cameras,
            partial.num_images,
            partial.num_points3D,
        ) == (1, 1, 0)
        assert (
            partial.quaternion_order,
            partial.pose_convention,
        ) == (
            full.quaternion_order,
            full.pose_convention,
        )
        assert partial.image_names == [full.image_names[row]]
        np.testing.assert_array_equal(
            np.asarray(partial.image_ids),
            np.asarray(full.image_ids)[row : row + 1],
        )
        np.testing.assert_array_equal(
            np.asarray(partial.quaternions),
            np.asarray(full.quaternions)[row : row + 1],
        )
        np.testing.assert_array_equal(
            np.asarray(partial.translations),
            np.asarray(full.translations)[row : row + 1],
        )
        np.testing.assert_array_equal(
            np.asarray(partial.image_camera_ids),
            np.asarray(full.image_camera_ids)[row : row + 1],
        )
        camera = partial.cameras[0]
        expected_camera = next(
            item
            for item in full.cameras
            if item.id == int(np.asarray(full.image_camera_ids)[row])
        )
        assert (
            camera.id,
            camera.model_id,
            camera.width,
            camera.height,
        ) == (
            expected_camera.id,
            expected_camera.model_id,
            expected_camera.width,
            expected_camera.height,
        )
        np.testing.assert_array_equal(
            np.asarray(camera.params), np.asarray(expected_camera.params)
        )


def test_single_colmap_image_rejects_unknown_id(tmp_path):
    directory = tmp_path / "model"
    directory.mkdir()
    _core.write_colmap_sparse(_three_view_reconstruction(), str(directory))
    with pytest.raises(FormatError, match="image id 4294967295 not found"):
        sceneio.read_partial(
            directory, format="colmap_sparse", image_id=0xFFFFFFFF
        )
    with pytest.raises(ValueError, match=r"0\.\.4294967295"):
        sceneio.read_partial(directory, format="colmap_sparse", image_id=-1)


@pytest.mark.parametrize("format_id", ["colmap_sparse", "colmap_sparse_txt"])
def test_single_colmap_image_does_not_open_the_point_container(
    tmp_path, format_id
):
    directory = tmp_path / format_id
    directory.mkdir()
    source = _three_view_reconstruction()
    if format_id == "colmap_sparse":
        _core.write_colmap_sparse(source, str(directory))
        (directory / "points3D.bin").unlink()
    else:
        _core.write_colmap_txt(source, str(directory))
        (directory / "points3D.txt").unlink()
    partial = sceneio.read_partial(directory, format=format_id, image_id=1)
    assert (partial.num_images, partial.num_points3D) == (1, 0)


@pytest.mark.parametrize("format_id", ["colmap_sparse", "colmap_sparse_txt"])
def test_single_colmap_image_skips_unselected_names_over_one_mib(
    tmp_path, format_id
):
    directory = tmp_path / format_id
    directory.mkdir()
    source = _three_view_reconstruction()
    long_name = b"x" * (1024 * 1024 + 17)
    if format_id == "colmap_sparse":
        _core.write_colmap_sparse(source, str(directory))
        images_path = directory / "images.bin"
        encoded = images_path.read_bytes()
        name_start = 8 + 4 + 4 * 8 + 3 * 8 + 4
        name_end = encoded.index(b"\0", name_start)
        images_path.write_bytes(
            encoded[:name_start] + long_name + encoded[name_end:]
        )
    else:
        _core.write_colmap_txt(source, str(directory))
        images_path = directory / "images.txt"
        encoded = images_path.read_bytes()
        images_path.write_bytes(encoded.replace(b"a.jpg", long_name, 1))

    # The full reader establishes that this is a valid accepted name. The
    # partial reader must skip it without allocating or imposing a new limit.
    full = sceneio.read(directory, format=format_id)
    long_id = int(np.asarray(full.image_ids)[0])
    selected = sceneio.read_partial(
        directory, format=format_id, image_id=long_id
    )
    assert selected.image_names == [full.image_names[0]]
    target_id = int(np.asarray(full.image_ids)[1])
    partial = sceneio.read_partial(
        directory, format=format_id, image_id=target_id
    )
    assert partial.image_names == [full.image_names[1]]


def _fresh_process_colmap_error_rss(
    path,
    format_id,
    image_id,
    *,
    warm_path,
    mode="sceneio",
    repeats=3,
):
    if os.environ.get("ASAN_OPTIONS") or "libasan" in os.environ.get(
        "LD_PRELOAD", ""
    ):
        pytest.skip("RSS measurements include AddressSanitizer shadow memory")
    script = """
import gc
import json
import sys
import threading
import time
from pathlib import Path

import psutil
import sceneio

process = psutil.Process()
control_headroom = 0

def high_water_rss():
    memory = process.memory_info()
    peak_wset = getattr(memory, "peak_wset", None)
    if peak_wset is not None:
        return peak_wset
    try:
        import resource
    except ImportError:
        return memory.rss
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024

def sceneio_error(target):
    try:
        sceneio.read_partial(
            target, format=sys.argv[2], image_id=int(sys.argv[3])
        )
    except sceneio.FormatError:
        return
    raise AssertionError("malformed model unexpectedly decoded")

def operation():
    if sys.argv[5] == "allocate":
        payload_size = (Path(sys.argv[1]) / "images.bin").stat().st_size
        value = bytearray(control_headroom + payload_size)
        for offset in range(0, len(value), 4096):
            value[offset] = 1
        if value:
            value[-1] = 1
        del value
        return
    sceneio_error(sys.argv[1])

# Warm lazy imports, native dispatch, filesystem metadata, and allocator pools
# with a fixed tiny malformed fixture. The first size-dependent operation is
# always inside the measured window.
sceneio_error(sys.argv[4])
process.memory_info()
gc.collect()
baseline = process.memory_info().rss
baseline_high_water = high_water_rss()
# Make the transient control clear any high-water established by imports, then
# add exactly one file-controlled extent above it.
control_headroom = max(0, baseline_high_water - baseline)
peak = [baseline]
running = [True]

def sample():
    while running[0]:
        peak[0] = max(peak[0], process.memory_info().rss)
        time.sleep(0.0005)

thread = threading.Thread(target=sample, daemon=True)
thread.start()
try:
    operation()
    peak[0] = max(peak[0], process.memory_info().rss)
finally:
    running[0] = False
    thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("RSS sampler thread did not stop")
peak_current = peak[0]
peak_high_water = high_water_rss()
current_delta = max(0, peak_current - baseline)
high_water_delta = max(0, peak_high_water - baseline_high_water)
print(json.dumps({
    "baseline": baseline,
    "baseline_high_water": baseline_high_water,
    "peak_current": peak_current,
    "peak_high_water": peak_high_water,
    "current_delta": current_delta,
    "high_water_delta": high_water_delta,
    "delta": max(current_delta, high_water_delta),
}))
"""
    measurements = []
    for _ in range(repeats):
        command = [
            sys.executable,
            "-c",
            script,
            str(path),
            format_id,
            str(image_id),
            str(warm_path),
            mode,
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            pytest.fail(
                "RSS child timed out: "
                f"mode={mode}, path={path}, warm_path={warm_path}, "
                f"stdout={exc.stdout!r}, stderr={exc.stderr!r}"
            )
        measurements.append(json.loads(completed.stdout))
    return measurements


def _assert_payload_relative_rss(
    small_size,
    small_measurements,
    large_size,
    large_measurements,
    *,
    metric="delta",
):
    small_delta = median(item[metric] for item in small_measurements)
    large_delta = median(item[metric] for item in large_measurements)
    payload_growth = large_size - small_size
    measured_growth = max(0, large_delta - small_delta)
    assert measured_growth < payload_growth // 4, (
        "payload-relative RSS growth is too steep: "
        f"metric={metric}, "
        f"sizes=({small_size}, {large_size}), "
        f"deltas=({small_delta}, {large_delta}), "
        f"samples=({small_measurements}, {large_measurements})"
    )


def _assert_colmap_error_rss_is_sublinear(
    cases,
    format_id,
    image_id,
    *,
    warm_path,
):
    assert len(cases) == 2
    sceneio_measurements = [
        (
            size,
            _fresh_process_colmap_error_rss(
                path,
                format_id,
                image_id,
                warm_path=warm_path,
            ),
        )
        for size, path in cases
    ]
    _assert_payload_relative_rss(
        sceneio_measurements[0][0],
        sceneio_measurements[0][1],
        sceneio_measurements[1][0],
        sceneio_measurements[1][1],
    )

    allocation_controls = [
        (
            size,
            _fresh_process_colmap_error_rss(
                path,
                format_id,
                image_id,
                warm_path=warm_path,
                mode="allocate",
            ),
        )
        for size, path in cases
    ]
    with pytest.raises(
        AssertionError,
        match="payload-relative RSS growth is too steep",
    ):
        _assert_payload_relative_rss(
            allocation_controls[0][0],
            allocation_controls[0][1],
            allocation_controls[1][0],
            allocation_controls[1][1],
            metric="high_water_delta",
        )


def _traced_format_error_peak(operation, *, match):
    gc.collect()
    tracemalloc.start()
    try:
        with pytest.raises(FormatError, match=match):
            operation()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


def test_colmap_text_skips_unselected_large_observation_line_bounded(
    tmp_path,
):
    directory = tmp_path / "large-text-model"
    directory.mkdir()
    (directory / "cameras.txt").write_text(
        "1 PINHOLE 640 480 500 500 320 240\n"
        "2 PINHOLE 640 480 500 500 320 240\n",
        encoding="utf-8",
    )
    images = directory / "images.txt"
    with images.open("wb") as stream:
        stream.write(b"1 1 0 0 0 0 0 0 1 first.jpg\n")
        stream.seek(64 * 1024 * 1024, 1)
        stream.write(b"\n2 1 0 0 0 0 0 0 2 second.jpg\n\n")
    partial = sceneio.read_partial(
        directory, format="colmap_sparse_txt", image_id=2
    )
    assert partial.image_names == ["second.jpg"]
    assert partial.num_points3D == 0
    assert (
        _fresh_process_partial_rss(
            directory, "colmap_sparse_txt", "partial"
        )
        < 16 * 1024 * 1024
    )


def _write_malformed_observation_model(tmp_path, label, payload_size):
    source = _three_view_reconstruction()
    image_id = int(np.asarray(source.image_ids)[0])
    directory = tmp_path / f"malformed-binary-model-{label}"
    directory.mkdir()
    _core.write_colmap_sparse(source, str(directory))
    images_path = directory / "images.bin"
    encoded = bytearray(images_path.read_bytes())
    name_start = 8 + 4 + 4 * 8 + 3 * 8 + 4
    name_end = encoded.index(0, name_start)
    count_offset = name_end + 1
    observation_count = payload_size // 24 + 1
    encoded[count_offset : count_offset + 8] = struct.pack(
        "<Q", observation_count
    )
    del encoded[count_offset + 8 :]
    with images_path.open("wb") as stream:
        stream.write(encoded)
        stream.truncate(stream.tell() + payload_size)
    return directory, image_id, images_path.stat().st_size


def _write_unterminated_name_model(tmp_path, label, payload_size):
    source = _three_view_reconstruction()
    image_id = int(np.asarray(source.image_ids)[0])
    directory = tmp_path / f"unterminated-binary-name-{label}"
    directory.mkdir()
    _core.write_colmap_sparse(source, str(directory))
    images_path = directory / "images.bin"
    prefix = images_path.read_bytes()[: 8 + 4 + 4 * 8 + 3 * 8 + 4]
    with images_path.open("wb") as stream:
        stream.write(prefix)
        block = b"x" * 65536
        complete_blocks, remainder = divmod(payload_size, len(block))
        for _ in range(complete_blocks):
            stream.write(block)
        stream.write(block[:remainder])
    return directory, image_id, images_path.stat().st_size


def test_colmap_binary_checks_selected_observation_bytes_before_allocating(
    tmp_path,
):
    directory, image_id, _size = _write_malformed_observation_model(
        tmp_path,
        "semantic",
        64,
    )
    with pytest.raises(
        FormatError,
        match="truncated image observations",
    ):
        sceneio.read_partial(
            directory,
            format="colmap_sparse",
            image_id=image_id,
        )


def test_colmap_binary_validates_selected_name_terminator_before_allocating(
    tmp_path,
):
    directory, image_id, _size = _write_unterminated_name_model(
        tmp_path,
        "semantic",
        64,
    )
    with pytest.raises(FormatError, match="truncated image name"):
        sceneio.read_partial(
            directory,
            format="colmap_sparse",
            image_id=image_id,
        )


def _instrumented_rss_measurement():
    return bool(
        os.environ.get("ASAN_OPTIONS")
        or "libasan" in os.environ.get("LD_PRELOAD", "")
    )


@pytest.mark.skipif(
    _instrumented_rss_measurement(),
    reason="RSS measurements include AddressSanitizer shadow memory",
)
def test_colmap_observation_error_rss_growth_is_payload_relative(tmp_path):
    warm_path, image_id, _size = _write_malformed_observation_model(
        tmp_path,
        "warm",
        64,
    )
    cases = []
    for payload_size in (8 * 1024 * 1024, 32 * 1024 * 1024):
        directory, case_image_id, size = _write_malformed_observation_model(
            tmp_path,
            str(payload_size),
            payload_size,
        )
        assert case_image_id == image_id
        assert (
            _traced_format_error_peak(
                lambda directory=directory: sceneio.read_partial(
                    directory,
                    format="colmap_sparse",
                    image_id=image_id,
                ),
                match="truncated image observations",
            )
            < 1024 * 1024
        )
        cases.append((size, directory))
    _assert_colmap_error_rss_is_sublinear(
        cases,
        "colmap_sparse",
        image_id,
        warm_path=warm_path,
    )


@pytest.mark.skipif(
    _instrumented_rss_measurement(),
    reason="RSS measurements include AddressSanitizer shadow memory",
)
def test_colmap_name_error_rss_growth_is_payload_relative(tmp_path):
    warm_path, image_id, _size = _write_unterminated_name_model(
        tmp_path,
        "warm",
        64,
    )
    cases = []
    for payload_size in (8 * 1024 * 1024, 32 * 1024 * 1024):
        directory, case_image_id, size = _write_unterminated_name_model(
            tmp_path,
            str(payload_size),
            payload_size,
        )
        assert case_image_id == image_id
        assert (
            _traced_format_error_peak(
                lambda directory=directory: sceneio.read_partial(
                    directory,
                    format="colmap_sparse",
                    image_id=image_id,
                ),
                match="truncated image name",
            )
            < 1024 * 1024
        )
        cases.append((size, directory))
    _assert_colmap_error_rss_is_sublinear(
        cases,
        "colmap_sparse",
        image_id,
        warm_path=warm_path,
    )


def _write_malformed_text_token_model(tmp_path, label, payload_size):
    directory = tmp_path / f"malformed-text-model-{label}"
    directory.mkdir()
    (directory / "cameras.txt").write_text(
        "1 PINHOLE 640 480 500 500 320 240\n",
        encoding="utf-8",
    )
    images_path = directory / "images.txt"
    with images_path.open("wb") as stream:
        stream.write(b"1 1 0 0 0 0 0 0 1 image.jpg\n")
        stream.seek(payload_size, 1)
        stream.write(b"x\n")
    (directory / "points3D.txt").write_bytes(b"")
    return directory


def test_colmap_text_selected_malformed_token_is_memory_bounded(tmp_path):
    warm_path = _write_malformed_text_token_model(tmp_path, "warm", 64)
    directory = _write_malformed_text_token_model(
        tmp_path,
        "measured",
        32 * 1024 * 1024,
    )
    with pytest.raises(FormatError, match="token exceeds 1 MiB"):
        sceneio.read_partial(
            directory, format="colmap_sparse_txt", image_id=1
        )
    measurements = _fresh_process_colmap_error_rss(
        directory,
        "colmap_sparse_txt",
        1,
        warm_path=warm_path,
    )
    assert (
        median(item["delta"] for item in measurements)
        # Hosted Linux allocators vary by several MiB. This remains below the
        # malformed 32 MiB token and therefore catches a whole-line mirror.
        < 24 * 1024 * 1024
    )


def test_colmap_text_oversized_numeric_token_policy_matches_full_read(
    tmp_path,
):
    directory = tmp_path / "oversized-text-token"
    directory.mkdir()
    (directory / "cameras.txt").write_text(
        "1 PINHOLE 640 480 500 500 320 240\n",
        encoding="utf-8",
    )
    (directory / "images.txt").write_bytes(
        b"1 1 0 0 0 0 0 0 1 image.jpg\n"
        + b"0" * (1024 * 1024 + 1)
        + b" 0 -1\n"
    )
    (directory / "points3D.txt").write_bytes(b"")
    for call in (
        lambda: sceneio.read(directory, format="colmap_sparse_txt"),
        lambda: sceneio.read_partial(
            directory, format="colmap_sparse_txt", image_id=1
        ),
    ):
        with pytest.raises(FormatError, match="token exceeds 1 MiB"):
            call()


def test_colmap_text_stream_skips_oversized_comment_line(tmp_path):
    directory = tmp_path / "large-text-comment"
    directory.mkdir()
    (directory / "cameras.txt").write_bytes(
        b"#" + b"x" * (2 * 1024 * 1024) + b"\n"
        b"1 PINHOLE 640 480 500 500 320 240\n"
    )
    (directory / "images.txt").write_bytes(
        b"#" + b"x" * (2 * 1024 * 1024) + b"\n"
        b"1 1 0 0 0 0 0 0 1 image.jpg\n\n"
    )
    (directory / "points3D.txt").write_bytes(b"")
    full = sceneio.read(directory, format="colmap_sparse_txt")
    partial = sceneio.read_partial(
        directory, format="colmap_sparse_txt", image_id=1
    )
    assert partial.image_names == full.image_names == ["image.jpg"]
