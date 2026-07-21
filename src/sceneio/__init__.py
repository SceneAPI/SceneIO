"""sceneio — the contract plane for SceneAPI.

This is a *contract*, not an implementation. It owns both the **data
contracts** and the **procedure contracts** the SceneAPI family agrees
on, organized as import-isolated namespaces:

- :mod:`sceneio.data` — numpy-native datatypes (calibration,
  SE3/Sim3, priors, depth/pointmaps/confidence/masks, features,
  correspondences, tracked point clouds, view inputs, frame metadata).
- :mod:`sceneio.formats` — the disk/wire format-id registry.
- :mod:`sceneio.mapping` — the neutral `Mapper` contract + traits.
- :mod:`sceneio.matching` — `FeatureExtractor` / `PairMatcher` /
  `GeometricVerifier` + traits.
- :mod:`sceneio.testing` — conformance kits for implementations.

Plus the pre-0.2 surface, unchanged and re-exported flat off this
module: the ``application/x-sfm-points-v1`` wire codec
(``points_binary``), the storage / image-source Protocols
(`BlobStore`, `ImageSourceImpl`), the extended COLMAP scene-database
schema (``colmap_db``), the ``PCMAPIN`` checkpoint helpers
(``mapping_input``), and the shared error base (`SceneIoError`, with
`ContractViolation` for contract breaches).

Concrete backends (blob stores, the FastAPI service, engine adapters,
the SceneMap / SceneMatch implementation bundles) live elsewhere; they
depend on this package for the contracts they must agree on. This
package is a leaf: it imports **nothing from the SceneAPI family**
(``sceneapi`` / ``sfm_hub`` / ``app``; guard-tested). numpy is its one
hard dependency — the contracts are numpy-native.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from sceneio.blobstore import BlobStore, validate_sha
from sceneio.colmap_db import (
    COLMAP_DB_TABLES,
    COLMAP_DB_TABLES_BY_NAME,
    COLMAP_KNOWN_EXTRACTOR_TYPES,
    COLMAP_KNOWN_MATCHER_TYPES,
    CONTRACT_NAME,
    CONTRACT_SCHEMA_VERSION,
    DATABASE_SCHEMA_REVISION,
    DATABASE_VERSION_NUMBER,
    EXTENSION_COLUMNS,
    EXTENSION_TABLES,
    MAX_NUM_IMAGES,
    UNDEFINED_EXTRACTOR_TYPE,
    UPSTREAM_TABLES,
    ColumnDef,
    TableDef,
    contract_dict,
    image_pair_to_pair_id,
    is_colmap_native_extractor_type,
    is_extension_column,
    is_extension_table,
    make_database_version_number,
    matches_are_type_compatible,
    pair_id_to_image_pair,
)
from sceneio.errors import ContractViolation, SceneIoError
from sceneio.imagesource import ImageSourceImpl, MaterializedImage
from sceneio.mapping_input import (
    CheckpointRef,
    checkpoint_root,
    gc_checkpoints,
    latest_checkpoint,
    list_checkpoints,
    write_checkpoint,
)
from sceneio.points_binary import (
    HEADER_FMT,
    HEADER_SIZE,
    MAGIC,
    RECORD_FMT,
    RECORD_SIZE,
    Point3DRecord,
    decode_records,
    encode_all,
    read_header,
    read_record,
    write_header,
    write_record,
)

if TYPE_CHECKING:
    from sceneio import (
        data,
        formats,
        mapping,
        matching,
        testing,
    )

__version__ = "0.2.0"

# The contract namespaces are import-isolated: they are loaded lazily on
# first attribute access so that `import sceneio` alone stays cheap
# and no namespace ever depends on a sibling being imported.
_NAMESPACES = frozenset({"data", "formats", "mapping", "matching", "testing"})


def __getattr__(name: str) -> object:
    if name in _NAMESPACES:
        return importlib.import_module(f"sceneio.{name}")
    raise AttributeError(f"module 'sceneio' has no attribute {name!r}")


__all__ = [
    "COLMAP_DB_TABLES",
    "COLMAP_DB_TABLES_BY_NAME",
    "COLMAP_KNOWN_EXTRACTOR_TYPES",
    "COLMAP_KNOWN_MATCHER_TYPES",
    "CONTRACT_NAME",
    "CONTRACT_SCHEMA_VERSION",
    "DATABASE_SCHEMA_REVISION",
    "DATABASE_VERSION_NUMBER",
    "EXTENSION_COLUMNS",
    "EXTENSION_TABLES",
    "HEADER_FMT",
    "HEADER_SIZE",
    "MAGIC",
    "MAX_NUM_IMAGES",
    "RECORD_FMT",
    "RECORD_SIZE",
    "UNDEFINED_EXTRACTOR_TYPE",
    "UPSTREAM_TABLES",
    "BlobStore",
    "CheckpointRef",
    "ColumnDef",
    "ContractViolation",
    "ImageSourceImpl",
    "MaterializedImage",
    "Point3DRecord",
    "SceneIoError",
    "TableDef",
    "__version__",
    "checkpoint_root",
    "contract_dict",
    "data",
    "decode_records",
    "encode_all",
    "formats",
    "gc_checkpoints",
    "image_pair_to_pair_id",
    "is_colmap_native_extractor_type",
    "is_extension_column",
    "is_extension_table",
    "latest_checkpoint",
    "list_checkpoints",
    "make_database_version_number",
    "mapping",
    "matches_are_type_compatible",
    "matching",
    "pair_id_to_image_pair",
    "read_header",
    "read_record",
    "testing",
    "validate_sha",
    "write_checkpoint",
    "write_header",
    "write_record",
]
