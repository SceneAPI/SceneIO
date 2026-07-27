"""Deterministic fixtures for array-family benchmark codecs."""

from __future__ import annotations

import numpy as np

from sceneio import _core


def _depth_map(h, w):
    values = np.random.default_rng(7).standard_normal((h, w)).astype(np.float32)
    return (
        _core.depth_map(
            values,
            unit="unknown",
            invalid_policy="zero",
        ),
        values,
    )


__all__ = ["_depth_map"]
