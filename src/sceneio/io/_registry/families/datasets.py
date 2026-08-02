"""Built-in multi-sensor dataset codec definitions."""

from __future__ import annotations

from sceneio.io._ncore import (
    NCoreDataset,
    inspect_ncore_v4,
    is_ncore_v4_directory,
    is_ncore_v4_file,
    read_ncore_v4,
    write_ncore_v4,
)
from sceneio.io._registry.model import Codec

DATASET_CODECS = (
    Codec(
        "ncore_v4",
        (),
        read_ncore_v4,
        write_ncore_v4,
        record=NCoreDataset,
        datatype="ncore_dataset",
        is_directory=True,
        container_kind="multi_file",
        dir_marker=".zattrs",
        directory_markers=(".zattrs", ".zgroup"),
        file_probe=is_ncore_v4_file,
        directory_probe=is_ncore_v4_directory,
        inspect=inspect_ncore_v4,
        streams_write=True,
        requires_features=("zarr", "cbor2"),
        supported_features=(
            "v4",
            "local_directory_stores",
            "local_indexed_tar_stores",
            "sequence_manifests",
            "grouped_component_stores",
            "lazy_component_catalog",
            "metadata_only_inspect",
            "standard_component_enumeration",
            "custom_component_enumeration",
            "component_materialization",
            "standard_semantic_profiles",
            "generic_component_interpretation",
            "deterministic_directory_write",
            "deterministic_indexed_tar_write",
            "sequence_manifest_write",
            "transactional_path_write",
        ),
        unsupported_features=(
            "remote_stores",
            "legacy_versions",
        ),
    ),
)

__all__ = ["DATASET_CODECS"]
