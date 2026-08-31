"""Architecture contracts for the image registry/inspector family."""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
import sys
import textwrap
import tomllib
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import _inspection, registry
from sceneio.io._builtin_manifest import (
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)
from sceneio.io._inspectors import images as image_inspector
from sceneio.io._registry.families import images as image_family

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tests" / "contracts" / "io_image_inspection_v1.json"
IMAGE_IDS = FAMILY_MEMBERS["images"]
NATIVE_IMAGE_IDS = tuple(
    json.loads(CONTRACT.read_text(encoding="utf-8"))["valid"]
)


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


def _assert_image_family_imports(source: str) -> None:
    imports = _absolute_imports_from_source(source)
    _assert_core_only_sceneio_import(imports)
    assert {
        module for module, _ in imports
    } <= {
        "__future__",
        "sceneio",
        "sceneio._data",
        "sceneio.io._avif",
        "sceneio.io._tiff",
        "sceneio.io._registry.adapters",
        "sceneio.io._registry.model",
    }


def _write_valid_images(root: Path) -> dict[str, Path]:
    u8 = np.arange(5 * 7 * 3, dtype=np.uint8).reshape(5, 7, 3)
    f32 = np.linspace(
        0.25,
        4.0,
        5 * 7 * 3,
        dtype=np.float32,
    ).reshape(5, 7, 3)
    records = {
        "netpbm": _core.image(u8, color_space="srgb"),
        "png": _core.image(u8, color_space="srgb"),
        "jpeg": _core.image(u8, color_space="srgb"),
        "bmp": _core.image(u8, color_space="srgb"),
        "tga": _core.image(u8, color_space="srgb"),
        "hdr": _core.image(f32, color_space="linear"),
        "exr": _core.image(f32, color_space="linear"),
        "webp": _core.image(u8, color_space="srgb"),
    }
    paths = {}
    for format_id, record in records.items():
        path = root / f"valid-{format_id}"
        sceneio.write(record, path, format=format_id)
        paths[format_id] = path
    return paths


def _normalized_inspection(info) -> dict[str, object]:
    return json.loads(
        json.dumps(
            {
                "shape": info.shape,
                "dtype": info.dtype,
                "channels": info.channels,
                "count": info.count,
                "metadata": dict(info.metadata),
            }
        )
    )


def test_image_definitions_preserve_canonical_order_and_identity():
    definitions = image_family.IMAGE_CODECS
    assert isinstance(definitions, tuple)
    assert tuple(codec.id for codec in definitions) == IMAGE_IDS
    assert tuple(
        sorted(IMAGE_IDS, key=CANONICAL_BUILTIN_IDS.index)
    ) == IMAGE_IDS
    native_start = CANONICAL_BUILTIN_IDS.index(NATIVE_IMAGE_IDS[0])
    native_stop = native_start + len(NATIVE_IMAGE_IDS)
    assert CANONICAL_BUILTIN_IDS[native_start:native_stop] == (
        NATIVE_IMAGE_IDS
    )
    for codec in definitions:
        position = CANONICAL_BUILTIN_IDS.index(codec.id)
        assert registry.REGISTRY[codec.id] is codec
        assert registry.BUILTIN_DEFINITIONS[position] is codec
        if codec.id == "tiff":
            assert codec.record is sceneio.RasterCollection
            assert codec.inspect is not None
        else:
            assert codec.record is _core.Image
            assert (codec.inspect is not None) == (codec.id == "avif")


def test_image_adapter_closures_preserve_exact_native_targets():
    codecs = {codec.id: codec for codec in image_family.IMAGE_CODECS}
    for format_id in NATIVE_IMAGE_IDS:
        codec = codecs[format_id]
        assert inspect.getclosurevars(codec.read).nonlocals == {
            "fn": getattr(_core, f"read_{format_id}")
        }
        assert inspect.getclosurevars(codec.write).nonlocals == {
            "fn": getattr(_core, f"write_{format_id}"),
            "prepare": None,
        }

    assert inspect.getclosurevars(codecs["netpbm"].read_window).nonlocals == {
        "fn": _core.read_netpbm_window
    }
    assert inspect.getclosurevars(codecs["webp"].read_window).nonlocals == {
        "fn": _core.read_webp_window
    }
    assert all(
        codecs[format_id].read_window is None
        for format_id in set(NATIVE_IMAGE_IDS) - {"netpbm", "webp"}
    )


def test_image_detection_and_lossy_fields_remain_exact():
    codecs = {codec.id: codec for codec in image_family.IMAGE_CODECS}
    assert {
        format_id: (
            codec.extensions,
            codec.magic,
            codec.lossy,
        )
        for format_id, codec in codecs.items()
    } == {
        "netpbm": (
            (".ppm", ".pgm", ".pnm"),
            (b"P2", b"P3", b"P5", b"P6"),
            False,
        ),
        "png": ((".png",), (b"\x89PNG\r\n\x1a\n",), False),
        "jpeg": ((".jpg", ".jpeg"), (b"\xff\xd8\xff",), True),
        "bmp": ((".bmp",), (b"BM",), False),
        "tga": ((".tga",), (), False),
        "hdr": ((".hdr",), (b"#?RADIANCE", b"#?RGBE"), True),
        "exr": ((".exr",), (b"\x76\x2f\x31\x01",), False),
        "webp": ((".webp",), (), True),
        "avif": ((".avif",), (), True),
        "tiff": (
            (".tif", ".tiff"),
            (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"),
            False,
        ),
    }


def test_image_family_modules_are_lower_layer_only():
    _assert_image_family_imports(inspect.getsource(image_family))

    inspector_imports = _absolute_imports_from_source(
        inspect.getsource(image_inspector)
    )
    _assert_core_only_sceneio_import(inspector_imports)
    assert {
        module for module, _ in inspector_imports
    } <= {
        "__future__",
        "binascii",
        "collections.abc",
        "pathlib",
        "re",
        "sceneio",
        "sceneio.io._inspectors.common",
        "sceneio.io._inspectors.model",
        "struct",
        "typing",
    }

    for module in (image_family, image_inspector):
        source = inspect.getsource(module)
        assert "sceneio.io.registry" not in source
        assert "sceneio.io._inspection" not in source
        assert "sceneio.io._image_sequence" not in source
        assert "sceneio.io._frame_access" not in source
        assert "REGISTRY" not in source
        assert "register(" not in source


def test_lower_image_inspectors_use_only_metadata_entry_points():
    source = inspect.getsource(image_inspector)
    assert "_core.read_" not in source
    assert "_core.write_" not in source
    assert source.count("_core._inspect_bmp") == 1
    assert source.count("_core._inspect_tga") == 1
    assert "_core._inspect_" not in source.replace(
        "_core._inspect_bmp", ""
    ).replace("_core._inspect_tga", "")


def test_image_lower_import_guard_rejects_upward_relative_and_sibling_imports():
    for source in (
        "import sceneio",
        "from sceneio import io",
        "from sceneio import _core, io",
        "from sceneio.io import registry",
        "from sceneio.io import _inspection",
        "from sceneio.io import _image_sequence",
        "from sceneio.io import _frame_access",
        "from sceneio.io._registry.families import meshes",
        "from . import images",
    ):
        with pytest.raises(AssertionError):
            _assert_image_family_imports(source)


def test_image_family_registry_reload_and_live_frame_access_are_idempotent():
    code = textwrap.dedent(
        """
        import importlib
        from functools import partial

        from sceneio import Codec, _core
        from sceneio.io import registry
        from sceneio.io._builtin_manifest import (
            CANONICAL_BUILTIN_IDS,
            FAMILY_MEMBERS,
        )
        from sceneio.io._registry.families import images

        before_registry = registry.REGISTRY
        before_items = tuple(registry.REGISTRY.items())
        before_access = registry._IMAGE_FRAME_ACCESS
        reloaded_family = importlib.reload(images)
        assert registry.REGISTRY is before_registry
        assert tuple(registry.REGISTRY.items()) == before_items
        assert registry._IMAGE_FRAME_ACCESS is before_access
        assert all(
            registry.REGISTRY[codec.id] is not codec
            for codec in reloaded_family.IMAGE_CODECS
        )

        for _ in range(2):
            old_access = registry._IMAGE_FRAME_ACCESS
            reloaded_registry = importlib.reload(registry)
            assert tuple(reloaded_registry.REGISTRY) == CANONICAL_BUILTIN_IDS
            assert tuple(
                reloaded_registry.REGISTRY[format_id]
                for format_id in FAMILY_MEMBERS["images"]
            ) == reloaded_family.IMAGE_CODECS
            access = reloaded_registry._IMAGE_FRAME_ACCESS
            assert access is not old_access
            expected = frozenset(
                extension.lower()
                for codec in reloaded_registry.REGISTRY.values()
                if codec.record is _core.Image
                for extension in codec.extensions
            )
            assert access.image_extensions() == expected
            sequence = reloaded_registry.REGISTRY["image_sequence"]
            for callback in (
                sequence.read,
                sequence.write,
                sequence.inspect,
                sequence.read_frames,
            ):
                assert isinstance(callback, partial)
                assert callback.args[0] is access

            probe = Codec(
                "image-contract-probe",
                (".CONTRACT-IMAGE",),
                lambda path: path,
                lambda record, path: None,
                record=_core.Image,
                payload_kind="image",
            )
            reloaded_registry.register(probe)
            try:
                assert ".contract-image" in access.image_extensions()
            finally:
                assert reloaded_registry.REGISTRY.pop(probe.id) is probe
            assert access.image_extensions() == expected
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.parametrize(
    "format_id",
    [
        "netpbm",
        "png",
        "jpeg",
        "bmp",
        "tga",
        "hdr",
        "exr",
        "webp",
    ],
)
def test_image_inspection_dispatch_uses_family_implementation(format_id):
    selected = _inspection._PATH_INSPECTORS[format_id]
    expected = getattr(image_inspector, f"inspect_{format_id}")
    assert (selected.__module__, selected.__name__) == (
        expected.__module__,
        expected.__name__,
    )


def test_repository_coverage_tracks_all_moved_image_inspectors():
    contract = tomllib.loads(
        (
            ROOT / "tests" / "contracts" / "repository_coverage_v1.toml"
        ).read_text(encoding="utf-8")
    )
    owners = {
        item["id"]: item["inspection_source"]
        for item in contract["codec"]
        if item["id"] in IMAGE_IDS
    }
    assert owners == {
        format_id: "src/sceneio/io/_inspectors/images.py"
        for format_id in NATIVE_IMAGE_IDS
    } | {
        "avif": "src/sceneio/io/_avif.py",
        "tiff": "src/sceneio/io/_tiff.py",
    }


@pytest.mark.parametrize("format_id", NATIVE_IMAGE_IDS)
def test_image_inspection_matches_parent_contract_and_full_read(
    tmp_path,
    format_id,
):
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["parent_commit"] == "8040bc7"
    path = _write_valid_images(tmp_path)[format_id]
    lower = getattr(image_inspector, f"inspect_{format_id}")(
        path,
        "image",
    )
    public = sceneio.inspect(path, format=format_id)
    assert _normalized_inspection(lower) == contract["valid"][format_id]
    assert _normalized_inspection(public) == contract["valid"][format_id]
    full = sceneio.read(path, format=format_id)
    pixels = np.asarray(full.pixels)
    assert pixels.shape == tuple(public.shape)
    assert str(pixels.dtype) == public.dtype


_MALFORMED = {
    "netpbm": b"P5\n0 2\n255\n",
    "png": b"not png!",
    "jpeg": b"bad",
    "bmp": b"bad",
    "tga": b"bad",
    "hdr": b"bad\n",
    "exr": b"bad!",
    "webp": b"badbadbadbad",
}


@pytest.mark.parametrize("format_id", NATIVE_IMAGE_IDS)
def test_malformed_image_inspection_matches_parent_contract(
    tmp_path,
    format_id,
):
    expected = json.loads(CONTRACT.read_text(encoding="utf-8"))[
        "malformed"
    ][format_id]
    path = tmp_path / f"bad-{format_id}"
    path.write_bytes(_MALFORMED[format_id])
    inspector = getattr(image_inspector, f"inspect_{format_id}")
    with pytest.raises(Exception) as lower_error:
        inspector(path, "image")
    assert type(lower_error.value).__name__ == expected["cause_type"]
    assert str(lower_error.value) == expected["cause_message"]

    with pytest.raises(sceneio.FormatError) as public_error:
        sceneio.inspect(path, format=format_id)
    cause = public_error.value.__cause__
    assert type(cause).__name__ == expected["cause_type"]
    assert str(cause) == expected["cause_message"]


def test_public_image_inspection_does_not_call_full_decoders(
    tmp_path,
    monkeypatch,
):
    paths = _write_valid_images(tmp_path)

    def fail(*_args, **_kwargs):
        raise AssertionError("full image decoder called during inspection")

    for format_id in NATIVE_IMAGE_IDS:
        monkeypatch.setattr(_core, f"read_{format_id}", fail)
    for format_id, path in paths.items():
        info = sceneio.inspect(path, format=format_id)
        assert info.format == format_id


def test_large_image_inspections_are_bounded_and_release_paths(tmp_path):
    paths = _write_valid_images(tmp_path)
    retained = []
    for format_id, path in paths.items():
        with path.open("r+b") as stream:
            stream.seek(0, 2)
            stream.truncate(36 * 1024 * 1024)

        tracemalloc.start()
        try:
            info = getattr(image_inspector, f"inspect_{format_id}")(
                path,
                "image",
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 1024 * 1024, (format_id, peak)
        retained.append(info)

        renamed = path.with_suffix(".released")
        path.rename(renamed)
        renamed.unlink()
    assert tuple(info.format for info in retained) == NATIVE_IMAGE_IDS
