"""Contracts for the lower registry model, adapters, and services."""

from __future__ import annotations

import ast
import base64
import inspect
import json
import pickle
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import sceneio
from sceneio import _core
from sceneio.io import registry
from sceneio.io._registry import adapters, detection, model, native_features

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "tests/contracts/io_registry_shared_v1.json").read_text(
        encoding="utf-8"
    )
)


class _DetectionError(Exception):
    pass


def _read_identity(path):
    return path


def _codec(
    format_id: str,
    *,
    extensions: tuple[str, ...] = (),
    magic: tuple[bytes, ...] = (),
    filenames: tuple[str, ...] = (),
    is_directory: bool = False,
    dir_marker: str = "marker",
) -> model.Codec:
    return model.Codec(
        format_id,
        extensions,
        _read_identity,
        None,
        None,
        "probe",
        magic=magic,
        filenames=filenames,
        is_directory=is_directory,
        dir_marker=dir_marker,
    )


def _detect(path, codecs, *, classify_ply=lambda path: "ply"):
    return detection.detect_path(
        path,
        codecs,
        classify_ply=classify_ply,
        format_error=_DetectionError,
    )


def _assert_lower_imports(module_name: str, source: str) -> None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "sceneio"
                if alias.name == "sceneio.io" or alias.name.startswith(
                    "sceneio.io."
                ):
                    assert alias.name.startswith("sceneio.io._registry"), (
                        module_name,
                        alias.name,
                    )
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, (module_name, node.level, node.module)
            if node.module == "sceneio":
                assert {alias.name for alias in node.names} == {"_core"}, (
                    module_name,
                    tuple(alias.name for alias in node.names),
                )
            elif node.module == "sceneio.io" or (
                node.module is not None
                and node.module.startswith("sceneio.io.")
            ):
                assert node.module.startswith("sceneio.io._registry"), (
                    module_name,
                    node.module,
                )


def test_shared_model_is_the_exact_historical_public_model():
    for name in ("Codec", "CodecCapabilities", "NativeFeatureCapabilities"):
        shared = getattr(model, name)
        assert getattr(registry, name) is shared
        assert getattr(sceneio, name) is shared
        assert not hasattr(sceneio.io, name)
        assert shared.__module__ == "sceneio.io.registry"
        assert shared.__qualname__ == name

    codec = _codec("pickle_probe", extensions=(".probe",))
    capability = codec.capabilities()
    native = model.NativeFeatureCapabilities(
        "probe",
        "SCENEIO_WITH_PROBE",
        False,
        ("probe",),
    )
    for value in (codec, capability, native):
        payload = pickle.dumps(value)
        assert b"sceneio.io.registry" in payload
        restored = pickle.loads(payload)
        assert type(restored) is type(value)
        assert restored == value


def test_pre_move_pickles_load_and_new_emission_stays_legacy_compatible():
    current = {
        "CodecCapabilities": sceneio.capabilities("npy"),
        "NativeFeatureCapabilities": sceneio.native_features("hdf5"),
    }
    assert CONTRACT["pre_move_commit"] == "40d5412"
    for name, expected in current.items():
        fixture = CONTRACT["protocol_4_pickles"][name]
        payload = base64.b64decode(fixture["base64"])
        restored = pickle.loads(payload)
        assert type(restored) is type(expected)
        assert restored == expected
        assert repr(restored) == fixture["repr"]
        assert pickle.dumps(expected, protocol=4) == payload


def test_shared_model_constructor_and_facade_function_signatures_are_stable():
    callables = {
        "Codec": model.Codec,
        "CodecCapabilities": model.CodecCapabilities,
        "NativeFeatureCapabilities": model.NativeFeatureCapabilities,
        "register": registry.register,
        "get": registry.get,
        "detect": registry.detect,
        "native_feature_capabilities": registry.native_feature_capabilities,
    }
    assert {
        name: str(inspect.signature(value)) for name, value in callables.items()
    } == CONTRACT["signatures"]


def test_adapter_factories_are_reexported_without_renaming(tmp_path):
    names = (
        "_bytes_reader",
        "_mmap_reader",
        "_mmap_selector_reader",
        "_mmap_view_reader",
        "_array_window_reader",
        "_file_sink_writer",
    )
    for name in names:
        assert getattr(registry, name) is getattr(adapters, name)

    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    assert adapters._bytes_reader(bytes)(path) == b"payload"
    assert (
        adapters._mmap_view_reader(bytes, bytes).__qualname__
        == "_mmap_view_reader.<locals>.read"
    )
    assert (
        adapters._file_sink_writer(bytes).__qualname__
        == "_file_sink_writer.<locals>.write"
    )


def test_lower_registry_modules_have_no_upward_or_family_imports():
    modules = (model, adapters, detection, native_features)
    for module in modules:
        _assert_lower_imports(module.__name__, inspect.getsource(module))


def test_lower_registry_import_guard_rejects_relative_upward_spelling():
    for source in (
        "from .. import registry",
        "from .._ply import classify_ply",
    ):
        with pytest.raises(AssertionError):
            _assert_lower_imports("sceneio.io._registry.probe", source)


def test_lower_model_import_preserves_existing_eager_parent_and_identity():
    code = textwrap.dedent(
        """
        import sys
        from sceneio.io._registry import model
        from sceneio.io import registry

        assert "sceneio.io" in sys.modules
        assert "sceneio.io.registry" in sys.modules
        assert model.Codec is registry.Codec
        assert model.CodecCapabilities is registry.CodecCapabilities
        assert model.NativeFeatureCapabilities is registry.NativeFeatureCapabilities
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_registry_facade_reload_remains_supported_in_a_fresh_process():
    code = textwrap.dedent(
        """
        import importlib
        from sceneio.io import registry
        from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS
        from sceneio.io._registry import model

        reloaded = importlib.reload(registry)
        assert tuple(reloaded.REGISTRY) == CANONICAL_BUILTIN_IDS
        assert reloaded.Codec is model.Codec
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_detection_preserves_directory_filename_extension_magic_precedence(tmp_path):
    directory = tmp_path / "scene.named"
    directory.mkdir()
    (directory / "marker").write_bytes(b"")
    assert _detect(
        directory,
        (
            _codec("directory", is_directory=True),
            _codec("filename", filenames=("scene.named",)),
            _codec("extension", extensions=(".named",)),
        ),
    ) == "directory"

    named = tmp_path / "scene.probe"
    named.write_bytes(b"MAGIC payload")
    codecs = (
        _codec("filename", filenames=("scene.probe",)),
        _codec("extension", extensions=(".probe",)),
        _codec("magic", magic=(b"MAGIC",)),
    )
    assert _detect(named, codecs) == "filename"

    extended = tmp_path / "other.PROBE"
    extended.write_bytes(b"MAGIC payload")
    assert _detect(extended, codecs) == "extension"

    extensionless = tmp_path / "payload"
    extensionless.write_bytes(b"MAGIC payload")
    assert _detect(extensionless, codecs) == "magic"


def test_detection_preserves_order_ply_and_las_laz_rules(tmp_path):
    collision = tmp_path / "collision.same"
    collision.write_bytes(b"")
    codecs = (
        _codec("first", extensions=(".same",)),
        _codec("second", extensions=(".same",)),
    )
    assert _detect(collision, codecs) == "first"

    ply = tmp_path / "schema.PLY"
    ply.write_bytes(b"not parsed by injected classifier")
    calls = []

    def classify(path):
        calls.append(path)
        return "gaussian_ply"

    assert _detect(ply, codecs, classify_ply=classify) == "gaussian_ply"
    assert calls == [ply]

    las_payload = bytearray(105)
    las_payload[:4] = b"LASF"
    las_payload[104] = 0x80
    extensionless = tmp_path / "cloud"
    extensionless.write_bytes(las_payload)
    assert _detect(extensionless, ()) == "laz"
    las_payload[104] = 0xC0
    extensionless.write_bytes(las_payload)
    assert _detect(extensionless, ()) == "las"


def test_detection_preserves_exact_errors_and_classification_cause(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(
        _DetectionError,
        match=r"^cannot detect a format for .*missing.* \(ext ''\)$",
    ) as unknown:
        _detect(missing, ())
    assert unknown.value.__cause__ is None

    ply = tmp_path / "bad.ply"
    ply.write_bytes(b"ply")

    def reject(path):
        raise ValueError("bad schema")

    with pytest.raises(
        _DetectionError,
        match=r"^cannot classify PLY .*bad\.ply.*: bad schema$",
    ) as classified:
        _detect(ply, (), classify_ply=reject)
    assert isinstance(classified.value.__cause__, ValueError)


def test_native_feature_metadata_is_ordered_live_and_error_compatible(monkeypatch):
    snapshots = native_features.native_feature_snapshots(
        ("hdf5",),
        unknown_feature=lambda name: registry.FormatError(
            f"unknown native feature {name!r}"
        ),
    )
    assert tuple(snapshots) == tuple(sorted(native_features.NATIVE_FEATURE_FORMATS))
    assert snapshots["hdf5"].available
    assert not snapshots["arrow"].available

    monkeypatch.setattr(_core, "__native_features__", ("hdf5",))
    assert registry.native_feature_capabilities("hdf5").available
    monkeypatch.setattr(_core, "__native_features__", ())
    assert not registry.native_feature_capabilities("hdf5").available

    with pytest.raises(
        registry.FormatError,
        match=r"^unknown native feature 'missing'$",
    ) as unknown:
        registry.native_feature_capabilities("missing")
    assert unknown.value.__cause__ is None

    monkeypatch.setattr(_core, "__native_features__", ("future",))
    with pytest.raises(
        RuntimeError,
        match=r"^compiled extension reports unknown native features: future$",
    ):
        registry.native_feature_capabilities()
