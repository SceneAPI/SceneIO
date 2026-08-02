"""Repository-owned NVIDIA NCore V4 dataset support.

The public adapter is intentionally split into small modules because an NCore
sequence is a collection of typed component stores, not one tensor container.
Importing this package does not import the optional Zarr or CBOR providers.
"""

from sceneio.io._ncore.component_io import read_ncore_component
from sceneio.io._ncore.model import (
    NCoreArray,
    NCoreComponent,
    NCoreComponentData,
    NCoreDataset,
    NCoreGroup,
    NCoreSelection,
    NCoreStore,
)
from sceneio.io._ncore.schema import (
    inspect_ncore_v4,
    is_ncore_v4_directory,
    is_ncore_v4_file,
    read_ncore_v4,
)

__all__ = [
    "NCoreArray",
    "NCoreComponent",
    "NCoreComponentData",
    "NCoreDataset",
    "NCoreGroup",
    "NCoreSelection",
    "NCoreStore",
    "inspect_ncore_v4",
    "is_ncore_v4_directory",
    "is_ncore_v4_file",
    "read_ncore_component",
    "read_ncore_v4",
]
