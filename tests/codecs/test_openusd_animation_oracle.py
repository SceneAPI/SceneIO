"""OpenUSD 26.8 oracle for the bounded selected-time USDA profile."""

from __future__ import annotations

import importlib.metadata

import numpy as np
import pytest

import sceneio
from sceneio.io._usd import package
from tests.codecs.test_usd_animation import _ANIMATED_USDA

try:
    _USD_CORE_VERSION = importlib.metadata.version("usd-core")
except importlib.metadata.PackageNotFoundError:
    _USD_CORE_VERSION = None

try:
    from pxr import Usd, UsdGeom
except ModuleNotFoundError:
    Usd = None
    UsdGeom = None

if _USD_CORE_VERSION is None or Usd is None or UsdGeom is None:
    _OPENUSD_SKIP_REASON = (
        "OpenUSD oracle is optional; install usd-core==26.8 for this suite"
    )
elif _USD_CORE_VERSION != "26.8":
    _OPENUSD_SKIP_REASON = (
        "OpenUSD oracle suite is pinned to usd-core==26.8; "
        f"found {_USD_CORE_VERSION}"
    )
else:
    _OPENUSD_SKIP_REASON = None

pytestmark = pytest.mark.skipif(
    _OPENUSD_SKIP_REASON is not None,
    reason=_OPENUSD_SKIP_REASON or "",
)


def _fixture(tmp_path, suffix):
    source = tmp_path / "oracle.usda"
    source.write_text(_ANIMATED_USDA, encoding="utf-8")
    if suffix == ".usda":
        return source
    destination = tmp_path / "oracle.usdz"
    package.write_usdz_archive(source, destination)
    return destination


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
@pytest.mark.parametrize(
    "time",
    [-7.25, -3.0, -2.5, -0.25, 0.0, 1.0, 2.125, 4.5, 4.75, 9.5],
)
def test_sceneio_selected_time_matches_openusd_26_8(
    tmp_path,
    suffix,
    time,
):
    path = _fixture(tmp_path, suffix)
    oracle_stage = Usd.Stage.Open(str(path))
    assert oracle_stage
    prim = oracle_stage.GetPrimAtPath("/World")
    assert prim

    oracle_matrix = np.asarray(
        UsdGeom.Xformable(prim).GetLocalTransformation(Usd.TimeCode(time)),
        dtype=np.float64,
    )
    oracle_visibility = str(
        UsdGeom.Imageable(prim).GetVisibilityAttr().Get(Usd.TimeCode(time))
    )
    actual = sceneio.read_scene(path, time=time)

    np.testing.assert_allclose(
        actual.node_local_transforms[0],
        oracle_matrix,
        rtol=0,
        atol=1e-14,
    )
    assert actual.node_visibility[0] == oracle_visibility


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
def test_openusd_observes_the_pinned_authored_samples(tmp_path, suffix):
    path = _fixture(tmp_path, suffix)
    oracle_stage = Usd.Stage.Open(str(path))
    prim = oracle_stage.GetPrimAtPath("/World")

    assert prim.GetAttribute("xformOp:transform").GetTimeSamples() == [
        -2.5,
        1.0,
        4.75,
    ]
    assert prim.GetAttribute("visibility").GetTimeSamples() == [
        -3.0,
        0.0,
        4.5,
    ]
    assert float(oracle_stage.GetTimeCodesPerSecond()) == 30.0
