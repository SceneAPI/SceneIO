"""Repository-owned NVIDIA NCore V4 dataset support.

The public adapter is intentionally split into small modules because an NCore
sequence is a collection of typed component stores, not one tensor container.
Importing this package does not import the optional Zarr or CBOR providers.
"""

from sceneio.io._ncore.model import (
    NCoreArray,
    NCoreComponent,
    NCoreDataset,
    NCoreSelection,
    NCoreStore,
)
from sceneio.io._ncore.schema import inspect_ncore_v4, read_ncore_v4

__all__ = [
    "NCoreArray",
    "NCoreComponent",
    "NCoreDataset",
    "NCoreSelection",
    "NCoreStore",
    "inspect_ncore_v4",
    "read_ncore_v4",
]
