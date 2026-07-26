"""Architecture and parent-behavior contracts for the array I/O family."""

from __future__ import annotations

import ast
import dataclasses
import gc
import hashlib
import inspect
import io
import json
import struct
import subprocess
import sys
import textwrap
import tomllib
import tracemalloc
import zipfile
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
from sceneio.io._inspectors import arrays as array_inspector
from sceneio.io._registry.families import arrays as array_family

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "tests" / "contracts" / "io_array_family_v1.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
ARRAY_IDS = FAMILY_MEMBERS["arrays"]


def _absolute_imports(source: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
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


def _write_valid_arrays(root: Path) -> dict[str, Path]:
    values = {
        "pfm": (
            np.arange(3 * 4 * 3, dtype=np.float32).reshape(3, 4, 3) / 7
        ),
        "npy": np.arange(12, dtype=np.int16).reshape(3, 4),
        "npz": {
            "x": np.arange(6, dtype=np.int16).reshape(2, 3),
            "empty": np.empty((0, 2), np.float32),
        },
        "safetensors": _core.tensor_dict(
            {
                "weights": np.arange(6, dtype=np.float32).reshape(2, 3),
                "mask": np.array([True, False, True]),
            },
            attrs={"unit": "m", "frame": "opencv"},
        ),
        "flo": (
            np.arange(3 * 4 * 2, dtype=np.float32).reshape(3, 4, 2) / 5
        ),
        "dmb": _core.depth_map(
            np.arange(12, dtype=np.float32).reshape(3, 4),
            unit="unknown",
            invalid_policy="zero",
        ),
    }
    paths = {}
    for format_id in ARRAY_IDS:
        path = root / f"valid.{format_id}"
        sceneio.write(values[format_id], path, format=format_id)
        paths[format_id] = path
    return paths


def _normalized_inspection(info) -> dict[str, object]:
    return json.loads(
        json.dumps(
            {
                "format": info.format,
                "datatype": info.datatype,
                "shape": info.shape,
                "dtype": info.dtype,
                "channels": info.channels,
                "count": info.count,
                "arrays": [
                    {
                        "name": value.name,
                        "shape": value.shape,
                        "dtype": value.dtype,
                    }
                    for value in info.arrays
                ],
                "metadata": dict(info.metadata),
            }
        )
    )


def test_array_definitions_preserve_noncontiguous_order_and_identity():
    definitions = registry._ARRAY_CODECS
    assert isinstance(definitions, tuple)
    assert tuple(codec.id for codec in definitions) == ARRAY_IDS
    assert tuple(CONTRACT["family_ids"]) == ARRAY_IDS
    assert tuple(registry.REGISTRY) == CANONICAL_BUILTIN_IDS
    assert CONTRACT["canonical_positions"] == {
        format_id: CANONICAL_BUILTIN_IDS.index(format_id)
        for format_id in ARRAY_IDS
    }
    for codec in definitions:
        position = CONTRACT["canonical_positions"][codec.id]
        assert registry.REGISTRY[codec.id] is codec
        assert registry.BUILTIN_DEFINITIONS[position] is codec
        assert codec.inspect is None


def test_array_family_is_staged_once_and_not_defined_inline():
    source = inspect.getsource(registry)
    tree = ast.parse(source)
    array_staging = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_define_builtin_family"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "arrays"
    ]
    assert len(array_staging) == 1
    assert source.count("build_array_codecs(_canon, _prepare_tensor_dict)") == 1
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Codec"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            assert node.args[0].value not in ARRAY_IDS


def test_array_adapter_closures_preserve_exact_native_targets():
    codecs = {codec.id: codec for codec in registry._ARRAY_CODECS}
    assert inspect.getclosurevars(codecs["pfm"].read).nonlocals == {
        "fn": _core.read_pfm
    }
    assert inspect.getclosurevars(codecs["pfm"].write).nonlocals == {
        "fn": _core.write_pfm,
        "prepare": registry._canon,
    }
    assert inspect.getclosurevars(codecs["pfm"].read_window).nonlocals == {
        "fn": _core.read_pfm_window
    }

    assert inspect.getclosurevars(codecs["npy"].read).nonlocals == {
        "view_fn": _core.read_npy_view,
        "fallback_fn": _core.read_npy,
    }
    assert inspect.getclosurevars(codecs["npy"].write).nonlocals == {
        "fn": _core.write_npy,
        "prepare": registry._canon,
    }
    assert inspect.getclosurevars(codecs["npz"].read).nonlocals == {
        "fn": _core.read_npz
    }
    assert inspect.getclosurevars(codecs["npz"].write).nonlocals == {
        "fn": _core.write_npz,
        "prepare": registry._prepare_tensor_dict,
    }

    safetensors = codecs["safetensors"]
    assert inspect.getclosurevars(safetensors.read).nonlocals == {
        "view_fn": _core.read_safetensors_view,
        "fallback_fn": _core.read_safetensors,
    }
    assert inspect.getclosurevars(safetensors.write).nonlocals == {
        "fn": _core.write_safetensors,
        "prepare": registry._prepare_tensor_dict,
    }
    assert inspect.getclosurevars(safetensors.read_tensors).nonlocals == {
        "view_fn": _core.read_safetensors_tensors_view,
        "fallback_fn": _core.read_safetensors_tensors,
    }
    assert inspect.getclosurevars(safetensors.read_slices).nonlocals == {
        "view_fn": _core.read_safetensors_slices_view,
        "fallback_fn": _core.read_safetensors_slices,
    }

    flo = codecs["flo"]
    assert inspect.getclosurevars(flo.read).nonlocals == {
        "view_fn": _core.read_flo_view,
        "fallback_fn": _core.read_flo,
    }
    assert inspect.getclosurevars(flo.write).nonlocals == {
        "fn": _core.write_flo,
        "prepare": registry._canon,
    }
    nested_reader = inspect.getclosurevars(flo.read_window).nonlocals["reader"]
    assert nested_reader is not flo.read
    assert inspect.getclosurevars(nested_reader).nonlocals == {
        "view_fn": _core.read_flo_view,
        "fallback_fn": _core.read_flo,
    }

    assert inspect.getclosurevars(codecs["dmb"].read).nonlocals == {
        "fn": _core.read_dmb
    }
    assert inspect.getclosurevars(codecs["dmb"].write).nonlocals == {
        "fn": _core.write_dmb,
        "prepare": None,
    }
    assert inspect.getclosurevars(codecs["dmb"].read_window).nonlocals == {
        "fn": _core.read_dmb_window
    }


def test_facade_owned_array_preparation_callbacks_remain_exact():
    native = np.arange(12, dtype=np.float32).reshape(3, 4)
    assert registry._canon(native) is native

    noncontiguous = native[:, ::2]
    canonical = registry._canon(noncontiguous)
    assert canonical.flags.c_contiguous
    assert canonical is not noncontiguous
    assert canonical.tobytes() == np.ascontiguousarray(noncontiguous).tobytes()

    opposite = np.arange(6, dtype=">i2")
    native_endian = registry._canon(opposite)
    assert native_endian.dtype.isnative
    assert native_endian.tobytes() == opposite.astype("=i2").tobytes()

    tensor_dict = _core.tensor_dict({"x": native})
    assert registry._prepare_tensor_dict(tensor_dict) is tensor_dict
    prepared = registry._prepare_tensor_dict(
        {"z": noncontiguous, "a": opposite}
    )
    assert prepared.keys() == ["z", "a"]
    assert np.asarray(prepared["z"]).flags.c_contiguous
    assert np.asarray(prepared["a"]).dtype.isnative
    with pytest.raises((TypeError, ValueError)):
        registry._prepare_tensor_dict({"bad": np.array([object()])})


def test_array_family_modules_are_lower_layer_only():
    family_imports = _absolute_imports(inspect.getsource(array_family))
    assert {
        module for module, _ in family_imports
    } <= {
        "__future__",
        "sceneio",
        "sceneio.io._registry.adapters",
        "sceneio.io._registry.model",
    }
    assert tuple(
        names for module, names in family_imports if module == "sceneio"
    ) == (("_core",),)

    inspector_imports = _absolute_imports(inspect.getsource(array_inspector))
    assert {
        module for module, _ in inspector_imports
    } <= {
        "__future__",
        "math",
        "pathlib",
        "sceneio",
        "sceneio.io._inspectors.common",
        "sceneio.io._inspectors.model",
        "struct",
        "typing",
        "zipfile",
    }
    assert tuple(
        names for module, names in inspector_imports if module == "sceneio"
    ) == (("_core",),)

    for module in (array_family, array_inspector):
        source = inspect.getsource(module)
        assert "sceneio.io.registry" not in source
        assert "sceneio.io._inspection" not in source
        assert "sceneio.io._registry.assembly" not in source
        assert "REGISTRY" not in source
        assert "register(" not in source

    inspector_source = inspect.getsource(array_inspector)
    assert "_core.read_" not in inspector_source
    assert "_core.write_" not in inspector_source


def test_array_family_reload_is_inert_and_registry_reload_is_exact():
    code = textwrap.dedent(
        """
        import importlib
        import inspect

        from sceneio.io import registry
        from sceneio.io._builtin_manifest import (
            CANONICAL_BUILTIN_IDS,
            FAMILY_MEMBERS,
        )
        from sceneio.io._registry.families import arrays

        before_registry = registry.REGISTRY
        before_items = tuple(registry.REGISTRY.items())
        before_array_codecs = registry._ARRAY_CODECS
        reloaded_family = importlib.reload(arrays)
        assert registry.REGISTRY is before_registry
        assert tuple(registry.REGISTRY.items()) == before_items
        assert registry._ARRAY_CODECS is before_array_codecs

        fresh = reloaded_family.build_array_codecs(
            registry._canon,
            registry._prepare_tensor_dict,
        )
        assert tuple(codec.id for codec in fresh) == FAMILY_MEMBERS["arrays"]
        assert all(registry.REGISTRY[codec.id] is not codec for codec in fresh)

        for _ in range(2):
            reloaded_registry = importlib.reload(registry)
            assert tuple(reloaded_registry.REGISTRY) == CANONICAL_BUILTIN_IDS
            assert tuple(
                codec.id for codec in reloaded_registry._ARRAY_CODECS
            ) == FAMILY_MEMBERS["arrays"]
            for codec in reloaded_registry._ARRAY_CODECS:
                assert reloaded_registry.REGISTRY[codec.id] is codec
            assert inspect.getclosurevars(
                reloaded_registry.REGISTRY["npy"].write
            ).nonlocals["prepare"] is reloaded_registry._canon
            assert inspect.getclosurevars(
                reloaded_registry.REGISTRY["npz"].write
            ).nonlocals["prepare"] is reloaded_registry._prepare_tensor_dict
        """
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


@pytest.mark.parametrize(
    ("wrapper_name", "delegate_name"),
    [
        ("_inspect_pfm", "_inspect_array_pfm"),
        ("_inspect_npy", "_inspect_array_npy"),
        ("_inspect_npz", "_inspect_array_npz"),
        ("_inspect_safetensors", "_inspect_array_safetensors"),
        ("_inspect_flo", "_inspect_array_flo"),
        ("_inspect_dmb", "_inspect_array_dmb"),
    ],
)
def test_array_inspector_facade_preserves_wrapper_signatures(
    wrapper_name,
    delegate_name,
    monkeypatch,
):
    marker = object()
    calls = []

    def inspect_family(path, datatype):
        calls.append((path, datatype))
        return marker

    monkeypatch.setattr(_inspection, delegate_name, inspect_family)
    path = Path("array.fixture")
    wrapper = getattr(_inspection, wrapper_name)
    assert tuple(inspect.signature(wrapper).parameters) == ("path", "datatype")
    assert wrapper(path, "array") is marker
    assert calls == [(path, "array")]


def test_npy_header_facade_preserves_signature_and_delegate(monkeypatch):
    marker = ((2, 3), "float32", False)
    calls = []

    def inspect_header(stream):
        calls.append(stream)
        return marker

    monkeypatch.setattr(
        _inspection,
        "_inspect_array_npy_header",
        inspect_header,
    )
    stream = io.BytesIO(b"header")
    assert tuple(inspect.signature(_inspection._npy_header).parameters) == (
        "stream",
    )
    assert _inspection._npy_header(stream) == marker
    assert calls == [stream]


def test_repository_coverage_tracks_all_array_inspectors():
    contract = tomllib.loads(
        (
            ROOT / "tests" / "contracts" / "repository_coverage_v1.toml"
        ).read_text(encoding="utf-8")
    )
    owners = {
        item["id"]: item["inspection_source"]
        for item in contract["codec"]
        if item["id"] in ARRAY_IDS
    }
    assert owners == {
        format_id: "src/sceneio/io/_inspectors/arrays.py"
        for format_id in ARRAY_IDS
    }


@pytest.mark.parametrize("format_id", ARRAY_IDS)
def test_array_inspection_matches_parent_contract_and_full_read(
    tmp_path,
    format_id,
):
    expected = CONTRACT["valid"][format_id]
    path = _write_valid_arrays(tmp_path)[format_id]
    assert path.stat().st_size == expected["byte_size"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"]

    lower = getattr(array_inspector, f"inspect_{format_id}")(
        path,
        registry.REGISTRY[format_id].datatype,
    )
    public = sceneio.inspect(path, format=format_id)
    assert _normalized_inspection(lower) == expected["inspection"]
    assert _normalized_inspection(public) == expected["inspection"]

    full = sceneio.read(path, format=format_id)
    if format_id in {"pfm", "npy", "flo"}:
        array = np.asarray(full)
        assert list(array.shape) == expected["inspection"]["shape"]
        assert str(array.dtype) == expected["inspection"]["dtype"]
    elif format_id == "dmb":
        assert list(full.depth.shape) == expected["inspection"]["shape"]
        assert str(full.depth.dtype) == expected["inspection"]["dtype"]
    else:
        assert full.keys() == [
            value["name"] for value in expected["inspection"]["arrays"]
        ]
        for value in expected["inspection"]["arrays"]:
            array = np.asarray(full[value["name"]])
            assert list(array.shape) == value["shape"]
            assert str(array.dtype) == value["dtype"]


_MALFORMED = {
    "pfm": b"XX\n2 2\n-1.0\n" + b"\0" * 16,
    "npy": b"not-npy",
    "npz": b"not-zip",
    "safetensors": b"bad",
    "flo": b"bad",
    "dmb": b"bad",
}


@pytest.mark.parametrize("format_id", ARRAY_IDS)
def test_malformed_array_inspection_matches_parent_contract(
    tmp_path,
    format_id,
):
    expected = CONTRACT["malformed"][format_id]
    path = tmp_path / f"bad.{format_id}"
    path.write_bytes(_MALFORMED[format_id])
    inspector = getattr(array_inspector, f"inspect_{format_id}")
    with pytest.raises(Exception) as lower_error:
        inspector(path, registry.REGISTRY[format_id].datatype)
    assert type(lower_error.value).__name__ == expected["cause_type"]
    assert str(lower_error.value) == expected["cause_message"]

    with pytest.raises(sceneio.FormatError) as public_error:
        sceneio.inspect(path, format=format_id)
    cause = public_error.value.__cause__
    assert type(cause).__name__ == expected["cause_type"]
    assert str(cause) == expected["cause_message"]


def test_public_array_inspection_does_not_call_captured_or_dynamic_decoders(
    tmp_path,
    monkeypatch,
):
    paths = _write_valid_arrays(tmp_path)
    original = {format_id: registry.REGISTRY[format_id] for format_id in ARRAY_IDS}

    def fail(*_args, **_kwargs):
        raise AssertionError("full array decoder called during inspection")

    for format_id, codec in original.items():
        registry.REGISTRY[format_id] = dataclasses.replace(codec, read=fail)
    for name in (
        "read_pfm",
        "read_npy",
        "read_npy_view",
        "read_npz",
        "read_safetensors",
        "read_safetensors_view",
        "read_safetensors_tensors",
        "read_safetensors_tensors_view",
        "read_safetensors_slices",
        "read_safetensors_slices_view",
        "read_flo",
        "read_flo_view",
        "read_dmb",
    ):
        monkeypatch.setattr(_core, name, fail)
    try:
        for format_id, path in paths.items():
            assert sceneio.inspect(path, format=format_id).format == format_id
    finally:
        registry.REGISTRY.update(original)


def _npy_header_bytes(shape: tuple[int, ...]) -> bytes:
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        stream,
        {
            "descr": "<f4",
            "fortran_order": False,
            "shape": shape,
        },
    )
    return stream.getvalue()


def _write_large_inspection_fixture(root: Path, format_id: str) -> Path:
    height, width = 4096, 2048
    payload_size = height * width * 4
    path = root / f"large.{format_id}"
    if format_id == "pfm":
        header = f"Pf\n{width} {height}\n-1.0\n".encode()
        with path.open("wb") as stream:
            stream.write(header)
            stream.truncate(len(header) + payload_size)
    elif format_id == "npy":
        header = _npy_header_bytes((height, width))
        with path.open("wb") as stream:
            stream.write(header)
            stream.truncate(len(header) + payload_size)
    elif format_id == "npz":
        header = _npy_header_bytes((height, width))
        with zipfile.ZipFile(
            path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive, archive.open("x.npy", "w") as member:
            member.write(header)
            block = b"\0" * (1024 * 1024)
            for _ in range(payload_size // len(block)):
                member.write(block)
    elif format_id == "safetensors":
        header = json.dumps(
            {
                "x": {
                    "dtype": "F32",
                    "shape": [height, width],
                    "data_offsets": [0, payload_size],
                }
            },
            separators=(",", ":"),
        ).encode()
        header += b" " * (-len(header) % 8)
        with path.open("wb") as stream:
            stream.write(struct.pack("<Q", len(header)))
            stream.write(header)
            stream.truncate(8 + len(header) + payload_size)
    elif format_id == "flo":
        with path.open("wb") as stream:
            stream.write(b"PIEH" + struct.pack("<ii", width, height))
            stream.truncate(12 + payload_size * 2)
    else:
        with path.open("wb") as stream:
            stream.write(struct.pack("<4i", 1, height, width, 1))
            stream.truncate(16 + payload_size)
    return path


@pytest.mark.parametrize("format_id", ARRAY_IDS)
def test_large_array_inspections_are_bounded_and_release_paths(
    tmp_path,
    format_id,
):
    path = _write_large_inspection_fixture(tmp_path, format_id)
    gc.collect()
    tracemalloc.start()
    try:
        info = getattr(array_inspector, f"inspect_{format_id}")(
            path,
            registry.REGISTRY[format_id].datatype,
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1024 * 1024, (format_id, peak)

    renamed = path.with_suffix(".released")
    path.rename(renamed)
    renamed.unlink()
    assert info.format == format_id
