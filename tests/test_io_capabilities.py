"""Public codec capability discovery and documentation consistency."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

import sceneio
from sceneio.io import registry

_BUILTINS = {
    "bal",
    "bmp",
    "bundler",
    "colmap_db",
    "colmap_sparse",
    "colmap_sparse_txt",
    "compressed_ply",
    "dmb",
    "euroc_state",
    "exr",
    "flo",
    "gaussian_ply",
    "g2o",
    "hdr",
    "jpeg",
    "kitti",
    "kalibr",
    "ksplat",
    "las",
    "netpbm",
    "npy",
    "npz",
    "nvm",
    "obj",
    "off",
    "openmvg",
    "opencv_xml",
    "opencv_yaml",
    "pcd",
    "pfm",
    "ply",
    "ply_mesh",
    "png",
    "pts",
    "ros_camera_info",
    "safetensors",
    "sog",
    "splat",
    "spz",
    "stl",
    "transforms_json",
    "tum",
    "tga",
    "webp",
    "xyz",
}

_PARTIAL = {
    "colmap_db": ("image_id", "pair"),
    "colmap_sparse": ("image_id",),
    "colmap_sparse_txt": ("image_id",),
    "dmb": ("window",),
    "euroc_state": ("states",),
    "flo": ("window",),
    "gaussian_ply": ("points",),
    "compressed_ply": ("points",),
    "sog": ("points",),
    "ksplat": ("points",),
    "las": ("points",),
    "netpbm": ("window",),
    "pcd": ("points",),
    "pfm": ("window",),
    "ply_mesh": ("faces",),
    "off": ("faces",),
    "ply": ("points",),
    "pts": ("points",),
    "safetensors": ("tensors", "slices"),
    "splat": ("points",),
    "stl": ("faces",),
    "webp": ("window",),
    "xyz": ("points",),
}

_LOSSY = {
    "compressed_ply",
    "hdr",
    "jpeg",
    "ksplat",
    "las",
    "splat",
    "spz",
    "sog",
    "webp",
}

_NATIVE_FEATURES = {
    "arrow": ("SCENEIO_WITH_ARROW", ("parquet",)),
    "avif": ("SCENEIO_WITH_AVIF", ("avif",)),
    "draco": ("SCENEIO_WITH_DRACO", ("gltf", "glb")),
    "e57": ("SCENEIO_WITH_E57", ("e57",)),
    "hdf5": (
        "SCENEIO_WITH_HDF5",
        ("hdf5", "hloc_features", "hloc_matches"),
    ),
    "jxl": ("SCENEIO_WITH_JXL", ("jpeg_xl",)),
    "openvdb": ("SCENEIO_WITH_OPENVDB", ("openvdb",)),
    "tiff": ("SCENEIO_WITH_TIFF", ("tiff",)),
    "usd": ("SCENEIO_WITH_USD", ("usd", "usdz")),
}


def test_capabilities_cover_the_exact_builtin_registry():
    all_caps = sceneio.capabilities()
    assert isinstance(all_caps, dict)
    assert set(all_caps) == set(sceneio.codecs()) == _BUILTINS
    assert all(cap.format == format_id for format_id, cap in all_caps.items())


def test_capability_hooks_and_metadata_are_consistent():
    for format_id, codec in sceneio.codecs().items():
        cap = sceneio.capabilities(format_id)
        assert isinstance(cap, sceneio.CodecCapabilities)
        assert cap.available and cap.can_read and cap.can_inspect
        assert cap.can_write is (codec.write is not None)
        assert cap.streams_read is codec.streams_read
        assert cap.streams_write is (
            codec.write is not None and codec.streams_write
        )
        assert cap.partial_selectors == _PARTIAL.get(format_id, ())
        assert cap.lossy is (format_id in _LOSSY)
        assert cap.container_kind == codec.container_kind
        assert cap.requires_features == ()
        assert not (
            set(cap.supported_features) & set(cap.unsupported_features)
        )


def test_capability_snapshots_are_frozen_and_mapping_is_detached():
    cap = sceneio.capabilities("npy")
    with pytest.raises(dataclasses.FrozenInstanceError):
        cap.can_write = False

    all_caps = sceneio.capabilities()
    del all_caps["npy"]
    assert "npy" in sceneio.capabilities()


def test_capability_details_pin_current_fidelity_boundaries():
    npy = sceneio.capabilities("npy")
    assert "native_endian_mmap_view" in npy.supported_features
    assert {"fortran_order", "object_dtype"} <= set(npy.unsupported_features)

    las = sceneio.capabilities("las")
    assert {"point_formats_0_3", "point_formats_6_8"} <= set(
        las.supported_features
    )
    assert {
        "point_formats_4_5",
        "point_formats_9_10",
        "laz",
    } <= set(las.unsupported_features)

    webp = sceneio.capabilities("webp")
    assert {"lossless", "lossy"} <= set(webp.supported_features)
    assert {"animation", "lossy_window"} <= set(webp.unsupported_features)

    safetensors = sceneio.capabilities("safetensors")
    assert {"metadata", "mmap_views", "leading_axis_slices"} <= set(
        safetensors.supported_features
    )
    assert {"bfloat16", "float8", "complex64"} <= set(
        safetensors.unsupported_features
    )


def test_unknown_capability_format_is_normalized():
    with pytest.raises(sceneio.FormatError, match="unknown format id"):
        sceneio.capabilities("not-a-format")


def test_native_feature_manifest_has_stable_compiled_state():
    features = sceneio.native_features()
    assert set(features) == set(_NATIVE_FEATURES)
    for name, (build_option, formats) in _NATIVE_FEATURES.items():
        feature = features[name]
        assert isinstance(feature, sceneio.NativeFeatureCapabilities)
        assert feature.name == name
        assert feature.build_option == build_option
        assert feature.formats == formats
        assert not feature.available

    with pytest.raises(dataclasses.FrozenInstanceError):
        features["hdf5"].available = True
    del features["hdf5"]
    assert "hdf5" in sceneio.native_features()


def test_unknown_native_feature_is_normalized():
    with pytest.raises(sceneio.FormatError, match="unknown native feature"):
        sceneio.native_features("not-a-feature")


def test_unavailable_optional_codecs_are_normalized():
    for format_id in ("hdf5", "tiff", "e57", "parquet"):
        with pytest.raises(sceneio.FormatError, match="unknown format id"):
            sceneio.capabilities(format_id)


def test_native_feature_manifest_reads_compiled_extension_state(monkeypatch):
    monkeypatch.setattr(
        registry._core,
        "__native_features__",
        ("hdf5",),
        raising=False,
    )
    assert sceneio.native_features("hdf5").available
    assert not sceneio.native_features("tiff").available

    monkeypatch.setattr(registry._core, "__native_features__", ("unknown",))
    with pytest.raises(RuntimeError, match="unknown native features"):
        sceneio.native_features()


def test_codec_metadata_normalizes_sequences_and_rejects_conflicts():
    codec = registry.Codec(
        "metadata_test",
        [".meta"],
        lambda path: path,
        None,
        record=None,
        datatype="tensor",
        supported_features=["one"],
        unsupported_features=["two"],
    )
    assert codec.extensions == (".meta",)
    assert codec.supported_features == ("one",)
    assert codec.capabilities().container_kind == "file"
    assert not codec.capabilities().can_write
    assert not codec.capabilities().streams_write

    with pytest.raises(ValueError, match="overlap"):
        registry.Codec(
            "bad",
            (),
            lambda path: path,
            None,
            record=None,
            datatype="tensor",
            supported_features=("same",),
            unsupported_features=("same",),
        )
    with pytest.raises(ValueError, match="disagree"):
        registry.Codec(
            "bad-dir",
            (),
            lambda path: path,
            None,
            record=None,
            datatype="tensor",
            is_directory=True,
            container_kind="file",
        )


def _capability_rows() -> str:
    rows = []
    for format_id, cap in sorted(sceneio.capabilities().items()):
        partial = ", ".join(cap.partial_selectors) or "-"
        requires = ", ".join(cap.requires_features) or "-"
        rows.append(
            f"| `{format_id}` | {cap.container_kind} | yes | "
            f"{'yes' if cap.can_write else 'no'} | yes | {partial} | "
            f"{'yes' if cap.streams_read else 'no'} | "
            f"{'yes' if cap.streams_write else 'no'} | "
            f"{'yes' if cap.lossy else 'no'} | {requires} |"
        )
    return "\n".join(rows)


def _native_feature_rows() -> str:
    rows = []
    for name, feature in sceneio.native_features().items():
        formats = ", ".join(f"`{item}`" for item in feature.formats)
        rows.append(
            f"| `{name}` | `{feature.build_option}` | "
            f"{'yes' if feature.available else 'no'} | {formats} |"
        )
    return "\n".join(rows)


def test_documented_capability_snapshot_matches_registry():
    document = (
        Path(__file__).parents[1] / "docs" / "format_coverage.md"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"<!-- sceneio-capabilities:start -->\n"
        r".*?\n"
        r"<!-- sceneio-capability-rows:start -->\n"
        r"(.*?)\n"
        r"<!-- sceneio-capability-rows:end -->\n"
        r".*?\n"
        r"<!-- sceneio-capabilities:end -->",
        document,
        re.DOTALL,
    )
    assert match is not None, "format_coverage.md lacks the capability snapshot"
    assert match.group(1) == _capability_rows()

    feature_match = re.search(
        r"<!-- sceneio-native-features:start -->\n"
        r".*?\n"
        r"<!-- sceneio-native-feature-rows:start -->\n"
        r"(.*?)\n"
        r"<!-- sceneio-native-feature-rows:end -->\n"
        r".*?\n"
        r"<!-- sceneio-native-features:end -->",
        document,
        re.DOTALL,
    )
    assert feature_match is not None, "format_coverage.md lacks native features"
    assert feature_match.group(1) == _native_feature_rows()
