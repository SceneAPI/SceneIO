"""Benchmark specifications for the buffer-backed sequence codec family."""

from __future__ import annotations

from bench.io_bench.fixtures.sequences import _y4m_fixture
from bench.io_bench.model import Spec
from bench.io_bench.oracles.sequences import (
    _y4m_oracle_read,
    _y4m_oracle_write,
)
from sceneio import _core


def build_sequence_specs(scale):
    side = max(1, int(1024 * scale**0.5))
    return [
        Spec(
            "y4m",
            lambda: _y4m_fixture(side),
            _core.write_y4m,
            _core.read_y4m,
            _y4m_oracle_write,
            _y4m_oracle_read,
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
    ]


__all__ = ["build_sequence_specs"]
