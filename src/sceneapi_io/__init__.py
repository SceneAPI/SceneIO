"""sceneapi-io — the I/O contract package for SceneAPI.

This is a *contract*, not an implementation: it owns the wire codecs
(the ``application/x-sfm-points-v1`` binary points format), the
storage / image-source Protocols (`BlobStore`, `ImageSourceImpl`), the
on-disk data-format schemas (the extended COLMAP scene-database
contract, the ``PCMAPIN`` checkpoint helpers), and the shared error
base (`SceneIoError`).

Concrete backends (filesystem / S3 / in-memory blob stores, the
FastAPI service, the engine adapters) live in the sceneapi core and in
third-party backend packages; they depend on this package for the
interfaces and codecs they must agree on. The generated SDKs decode the
same formats defined here.

This package is a leaf: it imports nothing from ``sceneapi`` / ``app``
and depends only on the Python standard library.
"""

from __future__ import annotations

from sceneapi_io.blobstore import BlobStore, validate_sha
from sceneapi_io.colmap_db import (
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
from sceneapi_io.errors import SceneIoError
from sceneapi_io.imagesource import ImageSourceImpl, MaterializedImage
from sceneapi_io.mapping_input import (
    CheckpointRef,
    checkpoint_root,
    gc_checkpoints,
    latest_checkpoint,
    list_checkpoints,
    write_checkpoint,
)
from sceneapi_io.points_binary import (
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

__version__ = "0.1.0"

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
    "ImageSourceImpl",
    "MaterializedImage",
    "Point3DRecord",
    "SceneIoError",
    "TableDef",
    "__version__",
    "checkpoint_root",
    "contract_dict",
    "decode_records",
    "encode_all",
    "gc_checkpoints",
    "image_pair_to_pair_id",
    "is_colmap_native_extractor_type",
    "is_extension_column",
    "is_extension_table",
    "latest_checkpoint",
    "list_checkpoints",
    "make_database_version_number",
    "matches_are_type_compatible",
    "pair_id_to_image_pair",
    "read_header",
    "read_record",
    "validate_sha",
    "write_checkpoint",
    "write_header",
    "write_record",
]
