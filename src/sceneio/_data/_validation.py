"""Internal array/scalar validation helpers for the data contracts.

Every helper raises :class:`sceneio.errors.ContractViolation` with a
precise, field-qualified message (``"DepthMap.depth: expected dtype
float32, got float64"``). Not public API — the contract types own the
messages, this module only keeps them uniform.
"""

from __future__ import annotations

import numpy as np

from sceneio.errors import ContractViolation


def _shape_desc(shape: tuple[int | None, ...]) -> str:
    return "(" + ", ".join("?" if dim is None else str(dim) for dim in shape) + ")"


def ensure_array(
    name: str,
    value: object,
    *,
    dtypes: tuple[object, ...] | None = None,
    shape: tuple[int | None, ...] | None = None,
    finite: bool = False,
) -> np.ndarray:
    """Validate ``value`` is an ndarray of the given dtype(s)/shape.

    ``shape`` entries of ``None`` are wildcard dimensions. The array is
    returned unchanged — no copies, no silent dtype conversion.
    """
    if not isinstance(value, np.ndarray):
        raise ContractViolation(f"{name}: expected numpy.ndarray, got {type(value).__name__}")
    if dtypes is not None:
        allowed = tuple(np.dtype(d) for d in dtypes)
        if value.dtype not in allowed:
            names = " or ".join(d.name for d in allowed)
            raise ContractViolation(f"{name}: expected dtype {names}, got {value.dtype.name}")
    if shape is not None:
        if value.ndim != len(shape):
            raise ContractViolation(
                f"{name}: expected a {len(shape)}-D array of shape "
                f"{_shape_desc(shape)}, got shape {value.shape}"
            )
        for axis, dim in enumerate(shape):
            if dim is not None and value.shape[axis] != dim:
                raise ContractViolation(
                    f"{name}: expected shape {_shape_desc(shape)}, got shape "
                    f"{value.shape} (axis {axis} is {value.shape[axis]}, expected {dim})"
                )
    if finite and value.size and not np.isfinite(value).all():
        raise ContractViolation(f"{name}: array contains non-finite values (NaN/Inf)")
    return value


def ensure_integer_array(
    name: str,
    value: object,
    *,
    shape: tuple[int | None, ...] | None = None,
    non_negative: bool = False,
) -> np.ndarray:
    arr = ensure_array(name, value, shape=shape)
    if not np.issubdtype(arr.dtype, np.integer):
        raise ContractViolation(f"{name}: expected an integer dtype, got {arr.dtype.name}")
    if non_negative and arr.size and int(arr.min()) < 0:
        raise ContractViolation(f"{name}: contains negative values (min {int(arr.min())})")
    return arr


def as_float64(
    name: str,
    value: object,
    shape: tuple[int | None, ...],
    *,
    finite: bool = True,
) -> np.ndarray:
    """Coerce a small numeric array (or nested sequence) to float64.

    Used for the transform types (SE3/Sim3, covariances, intrinsics
    params) where float64 is the canonical precision and the arrays are
    tiny, so a converting copy is cheap and safe.
    """
    try:
        arr = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(
            f"{name}: expected a numeric array convertible to float64, got {type(value).__name__}"
        ) from exc
    return ensure_array(name, arr, shape=shape, finite=finite)


def ensure_instance(name: str, value: object, expected: type, label: str) -> None:
    if not isinstance(value, expected):
        raise ContractViolation(f"{name}: expected {label}, got {type(value).__name__}")


def ensure_optional_instance(name: str, value: object, expected: type, label: str) -> None:
    if value is not None and not isinstance(value, expected):
        raise ContractViolation(f"{name}: expected {label} or None, got {type(value).__name__}")


def ensure_bool(name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise ContractViolation(f"{name}: expected bool, got {type(value).__name__}")


def ensure_positive_int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContractViolation(f"{name}: expected a positive int, got {value!r}")


def ensure_choice(name: str, value: object, choices: frozenset[str]) -> None:
    if value not in choices:
        raise ContractViolation(f"{name}: expected one of {sorted(choices)}, got {value!r}")
