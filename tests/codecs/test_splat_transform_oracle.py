"""Executable cross-implementation oracle for the Gaussian splat family.

The optional oracle is PlayCanvas ``splat-transform`` 3.1.6, pinned to npm
gitHead 04b6d15b3c895136d2deba57fdb06df1d4ff3b91.  Normal local runs skip this
suite unless ``SCENEIO_SPLAT_TRANSFORM_CLI`` names the executable; the
cross-platform splat CI job installs and runs that exact package.

SceneIO writers are checked by asking the external implementation to decode
all six legacy splat formats to Gaussian PLY.  SceneIO readers are checked
against files produced by the external implementation for every nontrivial
format it writes.  Comparisons use decoded attributes because four formats
are quantized and quaternion signs are rotation-equivalent.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core

EXPECTED_VERSION = "splat-transform v3.1.6 (04b6d15)"
FORMAT_EXTENSIONS = {
    "gaussian_ply": ".ply",
    "compressed_ply": ".compressed.ply",
    "sog": ".sog",
    "ksplat": ".ksplat",
    "spz": ".spz",
    "splat": ".splat",
}
SPLAT_TRANSFORM_WRITABLE = {
    "compressed_ply": (),
    "sog": ("--gpu", "cpu", "--max-workers", "0"),
    "spz": ("--spz-version", "3"),
}


def _cloud(n: int = 67, degree: int = 2):
    """Asymmetric finite fixture that exercises every stored attribute."""
    i = np.arange(n, dtype=np.int64)
    means = np.stack(
        [
            ((i * 17) % 1009 - 504) / 64,
            ((i * 31) % 997 - 498) / 64,
            ((i * 43) % 991 - 495) / 64,
        ],
        axis=1,
    ).astype(np.float32)
    scales = np.stack(
        [
            ((i * 7) % 97 - 48) / 16,
            ((i * 11) % 89 - 44) / 16,
            ((i * 13) % 83 - 41) / 16,
        ],
        axis=1,
    ).astype(np.float32)
    quaternions = np.stack(
        [
            ((i * 3) % 31 - 15) / 32,
            ((i * 5) % 29 - 14) / 32,
            ((i * 7) % 23 - 11) / 32,
            np.where(i % 2, 1, -1) / 32,
        ],
        axis=1,
    ).astype(np.float32)
    opacities = (((i * 19) % 127 - 63) / 16).astype(np.float32)
    sh_dc = np.stack(
        [
            ((i * 23) % 137 - 68) / 32,
            ((i * 29) % 131 - 65) / 32,
            ((i * 37) % 139 - 69) / 32,
        ],
        axis=1,
    ).astype(np.float32)
    rest = (0, 9, 24, 45)[degree]
    j = np.arange(rest, dtype=np.int64)
    sh_rest = (
        ((i[:, None] * 17 + j[None, :] * 37) % 249 - 124) / 32
    ).astype(np.float32)
    return _core.gaussian_cloud(
        means,
        scales,
        quaternions,
        opacities,
        sh_dc,
        sh_rest,
    )


def _run(cli: Path, *arguments: object) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(cli), "--quiet", *(str(value) for value in arguments)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def splat_transform_cli() -> Path:
    configured = os.environ.get("SCENEIO_SPLAT_TRANSFORM_CLI")
    if not configured:
        if os.environ.get("SCENEIO_REQUIRE_SPLAT_ORACLES") == "1":
            pytest.fail(
                "SCENEIO_SPLAT_TRANSFORM_CLI is required in this oracle lane"
            )
        pytest.skip("SCENEIO_SPLAT_TRANSFORM_CLI is not configured")
    cli = Path(configured)
    assert cli.is_file(), cli
    result = subprocess.run(
        [str(cli), "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert EXPECTED_VERSION in result.stdout + result.stderr
    return cli


def _assert_same_attributes(actual, oracle, *, splat: bool = False) -> None:
    assert actual.num_gaussians == oracle.num_gaussians
    assert actual.sh_degree == oracle.sh_degree
    for field in ("means", "scales", "opacities", "sh_dc", "sh_rest"):
        np.testing.assert_allclose(
            np.asarray(getattr(actual, field)),
            np.asarray(getattr(oracle, field)),
            rtol=1e-6,
            atol=5e-7,
        )

    left = np.asarray(actual.quaternions, dtype=np.float64)
    right = np.asarray(oracle.quaternions, dtype=np.float64)
    left /= np.linalg.norm(left, axis=1, keepdims=True)
    right /= np.linalg.norm(right, axis=1, keepdims=True)
    rotation_error = 1.0 - np.abs(np.sum(left * right, axis=1))
    # The legacy .splat format stores four 8-bit quaternion components.
    tolerance = 5e-5 if splat else 1e-6
    assert float(np.max(rotation_error)) <= tolerance


def test_pinned_splat_transform_version(splat_transform_cli):
    assert splat_transform_cli.is_file()


@pytest.mark.parametrize("format_id", tuple(FORMAT_EXTENSIONS))
def test_sceneio_writers_are_readable_by_splat_transform(
    splat_transform_cli,
    tmp_path,
    format_id,
):
    source = tmp_path / f"sceneio{FORMAT_EXTENSIONS[format_id]}"
    oracle_ply = tmp_path / f"{format_id}-oracle.ply"
    sceneio.write(
        _cloud(degree=0 if format_id == "splat" else 2),
        source,
        format=format_id,
    )

    expected = sceneio.read(source, format=format_id)
    _run(splat_transform_cli, source, oracle_ply)
    oracle = sceneio.read(oracle_ply, format="gaussian_ply")

    _assert_same_attributes(expected, oracle, splat=format_id == "splat")


@pytest.mark.parametrize(
    ("format_id", "options"), tuple(SPLAT_TRANSFORM_WRITABLE.items())
)
def test_sceneio_readers_match_splat_transform_writers(
    splat_transform_cli,
    tmp_path,
    format_id,
    options,
):
    source_ply = tmp_path / "source.ply"
    external = tmp_path / f"external{FORMAT_EXTENSIONS[format_id]}"
    oracle_ply = tmp_path / "external-decoded.ply"
    sceneio.write(_cloud(), source_ply, format="gaussian_ply")

    _run(splat_transform_cli, source_ply, external, *options)
    actual = sceneio.read(external, format=format_id)
    _run(splat_transform_cli, external, oracle_ply)
    oracle = sceneio.read(oracle_ply, format="gaussian_ply")

    _assert_same_attributes(actual, oracle)
