"""Architecture contracts for the sequence registry/inspector family."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import subprocess
import sys
import textwrap
import tomllib
import tracemalloc
from functools import partial
from pathlib import Path

import numpy as np
import pytest

import sceneio
import sceneio.io._image_sequence as sequence_adapter
import sceneio.io._rtmv as rtmv_adapter
from sceneio import _core
from sceneio.io import _inspection, registry
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._inspectors import sequences as sequence_inspector
from sceneio.io._registry.families import sequences as sequence_family

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tests" / "contracts" / "io_sequence_inspection_v1.json"
SEQUENCE_IDS = (
    "y4m",
    "webm",
    "ivf",
    "mjpeg",
    "mp4",
    "theora",
    "animated_webp",
    "apng",
    "animated_avif",
    "rtmv",
    "image_sequence",
)
FRAME_ACCESS_AST_NORMALIZATION = {
    "_IMAGE_FRAME_ACCESS": "__FRAME_ACCESS__",
    "frame_access": "__FRAME_ACCESS__",
}

_Y4M_FIXTURES = {
    "mono": (
        b"YUV4MPEG2 W2 H2 F25:1 Ip A1:1 Cmono\n"
        b"FRAME\n\x00\x01\x02\xff"
    ),
    "color422": (
        b"YUV4MPEG2 W3 H2 F30000:1001 It A4:3 C422 "
        b"XYSCSS=422 XCOLORRANGE=LIMITED XCOLORSPACE=BT601\n"
        b"FRAME\n"
        + bytes(range(14))
        + b"FRAME\n"
        + bytes(range(14, 28))
    ),
}

_MALFORMED_Y4M = {
    "bad_magic": b"not-y4m\n",
    "missing_aspect": b"YUV4MPEG2 W5 H3 F25:1 Ip C420jpeg\n",
}

_MANIFEST = (
    b'{"sceneio_image_sequence":2,"frame_contract":{'
    b'"height":2,"width":3,"channels":1,"dtype":"uint8",'
    b'"color_space":"gray","alpha_mode":"none","maxval":255,'
    b'"projection":"unknown","projection_canvas_width":0,'
    b'"projection_canvas_height":0,"projection_crop_left":0,'
    b'"projection_crop_top":0},"frames":['
    b'{"file":"c.pgm","timestamp_ns":100,"duration_ns":40},'
    b'{"file":"a.pgm","timestamp_ns":140,"duration_ns":41},'
    b'{"file":"b.pgm","timestamp_ns":181,"duration_ns":39}]}'
)


def _contract() -> dict[str, object]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _normalized_inspection(info) -> dict[str, object]:
    return json.loads(
        json.dumps(
            {
                "byte_size": info.byte_size,
                "shape": info.shape,
                "dtype": info.dtype,
                "count": info.count,
                "channels": info.channels,
                "arrays": [
                    {
                        "name": item.name,
                        "shape": item.shape,
                        "dtype": item.dtype,
                    }
                    for item in info.arrays
                ],
                "metadata": dict(info.metadata),
            }
        )
    )


def _sequence_summary(sequence) -> dict[str, object]:
    return {
        "frame_names": list(sequence.frame_names),
        "timestamps_ns": sequence.timestamps_ns.tolist(),
        "durations_ns": sequence.durations_ns.tolist(),
        "height": sequence.height,
        "width": sequence.width,
        "channels": sequence.channels,
        "frame_dtype": sequence.frame_dtype,
        "color_space": sequence.color_space,
        "alpha_mode": sequence.alpha_mode,
        "maxval": sequence.maxval,
        "projection": sequence.projection,
        "projection_canvas_width": sequence.projection_canvas_width,
        "projection_canvas_height": sequence.projection_canvas_height,
        "projection_crop_left": sequence.projection_crop_left,
        "projection_crop_top": sequence.projection_crop_top,
        "storage_mode": sequence.storage_mode,
    }


def _pgm(offset: int) -> bytes:
    return b"P5\n3 2\n255\n" + bytes((offset + index) % 256 for index in range(6))


def _write_directory_fixture(root: Path, mode: str) -> Path:
    directory = root / mode
    directory.mkdir()
    names = (
        ("frame10.pgm", "frame2.pgm", "frame1.pgm")
        if mode == "unmanifested"
        else ("a.pgm", "b.pgm", "c.pgm")
    )
    for index, name in enumerate(names):
        (directory / name).write_bytes(_pgm(index * 10))
    if mode == "manifested":
        (directory / "sceneio_sequence.json").write_bytes(_MANIFEST)
    return directory


def _absolute_imports_from_source(
    source: str,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    imports = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, (node.level, node.module)
            imports.append(
                (
                    node.module or "",
                    tuple(alias.name for alias in node.names),
                )
            )
    return tuple(imports)


def _assert_core_only_sceneio_import(
    imports: tuple[tuple[str, tuple[str, ...]], ...],
) -> None:
    assert tuple(
        names for module, names in imports if module == "sceneio"
    ) == (("_core",),)


def _assert_sequence_family_imports(source: str) -> None:
    imports = _absolute_imports_from_source(source)
    _assert_core_only_sceneio_import(imports)
    assert {
        module for module, _ in imports
    } <= {
        "__future__",
        "functools",
        "sceneio",
        "sceneio.io._avif",
        "sceneio.io._frame_access",
        "sceneio.io._image_sequence",
        "sceneio.io._rtmv",
        "sceneio.io._registry.adapters",
        "sceneio.io._registry.model",
    }


class _NormalizeInjectedFrameAccess(ast.NodeTransformer):
    """Make the parent facade name and extracted factory parameter comparable."""

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if node.id in FRAME_ACCESS_AST_NORMALIZATION:
            return ast.copy_location(
                ast.Name(
                    id=FRAME_ACCESS_AST_NORMALIZATION[node.id],
                    ctx=node.ctx,
                ),
                node,
            )
        return node


def _codec_ast_hashes() -> dict[str, str]:
    tree = ast.parse(inspect.getsource(sequence_family))
    calls = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Codec"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in SEQUENCE_IDS
        ):
            calls[node.args[0].value] = node
    return {
        format_id: hashlib.sha256(
            ast.dump(
                _NormalizeInjectedFrameAccess().visit(calls[format_id]),
                include_attributes=False,
            ).encode()
        ).hexdigest()
        for format_id in SEQUENCE_IDS
    }


def test_sequence_codec_ast_contract_and_canonical_installation_are_exact():
    contract = _contract()
    assert contract["parent_commit"] == "68c47d6"
    assert (
        contract["codec_ast_name_normalization"]
        == FRAME_ACCESS_AST_NORMALIZATION
    )
    assert _codec_ast_hashes() == contract["codec_ast_sha256"]

    start = CANONICAL_BUILTIN_IDS.index("y4m")
    assert CANONICAL_BUILTIN_IDS[start - 1 : start + 12] == (
        "avif",
        "y4m",
        "webm",
        "ivf",
        "mjpeg",
        "mp4",
        "theora",
        "animated_webp",
        "apng",
        "animated_avif",
        "rtmv",
        "image_sequence",
        "colmap_sparse_txt",
    )
    assert tuple(registry.REGISTRY)[start : start + 11] == SEQUENCE_IDS
    assert tuple(
        codec.id for codec in registry.BUILTIN_DEFINITIONS[start : start + 11]
    ) == SEQUENCE_IDS
    for offset, format_id in enumerate(SEQUENCE_IDS):
        assert (
            registry.REGISTRY[format_id]
            is registry.BUILTIN_DEFINITIONS[start + offset]
        )


def test_sequence_native_and_directory_callable_targets_are_exact():
    y4m = registry.REGISTRY["y4m"]
    assert y4m.record is _core.ImageSequence
    assert inspect.getclosurevars(y4m.read).nonlocals == {
        "fn": _core.read_y4m
    }
    assert inspect.getclosurevars(y4m.write).nonlocals == {
        "fn": _core.write_y4m,
        "prepare": None,
    }
    assert inspect.getclosurevars(y4m.read_frames).nonlocals == {
        "fn": _core.read_y4m_frames
    }

    webm = registry.REGISTRY["webm"]
    assert webm.record is _core.ImageSequence
    assert inspect.getclosurevars(webm.read).nonlocals == {
        "fn": _core.read_webm
    }
    assert webm.write.__name__ == "_write_webm"
    assert webm.write.__module__ == "sceneio.io._registry.families.sequences"
    assert inspect.getclosurevars(webm.write).nonlocals == {}
    assert inspect.getclosurevars(webm.read_frames).nonlocals == {
        "fn": _core.read_webm_frames
    }

    ivf = registry.REGISTRY["ivf"]
    assert ivf.record is _core.ImageSequence
    assert inspect.getclosurevars(ivf.read).nonlocals == {
        "fn": _core.read_ivf
    }
    assert ivf.write.__name__ == "_write_ivf"
    assert ivf.write.__module__ == "sceneio.io._registry.families.sequences"
    assert inspect.getclosurevars(ivf.write).nonlocals == {}
    assert inspect.getclosurevars(ivf.read_frames).nonlocals == {
        "fn": _core.read_ivf_frames
    }

    mjpeg = registry.REGISTRY["mjpeg"]
    assert mjpeg.record is _core.ImageSequence
    assert inspect.getclosurevars(mjpeg.read).nonlocals == {
        "fn": _core.read_mjpeg
    }
    assert inspect.getclosurevars(mjpeg.write).nonlocals == {
        "fn": _core.write_mjpeg,
        "prepare": None,
    }
    assert inspect.getclosurevars(mjpeg.read_frames).nonlocals == {
        "fn": _core.read_mjpeg_frames
    }

    mp4 = registry.REGISTRY["mp4"]
    assert mp4.record is _core.ImageSequence
    assert inspect.getclosurevars(mp4.read).nonlocals == {
        "fn": _core.read_mp4
    }
    assert mp4.write is None
    assert inspect.getclosurevars(mp4.read_frames).nonlocals == {
        "fn": _core.read_mp4_frames
    }

    theora = registry.REGISTRY["theora"]
    assert theora.record is _core.ImageSequence
    assert inspect.getclosurevars(theora.read).nonlocals == {
        "fn": _core.read_theora
    }
    assert inspect.getclosurevars(theora.write).nonlocals == {
        "fn": _core.write_theora,
        "prepare": None,
    }
    assert inspect.getclosurevars(theora.read_frames).nonlocals == {
        "fn": _core.read_theora_frames
    }

    animated_webp = registry.REGISTRY["animated_webp"]
    assert animated_webp.record is _core.ImageSequence
    assert inspect.getclosurevars(animated_webp.read).nonlocals == {
        "fn": _core.read_animated_webp
    }
    assert inspect.getclosurevars(animated_webp.write).nonlocals == {
        "fn": _core.write_animated_webp,
        "prepare": None,
    }

    apng = registry.REGISTRY["apng"]
    assert apng.record is _core.ImageSequence
    assert inspect.getclosurevars(apng.read).nonlocals == {
        "fn": _core.read_apng
    }
    assert inspect.getclosurevars(apng.write).nonlocals == {
        "fn": _core.write_apng,
        "prepare": None,
    }

    access = registry._IMAGE_FRAME_ACCESS
    rtmv = registry.REGISTRY["rtmv"]
    assert rtmv.record is rtmv_adapter.RtmvDataset
    assert rtmv.write is None
    for callback, target, parameters in (
        (rtmv.read, rtmv_adapter.read_rtmv_directory, ("path",)),
        (rtmv.inspect, rtmv_adapter.inspect_rtmv_directory, ("path",)),
        (
            rtmv.read_frames,
            rtmv_adapter.read_rtmv_directory_frames,
            ("path", "start", "stop"),
        ),
    ):
        assert isinstance(callback, partial)
        assert callback.func is target
        assert callback.args == (access,)
        assert callback.keywords == {}
        assert tuple(inspect.signature(callback).parameters) == parameters

    directory = registry.REGISTRY["image_sequence"]
    callbacks = (
        (
            directory.read,
            sequence_adapter.read_image_sequence_directory,
            ("path",),
        ),
        (
            directory.write,
            sequence_adapter.write_image_sequence_directory,
            ("sequence", "path"),
        ),
        (
            directory.inspect,
            sequence_adapter.inspect_image_sequence_directory,
            ("path",),
        ),
        (
            directory.read_frames,
            sequence_adapter.read_image_sequence_directory_frames,
            ("path", "start", "stop"),
        ),
    )
    for callback, target, parameters in callbacks:
        assert isinstance(callback, partial)
        assert callback.func is target
        assert callback.args == (access,)
        assert callback.keywords == {}
        assert tuple(inspect.signature(callback).parameters) == parameters
    with pytest.raises(
        TypeError,
        match="multiple values for argument 'frame_access'",
    ):
        directory.read("unused", frame_access=access)


def test_sequence_factory_is_inert_reentrant_and_binds_supplied_access():
    calls = []

    def extensions():
        calls.append("extensions")
        return frozenset()

    def inspect_frame(path):
        calls.append(path)
        raise AssertionError

    first_access = ImageFrameAccess(extensions, inspect_frame)
    second_access = ImageFrameAccess(lambda: frozenset(), inspect_frame)
    calls.clear()
    first = sequence_family.build_sequence_codecs(first_access)
    second = sequence_family.build_sequence_codecs(second_access)
    assert tuple(codec.id for codec in first) == SEQUENCE_IDS
    assert tuple(codec.id for codec in second) == SEQUENCE_IDS
    assert first[0] is second[0] is sequence_family._Y4M_CODEC
    assert (
        first[1]
        is second[1]
        is sequence_family._WEBM_CODEC
    )
    assert first[2] is second[2] is sequence_family._IVF_CODEC
    assert first[3] is second[3] is sequence_family._MJPEG_CODEC
    assert first[4] is second[4] is sequence_family._MP4_CODEC
    assert first[5] is second[5] is sequence_family._THEORA_CODEC
    assert first[6] is second[6] is sequence_family._ANIMATED_WEBP_CODEC
    assert first[7] is second[7] is sequence_family._APNG_CODEC
    assert first[8] is second[8] is sequence_family._ANIMATED_AVIF_CODEC
    assert first[9] is not second[9]
    assert first[10] is not second[10]
    assert calls == []
    for codec, access in ((first[9], first_access), (second[9], second_access)):
        for callback in (codec.read, codec.inspect, codec.read_frames):
            assert callback.args == (access,)
        assert codec.write is None
    for codec, access in ((first[10], first_access), (second[10], second_access)):
        for callback in (
            codec.read,
            codec.write,
            codec.inspect,
            codec.read_frames,
        ):
            assert callback.args == (access,)


def test_sequence_lower_modules_have_strict_dependency_direction():
    _assert_sequence_family_imports(inspect.getsource(sequence_family))
    inspector_imports = _absolute_imports_from_source(
        inspect.getsource(sequence_inspector)
    )
    _assert_core_only_sceneio_import(inspector_imports)
    assert {
        module for module, _ in inspector_imports
    } <= {
        "__future__",
        "pathlib",
        "sceneio",
        "sceneio.io._inspectors.common",
        "sceneio.io._inspectors.model",
    }
    for module in (sequence_family, sequence_inspector):
        source = inspect.getsource(module)
        assert "sceneio.io.registry" not in source
        assert "sceneio.io._inspection" not in source
        assert "REGISTRY" not in source
        assert "register(" not in source
        assert ".families." not in source


def test_sequence_lower_import_guard_rejects_upward_relative_and_siblings():
    for source in (
        "import sceneio.io",
        "from sceneio import io",
        "from sceneio import _core, io",
        "from sceneio.io import registry",
        "from sceneio.io import _inspection",
        "from sceneio.io._registry.families import images",
        "from . import sequences",
    ):
        with pytest.raises(AssertionError):
            _assert_sequence_family_imports(source)


def test_sequence_lower_inspector_uses_only_compiled_metadata_entry_points():
    source = inspect.getsource(sequence_inspector)
    assert "_core._inspect_y4m" in source
    assert "_core._inspect_webm" in source
    assert "_core._inspect_ivf" in source
    assert "_core._inspect_mjpeg" in source
    assert "_core._inspect_mp4" in source
    assert "_core._inspect_theora" in source
    assert "_core._inspect_animated_webp" in source
    assert "_core._inspect_apng" in source
    assert "_core.read_y4m" not in source
    assert "_core.write_y4m" not in source
    assert "_core.read_animated_webp" not in source
    assert "_core.write_animated_webp" not in source
    assert "_core.read_apng" not in source
    assert "_core.write_apng" not in source
    lower_only = source.replace("_core._inspect_y4m", "").replace(
        "_core._inspect_webm", ""
    ).replace(
        "_core._inspect_ivf", ""
    ).replace(
        "_core._inspect_mjpeg", ""
    ).replace(
        "_core._inspect_mp4", ""
    ).replace(
        "_core._inspect_theora", ""
    ).replace(
        "_core._inspect_animated_webp", ""
    ).replace("_core._inspect_apng", "")
    assert "_core._inspect_" not in lower_only


def test_sequence_family_and_registry_reload_keep_live_access():
    code = textwrap.dedent(
        """
        import importlib
        import tempfile
        from functools import partial
        from pathlib import Path

        from sceneio import Codec, _core
        from sceneio.io import registry
        from sceneio.io._inspectors.model import Inspection
        from sceneio.io._registry.families import sequences

        before_registry = registry.REGISTRY
        before_items = tuple(registry.REGISTRY.items())
        old_access = registry._IMAGE_FRAME_ACCESS
        old_sequence = registry.REGISTRY["image_sequence"]
        reloaded_family = importlib.reload(sequences)
        assert registry.REGISTRY is before_registry
        assert tuple(registry.REGISTRY.items()) == before_items
        assert registry._IMAGE_FRAME_ACCESS is old_access
        assert reloaded_family.build_sequence_codecs(old_access)[10] is not old_sequence

        for _ in range(2):
            registry = importlib.reload(registry)
            ids = tuple(registry.REGISTRY)
            start = ids.index("y4m")
            assert ids[start : start + 12] == (
                "y4m",
                "webm",
                "ivf",
                "mjpeg",
                "mp4",
                "theora",
                "animated_webp",
                "apng",
                "animated_avif",
                "rtmv",
                "image_sequence",
                "colmap_sparse_txt",
            )
            sequence = registry.REGISTRY["image_sequence"]
            access = registry._IMAGE_FRAME_ACCESS
            assert access is not old_access
            for callback in (
                sequence.read,
                sequence.write,
                sequence.inspect,
                sequence.read_frames,
            ):
                assert isinstance(callback, partial)
                assert callback.args == (access,)

        def inspect_frame(path):
            return Inspection(
                format="sequence-probe",
                payload_kind="image",
                byte_size=Path(path).stat().st_size,
                shape=(2, 3, 1),
                dtype="uint8",
                channels=1,
            )

        probe = Codec(
            "sequence-probe",
            (".seqprobe",),
            lambda path: path,
            lambda record, path: None,
            record=_core.Image,
            payload_kind="image",
            inspect=inspect_frame,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "frame.seqprobe").write_bytes(b"frame")
            (source / "sceneio_sequence.json").write_text(
                '{"sceneio_image_sequence":2,"frame_contract":{'
                '"height":2,"width":3,"channels":1,"dtype":"uint8",'
                '"color_space":"gray","alpha_mode":"none","maxval":255,'
                '"projection":"unknown","projection_canvas_width":0,'
                '"projection_canvas_height":0,"projection_crop_left":0,'
                '"projection_crop_top":0},'
                '"frames":[{"file":"frame.seqprobe"}]}',
                encoding="utf-8",
            )
            registry.register(probe)
            try:
                assert ".seqprobe" in old_access.image_extensions()
                assert ".seqprobe" in access.image_extensions()
                for index, codec in enumerate((old_sequence, sequence)):
                    record = codec.read(str(source))
                    assert record.frame_names == ["frame.seqprobe"]
                    assert codec.inspect(str(source)).shape == (1, 2, 3, 1)
                    assert codec.read_frames(str(source), 0, 1).num_frames == 1
                    destination = root / f"copy-{index}"
                    codec.write(record, str(destination))
                    assert (destination / "frame.seqprobe").read_bytes() == b"frame"
            finally:
                assert registry.REGISTRY.pop(probe.id) is probe
            assert ".seqprobe" not in old_access.image_extensions()
            assert ".seqprobe" not in access.image_extensions()
            try:
                old_sequence.read(str(source))
            except ValueError as error:
                assert "unsupported frame extension" in str(error)
            else:
                raise AssertionError("removed extension remained visible")
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.parametrize(
    "format_id",
    [
        "y4m",
        "webm",
        "ivf",
        "mjpeg",
        "mp4",
        "theora",
        "animated_webp",
        "apng",
    ],
)
def test_sequence_inspection_dispatch_uses_family_implementation(format_id):
    assert _inspection._PATH_INSPECTORS[format_id] is getattr(
        sequence_inspector,
        f"inspect_{format_id}",
    )


def test_repository_coverage_keeps_sequence_inspection_ownership_exact():
    contract = tomllib.loads(
        (
            ROOT / "tests" / "contracts" / "repository_coverage_v1.toml"
        ).read_text(encoding="utf-8")
    )
    owners = {
        item["id"]: item["inspection_source"]
        for item in contract["codec"]
        if item["id"] in SEQUENCE_IDS
    }
    assert owners == {
        "y4m": "src/sceneio/io/_inspectors/sequences.py",
        "webm": "src/sceneio/io/_inspectors/sequences.py",
        "ivf": "src/sceneio/io/_inspectors/sequences.py",
        "mjpeg": "src/sceneio/io/_inspectors/sequences.py",
        "mp4": "src/sceneio/io/_inspectors/sequences.py",
        "theora": "src/sceneio/io/_inspectors/sequences.py",
        "animated_webp": "src/sceneio/io/_inspectors/sequences.py",
        "apng": "src/sceneio/io/_inspectors/sequences.py",
        "animated_avif": "src/sceneio/io/_avif.py",
        "rtmv": "src/sceneio/io/_rtmv.py",
        "image_sequence": "src/sceneio/io/_image_sequence.py",
    }


@pytest.mark.parametrize("fixture_name", tuple(_Y4M_FIXTURES))
def test_y4m_inspection_matches_parent_contract_and_full_read(
    tmp_path,
    fixture_name,
):
    expected = _contract()["y4m"][fixture_name]
    path = tmp_path / f"{fixture_name}.y4m"
    path.write_bytes(_Y4M_FIXTURES[fixture_name])
    lower = sequence_inspector.inspect_y4m(path, "image_sequence")
    public = sceneio.inspect(path, format="y4m")
    assert _normalized_inspection(lower) == expected
    assert _normalized_inspection(public) == expected

    full = sceneio.read(path, format="y4m")
    assert full.y.shape == tuple(expected["arrays"][0]["shape"])
    start = 0 if full.num_frames == 1 else 1
    partial_record = sceneio.read_partial(
        path,
        format="y4m",
        frames=(start, start + 1),
    )
    np.testing.assert_array_equal(
        partial_record.y,
        full.y[start : start + 1],
    )
    np.testing.assert_array_equal(
        partial_record.timestamps_ns,
        full.timestamps_ns[start : start + 1],
    )
    np.testing.assert_array_equal(
        partial_record.durations_ns,
        full.durations_ns[start : start + 1],
    )
    if full.channels == 3:
        np.testing.assert_array_equal(
            partial_record.u,
            full.u[start : start + 1],
        )
        np.testing.assert_array_equal(
            partial_record.v,
            full.v[start : start + 1],
        )


@pytest.mark.parametrize("fixture_name", tuple(_MALFORMED_Y4M))
def test_malformed_y4m_inspection_matches_parent_contract(
    tmp_path,
    fixture_name,
):
    expected = _contract()["malformed_y4m"][fixture_name]
    path = tmp_path / f"{fixture_name}.y4m"
    path.write_bytes(_MALFORMED_Y4M[fixture_name])
    with pytest.raises(Exception) as lower_error:
        sequence_inspector.inspect_y4m(path, "image_sequence")
    assert type(lower_error.value).__name__ == expected["cause_type"]
    assert str(lower_error.value) == expected["cause_message"]

    with pytest.raises(sceneio.FormatError) as public_error:
        sceneio.inspect(path, format="y4m")
    cause = public_error.value.__cause__
    assert type(cause).__name__ == expected["cause_type"]
    assert str(cause) == expected["cause_message"]
    public_message = str(public_error.value)

    renamed = path.with_suffix(".released")
    path.rename(renamed)
    renamed.unlink()
    assert str(lower_error.value) == expected["cause_message"]
    assert str(public_error.value) == public_message
    retained_cause = public_error.value.__cause__
    assert type(retained_cause).__name__ == expected["cause_type"]
    assert str(retained_cause) == expected["cause_message"]


def test_public_y4m_inspection_does_not_call_full_decoder(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "mono.y4m"
    path.write_bytes(_Y4M_FIXTURES["mono"])

    def fail(*_args, **_kwargs):
        raise AssertionError("full Y4M decoder called during inspection")

    monkeypatch.setattr(_core, "read_y4m", fail)
    assert sceneio.inspect(path, format="y4m").shape == (1, 2, 2, 1)


def test_large_y4m_inspection_is_bounded_and_releases_path(tmp_path):
    width = 8192
    height = 4096
    header = (
        f"YUV4MPEG2 W{width} H{height} F25:1 Ip A1:1 Cmono\n"
    ).encode("ascii")
    path = tmp_path / "large.y4m"
    with path.open("wb") as stream:
        stream.write(header)
        stream.write(b"FRAME\n")
        stream.seek(width * height - 1, 1)
        stream.write(b"\0")

    tracemalloc.start()
    try:
        retained = sequence_inspector.inspect_y4m(path, "image_sequence")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert retained.shape == (1, height, width, 1)
    assert peak < 1024 * 1024
    renamed = path.with_suffix(".released")
    path.rename(renamed)
    renamed.unlink()
    assert retained.byte_size > 32 * 1024 * 1024


@pytest.mark.parametrize("mode", ["unmanifested", "manifested"])
def test_directory_behavior_matches_hand_authored_parent_contract(
    tmp_path,
    mode,
):
    expected = _contract()["directories"][mode]
    directory = _write_directory_fixture(tmp_path, mode)
    if mode == "manifested":
        assert sceneio.detect(directory) == "image_sequence"
    else:
        with pytest.raises(sceneio.FormatError, match="no directory format"):
            sceneio.detect(directory)
    info = sceneio.inspect(directory, format="image_sequence")
    full = sceneio.read(directory, format="image_sequence")
    selected = sceneio.read_partial(
        directory,
        format="image_sequence",
        frames=(1, 3),
    )
    assert _normalized_inspection(info) == expected["inspection"]
    assert _sequence_summary(full) == expected["full"]
    assert _sequence_summary(selected) == expected["partial"]

    retained = (info, full, selected)
    renamed = directory.with_name(f"{directory.name}-released")
    directory.rename(renamed)
    for child in renamed.iterdir():
        child.unlink()
    renamed.rmdir()
    assert retained[0].count == 3
    assert retained[1].num_frames == 3
    assert retained[2].num_frames == 2
