"""Error hierarchy for sceneio."""

from __future__ import annotations


class SceneIoError(Exception):
    """Base for sceneio format/codec/contract errors."""


class ContractViolation(SceneIoError):
    """A data or procedure contract was violated.

    Raised by the numpy-native datatypes in :mod:`sceneio.data` (bad
    shape, dtype, value range, or inconsistent components) and by
    conforming :mod:`sceneio.mapping` / :mod:`sceneio.matching`
    implementations when a call breaks the declared contract (for
    example a Mapper whose traits require correspondences being invoked
    with ``correspondences=None``).
    """
