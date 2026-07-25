"""Lazy image-directory sequence parity, ordering, and bounded-copy tests."""

from __future__ import annotations

import gc
import json
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import _image_sequence as adapter


def _pgm(values: np.ndarray) -> bytes:
    values = np.asarray(values, np.uint8)
    height, width = values.shape
    return f"P5\n{width} {height}\n255\n".encode("ascii") + values.tobytes()


def _write_frames(directory: Path, names: list[str], *, shape=(3, 4)):
    directory.mkdir()
    payloads = {}
    for index, name in enumerate(names):
        values = (
            np.arange(shape[0] * shape[1], dtype=np.uint8).reshape(shape)
            + index * 17
        )
        payloads[name] = _pgm(values)
        (directory / name).write_bytes(payloads[name])
    return payloads


def _path_record(
    paths: list[Path],
    names: list[str],
    *,
    timestamps: np.ndarray | None = None,
    durations: np.ndarray | None = None,
    height: int = 3,
    width: int = 4,
):
    empty = np.empty(0, np.int64)
    return _core.image_sequence_paths(
        [str(path) for path in paths],
        names,
        empty if timestamps is None else timestamps,
        empty if durations is None else durations,
        height,
        width,
        1,
        "uint8",
        "gray",
        "none",
    )


def test_unmanifested_directory_uses_deterministic_natural_order(tmp_path):
    directory = tmp_path / "frames"
    payloads = _write_frames(
        directory,
        ["frame10.pgm", "frame2.pgm", "frame1.pgm"],
    )
    (directory / "notes.txt").write_text("ignored", encoding="utf-8")

    sequence = sceneio.read(directory, format="image_sequence")
    assert isinstance(sequence, sceneio.ImageSequence)
    assert sequence.storage_mode == "encoded_paths"
    assert sequence.frame_names == [
        "frame1.pgm",
        "frame2.pgm",
        "frame10.pgm",
    ]
    assert all(Path(value).is_absolute() for value in sequence.frame_paths)
    assert (sequence.num_frames, sequence.height, sequence.width) == (3, 3, 4)
    assert sequence.channels == 1
    assert sequence.frame_dtype == "uint8"
    assert not sequence.has_timing
    assert sequence.y.shape == (0, 0, 0)

    # Frames remain encoded and independently readable through their owned paths.
    for name, path in zip(
        sequence.frame_names, sequence.frame_paths, strict=True
    ):
        assert Path(path).read_bytes() == payloads[name]
        assert sceneio.read(path).pixels.tobytes() == payloads[name][-12:]


def test_manifest_order_exact_timing_inspect_and_partial(tmp_path):
    directory = tmp_path / "timed"
    payloads = _write_frames(directory, ["a.pgm", "b.pgm", "c.pgm"])
    document = {
        "sceneio_image_sequence": 1,
        "frames": [
            {"file": "c.pgm", "timestamp_ns": 100, "duration_ns": 40},
            {"file": "a.pgm", "timestamp_ns": 140, "duration_ns": 41},
            {"file": "b.pgm", "timestamp_ns": 181, "duration_ns": 39},
        ],
    }
    (directory / "sceneio_sequence.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )

    assert sceneio.detect(directory) == "image_sequence"
    sequence = sceneio.read(directory)
    assert sequence.frame_names == ["c.pgm", "a.pgm", "b.pgm"]
    assert sequence.timestamps_ns.tolist() == [100, 140, 181]
    assert sequence.durations_ns.tolist() == [40, 41, 39]
    assert sequence.has_timing
    for name, path in zip(
        sequence.frame_names, sequence.frame_paths, strict=True
    ):
        assert Path(path).read_bytes() == payloads[name]

    info = sceneio.inspect(directory)
    assert info.format == "image_sequence"
    assert info.datatype == "image_sequence"
    assert info.shape == (3, 3, 4, 1)
    assert info.dtype == "uint8"
    assert info.count == 3
    assert info.channels == 1
    assert info.metadata == {
        "storage_mode": "encoded_paths",
        "has_timing": True,
        "manifest": True,
        "frame_names": ("c.pgm", "a.pgm", "b.pgm"),
    }

    selected = sceneio.read_partial(directory, frames=(1, 3))
    assert selected.frame_names == ["a.pgm", "b.pgm"]
    assert selected.timestamps_ns.tolist() == [140, 181]
    assert selected.durations_ns.tolist() == [41, 39]


def test_directory_write_copies_encoded_bytes_and_is_deterministic(tmp_path):
    source = tmp_path / "source"
    payloads = _write_frames(source, ["f1.pgm", "f2.pgm"])
    sequence = _path_record(
        [source / "f1.pgm", source / "f2.pgm"],
        ["f1.pgm", "f2.pgm"],
        timestamps=np.array([0, 50], np.int64),
        durations=np.array([50, 50], np.int64),
    )

    destination = tmp_path / "output"
    sceneio.write(sequence, destination)
    assert sceneio.detect(destination) == "image_sequence"
    assert (destination / "f1.pgm").read_bytes() == payloads["f1.pgm"]
    assert (destination / "f2.pgm").read_bytes() == payloads["f2.pgm"]
    assert (destination / "sceneio_sequence.json").read_text(
        encoding="utf-8"
    ) == (
        '{"frames":[{"duration_ns":50,"file":"f1.pgm","timestamp_ns":0},'
        '{"duration_ns":50,"file":"f2.pgm","timestamp_ns":50}],'
        '"sceneio_image_sequence":1}\n'
    )
    decoded = sceneio.read(destination)
    assert decoded.frame_names == sequence.frame_names
    assert decoded.timestamps_ns.tolist() == [0, 50]

    # Replacing an existing output removes stale files and keeps source bytes.
    (destination / "stale.txt").write_text("old", encoding="utf-8")
    sceneio.write(sequence, destination)
    assert not (destination / "stale.txt").exists()
    assert (source / "f1.pgm").read_bytes() == payloads["f1.pgm"]


def test_rewriting_the_same_directory_stages_all_reads_before_replace(tmp_path):
    directory = tmp_path / "frames"
    payloads = _write_frames(directory, ["a.pgm", "b.pgm"])
    sequence = sceneio.read(directory, format="image_sequence")
    sceneio.write(sequence, directory, format="image_sequence")
    assert (directory / "a.pgm").read_bytes() == payloads["a.pgm"]
    assert (directory / "b.pgm").read_bytes() == payloads["b.pgm"]
    assert sceneio.detect(directory) == "image_sequence"


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {"sceneio_image_sequence": 2, "frames": [{"file": "a.pgm"}]},
        {"sceneio_image_sequence": 1, "frames": []},
        {
            "sceneio_image_sequence": 1,
            "frames": [{"file": "a.pgm"}],
            "extra": 1,
        },
        {
            "sceneio_image_sequence": 1,
            "frames": [{"file": "../a.pgm"}],
        },
        {
            "sceneio_image_sequence": 1,
            "frames": [{"file": "a.txt"}],
        },
        {
            "sceneio_image_sequence": 1,
            "frames": [{"file": "a.pgm"}, {"file": "a.pgm"}],
        },
        {
            "sceneio_image_sequence": 1,
            "frames": [
                {"file": "a.pgm", "timestamp_ns": 0, "duration_ns": 1},
                {"file": "b.pgm"},
            ],
        },
        {
            "sceneio_image_sequence": 1,
            "frames": [
                {"file": "a.pgm", "timestamp_ns": True, "duration_ns": 1},
            ],
        },
        {
            "sceneio_image_sequence": 1,
            "frames": [{"file": "missing.pgm"}],
        },
    ],
)
def test_manifest_schema_and_references_are_strict(tmp_path, document):
    directory = tmp_path / "invalid"
    _write_frames(directory, ["a.pgm", "b.pgm"])
    (directory / "sceneio_sequence.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )
    with pytest.raises(sceneio.FormatError):
        sceneio.read(directory)
    with pytest.raises(sceneio.FormatError):
        sceneio.inspect(directory)


def test_invalid_json_oversized_manifest_and_heterogeneous_frames_reject(tmp_path):
    invalid = tmp_path / "invalid_json"
    _write_frames(invalid, ["a.pgm"])
    (invalid / "sceneio_sequence.json").write_text("{", encoding="utf-8")
    with pytest.raises(sceneio.FormatError, match="manifest"):
        sceneio.read(invalid)

    duplicate = tmp_path / "duplicate_json"
    _write_frames(duplicate, ["a.pgm"])
    (duplicate / "sceneio_sequence.json").write_text(
        '{"sceneio_image_sequence":1,"frames":[{"file":"a.pgm",'
        '"file":"a.pgm"}]}',
        encoding="utf-8",
    )
    with pytest.raises(sceneio.FormatError, match="duplicate manifest key"):
        sceneio.read(duplicate)

    oversized = tmp_path / "oversized"
    _write_frames(oversized, ["a.pgm"])
    (oversized / "sceneio_sequence.json").write_bytes(
        b" " * (1024 * 1024 + 1)
    )
    with pytest.raises(sceneio.FormatError, match="1 MiB"):
        sceneio.read(oversized)

    mixed = tmp_path / "mixed"
    _write_frames(mixed, ["a.pgm"], shape=(3, 4))
    (mixed / "b.pgm").write_bytes(_pgm(np.zeros((4, 4), np.uint8)))
    with pytest.raises(sceneio.FormatError, match="heterogeneous"):
        sceneio.read(mixed, format="image_sequence")


def test_partial_bounds_and_unsupported_directory_detection(tmp_path):
    directory = tmp_path / "frames"
    _write_frames(directory, ["a.pgm", "b.pgm"])
    with pytest.raises(sceneio.FormatError, match="no directory format"):
        sceneio.detect(directory)
    for bounds in ((0, 0), (-1, 1), (1, 3), (2, 1)):
        with pytest.raises((ValueError, sceneio.FormatError)):
            sceneio.read_partial(
                directory,
                frames=bounds,
                format="image_sequence",
            )


def test_writer_guards_storage_empty_and_referenced_metadata(tmp_path):
    output = tmp_path / "output"
    empty = np.empty(0, np.int64)
    with pytest.raises(sceneio.FormatError, match="at least one"):
        sceneio.write(
            _core.image_sequence_paths(
                [],
                [],
                empty,
                empty,
                0,
                0,
                1,
                "uint8",
                "gray",
                "none",
            ),
            output,
            format="image_sequence",
        )

    y = np.zeros((1, 2, 2), np.uint8)
    with pytest.raises(sceneio.FormatError, match="encoded paths"):
        sceneio.write(
            _core.image_sequence_yuv(
                y,
                None,
                None,
                empty,
                empty,
                "mono",
                "none",
                "unknown",
                "unknown",
                "progressive",
                25,
                1,
                1,
                1,
            ),
            output,
            format="image_sequence",
        )

    source = tmp_path / "source"
    _write_frames(source, ["a.pgm"])
    wrong_shape = _path_record(
        [source / "a.pgm"],
        ["a.pgm"],
        height=9,
        width=9,
    )
    with pytest.raises(sceneio.FormatError, match="metadata disagrees"):
        sceneio.write(wrong_shape, output, format="image_sequence")


def test_failed_staging_preserves_existing_destination(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _write_frames(source, ["a.pgm", "b.pgm"])
    sequence = _path_record(
        [source / "a.pgm", source / "b.pgm"],
        ["a.pgm", "b.pgm"],
    )
    destination = tmp_path / "destination"
    destination.mkdir()
    sentinel = destination / "existing.txt"
    sentinel.write_text("keep", encoding="utf-8")

    original = adapter._copy_file
    calls = 0

    def fail_second(source_path, destination_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected copy failure")
        original(source_path, destination_path)

    monkeypatch.setattr(adapter, "_copy_file", fail_second)
    with pytest.raises(sceneio.FormatError, match="injected copy failure"):
        sceneio.write(sequence, destination, format="image_sequence")
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert sorted(item.name for item in destination.iterdir()) == ["existing.txt"]


def test_large_encoded_frame_copy_has_bounded_python_memory(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    frame = source / "large.pgm"
    header = b"P5\n4096 4096\n255\n"
    with frame.open("wb") as stream:
        stream.write(header)
        stream.truncate(len(header) + 4096 * 4096)
    sequence = _path_record(
        [frame],
        ["large.pgm"],
        height=4096,
        width=4096,
    )

    gc.collect()
    tracemalloc.start()
    try:
        sceneio.write(
            sequence,
            tmp_path / "output",
            format="image_sequence",
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024
    assert (tmp_path / "output" / "large.pgm").stat().st_size == frame.stat().st_size
