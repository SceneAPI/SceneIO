"""Single source of truth for SceneIO's COLMAP camera-model vocabulary.

This module is deliberately private and stdlib-only.  Python contracts and
COLMAP adapters import the tables below directly; CMake runs
``tools/generate_camera_models.py`` against the same manifest to build the C++
``colmap_model_info`` switch.  Keep model ids contiguous and parameter names in
their persisted order.
"""

from __future__ import annotations

from types import MappingProxyType

CAMERA_MODEL_SCHEMA_VERSION = 1

# (persisted id, persisted name, ordered persisted parameter names)
CAMERA_MODEL_SPECS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (0, "SIMPLE_PINHOLE", ("f", "cx", "cy")),
    (1, "PINHOLE", ("fx", "fy", "cx", "cy")),
    (2, "SIMPLE_RADIAL", ("f", "cx", "cy", "k")),
    (3, "RADIAL", ("f", "cx", "cy", "k1", "k2")),
    (4, "OPENCV", ("fx", "fy", "cx", "cy", "k1", "k2", "p1", "p2")),
    (
        5,
        "OPENCV_FISHEYE",
        ("fx", "fy", "cx", "cy", "k1", "k2", "k3", "k4"),
    ),
    (
        6,
        "FULL_OPENCV",
        ("fx", "fy", "cx", "cy", "k1", "k2", "p1", "p2", "k3", "k4", "k5", "k6"),
    ),
    (7, "FOV", ("fx", "fy", "cx", "cy", "omega")),
    (8, "SIMPLE_RADIAL_FISHEYE", ("f", "cx", "cy", "k")),
    (9, "RADIAL_FISHEYE", ("f", "cx", "cy", "k1", "k2")),
    (
        10,
        "THIN_PRISM_FISHEYE",
        ("fx", "fy", "cx", "cy", "k1", "k2", "p1", "p2", "k3", "k4", "sx1", "sy1"),
    ),
    (
        11,
        "RAD_TAN_THIN_PRISM_FISHEYE",
        (
            "fx",
            "fy",
            "cx",
            "cy",
            "k0",
            "k1",
            "k2",
            "k3",
            "k4",
            "k5",
            "p0",
            "p1",
            "s0",
            "s1",
            "s2",
            "s3",
        ),
    ),
    (12, "SIMPLE_DIVISION", ("f", "cx", "cy", "k")),
    (13, "DIVISION", ("fx", "fy", "cx", "cy", "k")),
    (14, "SIMPLE_FISHEYE", ("f", "cx", "cy")),
    (15, "FISHEYE", ("fx", "fy", "cx", "cy")),
    (16, "EUCM", ("fx", "fy", "cx", "cy", "alpha", "beta")),
    (17, "EQUIRECTANGULAR", ("w", "h")),
)

_EXPECTED_IDS = tuple(range(len(CAMERA_MODEL_SPECS)))
if tuple(spec[0] for spec in CAMERA_MODEL_SPECS) != _EXPECTED_IDS:
    raise RuntimeError("camera-model ids must be contiguous and ordered from zero")
if len({spec[1] for spec in CAMERA_MODEL_SPECS}) != len(CAMERA_MODEL_SPECS):
    raise RuntimeError("camera-model names must be unique")
if any(not params or len(params) != len(set(params)) for _, _, params in CAMERA_MODEL_SPECS):
    raise RuntimeError("camera-model parameter names must be nonempty and unique per model")

CAMERA_MODEL_NAMES = tuple(name for _, name, _ in CAMERA_MODEL_SPECS)
CAMERA_MODEL_PARAMETER_NAMES = tuple(params for _, _, params in CAMERA_MODEL_SPECS)
CAMERA_MODEL_PARAMETER_COUNTS = tuple(len(params) for params in CAMERA_MODEL_PARAMETER_NAMES)
CAMERA_MODEL_IDS_BY_NAME = MappingProxyType(
    {name: model_id for model_id, name, _ in CAMERA_MODEL_SPECS}
)
CAMERA_MODEL_PARAMETER_COUNTS_BY_NAME = MappingProxyType(
    {name: len(params) for _, name, params in CAMERA_MODEL_SPECS}
)

__all__ = [
    "CAMERA_MODEL_IDS_BY_NAME",
    "CAMERA_MODEL_NAMES",
    "CAMERA_MODEL_PARAMETER_COUNTS",
    "CAMERA_MODEL_PARAMETER_COUNTS_BY_NAME",
    "CAMERA_MODEL_PARAMETER_NAMES",
    "CAMERA_MODEL_SCHEMA_VERSION",
    "CAMERA_MODEL_SPECS",
]
