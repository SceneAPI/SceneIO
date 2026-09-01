"""Benchmark specifications for the buffer-backed sequence codec family."""

from __future__ import annotations

from bench.io_bench.fixtures.sequences import (
    _animated_webp_fixture,
    _apng_fixture,
    _ivf_fixture,
    _mjpeg_fixture,
    _theora_fixture,
    _webm_fixture,
    _y4m_fixture,
)
from bench.io_bench.model import Spec
from bench.io_bench.oracles.sequences import (
    _animated_webp_oracle_read,
    _animated_webp_oracle_write,
    _apng_oracle_read,
    _apng_oracle_write,
    _webm_oracle_read,
    _webm_oracle_write,
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
        Spec(
            "webm",
            lambda: _webm_fixture(side),
            _core.write_webm,
            _core.read_webm,
            _webm_oracle_write,
            _webm_oracle_read,
            lambda rec, p: p["frames"].nbytes,
        ),
        Spec(
            "ivf",
            lambda: _ivf_fixture(side),
            _core.write_ivf,
            _core.read_ivf,
            None,
            None,
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "mjpeg",
            lambda: _mjpeg_fixture(side),
            _core.write_mjpeg,
            _core.read_mjpeg,
            None,
            None,
            lambda rec, p: p["frames"].nbytes,
        ),
        Spec(
            "theora",
            lambda: _theora_fixture(side),
            _core.write_theora,
            _core.read_theora,
            None,
            None,
            lambda rec, p: sum(value.nbytes for value in p.values()),
        ),
        Spec(
            "animated_webp",
            lambda: _animated_webp_fixture(side),
            _core.write_animated_webp,
            _core.read_animated_webp,
            _animated_webp_oracle_write,
            _animated_webp_oracle_read,
            lambda rec, p: p["frames"].nbytes,
        ),
        Spec(
            "apng",
            lambda: _apng_fixture(side),
            _core.write_apng,
            _core.read_apng,
            _apng_oracle_write,
            _apng_oracle_read,
            lambda rec, p: p["frames"].nbytes,
        ),
    ]


__all__ = ["build_sequence_specs"]
