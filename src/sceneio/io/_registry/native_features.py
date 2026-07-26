"""Build-time native-feature metadata independent of the registry facade."""

from __future__ import annotations

from collections.abc import Callable, Collection

from sceneio.io._registry.model import NativeFeatureCapabilities

NATIVE_FEATURE_FORMATS = {
    "arrow": ("parquet",),
    "avif": ("avif",),
    "draco": ("gltf", "glb"),
    "e57": ("e57",),
    "hdf5": ("hdf5", "hloc_features", "hloc_matches"),
    "jxl": ("jpeg_xl",),
    "openvdb": ("openvdb",),
    "tiff": ("tiff",),
    "usd": ("usd", "usdz"),
}


def native_feature_snapshots(
    compiled_features: Collection[str],
    name: str | None = None,
    *,
    unknown_feature: Callable[[str], Exception],
) -> NativeFeatureCapabilities | dict[str, NativeFeatureCapabilities]:
    """Return immutable metadata for the supplied compiled feature names."""

    compiled = frozenset(compiled_features)
    unknown_compiled = compiled - NATIVE_FEATURE_FORMATS.keys()
    if unknown_compiled:
        raise RuntimeError(
            "compiled extension reports unknown native features: "
            + ", ".join(sorted(unknown_compiled))
        )

    def snapshot(feature_name: str) -> NativeFeatureCapabilities:
        try:
            formats = NATIVE_FEATURE_FORMATS[feature_name]
        except KeyError:
            raise unknown_feature(feature_name) from None
        return NativeFeatureCapabilities(
            name=feature_name,
            build_option=f"SCENEIO_WITH_{feature_name.upper()}",
            available=feature_name in compiled,
            formats=formats,
        )

    if name is not None:
        return snapshot(name)
    return {
        feature_name: snapshot(feature_name)
        for feature_name in sorted(NATIVE_FEATURE_FORMATS)
    }
