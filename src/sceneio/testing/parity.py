"""Reusable helpers for codec parity tests (see ``docs/core_architecture.md``).

Every codec test compares a record decoded by our codec against one from a
reference oracle, field by field. :func:`assert_fields_close` makes that a
couple of lines; :func:`sh_rest_channel_grouped` handles the one recurring
reshape (gsplat ``(N,K,3)`` -> the file's channel-grouped ``f_rest``).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np


def assert_fields_close(actual, expected, mapping, *, rtol=0.0, atol=0.0):
    """Assert named ndarray fields match between two record-like objects.

    ``mapping`` maps each attribute on ``actual`` to the corresponding
    attribute on ``expected`` — either a name, or a ``(name, transform)``
    pair applied to the oracle's array before comparing::

        assert_fields_close(ours, oracle, {
            "means": "means",
            "sh_rest": ("shN", sh_rest_channel_grouped),
        }, rtol=1e-5, atol=1e-6)
    """
    for actual_attr, spec in mapping.items():
        oracle_attr, fn = spec if isinstance(spec, tuple) else (spec, None)
        a = np.asarray(getattr(actual, actual_attr))
        e = np.asarray(getattr(expected, oracle_attr))
        if fn is not None:
            e = fn(e)
        np.testing.assert_allclose(
            a,
            e.reshape(a.shape) if e.shape != a.shape and e.size == a.size else e,
            rtol=rtol,
            atol=atol,
            err_msg=f"field {actual_attr!r} != oracle {oracle_attr!r}",
        )


def sh_rest_channel_grouped(shN: np.ndarray) -> np.ndarray:
    """gsplat higher-order SH ``(N,K,3)`` -> channel-grouped ``(N, 3K)``
    ``[R.. G.. B..]``, matching the PLY ``f_rest`` / SPZ layout."""
    n = shN.shape[0]
    return np.ascontiguousarray(shN.transpose(0, 2, 1).reshape(n, -1))


def roundtrip(read: Callable[[bytes], object], write: Callable[[object], bytes], obj):
    """``read(write(obj))`` for a bytes-based codec."""
    return read(write(obj))
