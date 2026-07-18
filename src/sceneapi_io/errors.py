"""Error hierarchy for sceneapi-io."""

from __future__ import annotations


class SceneIoError(Exception):
    """Base for sceneapi-io format/codec/contract errors."""


class ContractViolation(SceneIoError):
    """A data or procedure contract was violated.

    Raised by the numpy-native datatypes in :mod:`sceneapi_io.data` (bad
    shape, dtype, value range, or inconsistent components) and by
    conforming :mod:`sceneapi_io.mapping` / :mod:`sceneapi_io.matching`
    implementations when a call breaks the declared contract (for
    example a Mapper whose traits require correspondences being invoked
    with ``correspondences=None``).
    """
